# noita-player

An LLM-driven bot that plays [Noita](https://noitagame.com/). An in-game Lua bridge streams
structured game state out of Noita to a Python orchestrator, which runs a real-time reflex
layer and consults an LLM for strategic decisions every couple of seconds.

## Architecture

```
┌──────────── Noita (noita.exe -windowed) ────────────────────────────────────┐
│ bridge runs IN-GAME as local mod  <game dir>\mods\noita_player\             │
│   init.lua — OnWorldPostUpdate() hook, ~30 Hz:                              │
│     • Phase 0: frame number + player position (heartbeat)                   │
│     • Phase 1: HP, inventory, nearby enemies, items on ground, biome/depth  │
│   → JSON written to %TEMP%\noita_bot_state.json                             │
│     (UDP to 127.0.0.1:54321 is attempted first; this Noita build has no     │
│      LuaSocket, so the file path is what actually carries data)             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                ▼  (Python polls the file at ~50 Hz, mtime-gated)
┌──────────────── Python orchestrator (noita_bot/) ───────────────────────────┐
│  state_server.py — UDP + file listener → GameState                          │
│  reflexes.py     — Phase 2: 60 Hz goal interpreter + survival rules         │
│  input_driver.py — Phase 2: pynput key injection into the game window       │
│  llm_brain.py    — Phase 3: compact prompt → LLM chat API → JSON action     │
└─────────────────────────────────────────────────────────────────────────────┘
```

Design notes:

- **Hierarchical control**: the LLM thinks at ~0.5 Hz (*what* to do); a Python reflex layer
  acts at 60 Hz (*how*, in real time). This hides LLM latency and cost, and keeps the bot
  alive between decisions.
- **Text state, not pixels**: structured JSON → compact prompt (~400 tokens) works with any
  chat model; no vision required (screenshots can be added later for vision models).
- **No key simulation in Noita's public Lua API**, so keys are injected at the OS level
  (pynput / SendInput) into the focused game window.

### How the bridge loads inside the game

This Noita build (Jan 25 2025) has **no `-lua_script` CLI parameter** (verified by inspecting
the binary's argument table). Custom Lua runs as a *mod*: `launcher.py` copies
`lua/bot_bridge.lua` to `<game dir>\mods\noita_player\init.lua` (next to the `mod.xml` that
requests unrestricted API access for file I/O) and starts the game. Local mods in `mods/`
load automatically; if yours ever doesn't, enable it once in Noita's **Mods** menu.

## Roadmap

- [x] Phase 0 — state bridge (in-game mod → JSON file → Python), launcher, static checks
- [~] Phase 1 — full state snapshot + live dashboard (code complete 2026-11-02; live: position +
      enemies OK; HP + item names still unsolved — see `.agents/current_state.md`)
- [ ] Phase 2 — reflex layer + key injection (bot plays without an LLM)
- [ ] Phase 3 — LLM brain (prompts, structured actions, transcripts, cost log)
- [ ] Phase 4 — memory of visited areas, episode summaries, tuning

## Setup

```powershell
cd c:\Users\ivand\Documents\PROJECTS\PETS\noita-player
pip install -r requirements.txt
```

Noita must be installed at the path in `config.yaml` (default: Steam library).

## Running — Phase 0 test

```powershell
python -m noita_bot.launcher
```

This installs the bridge mod, starts Noita windowed, then prints a heartbeat line every ~2 s
**once you start a New Game in the menu** (the per-frame hook only fires while the world is
updating). You should see:

```
  frame=12345 t=   87.3s player=(5230,-120) alive=True via=file:C:\Users\...\Temp\noita_bot_state.json
```

Note: `GamePrint` from mod code does NOT reach `<game dir>\logger.txt` in this build (verified
2026-11-02) — only Lua errors are logged there. If state doesn't appear after starting a new
game, check Lua errors in logger.txt and the launcher's `[launcher] DIAG:` line. The mod is
auto-enabled for all save slots by `launcher.py`; if you ever edit saves manually, enable it
once in Noita's **Mods** menu.

## Layout

```
noita-player/
├── lua/bot_bridge.lua      # in-game state reader (source of truth)
├── noita_bot/              # Python orchestrator
│   ├── launcher.py         # installs the mod, starts the game, listens for heartbeats
│   └── state_server.py     # UDP/file listener → GameState
├── tests/test_state_server.py  # transport smoke tests (no game needed)
├── config.yaml             # game path, bridge port, LLM settings (Phase 3)
├── requirements.txt
├── tools/luacheck.exe      # static checker for the Lua side
├── tools/send_input.py     # OS-level keys + mouse clicks (Phase 2 foundation; menu driving)
└── tools/measure_menu.ps1  # screenshot text-row measurement (menu calibration)
```

The launcher also maintains `<game dir>\mods\noita_player\` (init.lua + mod.xml) — safe to
delete; it's recreated on next launch.
