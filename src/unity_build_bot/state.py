"""Small JSON state file: last built commit SHA, version, run history."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class State:
    last_built_sha: str | None = None
    last_version: str | None = None
    last_status: str | None = None
    last_run_at: str | None = None

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text())
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
