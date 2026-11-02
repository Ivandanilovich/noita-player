# AGENTS.md — noita-player

An LLM-driven bot that plays **Noita**. An in-game Lua bridge (installed as a local mod)
streams structured game state out of Noita; a Python orchestrator runs a real-time reflex
layer and will consult an LLM for strategic decisions (~0.5 Hz). See `README.md` for the
full architecture diagram and roadmap.

## Critical facts about this Noita build (VERIFIED — do not re-derive)

Game: `C:\Program Files (x86)\Steam\steamapps\common\noita` (build Jan 25 2025, API v12).

1. **There is NO `-lua_script` CLI parameter** in this build. Verified by extracting the
   binary's argument table from `noita.exe` (full list: `-windowed`, `-fullscreen`,
   `-clean_save`, `-daily_run`, `-gamemode`, `-play`, `-debug_lua`, ...). Custom Lua only
   runs as a **mod**: `<game dir>\mods\<name>\{mod.xml, init.lua}`. New local mods are registered but start **DISABLED** - per-save enable state lives in `%USERPROFILE%\AppData\LocalLow\Nolla_Games_Noita\saveNN\mod_config.xml` (`<Mod enabled="0" name="<folder>" .../>`). `launcher.py::enable_mod_in_saves()` flips our entry to `enabled="1"` on every launch (creates the file if missing), so no Mods-menu toggle is ever needed. The game rewrites these files on exit - only edit while closed.
2. **No LuaSocket**: zero socket strings in `lua51.dll`, no socket DLL shipped.
   `require("socket")` will fail → state transport is a **JSON file**:
   `%TEMP%\noita_bot_state.json`, written by the mod at ~30 Hz, polled by Python at ~50 Hz
   (mtime-gated). The UDP path in the code is dead weight kept for future-proofing.
3. **Mod API restrictions**: default mod context only has `table/string/math/bit` + game
   APIs. Our `mod.xml` sets `request_no_api_restrictions="1"` to get `io.*`/`os.*`.
