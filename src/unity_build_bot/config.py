"""Load and validate config.yaml, resolving ${ENV_VAR} placeholders."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_BUILD_DESCRIPTION_FIELDS = {"version", "branch", "short_sha", "targets"}
_NOTIFICATION_SUBJECT_FIELDS = {
    "status",
    "repo",
    "branch",
    "version",
    "short_sha",
    "build_id",
    "job_mode",
}


def _expand_env(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            name = m.group(1)
            if name not in variables:
                raise ValueError(f"Environment variable {name} is not set")
            return variables[name]
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, variables) for v in value]
    return value


@dataclass
class GitConfig:
    repo_url: str
    branch: str
    workdir: Path
    workspace_root: Path
    auth_token_env: str | None = None
    auth_token: str | None = None


@dataclass
class UnityBuildConfig:
    id: str
    build_target: str
    output_subdir: Path
    build_name: str = "Game"
    enabled: bool = True


@dataclass
class UnityConfig:
    executable_path: Path
    project_subpath: str
    build_method: str
    builds: list[UnityBuildConfig]
    extra_args: list[str] = field(default_factory=list)


@dataclass
class VersioningConfig:
    version_file: str
    auto_increment: bool
    bump_part: str
    append_short_commit_hash: bool = False
    short_commit_hash_length: int = 7


@dataclass
class SteamConfig:
    steamcmd_path: Path
    config_vdf_path: Path
    username: str
    app_id: str
    depots: dict[str, str]
    set_live_branch: str
    build_description: str


@dataclass
class LoggingConfig:
    log_dir: Path
    level: str
    show_activity_window: bool = False


@dataclass
class NotificationSmtpConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password_env: str | None = None
    password: str | None = None
    use_starttls: bool = True
    use_ssl: bool = False


@dataclass
class NotificationConfig:
    enabled: bool = False
    transport: str = "smtp"
    on_success: bool = True
    on_failure: bool = True
    from_address: str = ""
    from_name: str = ""
    recipients: list[str] = field(default_factory=list)
    subject_template: str = "[unity-build-bot] {status} {repo} {branch} {version}"
    machine_label: str = ""
    smtp: NotificationSmtpConfig = field(default_factory=NotificationSmtpConfig)


@dataclass
class StateConfig:
    state_file: Path


@dataclass
class JobConfig:
    mode: str = "build_and_upload"
    steam_upload_retries: int = 3
    steam_upload_retry_delay_seconds: int = 30


@dataclass
class Config:
    git: GitConfig
    unity: UnityConfig
    versioning: VersioningConfig
    steam: SteamConfig
    logging: LoggingConfig
    notifications: NotificationConfig
    state: StateConfig
    job: JobConfig


def _expand_path(p: str, base_dir: Path) -> Path:
    expanded = Path(os.path.expanduser(os.path.expandvars(p)))
    if not expanded.is_absolute():
        expanded = base_dir / expanded
    return expanded.resolve()


def _config_base_dir(config_path: Path) -> Path:
    if config_path.parent.name == "config":
        return config_path.parent.parent
    return config_path.parent


def _required(raw: dict[str, Any], key: str, section: str) -> Any:
    if key not in raw or raw[key] is None or raw[key] == "":
        raise ValueError(f"Missing required configuration value: {section}.{key}")
    return raw[key]


def _read_yaml(path: Path, description: str) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {description} {path}: {exc}") from exc


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Configuration section '{name}' must be a mapping")
    return value


def _validate_build_description(template: Any) -> str:
    if not isinstance(template, str):
        raise ValueError("steam.build_description must be a string")
    try:
        parsed = Formatter().parse(template)
        for _, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if field_name not in _BUILD_DESCRIPTION_FIELDS:
                raise ValueError(
                    f"Unsupported steam.build_description placeholder: {{{field_name}}}"
                )
            if format_spec or conversion:
                raise ValueError(
                    "steam.build_description placeholders do not support "
                    "format specifiers or conversions"
                )
    except ValueError as exc:
        if str(exc).startswith("steam.") or str(exc).startswith("Unsupported"):
            raise
        raise ValueError(f"Invalid steam.build_description template: {exc}") from exc
    return template


def _validate_notification_subject(template: Any) -> str:
    if not isinstance(template, str):
        raise ValueError("notifications.subject_template must be a string")
    try:
        parsed = Formatter().parse(template)
        for _, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if field_name not in _NOTIFICATION_SUBJECT_FIELDS:
                raise ValueError(
                    f"Unsupported notifications.subject_template placeholder: {{{field_name}}}"
                )
            if format_spec or conversion:
                raise ValueError(
                    "notifications.subject_template placeholders do not support "
                    "format specifiers or conversions"
                )
    except ValueError as exc:
        if str(exc).startswith("notifications.") or str(exc).startswith("Unsupported"):
            raise
        raise ValueError(f"Invalid notifications.subject_template template: {exc}") from exc
    return template


def _load_secrets(config_path: Path) -> dict[str, str]:
    secrets_path = config_path.with_name("secrets.yaml")
    if not secrets_path.is_file():
        return {}
    secrets = _read_yaml(secrets_path, "secrets file") or {}
    if not isinstance(secrets, dict):
        raise ValueError(f"Secrets file must contain a mapping: {secrets_path}")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in secrets.items()):
        raise ValueError(f"Secrets file values must be strings: {secrets_path}")
    return secrets


def _load_builds(unity_raw: dict[str, Any], base_dir: Path) -> list[UnityBuildConfig]:
    builds_raw = unity_raw.get("builds")
    if builds_raw is None:
        builds_raw = [{
            "id": "default",
            "build_target": _required(unity_raw, "build_target", "unity"),
            "output_subdir": _required(unity_raw, "output_subdir", "unity"),
            "build_name": unity_raw.get("build_name", "Game"),
        }]
    if not builds_raw:
        raise ValueError("unity.builds must contain at least one build")
    if not isinstance(builds_raw, list) or not all(
        isinstance(build, dict) for build in builds_raw
    ):
        raise ValueError("unity.builds must be a list of mappings")

    builds = []
    for build_raw in builds_raw:
        enabled = build_raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("unity.builds enabled values must be true or false")
        builds.append(UnityBuildConfig(
            id=str(_required(build_raw, "id", "unity.builds")),
            build_target=_required(build_raw, "build_target", "unity.builds"),
            output_subdir=_expand_path(
                _required(build_raw, "output_subdir", "unity.builds"), base_dir
            ),
            build_name=build_raw.get("build_name", "Game"),
            enabled=enabled,
        ))
    build_ids = [build.id for build in builds]
    if len(build_ids) != len(set(build_ids)):
        raise ValueError("unity.builds IDs must be unique")
    if not any(build.enabled for build in builds):
        raise ValueError("unity.builds must contain at least one enabled build")
    return builds


def _load_depots(
    steam_raw: dict[str, Any],
    build_ids: set[str],
    enabled_build_ids: set[str],
) -> dict[str, str]:
    depots_raw = steam_raw.get("depots")
    if depots_raw is not None and not isinstance(depots_raw, dict):
        raise ValueError("steam.depots must be a mapping of build IDs to depot IDs")
    depots = (
        {str(build_id): str(depot_id) for build_id, depot_id in depots_raw.items()}
        if depots_raw is not None
        else {"default": str(steam_raw["depot_id"])}
    )
    unknown_ids = set(depots) - build_ids
    if unknown_ids:
        raise ValueError("steam.depots contains IDs not defined in unity.builds")
    missing_ids = enabled_build_ids - set(depots)
    if missing_ids:
        raise ValueError("steam.depots must contain every enabled unity.builds ID")
    return depots


def _load_notifications(
    notifications_raw: dict[str, Any],
    variables: dict[str, str],
) -> NotificationConfig:
    enabled = notifications_raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("notifications.enabled must be true or false")
    transport = notifications_raw.get("transport", "smtp")
    if transport != "smtp":
        raise ValueError("notifications.transport must be 'smtp'")
    on_success = notifications_raw.get("on_success", True)
    if not isinstance(on_success, bool):
        raise ValueError("notifications.on_success must be true or false")
    on_failure = notifications_raw.get("on_failure", True)
    if not isinstance(on_failure, bool):
        raise ValueError("notifications.on_failure must be true or false")
    recipients = notifications_raw.get("recipients", [])
    if not isinstance(recipients, list) or not all(
        isinstance(recipient, str) and recipient.strip() for recipient in recipients
    ):
        raise ValueError("notifications.recipients must be a list of non-empty strings")
    smtp_raw = notifications_raw.get("smtp", {})
    if not isinstance(smtp_raw, dict):
        raise ValueError("notifications.smtp must be a mapping")
    smtp_port = smtp_raw.get("port", 587)
    if type(smtp_port) is not int or not 1 <= smtp_port <= 65535:
        raise ValueError("notifications.smtp.port must be an integer from 1 to 65535")
    use_starttls = smtp_raw.get("use_starttls", True)
    if not isinstance(use_starttls, bool):
        raise ValueError("notifications.smtp.use_starttls must be true or false")
    use_ssl = smtp_raw.get("use_ssl", False)
    if not isinstance(use_ssl, bool):
        raise ValueError("notifications.smtp.use_ssl must be true or false")
    if use_ssl and use_starttls:
        raise ValueError(
            "notifications.smtp.use_ssl and notifications.smtp.use_starttls cannot both be true"
        )
    password_env = smtp_raw.get("password_env")
    password = variables.get(password_env) if password_env else None
    if enabled:
        if not recipients:
            raise ValueError("notifications.recipients must contain at least one address when enabled")
        if not notifications_raw.get("from_address"):
            raise ValueError("Missing required configuration value: notifications.from_address")
        if not smtp_raw.get("host"):
            raise ValueError("Missing required configuration value: notifications.smtp.host")
        if password_env and not password:
            raise ValueError(
                f"Notification SMTP password variable {password_env} is not set; define it in the "
                "environment or config/secrets.yaml"
            )
    return NotificationConfig(
        enabled=enabled,
        transport=transport,
        on_success=on_success,
        on_failure=on_failure,
        from_address=notifications_raw.get("from_address", ""),
        from_name=notifications_raw.get("from_name", ""),
        recipients=recipients,
        subject_template=_validate_notification_subject(
            notifications_raw.get(
                "subject_template",
                "[unity-build-bot] {status} {repo} {branch} {version}",
            )
        ),
        machine_label=notifications_raw.get("machine_label", ""),
        smtp=NotificationSmtpConfig(
            host=smtp_raw.get("host", ""),
            port=smtp_port,
            username=smtp_raw.get("username", ""),
            password_env=password_env,
            password=password,
            use_ssl=use_ssl,
        ),
    )


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config/config.example.yaml to "
            "config/config.yaml and fill in your values."
        )

    raw = _read_yaml(path, "configuration file") or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")
    variables = _load_secrets(path)
    variables.update(os.environ)
    raw = _expand_env(raw, variables)

    git_raw = _section(raw, "git")
    unity_raw = _section(raw, "unity")
    versioning_raw = _section(raw, "versioning")
    steam_raw = _section(raw, "steam")
    logging_raw = _section(raw, "logging")
    notifications_raw = _section(raw, "notifications")
    state_raw = _section(raw, "state")
    job_raw = _section(raw, "job")

    base_dir = _config_base_dir(path)
    builds = _load_builds(unity_raw, base_dir)
    show_activity_window = logging_raw.get("show_activity_window", False)
    if not isinstance(show_activity_window, bool):
        raise ValueError("logging.show_activity_window must be true or false")
    append_short_commit_hash = versioning_raw.get("append_short_commit_hash", False)
    if not isinstance(append_short_commit_hash, bool):
        raise ValueError("versioning.append_short_commit_hash must be true or false")
    short_commit_hash_length = versioning_raw.get("short_commit_hash_length", 7)
    if type(short_commit_hash_length) is not int or not 1 <= short_commit_hash_length <= 64:
        raise ValueError("versioning.short_commit_hash_length must be an integer from 1 to 64")

    workdir = _expand_path(_required(git_raw, "workdir", "git"), base_dir)
    workspace_root = _expand_path(
        _required(git_raw, "workspace_root", "git"), base_dir
    )
    if workspace_root not in workdir.parents:
        raise ValueError("git.workdir must be inside git.workspace_root")
    job_mode = job_raw.get("mode", "build_and_upload")
    if job_mode not in {"build_and_upload", "upload_only"}:
        raise ValueError("job.mode must be 'build_and_upload' or 'upload_only'")
    steam_upload_retries = job_raw.get("steam_upload_retries", 3)
    if type(steam_upload_retries) is not int or steam_upload_retries < 0:
        raise ValueError("job.steam_upload_retries must be a non-negative integer")
    retry_delay = job_raw.get("steam_upload_retry_delay_seconds", 30)
    if type(retry_delay) is not int or retry_delay < 0:
        raise ValueError(
            "job.steam_upload_retry_delay_seconds must be a non-negative integer"
        )

    repo_url = _required(git_raw, "repo_url", "git")
    auth_token_env = git_raw.get("auth_token_env")
    auth_token = variables.get(auth_token_env) if auth_token_env else None
    if repo_url.startswith("https://") and auth_token_env and not auth_token:
        raise ValueError(
            f"Git token variable {auth_token_env} is not set; define it in the "
            "environment or config/secrets.yaml"
        )

    return Config(
        git=GitConfig(
            repo_url=repo_url,
            branch=_required(git_raw, "branch", "git"),
            workdir=workdir,
            workspace_root=workspace_root,
            auth_token_env=auth_token_env,
            auth_token=auth_token,
        ),
        unity=UnityConfig(
            executable_path=_expand_path(
                _required(unity_raw, "executable_path", "unity"), base_dir
            ),
            project_subpath=unity_raw.get("project_subpath", "."),
            build_method=_required(unity_raw, "build_method", "unity"),
            builds=builds,
            extra_args=unity_raw.get("extra_args", []),
        ),
        versioning=VersioningConfig(
            version_file=versioning_raw.get("version_file", "version.txt"),
            auto_increment=versioning_raw.get("auto_increment", False),
            bump_part=versioning_raw.get("bump_part", "patch"),
            append_short_commit_hash=append_short_commit_hash,
            short_commit_hash_length=short_commit_hash_length,
        ),
        steam=SteamConfig(
            steamcmd_path=_expand_path(
                _required(steam_raw, "steamcmd_path", "steam"), base_dir
            ),
            config_vdf_path=_expand_path(
                _required(steam_raw, "config_vdf_path", "steam"), base_dir
            ),
            username=_required(steam_raw, "username", "steam"),
            app_id=str(_required(steam_raw, "app_id", "steam")),
            depots=_load_depots(
                steam_raw,
                {build.id for build in builds},
                {build.id for build in builds if build.enabled},
            ),
            set_live_branch=steam_raw.get("set_live_branch", ""),
            build_description=_validate_build_description(
                steam_raw.get("build_description", "")
            ),
        ),
        logging=LoggingConfig(
            log_dir=_expand_path(
                logging_raw.get("log_dir", "~/.unity-build-bot/logs"), base_dir
            ),
            level=logging_raw.get("level", "INFO"),
            show_activity_window=show_activity_window,
        ),
        notifications=_load_notifications(notifications_raw, variables),
        state=StateConfig(
            state_file=_expand_path(
                state_raw.get("state_file", "~/.unity-build-bot/state.json"),
                base_dir,
            ),
        ),
        job=JobConfig(
            mode=job_mode,
            steam_upload_retries=steam_upload_retries,
            steam_upload_retry_delay_seconds=retry_delay,
        ),
    )
