"""Generate SteamPipe VDF files and run steamcmd to upload a build."""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from unity_build_bot.config import SteamConfig

logger = logging.getLogger("unity_build_bot")


def _write_vdfs(steam_cfg: SteamConfig, content_root: Path, vdf_dir: Path, description: str) -> Path:
    vdf_dir.mkdir(parents=True, exist_ok=True)
    depot_vdf = vdf_dir / f"depot_{steam_cfg.depot_id}.vdf"
    app_build_vdf = vdf_dir / "app_build.vdf"
    build_output = vdf_dir / "output"

    depot_vdf.write_text(
        f'"DepotBuildConfig"\n{{\n'
        f'\t"DepotID"\t"{steam_cfg.depot_id}"\n'
        f'\t"FileMapping"\n\t{{\n'
        f'\t\t"LocalPath"\t"{content_root}/*"\n'
        f'\t\t"DepotPath"\t"."\n'
        f'\t\t"recursive"\t"1"\n\t}}\n}}\n'
    )

    app_build_vdf.write_text(
        f'"appbuild"\n{{\n'
        f'\t"appid"\t"{steam_cfg.app_id}"\n'
        f'\t"desc"\t"{description}"\n'
        f'\t"buildoutput"\t"{build_output}"\n'
        f'\t"contentroot"\t"{content_root}"\n'
        f'\t"setlive"\t"{steam_cfg.set_live_branch}"\n'
        f'\t"depots"\n\t{{\n'
        f'\t\t"{steam_cfg.depot_id}"\t"{depot_vdf}"\n\t}}\n}}\n'
    )

    return app_build_vdf


def upload(steam_cfg: SteamConfig, content_root: Path, workdir_root: Path) -> None:
    if not steam_cfg.config_vdf_path.is_file():
        raise RuntimeError(
            f"Steam session file not found at {steam_cfg.config_vdf_path}. "
            "Log in once interactively with `steamcmd +login <user> +quit` to seed it "
            "(see steam-deploy/README.md)."
        )

    description = steam_cfg.build_description or f"unity-build-bot {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
    vdf_dir = workdir_root / ".unity-build-bot" / "vdf"
    app_build_vdf = _write_vdfs(steam_cfg, content_root, vdf_dir, description)

    steamcmd_log = vdf_dir / "steamcmd.log"
    cmd = [
        str(steam_cfg.steamcmd_path),
        "+login", steam_cfg.username,
        "+run_app_build", str(app_build_vdf),
        "+quit",
    ]

    logger.info("Uploading build to Steam (app=%s, depot=%s, branch=%s)",
                steam_cfg.app_id, steam_cfg.depot_id, steam_cfg.set_live_branch or "<none>")
    logger.debug("steamcmd command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    steamcmd_log.write_text(result.stdout + "\n" + result.stderr)

    # steamcmd can exit 0 even on a failed login/upload; also check its own output.
    if result.returncode != 0 or "Success!" not in result.stdout:
        raise RuntimeError(
            f"steamcmd did not report a successful upload (exit={result.returncode}); "
            f"see {steamcmd_log}"
        )

    logger.info("Steam upload complete for depot %s (app %s)", steam_cfg.depot_id, steam_cfg.app_id)
