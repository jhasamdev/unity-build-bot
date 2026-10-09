import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.process_runner import keep_awake, run_streaming, safe_command


class ProcessRunnerTests(TestCase):
    def test_streams_output_to_logger_and_file(self):
        with TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "command.log"
            with patch.object(logging.getLogger("unity_build_bot"), "debug") as debug_mock, patch.object(
                logging.getLogger("unity_build_bot"), "info"
            ) as info_mock:
                result = run_streaming(
                    [sys.executable, "-c", "print('first'); print('second')"],
                    output_file=output_file,
                )

            self.assertEqual(0, result.returncode)
            self.assertEqual("first\nsecond\n", result.stdout)
            self.assertEqual("first\nsecond\n", output_file.read_text())
            debug_mock.assert_any_call("%s", "first")
            debug_mock.assert_any_call("%s", "second")
            info_mock.assert_called_once_with(
                "Running command: %s (cwd=%s)", safe_command([sys.executable, "-c", "print('first'); print('second')"]), None
            )

    def test_command_log_masks_credentials_without_changing_execution(self):
        cmd = [sys.executable, "-c", "print('done')", "--password", "hunter2", "--token=secret123", "https://user:pass@example.com/repo?access_token=private"]
        with patch.object(logging.getLogger("unity_build_bot"), "info") as info_mock:
            result = run_streaming(cmd)

        self.assertEqual(0, result.returncode)
        logged = str(info_mock.call_args)
        for secret in ("hunter2", "secret123", "user:pass", "private"):
            self.assertNotIn(secret, logged)
        self.assertIn("****", logged)

    def test_command_output_file_masks_credentials(self):
        with TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "command.log"
            result = run_streaming(
                [sys.executable, "-c", "print('password=hunter2 Authorization: Bearer private')"],
                output_file=output_file,
            )

            self.assertIn("hunter2", result.stdout)
            self.assertNotIn("hunter2", output_file.read_text())
            self.assertNotIn("private", output_file.read_text())
            self.assertIn("****", output_file.read_text())

class KeepAwakeTests(TestCase):
    def test_disabled_keep_awake_starts_no_helper(self):
        with patch("unity_build_bot.process_runner.subprocess.Popen") as popen_mock:
            with keep_awake(False):
                pass

        popen_mock.assert_not_called()

    def test_macos_keep_awake_stops_helper_on_exit(self):
        with (
            patch("unity_build_bot.process_runner.sys.platform", "darwin"),
            patch("unity_build_bot.process_runner.subprocess.Popen") as popen_mock,
        ):
            with keep_awake(True):
                popen_mock.assert_called_once()
                self.assertEqual(
                    ["caffeinate", "-dimsu"], popen_mock.call_args.args[0]
                )
                popen_mock.return_value.terminate.assert_not_called()

        popen_mock.return_value.terminate.assert_called_once()

    def test_keep_awake_survives_a_missing_helper(self):
        with (
            patch("unity_build_bot.process_runner.sys.platform", "darwin"),
            patch(
                "unity_build_bot.process_runner.subprocess.Popen",
                side_effect=OSError("not found"),
            ),
            patch.object(logging.getLogger("unity_build_bot"), "warning") as warn_mock,
        ):
            with keep_awake(True):
                pass

        warn_mock.assert_called_once()
