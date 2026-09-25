# unity-build-bot

Local, generic job that watches a git branch for new commits, pulls,
builds a Unity project headlessly, and uploads the build to Steam via
SteamPipe (steamcmd). Runs on Windows or macOS, driven by the OS scheduler
(no daemon required).

## Layout

```
config/
  config.example.yaml   # copy to config.yaml (gitignored) and edit
  secrets.example.yaml   # optional, copy to secrets.yaml (gitignored)
src/unity_build_bot/
  cli.py                 # entry point: `run` and `status` subcommands
  config.py              # loads config.yaml, expands ${ENV_VAR}
  git_watcher.py         # ls-remote polling + clean pull
  unity_builder.py        # invokes Unity -batchmode
  steam_uploader.py       # generates vdf + runs steamcmd
  version_file.py         # reads/bumps version.txt
  state.py                # last built SHA / version / status (JSON)
  logging_utils.py        # file + console logging
unity_editor/Editor/BuildScript.cs   # copy into your Unity project's Assets/Editor/
scripts/
  schedule_windows_task.ps1   # registers a Windows Task Scheduler job
  schedule_macos_launchd.sh   # installs a macOS launchd agent
```

## Setup

1. Set up Python using the instructions below.
2. Copy `config/config.example.yaml` to `config/config.yaml` and fill in your repo, Unity, and Steam settings.
3. Copy `unity_editor/Editor/BuildScript.cs` into your Unity project's `Assets/Editor/` folder and commit it there.
4. Ensure the target Unity project's repo root contains a `version.txt` with a starting version (for example, `0.1.0`).
5. Install and initialize SteamCMD using the instructions below.
6. Set up Git authentication. Prefer an SSH deploy key loaded in `ssh-agent`. For HTTPS, set a `GIT_TOKEN` environment variable and use `auth_token_env: "GIT_TOKEN"`.
7. Test one run using the commands in the Python setup section.
8. Install the scheduler only after the manual run succeeds.

### Set up Python

Python 3.10 or newer is required. Run these commands from the repository root.
The project uses `.venv` so its dependencies do not affect the system Python.
Activation is optional because the commands below invoke `.venv` directly.

#### macOS

