from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.logging_utils import setup_logging


class LoggingSetupTests(TestCase):
    @patch("unity_build_bot.logging_utils.open_activity_window")
    def test_redacts_credentials_in_log_file(self, _open_window_mock):
        with TemporaryDirectory() as temp_dir:
            logger = setup_logging(Path(temp_dir), "DEBUG", secrets=("real-token",))
            try:
                logger.error(
                    "git failed: token=%s Authorization: Basic abc123 https://user:pass@example.com",
                    "real-token",
                )
                contents = next(Path(temp_dir).glob("run-*.log")).read_text()
                for secret in ("real-token", "abc123", "user:pass"):
                    self.assertNotIn(secret, contents)
                self.assertIn("****", contents)
            finally:
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)

    @patch("unity_build_bot.logging_utils.open_activity_window")
    def test_opens_activity_window_when_enabled(self, open_window_mock):
        with TemporaryDirectory() as temp_dir:
            logger = setup_logging(Path(temp_dir), show_activity_window=True)
            try:
                open_window_mock.assert_called_once()
                log_file = open_window_mock.call_args.args[0]
                self.assertEqual(Path(temp_dir), log_file.parent)
                self.assertRegex(log_file.name, r"^run-\d{8}\.log$")
            finally:
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)

    @patch("unity_build_bot.logging_utils.open_activity_window")
    def test_does_not_open_activity_window_by_default(self, open_window_mock):
        with TemporaryDirectory() as temp_dir:
            logger = setup_logging(Path(temp_dir))
            try:
                open_window_mock.assert_not_called()
            finally:
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
