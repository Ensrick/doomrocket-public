#!/usr/bin/env python3
"""Execute production Lua 5.1 reload/shove/launch actions across interruptions.

The harness stubs engine I/O, not the action implementations. These tests prove
ammunition and callback transitions; game animation/physics and multiplayer
rendering still require the TEST Workshop playtest.
"""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
NODES = ROOT / "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket"
HARNESS = Path(__file__).with_name("fixtures") / "doomrocket_combat_harness.lua"


def create_runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS.read_text(encoding="utf-8"))
    for name in ("reload", "launch", "shove", "reposition"):
        lua.execute((NODES / f"bt_doomrocket_{name}_action.lua").read_text(encoding="utf-8"))
    # Load the production tuning table, not a duplicate test configuration.
    breed = (ROOT / "scripts/mods/doomrocket/breeds/skaven_doomrocket.lua").read_text(encoding="utf-8")
    config = re.search(r"BreedActions\.skaven_doomrocket\.reposition = \{.*?\n\}", breed, re.S)
    assert config, "production reposition tuning is missing"
    lua.execute("Breeds = { skaven_doomrocket = blackboard.breed }")
    lua.execute(config.group())
    lua.execute((NODES / "trees/skaven/skaven_doomrocket_behavior.lua").read_text(encoding="utf-8"))
    lua.execute("attach_actions()")
    return lua


class DoomrocketReloadLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.lua = create_runtime()

    def test_spawned_loaded_rocket_initializes_aim_without_reload_animation(self):
        self.lua.execute("""
            enter_reload()
            assert(run_reload(0, 0, false) == 'done')
            assert(blackboard.reloaded_rocket == true)
            assert(blackboard.first_shots_fired == nil)
            assert(blackboard.attack_pattern_data.ratling_gun_unit == weapon)
            assert(blackboard.attack_pattern_data.last_known_target_position:unbox() == target.position)
            assert(blackboard.attack_pattern_data.constraint_target == 1)
            assert(count_event('animations', 'wind_up_start') == 0)
            assert(#events.rpcs == 0)
        """)

    def test_completed_reload_survives_repeated_shoves_and_replaced_action_data(self):
        self.lua.execute("""
            blackboard.reloaded_rocket = false
            blackboard.first_shots_fired = true
            enter_reload()
            assert(run_reload(4.1, 4.1, true) == 'done')
            reload:leave(unit, blackboard, 4.1, 'done')
            assert(blackboard.reloaded_rocket and weapon.rocket_visible)
            assert(count_event('rpcs', 'rpc_reload_rocket') == 1)
            for cycle = 1, 3 do
                finish_shove(cycle * 10)
                -- Vanilla move-to-shoot replaces this table between sequences.
                blackboard.attack_pattern_data = {}
                enter_reload(cycle * 10 + 1.3)
                assert(run_reload(cycle * 10 + 1.3, 0, false) == 'done')
                reload:leave(unit, blackboard, cycle * 10 + 1.3, 'done')
                assert(blackboard.reloaded_rocket)
                assert(blackboard.attack_pattern_data.ratling_gun_unit == weapon)
            end
            assert(count_event('animations', 'wind_up_start') == 1)
            assert(count_event('rpcs', 'rpc_reload_rocket') == 1)
        """)

    def test_eligible_shove_can_interrupt_reload_before_or_after_former_mesh_reveal(self):
        for interruption in (0.5, 3.5):
            with self.subTest(interruption=interruption):
                self.setUp()
                self.lua.globals().interruption = interruption
                self.lua.execute("""
                    blackboard.reloaded_rocket = false
                    blackboard.first_shots_fired = true
                    weapon.rocket_visible = false
                    enter_reload()
                    assert(run_reload(interruption, interruption, true) == 'running')
                    become_close()
                    assert(BTConditions.doomrocket_should_shove(blackboard, nil, shove_action))
                    reload:leave(unit, blackboard, interruption, 'aborted')
                    finish_shove(interruption)
                    assert(blackboard.reloaded_rocket == false)
                    assert(weapon.rocket_visible == false)
                    assert(#events.rpcs == 0)
                    blackboard.attack_pattern_data = {}
                    enter_reload(interruption + 1.3)
                    assert(run_reload(interruption + 1.3, 0, true) == 'running')
                    assert(blackboard.attack_pattern_data.wind_up_timer == 4)
                    assert(run_reload(interruption + 5.4, 4.1, true) == 'done')
                    assert(blackboard.reloaded_rocket and weapon.rocket_visible)
                    assert(count_event('animations', 'wind_up_start') == 2)
                    assert(count_event('rpcs', 'rpc_reload_rocket') == 1)
                """)

    def test_interrupted_initial_aim_is_not_a_shot_and_keeps_loaded_round(self):
        self.lua.execute("""
            enter_reload()
            assert(run_reload(0, 0, false) == 'done')
            reload:leave(unit, blackboard, 0, 'done')
            launch:enter(unit, blackboard, 0)
            assert(blackboard.first_shots_fired == nil)
            assert(blackboard.attack_pattern_data.state == 'align')
            become_close()
            assert(BTConditions.doomrocket_should_shove(blackboard, nil, shove_action))
            launch:leave(unit, blackboard, 0.2, 'aborted')
            finish_shove(0.2)
            enter_reload(1.5)
            assert(run_reload(1.5, 0, false) == 'done')
            assert(blackboard.reloaded_rocket)
            assert(blackboard.first_shots_fired == nil)
            assert(count_event('animations', 'wind_up_start') == 0)
            assert(events.spawns == 0)
        """)

    def test_only_successful_projectile_spawn_consumes_round_and_requires_reload(self):
        self.lua.execute("""
            enter_reload()
            assert(run_reload(0, 0, false) == 'done')
            reload:leave(unit, blackboard, 0, 'done')
            launch:enter(unit, blackboard, 0)
            reject_spawn = true
            assert(not pcall(launch._shoot, launch, unit, blackboard, blackboard.attack_pattern_data))
            assert(blackboard.reloaded_rocket and blackboard.first_shots_fired == nil)
            assert(events.spawns == 0 and weapon.rocket_visible)
            reject_spawn = false
            launch:_shoot(unit, blackboard, blackboard.attack_pattern_data)
            assert(events.spawns == 1)
            assert(blackboard.first_shots_fired == true)
            assert(blackboard.reloaded_rocket == false and weapon.rocket_visible == false)
            assert(count_event('rpcs', 'rpc_launch_rocket') == 1)
            launch:leave(unit, blackboard, 0.5, 'done')
            blackboard.attack_pattern_data = {}
            enter_reload(1)
            assert(run_reload(1.1, 0.1, true) == 'running')
            assert(count_event('animations', 'wind_up_start') == 1)
        """)

    def test_reload_completion_requires_fresh_animation_callback_and_full_timer(self):
        self.lua.execute("""
            blackboard.reloaded_rocket = false
            blackboard.first_shots_fired = true
            blackboard.anim_cb_attack_windup_start_finished = true
            enter_reload()
            assert(blackboard.anim_cb_attack_windup_start_finished == nil)
            assert(run_reload(4.1, 4.1, false) == 'running')
            assert(blackboard.reloaded_rocket == false and #events.rpcs == 0)
            assert(run_reload(4.2, 0.1, true) == 'done')
            assert(blackboard.reloaded_rocket)
            assert(count_event('rpcs', 'rpc_reload_rocket') == 1)
            assert(run_reload(4.3, 0.1, true) == 'done')
            assert(count_event('rpcs', 'rpc_reload_rocket') == 1)
        """)

    def test_deleted_target_rejection_does_not_consume_loaded_round_or_stale_abort(self):
        self.lua.execute("""
            target.alive = false
            enter_reload()
            assert(run_reload(0, 0, false) == 'failed')
            reload:leave(unit, blackboard, 0, 'failed')
            assert(blackboard.reloaded_rocket)
            assert(blackboard.attack_pattern_data.target_unit == nil)
            target.alive = true
            enter_reload(1)
            assert(run_reload(1, 0, false) == 'done')
            assert(blackboard.attack_pattern_data.target_unit == target)
            assert(count_event('animations', 'wind_up_start') == 0)
        """)

    def test_loaded_close_cooldown_waits_without_reentering_ranged_sequence(self):
        self.lua.execute("""
            become_close()
            blackboard.reloaded_rocket = true
            blackboard.utility_actions.push_attack.time_since_last = 0
            for frame = 1, 600 do
                local name, class_name = selected_close_combat_child()
                assert(name == 'wait_at_close_range' and class_name == 'BTIdleAction')
            end
            assert(#events.animations == 0 and #events.rpcs == 0)
            assert(#events.logs == 0 and events.spawns == 0)
            assert(blackboard.reloaded_rocket)
            blackboard.utility_actions.push_attack.time_since_last = 7.5
            assert(selected_close_combat_child() == 'push_attack')
            blackboard.target_dist = 2.2
            assert(selected_close_combat_child() == 'attack_pattern')
        """)

    def test_close_wait_allows_empty_reload_and_preserves_shove_priority(self):
        self.lua.execute("""
            become_close()
            blackboard.utility_actions.push_attack.time_since_last = 0
            -- Initial weapon is loaded even before the reload node initializes it.
            assert(selected_close_combat_child() == 'wait_at_close_range')
            blackboard.reloaded_rocket = false
            assert(selected_close_combat_child() == 'attack_pattern')
            blackboard.utility_actions.push_attack.time_since_last = 7.5
            assert(selected_close_combat_child() == 'push_attack')
            target.alive = false
            assert(selected_close_combat_child() == 'attack_pattern')
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
