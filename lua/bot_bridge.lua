--[[============================================================================
  bot_bridge.lua — Noita -> Python state bridge (v2 / Phase 1)
  ============================================================================
  Runs inside Noita as a local mod: <game dir>\mods\noita_player\init.lua
  (installed + enabled by noita_bot\launcher.py. NOTE: this build has NO
  -lua_script parameter — mods are the only way to load custom Lua.)

  While the world is updating, sends a compact JSON snapshot over UDP to
  127.0.0.1:<port>. If LuaSocket is not available in this build (it is not),
  falls back to writing the same JSON to %TEMP%\noita_bot_state.json,
  which Python polls at ~50 Hz.

  Phase 1 payload: frame/t/player position + hp/max_hp, inventory item names,
  nearby enemies (name+dist+hp, cap 12), biome name, nearby ground items.
  Expensive radius queries are rate-limited (enemies+ground ~4 Hz, biome ~2 Hz)
  and cached between snapshots.

  Robustness rules:
  - every game API call is pcall-guarded: a wrong guess degrades to null,
    never crashes the mod;
  - component type/field names and entity tags are probed against candidate
    lists at runtime and the working combo is remembered;
  - OnPlayerSpawned prints a one-time diagnostic block
    ("[bot_bridge] diag: ..." in <game dir>\logger.txt) to confirm which
    names work in this build.
]]

local BOT_HOST = "127.0.0.1"
local BOT_PORT = 54321
local SEND_EVERY_N_FRAMES = 2 -- ~30 Hz at 60 fps

-- Rate limits for expensive queries (in frames; at 60 fps)
local ENEMY_SCAN_EVERY = 15 -- ~4 Hz: enemy radius scan (+ ground items + inventory)
local BIOME_SCAN_EVERY = 30 -- ~2 Hz: biome name

local ENEMY_RADIUS = 800
local ENEMY_CAP = 12
local GROUND_RADIUS = 400
local GROUND_CAP = 8
local INVENTORY_CAP = 12

-- ENEMY_TAGS / GROUND_TAGS are probed at runtime (see scan_* below).
local ENEMY_TAGS = { "enemy", "hostile" }
local GROUND_TAGS = { "item", "pickup" }

