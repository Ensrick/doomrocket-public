#!/usr/bin/env python3
"""Issue #33: the rocket detonates on contact instead of sliding to a stop.

Executes the production ProjectileRocket in Lua 5.1. Physics is a prescribed
input: a raycast stub intersects rays with axis-aligned planes owned by stub
units, and the test moves the rocket body between frames the way a physics step
would. These tests prove the contact detection and detonation point, not
in-game physics, collision filters or visuals.
"""

from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
PROJECTILE = ROOT / "scripts/mods/doomrocket/extensions/projectile_rocket.lua"

HARNESS = r"""
    local V = {}
    V.__index = V
    function Vector3(x, y, z) return setmetatable({ x = x, y = y, z = z }, V) end
    V.__add = function(a, b) return Vector3(a.x + b.x, a.y + b.y, a.z + b.z) end
    V.__sub = function(a, b) return Vector3(a.x - b.x, a.y - b.y, a.z - b.z) end
    V.__mul = function(a, b)
        if type(a) == 'number' then a, b = b, a end
        return Vector3(a.x * b, a.y * b, a.z * b)
    end
    Vector3Ops = {
        length = function(v) return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) end,
        dot = function(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end,
    }
    Vector3Ops.direction_length = function(v)
        local length = Vector3Ops.length(v)
        if length == 0 then return Vector3(0, 0, 0), 0 end
        return v * (1 / length), length
    end
    setmetatable(Vector3Ops, { __call = function(_, x, y, z) return Vector3(x, y, z) end })
    local construct = Vector3
    Vector3 = Vector3Ops
    Vector3.normal = function(v) return (Vector3.direction_length(v)) end
    Vector3.distance = function(a, b) return Vector3.length(a - b) end
    Vector3.zero = function() return Vector3(0, 0, 0) end
    setmetatable(Vector3, { __call = function(_, x, y, z) return construct(x, y, z) end })
    function Vector3Box(v)
        local box = { value = Vector3(v.x, v.y, v.z) }
        function box:store(value) self.value = Vector3(value.x, value.y, value.z) end
        function box:unbox() return Vector3(self.value.x, self.value.y, self.value.z) end
        return box
    end

    Quaternion = {
        look = function(direction) return { look = direction } end,
        multiply = function(a, b) return a end,
        from_elements = function() return {} end,
    }
    World = {
        move_particles = function() end,
        create_particles = function() return 7 end,
        destroy_particles = function() end,
        physics_world = function() return 'physics_world' end,
    }
    stingray = { PhysicsWorld = { linear_sphere_sweep = function() end } }

    rocket_unit = { name = 'rocket' }
    shooter_unit = { name = 'shooter' }
    wall_unit = { name = 'wall' }
    floor_unit = { name = 'floor' }
    player_unit = { name = 'player' }

    body = { position = Vector3(0, 0, 1), velocity = Vector3(10, 0, 0) }
    Actor = {
        velocity = function(actor) return body.velocity end,
        position = function(actor) return body.position end,
        rotation = function(actor) return { rotation = true } end,
        teleport_rotation = function() end,
        add_velocity = function() end,
        set_angular_velocity = function(actor, value)
            body.angular_velocity = Vector3(value.x, value.y, value.z)
        end,
        unit = function(actor) return actor.unit end,
    }
    function printf(fmt, ...) impact_logs[#impact_logs + 1] = string.format(fmt, ...) end
    impact_logs = {}
    Unit = {
        actor = function(unit, name)
            if name == 'c_afro' then return unit.afro end
            return { unit = rocket_unit }
        end,
        alive = function(u) return u ~= nil and not u.dead end,
        world = function() return 'world' end,
        local_position = function() return Vector3(0, 0, 0) end,
        set_local_rotation = function() end,
        delta_rotation = function() end,
        destroy_actor = function() end,
    }

    -- Planes: { axis = 'x'|'y'|'z', value = n, unit = owner, filter = which filter
    -- sees it }. Level geometry answers only the static-only filter by default.
    STATIC = 'filter_player_ray_projectile_static_only'
    ENEMY = 'filter_enemy_ray_projectile'
    planes = {}
    ray_casts = 0
    PhysicsWorld = {
        prepare_actors_for_raycast = function() end,
        immediate_raycast = function(world, from, direction, distance, mode, filter_key, filter)
            assert(mode == 'all' and filter_key == 'collision_filter')
            assert(filter == STATIC or filter == ENEMY, filter)
            ray_casts = ray_casts + 1
            local hits = {}
            for _, plane in ipairs(planes) do
                local d = direction[plane.axis]
                if d ~= 0 and (plane.filter or STATIC) == filter then
                    local s = (plane.value - from[plane.axis]) / d
                    if s >= 0 and s <= distance then
                        local actor = plane.actor or { unit = plane.unit }
                        hits[#hits + 1] = { from + direction * s, s, Vector3(0, 0, 1), actor }
                    end
                end
            end
            -- Native "all" results carry no ordering guarantee; reverse them.
            local reversed = {}
            for i = #hits, 1, -1 do reversed[#reversed + 1] = hits[i] end
            return #reversed > 0 and reversed or nil
        end,
    }

    function class(c)
        c = c or {}
        c.__index = c
        c.new = function(cls, ...)
            local o = setmetatable({}, cls)
            o:init(...)
            return o
        end
        return c
    end

    rpcs = {}
    deleted = {}
    Managers = {
        player = { is_server = true },
        package = { load = function() end },
        state = {
            unit_storage = { go_id = function() return 42 end },
            unit_spawner = { mark_for_deletion = function(_, u) deleted[#deleted + 1] = u end },
            network = { network_transmit = { send_rpc_server = function(_, name, ...)
                rpcs[#rpcs + 1] = { name = name, args = { ... } }
            end } },
        },
    }
    NetworkLookup = { explosion_templates = { doomrocket_explosion = 3 }, damage_sources = { skaven_doomrocket = 9 } }
    mod = {
        projectiles = {},
        _play_warlock_combat_voice = function() end,
        _play_doomrocket_launch_sound = function() end,
        _doomrocket_sound_impact_requested = function() end,
    }
    function get_mod() return mod end
"""

