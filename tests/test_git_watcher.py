from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.config import GitConfig
from unity_build_bot.git_watcher import _clear_workspace, sync_workdir


class SyncWorkdirTests(TestCase):
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
