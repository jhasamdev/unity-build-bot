"""Open and run the optional terminal-based activity viewer."""
from __future__ import annotations

import logging
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("unity_build_bot")


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def follow_log(log_file: Path, parent_process_id: int) -> None:
    with log_file.open(errors="replace") as stream:
        lines = stream.readlines()
        for line in lines[-200:]:
            print(line, end="", flush=True)

        while _process_exists(parent_process_id):
            line = stream.readline()
            if line:
                print(line, end="", flush=True)
            else:
                time.sleep(0.2)

        for line in stream.readlines():
            print(line, end="", flush=True)


def open_activity_window(log_file: Path) -> None:
    script_path = Path(__file__).resolve()
    viewer_args = [
        sys.executable,
        str(script_path),
        str(log_file),
        str(os.getpid()),
    ]
    try:
        if sys.platform == "darwin":
            command = " ".join(shlex.quote(arg) for arg in viewer_args)
            apple_script = f'tell application "Terminal" to do script {json.dumps(command)}'
            subprocess.Popen(
                ["osascript", "-e", apple_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            subprocess.Popen(
                viewer_args,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            logger.warning("Activity windows are supported only on macOS and Windows")
    except OSError as exc:
        logger.warning("Could not open activity window: %s", exc)


if __name__ == "__main__":
    follow_log(Path(sys.argv[1]), int(sys.argv[2]))
