"""Prevent overlapping scheduled bot runs."""
from __future__ import annotations

import errno
import os
from pathlib import Path


class RunLock:
    def __init__(self, path: Path):
        self.path = path
        self._held = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError:
            try:
                pid = int(self.path.joinpath("pid").read_text())
            except (FileNotFoundError, ValueError):
                pid = None
            if pid and _process_exists(pid):
                return False
            self.path.joinpath("pid").unlink(missing_ok=True)
            self.path.rmdir()
            self.path.mkdir()
        self.path.joinpath("pid").write_text(str(os.getpid()))
        self._held = True
        return True

    def release(self) -> None:
        if not self._held:
            return
        try:
            self.path.joinpath("pid").unlink(missing_ok=True)
            self.path.rmdir()
        finally:
            self._held = False


def _process_exists(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError as exc:
        if exc.errno == errno.ESRCH or getattr(exc, "winerror", None) == 87:
            return False
        raise
    return True