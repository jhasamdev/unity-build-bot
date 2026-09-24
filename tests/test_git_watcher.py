from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import call, patch

from unity_build_bot.config import GitConfig
from unity_build_bot.git_watcher import sync_workdir


class SyncWorkdirTests(TestCase):
    @patch("unity_build_bot.git_watcher._run")
    def test_clears_existing_directory_before_clone(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "", "")
        with TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir) / "repo"
            workdir.mkdir()
            stale_file = workdir / "stale.txt"
            stale_file.write_text("stale")
            config = GitConfig("git@example/repo.git", "main", workdir)

            sync_workdir(config)

            self.assertFalse(stale_file.exists())
            run_mock.assert_called_once_with([
                "git", "clone", "--branch", "main", "git@example/repo.git", str(workdir)
            ])

    @patch("unity_build_bot.git_watcher._run")
    def test_existing_clone_uses_reset_and_clean(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "", "")
        with TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir) / "repo"
            git_dir = workdir / ".git"
            git_dir.mkdir(parents=True)
            config = GitConfig("git@example/repo.git", "main", workdir)

            sync_workdir(config)

            self.assertTrue(git_dir.is_dir())
            self.assertEqual([
                call(["git", "fetch", "origin", "main"], cwd=workdir),
                call(["git", "reset", "--hard", "origin/main"], cwd=workdir),
                call(["git", "clean", "-xdf"], cwd=workdir),
            ], run_mock.call_args_list)
