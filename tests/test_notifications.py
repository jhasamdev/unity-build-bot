from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.config import NotificationConfig, NotificationSmtpConfig, SteamConfig
from unity_build_bot.notifier import MachineDetails, RunSummary, send_email
from unity_build_bot.steam_uploader import upload


class NotificationTests(TestCase):
    @patch("unity_build_bot.notifier.smtplib.SMTP")
    def test_send_email_formats_failure_summary_and_redacts_error(self, smtp_mock):
        smtp_client = smtp_mock.return_value.__enter__.return_value
        config = NotificationConfig(
            enabled=True,
            from_address="bot@example.com",
            from_name="Unity Build Bot",
            recipients=["dev@example.com"],
            subject_template="[unity-build-bot] {status} {repo}",
            smtp=NotificationSmtpConfig(
                host="smtp.example.com",
                port=587,
                use_starttls=True,
                use_ssl=False,
            ),
        )
        summary = RunSummary(
            status="failure",
            job_mode="build_and_upload",
            repo_url="https://github.com/example/game.git",
            repo_name="game",
            branch="main",
            commit_sha="abcdef123456",
            short_sha="abcdef1",
            version="1.2.3.abcdef1",
            targets="macos,windows",
            steam_app_id="100",
            steam_build_id="25520824",
            started_at=datetime(2026, 9, 28, 1, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 9, 28, 1, 5, 0, tzinfo=timezone.utc),
            duration_seconds=300.0,
            machine=MachineDetails(
                hostname="builder.local",
                os_name="Darwin",
                os_version="24.0.0",
                architecture="arm64",
                cpu_count=8,
                label="Mac mini M2 / 16 GB",
            ),
            log_file=Path("/tmp/run.log"),
            error_stage="Steam upload",
            error_message="upload failed with secret-token",
        )

        send_email(config, summary, secrets=("secret-token",))

        smtp_client.starttls.assert_called_once_with()
        smtp_client.send_message.assert_called_once()
        message = smtp_client.send_message.call_args.args[0]
        self.assertEqual("[unity-build-bot] FAILURE game", message["Subject"])
        self.assertIn("Failed stage: Steam upload", message.get_content())
        self.assertIn("Steam Build ID: 25520824", message.get_content())
        self.assertNotIn("secret-token", message.get_content())
        self.assertIn("****", message.get_content())


class SteamUploadResultTests(TestCase):
    @patch("unity_build_bot.steam_uploader.run_streaming")
    def test_upload_returns_structured_result(self, run_streaming_mock):
        run_streaming_mock.return_value = CompletedProcess(
            args=["steamcmd"],
            returncode=0,
            stdout="[2026-09-24 22:07:50]: Successfully finished AppID 100 build (BuildID 25520824).",
            stderr="",
        )
        steam_config = SteamConfig(
            steamcmd_path=Path("steamcmd"),
            config_vdf_path=Path("config.vdf"),
            username="builder",
            app_id="100",
            depots={"macos": "101"},
            set_live_branch="",
            build_description="{version}",
        )

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config.vdf").write_text("session")
            content_root = root / "build/macos"
            content_root.mkdir(parents=True)
            result = upload(
                SteamConfig(
                    steamcmd_path=steam_config.steamcmd_path,
                    config_vdf_path=root / "config.vdf",
                    username=steam_config.username,
                    app_id=steam_config.app_id,
                    depots=steam_config.depots,
                    set_live_branch=steam_config.set_live_branch,
                    build_description=steam_config.build_description,
                ),
                {"macos": content_root},
                root,
                build_metadata={"version": "1.2.3"},
            )

        self.assertEqual("25520824", result.build_id)
        self.assertEqual("1.2.3", result.description)
        self.assertEqual("steamcmd.log", result.log_path.name)
