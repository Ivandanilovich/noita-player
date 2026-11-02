"""Launches Noita with the state-bridge mod installed and listens for heartbeats.

The bridge runs inside the game as a local mod (<game dir>/mods/noita_player).
This launcher keeps it in sync from lua/bot_bridge.lua, then starts the game
windowed and prints state snapshots as they arrive.

Usage:
    python -m noita_bot.launcher               # install mod + start game + listen
    python -m noita_bot.launcher --listen-only # just listen (game started elsewhere)
    python -m noita_bot.launcher --duration 60 # stop after 60 s
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

GAME_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\noita")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_LUA = PROJECT_ROOT / "lua" / "bot_bridge.lua"
MOD_XML_SRC = PROJECT_ROOT / "lua" / "mod.xml"
COMPAT_XML_SRC = PROJECT_ROOT / "lua" / "compatibility.xml"
MOD_DIR = GAME_DIR / "mods" / "noita_player"
# Folder name is what Noita uses as the mod identity in mod_config.xml.
MOD_NAME = "noita_player"
# NOTE: per-save data lives under AppData\LocalLow (a SIBLING of Roaming/Local),
# not under either of those dirs.
NOITA_DATA_DIR = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "Nolla_Games_Noita"


def install_mod() -> None:
    """Copy the bridge + mod metadata into the game's mods folder (idempotent)."""
    for src, dst_name in (
        (BRIDGE_LUA, "init.lua"),
        (MOD_XML_SRC, "mod.xml"),
        (COMPAT_XML_SRC, "compatibility.xml"),
    ):
        if not src.exists():
            sys.exit(f"missing mod source file: {src}")
        MOD_DIR.mkdir(parents=True, exist_ok=True)
        dst = MOD_DIR / dst_name
        data = src.read_bytes()
        if not (dst.exists() and dst.read_bytes() == data):
            dst.write_bytes(data)
            print(f"[launcher] installed mod file -> {dst}", flush=True)


def _mod_config_entry(enabled: str) -> str:
    # Matches the exact format Noita itself writes into mod_config.xml.
    return (
        f'\n  <Mod enabled="{enabled}" name="{MOD_NAME}" '
        'settings_fold_open="0" workshop_item_id="0" >\n\n  </Mod>\n'
    )


def enable_mod_in_saves() -> None:
    """Enable our mod in every save slot's mod_config.xml.

    Noita registers newly discovered local mods as DISABLED (enabled="0")
    until the user toggles them once in the Mods menu. We flip the flag here
    so `python -m noita_bot.launcher` is fully zero-touch. The game rewrites
    these files on exit, so this must run while noita.exe is not running.
    """
    if not NOITA_DATA_DIR.exists():
        print(f"[launcher] note: {NOITA_DATA_DIR} not found; skipping mod enable", flush=True)
        return
    entry_re = re.compile(r'<Mod\s[^>]*name="%s"[^>]*>' % re.escape(MOD_NAME))

    def _flip(m: "re.Match[str]") -> str:
        tag = m.group(0)
        if 'enabled="1"' in tag:
            return tag
        if 'enabled="' in tag:
            return re.sub(r'enabled="\d+"', 'enabled="1"', tag, count=1)
        return tag[:-1].rstrip() + ' enabled="1">'

    for save_dir in sorted(NOITA_DATA_DIR.glob("save*")):
        cfg = save_dir / "mod_config.xml"
        if cfg.exists():
            text = cfg.read_text(encoding="utf-8")
            new_text, n = entry_re.subn(_flip, text)
            if n == 0 and "</Mods>" in text:
                new_text = text.replace("</Mods>", _mod_config_entry("1") + "</Mods>")
            if new_text != text:
                cfg.write_text(new_text, encoding="utf-8")
                print(f"[launcher] enabled mod in {cfg}", flush=True)
        else:
            cfg.write_text("<Mods>" + _mod_config_entry("1") + "\n</Mods>\n", encoding="utf-8")
            print(f"[launcher] created {cfg} with mod enabled", flush=True)



