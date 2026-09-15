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

1. `python -m venv .venv && source .venv/bin/activate` (or `.venv\Scripts\activate` on Windows)
2. `pip install -e .`
3. `cp config/config.example.yaml config/config.yaml` and fill in your repo, Unity, and Steam settings.
4. Copy `unity_editor/Editor/BuildScript.cs` into your Unity project's `Assets/Editor/` folder and commit it there.
5. Ensure the target Unity project's repo root contains a `version.txt` with a starting version (e.g. `0.1.0`).
6. Seed the Steam session once, locally: `steamcmd +login <builder_account> +quit`, solving the Steam Guard prompt — this writes the `config.vdf` referenced by `steam.config_vdf_path`.
7. Set up git auth: prefer an SSH deploy key loaded in `ssh-agent` for the builder machine (read-only access to the repo). For HTTPS, set a `GIT_TOKEN` environment variable and reference it via `auth_token_env`.
8. Test a single run: `python -m unity_build_bot run --config config/config.yaml`
9. Check status any time: `python -m unity_build_bot status --config config/config.yaml`
10. Install the scheduler:
    - Windows: `powershell scripts/schedule_windows_task.ps1`
    - macOS: `./scripts/schedule_macos_launchd.sh "$(pwd)" 300`

## Notes / design decisions

- **No secrets in config.yaml.** `config.yaml` and `secrets.yaml` are gitignored; use `${ENV_VAR}` placeholders or the OS keychain for anything sensitive.
- **Logs are kept outside git** (default `~/.unity-build-bot/logs`), not committed to the game repo, to avoid leaking machine paths/usernames and repo bloat.
- **Polling, not a webhook**, for simplicity — `git ls-remote` is cheap and doesn't require inbound networking on the build machine.
- **One job per OS/build target.** Unity licensing and native builds are per-machine; run this tool separately on your Windows box (for `StandaloneWindows64`) and your Mac (for `StandaloneOSX`), each with its own `config.yaml` and depot ID.
- **Workspace is force-synced** (`git reset --hard` + `git clean -xdf`) before every build for reproducibility — don't keep uncommitted local changes in the watched repo's working copy.