1. Verify Python is available and is version 3.10 or newer:

  ```bash
  python3 --version
  ```

  If the command is missing or reports an older version, install a current
  Python release from [python.org](https://www.python.org/downloads/macos/)
  or with Homebrew: `brew install python`.

2. Create the virtual environment and install the bot:

  ```bash
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
  ```

3. Confirm that the command was installed:

  ```bash
  .venv/bin/unity-build-bot --help
  ```

4. Copy the example configuration and edit it:

  ```bash
  cp config/config.example.yaml config/config.yaml
  ```

5. Check the configuration and state without starting a build:

  ```bash
  .venv/bin/unity-build-bot status --config config/config.yaml
  ```

6. After completing the Unity and SteamCMD setup, run the job once manually:

  ```bash
  .venv/bin/unity-build-bot run --config config/config.yaml
  ```

7. When the manual run succeeds, install the scheduler:

  ```bash
  chmod +x scripts/schedule_macos_launchd.sh
  ./scripts/schedule_macos_launchd.sh "$(pwd)" 300
  ```

#### Windows PowerShell

1. Verify Python is available and is version 3.10 or newer:

  ```powershell
  py --version
  ```

  If the command is missing or reports an older version, install a current
  Python release from [python.org](https://www.python.org/downloads/windows/).
  During installation, enable the Python launcher and add Python to `PATH`.

2. Create the virtual environment and install the bot:

  ```powershell
  py -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -e .
  ```

3. Confirm that the command was installed:

  ```powershell
  .\.venv\Scripts\unity-build-bot.exe --help
  ```

4. Copy the example configuration and edit it:

  ```powershell
  Copy-Item config\config.example.yaml config\config.yaml
  ```

5. Check the configuration and state without starting a build:

  ```powershell
  .\.venv\Scripts\unity-build-bot.exe status --config config\config.yaml
  ```

6. After completing the Unity and SteamCMD setup, run the job once manually:

  ```powershell
  .\.venv\Scripts\unity-build-bot.exe run --config config\config.yaml
  ```

7. When the manual run succeeds, install the scheduler:

  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\schedule_windows_task.ps1
  ```

Both scheduler scripts use the Python interpreter inside `.venv`. Do not
delete or move `.venv` after installing the scheduled job; recreate the job
if the repository is moved.

### Set up SteamCMD

SteamCMD needs a one-time interactive login before the bot can upload builds
without supervision. Use a dedicated Steam build account that has permission
to upload the configured app and depots.

#### macOS

1. Create a dedicated installation directory and download SteamCMD:

    ```bash
    mkdir -p ~/steamcmd
    cd ~/steamcmd
    curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz | tar -xz
    ```

2. Start SteamCMD and log in once:

    ```bash
    ~/steamcmd/steamcmd.sh +login <builder_account> +quit
    ```

3. Enter the account password and Steam Guard code when prompted. Never put
    the password or Steam Guard code in `config.yaml`.

4. Verify the executable and cached session:

    ```bash
    test -x ~/steamcmd/steamcmd.sh && echo "SteamCMD is installed"
    test -f "$HOME/Library/Application Support/Steam/config/config.vdf" && echo "Steam session is ready"
    ```

5. Configure the matching paths:

   ```yaml
   steam:
     steamcmd_path: "~/steamcmd/steamcmd.sh"
     config_vdf_path: "~/Library/Application Support/Steam/config/config.vdf"
     username: "your-steam-builder-account"
   ```

#### Windows PowerShell

1. Create a dedicated installation directory and download SteamCMD:

   ```powershell
   New-Item -ItemType Directory -Force C:\steamcmd | Out-Null
   Invoke-WebRequest `
     https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip `
     -OutFile C:\steamcmd\steamcmd.zip
   Expand-Archive C:\steamcmd\steamcmd.zip C:\steamcmd -Force
   ```

2. Start SteamCMD and log in once:

    ```powershell
    C:\steamcmd\steamcmd.exe +login <builder_account> +quit
    ```

3. Enter the account password and Steam Guard code when prompted. Never put
    the password or Steam Guard code in `config.yaml`.

4. Verify the executable and cached session:

    ```powershell
    Test-Path C:\steamcmd\steamcmd.exe
    Test-Path C:\steamcmd\config\config.vdf
    ```

5. Configure the matching paths. Forward slashes avoid YAML escaping issues:

   ```yaml
   steam:
     steamcmd_path: "C:/steamcmd/steamcmd.exe"
     config_vdf_path: "C:/steamcmd/config/config.vdf"
     username: "your-steam-builder-account"
   ```

The scheduled task must run as the same operating-system user that performed
the SteamCMD login. If Steam invalidates the cached session, repeat the login
command and complete Steam Guard again. You can then rerun the bot without
changing its configuration.

### Configure platform builds

Add one entry to `unity.builds` for each platform. Set `enabled` to select
macOS, Windows, or both without removing either definition. Each build needs
a unique ID, Unity build target, output directory, and output name. Map the
enabled IDs to Steam depot IDs under `steam.depots`. The bot builds every
enabled entry first, then uploads their depots together as one Steam app build.

```yaml
unity:
  builds:
    - id: macos
      enabled: true
      build_target: StandaloneOSX
      output_subdir: workspace/build/macos
      build_name: Game
    - id: windows
      enabled: false
      build_target: StandaloneWindows64
      output_subdir: workspace/build/windows
      build_name: Game

steam:
  depots:
    macos: "123457"
```

  Set only `macos.enabled` to `true` for macOS, only `windows.enabled` to `true`
  for Windows, or both to `true` to build both platforms. An enabled build must
  have a matching depot; disabled builds may omit their depot mapping.

Install the macOS and Windows build-support modules for the configured Unity
Editor version. Existing configs with one `build_target`, `output_subdir`,
`build_name`, and `depot_id` remain supported.

### Test without installing the bot

From the repository root, set `PYTHONPATH` to the `src` directory and invoke
the module directly. This requires Python and the runtime dependency
`PyYAML`, but does not require installing the bot package.

On macOS or Linux:

```bash
export PYTHONPATH="$PWD/src"
python3 -m unity_build_bot status --config config/config.yaml
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\src"
py -m unity_build_bot status --config config/config.yaml
```

The `status` command safely checks that the source tree and configuration are
usable. To run the actual job once, replace `status` with `run`; this can pull
the Unity project, build it, and upload it to Steam.

### Live activity window

Enable the optional terminal window in `config.yaml`:

```yaml
logging:
  show_activity_window: true
```

The window displays Git cloning and synchronization, Unity build output,
SteamCMD upload output, and the bot's status messages in real time. It closes
when the bot process finishes. The normal daily log remains available under
`logging.log_dir` whether or not the window is enabled.

The window requires an active logged-in desktop session. Scheduled jobs that
run while the user is logged out cannot display UI, but they continue writing
to the log file normally.

## Notes / design decisions

- **No secrets in config.yaml.** `config.yaml` and `secrets.yaml` are gitignored; use `${ENV_VAR}` placeholders or the OS keychain for anything sensitive.
- **Logs are kept outside git** (default `~/.unity-build-bot/logs`), not committed to the game repo, to avoid leaking machine paths/usernames and repo bloat.
- **Polling, not a webhook**, for simplicity — `git ls-remote` is cheap and doesn't require inbound networking on the build machine.
- **Platform support is required.** The Unity installation running the job must include a build-support module for every target in `unity.builds`.
- **The complete workspace is disposable.** Before each build synchronization, the bot deletes `git.workspace_root`, recreates it, and freshly clones the repository into `git.workdir`. Build outputs inside the workspace are also removed. Keep no files there that are not safe to delete.
