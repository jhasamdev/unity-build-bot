"""Git polling + workspace sync: detect new commits and pull cleanly."""
from __future__ import annotations

import base64
import logging
import os
import shutil
from pathlib import Path
from uuid import uuid4

from unity_build_bot.config import GitConfig
from unity_build_bot.process_runner import run_streaming

logger = logging.getLogger("unity_build_bot")


def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None):
    return run_streaming(cmd, cwd=cwd, env=env)


def _git_env(git_cfg: GitConfig) -> dict[str, str] | None:
    if not git_cfg.auth_token:
        return None
    env = os.environ.copy()
    config_count = int(env.get("GIT_CONFIG_COUNT", "0"))
    auth_value = base64.b64encode(
        f"x-access-token:{git_cfg.auth_token}".encode()
    ).decode("ascii")
    env[f"GIT_CONFIG_KEY_{config_count}"] = "http.extraheader"
    env[f"GIT_CONFIG_VALUE_{config_count}"] = f"AUTHORIZATION: basic {auth_value}"
    env["GIT_CONFIG_COUNT"] = str(config_count + 1)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(cmd: list[str], git_cfg: GitConfig):
    env = _git_env(git_cfg)
    if env is None:
        return _run(cmd)
    return _run(cmd, env=env)


def _clear_workspace(workspace_root: Path) -> None:
    if workspace_root.is_dir():
        cleanup_root = workspace_root.with_name(
            f".{workspace_root.name}.cleanup-{uuid4().hex}"
        )
        workspace_root.rename(cleanup_root)
        workspace_root.mkdir(parents=True)
        shutil.rmtree(cleanup_root)
        return
    if workspace_root.exists():
        workspace_root.unlink()
    workspace_root.mkdir(parents=True)


def remove_workspace(workspace_root: Path) -> None:
    """Remove the complete workspace after a build run."""
    workspace_root = workspace_root.resolve()
    validate_workspace_root(workspace_root)
    if workspace_root.is_dir():
        cleanup_root = workspace_root.with_name(
            f".{workspace_root.name}.cleanup-{uuid4().hex}"
        )
        workspace_root.rename(cleanup_root)
        shutil.rmtree(cleanup_root)
        return
    if workspace_root.exists():
        workspace_root.unlink()


def validate_workspace_root(workspace_root: Path) -> None:
    workspace_root = workspace_root.resolve()
    protected_paths = {
        Path(workspace_root.anchor),
        Path.home().resolve(),
        Path.cwd().resolve(),
        Path(__file__).resolve(),
    }
    for protected_path in protected_paths:
        if workspace_root == protected_path or workspace_root in protected_path.parents:
            raise RuntimeError(
                f"Refusing to clear protected directory or its parent: {workspace_root}"
            )


def remote_head_sha(git_cfg: GitConfig) -> str:
    """Return the current remote SHA for the configured branch, without cloning."""
    result = _run_git(
        ["git", "ls-remote", git_cfg.repo_url, f"refs/heads/{git_cfg.branch}"],
        git_cfg,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote failed: {(result.stdout or result.stderr).strip()}")
    line = result.stdout.strip()
    if not line:
        raise RuntimeError(
            f"Branch '{git_cfg.branch}' not found on {git_cfg.repo_url}"
        )
    sha = line.split()[0]
    logger.info("Git remote head (branch=%s, sha=%s)", git_cfg.branch, sha)
    return sha


def has_new_commit(git_cfg: GitConfig, last_built_sha: str | None) -> str | None:
    """Return the new SHA if it differs from last_built_sha, else None."""
    sha = remote_head_sha(git_cfg)
    if sha != last_built_sha:
        return sha
    return None


def sync_workdir(git_cfg: GitConfig) -> None:
    """Clear the complete workspace and clone a fresh copy of the branch."""
    workdir = git_cfg.workdir.resolve()
    workspace_root = git_cfg.workspace_root.resolve()
    validate_workspace_root(workspace_root)
    if workspace_root not in workdir.parents:
        raise RuntimeError(
            f"Git work directory {workdir} must be inside workspace root {workspace_root}"
        )

    logger.info("Clearing complete workspace %s", workspace_root)
    _clear_workspace(workspace_root)

    logger.info("Cloning repository into %s", workdir)
    result = _run_git(
        [
            "git", "clone", "--progress", "--branch", git_cfg.branch,
            git_cfg.repo_url, str(workdir),
        ],
        git_cfg,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {(result.stdout or result.stderr).strip()}")
