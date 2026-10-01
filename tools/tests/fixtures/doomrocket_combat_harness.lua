-- Minimal engine boundary for executing the production combat actions in Lua 5.1.
-- Animation rendering, physics and the native BT scheduler are not simulated.
function require() end
function class(existing, parent)
    return setmetatable({ super = parent }, { __index = parent })
end
BTNode = {}
BTConditions = { ask_target_before_attacking = function() return true end }
script_data = {}
events = { animations = {}, rpcs = {}, meshes = {}, logs = {}, spawns = 0,
    nav_goals = {}, nav_queries = 0, nav_stops = 0 }
function printf(format, ...)
    table.insert(events.logs, string.format(format, ...))
end

local vector_mt = {}
local function vector(x, y, z)
    return setmetatable({ x = x or 0, y = y or 0, z = z or 0 }, vector_mt)
end
vector_mt.__add = function(a, b) return vector(a.x+b.x, a.y+b.y, a.z+b.z) end
vector_mt.__sub = function(a, b) return vector(a.x-b.x, a.y-b.y, a.z-b.z) end
vector_mt.__mul = function(a, b) return vector(a.x*b, a.y*b, a.z*b) end
Vector3 = setmetatable({}, { __call = function(_, ...) return vector(...) end })
Vector3.zero = function() return vector() end
Vector3.forward = function() return vector(0, 1, 0) end
Vector3.up = function() return vector(0, 0, 1) end
Vector3.right = function() return vector(1, 0, 0) end
Vector3.flat = function(v) return vector(v.x, v.y, 0) end
Vector3.dot = function(a, b) return a.x*b.x+a.y*b.y+a.z*b.z end
Vector3.length_squared = function(v) return Vector3.dot(v, v) end
Vector3.length = function(v) return math.sqrt(Vector3.length_squared(v)) end
Vector3.normalize = function(v) return v * (1/Vector3.length(v)) end
Vector3.distance = function(a, b) return Vector3.length(a-b) end
Vector3.is_valid = function(v) return v ~= nil end
Vector3.flat_angle = function() return 0 end
function Vector3Box(v)
    return {
        value = v,
        store = function(self, value) self.value = value end,
        unbox = function(self) return self.value end,
    }
end
Quaternion = setmetatable({}, { __call = function() return {} end })
Quaternion.forward = Vector3.forward
Quaternion.look = function() return {} end
Quaternion.multiply = function() return {} end
math.clamp = function(v, low, high) return math.max(low, math.min(high, v)) end
Math = { random = function() return 0.5 end }

unit = { alive = true, position = vector() }
target = { alive = true, position = vector(0, 5, 0) }
weapon = { alive = true, position = vector(), rocket_visible = true }
POSITION_LOOKUP = { [unit] = unit.position, [target] = target.position }
HEALTH_ALIVE = { [unit] = true }
Unit = {
    alive = function(u) return u and u.alive == true end,
    node = function(u, name)
        assert(u and u.alive, 'node access to dead unit')
        assert(name, 'missing node name')
        return name
    end,
    world_position = function(u) assert(u.alive); return u.position end,
    local_position = function(u) assert(u.alive); return u.position end,
    world_rotation = function(u) assert(u.alive); return {} end,
    local_rotation = function(u) assert(u.alive); return {} end,
    animation_find_constraint_target = function() return 1 end,
    has_animation_event = function() return true end,
    set_mesh_visibility = function(u, mesh, visible)
        u.rocket_visible = visible
        table.insert(events.meshes, { mesh = mesh, visible = visible })
    end,
}
local function noop() end
local navigation = {
    enabled = true,
    set_enabled = function(self, enabled) self.enabled = enabled end,
    max_speed = 1,
    set_max_speed = function(self, speed) self.max_speed = speed end,
    get_max_speed = function(self) return self.max_speed end,
    number_failed_move_attempts = function(self) return self.failed_attempts or 0 end,
    traverse_logic = function() return 'test_traverse' end,
    move_to = function(self, goal)
        self.failed_attempts = 0
        self.goal = goal
        table.insert(events.nav_goals, goal)
    end,
    stop = function(self) self.goal = nil; events.nav_stops = events.nav_stops + 1 end,
}
local locomotion = { set_wanted_velocity = noop, set_wanted_rotation = noop, use_lerp_rotation = noop }
local status = {}
ScriptUnit = {
    extension = function(_, name)
        assert(name == 'ai_inventory_system')
        return { get_unit = function() return weapon end }
    end,
    has_extension = function(_, name)
        if name == 'status_system' then return status end
    end,
}
AiUtils = {
    random = function() return 4 end,
    anim_event = function(_, data, name)
        if data.last_anim ~= name then
            table.insert(events.animations, name)
            data.last_anim = name
        end
    end,
    clear_anim_event = function(data) data.last_anim = nil end,
    clear_temp_anim_event = noop,
    get_default_breed_move_speed = function() return 1 end,
    add_attack_intensity = noop,
}
LocomotionUtils = {
    rotation_towards_unit_flat = function() return {} end,
    look_at_position_flat = function() return {} end,
    ray_can_go_on_mesh = function(world, origin, goal, traverse, above, below)
        assert(world == 'test_nav_world' and traverse == 'test_traverse')
        assert(above <= 0.5 and below <= 0.5, 'unsafe vertical projection')
        events.nav_queries = events.nav_queries + 1
        if nav_policy then return nav_policy(origin, goal) end
        return true, origin, goal
    end,
}
PerceptionUtils = {
    pick_ratling_gun_target = function(_, bb)
        return bb.perceived_target, bb.perceived_node, bb.old_target_visible
    end,
}
local bot_group = {
    _urgent_targets = {},
    ranged_attack_started = function(self, attacker)
        assert(self._urgent_targets[attacker] ~= math.huge, 'duplicate notification')
        self._urgent_targets[attacker] = math.huge
    end,
    ranged_attack_ended = function(self, attacker) self._urgent_targets[attacker] = 0 end,
}
Managers = { state = {
    unit_storage = { go_id = function() return 1 end },
    network = { anim_event = function(_, _, name) table.insert(events.animations, name) end },
    entity = { system = function(_, name)
        if name == 'ai_bot_group_system' then return bot_group end
        return {}
    end },
    debug = { drawer = function() return { reset = noop } end },
    difficulty = { get_difficulty_rank = function() return 1 end },
    unit_spawner = { spawn_network_unit = function()
        if reject_spawn then error('spawn failed') end
        events.spawns = events.spawns + 1
        return {}, events.spawns
    end },
} }
Network = { peer_id = function() return 'server' end }
AiAnimUtils = {
    position_network_scale = function(v) return v end,
    rotation_network_scale = function(v) return v end,
    velocity_network_scale = function(v) return v end,
}
LightWeightProjectiles = { test = { spread = 0, attack_power_level = {1}, impact_push_speed = 0 } }
ProjectileRocket = { new = function() return {} end }
mod = {
    projectiles = {},
    network_send = function(_, name) table.insert(events.rpcs, name) end,
    _choose_warlock_combat_voice = function() return 1 end,
    doomrocket_ballistics = { solve_launch_velocity = function()
        if reject_solution then return nil end
        return vector(0, 10, 1), 0.5
    end },
}
function get_mod() return mod end

