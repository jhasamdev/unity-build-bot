import os
import plistlib
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


class MacSchedulerTests(TestCase):
    def test_distinct_configs_have_independent_agents(self):
        script = Path(__file__).resolve().parents[1] / "scripts/schedule_macos_launchd.sh"
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool_path = root / "bot"
            config_dir = tool_path / "config"
            config_dir.mkdir(parents=True)
            for name in ("config.yaml", "mac&steam.yaml", "windows.yaml"):
                (config_dir / name).touch()
            python_path = tool_path / ".venv/bin/python"
            python_path.parent.mkdir(parents=True)
            python_path.write_text("#!/bin/sh\nexit 0\n")
            python_path.chmod(0o755)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            launchctl = bin_dir / "launchctl"
            launchctl.write_text("#!/bin/sh\nexit 0\n")
            launchctl.chmod(0o755)
            env = {**os.environ, "HOME": str(root / "home"), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
            agents = root / "home/Library/LaunchAgents"

            def schedule(*args):
                subprocess.run(["bash", str(script), *args], env=env, check=True, capture_output=True, text=True)

            schedule(str(tool_path), "300")
            schedule(str(tool_path), "300", "config/mac&steam.yaml")
            schedule(str(tool_path), "600", "config/windows.yaml")
            default_agent = agents / "com.unitybuildbot.run.plist"
            self.assertTrue(default_agent.exists())
            custom_agents = [path for path in agents.glob("*.plist") if path != default_agent]
            configs = {
                plistlib.loads(path.read_bytes())["ProgramArguments"][-1]: path
                for path in custom_agents
            }
            macos_config = str((config_dir / "mac&steam.yaml").resolve())
            windows_config = str((config_dir / "windows.yaml").resolve())
            self.assertEqual({macos_config, windows_config}, set(configs))
            self.assertNotEqual(
                plistlib.loads(configs[macos_config].read_bytes())["StandardOutPath"],
                plistlib.loads(configs[windows_config].read_bytes())["StandardOutPath"],
            )

            schedule("--uninstall", str(tool_path), "config/mac&steam.yaml")
            self.assertFalse(configs[macos_config].exists())
            self.assertTrue(configs[windows_config].exists())
            schedule("--uninstall", str(tool_path))
            self.assertFalse(default_agent.exists())
            self.assertTrue(configs[windows_config].exists())