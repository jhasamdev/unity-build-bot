"""Semver-ish helpers for reading/bumping version.txt."""
from __future__ import annotations

from pathlib import Path


def read_version(version_file: Path) -> str:
    if not version_file.is_file():
        raise FileNotFoundError(
            f"version.txt not found in repo at {version_file}; the project repo "
            "must contain a version.txt with the starting version."
        )
    return version_file.read_text().strip()


def bump_version(version: str, part: str = "patch") -> str:
    parts = version.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = (int(p) for p in parts[:3])

    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1

    return f"{major}.{minor}.{patch}"


def write_version(version_file: Path, version: str) -> None:
    version_file.write_text(version + "\n")