------------------------------------------------------------------------------
-- Minimal JSON encoder (Lua 5.1, no dependencies)
------------------------------------------------------------------------------
local function json_encode(value)
    local t = type(value)
    if value == nil then return "null" end
    if t == "boolean" then return (value and "true") or "false" end
    if t == "number" then
        if value ~= value then return "0" end -- NaN guard
        return string.format("%.10g", value)
    end
    if t == "string" then
        local s = value:gsub("[\\\"]", "\\%1")
            :gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
        return '"' .. s .. '"'
    end
    if t ~= "table" then return "null" end

    local n = #value
    local is_array = true
    for k in pairs(value) do
        if type(k) ~= "number" or k < 1 or k > n then
            is_array = false
            break
        end
    end
    if is_array and n > 0 then
        local parts = {}
        for i = 1, n do parts[i] = json_encode(value[i]) end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    -- object (or empty table)
    local parts = {}
    for k, v in pairs(value) do
        parts[#parts + 1] = json_encode(tostring(k)) .. ":" .. json_encode(v)
    end
    table.sort(parts)
    return "{" .. table.concat(parts, ",") .. "}"
end

------------------------------------------------------------------------------
-- Transport: UDP first, file fallback
------------------------------------------------------------------------------
local udp_socket = nil
local transport_mode = "none"
local fallback_file = nil

local function setup_transport()
    local ok, lib = pcall(require, "socket")
    if ok and type(lib) == "table" then
        local factory = lib.udp4 or lib.udp
        if factory then
            local ok2, sock = pcall(factory)
            if ok2 and sock then
                pcall(function() sock:settimeout(0) end) -- non-blocking
                udp_socket = sock
                transport_mode = "udp"
                return
            end
        end
    end
    local dir = "."
    local ok3, temp = pcall(os.getenv, "TEMP")
    if ok3 and type(temp) == "string" and temp ~= "" then dir = temp end
    fallback_file = dir .. "\\noita_bot_state.json"
    transport_mode = "file:" .. fallback_file
end

local file_warned = false
local function send_payload(payload_table)
    local json = json_encode(payload_table)
    if udp_socket then
        local ok, err = pcall(function() udp_socket:sendto(json, BOT_HOST, BOT_PORT) end)
        if not ok then
            GamePrint("[bot_bridge] UDP send failed (" .. tostring(err) .. ") -> switching to file mode")
            udp_socket = nil
            transport_mode = "file:" .. fallback_file
        end
    end
    if not udp_socket and fallback_file then
        local f = io.open(fallback_file, "w")
        if f then
            f:write(json)
            f:close()
        elseif not file_warned then
            GamePrint("[bot_bridge] cannot open fallback file " .. tostring(fallback_file))
            file_warned = true
        end
    end
end

------------------------------------------------------------------------------
-- Game API helpers (all pcall-guarded: failure -> nil/empty, never a crash)
------------------------------------------------------------------------------
local function log(msg)
    pcall(GamePrint, msg)
end

local function first_component(eid, comp_type)
    local ok, comps = pcall(EntityGetComponent, eid, comp_type)
    if not ok or type(comps) ~= "table" or #comps == 0 then return nil end
    return comps[1]
end

local function component_value(eid, comp_type, field_name)
    local comp = first_component(eid, comp_type)
    if comp == nil then return nil end
    local ok, val = pcall(ComponentGetValue2, comp, field_name)
    if not ok or val == nil then return nil end
    return val
end

local function radius_entities(x, y, r, tag)
    local ok, ids = pcall(EntityGetInRadiusWithTag, x, y, r, tag)
    if not ok or type(ids) ~= "table" then return {} end
    return ids
end

local function entity_pos(eid)
    local ok, x, y = pcall(EntityGetTransform, eid)
    if not ok then return nil end
    return x, y
end

local function entity_name(eid)
    local ok, name = pcall(EntityGetName, eid)
    if not ok or type(name) ~= "string" then return nil end
    return name
end

local function dist(ax, ay, bx, by)
    local dx, dy = ax - bx, ay - by
    return math.sqrt(dx * dx + dy * dy)
end

-- Health readers.
-- VERIFIED 2026-11-02 (EntityGetComponent registry errors in logger.txt):
-- "HealthComponent" and "health" do NOT exist in this build. Valid names
-- (used by the working quant.ew mod): VariableStorageComponent,
-- DamageModelComponent. Docs: VariableStorageComponent stores ONE variable
-- per component instance (name + value_string/int/bool/float) — so the
-- readers cover BOTH plausible API semantics; the first reader that returns
-- a number is remembered (and reported in payload.diag).
local function vsc_variable_value(eid, var_name, value_field)
    local ok, comps = pcall(EntityGetComponent, eid, "VariableStorageComponent")
    if not ok or type(comps) ~= "table" then return nil end
    for _, comp in ipairs(comps) do
        local okn, n = pcall(ComponentGetValue2, comp, "name")
        if okn and n == var_name then
            local okv, v = pcall(ComponentGetValue2, comp, value_field)
            if okv and v ~= nil then return v end
        end
    end
    return nil
end

local function vsc_var_names(eid, cap)
    local ok, comps = pcall(EntityGetComponent, eid, "VariableStorageComponent")
    if not ok or type(comps) ~= "table" or #comps == 0 then return nil end
    local names = {}
    for i = 1, math.min(#comps, cap) do
        local okn, n = pcall(ComponentGetValue2, comps[i], "name")
        if okn and type(n) == "string" then names[i] = n end
    end
    return names
end

local HEALTH_READERS = {
    function(eid) return component_value(eid, "VariableStorageComponent", "health") end,
    function(eid) return vsc_variable_value(eid, "health", "value_float") end,
    function(eid) return component_value(eid, "HealthBarComponent", "current_health") end,
    function(eid) return component_value(eid, "HealthBarComponent", "value") end,
    function(eid) return component_value(eid, "DamageModelComponent", "health") end,
}
local MAX_READERS = {
    function(eid) return component_value(eid, "VariableStorageComponent", "max_health") end,
    function(eid) return vsc_variable_value(eid, "max_health", "value_float") end,
    function(eid) return component_value(eid, "HealthBarComponent", "max_health") end,
}

local health_reader_idx = nil
local max_reader_idx = nil

local function read_health(eid)
    if health_reader_idx then
        local v = HEALTH_READERS[health_reader_idx](eid)
        if type(v) == "number" then return v end
    end
    for i, r in ipairs(HEALTH_READERS) do
        local v = r(eid)
        if type(v) == "number" then
            health_reader_idx = i
            return v
        end
    end
    return nil
end

local function read_max_health(eid)
    if max_reader_idx then
        local v = MAX_READERS[max_reader_idx](eid)
        if type(v) == "number" then return v end
    end
    for i, r in ipairs(MAX_READERS) do
        local v = r(eid)
        if type(v) == "number" then
            max_reader_idx = i
            return v
        end
    end
    return nil
end

local function collect_inventory(eid)
    -- Returns (id_set, names): id_set for ground-item exclusion, names for UI.
    local id_set = {}
    local names = {}
    local ok, ids = pcall(GameGetAllInventoryItems, eid)
    if not ok or type(ids) ~= "table" then return id_set, names end
    for _, id in ipairs(ids) do id_set[id] = true end
    for i = 1, math.min(#ids, INVENTORY_CAP) do
        local name = component_value(ids[i], "ItemComponent", "item_name")
        if type(name) ~= "string" or name == "" then
            name = entity_name(ids[i]) -- fallback: internal entity name
        end
        if type(name) ~= "string" or name == "" then
            name = "item_" .. tostring(ids[i])
        end
        names[i] = name
    end
    return id_set, names
end

local enemy_tag = ENEMY_TAGS[1]
local ground_tag = GROUND_TAGS[1]

local function scan_enemies(px, py)
    local ids = radius_entities(px, py, ENEMY_RADIUS, enemy_tag)
    if #ids == 0 then
        for _, tag in ipairs(ENEMY_TAGS) do
            if tag ~= enemy_tag then
                local alt = radius_entities(px, py, ENEMY_RADIUS, tag)
                if #alt > 0 then
                    ids, enemy_tag = alt, tag
                    break
                end
            end
        end
    end
    local list = {}
    for _, eid in ipairs(ids) do
        local x, y = entity_pos(eid)
        list[#list + 1] = {
            name = entity_name(eid) or ("e" .. tostring(eid)),
            dist = x and math.floor(dist(x, y, px, py)) or nil,
            hp = read_health(eid),
        }
    end
    table.sort(list, function(a, b)
        return (a.dist or 1e18) < (b.dist or 1e18)
    end)
    local capped = {}
    for i = 1, math.min(#list, ENEMY_CAP) do capped[i] = list[i] end
    return capped
end

local function scan_ground_items(px, py, own_ids)
    local ids = radius_entities(px, py, GROUND_RADIUS, ground_tag)
    if #ids == 0 then
        for _, tag in ipairs(GROUND_TAGS) do
            if tag ~= ground_tag then
                local alt = radius_entities(px, py, GROUND_RADIUS, tag)
                if #alt > 0 then
                    ids, ground_tag = alt, tag
                    break
                end
            end
        end
    end
    local list = {}
    for _, eid in ipairs(ids) do
        if not own_ids[eid] then -- own inventory items sit at player pos; skip
            local x, y = entity_pos(eid)
            local name = component_value(eid, "ItemComponent", "item_name")
            if type(name) ~= "string" or name == "" then
                name = entity_name(eid)
            end
            list[#list + 1] = {
                name = name or ("item_" .. tostring(eid)),
                dist = x and math.floor(dist(x, y, px, py)) or nil,
            }
        end
    end
    table.sort(list, function(a, b)
        return (a.dist or 1e18) < (b.dist or 1e18)
    end)
    local capped = {}
    for i = 1, math.min(#list, GROUND_CAP) do capped[i] = list[i] end
    return capped
end

------------------------------------------------------------------------------
-- One-time spawn diagnostics (results ship in payload.diag; the launcher
-- prints it once. NOTE: GamePrint does NOT reach logger.txt in this build,
-- but API errors DO — wrong component names are still visible there.)
------------------------------------------------------------------------------
local diag = nil

local function build_diag(pid, px, py)
    local d = {}
    d.vsc_vars_player = vsc_var_names(pid, 16)
    local okh, ch = pcall(EntityGetComponent, pid, "HealthBarComponent")
    d.hbar_count = (type(ch) == "table") and #ch or -1
    d.player_hp = read_health(pid)
    d.player_max_hp = read_max_health(pid)
    d.hp_reader_idx = health_reader_idx
    d.max_reader_idx = max_reader_idx
    local oki, inv = pcall(GameGetAllInventoryItems, pid)
    if oki and type(inv) == "table" then
        d.inv_count = #inv
        if #inv > 0 then
            d.inv0_entity_name = entity_name(inv[1])
            d.inv0_item_name = component_value(inv[1], "ItemComponent", "item_name")
            d.inv0_vsc_vars = vsc_var_names(inv[1], 8)
        end
    else
        d.inv_count = 0
    end
    local okb, b = pcall(BiomeMapGetName, px, py)
    d.biome_raw = okb and tostring(b) or "ERROR"
    return d
end

------------------------------------------------------------------------------
-- Game hooks (full list documented in mods/example/init.lua)
------------------------------------------------------------------------------
local player_id = nil
local frame_counter = 0
local first_update_logged = false

-- Cached rate-limited scans (only refreshed on their cadence tick).
local cache = {
    inventory = nil,
    enemies = nil,
    ground = nil,
    biome = nil,
}

function OnPlayerSpawned(entity_player)
    player_id = entity_player
    log("[bot_bridge] player spawned, id=" .. tostring(player_id))
    local x, y = entity_pos(player_id)
    if x then
        diag = build_diag(player_id, x, y)
    end
end

function OnWorldPostUpdate()
    frame_counter = frame_counter + 1
    if not first_update_logged then
        first_update_logged = true
        log("[bot_bridge] world update hook active (transport=" .. transport_mode .. ")")
    end
    if frame_counter % SEND_EVERY_N_FRAMES ~= 0 then return end

    local payload = {
        v = 2,
        mode = transport_mode,
        frame = GameGetFrameNum(),
        t = GameGetRealWorldTimeSinceStarted(),
        alive = false,
    }

    local ok_alive, alive = pcall(EntityGetIsAlive, player_id)
    if ok_alive and alive then
        local x, y = entity_pos(player_id)
        if x then
            payload.px = x
            payload.py = y
            payload.alive = true
            payload.hp = read_health(player_id)
            payload.max_hp = read_max_health(player_id)

            if frame_counter % ENEMY_SCAN_EVERY == 0 then
                local own_ids, names = collect_inventory(player_id)
                cache.inventory = names
                cache.enemies = scan_enemies(x, y)
                cache.ground = scan_ground_items(x, y, own_ids)
            end
            if frame_counter % BIOME_SCAN_EVERY == 0 then
                local ok_b, b = pcall(BiomeMapGetName, x, y)
                if ok_b and type(b) == "string" and b ~= "" then
                    cache.biome = b
                end
            end
        end
    end

    if cache.inventory then payload.inventory = cache.inventory end
    if cache.enemies then payload.enemies = cache.enemies end
    if cache.ground then payload.ground_items = cache.ground end
    if cache.biome then payload.biome = cache.biome end
    if diag then payload.diag = diag end

    send_payload(payload)
end

------------------------------------------------------------------------------
setup_transport()
local banner = "[bot_bridge] v2 loaded (transport=" .. transport_mode .. ")"
print(banner)
pcall(GamePrint, banner) -- GamePrint may not be available this early; print() is the fallback
