#!/usr/bin/env python3
"""Issue #33 balance contracts, executed from the production bootstrap in Lua 5.1.

Covers the explosion knockback (owner-routed catapult without the forced
camera turn, distance-scaled) and the 0.6x
rocket damage against AI. The knockback, explosion and hook blocks are executed
as written in doomrocket.lua with engine calls stubbed. Not an in-game test.
"""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (ROOT / "scripts/mods/doomrocket/doomrocket.lua").read_text(encoding="utf-8")


def block(pattern):
    match = re.search(pattern, BOOTSTRAP, re.M | re.S)
    if not match:
        raise AssertionError(f"production block missing: {pattern}")
    return match.group()


KNOCKBACK = block(r"^local KNOCKBACK_NEAR_SPEED = .*?(?=^--setup rocket explosion template)")
EXPLOSION = block(r'^ExplosionTemplates\["doomrocket_explosion"\] = \{.*?^\}')
DAMAGE_HOOK = block(r"^local DOOMROCKET_DAMAGE_SOURCE = .*?^end\)")


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        mod = { hooks = {}, rpcs = {}, sent = {} }
        function mod._doomrocket_select_impact_event() return 'impact' end
        function mod:hook(object, method, handler)
            assert(not self.hooks[method], 'duplicate hook ' .. method)
            self.hooks[method] = { object = object, handler = handler }
        end
        function mod:network_register(name, handler) self.rpcs[name] = handler end
        function mod:network_send(name, recipient, ...) self.sent[#self.sent + 1] = { name = name, to = recipient, args = { ... } } end
        function mod:pcall(fn, ...)
            local ok, err = pcall(fn, ...)
            if not ok then self.last_error = err end
            return ok
        end
        ExplosionTemplates = {}
        DamageUtils = { calculate_damage = function() error('call through the hook') end }
        units = {
            clan_rat = { breed = { name = 'skaven_clan_rat' } },
            warlock = { breed = { name = 'skaven_doomrocket' } },
            hero = { breed = { name = 'hero_es_mercenary', is_player = true } },
            barrel = {},
            corpse = { breed = { name = 'skaven_slave' }, dead = true },
        }
        Unit = {
            alive = function(unit) return unit ~= nil and not unit.dead end,
            get_data = function(unit, key) assert(key == 'breed'); return unit.breed end,
        }
        native_calls = 0
        function native(...)
            native_calls = native_calls + 1
            native_args = { ... }
            return 10, 'second'
        end
        local V = {}
        V.__index = V
        local function vec(x, y, z) return setmetatable({ x = x, y = y, z = z }, V) end
        V.__add = function(a, b) return vec(a.x + b.x, a.y + b.y, a.z + b.z) end
        V.__sub = function(a, b) return vec(a.x - b.x, a.y - b.y, a.z - b.z) end
        V.__mul = function(a, b)
            if type(a) == 'number' then a, b = b, a end
            return vec(a.x * b, a.y * b, a.z * b)
        end
        Vector3 = setmetatable({
            zero = function() return vec(0, 0, 0) end,
            flat = function(v) return vec(v.x, v.y, 0) end,
            direction_length = function(v)
                local length = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
                if length == 0 then return vec(0, 0, 0), 0 end
                return v * (1 / length), length
            end,
        }, { __call = function(_, x, y, z) return vec(x, y, z) end })
        Vector3.normalize = function(v) return (Vector3.direction_length(v)) end
        function math.clamp(value, min, max)
            if max < value then return max elseif value < min then return min end
            return value
        end
        catapults = {}
        forced_looks = 0
        function original_force_look() forced_looks = forced_looks + 1 end
        local function force_look(first_person, rot)
            return mod.hooks.force_look_rotation.handler(original_force_look, first_person, rot)
        end
        local function player(x, y, disabled, remote)
            local unit = { player = true }
            next_go_id = (next_go_id or 40) + 1
            unit.go_id = next_go_id
            unit.owner = { remote = remote or false, network_id = function() return 'peer_' .. unit.go_id end }
            unit.status = {
                is_husk = false,
                is_disabled = function() return disabled end,
                -- Vanilla GenericStatusExtension.set_catapulted: flail state + forced look.
                set_catapulted = function(self, catapulted, velocity)
                    if fail_catapult then error('boom') end
                    catapults[#catapults + 1] = { unit = unit, catapulted = catapulted, velocity = velocity }
                    force_look({}, 'rot')
                end,
            }
            unit.position = vec(x, y, 0)
            return unit
        end
        DamageUtils.is_player_unit = function(unit) return unit.player == true end
        ScriptUnit = { has_extension = function(unit, system)
            return system == 'status_system' and unit.status or nil
        end }
        POSITION_LOOKUP = setmetatable({}, { __index = function(_, unit) return unit.position end })
        storage = {}
        Managers = {
            player = { unit_owner = function(_, unit) return unit.owner end },
            state = {
                network = { unit_game_object_id = function(_, unit) storage[unit.go_id] = unit; return unit.go_id end },
                unit_storage = { unit = function(_, id) return storage[id] end },
            },
        }
        make_player = player
        function knock(unit, impact, attacker)
            local data = ExplosionTemplates.doomrocket_explosion.explosion
            data.server_hit_func(unit, 'skaven_doomrocket', attacker or { position = vec(-10, 0, 0) }, impact or vec(0, 0, 0), data)
            return catapults[#catapults]
        end
        function hooked(target, source)
            return mod.hooks.calculate_damage.handler(native, 'output', target, 'attacker',
                'torso', 800, nil, 0, false, 'profile', 1, 1, source, 'extra')
        end
    """)
    lua.execute(KNOCKBACK)
    lua.execute(EXPLOSION)
    lua.execute(DAMAGE_HOOK)
    return lua


class BalanceContractTests(unittest.TestCase):
    def test_template_carries_no_native_catapult_or_push(self):
        explosion = runtime().eval('ExplosionTemplates.doomrocket_explosion.explosion')
        self.assertFalse(explosion["catapult_players"])
        self.assertIsNone(explosion["catapult_force"])
        # Vanilla's push falloff clamps to 1 m/s whenever player_push_speed > 1.
        self.assertIsNone(explosion["player_push_speed"])
        self.assertIsNotNone(explosion["server_hit_func"])
        self.assertEqual((explosion["max_damage_radius"], explosion["radius"]), (1.5, 6))

    def test_catapult_throw_and_lift_fall_off_linearly(self):
        lua = runtime()
        for distance, speed, lift in ((0.5, 10, 5), (1.5, 10, 5), (3.75, 6.5, 3.75), (6, 3, 2.5), (9, 3, 2.5)):
            with self.subTest(distance=distance):
                lua.execute(f"""
                    local c = knock(make_player({distance}, 0, false))
                    assert(c.catapulted == true)
                    local v = c.velocity
                    assert(math.abs(v.x - {speed}) < 1e-9 and math.abs(v.y) < 1e-9, v.x)
                    assert(math.abs(v.z - {lift}) < 1e-9, v.z)
                """)

    def test_the_throw_never_forces_the_camera_but_other_catapults_still_do(self):
        runtime().execute("""
            knock(make_player(2, 0, false))
            assert(#catapults == 1 and forced_looks == 0, 'doomrocket throw kept the camera')
            -- A vanilla catapult (rat ogre, troll) outside our call is untouched.
            mod.hooks.force_look_rotation.handler(original_force_look, {}, 'rot')
            assert(forced_looks == 1)
            assert(mod.hooks.force_look_rotation.object == 'PlayerUnitFirstPerson')
        """)

    def test_remote_players_are_thrown_by_their_own_peer(self):
        runtime().execute("""
            local victim = make_player(3, 4, false, true)
            knock(victim, Vector3(0, 0, 2))
            assert(#catapults == 0, 'the host never catapults a remote husk')
            local sent = mod.sent[1]
            assert(sent.name == 'rpc_doomrocket_catapult' and sent.to == 'peer_' .. victim.go_id)
            assert(sent.args[1] == victim.go_id)
            -- 5 m away: speed 10 - 7 * (3.5 / 4.5) along (0.6, 0.8); lift 5 - 2.5 * (3.5 / 4.5).
            local speed, lift = 10 - 7 * (3.5 / 4.5), 5 - 2.5 * (3.5 / 4.5)
            assert(math.abs(sent.args[2] - 0.6 * speed) < 1e-9 and math.abs(sent.args[3] - 0.8 * speed) < 1e-9)
            assert(math.abs(sent.args[4] - lift) < 1e-9)
            -- The owning peer applies it with the same camera guard.
            mod.rpcs.rpc_doomrocket_catapult('host', unpack(sent.args))
            assert(#catapults == 1 and catapults[1].unit == victim and forced_looks == 0)
        """)

    def test_disabled_husk_ai_and_ownerless_units_are_not_thrown(self):
        runtime().execute("""
            knock(make_player(1, 0, true))
            local data = ExplosionTemplates.doomrocket_explosion.explosion
            data.server_hit_func({ position = Vector3(1, 0, 0) }, 'skaven_doomrocket', {}, Vector3(0, 0, 0), data)
            local orphan = make_player(1, 0, false); orphan.owner = nil
            knock(orphan)
            local husk = make_player(1, 0, false); husk.status.is_husk = true
            assert(mod._doomrocket_catapult_local(husk, Vector3(1, 0, 0)) == false)
            mod.rpcs.rpc_doomrocket_catapult('host', 999, 1, 2, 3)
            storage[husk.go_id] = make_player(1, 0, false)
            mod.rpcs.rpc_doomrocket_catapult('host', husk.go_id, 'x', 2, 3)
            assert(#catapults == 0 and #mod.sent == 0)
        """)

    def test_direct_hit_throws_away_from_the_shooter(self):
        runtime().execute("""
            local c = knock(make_player(2, 0, false), Vector3(2, 0, 0), { position = Vector3(-8, 0, 0) })
            assert(math.abs(c.velocity.x - 10) < 1e-9 and c.velocity.y == 0)
        """)

    def test_a_failing_catapult_releases_the_camera_guard(self):
        runtime().execute("""
            fail_catapult = true
            assert(mod._doomrocket_catapult_local(make_player(1, 0, false), Vector3(1, 0, 0)) == false)
            assert(mod.last_error)
            fail_catapult = false
            mod.hooks.force_look_rotation.handler(original_force_look, {}, 'rot')
            assert(forced_looks == 1, 'guard must not stay set after an error')
        """)

    def test_rocket_damage_to_ai_is_sixty_percent(self):
        lua = runtime()
        lua.execute("""
            assert(mod.hooks.calculate_damage.object == DamageUtils)
            for _, name in ipairs({ 'clan_rat', 'warlock' }) do
                local damage, second = hooked(units[name], 'skaven_doomrocket')
                assert(damage == 6 and second == 'second', name)
            end
            assert(native_args[12] == 'skaven_doomrocket' and native_args[13] == 'extra')
        """)

    def test_players_props_and_other_sources_are_unchanged(self):
        lua = runtime()
        lua.execute("""
            local cases = {
                { units.hero, 'skaven_doomrocket' },
                { units.barrel, 'skaven_doomrocket' },
                { units.corpse, 'skaven_doomrocket' },
                { nil, 'skaven_doomrocket' },
                { units.clan_rat, 'warpfire_thrower' },
                { units.clan_rat, nil },
            }
            for i, case in ipairs(cases) do
                local damage, second = hooked(case[1], case[2])
                assert(damage == 10 and second == 'second', i)
            end
            assert(native_calls == #cases)
        """)

    def test_invincible_targets_stay_at_zero(self):
        lua = runtime()
        lua.execute("""
            local result = { mod.hooks.calculate_damage.handler(function() return 0, true end,
                'output', units.clan_rat, 'attacker', 'torso', 800, nil, 0, false, 'profile', 1, 1,
                'skaven_doomrocket') }
            assert(result[1] == 0 and result[2] == true)
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
