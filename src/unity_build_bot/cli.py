"""Entry point: single-pass job intended to be run on a schedule
(cron / launchd / Task Scheduler). Checks for a new commit, and if found,
pulls, builds with Unity, uploads to Steam, and records state + logs.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from unity_build_bot import git_watcher, steam_uploader, unity_builder, version_file
from unity_build_bot.config import load_config
from unity_build_bot.logging_utils import setup_logging
from unity_build_bot.notifier import (
    RunSummary,
    build_machine_details,
    repo_name_from_url,
    send_email,
    should_notify,
)
from unity_build_bot.run_lock import RunLock
from unity_build_bot.state import State


def _content_roots_from_enabled_builds(cfg) -> dict[str, Path]:
    return {
        build_cfg.id: build_cfg.output_subdir
        for build_cfg in cfg.unity.builds
        if build_cfg.enabled
    }


def _validate_content_roots(content_roots: dict[str, Path]) -> None:
    missing = [
        f"{build_id}: {content_root}"
        for build_id, content_root in content_roots.items()
        if not content_root.is_dir()
    ]
    if missing:
        raise RuntimeError(
            "Cannot upload because build output is missing: " + ", ".join(missing)
        )


def _configured_secrets(cfg) -> tuple[str, ...]:
    secrets = []
    git_token = getattr(cfg.git, "auth_token", None)
    if git_token:
        secrets.append(git_token)
    notifications = getattr(cfg, "notifications", None)
    smtp_cfg = getattr(notifications, "smtp", None)
    smtp_password = getattr(smtp_cfg, "password", None)
    if smtp_password:
        secrets.append(smtp_password)
    return tuple(secrets)


def _log_file_from_logger(logger: logging.Logger) -> Path | None:
    log_file = getattr(logger, "unity_build_bot_log_file", None)
    return log_file if isinstance(log_file, Path) else None


def _build_summary(
    cfg,
    logger: logging.Logger,
    start_time: datetime,
    end_time: datetime,
    *,
    status: str,
    state: State | None,
    upload_result: steam_uploader.UploadResult | None = None,
    error_stage: str = "",
    error_message: str = "",
) -> RunSummary:
    git_cfg = getattr(cfg, "git", None)
    unity_cfg = getattr(cfg, "unity", None)
    versioning_cfg = getattr(cfg, "versioning", None)
    job_cfg = getattr(cfg, "job", None)
    steam_cfg = getattr(cfg, "steam", None)
    commit_sha = (
        state.last_built_sha
        if state and state.last_built_sha
        else "unknown"
    )
    short_sha_length = getattr(versioning_cfg, "short_commit_hash_length", 7)
    short_sha = (
        commit_sha[:short_sha_length]
        if commit_sha != "unknown"
        else "unknown"
    )
    version = state.last_version if state and state.last_version else "unknown"
    targets = ",".join(
        build_cfg.id
        for build_cfg in getattr(unity_cfg, "builds", [])
        if build_cfg.enabled
    ) or "unknown"
    return RunSummary(
        status=status,
        job_mode=getattr(job_cfg, "mode", "upload_only"),
        repo_url=getattr(git_cfg, "repo_url", "unknown"),
        repo_name=repo_name_from_url(getattr(git_cfg, "repo_url", "unknown")),
        branch=state.last_branch if state and state.last_branch else getattr(git_cfg, "branch", "unknown"),
        commit_sha=commit_sha,
        short_sha=short_sha,
        version=version,
        targets=targets,
        steam_app_id=getattr(steam_cfg, "app_id", "unknown"),
        steam_build_id=upload_result.build_id if upload_result else "unknown",
        started_at=start_time,
        ended_at=end_time,
        duration_seconds=max((end_time - start_time).total_seconds(), 0.0),
        machine=build_machine_details(
            getattr(getattr(cfg, "notifications", None), "machine_label", "")
        ),
        log_file=_log_file_from_logger(logger),
        error_stage=error_stage,
        error_message=error_message,
    )


def _send_notification(cfg, logger: logging.Logger, summary: RunSummary, secrets: tuple[str, ...]) -> None:
    notifications = getattr(cfg, "notifications", None)
    if not should_notify(notifications, summary.status):
        return
    try:
        send_email(notifications, summary, secrets=secrets)
    except Exception as exc:  # noqa: BLE001 - notifications must not change job status
        logger.exception("Notification delivery failed: %s", exc)


def run(config_path: str) -> int:
    cfg = load_config(config_path)
    secrets = _configured_secrets(cfg)
    logger = setup_logging(
        cfg.logging.log_dir,
        cfg.logging.level,
        cfg.logging.show_activity_window,
        secrets=secrets,
    )
    start_time = datetime.now(timezone.utc)
    run_lock = RunLock(cfg.state.state_file.parent / ".run.lock")
    if not run_lock.acquire():
        logger.warning("Another bot run is active; skipping this scheduled run")
        return 0

    try:
        logger.info("Run started (mode=%s, branch=%s)", cfg.job.mode, cfg.git.branch)
        stage = "State load"
        state = State()
        try:
            state = State.load(cfg.state.state_file)
            if cfg.job.mode == "upload_only":
                stage = "Upload-only run"
                logger.info("Job mode is upload_only; skipping Git sync and Unity build")
                upload_result = upload_existing_outputs(cfg, logger, state)
                end_time = datetime.now(timezone.utc)
                _send_notification(
                    cfg,
                    logger,
                    _build_summary(
                        cfg,
                        logger,
                        start_time,
                        end_time,
                        status="success",
                        state=state,
                        upload_result=upload_result,
                    ),
                    secrets,
                )
                return 0

            stage = "Git check"
            comparison_sha = state.last_built_sha
            if state.last_status and state.last_status.startswith("failed:"):
                comparison_sha = None
            if getattr(state, "last_branch", None) not in {None, cfg.git.branch}:
                comparison_sha = None

            logger.info("Git check started (branch=%s)", cfg.git.branch)
            new_sha = git_watcher.has_new_commit(cfg.git, comparison_sha)
            logger.info("Git check finished (new_commit=%s)", new_sha is not None)
            if new_sha is None:
                logger.info("Run finished: no new commits on %s", cfg.git.branch)
                return 0

            logger.info(
                "New commit detected: %s (previous: %s)",
                new_sha,
                state.last_built_sha,
            )
            state.last_built_sha = new_sha
            state.last_branch = cfg.git.branch
            stage = "Workspace sync"
            logger.info("Workspace sync started")
            git_watcher.sync_workdir(cfg.git)
            logger.info("Workspace sync finished")

            stage = "Version preparation"
            logger.info("Version preparation started")
            version_path = cfg.git.workdir / cfg.versioning.version_file
            base_version = version_file.read_version(version_path)
            if cfg.versioning.auto_increment:
                base_version = version_file.bump_version(
                    base_version, cfg.versioning.bump_part
                )
            version = base_version
            if cfg.versioning.append_short_commit_hash:
                version = version_file.append_short_commit_hash(
                    base_version,
                    new_sha,
                    cfg.versioning.short_commit_hash_length,
                )
            state.last_version = version
            logger.info("Version preparation finished (version=%s)", version)

            content_roots = {}
            for build_cfg in cfg.unity.builds:
                if not build_cfg.enabled:
                    logger.debug("Skipping disabled build %s", build_cfg.id)
                    continue
                stage = f"Unity build {build_cfg.id}"
                unity_builder.build(cfg.unity, build_cfg, cfg.git.workdir, version)
                content_roots[build_cfg.id] = build_cfg.output_subdir
            stage = "Steam upload"
            upload_result = _upload_with_retries(
                cfg,
                logger,
                content_roots,
                cfg.git.workdir,
                build_metadata={
                    "version": version,
                    "branch": cfg.git.branch,
                    "short_sha": new_sha[:cfg.versioning.short_commit_hash_length],
                    "targets": ",".join(content_roots),
                },
            )

            if cfg.versioning.auto_increment:
                stage = "Version file update"
                logger.info("Version file update started")
                version_file.write_version(version_path, base_version)
                logger.info("Version file update finished")

            stage = "State save"
            state.last_status = "success"
            state.last_run_at = datetime.now(timezone.utc).isoformat()
            state.save(cfg.state.state_file)
            logger.info("Run finished successfully: version=%s sha=%s", version, new_sha)
            end_time = datetime.now(timezone.utc)
            _send_notification(
                cfg,
                logger,
                _build_summary(
                    cfg,
                    logger,
                    start_time,
                    end_time,
                    status="success",
                    state=state,
                    upload_result=upload_result,
                ),
                secrets,
            )
            return 0

        except Exception as exc:  # noqa: BLE001 - top-level job boundary
            logger.exception("%s failed; run aborted: %s", stage, exc)
            state.last_status = f"failed: {exc}"
            state.last_run_at = datetime.now(timezone.utc).isoformat()
            state.save(cfg.state.state_file)
            end_time = datetime.now(timezone.utc)
            _send_notification(
                cfg,
                logger,
                _build_summary(
                    cfg,
                    logger,
                    start_time,
                    end_time,
                    status="failure",
                    state=state,
                    error_stage=stage,
                    error_message=str(exc),
                ),
                secrets,
            )
            return 1
        finally:
            try:
                logger.info("Workspace cleanup started")
                git_watcher.remove_workspace(cfg.git.workspace_root)
                logger.info("Workspace cleanup finished: %s", cfg.git.workspace_root)
            except Exception as exc:  # noqa: BLE001 - cleanup must not hide run result
                logger.exception("Workspace cleanup failed: %s", exc)
    finally:
        run_lock.release()


def _upload_with_retries(cfg, logger, content_roots, workdir, build_metadata):
    job = getattr(cfg, "job", None)
    attempts = getattr(job, "steam_upload_retries", 3) + 1
    delay = getattr(job, "steam_upload_retry_delay_seconds", 30)
    for attempt in range(1, attempts + 1):
        try:
            return steam_uploader.upload(
                cfg.steam, content_roots, workdir, build_metadata=build_metadata
            )
        except Exception as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "Steam upload attempt %s/%s failed (%s); retrying in %ss",
                attempt,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)


def upload(config_path: str) -> int:
    cfg = load_config(config_path)
    secrets = _configured_secrets(cfg)
    logger = setup_logging(
        cfg.logging.log_dir,
        cfg.logging.level,
        cfg.logging.show_activity_window,
        secrets=secrets,
    )
    start_time = datetime.now(timezone.utc)

    try:
        logger.info("Upload-only run started")
        state = State.load(cfg.state.state_file)
        upload_result = upload_existing_outputs(cfg, logger, state)
        end_time = datetime.now(timezone.utc)
        _send_notification(
            cfg,
            logger,
            _build_summary(
                cfg,
                logger,
                start_time,
                end_time,
                status="success",
                state=state,
                upload_result=upload_result,
            ),
            secrets,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level job boundary
        logger.exception("Upload-only run failed: %s", exc)
        end_time = datetime.now(timezone.utc)
        _send_notification(
            cfg,
            logger,
            _build_summary(
                cfg,
                logger,
                start_time,
                end_time,
                status="failure",
                state=None,
                error_stage="Upload-only run",
                error_message=str(exc),
            ),
            secrets,
        )
        return 1


def upload_existing_outputs(
    cfg,
    logger: logging.Logger,
    state: State | None = None,
) -> steam_uploader.UploadResult:
    content_roots = _content_roots_from_enabled_builds(cfg)
    logger.info(
        "Upload context (branch=%s, sha=%s)",
        state.last_branch if state and state.last_branch else cfg.git.branch,
        state.last_built_sha if state and state.last_built_sha else "<unknown>",
    )
    logger.info("Build output validation started")
    _validate_content_roots(content_roots)
    logger.info("Build output validation finished")
    logger.info("Uploading existing build outputs without running Unity")
    commit_sha = state.last_built_sha if state else None
    upload_result = _upload_with_retries(
        cfg,
        logger,
        content_roots,
        cfg.git.workdir,
        build_metadata={
            "version": state.last_version if state and state.last_version else "unknown",
            "branch": state.last_branch if state and state.last_branch else cfg.git.branch,
            "short_sha": (
                commit_sha[:cfg.versioning.short_commit_hash_length]
                if commit_sha else "unknown"
            ),
            "targets": ",".join(content_roots),
        },
    )
    logger.info("Upload-only run complete")
    return upload_result


def status(config_path: str) -> int:
    cfg = load_config(config_path)
    state = State.load(cfg.state.state_file)
    print(f"last_built_sha: {state.last_built_sha}")
    print(f"last_version:   {state.last_version}")
    print(f"last_branch:    {state.last_branch}")
    print(f"last_status:    {state.last_status}")
    print(f"last_run_at:    {state.last_run_at}")
    return 0


def doctor(config_path: str) -> int:
    try:
        cfg = load_config(config_path)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] Configuration: {exc}")
        return 1

    failed = False

    def report(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        failed |= not ok
        state = "OK" if ok else "FAIL"
        suffix = f" ({detail})" if detail else ""
        print(f"[{state}] {label}{suffix}")

    try:
        git_watcher.validate_workspace_root(cfg.git.workspace_root)
    except RuntimeError as exc:
        report("Workspace cleanup target", False, str(exc))
    else:
        report("Workspace cleanup target", True, str(cfg.git.workspace_root))

    if cfg.job.mode != "upload_only":
        git_path = shutil.which("git")
        report("Git executable", git_path is not None, git_path or "not found on PATH")
        if git_path:
            try:
                git_watcher.remote_head_sha(cfg.git)
            except (OSError, RuntimeError) as exc:
                report("Git remote", False, str(exc))
            else:
                report("Git remote", True, f"{cfg.git.repo_url} ({cfg.git.branch})")
        report(
            "Unity Editor",
            cfg.unity.executable_path.is_file(),
            str(cfg.unity.executable_path),
        )

    report("SteamCMD", cfg.steam.steamcmd_path.is_file(), str(cfg.steam.steamcmd_path))
    report(
        "Steam login session",
        cfg.steam.config_vdf_path.is_file(),
        str(cfg.steam.config_vdf_path),
    )

    if cfg.job.mode == "upload_only":
        for build_cfg in cfg.unity.builds:
            if build_cfg.enabled:
                report(
                    f"Build output {build_cfg.id}",
                    build_cfg.output_subdir.is_dir(),
                    str(build_cfg.output_subdir),
                )

    if failed:
        print("Setup checks failed. Fix the items marked FAIL and run doctor again.")
        return 1
    print("Setup checks passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")

    parser = argparse.ArgumentParser(prog="unity-build-bot", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Check for a new commit and build/upload if found", parents=[common])
    sub.add_parser("upload", help="Upload existing build outputs without syncing or building", parents=[common])
    sub.add_parser("status", help="Print last recorded run state", parents=[common])
    sub.add_parser("doctor", help="Check configuration and required setup", parents=[common])

    args = parser.parse_args(argv)

    if args.command == "run":
        return run(args.config)
    if args.command == "upload":
        return upload(args.config)
    if args.command == "status":
        return status(args.config)
    if args.command == "doctor":
        return doctor(args.config)

    logging.getLogger("unity_build_bot").error("Unknown command: %s", args.command)
    return 2


if __name__ == "__main__":
    sys.exit(main())