4. **Per-frame hooks** (documented in the game's own `mods/example/init.lua`):
   `OnPlayerSpawned(entity)`, `OnWorldPostUpdate()` / `OnWorldPreUpdate()` (every frame,
   only while the world updates — NOT in menus/pause), plus `OnModInit` etc.
5. **Logging**: `<game dir>\logger.txt` is truncated each launch and captures **Lua errors only**.
   VERIFIED 2026-11-02: `GamePrint()` from mod code does NOT appear there (zero `[bot_bridge]`
   lines while the mod streams) — do not rely on it. Diagnostics ship in the JSON payload's
   `diag` field; the launcher prints it once as `[launcher] DIAG: ...`.
   `EntityGetComponent` validates type names against a registry (bad name raises
   "component type X doesn't exist" — that IS visible in logger.txt, deduped); "HealthComponent"/
   "health" do not exist in this build.
6. **No key simulation in the public Lua API** (`InputIsKeyDown` is read-only) → Phase 2
   injects keys at OS level (pynput/SendInput) into the focused windowed game. Controls:
   A/D move, W fly, S crouch/drink/eat, LMB use item, number keys/scroll switch slots,
   F kick, E interact (from `<game dir>\README.txt`).
7. Useful API functions for Phase 1 state: `EntityGetTransform`, `EntityGetIsAlive`,
   `EntityGetInRadiusWithTag(x,y,r,tag)`, `GameGetAllInventoryItems(eid)`, `BiomeMapGetName(x,y)`, `EntityGetComponent(eid,type)` +
   `ComponentGetValue2(comp, field)` (health etc.), `GameGetFrameNum`. Full reference:
   `<game dir>\tools_modding\lua_api_documentation.txt` (API v12).
8. **User data dir**: `%USERPROFILE%\AppData\LocalLow\Nolla_Games_Noita` - a SIBLING of AppData\Roaming and AppData\Local, NOT under either (earlier searches missed it for that reason). Contains `save00..save06` (worlds, per-save `mod_config.xml`, stats) and `save_shared\config.xml` - the REAL config; the one in the game dir is a default template.

## Commands

```powershell
cd c:\Users\ivand\Documents\PROJECTS\PETS\noita-player

pip install -r requirements.txt          # pynput, requests, PyYAML

python tests/test_state_server.py        # transport smoke tests (no game needed)
tools\luacheck.exe --std max -q lua\bot_bridge.lua   # 0 errors expected; ~25 warnings = Noita globals

python -m noita_bot.launcher             # installs mod, starts game windowed, prints heartbeats
python -m noita_bot.launcher --listen-only
```

Live test flow: run the launcher → drive the menu with the MOUSE (Enter does NOTHING in menus):
`python tools\send_input.py fix-topmost` then `python tools\send_input.py click 1718 740`
(New Game on the 3440x1440 setup; full coordinates in `.agents/current_state.md`) → confirm
"Yes" (~1660,728) → state lines appear. If nothing after ~30 s of play: check Lua errors in
`<game dir>\logger.txt` (GamePrint is NOT logged there) and the launcher's `[launcher] DIAG:`
line; last resort = Mods menu toggle.

## File map

```
lua/bot_bridge.lua          # SOURCE OF TRUTH for the in-game bridge (Lua 5.1!)
lua/mod.xml                 # mod metadata source (synced to <game>\mods\noita_player\)
lua/compatibility.xml       # compatibility marker, matches working mods' layout
noita_bot/launcher.py       # installs+enables mod, launches game windowed, listens
noita_bot/state_server.py   # UDP + file listener → GameState dataclass
tests/test_state_server.py  # transport smoke tests
config.yaml                 # game path, bridge port, LLM settings (used from Phase 3)
tools/luacheck.exe          # Lua static checker (0.23.0 win64)
tools/send_input.py         # SendInput keys+clicks + Noita window mgmt (Phase 2 foundation)
tools/measure_menu.ps1      # screenshot text-row measurement (menu coordinate calibration)
logs/                       # launcher output captures (phase1_test*.log, screenshot*.png)
.agents/current_state.md    # where the project stands right now (keep updated!)
.agents/worklog.md          # chronological log of decisions and discoveries
```

## Conventions

- **Lua is 5.1** (no `goto`, no `//`): keep syntax conservative; run luacheck after edits.
- The launcher re-copies `lua/bot_bridge.lua` → mod folder on every launch; never edit the
  copy in `<game>\mods\noita_player\` directly.
- Python: stdlib-first (Phase 0/1 need nothing beyond pynput later); type hints + dataclasses;
  `flush=True` on prints that must be visible when stdout is redirected to a file.
- Background sessions: only ONE process may bind port 54321 — Windows `SO_REUSEADDR` allows
  double-binding but datagrams go to the FIRST binder (this bit us once). Kill stale
  `python -m noita_bot.launcher` processes before re-testing.
- Keep `.agents/current_state.md` current at every meaningful milestone; append to
  `.agents/worklog.md` for discoveries, pivots, and non-obvious decisions.

## Roadmap status (detail in README)

- [x] Phase 0 — state bridge mod → JSON file → Python listener (smoke tests + LIVE-VERIFIED 2026-11-01)
- [~] Phase 1 — full state snapshot (HP/inventory/enemies/biome) + live dashboard (code done
      2026-11-02; LIVE: position+enemies OK; HP UNSOLVED, item names + biome partial —
      see .agents/current_state.md for the task list)
- [ ] Phase 2 — reflex layer + pynput key injection (bot plays without LLM)
- [ ] Phase 3 — LLM brain (provider-agnostic: any OpenAI-compatible endpoint, incl. local Ollama/LM Studio on the RTX 5090)
- [ ] Phase 4 — memory of visited areas, episode summaries
