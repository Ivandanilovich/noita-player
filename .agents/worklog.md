# Worklog — noita-player

Chronological log of decisions, discoveries, and pivots. Newest at bottom.

## 2026-11-01 — Project start + Phase 0 build

### Discovery phase (plan mode)
- User goal: "teach bot based on you to play noita" → clarified via question → **LLM-driven
  bot**: LLM API makes strategic decisions, Python reflex layer handles real-time combat.
- Environment verified: Noita at `C:\Program Files (x86)\Steam\steamapps\common\noita`
  (build Jan 25 2025), Lua modding API v12 docs in `tools_modding/`, Python 3.12, RTX 5090 32GB.
- Read the public API doc: rich state reading (entities/components/biome map) but **no key
  simulation** → OS-level input injection decided for Phase 2.
- Architecture agreed: in-game Lua bridge → structured JSON → Python orchestrator with
  hierarchical control (LLM ~0.5 Hz strategy / reflexes 60 Hz). Text state, not pixels.

### Phase 0 build
- Scaffolded project: `lua/bot_bridge.lua` (JSON encoder + transport + hooks),
  `noita_bot/{__init__,state_server,launcher}.py`, `tests/test_state_server.py`,
  `config.yaml`, `requirements.txt`, `README.md`. Downloaded luacheck 0.23.0 to `tools/`.
- Found the per-frame hook API by reading the game's own **`mods/example/init.lua`**:
  `OnPlayerSpawned(entity)`, `OnWorldPostUpdate()`, etc. (web docs were unreachable; local
  installed mods turned out to be the best reference).

### Pivots (important — these assumptions were WRONG, verified against the binary/files)
1. **`-lua_script` CLI parameter does not exist in this build.** First live test: game ran,
   user clicked New Game, zero heartbeats and no `[bot_bridge]` log lines. Extracted the
   argument table from `noita.exe` (string dump around `-clean_everything`) — full param list
   confirmed, no `-lua_script`. The 4 "lua_script" strings in the exe are biome XML attrs.
   → **Pivot: bridge runs as a local mod** `<game>\mods\noita_player\{mod.xml,init.lua}`;
   launcher auto-installs it from `lua/bot_bridge.lua` (single source of truth).
2. **No LuaSocket in the game's Lua runtime.** Zero socket strings in `lua51.dll`, no socket
   DLL shipped, and mod contexts are API-restricted by default. → **File transport is primary**:
   `%TEMP%\noita_bot_state.json` written at ~30 Hz; Python polls mtime-gated at ~50 Hz. UDP
   code kept as a harmless future-proofing path.
3. `mod.xml` needs **`request_no_api_restrictions="1"`** for `io.*`/`os.*` (per the comment in
   `mods/example/mod.xml`). Set on our mod.

### Bugs found & fixed
- **Listener thread died silently**: with `settimeout(0)`, empty UDP reads raise
  `BlockingIOError` (an `OSError`) not `socket.timeout`, so `except OSError: break` exited the
  loop on tick 1. Fix: small *blocking* timeout (`settimeout(0.02)`) paces the ~50 Hz loop;
  `socket.timeout` is then raised reliably for empty reads. Caught by smoke tests.
- **Stale background process ate UDP**: an old launcher session still bound port 54321; Windows
  `SO_REUSEADDR` allows double-bind but datagrams deliver to the FIRST binder → new test server
  saw nothing. Fix: kill stale processes before re-testing (documented in AGENTS.md).
- **Buffered stdout**: heartbeat prints invisible for minutes when redirected to file →
  `flush=True` on launcher prints + run background sessions with `python -u`.

### Diagnostics added
- Bridge now GamePrints `[bot_bridge] loaded`, `player spawned, id=N`, and one-time
  `world update hook active (transport=...)` — distinguishes "mod didn't load" vs "hooks dead"
  vs "transport broken" from `<game dir>\logger.txt`.

### Status at end of session
- All static checks + smoke tests green. Live verification pending: user must click New Game
  in a launcher-started session (one was running, PID 16056). See `.agents/current_state.md`
  for the decision tree if heartbeats don't appear.

## 2026-11-01 (later) - Phase 0 LIVE VERIFIED + mod-enable root cause found

### The "no heartbeat" mystery, solved
- User played a launcher session; still zero heartbeats and no `[bot_bridge]` lines in `logger.txt`,
  while quant.ew's init.lua clearly ran (its errors were logged).
- Noita user data is at **`%USERPROFILE%\AppData\LocalLow\Nolla_Games_Noita`** - a sibling of
  Roaming/Local, which is why all earlier AppData searches missed it entirely.
- Found `save00\mod_config.xml`: the per-save mod enable list. Our mod WAS registered by the game but
  with **`enabled="0"`** (new local mods default to disabled); quant.ew had "1". That single flag was
  the whole problem - hooks and transport were fine all along.

### Fixes shipped
- `launcher.py::enable_mod_in_saves()`: flips our entry to enabled="1" in every save slot's
  mod_config.xml (regex in-place edit preserving other entries; creates file if missing). Runs on
  every launch incl. --listen-only. Zero-touch from now on.
- Mod folder sync now also copies `mod.xml` + `compatibility.xml` from repo sources (`lua/`) -
  matching the layout of working mods (quant.ew and example both ship compatibility.xml).

### Live verification: SUCCESS
- Fresh launcher session -> heartbeats at a steady 60 fps via file transport:
  `frame=2032 t=102s player=(256,-79) alive=True via=file:%TEMP%\noita_bot_state.json`.
  User's real movement visible in the stream (walk + jump). **Phase 0 complete.**

