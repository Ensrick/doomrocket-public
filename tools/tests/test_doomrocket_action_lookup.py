#!/usr/bin/env python3
"""Issue #14: execute registration and host/husk network boundaries in Lua 5.1.

Always-run tests model the documented engine boundary (including its throwing
metatable), execute production actions/tuning, and mutate away registration to
prove the reported exception is detected. When the local game-source checkout
is available, two additional tests execute its actual AISystem encoder and
AI extension accessors. No game code or downloaded logs are vendored here.
Neither lane is an in-game navigation or multiplayer acceptance test.
"""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaError

from test_doomrocket_reload_lifecycle import ROOT, create_runtime


REGISTRATION = ROOT / "scripts/mods/doomrocket/utils/doomrocket_action_lookup.lua"
NATIVE_ROOT = ROOT.parent / "Vermintide-2-Source-Code"

BOUNDARY = """
    NetworkLookup = { bt_action_names = { 'n/a', 'push_attack',
        'wind_up_ratling_gun', 'shoot_ratling_gun', 'unrelated_action' } }
    for id, name in ipairs(NetworkLookup.bt_action_names) do
        NetworkLookup.bt_action_names[name] = id
    end
    lookup_metatable = { __index = function(_, key)
        error('[NetworkLookup.lua] Table bt_action_names does not contain key: ' .. tostring(key))
    end }
    setmetatable(NetworkLookup.bt_action_names, lookup_metatable)
    network_fields = {}
    function send_action_frame()
        local name = blackboard.action and blackboard.action.name or 'n/a'
        network_fields.bt_action_name = NetworkLookup.bt_action_names[name]
        return network_fields.bt_action_name
    end
    function receive_action_frame()
        return NetworkLookup.bt_action_names[network_fields.bt_action_name]
    end
"""


def runtime(register=True):
    lua = create_runtime()
    lua.execute(BOUNDARY)
    if register:
        lua.execute(REGISTRATION.read_text(encoding="utf-8"))
    return lua


def native_function(relative_path, name):
    source = (NATIVE_ROOT / relative_path).read_text(encoding="utf-8")
    match = re.search(r"(?m)^" + re.escape(name) + r" = function\b.*?\nend", source, re.S)
    if not match:
        raise AssertionError(f"Missing native method {name}; update the source-boundary test")
    return match.group()


class DoomrocketActionLookupTests(unittest.TestCase):
    def test_exact_reported_exception_without_registration_after_kick(self):
        lua = runtime(register=False)
        lua.execute("request_reposition(); reposition:enter(unit, blackboard, 1.3)")
        with self.assertRaisesRegex(LuaError, "bt_action_names does not contain key: reposition"):
            lua.execute("send_action_frame()")

    def test_host_and_husk_resolve_relocation_after_kick(self):
        lua = runtime()
        lua.execute("""
            request_reposition()
            reposition:enter(unit, blackboard, 1.3)
            assert(reposition:run(unit, blackboard, 1.3, 0) == 'running')
            assert(send_action_frame() == NetworkLookup.bt_action_names.reposition)
            assert(receive_action_frame() == 'reposition')
        """)

    def test_no_safe_route_still_has_a_valid_network_action(self):
        lua = runtime()
        lua.execute("""
            nav_policy = function() return false end
            request_reposition()
            reposition:enter(unit, blackboard, 1.3)
            assert(reposition:run(unit, blackboard, 1.3, 0) == 'done')
            reposition:leave(unit, blackboard, 1.3, 'done')
            -- Crunch's log reports no_safe_route before the serialization crash.
            send_action_frame()
            assert(receive_action_frame() == 'reposition')
        """)

    def test_interruption_and_next_action_do_not_remove_registration(self):
        lua = runtime()
        lua.execute("""
            request_reposition()
            reposition:enter(unit, blackboard, 1.3)
            reposition:leave(unit, blackboard, 1.5, 'aborted')
            send_action_frame()
            assert(receive_action_frame() == 'reposition')
            blackboard.action = nil -- Native no-action/close idle result.
            send_action_frame()
            assert(receive_action_frame() == 'n/a')
            blackboard.action = { name = 'push_attack' }
            send_action_frame()
            assert(receive_action_frame() == 'push_attack')
        """)

    def test_both_peers_produce_identical_round_tripping_ids(self):
        host, client = runtime(), runtime()
        for name in ("fire_rocket", "reposition"):
            action_id = host.eval("NetworkLookup.bt_action_names")[name]
            self.assertEqual(client.eval("NetworkLookup.bt_action_names")[action_id], name)
            self.assertEqual(client.eval("NetworkLookup.bt_action_names")[name], action_id)

    def test_reload_is_idempotent_and_keeps_native_entries_and_metatable(self):
        lua = runtime()
        lua.execute("""
            original_count = #NetworkLookup.bt_action_names
            original_fire = NetworkLookup.bt_action_names.fire_rocket
            original_reposition = NetworkLookup.bt_action_names.reposition
        """)
        lua.execute(REGISTRATION.read_text(encoding="utf-8"))
        lua.execute("""
            assert(#NetworkLookup.bt_action_names == original_count)
            assert(NetworkLookup.bt_action_names.fire_rocket == original_fire)
            assert(NetworkLookup.bt_action_names.reposition == original_reposition)
            assert(NetworkLookup.bt_action_names.unrelated_action == 5)
            assert(getmetatable(NetworkLookup.bt_action_names) == lookup_metatable)
        """)

    def test_reuses_an_existing_valid_action_id(self):
        lua = runtime(register=False)
        lua.execute("""
            NetworkLookup.bt_action_names[6] = 'reposition'
            NetworkLookup.bt_action_names.reposition = 6
        """)
        lua.execute(REGISTRATION.read_text(encoding="utf-8"))
        lua.execute("""
            assert(NetworkLookup.bt_action_names.reposition == 6)
            assert(NetworkLookup.bt_action_names.fire_rocket == 7)
            assert(#NetworkLookup.bt_action_names == 7)
        """)

    def test_rejects_corrupt_existing_mapping_instead_of_overwriting_other_mod(self):
        lua = runtime(register=False)
        lua.execute("NetworkLookup.bt_action_names.reposition = 5")
        with self.assertRaisesRegex(LuaError, "inconsistent bt_action_names entry for reposition"):
            lua.execute(REGISTRATION.read_text(encoding="utf-8"))
        self.assertEqual(lua.eval("NetworkLookup.bt_action_names[5]"), "unrelated_action")

    def test_action_names_are_explicit_without_native_breed_reinitialization(self):
        lua = runtime()
        lua.execute("assert(BreedActions.skaven_doomrocket.reposition.name == 'reposition')")
        source = (ROOT / "scripts/mods/doomrocket/breeds/skaven_doomrocket.lua").read_text(encoding="utf-8")
        assignment = re.search(r'BreedActions\.skaven_doomrocket\.fire_rocket\.name = "[^"]+"', source)
        self.assertIsNotNone(assignment)
        lua.execute("BreedActions.skaven_doomrocket.fire_rocket = { name = 'shoot_ratling_gun' }")
        lua.execute(assignment.group())
        lua.execute("""
            blackboard.action = BreedActions.skaven_doomrocket.fire_rocket
            send_action_frame()
            assert(receive_action_frame() == 'fire_rocket')
        """)

    def test_bootstrap_registers_on_all_peers_before_runtime_update(self):
        source = (ROOT / "scripts/mods/doomrocket/doomrocket.lua").read_text(encoding="utf-8")
        load = 'mod:dofile("scripts/mods/doomrocket/utils/doomrocket_action_lookup")'
        self.assertEqual(source.count(load), 1)
        self.assertLess(source.index(load), source.index("function mod.update"))
        self.assertNotIn('NetworkLookup.bt_action_names["fire_rocket"] =', source)


