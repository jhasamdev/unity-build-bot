from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import ANY, Mock, patch

from unity_build_bot import cli
from unity_build_bot.steam_uploader import UploadResult


class UploadRetryTests(TestCase):
    @patch("unity_build_bot.cli.time.sleep")
    @patch(
        "unity_build_bot.cli.steam_uploader.upload",
        side_effect=[
            RuntimeError("timeout"),
            UploadResult(build_id="25520824", description="test build", log_path=Path("steamcmd.log")),
        ],
    )
    def test_retries_failed_upload(self, upload_mock, sleep_mock):
        config = SimpleNamespace(
            steam=Mock(),
            job=SimpleNamespace(
                steam_upload_retries=1,
                steam_upload_retry_delay_seconds=12,
            ),
        )
        logger = Mock()

        cli._upload_with_retries(config, logger, {"macos": Path("build")}, Path("repo"), {})

        self.assertEqual(2, upload_mock.call_count)
        sleep_mock.assert_called_once_with(12)
        logger.warning.assert_called_once_with(
            "Steam upload attempt %s/%s failed (%s); retrying in %ss",
            1, 2, ANY, 12,
        )
        logger.exception.assert_not_called()