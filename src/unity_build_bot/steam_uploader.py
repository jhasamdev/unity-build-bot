"""Generate SteamPipe VDF files and run steamcmd to upload a build."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from unity_build_bot.config import SteamConfig
from unity_build_bot.process_runner import run_streaming

logger = logging.getLogger("unity_build_bot")


def _write_vdfs(
    steam_cfg: SteamConfig,
    content_roots: dict[str, Path],
    vdf_dir: Path,
    description: str,
) -> Path:
    vdf_dir.mkdir(parents=True, exist_ok=True)
    app_build_vdf = vdf_dir / "app_build.vdf"
    build_output = vdf_dir / "output"

    depot_entries = []
    for build_id, content_root in content_roots.items():
        depot_id = steam_cfg.depots[build_id]
        depot_vdf = vdf_dir / f"depot_{depot_id}.vdf"
        depot_vdf.write_text(
            f'"DepotBuildConfig"\n{{\n'
            f'\t"DepotID"\t"{depot_id}"\n'
            f'\t"FileMapping"\n\t{{\n'
            f'\t\t"LocalPath"\t"{content_root}/*"\n'
            f'\t\t"DepotPath"\t"."\n'
            f'\t\t"recursive"\t"1"\n\t}}\n}}\n'
        )
        depot_entries.append(f'\t\t"{depot_id}"\t"{depot_vdf}"')

    app_build_vdf.write_text(
        f'"appbuild"\n{{\n'
        f'\t"appid"\t"{steam_cfg.app_id}"\n'
        f'\t"desc"\t"{description}"\n'
        f'\t"buildoutput"\t"{build_output}"\n'
        f'\t"contentroot"\t"{vdf_dir}"\n'
        f'\t"setlive"\t"{steam_cfg.set_live_branch}"\n'
        f'\t"depots"\n\t{{\n'
        f'{chr(10).join(depot_entries)}\n\t}}\n}}\n'
    )

    return app_build_vdf


def upload(
    steam_cfg: SteamConfig,
    content_roots: dict[str, Path],
    workdir_root: Path,
) -> None:
    if not steam_cfg.config_vdf_path.is_file():
        raise RuntimeError(
            f"Steam session file not found at {steam_cfg.config_vdf_path}. "
            "Log in once interactively with `steamcmd +login <user> +quit` to seed it "
            "(see steam-deploy/README.md)."
        )

    description = steam_cfg.build_description or f"unity-build-bot {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
    vdf_dir = workdir_root / ".unity-build-bot" / "vdf"
    app_build_vdf = _write_vdfs(steam_cfg, content_roots, vdf_dir, description)

    steamcmd_log = vdf_dir / "steamcmd.log"
    cmd = [
        str(steam_cfg.steamcmd_path),
        "+login", steam_cfg.username,
        "+run_app_build", str(app_build_vdf),
        "+quit",
    ]

    logger.info(
        "Uploading build to Steam (app=%s, depots=%s, branch=%s)",
        steam_cfg.app_id,
        ", ".join(steam_cfg.depots.values()),
        steam_cfg.set_live_branch or "<none>",
    )
    logger.debug("steamcmd command: %s", " ".join(cmd))
    result = run_streaming(cmd, output_file=steamcmd_log)

    # steamcmd can exit 0 even on a failed login/upload; also check its own output.
    if result.returncode != 0 or "Success!" not in result.stdout:
        raise RuntimeError(
            f"steamcmd did not report a successful upload (exit={result.returncode}); "
            f"see {steamcmd_log}"
        )

    logger.info("Steam upload complete for app %s", steam_cfg.app_id)
