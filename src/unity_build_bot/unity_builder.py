"""Invoke the Unity Editor in batch mode to produce a build."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from unity_build_bot.config import UnityBuildConfig, UnityConfig
from unity_build_bot.process_runner import run_streaming

logger = logging.getLogger("unity_build_bot")


def build(
    unity_cfg: UnityConfig,
    build_cfg: UnityBuildConfig,
    repo_workdir: Path,
    version: str,
    clean_build: bool = False,
) -> None:
    project_path = (repo_workdir / unity_cfg.project_subpath).resolve()
    output_dir = build_cfg.output_subdir
    resolved_output_dir = output_dir.resolve()
    if resolved_output_dir == project_path or resolved_output_dir in project_path.parents:
        raise RuntimeError(
            f"Build output directory must not contain the Unity project: {output_dir}"
        )
    if output_dir.is_symlink():
        output_dir.unlink()
    elif output_dir.is_dir():
        shutil.rmtree(output_dir)
    elif output_dir.exists():
        output_dir.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    editor_log = output_dir.parent / f"{output_dir.name}.unity_editor.log"

    cmd = [
        str(unity_cfg.executable_path),
        "-batchmode",
        "-quit",
        "-nographics",
        "-projectPath", str(project_path),
        "-executeMethod", unity_cfg.build_method,
        "-buildTarget", build_cfg.build_target,
        "-customBuildOutput", str(output_dir),
        "-customBuildVersion", version,
        "-customBuildName", build_cfg.build_name,
        "-customCleanBuild", "true" if clean_build else "false",
        "-logFile", "-",
        *unity_cfg.extra_args,
    ]

    logger.info(
        "Starting Unity build (id=%s, target=%s, version=%s, clean=%s)",
        build_cfg.id,
        build_cfg.build_target,
        version,
        clean_build,
    )
    result = run_streaming(cmd, output_file=editor_log)

    if result.returncode != 0:
        tail = ""
        if editor_log.is_file():
            tail = "\n".join(editor_log.read_text(errors="replace").splitlines()[-50:])
        raise RuntimeError(
            f"Unity build failed (exit={result.returncode}). "
            f"Last lines of {editor_log}:\n{tail}"
        )

    expected_output = _expected_output_path(build_cfg, output_dir)
    if not expected_output.exists():
        raise RuntimeError(
            f"Unity reported a successful build but expected output is missing: "
            f"{expected_output}"
        )

    logger.info("Unity build finished, output at %s", output_dir)


def _expected_output_path(build_cfg: UnityBuildConfig, output_dir: Path) -> Path:
    if build_cfg.build_target in {"StandaloneWindows", "StandaloneWindows64"}:
        output_name = f"{build_cfg.build_name}.exe"
    elif build_cfg.build_target == "StandaloneOSX":
        output_name = f"{build_cfg.build_name}.app"
    else:
        output_name = build_cfg.build_name
    return output_dir / output_name
