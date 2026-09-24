"""Run child processes while streaming their output to the activity log."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("unity_build_bot")


def run_streaming(
    cmd: list[str],
    cwd: Path | None = None,
    output_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    file_handle = None
    try:
        if output_file is not None:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            file_handle = output_file.open("w")
        if process.stdout is not None:
            for line in process.stdout:
                output_lines.append(line)
                logger.info("%s", line.rstrip())
                if file_handle is not None:
                    file_handle.write(line)
                    file_handle.flush()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if file_handle is not None:
            file_handle.close()

    return subprocess.CompletedProcess(
        cmd,
        process.wait(),
        "".join(output_lines),
        "",
    )