@unittest.skipUnless(NATIVE_ROOT.is_dir(), "local native game-source checkout is unavailable")
class NativeActionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.lua = runtime()
        self.lua.execute("AISystem = {}; AISimpleExtension = {}; AiHuskBaseExtension = {}")
        for path, name in (
            ("scripts/entity_system/systems/ai/ai_system.lua", "AISystem.update_game_objects"),
            ("scripts/unit_extensions/human/ai_player_unit/ai_simple_extension.lua", "AISimpleExtension.current_action_name"),
            ("scripts/unit_extensions/human/ai_player_unit/ai_husk_base_extension.lua", "AiHuskBaseExtension.current_action_name"),
        ):
            self.lua.execute(native_function(path, name))
        self.lua.execute("""
            NetworkConstants = { invalid_game_object_id = 0 }
            BLACKBOARDS = { [unit] = blackboard }
            Managers.state.network.game = function() return 'game' end
            GameSession = {
                set_game_object_field = function(game, id, field, value)
                    assert(game == 'game' and id == 1)
                    network_fields[field] = value
                end,
                game_object_field = function(game, id, field)
                    assert(game == 'game' and id == 1)
                    return network_fields[field]
                end,
            }
            host_extension = setmetatable({ _blackboard = blackboard }, { __index = AISimpleExtension })
            host_system = setmetatable({ ai_units_alive = { [unit] = host_extension } }, { __index = AISystem })
            client_extension = setmetatable({ game = 'game', go_id = 1 }, { __index = AiHuskBaseExtension })
        """)

    def test_actual_native_encoder_and_husk_accessor_after_kick(self):
        self.lua.execute("""
            request_reposition()
            reposition:enter(unit, blackboard, 1.3)
            host_system:update_game_objects()
            assert(client_extension:current_action_name() == 'reposition')
            assert(network_fields.target_unit_id == 1)
        """)

    def test_actual_native_no_safe_route_and_missing_registration_mutant(self):
        self.lua.execute("""
            nav_policy = function() return false end
            request_reposition()
            reposition:enter(unit, blackboard, 1.3)
            assert(reposition:run(unit, blackboard, 1.3, 0) == 'done')
            reposition:leave(unit, blackboard, 1.3, 'done')
            host_system:update_game_objects()
            assert(client_extension:current_action_name() == 'reposition')
            NetworkLookup.bt_action_names.reposition = nil
        """)
        with self.assertRaisesRegex(LuaError, "bt_action_names does not contain key: reposition"):
            self.lua.execute("host_system:update_game_objects()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
