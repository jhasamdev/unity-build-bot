from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot import cli


class DoctorTests(TestCase):
    def test_doctor_reports_ready_build_machine(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_root = root / "workspace"
            unity = root / "Unity"
            steamcmd = root / "steamcmd"
            session = root / "config.vdf"
            for path in (unity, steamcmd, session):
                path.touch()
            config = SimpleNamespace(
                git=SimpleNamespace(
                    workspace_root=workspace_root,
                    repo_url="https://github.com/example/game.git",
                    branch="main",
                ),
                unity=SimpleNamespace(executable_path=unity),
                steam=SimpleNamespace(
                    steamcmd_path=steamcmd,
                    config_vdf_path=session,
                ),
                job=SimpleNamespace(mode="build_and_upload"),
            )

            with (
                patch("unity_build_bot.cli.load_config", return_value=config),
                patch("unity_build_bot.cli.shutil.which", return_value="/usr/bin/git"),
                patch("unity_build_bot.cli.git_watcher.remote_head_sha", return_value="abc"),
                patch("builtins.print") as print_mock,
            ):
                result = cli.doctor("config.yaml")

        self.assertEqual(0, result)
        self.assertTrue(any("Setup checks passed." in str(call) for call in print_mock.call_args_list))


class UploadLoggingTests(TestCase):
    @patch("unity_build_bot.cli.State.load", side_effect=ValueError("invalid state"))
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.load_config")
    def test_state_load_failure_is_logged_as_error(self, load_config_mock, setup_logging_mock, _state_load_mock):
        load_config_mock.return_value = SimpleNamespace(
            git=SimpleNamespace(auth_token=None),
            logging=SimpleNamespace(log_dir=Path("logs"), level="INFO", show_activity_window=False),
            state=SimpleNamespace(state_file=Path("state.json")),
        )

        result = cli.upload("config.yaml")

        self.assertEqual(1, result)
        setup_logging_mock.return_value.exception.assert_called_once()