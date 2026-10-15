from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.config import UnityBuildConfig, UnityConfig
from unity_build_bot.unity_builder import build


class UnityBuilderTests(TestCase):
    def _configs(self, root: Path, output_dir: Path):
        build_config = UnityBuildConfig(
            id="macos",
            build_target="StandaloneOSX",
            output_subdir=output_dir,
            build_name="Game",
        )
        unity_config = UnityConfig(
            executable_path=Path("/Applications/Unity"),
            project_subpath=".",
            build_method="BuildScript.PerformBuild",
            builds=[build_config],
        )
        return unity_config, build_config

    def test_clears_old_output_and_requires_new_app_bundle(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "repo"
            project.mkdir()
            output_dir = root / "workspace" / "build" / "macos"
            output_dir.mkdir(parents=True)
            (output_dir / "old-build.txt").write_text("stale")
            unity_config, build_config = self._configs(root, output_dir)

            def successful_build(cmd, output_file):
                self.assertEqual([], list(output_dir.iterdir()))
                self.assertEqual(
                    output_dir.parent / "macos.unity_editor.log",
                    output_file,
                )
                (output_dir / "Game.app").mkdir()
                return CompletedProcess(cmd, 0, "", "")

            with patch(
                "unity_build_bot.unity_builder.run_streaming",
                side_effect=successful_build,
            ):
                build(unity_config, build_config, project, "1.2.3")

            self.assertTrue((output_dir / "Game.app").is_dir())
            self.assertFalse((output_dir / "old-build.txt").exists())
            self.assertFalse((output_dir / "unity_editor.log").exists())

    def test_success_without_expected_artifact_fails_before_upload(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "repo"
            project.mkdir()
            output_dir = root / "workspace" / "build" / "macos"
            unity_config, build_config = self._configs(root, output_dir)

            with patch(
                "unity_build_bot.unity_builder.run_streaming",
                return_value=CompletedProcess([], 0, "", ""),
            ):
                with self.assertRaisesRegex(RuntimeError, "expected output is missing"):
                    build(unity_config, build_config, project, "1.2.3")

    def test_refuses_output_directory_that_contains_project(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "workspace" / "repo"
            project.mkdir(parents=True)
            unity_config, build_config = self._configs(root, root / "workspace")

            with patch("unity_build_bot.unity_builder.run_streaming") as run_mock:
                with self.assertRaisesRegex(RuntimeError, "must not contain the Unity project"):
                    build(unity_config, build_config, project, "1.2.3")

            self.assertTrue(project.is_dir())
            run_mock.assert_not_called()