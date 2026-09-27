import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from unity_build_bot.state import State


class StateTests(TestCase):
    def test_loads_existing_state_without_branch(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state_path.write_text(json.dumps({
                "last_built_sha": "abc123",
                "last_version": "1.0.0",
                "last_status": "success",
                "last_run_at": "2026-01-01T00:00:00+00:00",
            }))

            state = State.load(state_path)

        self.assertEqual("abc123", state.last_built_sha)
        self.assertEqual("1.0.0", state.last_version)
        self.assertIsNone(state.last_branch)

    def test_saves_branch_with_build_state(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            State(
                last_built_sha="abc123",
                last_version="1.0.0.abc123",
                last_branch="develop",
                last_status="failed: build broke",
            ).save(state_path)

            data = json.loads(state_path.read_text())

        self.assertEqual("develop", data["last_branch"])