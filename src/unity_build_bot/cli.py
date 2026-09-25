"""Entry point: single-pass job intended to be run on a schedule
(cron / launchd / Task Scheduler). Checks for a new commit, and if found,
pulls, builds with Unity, uploads to Steam, and records state + logs.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from unity_build_bot import git_watcher, steam_uploader, unity_builder, version_file
from unity_build_bot.config import load_config
from unity_build_bot.logging_utils import setup_logging
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


def run(config_path: str) -> int:
    cfg = load_config(config_path)
    logger = setup_logging(
        cfg.logging.log_dir,
        cfg.logging.level,
        cfg.logging.show_activity_window,
    )
    state = State.load(cfg.state.state_file)

    try:
        if cfg.job.mode == "upload_only":
            logger.info("Job mode is upload_only; skipping Git sync and Unity build")
            return upload_existing_outputs(cfg, logger)

        new_sha = git_watcher.has_new_commit(cfg.git, state.last_built_sha)
        if new_sha is None:
            logger.info("No new commits on %s, nothing to do.", cfg.git.branch)
            return 0

        logger.info("New commit detected: %s (previous: %s)", new_sha, state.last_built_sha)
        git_watcher.sync_workdir(cfg.git)

        version_path = cfg.git.workdir / cfg.versioning.version_file
        version = version_file.read_version(version_path)
        if cfg.versioning.auto_increment:
            version = version_file.bump_version(version, cfg.versioning.bump_part)
        logger.info("Building version %s", version)

        content_roots = {}
        for build_cfg in cfg.unity.builds:
            if not build_cfg.enabled:
                logger.info("Skipping disabled build %s", build_cfg.id)
                continue
            unity_builder.build(cfg.unity, build_cfg, cfg.git.workdir, version)
            content_roots[build_cfg.id] = build_cfg.output_subdir
        steam_uploader.upload(cfg.steam, content_roots, cfg.git.workdir)

        if cfg.versioning.auto_increment:
            version_file.write_version(version_path, version)

        state.last_built_sha = new_sha
        state.last_version = version
        state.last_status = "success"
        state.last_run_at = datetime.now(timezone.utc).isoformat()
        state.save(cfg.state.state_file)
        logger.info("Run complete: version=%s sha=%s", version, new_sha)
        return 0

    except Exception as exc:  # noqa: BLE001 - top-level job boundary
        logger.exception("Run failed: %s", exc)
        state.last_status = f"failed: {exc}"
        state.last_run_at = datetime.now(timezone.utc).isoformat()
        state.save(cfg.state.state_file)
        return 1


def upload(config_path: str) -> int:
    cfg = load_config(config_path)
    logger = setup_logging(
        cfg.logging.log_dir,
        cfg.logging.level,
        cfg.logging.show_activity_window,
    )

    try:
        return upload_existing_outputs(cfg, logger)
    except Exception as exc:  # noqa: BLE001 - top-level job boundary
        logger.exception("Upload-only run failed: %s", exc)
        return 1


def upload_existing_outputs(cfg, logger: logging.Logger) -> int:
    content_roots = _content_roots_from_enabled_builds(cfg)
    _validate_content_roots(content_roots)
    logger.info("Uploading existing build outputs without running Unity")
    steam_uploader.upload(cfg.steam, content_roots, cfg.git.workdir)
    logger.info("Upload-only run complete")
    return 0


def status(config_path: str) -> int:
    cfg = load_config(config_path)
    state = State.load(cfg.state.state_file)
    print(f"last_built_sha: {state.last_built_sha}")
    print(f"last_version:   {state.last_version}")
    print(f"last_status:    {state.last_status}")
    print(f"last_run_at:    {state.last_run_at}")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")

    parser = argparse.ArgumentParser(prog="unity-build-bot", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Check for a new commit and build/upload if found", parents=[common])
    sub.add_parser("upload", help="Upload existing build outputs without syncing or building", parents=[common])
    sub.add_parser("status", help="Print last recorded run state", parents=[common])

    args = parser.parse_args(argv)

    if args.command == "run":
        return run(args.config)
    if args.command == "upload":
        return upload(args.config)
    if args.command == "status":
        return status(args.config)

    logging.getLogger("unity_build_bot").error("Unknown command: %s", args.command)
    return 2


if __name__ == "__main__":
    sys.exit(main())
