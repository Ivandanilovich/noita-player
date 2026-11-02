"""One-shot doc updater (2026-11-01, second pass): rewrites .agents/current_state.md with the
exact project position and appends a worklog addendum for the Phase 1 research. No matching —
pure write/append, so no whitespace issues."""

ROOT = r"c:\Users\ivand\Documents\PROJECTS\PETS\noita-player"

CURRENT_STATE = r"""# Current State - noita-player

_Last updated: 2026-11-01 (Phase 1 designed; implementation NOT started)_

## Where we are

**Phase 0 is COMPLETE and LIVE-VERIFIED.** The bridge mod runs inside Noita and streams state
to Python at ~30 Hz via `%TEMP%\noita_bot_state.json` (verified with real gameplay: position
updates including the user's walk + jump).

**Phase 1 (full state snapshot + live dashboard): all research done, code NOT yet written.**
The immediate next action is writing the Phase 1 code per the plan below.

## Verified facts for Phase 1 (research complete)

From `tools_modding\lua_api_documentation.txt` (v12):
- `EntityGetInRadiusWithTag(x, y, r, tag)` - radius query with tag filter
- `GameGetAllInventoryItems(entity_id) -> {item_ids}` - direct inventory access
- `BiomeMapGetName(x, y)`
- `EntityGetComponent(eid, component_type_name) -> {comp_ids}`

From the working quant.ew mod (init.lua):
- `EntityGetComponent` takes **full C++ class names** ("VariableStorageComponent",
  "DamageModelComponent") -> use `"HealthComponent"` / `"ItemComponent"`, not lowercase short names.

From `tools_modding\component_documentation.txt`:
- **ItemComponent has an `item_name` field** ("the name of the item") -> inventory display names solvable.
- HealthComponent is NOT documented there (only UI health bars) -> HP field names unconfirmed;
  community convention is `"current_health"`/`"max_health"` via ComponentGetValue2 - verify at runtime.

Dead ends: `data.wak` is a custom container (not zip); the official `noita.exe -wizard_unpak`
(from data_wak_unpack.bat) exits silently without extracting anything useful. -> **Decision:
one-time runtime probe on player spawn** (GamePrint which component type names + field candidates
work; results land in `<game dir>\logger.txt`). All live payload access is pcall-guarded so a wrong
guess degrades to null instead of crashing the mod.

## Phase 1 implementation plan (designed, not written)

1. `lua/bot_bridge.lua` v2:
   - Payload adds: hp/max_hp (HealthComponent), inventory item names
     (ItemComponent.item_name via GameGetAllInventoryItems), nearby enemies
     (EntityGetInRadiusWithTag "enemy": name+dist+hp, cap 12, scanned ~4 Hz and cached),
     biome name (~2 Hz, cached), ground items within 400 px (tag "item", own-inventory ids
     excluded, cap 8).
   - One-time spawn diagnostics: probe health component type names {"HealthComponent","health"}
     x field candidates {"current_health","max_health","health","mCurrentHealth"}, item_name on the
     first 3 inventory items, radius-tag counts for {"enemy","hostile","item","pickup"}, and a
     BiomeMapGetName sample - all GamePrint'd as `[bot_bridge] diag:` lines.
   - Also fix the stale header comment (still mentions the non-existent `-lua_script` param).
2. `noita_bot/state_server.py`: extend GameState with hp/max_hp/biome/inventory/enemies/ground_items;
   parse v=2 defensively so v=1 payloads still work.
3. Launcher: live terminal dashboard when stdout is a TTY (ANSI redraw); keep plain periodic lines
   for file-redirected background sessions.
4. `tests/test_state_server.py`: extend smoke tests with v=2 payload assertions.
5. Verify: luacheck + smoke tests, then ONE short play session -> read the `[bot_bridge] diag:`
   lines in logger.txt -> fix any field names that came back null.

## How to run (unchanged)

```powershell
cd c:\Users\ivand\Documents\PROJECTS\PETS\noita-player
python -m noita_bot.launcher        # installs+enables mod, starts game windowed, prints state
# in Noita: New Game / Continue -> heartbeats appear
```

## Open questions (answered by the spawn diagnostics)
- Exact health component type name + field names in this build.
- Whether ground items carry tag "item" (vs "pickup") - if both probe counts are 0, rethink.
- What EntityGetName returns for enemy entities (internal id vs display name).

## Housekeeping
- `tools/fix_docs.py` and `tools/update_docs2.py` are one-shot doc fixers from this session
  (idempotent; safe to delete once AGENTS.md/worklog look right - they do).
"""

open(ROOT + r"\.agents\current_state.md", "w", encoding="utf-8", newline="\n").write(CURRENT_STATE)
print("current_state.md rewritten")

WORKLOG_ADDENDUM = """
### Phase 1 research (same day, continued)
- `tools_modding\\component_documentation.txt` exists (357 KB): **ItemComponent.item_name** confirmed -
  inventory display names are solvable. HealthComponent is NOT documented there (only UI health bars).
- quant.ew's init.lua shows EntityGetComponent takes full C++ class names ("VariableStorageComponent")
  -> use "HealthComponent" / "ItemComponent".
- `data.wak` is a custom container; the official `noita.exe -wizard_unpak` (from data_wak_unpack.bat)
  exits silently and extracts nothing useful. Dead end - not chasing further.
- Decision: one-time runtime probe on player spawn (GamePrint component/field candidates to logger.txt);
  all payload access pcall-guarded. Phase 1 code design is complete; writing it is the next action.
"""

w = ROOT + r"\.agents\worklog.md"
tail = open(w, encoding="utf-8").read()
if "Phase 1 research (same day, continued)" not in tail:
    open(w, "a", encoding="utf-8").write(WORKLOG_ADDENDUM)
    print("worklog.md appended")
else:
    print("worklog addendum already present; skipped")
