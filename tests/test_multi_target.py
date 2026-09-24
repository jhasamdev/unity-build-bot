from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import yaml

from unity_build_bot import cli
from unity_build_bot.config import SteamConfig, load_config
from unity_build_bot.steam_uploader import _write_vdfs


def _config_data() -> dict:
    return {
        "git": {"repo_url": "example", "branch": "main", "workdir": "repo"},
        "unity": {
            "executable_path": "Unity",
            "project_subpath": ".",
            "build_method": "BuildScript.PerformBuild",
            "build_target": "StandaloneOSX",
            "output_subdir": "build",
            "build_name": "LegacyGame",
        },
        "versioning": {},
        "steam": {
            "steamcmd_path": "steamcmd",
            "config_vdf_path": "config.vdf",
            "username": "builder",
            "app_id": "100",
            "depot_id": "101",
        },
        "logging": {},
        "state": {},
    }


class MultiTargetConfigTests(TestCase):
    def _load(self, data: dict):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(yaml.safe_dump(data))
            return load_config(config_path)

    def test_legacy_config_normalizes_to_default_build(self):
        config = self._load(_config_data())

        self.assertEqual(["default"], [build.id for build in config.unity.builds])
        self.assertEqual("StandaloneOSX", config.unity.builds[0].build_target)
        self.assertEqual("LegacyGame", config.unity.builds[0].build_name)
        self.assertEqual({"default": "101"}, config.steam.depots)
        self.assertFalse(config.logging.show_activity_window)

    def test_multi_target_config_supports_enabled_selection(self):
        data = _config_data()
        data["unity"].pop("build_target")
        data["unity"].pop("output_subdir")
        data["unity"].pop("build_name")
        data["unity"]["builds"] = [
            {
                "id": "macos",
                "build_target": "StandaloneOSX",
                "output_subdir": "build/macos",
                "build_name": "Game",
            },
            {
                "id": "windows",
                "build_target": "StandaloneWindows64",
                "output_subdir": "build/windows",
                "build_name": "Game",
            },
        ]
        data["steam"].pop("depot_id")
        data["steam"]["depots"] = {"macos": "101", "windows": "102"}

        config = self._load(data)

        self.assertEqual(["macos", "windows"], [build.id for build in config.unity.builds])
        self.assertEqual({"macos": "101", "windows": "102"}, config.steam.depots)

        data["unity"]["builds"][1]["enabled"] = False
        data["steam"]["depots"].pop("windows")
        config = self._load(data)

        self.assertTrue(config.unity.builds[0].enabled)
        self.assertFalse(config.unity.builds[1].enabled)
        self.assertEqual({"macos": "101"}, config.steam.depots)

        data["unity"]["builds"][0]["enabled"] = False
        with self.assertRaisesRegex(ValueError, "at least one enabled build"):
            self._load(data)


class MultiTargetRunTests(TestCase):
    @patch("unity_build_bot.cli.State.load")
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.steam_uploader.upload")
    @patch("unity_build_bot.cli.unity_builder.build")
    @patch("unity_build_bot.cli.version_file.read_version", return_value="1.2.3")
    @patch("unity_build_bot.cli.git_watcher.sync_workdir")
    @patch("unity_build_bot.cli.git_watcher.has_new_commit", return_value="new-sha")
    @patch("unity_build_bot.cli.load_config")
    def test_run_builds_only_enabled_targets_before_upload(
        self,
        load_config_mock,
        _has_new_commit_mock,
        _sync_workdir_mock,
        _read_version_mock,
        build_mock,
        upload_mock,
        setup_logging_mock,
        state_load_mock,
    ):
        macos = SimpleNamespace(id="macos", output_subdir=Path("build/macos"), enabled=True)
        windows = SimpleNamespace(id="windows", output_subdir=Path("build/windows"), enabled=False)
        config = SimpleNamespace(
            git=SimpleNamespace(branch="main", workdir=Path("repo")),
            unity=SimpleNamespace(builds=[macos, windows]),
            steam=Mock(),
            versioning=SimpleNamespace(version_file="version.txt", auto_increment=False),
            logging=SimpleNamespace(
                log_dir=Path("logs"),
                level="INFO",
                show_activity_window=False,
            ),
            state=SimpleNamespace(state_file=Path("state.json")),
        )
        state = SimpleNamespace(
            last_built_sha="old-sha",
            last_version=None,
            last_status=None,
            last_run_at=None,
            save=Mock(),
        )
        load_config_mock.return_value = config
        state_load_mock.return_value = state

        result = cli.run("config.yaml")

        self.assertEqual(0, result)
        self.assertEqual(
            [
                call(config.unity, macos, config.git.workdir, "1.2.3"),
            ],
            build_mock.call_args_list,
        )
        upload_mock.assert_called_once_with(
            config.steam,
            {"macos": Path("build/macos")},
            config.git.workdir,
        )


class MultiDepotVdfTests(TestCase):
    def test_app_build_references_every_depot(self):
        steam_config = SteamConfig(
            steamcmd_path=Path("steamcmd"),
            config_vdf_path=Path("config.vdf"),
            username="builder",
            app_id="100",
            depots={"macos": "101", "windows": "102"},
            set_live_branch="",
            build_description="",
        )
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_vdf = _write_vdfs(
                steam_config,
                {"macos": root / "macos", "windows": root / "windows"},
                root / "vdf",
                "test build",
            )

            app_contents = app_vdf.read_text()
            self.assertIn('"101"', app_contents)
            self.assertIn('"102"', app_contents)
            self.assertIn(f'"LocalPath"\t"{root / "macos"}/*"', (root / "vdf/depot_101.vdf").read_text())
            self.assertIn(f'"LocalPath"\t"{root / "windows"}/*"', (root / "vdf/depot_102.vdf").read_text())
