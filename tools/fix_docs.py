"""One-shot doc fixer (2026-11-01): updates AGENTS.md facts + appends worklog section.

The editor tool's exact-match failed on these regions (invisible whitespace), so this
script uses tolerant regex matching with assertions. Safe to re-run: idempotent guards.
"""
import re

ROOT = r"c:\Users\ivand\Documents\PROJECTS\PETS\noita-player"

# --- AGENTS.md fix 1: replace the now-wrong auto-load claim in fact #1 ---
p = ROOT + r"\AGENTS.md"
t = open(p, encoding="utf-8").read()

if "start **DISABLED**" not in t:
    pat1 = re.compile(
        r"Local mods in `mods/`\s*appear to auto-load.*?\*\*Mods\*\* menu\.", re.S
    )
    rep1 = (
        "New local mods are registered but start **DISABLED** - per-save enable state "
        "lives in `%USERPROFILE%\\AppData\\LocalLow\\Nolla_Games_Noita\\saveNN\\mod_config.xml` "
        '(`<Mod enabled="0" name="<folder>" .../>`). `launcher.py::enable_mod_in_saves()` flips '
        'our entry to `enabled="1"` on every launch (creates the file if missing), so no Mods-menu '
        "toggle is ever needed. The game rewrites these files on exit - only edit while closed."
    )
    t, n1 = pat1.subn(lambda m: rep1, t)
    assert n1 == 1, f"fact#1: {n1} matches"

# --- AGENTS.md fix 2: append fact #8 after the API-doc reference line ---
if "User data dir" not in t:
    anchor = r"`<game dir>\tools_modding\lua_api_documentation.txt` (API v12)."
    i = t.find(anchor)
    assert i >= 0, "fact#7 anchor not found"
    j = i + len(anchor)
    fact8 = (
        "\n8. **User data dir**: `%USERPROFILE%\\AppData\\LocalLow\\Nolla_Games_Noita` - a SIBLING of "
        "AppData\\Roaming and AppData\\Local, NOT under either (earlier searches missed it for that reason). "
        "Contains `save00..save06` (worlds, per-save `mod_config.xml`, stats) and `save_shared\\config.xml` - "
        "the REAL config; the one in the game dir is a default template."
    )
    t = t[:j] + fact8 + t[j:]

# --- AGENTS.md fix 3: update fact #7 with confirmed Phase-1 functions ---
if "EntityGetInRadiusWithTag" not in t:
    pat7 = re.compile(
        r"`EntityGetInRadius\(x,y,r\)`, `EntityHasTag\(eid,\"enemy\"\)`, `BiomeMapGetName\(x,y\)`,"
    )
    rep7 = (
        "`EntityGetInRadiusWithTag(x,y,r,tag)`, `GameGetAllInventoryItems(eid)`, "
        "`BiomeMapGetName(x,y)`, `EntityGetComponent(eid,type)` +"
    )
    t, n7 = pat7.subn(lambda m: rep7, t)
    assert n7 == 1, f"fact#7: {n7} matches"

open(p, "w", encoding="utf-8", newline="\n").write(t)
print("AGENTS.md updated")

# --- worklog.md: append new section (idempotent) ---
w = ROOT + r"\.agents\worklog.md"
tail = open(w, encoding="utf-8").read()
section = """
## 2026-11-01 (later) - Phase 0 LIVE VERIFIED + mod-enable root cause found

### The "no heartbeat" mystery, solved
- User played a launcher session; still zero heartbeats and no `[bot_bridge]` lines in `logger.txt`,
  while quant.ew's init.lua clearly ran (its errors were logged).
- Noita user data is at **`%USERPROFILE%\\AppData\\LocalLow\\Nolla_Games_Noita`** - a sibling of
  Roaming/Local, which is why all earlier AppData searches missed it entirely.
- Found `save00\\mod_config.xml`: the per-save mod enable list. Our mod WAS registered by the game but
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
  `frame=2032 t=102s player=(256,-79) alive=True via=file:%TEMP%\\noita_bot_state.json`.
  User's real movement visible in the stream (walk + jump). **Phase 0 complete.**

### Phase 1 prep
- Confirmed in v12 API doc: `EntityGetInRadiusWithTag`, `GameGetAllInventoryItems(eid) -> {ids}`,
  `BiomeMapGetName(x,y)`, `EntityGetComponent(eid, type_name)`. No direct health function and no
  component/field enumeration API -> exact field names must come from the game's own scripts or a
  runtime probe.
"""
if "Phase 0 LIVE VERIFIED" not in tail:
    open(w, "a", encoding="utf-8").write(section)
    print("worklog.md appended")
else:
    print("worklog already has section; skipped")