SETUP = r"""
    rocket = ProjectileRocket:new(rocket_unit, shooter_unit, Vector3(30, 0, 0), nil, 0)
    function step(dt) rocket:update(dt) end
    function exploded_at()
        assert(#rpcs == 1 and rpcs[1].name == 'rpc_create_explosion')
        return rpcs[1].args[3]
    end
"""


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(PROJECTILE.read_text(encoding="utf-8"))
    lua.execute(SETUP)
    return lua


class RocketImpactTests(unittest.TestCase):
    def test_contact_ahead_detonates_at_the_contact_point(self):
        lua = runtime()
        lua.execute("""
            planes[1] = { axis = 'x', value = 5, unit = wall_unit }
            step(0.016)                      -- not armed for the first 0.1 s
            step(0.09)
            assert(ray_casts == 0 and #rpcs == 0)
            body.position = Vector3(4.6, 0, 1)
            step(0.016)                      -- 0.4 m short: within travel + margin
            local at = exploded_at()
            assert(math.abs(at.x - 5) < 1e-9 and at.y == 0 and at.z == 1)
            assert(rocket.exploded and deleted[1] == rocket_unit)
        """)

    def test_contact_beyond_one_frame_of_travel_does_not_detonate(self):
        lua = runtime()
        lua.execute("""
            planes[1] = { axis = 'x', value = 5, unit = wall_unit }
            step(0.2)
            body.position = Vector3(3, 0, 1)
            step(0.016)                      -- 2 m away; reach is 0.46 m
            assert(#rpcs == 0 and not rocket.exploded)
        """)

    def test_closest_contact_wins_and_rocket_and_shooter_are_ignored(self):
        lua = runtime()
        lua.execute("""
            planes[1] = { axis = 'x', value = 4.7, unit = rocket_unit }
            planes[2] = { axis = 'x', value = 4.75, unit = shooter_unit, filter = ENEMY }
            planes[3] = { axis = 'x', value = 5.0, unit = wall_unit }
            planes[4] = { axis = 'x', value = 4.9, unit = player_unit, filter = ENEMY }
            step(0.2)
            body.position = Vector3(4.6, 0, 1)
            step(0.016)
            assert(math.abs(exploded_at().x - 4.9) < 1e-9)
        """)

    def test_bounce_resolved_by_the_physics_step_is_still_a_detonation(self):
        lua = runtime()
        lua.execute("""
            planes[1] = { axis = 'z', value = 0, unit = floor_unit }
            body.position = Vector3(0, 0, 1)
            body.velocity = Vector3(0, 0, -10)
            step(0.2)                        -- arm; remember the downward path
            body.position = Vector3(0, 0, 0.6)
            step(0.016)                      -- 0.6 m above the floor: no contact yet
            assert(#rpcs == 0)
            -- A long physics step bounces the body back up before the next update.
            body.position = Vector3(0, 0, 0.15)
            body.velocity = Vector3(0, 0, 4)
            step(0.06)
            local at = exploded_at()
            assert(at.z == 0 and at.x == 0)
        """)

    def test_clients_and_unarmed_rockets_never_cast(self):
        lua = runtime()
        lua.execute("""
            planes[1] = { axis = 'x', value = 0.2, unit = wall_unit }
            step(0.05)
            assert(ray_casts == 0 and #rpcs == 0)
            Managers.player.is_server = false
            step(0.2)
            step(0.016)
            assert(ray_casts == 0 and #rpcs == 0 and not rocket.exploded)
        """)

    def test_slow_settle_keeps_the_stop_fallback_at_the_body(self):
        lua = runtime()
        lua.execute("""
            body.velocity = Vector3(0.4, 0, 0)   -- below the cast speed floor
            step(0.4)
            body.position = Vector3(2, 0, 0.1)
            step(0.016)
            local at = exploded_at()
            assert(at.x == 2 and at.z == 0.1)
            assert(impact_logs[#impact_logs]:find('reason=stopped', 1, true))
        """)

    def test_explosion_without_contact_uses_the_body_position(self):
        lua = runtime()
        lua.execute("""
            body.position = Vector3(1, 2, 3)
            assert(rocket:rocket_explode())
            local at = exploded_at()
            assert(at.x == 1 and at.y == 2 and at.z == 3)
            assert(not rocket:rocket_explode(Vector3(0, 0, 0)))
            assert(#rpcs == 1)
        """)

    def test_near_miss_afro_volume_does_not_detonate(self):
        lua = runtime()
        lua.execute("""
            local afro = { unit = player_unit }
            player_unit.afro = afro
            planes[1] = { axis = 'x', value = 4.8, unit = player_unit, filter = ENEMY, actor = afro }
            step(0.2)
            body.position = Vector3(4.6, 0, 1)
            step(0.016)
            assert(#rpcs == 0)
        """)

    def test_contact_the_casts_cannot_see_still_detonates_on_the_next_frame(self):
        lua = runtime()
        lua.execute("""
            -- No plane at all: only the velocity can reveal the bounce.
            body.position = Vector3(0, 0, 1)
            body.velocity = Vector3(10, 0, -5)
            step(0.2)
            body.velocity = Vector3(10, 0, -5 - 9.82 * 0.016)
            step(0.016)
            assert(#rpcs == 0, 'gravity alone is ballistic')
            body.position = Vector3(0.2, 0, 0.1)
            body.velocity = Vector3(7, 0, 2)
            step(0.016)
            local at = exploded_at()
            assert(at.x == 0.2 and at.z == 0.1)
            assert(impact_logs[#impact_logs]:find('reason=deviation', 1, true))
        """)

    def test_long_frames_of_pure_ballistic_flight_never_trigger_the_deviation(self):
        lua = runtime()
        lua.execute("""
            body.velocity = Vector3(12, 0, 8)
            step(0.2)
            for i = 1, 20 do
                local dt = (i % 3 == 0) and 0.1 or 0.016
                body.velocity = body.velocity + Vector3(0, 0, -9.82 * dt)
                body.position = body.position + body.velocity * dt
                step(dt)
            end
            assert(#rpcs == 0 and not rocket.exploded)
        """)

    def test_every_detonation_logs_its_reason(self):
        lua = runtime()
        lua.execute("""
            planes[1] = { axis = 'x', value = 5, unit = wall_unit }
            step(0.2)
            body.position = Vector3(4.6, 0, 1)
            step(0.016)
            assert(impact_logs[#impact_logs]:find('reason=contact', 1, true))
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