def launch_game() -> subprocess.Popen:
    exe = GAME_DIR / "noita.exe"
    if not exe.exists():
        sys.exit(f"Noita not found at {exe}")
    install_mod()
    enable_mod_in_saves()
    cmd = [str(exe), "-windowed"]
    print("[launcher] starting:", " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(GAME_DIR))


def _name_of(e: dict) -> str:
    v = e.get("name")
    return str(v) if v else "?"


def _dist_of(e: dict) -> str:
    v = e.get("dist")
    return str(v) if v is not None else "?"


def render_dashboard(s, stale: bool) -> str:
    """One dashboard frame as text (caller adds ANSI clear/home on TTY)."""
    status = "STALE (paused/menu?)" if stale else "LIVE"
    pos = f"({s.px:.0f},{s.py:.0f})" if s.px is not None and s.py is not None else "n/a"
    if s.hp is not None and s.max_hp is not None:
        hp = f"{s.hp:.0f}/{s.max_hp:.0f}"
    elif s.hp is not None:
        hp = f"{s.hp:.0f}"
    else:
        hp = "n/a"
    lines = [
        f"Noita bot — {status}   frame={s.frame}  t={s.t:.1f}s  via={s.mode}",
        f"pos={pos}  alive={s.alive}  hp={hp}  biome={s.biome or 'n/a'}",
    ]
    inv = ", ".join(s.inventory[:8]) if s.inventory else "(empty)"
    lines.append(f"inventory: {inv}")
    if s.enemies:
        top = ", ".join(f"{_name_of(e)}@{_dist_of(e)}" for e in s.enemies[:5])
        lines.append(f"enemies ({len(s.enemies)} nearby): {top}")
    else:
        lines.append("enemies: none nearby")
    if s.ground_items:
        g = ", ".join(f"{_name_of(e)}@{_dist_of(e)}" for e in s.ground_items[:5])
        lines.append(f"ground items: {g}")
    return "\n".join(lines)


def listen(duration: float | None = None) -> None:
    from .state_server import StateServer

    server = StateServer()
    server.start()
    end = time.time() + duration if duration else None
    use_tty = sys.stdout.isatty()
    if use_tty and os.name == "nt":
        os.system("")  # enables ANSI/VT escape processing in the Windows console
    try:
        diag_logged = False

        def _maybe_log_diag() -> None:
            nonlocal diag_logged
            d = server.latest.raw.get("diag")
            if not diag_logged and d:
                print("[launcher] DIAG: " + json.dumps(d), flush=True)
                diag_logged = True

        if use_tty:
            print("[launcher] listening for Noita state... live dashboard below.")
            print("          In the game, start a NEW GAME. Ctrl+C to stop.", flush=True)
            while end is None or time.time() < end:
                time.sleep(0.2)  # ~5 Hz redraw
                _maybe_log_diag()
                screen = "\x1b[2J\x1b[H" + render_dashboard(server.latest, server.stale)
                print(screen, flush=True)
        else:
            print("[launcher] listening for Noita state...", flush=True)
            print("          In the game, start a NEW GAME. State appears below.", flush=True)
            last_print = 0.0
            warned_stale = False
            while end is None or time.time() < end:
                time.sleep(0.5)
                _maybe_log_diag()
                s = server.latest
                if s.frame > 0 and (time.time() - last_print) >= 2.0:
                    block = render_dashboard(s, server.stale).replace("\n", "\n    ")
                    print(f"  [{time.strftime('%H:%M:%S')}] {block}", flush=True)
                    last_print = time.time()
                    warned_stale = False
                elif server.stale and s.frame > 0 and not warned_stale:
                    print("  (no updates for a while - paused or in menu?)", flush=True)
                    warned_stale = True
    finally:
        server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listen-only",
        action="store_true",
        help="don't launch the game; just listen (game must be started separately)",
    )
    parser.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    args = parser.parse_args()

    if not args.listen_only:
        launch_game()
    else:
        # Game started elsewhere (e.g. from Steam): still make sure the mod is
        # installed and enabled for this save slot.
        install_mod()
        enable_mod_in_saves()
    try:
        listen(args.duration)
    except KeyboardInterrupt:
        print("\n[launcher] stopped.")


if __name__ == "__main__":
    main()
