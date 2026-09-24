import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from unity_build_bot.process_runner import run_streaming


class ProcessRunnerTests(TestCase):
    def test_streams_output_to_logger_and_file(self):
        with TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "command.log"
            with patch.object(logging.getLogger("unity_build_bot"), "info") as info_mock:
                result = run_streaming(
                    [sys.executable, "-c", "print('first'); print('second')"],
                    output_file=output_file,
                )

            self.assertEqual(0, result.returncode)
            self.assertEqual("first\nsecond\n", result.stdout)
            self.assertEqual("first\nsecond\n", output_file.read_text())
            info_mock.assert_any_call("%s", "first")
            info_mock.assert_any_call("%s", "second")