blackboard = {
    target_unit = target, target_dist = 5, target_speed_away = 0,
    target_is_not_downed = true, perceived_target = target, perceived_node = 'head',
    breed = { default_inventory_template = 'gun', walk_speed = 1, run_speed = 3 },
    nav_world = 'test_nav_world',
    navigation_extension = navigation, locomotion_extension = locomotion,
    utility_actions = { push_attack = { time_since_last = 100 } },
}
reload_action = {}
launch_action = {
    fire_rate_at_start = 1, fire_rate_at_end = 1, max_fire_rate_at_percentage = 1,
    target_switch_distance = {1, 1}, attack_time = {1, 1},
    light_weight_projectile_template_name = 'test',
}
shove_action = { name = 'push_attack', impact_time = 0.65, duration = 1.2, attack_anim = 'attack_shoot_align' }
BreedActions = { skaven_doomrocket = { push_attack = shove_action } }
BreedBehaviors = {}

function selected_close_combat_child()
    -- Inspect the production tree's ordering using its real conditions. The
    -- native BTSelector selects its first eligible child on every evaluation.
    local children = BreedBehaviors.skaven_doomrocket[7]
    for i = 2, #children do
        local child = children[i]
        if not child.condition or BTConditions[child.condition](blackboard, child.condition_args, child.action_data) then
            return child.name, child[1]
        end
    end
end

function attach_actions()
    reload = setmetatable({ _tree_node = { action_data = reload_action } }, { __index = BTDoomrocketReloadAction })
    launch = setmetatable({ _tree_node = { action_data = launch_action } }, { __index = BTDoomrocketLaunchAction })
    shove = setmetatable({ _tree_node = { action_data = shove_action } }, { __index = BTDoomrocketShoveAction })
    reposition = setmetatable({ _tree_node = { action_data = BreedActions.skaven_doomrocket.reposition } }, { __index = BTDoomrocketRepositionAction })
    launch._fire_from_position_direction = function() return unit.position, Vector3.forward() end
    launch._projectile_target_position = function() return target.position end
end

function become_close()
    target.position = vector(0, 1, 0)
    POSITION_LOOKUP[target] = target.position
    blackboard.target_dist = 1
end

function place_unit(x, y, z)
    unit.position = vector(x, y, z)
    POSITION_LOOKUP[unit] = unit.position
    blackboard.target_dist = Vector3.distance(unit.position, target.position)
end

function request_reposition(t)
    become_close()
    finish_shove(t or 0)
    blackboard.utility_actions.push_attack.time_since_last = 1.3
end

function enter_reload(t)
    reload:enter(unit, blackboard, t or 0)
end

function run_reload(t, dt, callback)
    blackboard.anim_cb_attack_windup_start_finished = callback
    return reload:run(unit, blackboard, t, dt)
end

function finish_shove(t)
    -- The native selector aborts the sequence and its active child first.
    shove:enter(unit, blackboard, t)
    -- Do not emulate physical damage. This test concerns entry/exit ownership.
    blackboard.doomrocket_shove_data.impact_applied = true
    assert(shove:run(unit, blackboard, t + 1.3, 1.3) == 'done')
    shove:leave(unit, blackboard, t + 1.3, 'done')
end

function count_event(group, value)
    local count = 0
    for _, event in ipairs(events[group]) do
        if event == value then count = count + 1 end
    end
    return count
end
