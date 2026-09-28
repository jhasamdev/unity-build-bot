"""Email notifications for completed bot runs."""
from __future__ import annotations

import logging
import os
import platform
import smtplib
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

from unity_build_bot.config import NotificationConfig
from unity_build_bot.logging_utils import redact

logger = logging.getLogger("unity_build_bot")


@dataclass(frozen=True)
class MachineDetails:
    hostname: str
    os_name: str
    os_version: str
    architecture: str
    cpu_count: int | None
    label: str = ""

    @property
    def summary(self) -> str:
        parts = [self.os_name]
        if self.os_version:
            parts.append(self.os_version)
        if self.architecture:
            parts.append(self.architecture)
        if self.cpu_count is not None:
            parts.append(f"{self.cpu_count} CPU(s)")
        details = " / ".join(parts)
        return f"{self.label} ({details})" if self.label else details


@dataclass(frozen=True)
class RunSummary:
    status: str
    job_mode: str
    repo_url: str
    repo_name: str
    branch: str
    commit_sha: str
    short_sha: str
    version: str
    targets: str
    steam_app_id: str
    steam_build_id: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    machine: MachineDetails
    log_file: Path | None = None
    error_stage: str = ""
    error_message: str = ""

    def subject_values(self) -> dict[str, str]:
        return {
            "status": self.status.upper(),
            "repo": self.repo_name,
            "branch": self.branch,
            "version": self.version,
            "short_sha": self.short_sha,
            "build_id": self.steam_build_id,
            "job_mode": self.job_mode,
        }


def build_machine_details(label: str = "") -> MachineDetails:
    return MachineDetails(
        hostname=socket.gethostname(),
        os_name=platform.system() or "unknown",
        os_version=platform.release() or platform.version() or "unknown",
        architecture=platform.machine() or "unknown",
        cpu_count=os.cpu_count(),
        label=label,
    )


def repo_name_from_url(repo_url: str) -> str:
    repo = repo_url
    if "://" in repo_url:
        parsed = urlparse(repo_url)
        repo = parsed.path
    elif ":" in repo_url:
        repo = repo_url.split(":", 1)[1]
    repo = repo.rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo.split("/")[-1] if repo else "unknown"


def should_notify(notification_cfg: NotificationConfig | None, status: str) -> bool:
    if not notification_cfg or not notification_cfg.enabled:
        return False
    if status == "success":
        return notification_cfg.on_success
    if status == "failure":
        return notification_cfg.on_failure
    return False


def send_email(
    notification_cfg: NotificationConfig,
    summary: RunSummary,
    secrets: tuple[str, ...] = (),
) -> None:
    message = EmailMessage()
    message["From"] = (
        f"{notification_cfg.from_name} <{notification_cfg.from_address}>"
        if notification_cfg.from_name
        else notification_cfg.from_address
    )
    message["To"] = ", ".join(notification_cfg.recipients)
    message["Subject"] = notification_cfg.subject_template.format_map(summary.subject_values())
    message.set_content(_render_body(summary, secrets))

    smtp_cfg = notification_cfg.smtp
    client_factory = smtplib.SMTP_SSL if smtp_cfg.use_ssl else smtplib.SMTP
    with client_factory(smtp_cfg.host, smtp_cfg.port, timeout=30) as client:
        if not smtp_cfg.use_ssl and smtp_cfg.use_starttls:
            client.starttls()
        if smtp_cfg.username:
            client.login(smtp_cfg.username, smtp_cfg.password or "")
        client.send_message(message)
    logger.info(
        "Notification email sent to %s for %s (%s)",
        ", ".join(notification_cfg.recipients),
        summary.repo_name,
        summary.status,
    )


def _render_body(summary: RunSummary, secrets: tuple[str, ...]) -> str:
    lines = [
        f"Result: {summary.status.upper()}",
        f"Job mode: {summary.job_mode}",
        f"Repository: {summary.repo_name}",
        f"Repository URL: {summary.repo_url}",
        f"Branch: {summary.branch}",
        f"Commit SHA: {summary.commit_sha}",
        f"Short SHA: {summary.short_sha}",
        f"Version: {summary.version}",
        f"Targets: {summary.targets}",
        f"Steam App ID: {summary.steam_app_id}",
        f"Steam Build ID: {summary.steam_build_id}",
        f"Started at (UTC): {_isoformat(summary.started_at)}",
        f"Finished at (UTC): {_isoformat(summary.ended_at)}",
        f"Duration: {summary.duration_seconds:.1f}s",
        f"Machine hostname: {summary.machine.hostname}",
        f"Machine details: {summary.machine.summary}",
    ]
    if summary.log_file is not None:
        lines.append(f"Log file: {summary.log_file}")
    if summary.status == "failure":
        lines.extend(
            [
                "",
                f"Failed stage: {summary.error_stage or 'unknown'}",
                "Error:",
                _trim_error(redact(summary.error_message or "unknown", secrets)),
            ]
        )
    return "\n".join(lines)


def _trim_error(message: str, limit: int = 4000) -> str:
    if len(message) <= limit:
        return message
    return message[: limit - 15].rstrip() + "\n...[truncated]"


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
