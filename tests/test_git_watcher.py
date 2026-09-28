from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.config import GitConfig
from unity_build_bot.git_watcher import (
    _clear_workspace,
    remote_head_sha,
    remove_workspace,
    sync_workdir,
)


class SyncWorkdirTests(TestCase):
    def test_refuses_workspace_that_contains_project_directory(self):
        workspace_root = Path(__file__).resolve().parents[2]
        config = GitConfig(
            "git@example/repo.git",
            "main",
            workspace_root / "workspace" / "repo",
            workspace_root,
        )

        with patch("unity_build_bot.git_watcher._run") as run_mock:
            with self.assertRaisesRegex(RuntimeError, "protected directory"):
                sync_workdir(config)

        run_mock.assert_not_called()

    @patch("unity_build_bot.git_watcher._run")
    def test_https_token_is_passed_in_git_environment(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "abc123\trefs/heads/main\n", "")
        config = GitConfig(
            "https://github.com/example/repo.git",
            "main",
            Path("workspace/repo"),
            Path("workspace"),
            auth_token_env="GIT_TOKEN",
            auth_token="secret-token",
        )

        with patch("unity_build_bot.git_watcher.logger.info") as info_mock:
            sha = remote_head_sha(config)

        self.assertEqual("abc123", sha)
        info_mock.assert_called_once_with("Git remote head (branch=%s, sha=%s)", "main", "abc123")
        args, kwargs = run_mock.call_args
        self.assertNotIn("secret-token", " ".join(args[0]))
        auth_values = [
            value
            for key, value in kwargs["env"].items()
            if key.startswith("GIT_CONFIG_VALUE_")
        ]
        self.assertTrue(any("AUTHORIZATION: basic " in value for value in auth_values))
        self.assertEqual("0", kwargs["env"]["GIT_TERMINAL_PROMPT"])

    @patch("unity_build_bot.git_watcher._run")
    def test_git_failure_includes_combined_command_output(self, run_mock):
        run_mock.return_value = CompletedProcess([], 128, "authentication failed", "")
        config = GitConfig("git@example/repo.git", "main", Path("repo"), Path("workspace"))

        with self.assertRaisesRegex(RuntimeError, "git ls-remote failed: authentication failed"):
            remote_head_sha(config)

    def test_detaches_workspace_before_recursive_delete(self):
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workspace_root.mkdir()
            (workspace_root / ".DS_Store").write_text("metadata")

            with patch("unity_build_bot.git_watcher.shutil.rmtree") as rmtree_mock:
                _clear_workspace(workspace_root)

            cleanup_root = rmtree_mock.call_args.args[0]
            self.assertNotEqual(workspace_root, cleanup_root)
            self.assertTrue(workspace_root.is_dir())
            self.assertFalse(any(workspace_root.iterdir()))
            self.assertTrue((cleanup_root / ".DS_Store").is_file())

    def test_removes_workspace_after_run(self):
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            (workspace_root / "repo").mkdir(parents=True)
            (workspace_root / "repo" / "build.txt").write_text("build")

            remove_workspace(workspace_root)

            self.assertFalse(workspace_root.exists())

    @patch("unity_build_bot.git_watcher._run")
    def test_clears_existing_directory_before_clone(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "", "")
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = workspace_root / "repo"
            workdir.mkdir(parents=True)
            stale_file = workdir / "stale.txt"
            stale_file.write_text("stale")
            stale_build = workspace_root / "build" / "stale.app"
            stale_build.parent.mkdir()
            stale_build.write_text("stale")
            config = GitConfig("git@example/repo.git", "main", workdir, workspace_root)

            sync_workdir(config)

            self.assertFalse(stale_file.exists())
            self.assertFalse(stale_build.exists())
            self.assertTrue(workspace_root.is_dir())
            run_mock.assert_called_once_with([
                "git", "clone", "--progress", "--branch", "main",
                "git@example/repo.git", str(workdir.resolve()),
            ])

    @patch("unity_build_bot.git_watcher._run")
    def test_existing_clone_is_replaced_with_fresh_clone(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "", "")
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = workspace_root / "repo"
            git_dir = workdir / ".git"
            git_dir.mkdir(parents=True)
            config = GitConfig("git@example/repo.git", "main", workdir, workspace_root)

            sync_workdir(config)

            self.assertFalse(git_dir.exists())
            run_mock.assert_called_once_with([
                "git", "clone", "--progress", "--branch", "main",
                "git@example/repo.git", str(workdir.resolve()),
            ])
