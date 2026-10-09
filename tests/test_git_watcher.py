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
                sync_workdir(config, first_run=True, branch_changed=False)

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
        self.assertIn("AUTHORIZATION: basic ", kwargs["env"]["GIT_CONFIG_VALUE_0"])
        self.assertEqual("0", kwargs["env"]["GIT_TERMINAL_PROMPT"])

    @patch("unity_build_bot.git_watcher._run")
    def test_git_failure_includes_combined_command_output(self, run_mock):
        run_mock.return_value = CompletedProcess([], 128, "authentication failed", "")
        config = GitConfig("git@example/repo.git", "main", Path("repo"), Path("workspace"))

        with self.assertRaisesRegex(RuntimeError, "git ls-remote failed: authentication failed"):
            remote_head_sha(config)

    @patch("unity_build_bot.git_watcher._run")
    def test_missing_remote_branch_is_rejected(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "", "")
        config = GitConfig("git@example/repo.git", "missing", Path("repo"), Path("workspace"))

        with self.assertRaisesRegex(RuntimeError, "Branch 'missing' not found"):
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

            sync_workdir(config, first_run=True, branch_changed=False)

            self.assertFalse(stale_file.exists())
            self.assertFalse(stale_build.exists())
            self.assertTrue(workspace_root.is_dir())
            run_mock.assert_called_once_with([
                "git", "clone", "--progress", "--branch", "main",
                "git@example/repo.git", str(workdir.resolve()),
            ])

    @patch("unity_build_bot.git_watcher._run")
    def test_existing_state_with_other_remote_recovers_with_clean_clone(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "git@example/other.git\n", "")
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = workspace_root / "repo"
            git_dir = workdir / ".git"
            git_dir.mkdir(parents=True)
            config = GitConfig("git@example/repo.git", "main", workdir, workspace_root)

            sync_workdir(config, first_run=False, branch_changed=False)

            self.assertFalse(git_dir.exists())
            self.assertEqual(
                ["git", "clone", "--progress", "--branch", "main", "git@example/repo.git", str(workdir.resolve())],
                run_mock.call_args.args[0],
            )

    @patch("unity_build_bot.git_watcher._run")
    def test_existing_clone_is_updated_in_place(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "git@example/repo.git\n", "")
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = (workspace_root / "repo").resolve()
            (workdir / ".git").mkdir(parents=True)
            kept = workdir / "Library"
            kept.mkdir()
            config = GitConfig("git@example/repo.git", "main", workdir, workspace_root)

            sync_workdir(config, first_run=False, branch_changed=False)

            self.assertTrue(kept.is_dir())
            self.assertEqual(
                [
                    ["git", "-C", str(workdir), "remote", "get-url", "origin"],
                    [
                        "git", "-C", str(workdir), "reset", "--hard",
                    ],
                    [
                        "git", "-C", str(workdir), "clean", "-ffd",
                    ],
                    [
                        "git", "-C", str(workdir), "checkout", "--force", "-B", "main",
                    ],
                    [
                        "git", "-C", str(workdir), "pull", "--ff-only", "--progress",
                        "origin", "main",
                    ],
                ],
                [call.args[0] for call in run_mock.call_args_list],
            )

    @patch("unity_build_bot.git_watcher._run")
    def test_branch_change_fetches_and_checks_out_configured_branch(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "git@example/repo.git\n", "")
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = (workspace_root / "repo").resolve()
            (workdir / ".git").mkdir(parents=True)
            config = GitConfig("git@example/repo.git", "develop", workdir, workspace_root)
            build_output = workspace_root / "build" / "macos"
            build_output.mkdir(parents=True)
            (build_output / "old.app").write_text("old output")

            sync_workdir(
                config,
                first_run=False,
                branch_changed=True,
                build_outputs=[build_output],
            )

        self.assertFalse(build_output.exists())
        self.assertEqual(
            [
                ["git", "-C", str(workdir), "remote", "get-url", "origin"],
                ["git", "-C", str(workdir), "reset", "--hard"],
                ["git", "-C", str(workdir), "clean", "-ffd"],
                [
                    "git", "-C", str(workdir), "fetch", "--progress",
                    "origin", "develop",
                ],
                [
                    "git", "-C", str(workdir), "checkout", "--force", "-B",
                    "develop", "FETCH_HEAD",
                ],
            ],
            [call.args[0] for call in run_mock.call_args_list],
        )

    @patch("unity_build_bot.git_watcher._run")
    def test_existing_clone_update_failure_does_not_clone_or_clear_workspace(self, run_mock):
        run_mock.side_effect = [
            CompletedProcess([], 0, "git@example/repo.git\n", ""),
            CompletedProcess([], 1, "network unavailable", ""),
        ]
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = (workspace_root / "repo").resolve()
            (workdir / ".git").mkdir(parents=True)
            marker = workdir / "preserved.marker"
            marker.write_text("keep workspace for retry")
            config = GitConfig("git@example/repo.git", "main", workdir, workspace_root)

            with self.assertRaisesRegex(RuntimeError, "git reset failed: network unavailable"):
                sync_workdir(config, first_run=False, branch_changed=False)

            self.assertTrue(marker.is_file())
            self.assertEqual(2, run_mock.call_count)

    @patch("unity_build_bot.git_watcher._run")
    def test_branch_checkout_failure_suggests_clean_reinitialization(self, run_mock):
        run_mock.side_effect = [
            CompletedProcess([], 0, "git@example/repo.git\n", ""),
            CompletedProcess([], 0, "", ""),
            CompletedProcess([], 0, "", ""),
            CompletedProcess([], 0, "", ""),
            CompletedProcess([], 1, "ignored file blocks checkout", ""),
        ]
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = (workspace_root / "repo").resolve()
            (workdir / ".git").mkdir(parents=True)
            config = GitConfig("git@example/repo.git", "develop", workdir, workspace_root)

            with self.assertRaisesRegex(RuntimeError, "remove the configured state file"):
                sync_workdir(config, first_run=False, branch_changed=True)

            self.assertEqual(5, run_mock.call_count)
            self.assertTrue((workdir / ".git").is_dir())

    @patch("unity_build_bot.git_watcher._run")
    def test_first_run_always_clears_and_clones(self, run_mock):
        run_mock.return_value = CompletedProcess([], 0, "git@example/repo.git\n", "")
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspace"
            workdir = workspace_root / "repo"
            (workdir / ".git").mkdir(parents=True)
            config = GitConfig("git@example/repo.git", "main", workdir, workspace_root)

            sync_workdir(config, first_run=True, branch_changed=False)

            run_mock.assert_called_once_with([
                "git", "clone", "--progress", "--branch", "main",
                "git@example/repo.git", str(workdir.resolve()),
            ])
