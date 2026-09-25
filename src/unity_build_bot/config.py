"""Load and validate config.yaml, resolving ${ENV_VAR} placeholders."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), "")
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class GitConfig:
    repo_url: str
    branch: str
    workdir: Path
    workspace_root: Path
    auth_token_env: str | None = None


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
class StateConfig:
    state_file: Path


@dataclass
class JobConfig:
    mode: str = "build_and_upload"


@dataclass
class Config:
    git: GitConfig
    unity: UnityConfig
    versioning: VersioningConfig
    steam: SteamConfig
    logging: LoggingConfig
    state: StateConfig
    job: JobConfig


def _expand_path(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p))).resolve()


def _load_builds(unity_raw: dict[str, Any]) -> list[UnityBuildConfig]:
    builds_raw = unity_raw.get("builds")
    if builds_raw is None:
        builds_raw = [{
            "id": "default",
            "build_target": unity_raw["build_target"],
            "output_subdir": unity_raw["output_subdir"],
            "build_name": unity_raw.get("build_name", "Game"),
        }]
    if not builds_raw:
        raise ValueError("unity.builds must contain at least one build")

    builds = []
    for build_raw in builds_raw:
        enabled = build_raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("unity.builds enabled values must be true or false")
        builds.append(UnityBuildConfig(
            id=str(build_raw["id"]),
            build_target=build_raw["build_target"],
            output_subdir=_expand_path(build_raw["output_subdir"]),
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


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config/config.example.yaml to "
            "config/config.yaml and fill in your values."
        )

    raw = yaml.safe_load(path.read_text()) or {}
    raw = _expand_env(raw)

    git_raw = raw.get("git", {})
    unity_raw = raw.get("unity", {})
    versioning_raw = raw.get("versioning", {})
    steam_raw = raw.get("steam", {})
    logging_raw = raw.get("logging", {})
    state_raw = raw.get("state", {})
    job_raw = raw.get("job", {})

    builds = _load_builds(unity_raw)
    show_activity_window = logging_raw.get("show_activity_window", False)
    if not isinstance(show_activity_window, bool):
        raise ValueError("logging.show_activity_window must be true or false")

    workdir = _expand_path(git_raw["workdir"])
    workspace_root = _expand_path(git_raw["workspace_root"])
    if workspace_root not in workdir.parents:
        raise ValueError("git.workdir must be inside git.workspace_root")
    job_mode = job_raw.get("mode", "build_and_upload")
    if job_mode not in {"build_and_upload", "upload_only"}:
        raise ValueError("job.mode must be 'build_and_upload' or 'upload_only'")

    return Config(
        git=GitConfig(
            repo_url=git_raw["repo_url"],
            branch=git_raw["branch"],
            workdir=workdir,
            workspace_root=workspace_root,
            auth_token_env=git_raw.get("auth_token_env"),
        ),
        unity=UnityConfig(
            executable_path=_expand_path(unity_raw["executable_path"]),
            project_subpath=unity_raw.get("project_subpath", "."),
            build_method=unity_raw["build_method"],
            builds=builds,
            extra_args=unity_raw.get("extra_args", []),
        ),
        versioning=VersioningConfig(
            version_file=versioning_raw.get("version_file", "version.txt"),
            auto_increment=versioning_raw.get("auto_increment", False),
            bump_part=versioning_raw.get("bump_part", "patch"),
        ),
        steam=SteamConfig(
            steamcmd_path=_expand_path(steam_raw["steamcmd_path"]),
            config_vdf_path=_expand_path(steam_raw["config_vdf_path"]),
            username=steam_raw["username"],
            app_id=str(steam_raw["app_id"]),
            depots=_load_depots(
                steam_raw,
                {build.id for build in builds},
                {build.id for build in builds if build.enabled},
            ),
            set_live_branch=steam_raw.get("set_live_branch", ""),
            build_description=steam_raw.get("build_description", ""),
        ),
        logging=LoggingConfig(
            log_dir=_expand_path(logging_raw.get("log_dir", "~/.unity-build-bot/logs")),
            level=logging_raw.get("level", "INFO"),
            show_activity_window=show_activity_window,
        ),
        state=StateConfig(
            state_file=_expand_path(state_raw.get("state_file", "~/.unity-build-bot/state.json")),
        ),
        job=JobConfig(mode=job_mode),
    )
