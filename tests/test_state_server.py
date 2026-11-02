"""Smoke tests for the state bridge (no game required).

Run:  python -m pytest tests/ -q     or     python tests/test_state_server.py
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from noita_bot.state_server import StateServer  # noqa: E402


def test_udp_roundtrip() -> None:
    """Simulate exactly what bot_bridge.lua sends (sorted keys, %.10g numbers)."""
    # start from a clean slate so a stale bridge file cannot fake a pass
    try:
        os.remove(StateServer.FILE_FALLBACK)
    except OSError:
        pass
    server = StateServer()
    server.start()
    try:
        payload = {
            "alive": True,
            "frame": 123456789,
            "mode": "udp",
            "px": 5234.678901,
            "py": -120.5,
            "t": 87.345678,
            "v": 1,
        }
        # Lua's json_encode sorts object keys; replicate that for realism.
        raw = json.dumps(payload, sort_keys=True).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(raw, (server.host, server.port))

        deadline = time.time() + 3.0
        while server.latest.frame == 0 and time.time() < deadline:
            time.sleep(0.05)

        st = server.latest
        assert st.frame == payload["frame"], st
        assert abs(st.px - payload["px"]) < 1e-6, st
        assert abs(st.py - payload["py"]) < 1e-6, st
        assert st.alive is True
        assert st.mode == "udp"
        assert not server.stale
        print("UDP round-trip OK:", st)
        sock.close()
    finally:
        server.close()


def test_file_fallback_roundtrip() -> None:
    """If Lua lacks sockets, the bridge writes %TEMP%\\noita_bot_state.json."""
    try:
        os.remove(StateServer.FILE_FALLBACK)
    except OSError:
        pass
    server = StateServer()
    server.start()
    try:
        payload = {"alive": False, "frame": 42, "mode": f"file:{StateServer.FILE_FALLBACK}", "t": 1.0, "v": 1}
        with open(StateServer.FILE_FALLBACK, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))

        deadline = time.time() + 3.0
        while server.latest.frame == 0 and time.time() < deadline:
            time.sleep(0.05)

        st = server.latest
        assert st.frame == 42, st
        assert st.alive is False
        # v=1 payload: Phase 1 fields must fall back to defaults
        assert st.hp is None and st.max_hp is None, st
        assert st.biome == ""
        assert st.inventory == [] and st.enemies == [] and st.ground_items == []
        print("File fallback OK:", st)
    finally:
        server.close()
        try:
            os.remove(StateServer.FILE_FALLBACK)
        except OSError:
            pass


def test_v2_payload_file() -> None:
    """Phase 1 payload: hp/biome/inventory/enemies/ground_items parse correctly."""
    try:
        os.remove(StateServer.FILE_FALLBACK)
    except OSError:
        pass
    server = StateServer()
    server.start()
    try:
        payload = {
            "v": 2,
            "mode": f"file:{StateServer.FILE_FALLBACK}",
            "frame": 987654321,
            "t": 42.5,
            "alive": True,
            "px": 250.25,
            "py": -75.5,
            "hp": 85.0,
            "max_hp": 100.0,
            "biome": "Surface",
            "inventory": ["torch", "wooden sword"],
            "enemies": [
                {"name": "goblin", "dist": 120, "hp": 50.0},
                {"name": "slime", "dist": 340},
            ],
            "ground_items": [{"name": "potion", "dist": 12}],
        }
        with open(StateServer.FILE_FALLBACK, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))

        deadline = time.time() + 3.0
        while server.latest.frame != payload["frame"] and time.time() < deadline:
            time.sleep(0.05)

        st = server.latest
        assert st.frame == payload["frame"], st
        assert st.px == 250.25 and st.py == -75.5, st
        assert st.hp == 85.0 and st.max_hp == 100.0, st
        assert st.biome == "Surface", st
        assert st.inventory == ["torch", "wooden sword"], st
        assert [e["name"] for e in st.enemies] == ["goblin", "slime"], st
        assert st.enemies[0]["hp"] == 50.0 and st.enemies[1].get("hp") is None, st
        assert st.ground_items[0]["name"] == "potion" and st.ground_items[0]["dist"] == 12, st
        print("v2 file round-trip OK:", st)
    finally:
        server.close()
        try:
            os.remove(StateServer.FILE_FALLBACK)
        except OSError:
            pass


def test_render_dashboard() -> None:
    """Dashboard renders all Phase 1 fields and tolerates empty state."""
    from noita_bot import launcher
    from noita_bot.state_server import GameState

    full = GameState(
        frame=123, t=4.5, px=100.0, py=-50.0, alive=True, hp=10.0, max_hp=20.0,
        biome="Cave", inventory=["torch"], mode="file:x",
        enemies=[{"name": "goblin", "dist": 10}],
        ground_items=[{"name": "potion", "dist": 3}],
    )
    text = launcher.render_dashboard(full, stale=False)
    assert "LIVE" in text and "100,-50" in text
    assert "10/20" in text and "Cave" in text
    assert "torch" in text and "goblin@10" in text and "potion@3" in text

    empty = GameState()
    text2 = launcher.render_dashboard(empty, stale=True)
    assert "STALE" in text2 and "n/a" in text2
    assert "inventory: (empty)" in text2 and "enemies: none nearby" in text2
    print("Dashboard render OK")


if __name__ == "__main__":
    test_udp_roundtrip()
    test_file_fallback_roundtrip()
    test_v2_payload_file()
    test_render_dashboard()
    print("all smoke tests passed")
