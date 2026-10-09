"""Run child processes while streaming their output to the activity log."""
from __future__ import annotations

import contextlib
import logging
import re
import shlex
import subprocess
import sys
from pathlib import Path

from unity_build_bot.logging_utils import redact

logger = logging.getLogger("unity_build_bot")
_SECRET_OPTION = re.compile(r"(?:password|passwd|token|secret|api[-_]?key|authorization|credential)", re.I)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def keep_awake(enabled: bool = True):
    """Stop the machine from sleeping or throttling while a long job runs."""
    if not enabled:
        yield
        return
    if sys.platform == "darwin":
        try:
            blocker = subprocess.Popen(
                ["caffeinate", "-dimsu"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning("Could not prevent sleep: %s", exc)
            yield
            return
        logger.info("Sleep prevention active (caffeinate)")
        try:
            yield
        finally:
            blocker.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                blocker.wait(timeout=5)
        return
    if sys.platform == "win32":
        import ctypes

        set_state = ctypes.windll.kernel32.SetThreadExecutionState
        if not set_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED):
            logger.warning("Could not prevent sleep: SetThreadExecutionState failed")
            yield
            return
        logger.info("Sleep prevention active (SetThreadExecutionState)")
        try:
            yield
        finally:
            set_state(_ES_CONTINUOUS)
        return
    logger.debug("Sleep prevention is supported only on macOS and Windows")
    yield


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
