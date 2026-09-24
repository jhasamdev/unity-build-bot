"""Rotating log file kept outside any git repo, plus console output."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from unity_build_bot.activity_window import open_activity_window


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    show_activity_window: bool = False,
) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run-{datetime.now(timezone.utc):%Y%m%d}.log"

    logger = logging.getLogger("unity_build_bot")
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    if show_activity_window:
        open_activity_window(log_file)

    return logger
