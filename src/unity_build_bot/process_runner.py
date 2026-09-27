"""Run child processes while streaming their output to the activity log."""
from __future__ import annotations

import logging
import re
import shlex
import subprocess
from pathlib import Path

from unity_build_bot.logging_utils import redact

logger = logging.getLogger("unity_build_bot")
_SECRET_OPTION = re.compile(r"(?:password|passwd|token|secret|api[-_]?key|authorization|credential)", re.I)


def safe_command(cmd: list[str]) -> str:
    arguments = []
    hide_next = False
    for arg in cmd:
        if hide_next:
            arguments.append("****")
            hide_next = False
            continue
        arguments.append(redact(arg))
        hide_next = bool(arg.startswith(("-", "+")) and _SECRET_OPTION.search(arg) and "=" not in arg)
    return shlex.join(arguments)


def run_streaming(
    cmd: list[str],
    cwd: Path | None = None,
    output_file: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    logger.info("Running command: %s (cwd=%s)", safe_command(cmd), cwd)
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
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
                logger.debug("%s", line.rstrip())
                if file_handle is not None:
                    file_handle.write(redact(line))
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
