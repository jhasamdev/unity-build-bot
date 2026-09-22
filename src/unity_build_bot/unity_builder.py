"""Invoke the Unity Editor in batch mode to produce a build."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from unity_build_bot.config import UnityConfig

logger = logging.getLogger("unity_build_bot")


def build(unity_cfg: UnityConfig, repo_workdir: Path, version: str) -> None:
    project_path = (repo_workdir / unity_cfg.project_subpath).resolve()
    output_dir = unity_cfg.output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)
    editor_log = output_dir / "unity_editor.log"

    cmd = [
        str(unity_cfg.executable_path),
        "-batchmode",
        "-quit",
        "-nographics",
        "-projectPath", str(project_path),
        "-executeMethod", unity_cfg.build_method,
        "-buildTarget", unity_cfg.build_target,
        "-customBuildOutput", str(output_dir),
        "-customBuildVersion", version,
        "-customBuildName", unity_cfg.build_name,
        "-logFile", str(editor_log),
        *unity_cfg.extra_args,
    ]

    logger.info("Starting Unity build (target=%s, version=%s)", unity_cfg.build_target, version)
    logger.debug("Unity command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        tail = ""
        if editor_log.is_file():
            tail = "\n".join(editor_log.read_text(errors="replace").splitlines()[-50:])
        raise RuntimeError(
            f"Unity build failed (exit={result.returncode}). "
            f"Last lines of {editor_log}:\n{tail}"
        )

    logger.info("Unity build finished, output at %s", output_dir)
