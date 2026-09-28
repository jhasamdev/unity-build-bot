"""Rotating log file kept outside any git repo, plus console output."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from unity_build_bot.activity_window import open_activity_window

_URL_CREDENTIALS = re.compile(r"(https?://)[^/\s@]+@", re.I)
_SECRET_VALUE = re.compile(
    r"((?:access[_-]?token|password|passwd|token|secret|api[-_]?key|credential)\s*[:=]\s*)[^\s&;]+",
    re.I,
)
_AUTH_HEADER = re.compile(r"(Authorization:\s*)(?:(?:basic|bearer)\s+)?\S+", re.I)


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "****")
    text = _URL_CREDENTIALS.sub(r"\1****@", text)
    text = _AUTH_HEADER.sub(r"\1****", text)
    return _SECRET_VALUE.sub(r"\1****", text)


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: tuple[str, ...]):
        super().__init__(fmt)
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self.secrets)


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    show_activity_window: bool = False,
    secrets: tuple[str, ...] = (),
) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run-{datetime.now(timezone.utc):%Y%m%d}.log"

    logger = logging.getLogger("unity_build_bot")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = RedactingFormatter("%(asctime)s %(levelname)-7s %(message)s", secrets)

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    if show_activity_window:
        open_activity_window(log_file)

    setattr(logger, "unity_build_bot_log_file", log_file)
    return logger
