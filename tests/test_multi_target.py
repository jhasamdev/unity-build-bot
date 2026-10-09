from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import yaml

from unity_build_bot import cli
from unity_build_bot.config import SteamConfig, load_config
from unity_build_bot.steam_uploader import (
    _render_build_description,
    _successful_build_id,
    _write_vdfs,
)


def _config_data() -> dict:
    return {
        "git": {
            "repo_url": "example",
            "branch": "main",
            "workspace_root": "workspace",
            "workdir": "workspace/repo",
        },
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
    def _load(self, data: dict, secrets: dict | None = None):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(yaml.safe_dump(data))
            if secrets is not None:
                (config_path.parent / "secrets.yaml").write_text(yaml.safe_dump(secrets))
            return load_config(config_path)

    def test_relative_paths_are_resolved_from_config_directory(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text(yaml.safe_dump(_config_data()))

            config = load_config(config_path)

            project_root = config_path.parent.parent
            self.assertEqual((project_root / "workspace").resolve(), config.git.workspace_root)
            self.assertEqual((project_root / "build").resolve(), config.unity.builds[0].output_subdir)

    def test_secrets_file_supplies_configured_git_token(self):
        data = _config_data()
        data["git"]["repo_url"] = "https://github.com/example/game.git"
        data["git"]["auth_token_env"] = "TEST_UNITY_BUILD_BOT_TOKEN"

        config = self._load(data, {"TEST_UNITY_BUILD_BOT_TOKEN": "secret-token"})

        self.assertEqual("secret-token", config.git.auth_token)

    def test_environment_overrides_secrets_file(self):
        data = _config_data()
        data["git"]["repo_url"] = "https://github.com/example/game.git"
        data["git"]["auth_token_env"] = "GIT_TOKEN"

        with patch.dict("os.environ", {"GIT_TOKEN": "environment-token"}):
            config = self._load(data, {"GIT_TOKEN": "file-token"})

        self.assertEqual("environment-token", config.git.auth_token)

    def test_missing_required_values_have_field_names(self):
        data = _config_data()
        del data["git"]["repo_url"]

        with self.assertRaisesRegex(ValueError, "git.repo_url"):
            self._load(data)

    def test_invalid_yaml_reports_the_config_file(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("git: [\n")

            with self.assertRaisesRegex(ValueError, "Invalid YAML in configuration file"):
                load_config(config_path)

    def test_missing_configured_https_token_is_reported(self):
        data = _config_data()
        data["git"]["repo_url"] = "https://github.com/example/game.git"
        data["git"]["auth_token_env"] = "UNITY_BUILD_BOT_MISSING_TOKEN"

        with self.assertRaisesRegex(ValueError, "UNITY_BUILD_BOT_MISSING_TOKEN"):
            self._load(data)

    def test_performance_options_default_to_cached_builds(self):
        config = self._load(_config_data())

        self.assertEqual("never", config.unity.clean_build)
        self.assertTrue(config.job.prevent_sleep)

    def test_unknown_clean_build_mode_is_rejected(self):
        data = _config_data()
        data["unity"]["clean_build"] = "sometimes"

        with self.assertRaisesRegex(ValueError, "unity.clean_build must be one of"):
            self._load(data)

    def test_legacy_config_normalizes_to_default_build(self):
        config = self._load(_config_data())

        self.assertEqual(["default"], [build.id for build in config.unity.builds])
        self.assertEqual("StandaloneOSX", config.unity.builds[0].build_target)
        self.assertEqual("LegacyGame", config.unity.builds[0].build_name)
        self.assertEqual({"default": "101"}, config.steam.depots)
        self.assertFalse(config.logging.show_activity_window)
        self.assertEqual("build_and_upload", config.job.mode)
        self.assertFalse(config.versioning.append_short_commit_hash)
        self.assertEqual(7, config.versioning.short_commit_hash_length)

    def test_versioning_config_controls_commit_hash_suffix(self):
        data = _config_data()
        data["versioning"] = {
            "append_short_commit_hash": True,
            "short_commit_hash_length": 10,
        }

        config = self._load(data)

        self.assertTrue(config.versioning.append_short_commit_hash)
        self.assertEqual(10, config.versioning.short_commit_hash_length)

        data["versioning"]["short_commit_hash_length"] = 0
        with self.assertRaisesRegex(ValueError, "integer from 1 to 64"):
            self._load(data)

    def test_rejects_unknown_build_description_placeholder(self):
        data = _config_data()
        data["steam"]["build_description"] = "{unknown}"

        with self.assertRaisesRegex(ValueError, "Unsupported.*unknown"):
            self._load(data)

    def test_upload_only_mode_loads_from_config(self):
        data = _config_data()
        data["job"] = {"mode": "upload_only"}

        config = self._load(data)

        self.assertEqual("upload_only", config.job.mode)

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
    def test_workspace_sync_decision_uses_state_initialization_and_branch(self):
        self.assertEqual((True, False), cli._workspace_sync_decision(False, None, "main"))
        self.assertEqual((False, True), cli._workspace_sync_decision(True, "develop", "main"))
        self.assertEqual((False, False), cli._workspace_sync_decision(True, "main", "main"))
        self.assertEqual((True, False), cli._workspace_sync_decision(True, None, "main"))

    def test_unchanged_remote_still_syncs_workspace_without_building(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_file = root / "state.json"
            state_file.touch()
            config = SimpleNamespace(
                git=SimpleNamespace(
                    auth_token=None,
                    branch="main",
                    workdir=root / "repo",
                    workspace_root=root / "workspace",
                ),
                unity=SimpleNamespace(builds=[], clean_build="never"),
                logging=SimpleNamespace(
                    log_dir=root / "logs",
                    level="INFO",
                    show_activity_window=False,
                ),
                state=SimpleNamespace(state_file=state_file),
                job=SimpleNamespace(mode="build_and_upload", prevent_sleep=False),
            )
            state = SimpleNamespace(
                last_built_sha="same-sha",
                last_branch="main",
                last_status="success",
                save=Mock(),
            )
            with (
                patch("unity_build_bot.cli.load_config", return_value=config),
                patch("unity_build_bot.cli.State.load", return_value=state),
                patch("unity_build_bot.cli.setup_logging"),
                patch("unity_build_bot.cli.git_watcher.has_new_commit", return_value=None),
                patch("unity_build_bot.cli.git_watcher.sync_workdir") as sync_mock,
                patch("unity_build_bot.cli.unity_builder.build") as build_mock,
            ):
                result = cli.run("config.yaml")

        self.assertEqual(0, result)
        sync_mock.assert_called_once_with(
            config.git,
            first_run=False,
            branch_changed=False,
            build_outputs=[],
        )
        build_mock.assert_not_called()

    @patch("unity_build_bot.cli.State.load")
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.steam_uploader.upload")
    @patch("unity_build_bot.cli.unity_builder.build")
    @patch("unity_build_bot.cli.version_file.write_version")
    @patch("unity_build_bot.cli.version_file.read_version", return_value="1.2.3")
    @patch("unity_build_bot.cli.git_watcher.sync_workdir")
    @patch("unity_build_bot.cli.git_watcher.has_new_commit", return_value="abcdef123456")
    @patch("unity_build_bot.cli.load_config")
    def test_run_builds_only_enabled_targets_before_upload(
        self,
        load_config_mock,
        _has_new_commit_mock,
        _sync_workdir_mock,
        _read_version_mock,
        write_version_mock,
        build_mock,
        upload_mock,
        setup_logging_mock,
        state_load_mock,
    ):
        macos = SimpleNamespace(id="macos", output_subdir=Path("build/macos"), enabled=True)
        windows = SimpleNamespace(id="windows", output_subdir=Path("build/windows"), enabled=False)
        config = SimpleNamespace(
            git=SimpleNamespace(branch="main", workdir=Path("repo"), workspace_root=Path("workspace")),
            unity=SimpleNamespace(builds=[macos, windows], clean_build="never"),
            steam=Mock(),
            versioning=SimpleNamespace(
                version_file="version.txt",
                auto_increment=True,
                bump_part="patch",
                append_short_commit_hash=True,
                short_commit_hash_length=7,
            ),
            logging=SimpleNamespace(
                log_dir=Path("logs"),
                level="INFO",
                show_activity_window=False,
            ),
            state=SimpleNamespace(state_file=Path("state.json")),
            job=SimpleNamespace(mode="build_and_upload"),
        )
        state = SimpleNamespace(
            last_built_sha="old-sha",
            last_version=None,
            last_branch=None,
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
                call(config.unity, macos, config.git.workdir, "1.2.4.abcdef1", clean_build=False),
            ],
            build_mock.call_args_list,
        )
        write_version_mock.assert_called_once_with(
            config.git.workdir / "version.txt", "1.2.4"
        )
        self.assertEqual("1.2.4.abcdef1", state.last_version)
        self.assertEqual("abcdef123456", state.last_built_sha)
        self.assertEqual("main", state.last_branch)
        _sync_workdir_mock.assert_called_once_with(
            config.git,
            first_run=True,
            branch_changed=False,
            build_outputs=[macos.output_subdir],
        )
        upload_mock.assert_called_once_with(
            config.steam,
            {"macos": Path("build/macos")},
            config.git.workdir,
            build_metadata={
                "version": "1.2.4.abcdef1",
                "branch": "main",
                "short_sha": "abcdef1",
                "targets": "macos",
            },
        )
        logger = setup_logging_mock.return_value
        logger.info.assert_any_call("Git check started (branch=%s)", "main")
        logger.info.assert_any_call("Git check finished (new_commit=%s)", True)
        logger.info.assert_any_call(
            "Workspace sync started (first_run=%s, branch_changed=%s)",
            True,
            False,
        )
        logger.info.assert_any_call("Workspace sync finished")
        logger.info.assert_any_call("Run finished successfully: version=%s sha=%s", "1.2.4.abcdef1", "abcdef123456")
        logger.exception.assert_not_called()

    @patch("unity_build_bot.cli.State.load")
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.unity_builder.build", side_effect=RuntimeError("build broke"))
    @patch("unity_build_bot.cli.version_file.read_version", return_value="2.0.0")
    @patch("unity_build_bot.cli.git_watcher.sync_workdir")
    @patch("unity_build_bot.cli.git_watcher.has_new_commit", return_value="1234567890abcdef")
    @patch("unity_build_bot.cli.load_config")
    def test_failed_build_records_generated_version_sha_and_branch(
        self,
        load_config_mock,
        has_new_commit_mock,
        _sync_workdir_mock,
        _read_version_mock,
        _build_mock,
        setup_logging_mock,
        state_load_mock,
    ):
        config = SimpleNamespace(
            git=SimpleNamespace(branch="develop", workdir=Path("repo"), workspace_root=Path("workspace")),
            unity=SimpleNamespace(builds=[
                SimpleNamespace(id="macos", output_subdir=Path("build/macos"), enabled=True),
            ], clean_build="on_previous_failure"),
            steam=Mock(),
            versioning=SimpleNamespace(
                version_file="version.txt",
                auto_increment=False,
                bump_part="patch",
                append_short_commit_hash=True,
                short_commit_hash_length=7,
            ),
            logging=SimpleNamespace(
                log_dir=Path("logs"), level="INFO", show_activity_window=False
            ),
            state=SimpleNamespace(state_file=Path("state.json")),
            job=SimpleNamespace(mode="build_and_upload"),
        )
        state = SimpleNamespace(
            last_built_sha="old-sha",
            last_version="1.9.0.oldhash",
            last_branch="develop",
            last_status="failed: previous failure",
            last_run_at=None,
            save=Mock(),
        )
        load_config_mock.return_value = config
        state_load_mock.return_value = state

        with patch("pathlib.Path.is_file", return_value=True):
            result = cli.run("config.yaml")

        self.assertEqual(1, result)
        _sync_workdir_mock.assert_called_once_with(
            config.git,
            first_run=False,
            branch_changed=False,
            build_outputs=[config.unity.builds[0].output_subdir],
        )
        has_new_commit_mock.assert_called_once_with(config.git, None)
        self.assertEqual("1234567890abcdef", state.last_built_sha)
        self.assertEqual("2.0.0.1234567", state.last_version)
        self.assertEqual("develop", state.last_branch)
        self.assertEqual("failed: build broke", state.last_status)
        state.save.assert_called_once_with(config.state.state_file)
        self.assertTrue(_build_mock.call_args.kwargs["clean_build"])
        setup_logging_mock.return_value.exception.assert_any_call(
            "%s failed; run aborted: %s", "Unity build macos", _build_mock.side_effect
        )

    @patch("unity_build_bot.cli.State.load")
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.steam_uploader.upload")
    @patch("unity_build_bot.cli.unity_builder.build")
    @patch("unity_build_bot.cli.git_watcher.sync_workdir")
    @patch("unity_build_bot.cli.git_watcher.has_new_commit")
    @patch("unity_build_bot.cli.load_config")
    def test_upload_skips_git_and_unity(
        self,
        load_config_mock,
        has_new_commit_mock,
        sync_workdir_mock,
        build_mock,
        upload_mock,
        setup_logging_mock,
        state_load_mock,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            macos_output = root / "build/macos"
            macos_output.mkdir(parents=True)
            windows_output = root / "build/windows"
            config = SimpleNamespace(
                git=SimpleNamespace(branch="develop", workdir=root / "repo"),
                unity=SimpleNamespace(builds=[
                    SimpleNamespace(id="macos", output_subdir=macos_output, enabled=True),
                    SimpleNamespace(id="windows", output_subdir=windows_output, enabled=False),
                ]),
                steam=Mock(),
                logging=SimpleNamespace(
                    log_dir=root / "logs",
                    level="INFO",
                    show_activity_window=False,
                ),
                state=SimpleNamespace(state_file=root / "state.json"),
                versioning=SimpleNamespace(short_commit_hash_length=7),
            )
            state_load_mock.return_value = SimpleNamespace(
                last_built_sha="abcdef123456",
                last_version="1.2.3.abcdef1",
                last_branch="develop",
            )
            load_config_mock.return_value = config

            result = cli.upload("config.yaml")

        self.assertEqual(0, result)
        has_new_commit_mock.assert_not_called()
        sync_workdir_mock.assert_not_called()
        build_mock.assert_not_called()
        upload_mock.assert_called_once_with(
            config.steam,
            {"macos": macos_output},
            config.git.workdir,
            build_metadata={
                "version": "1.2.3.abcdef1",
                "branch": "develop",
                "short_sha": "abcdef1",
                "targets": "macos",
            },
        )
        setup_logging_mock.return_value.info.assert_any_call(
            "Upload context (branch=%s, sha=%s)", "develop", "abcdef123456"
        )

    @patch("unity_build_bot.cli.State.load")
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.steam_uploader.upload")
    @patch("unity_build_bot.cli.unity_builder.build")
    @patch("unity_build_bot.cli.git_watcher.sync_workdir")
    @patch("unity_build_bot.cli.git_watcher.has_new_commit")
    @patch("unity_build_bot.cli.load_config")
    def test_run_uses_upload_only_mode_from_config(
        self,
        load_config_mock,
        has_new_commit_mock,
        sync_workdir_mock,
        build_mock,
        upload_mock,
        _setup_logging_mock,
        state_load_mock,
    ):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            macos_output = root / "build/macos"
            macos_output.mkdir(parents=True)
            config = SimpleNamespace(
                git=SimpleNamespace(branch="main", workdir=root / "repo"),
                unity=SimpleNamespace(builds=[
                    SimpleNamespace(id="macos", output_subdir=macos_output, enabled=True),
                ]),
                steam=Mock(),
                versioning=SimpleNamespace(
                    version_file="version.txt",
                    auto_increment=False,
                    short_commit_hash_length=7,
                ),
                logging=SimpleNamespace(
                    log_dir=root / "logs",
                    level="INFO",
                    show_activity_window=False,
                ),
                state=SimpleNamespace(state_file=root / "state.json"),
                job=SimpleNamespace(mode="upload_only"),
            )
            state = SimpleNamespace(
                last_built_sha="old-sha",
                last_version=None,
                last_branch="main",
                last_status=None,
                last_run_at=None,
                save=Mock(),
            )
            load_config_mock.return_value = config
            state_load_mock.return_value = state

            result = cli.run("config.yaml")

        self.assertEqual(0, result)
        has_new_commit_mock.assert_not_called()
        sync_workdir_mock.assert_not_called()
        build_mock.assert_not_called()
        state.save.assert_not_called()
        upload_mock.assert_called_once_with(
            config.steam,
            {"macos": macos_output},
            config.git.workdir,
            build_metadata={
                "version": "unknown",
                "branch": "main",
                "short_sha": "old-sha",
                "targets": "macos",
            },
        )

    @patch("unity_build_bot.cli.State.load")
    @patch("unity_build_bot.cli.setup_logging")
    @patch("unity_build_bot.cli.steam_uploader.upload")
    @patch("unity_build_bot.cli.load_config")
    def test_upload_fails_when_enabled_output_is_missing(
        self,
        load_config_mock,
        upload_mock,
        _setup_logging_mock,
        state_load_mock,
    ):
        config = SimpleNamespace(
            git=SimpleNamespace(workdir=Path("repo")),
            unity=SimpleNamespace(builds=[
                SimpleNamespace(id="macos", output_subdir=Path("missing/macos"), enabled=True),
            ]),
            steam=Mock(),
            logging=SimpleNamespace(
                log_dir=Path("logs"),
                level="INFO",
                show_activity_window=False,
            ),
            state=SimpleNamespace(state_file=Path("state.json")),
        )
        load_config_mock.return_value = config
        state_load_mock.return_value = SimpleNamespace()

        result = cli.upload("config.yaml")

        self.assertEqual(1, result)
        upload_mock.assert_not_called()


class MultiDepotVdfTests(TestCase):
    def test_renders_build_description_metadata(self):
        description = _render_build_description(
            "{version} | {branch} | {short_sha} | {targets} | automated",
            {
                "version": "1.2.3.abcdef1",
                "branch": "develop",
                "short_sha": "abcdef1",
                "targets": "macos,windows",
            },
        )

        self.assertEqual(
            "1.2.3.abcdef1 | develop | abcdef1 | macos,windows | automated",
            description,
        )

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
            self.assertIn(f'"contentroot"\t"{root.resolve()}"', app_contents)
            self.assertIn('"LocalPath"\t"macos/*"', (root / "vdf/depot_101.vdf").read_text())
            self.assertIn('"LocalPath"\t"windows/*"', (root / "vdf/depot_102.vdf").read_text())

    def test_detects_steamcmd_successful_build_line(self):
        output = "[2026-09-24 22:07:50]: Successfully finished AppID 4513280 build (BuildID 25520824)."

        self.assertEqual("25520824", _successful_build_id(output, "4513280"))
        self.assertIsNone(_successful_build_id(output, "999"))
