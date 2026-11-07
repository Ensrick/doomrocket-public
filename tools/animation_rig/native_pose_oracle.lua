-- Isolated VT2 SDK boot script. The staging tool supplies the immutable inputs.
-- No viewport, game code, Workshop operation, or scene authoring occurs here.
local config = require("native_pose_oracle_input")
local api = stingray or _G
local Application = api.Application or _G.Application
local World = api.World or _G.World
local Unit = api.Unit or _G.Unit
local Matrix4x4 = api.Matrix4x4 or _G.Matrix4x4
local Vector3 = api.Vector3 or _G.Vector3
local Script = api.Script or _G.Script
local world, unit, output, animation_id
local sample_index, finished = 1, false
local active_resource

local function json_string(value)
    return '"' .. value:gsub('[%z\1-\31\\"]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        return string.format('\\u%04x', string.byte(c))
    end) .. '"'
end

local function json(value)
    local kind = type(value)
    if kind == "string" then return json_string(value) end
    if kind == "number" then
        assert(value == value and value ~= math.huge and value ~= -math.huge, "Nonfinite native pose")
        return string.format("%.17g", value)
    end
    if kind == "boolean" then return value and "true" or "false" end
    assert(kind == "table", "Unsupported JSON value: " .. kind)
    local parts = {}
    if #value > 0 then
        for i = 1, #value do parts[i] = json(value[i]) end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    local keys = {}
    for key in pairs(value) do keys[#keys + 1] = key end
    table.sort(keys)
    for i, key in ipairs(keys) do parts[i] = json_string(key) .. ":" .. json(value[key]) end
    return "{" .. table.concat(parts, ",") .. "}"
end

local function xyz(v)
    return {Vector3.x(v), Vector3.y(v), Vector3.z(v)}
end

local function matrix_rows(pose)
    -- Native axes occupy rows; transpose them into conventional affine columns.
    -- Copy temporary native userdata immediately, without normalization/scaling.
    local x = xyz(Matrix4x4.x(pose))
    local y = xyz(Matrix4x4.y(pose))
    local z = xyz(Matrix4x4.z(pose))
    local t = xyz(Matrix4x4.translation(pose))
    return {{x[1], y[1], z[1], t[1]}, {x[2], y[2], z[2], t[2]},
        {x[3], y[3], z[3], t[3]}, {0, 0, 0, 1}}
end

local function stop(exit_code)
    finished = true
    if output then output:flush(); output:close(); output = nil end
    if world then Application.release_world(world); world = nil; unit = nil end
    Application.quit(exit_code)
end

local function fail(message)
    print("ANIMATION_ORACLE_FAILURE " .. tostring(message))
    stop(1)
end

local function packed(...)
    return {n = select("#", ...), ...}
end

local function require_single_animation_layer()
    assert(unit and Unit.alive(unit), "Native oracle unit is no longer alive")
    assert(Unit.has_animation_state_machine(unit), "Native oracle unit has no animation state machine")
    -- The compiled oracle controller has one zero-based layer. Preserve the
    -- return count: one nil state still describes an existing, idle layer;
    -- no returns describes zero layers and must never reach native layer APIs.
    local states = packed(Unit.animation_get_state(unit))
    assert(states.n == 1, "Native oracle requires exactly one animation layer")
end

local function start_animation(resource)
    require_single_animation_layer()
    animation_id = Unit.crossfade_animation(unit, resource, 0, 0, false, "normal")
    Unit.crossfade_animation_set_speed(unit, animation_id, 0)
    active_resource = resource
end

function init()
    local ok, message = xpcall(function()
        local provenance_file = assert(io.open(config.compiled_provenance_file, "r"))
        local provenance_text = provenance_file:read("*a")
        provenance_file:close()
        for _, key in ipairs({"compiled_unit_sha256", "compiled_animation_sha256", "sdk_executable_sha256"}) do
            local hash = provenance_text:match('"' .. key .. '"%s*:%s*"([a-f0-9]+)"')
            assert(hash and #hash == 64, "Missing compiled resource SHA: " .. key)
            config.provenance[key] = hash
        end
        for _, clip in ipairs(config.provenance.clips or {}) do
            local key = ("compiled_" .. clip.clip):gsub("([^%w])", "%%%1")
            local hash = provenance_text:match('"' .. key .. '"%s*:%s*"([a-f0-9]+)"')
            assert(hash and #hash == 64, "Missing compiled clip SHA: " .. clip.clip)
            clip.compiled_animation_sha256 = hash
        end
        -- VT2's SDK fork takes a world name before the documented flags.
        world = Application.new_world("animation_native_pose_oracle", Application.DISABLE_PHYSICS,
            Application.DISABLE_RENDERING, Application.DISABLE_SOUND, Application.DISABLE_APEX_CLOTH)
        unit = World.spawn_unit(world, config.unit_resource)
        require_single_animation_layer()
        Unit.disable_animation_state_machine(unit)
        Unit.set_animation_bone_mode(unit, "transform")
        Unit.set_animation_root_mode(unit, "ignore")
        start_animation(config.animation_resource)
        config.unit_node_indices = {}
        for _, name in ipairs(config.bone_names) do config.unit_node_indices[name] = Unit.node(unit, name) end
        output = assert(io.open(config.output_file, "w"))
        output:write('{"schema":1,"status":"native-sdk-poses-recorded","provenance":', json(config.provenance),
            ',"unit_node_indices":', json(config.unit_node_indices),
            ',"matrix_convention":', json({representation = "4x4 rows, affine column vectors",
                extraction = "native Matrix4x4 rows x/y/z/translation are transposed into output columns 0/1/2/3; bottom row [0,0,0,1]",
                units = "raw SDK units and scales, no conversion", bone_mode = "transform", root_mode = "ignore",
                sampling = "set frozen crossfade time; update_animations(1/fps); update_scene(0)"}),
            ',"samples":[')
        print("ANIMATION_ORACLE_STARTED " .. #config.samples .. " samples; " .. #config.bone_names .. " bones")
    end, debug.traceback)
    if not ok then fail(message) end
end

function update(dt)
    if finished then return end
    local ok, message = xpcall(function()
        -- Callback wall-clock dt is unused. Small compatibility batches stay
        -- below temporary native math storage limits (eight bones per sample).
        for _ = 1, config.samples_per_update do
            require_single_animation_layer()
            local requested = config.samples[sample_index]
            local resource = requested.animation_resource or config.animation_resource
            if active_resource ~= resource then
                start_animation(resource)
            end
            Unit.crossfade_animation_set_time(unit, animation_id, requested.time_seconds, true)
            World.update_animations(world, 1 / (requested.sample_fps or config.fps))
            World.update_scene(world, 0)
            local sample = {frame = requested.frame, sample_index = sample_index - 1,
                time_seconds = requested.time_seconds, bones_world = {}, bones_local = {}}
            if requested.clip then sample.clip = requested.clip end
            for _, name in ipairs(config.bone_names) do
                local vectors, quaternions, matrices = Script.temp_count()
                local node = config.unit_node_indices[name]
                sample.bones_local[name] = matrix_rows(Unit.local_pose(unit, node))
                sample.bones_world[name] = matrix_rows(Unit.world_pose(unit, node))
                Script.set_temp_count(vectors, quaternions, matrices)
            end
            local vectors, quaternions, matrices = Script.temp_count()
            sample.animation_wanted_root_pose = matrix_rows(Unit.animation_wanted_root_pose(unit))
            Script.set_temp_count(vectors, quaternions, matrices)
            if sample_index > 1 then output:write(",") end
            output:write(json(sample))
            if sample_index % 60 == 0 then output:flush(); print("ANIMATION_ORACLE_PROGRESS " .. sample_index) end
            sample_index = sample_index + 1
            if sample_index > #config.samples then
                output:write('],"sample_count":', #config.samples, ',"bone_count":', #config.bone_names, '}\n')
                local count = #config.samples
                if output then output:flush(); output:close(); output = nil end
                print("ANIMATION_ORACLE_COMPLETE " .. count)
                stop(0)
                return
            end
        end
    end, debug.traceback)
    if not ok then fail(message) end
end

function render() end
function shutdown()
    if output then output:close(); output = nil end
end
