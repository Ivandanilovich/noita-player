"""Receives state snapshots from the in-game Lua bridge (UDP or file fallback)."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field


@dataclass
class GameState:
    """Latest known game state (Phase 0 fields + Phase 1 snapshot fields)."""

    frame: int = 0
    t: float = 0.0
    px: float | None = None
    py: float | None = None
    alive: bool = False
    mode: str = ""  # "udp" or "file:<path>", as reported by the Lua side
    # Phase 1 fields (absent in v=1 payloads -> defaults below)
    hp: float | None = None
    max_hp: float | None = None
    biome: str = ""
    inventory: list[str] = field(default_factory=list)
    enemies: list[dict] = field(default_factory=list)
    ground_items: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class StateServer(threading.Thread):
    """Listens for JSON state snapshots from bot_bridge.lua.

    Primary transport is UDP on 127.0.0.1:54321. If the game's Lua runtime
    lacks sockets, the bridge writes %TEMP%\\noita_bot_state.json instead and
    we poll that file (checked whenever a UDP read times out).
    """

    FILE_FALLBACK = os.path.join(os.environ.get("TEMP", "."), "noita_bot_state.json")

    def __init__(self, host: str = "127.0.0.1", port: int = 54321):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.latest = GameState()
        self.last_rx_time = 0.0
        self._closed = False
        self._file_sig = None  # (mtime_ns, size) of last successfully read file
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        # Small blocking timeout paces the loop (~50 Hz); file polling rides along.
        self._sock.settimeout(0.02)

    def close(self) -> None:
        """Stop listening and release the port (lets a new server bind)."""
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    def _apply(self, payload: dict) -> None:
        s = self.latest
        s.raw = payload
        s.frame = int(payload.get("frame", 0))
        s.t = float(payload.get("t", 0.0))
        s.mode = str(payload.get("mode", ""))
        s.alive = bool(payload.get("alive", False))
        s.px = payload.get("px")
        s.py = payload.get("py")
        # Phase 1 fields; defensive so v=1 payloads (or dead player) keep working.
        hp = payload.get("hp")
        s.hp = float(hp) if isinstance(hp, (int, float)) else None
        mhp = payload.get("max_hp")
        s.max_hp = float(mhp) if isinstance(mhp, (int, float)) else None
        biome = payload.get("biome")
        s.biome = str(biome) if isinstance(biome, str) else ""
        inv = payload.get("inventory")
        s.inventory = [str(x) for x in inv] if isinstance(inv, list) else []
        enemies = payload.get("enemies")
        s.enemies = [e for e in enemies if isinstance(e, dict)] if isinstance(enemies, list) else []
        ground = payload.get("ground_items")
        s.ground_items = [g for g in ground if isinstance(g, dict)] if isinstance(ground, list) else []
        self.last_rx_time = time.time()

    def _poll_file(self) -> None:
        """Read the bridge's JSON file if it changed since last check.

        This is the primary transport (Noita's Lua has no sockets); UDP is a
        bonus fast path kept for builds that do have LuaSocket.
        """
        try:
            st = os.stat(self.FILE_FALLBACK)
        except OSError:
            return  # file doesn't exist yet
        sig = (st.st_mtime_ns, st.st_size)
        if sig == self._file_sig:
            return
        try:
            with open(self.FILE_FALLBACK, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return  # mid-write; retry next tick
            self._apply(json.loads(content))
            self._file_sig = sig
        except (OSError, ValueError):
            pass  # torn read or bad JSON; retry next tick

    def run(self) -> None:
        while not self._closed:
            try:
                data, _addr = self._sock.recvfrom(65536)
                self._apply(json.loads(data.decode("utf-8", "replace")))
            except socket.timeout:
                pass  # no datagram this tick; the timeout paces the loop
            except OSError:
                break  # socket closed via close()
            except Exception as exc:  # keep the listener alive no matter what
                print(f"[state_server] rx error: {exc!r}", flush=True)
            self._poll_file()

    @property
    def stale(self) -> bool:
        """True when nothing has arrived recently (menu / paused / not started)."""
        return self.last_rx_time == 0.0 or (time.time() - self.last_rx_time) > 1.5
