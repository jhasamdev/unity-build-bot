"""Git polling + workspace sync: detect new commits and pull cleanly."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from unity_build_bot.config import GitConfig

logger = logging.getLogger("unity_build_bot")


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    print(f"\n[EJECUTANDO COMANDO]: {' '.join(cmd)} (en directorio: {cwd or 'actual'})\n")
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


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
    """Clone if needed, otherwise fetch + hard reset + clean to match origin/branch."""
    workdir = git_cfg.workdir
    if not (workdir / ".git").is_dir():
        workdir.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning %s into %s", git_cfg.repo_url, workdir)
        result = _run(["git", "clone", "--branch", git_cfg.branch, git_cfg.repo_url, str(workdir)])
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")
        return

    logger.info("Fetching latest changes in %s", workdir)
    for cmd in (
        ["git", "fetch", "origin", git_cfg.branch],
        ["git", "reset", "--hard", f"origin/{git_cfg.branch}"],
        ["git", "clean", "-xdf"],
    ):
        result = _run(cmd, cwd=workdir)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