### Phase 1 prep
- Confirmed in v12 API doc: `EntityGetInRadiusWithTag`, `GameGetAllInventoryItems(eid) -> {ids}`,
  `BiomeMapGetName(x,y)`, `EntityGetComponent(eid, type_name)`. No direct health function and no
  component/field enumeration API -> exact field names must come from the game's own scripts or a
  runtime probe.

### Phase 1 research (same day, continued)
- `tools_modding\component_documentation.txt` exists (357 KB): **ItemComponent.item_name** confirmed -
  inventory display names are solvable. HealthComponent is NOT documented there (only UI health bars).
- quant.ew's init.lua shows EntityGetComponent takes full C++ class names ("VariableStorageComponent")
  -> use "HealthComponent" / "ItemComponent".
- `data.wak` is a custom container; the official `noita.exe -wizard_unpak` (from data_wak_unpack.bat)
  exits silently and extracts nothing useful. Dead end - not chasing further.
- Decision: one-time runtime probe on player spawn (GamePrint component/field candidates to logger.txt);
  all payload access pcall-guarded. Phase 1 code design is complete; writing it is the next action.

## 2026-11-02 - Phase 1 implementation + autonomous live verification (PARTIAL success)

### Phase 1 code (all written, tests green, deployed into the game)
- `lua/bot_bridge.lua` v2.1: Phase 1 payload (hp, inventory, enemies, biome, ground_items),
  pcall-guarded, rate-limited scans (enemies+ground ~4 Hz, biome ~2 Hz, cached), item-name
  fallbacks (ItemComponent.item_name -> EntityGetName -> `item_<id>`), 5 health-reader
  candidates (VSC direct field, VSC instance-per-variable scan, HealthBarComponent x2,
  DamageModelComponent), one-time `diag` block in the payload, stale header fixed.
- `noita_bot/state_server.py`: GameState + hp/max_hp/biome/inventory/enemies/ground_items,
  defensive v1/v2 parsing, hp coerced to float.
- `noita_bot/launcher.py`: TTY dashboard (ANSI ~5 Hz) vs compact lines (redirected),
  one-shot `[launcher] DIAG:` print, `server.close()` in finally.
- `tests/test_state_server.py`: 4 tests pass (UDP roundtrip, file v1 defaults, file v2 fields,
  dashboard render). luacheck: 0 errors, 25 warnings (Noita globals - normal).

### Autonomous live session (the bot itself drove the game's menus)
- New tool `tools/send_input.py`: SendInput keys + clicks (no deps), Noita window finder
  (EXACT title match), z-order management (topmost/untopmost/fix-topmost/list).
  Discovered menus ignore keyboard (Enter does nothing - no highlight) -> mouse clicks.
- Menu coordinates measured on the 3440x1440 screen with new `tools/measure_menu.ps1`:
  Continue (1718,696), New Game (1718,740), confirm "Yes" ~ (1660,728) (full list in
  current_state.md).
- Full flow WORKS: launcher -> New Game -> game-mode select -> Yes -> world -> player spawn
  -> state file streaming. Autonomous menu driving: SOLVED.

### Pivots / verified facts (important)
1. **GamePrint from mod code does NOT reach logger.txt** (zero `[bot_bridge]` lines while the
   mod streams; only Lua errors are logged). The old AGENTS.md #5 / README assumption was WRONG
   (both corrected). -> Diagnostics now ship in `payload.diag` + the launcher's DIAG line.
2. **EntityGetComponent validates type names against a registry**: bad name raises
   `component type X doesn't exist` (logged, deduped). -> "HealthComponent"/"health" do NOT
   exist in this build. The registry is probeable.
3. **Player's VariableStorageComponent** has exactly 4 variables at spawn: ocarina_song,
   kantele_song, ocarina_song_pos, kantele_song_pos. **NO "health" variable.**
   Instance-per-variable semantics verified (ComponentGetValue2(comp,"name") works).
4. Inventory items: ItemComponent.item_name empty, EntityGetName(item)="" -> names unsolved
   (fallback works). Enemy names = internal ids ($animal_zombie etc.).
5. Biome: BiomeMapGetName works, returns "_EMPTY_" at spawn (unclear if that is normal).
6. The agent terminal runs inside VS Code (project noita-player): command execution can raise
   the IDE over the game -> the game must be TOPMOST (fix-topmost). Also VS Code's title
   CONTAINS "noita" (project name) - the loose window matcher matched the IDE, not the game
   (bug found & fixed: exact match "Noita - Build ...").
7. SendInput err=87: the INPUT union must be sized by the largest member (MOUSEINPUT).
   SetForegroundWindow from background is unreliable; SetWindowPos (z-order) works.

### What is left (Phase 1 INCOMPLETE)
- **hp/max_hp: UNSOLVED** - all 5 reader candidates failed; the player's VSC has no "health"
  variable. Task list for the next session is in `.agents/current_state.md` (systematic
  registry probe of the ~150 documented component names is the leading approach).
- Item names (fallback works), biome "_EMPTY_" (unverified), ground_items (probably empty
  near spawn - unverified).

### Environment state at session end (frozen per user request)
- noita.exe: RUNNING, in-world (Continue), topmost.
- Launcher: python pid 44140, `--duration 900` (started ~11:56, expires ~12:12),
  `logs/phase1_test2.log`. After expiry the game keeps writing the state file.
- User asked: record the state, do NO further research or launches until the next session.
