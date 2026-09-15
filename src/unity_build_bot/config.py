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
    auth_token_env: str | None = None


@dataclass
class UnityConfig:
    executable_path: Path
    project_subpath: str
    build_target: str
    build_method: str
    output_subdir: Path
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
    depot_id: str
    set_live_branch: str
    build_description: str


@dataclass
class LoggingConfig:
    log_dir: Path
    level: str


@dataclass
class StateConfig:
    state_file: Path


@dataclass
class Config:
    git: GitConfig
    unity: UnityConfig
    versioning: VersioningConfig
    steam: SteamConfig
    logging: LoggingConfig
    state: StateConfig


def _expand_path(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p))).resolve()


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

    return Config(
        git=GitConfig(
            repo_url=git_raw["repo_url"],
            branch=git_raw["branch"],
            workdir=_expand_path(git_raw["workdir"]),
            auth_token_env=git_raw.get("auth_token_env"),
        ),
        unity=UnityConfig(
            executable_path=_expand_path(unity_raw["executable_path"]),
            project_subpath=unity_raw.get("project_subpath", "."),
            build_target=unity_raw["build_target"],
            build_method=unity_raw["build_method"],
            output_subdir=_expand_path(unity_raw["output_subdir"]),
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
            depot_id=str(steam_raw["depot_id"]),
            set_live_branch=steam_raw.get("set_live_branch", ""),
            build_description=steam_raw.get("build_description", ""),
        ),
        logging=LoggingConfig(
            log_dir=_expand_path(logging_raw.get("log_dir", "~/.unity-build-bot/logs")),
            level=logging_raw.get("level", "INFO"),
        ),
        state=StateConfig(
            state_file=_expand_path(state_raw.get("state_file", "~/.unity-build-bot/state.json")),
        ),
    )
