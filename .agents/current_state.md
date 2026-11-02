# Current State - noita-player

_Last updated: 2026-11-02 (~12:00) - Phase 1 code DONE + deployed + LIVE-VERIFIED PARTIALLY.
Health source still unsolved. User asked to freeze: no new research/launches._

## Where we are

**Phase 0 is COMPLETE and LIVE-VERIFIED** (unchanged).

**Phase 1 (full state snapshot + live dashboard): code complete, deployed in-game,
live-verified PARTIALLY.** The v2 bridge streams a full snapshot at ~30 Hz. Verified live:

| Field | Status | Evidence |
|---|---|---|
| frame / t / px / py / alive | OK | live state file, player (227,-78) |
| enemies (name+dist, cap 12) | OK | `$animal_zombie@377`, tag "enemy" is valid |
| hp / max_hp (player AND enemies) | BROKEN | all 5 reader candidates failed |
| inventory | PARTIAL | ids stream; names empty -> `item_<id>` fallback (works) |
| biome | PARTIAL | API works, returns `"_EMPTY_"` at spawn (y=-78) |
| ground_items | UNVERIFIED | `{}` - probably legitimately empty near spawn |

**ENTRY POINT for the next session: find the health source** (task 1 below). Everything else
of Phase 1 already works end-to-end (menu driving, dashboard, parsing, tests green).

## VERIFIED facts, new (2026-11-02) - do NOT re-derive

1. `EntityGetComponent` VALIDATES type names against a registry: a bad name raises
   `component type X doesn't exist` (logged to logger.txt even when pcall'd; the game dedupes
   recurring errors). The registry is probeable; bad probes are visible in the log.
2. **"HealthComponent" and "health" DO NOT EXIST** in this build's registry (error-verified).
3. **`GamePrint` from mod code does NOT reach logger.txt** (verified: zero `[bot_bridge]` lines
   while the mod streams; only Lua errors are logged). -> Diagnostics now ship in the payload's
   `diag` field; the launcher prints it once as `[launcher] DIAG: ...`. (Old AGENTS.md #5 /
   README claim was wrong - both corrected.)
4. **VariableStorageComponent semantics verified**: one variable per component instance;
   `ComponentGetValue2(comp,"name")` returns the variable name. The player at spawn has exactly
   4 variables: `ocarina_song, kantele_song, ocarina_song_pos, kantele_song_pos`.
   **There is NO "health" variable on the player.**
5. Inventory items (3 at spawn): `ItemComponent.item_name` empty, `EntityGetName(item)` returns
   `""` (empty string), item has no VariableStorageComponent -> item names unsolved;
   `item_<id>` fallback streams fine.
6. Enemy names via `EntityGetName` = internal ids (`$animal_zombie`, `$animal_longleg`,
   `$animal_acidshooter`, `$animal_slimeshooter`, `$animal_miner`).
7. Game menus ignore keyboard (Enter does nothing - no default highlight) -> drive with mouse.
8. Noita window is 2560x1440 CENTERED on the 3440x1440 ultrawide (black bars both sides).
9. Game window title: `Noita - Build <date> - <time>` - match EXACTLY. The VS Code window of
   THIS project contains "noita" in its title ("HANDOFF.md - noita-player - Visual Studio Code");
   a loose matcher matched the IDE, not the game (bug found & fixed in tools/send_input.py).
10. The agent terminal runs INSIDE VS Code: command execution can raise the IDE above the game
    -> the game must be TOPMOST for clicks/screenshots:
    `python tools\send_input.py fix-topmost`.
11. SendInput: the INPUT union must be sized by its largest member (MOUSEINPUT) or Windows
    returns err=87. SetForegroundWindow from a background process is unreliable; SetWindowPos
    (z-order) works.
12. Main-menu coordinates (3440x1440, measured with tools/measure_menu.ps1):
    Continue (1718,696), New Game (1718,740), Options (1716,784), Mods (1716,828),
    Release Notes (1716,872), Credits (1716,916), Quit (1716,960);
    New-Game confirm "Yes" ~ (1660,728).

