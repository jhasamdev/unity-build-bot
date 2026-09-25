"""Git polling + workspace sync: detect new commits and pull cleanly."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

from unity_build_bot.config import GitConfig
from unity_build_bot.process_runner import run_streaming

logger = logging.getLogger("unity_build_bot")


def _run(cmd: list[str], cwd: Path | None = None):
    return run_streaming(cmd, cwd=cwd)


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


def remote_head_sha(git_cfg: GitConfig) -> str:
    """Return the current remote SHA for the configured branch, without cloning."""
    result = _run(["git", "ls-remote", git_cfg.repo_url, f"refs/heads/{git_cfg.branch}"])
    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote failed: {result.stderr.strip()}")
    line = result.stdout.strip()
    if not line:
        raise RuntimeError(
            f"Branch '{git_cfg.branch}' not found on {git_cfg.repo_url}"
        )
    return line.split()[0]


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
    protected_roots = {
        Path(workspace_root.anchor),
        Path.home().resolve(),
        Path.cwd().resolve(),
    }
    if workspace_root in protected_roots:
        raise RuntimeError(f"Refusing to clear protected directory: {workspace_root}")
    if workspace_root not in workdir.parents:
        raise RuntimeError(
            f"Git work directory {workdir} must be inside workspace root {workspace_root}"
        )

    logger.info("Clearing complete workspace %s", workspace_root)
    _clear_workspace(workspace_root)

    logger.info("Cloning %s into %s", git_cfg.repo_url, workdir)
    result = _run([
        "git", "clone", "--progress", "--branch", git_cfg.branch,
        git_cfg.repo_url, str(workdir),
    ])
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr.strip()}")
