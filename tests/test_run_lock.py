from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.run_lock import RunLock


class RunLockTests(TestCase):
    def test_second_lock_skips_active_run(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".run.lock"
            first = RunLock(path)
            second = RunLock(path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_stale_lock_is_replaced(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".run.lock"
            path.mkdir()
            path.joinpath("pid").write_text("999999999")

            lock = RunLock(path)

            self.assertTrue(lock.acquire())
            lock.release()

    def test_stale_windows_pid_error_is_replaced(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".run.lock"
            path.mkdir()
            path.joinpath("pid").write_text("456")

            lock = RunLock(path)
            stale_pid_error = OSError()
            stale_pid_error.winerror = 87

            with (
                patch("unity_build_bot.run_lock.os.getpid", return_value=123),
                patch("unity_build_bot.run_lock.os.kill", side_effect=stale_pid_error),
            ):
                self.assertTrue(lock.acquire())
                self.assertEqual("123", path.joinpath("pid").read_text())
                lock.release()