## Built this session (all in the repo, tests green)

- `lua/bot_bridge.lua` v2.1 - Phase 1 payload + one-time `diag` block + 5 health-reader
  candidates (VSC direct field, VSC instance-per-variable scan, HealthBarComponent x2,
  DamageModelComponent) + item-name fallbacks. luacheck: 0 errors (25 warnings = Noita globals).
- `noita_bot/state_server.py` - GameState: hp/max_hp/biome/inventory/enemies/ground_items,
  defensive parsing (v1 payloads still work).
- `noita_bot/launcher.py` - live dashboard (TTY ANSI ~5 Hz) / compact lines (redirected),
  one-shot `[launcher] DIAG:` print, `server.close()` in finally.
- `tests/test_state_server.py` - 4 tests, all pass (UDP, file v1 defaults, file v2 fields,
  dashboard).
- `tools/send_input.py` - SendInput keys + mouse clicks (no deps), exact Noita-window finder,
  topmost/fix-topmost/list. **This is the Phase 2 input-driver foundation.**
- `tools/measure_menu.ps1` - text-row coordinate measurement in screenshots (menu calibration).
- Autonomous menu driving WORKS end-to-end: launcher -> New Game -> game mode -> Yes -> world
  -> player spawn -> state streaming. (tools/press_key.py deleted, superseded by send_input.py.)

## Environment state (at time of writing)

- `noita.exe`: RUNNING, in-world (loaded via Continue), topmost window.
- Launcher: python pid 44140, `--duration 900` (started ~11:56, expires ~12:12),
  log `logs/phase1_test2.log`. After expiry the game keeps writing the state file;
  nothing consumes it.
- Read state directly: `Get-Content $env:TEMP\noita_bot_state.json -Raw`.
- Screenshot recipe: PowerShell System.Drawing `CopyFromScreen` -> `logs\screenshotN.png`
  -> read the PNG with vision (this is how menus were calibrated).
- To apply Lua changes the game MUST be restarted (mod loads once at startup; the launcher
  re-syncs lua/bot_bridge.lua on launch).

## Tasks (priority order)

1. **Find the health source** (the only real Phase 1 blocker). Leads:
   - grep `tools_modding\lua_api_documentation.txt` for ALL `Component*` functions (maybe a
     field-enumeration API?) and for "health" (maybe a GetHealth-style helper?).
   - Systematic registry probe: iterate all component names from
     `component_documentation.txt` (~150) against the player via EntityGetComponent - valid
     names return a table (maybe empty), invalid ones raise; then probe fields on components
     the player actually has; results -> payload.diag (the mechanism already exists).
   - Candidates not yet tried: CharacterStatsComponent, CharacterDataComponent, health on a
     CHILD entity (character body), or a "health" variable appearing after first damage.
   - Web: community Noita-modding wiki - how do mods read player HP?
2. Inventory item names: try `EntityGetName` on the item's PARENT entity (check API for
   parent/child functions); low priority - the `item_<id>` fallback works, the LLM can learn
   the id->name mapping.
3. biome: figure out `"_EMPTY_"` (move/dig to change biome, or another Biome* API function).
4. ground_items: verify by dropping/picking up an item.
5. **Phase 2** - reflex layer on top of tools/send_input.py (key + click foundation is DONE).
6. **Phase 3** - LLM provider: USER DECISION (cloud API + key vs local Ollama/LM Studio;
   RTX 5090 32 GB fits 7-14B models, $0 local).
7. Phase 4 - memory of visited areas, episode summaries.

## How to run (unchanged)

```powershell
cd c:\Users\ivand\Documents\PROJECTS\PETS\noita-player
python tests\test_state_server.py                          # smoke tests (no game needed)
tools\luacheck.exe --std max -q lua\bot_bridge.lua         # 0 errors expected (~25 warnings)
python -m noita_bot.launcher                               # install+enable mod, start game, listen
python tools\send_input.py fix-topmost                     # keep the game window on top
```
