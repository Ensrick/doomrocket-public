#!/usr/bin/env python3
"""Execute #16/#33's pre-fire alignment floor and callback/interruption ordering.

Production launch/reload code and breed tuning run in Lua 5.1. Angular error
and native animation callbacks are prescribed engine inputs. These tests prove
the timing contract, not game animation/sound appearance or networking.
"""

import re
import unittest

from test_doomrocket_reload_lifecycle import ROOT, create_runtime


def timing_runtime():
    lua = create_runtime()
    source = (ROOT / "scripts/mods/doomrocket/breeds/skaven_doomrocket.lua").read_text(encoding="utf-8")
    assignment = re.search(r"BreedActions\.skaven_doomrocket\.fire_rocket\.minimum_aim_time = [0-9.]+", source)
    assert assignment, "production minimum aim time is missing"
    lua.execute("BreedActions.skaven_doomrocket.fire_rocket = launch_action")
    lua.execute(assignment.group())
    lua.execute("""
        CLIENT_CONTROLLED_RATLING_GUN = false
        math.round = function(v) return math.floor(v + 0.5) end
        Vector3.lerp = function(a, b, fraction) return a + (b - a) * fraction end
        function QuaternionBox(value)
            return { value = value, unbox = function(self) return self.value end }
        end
        launch._update_target = function() return false end
        launch._aim_at_target = function() return false end
        -- Actual alignment timer/transition code executes; geometry is an input.
        launch._remaining_angle = function() return prescribed_angle or 0 end
        launch._angle_to_speed = function() return 0 end
        function begin_aim(t)
            enter_reload(t)
            assert(run_reload(t, 0, false) == 'done')
            reload:leave(unit, blackboard, t, 'done')
            launch:enter(unit, blackboard, t)
            assert(blackboard.attack_pattern_data.state == 'align')
        end
        function tick_aim(t)
            return launch:run(unit, blackboard, t, 0)
        end
        function callback_at(t)
            blackboard.anim_cb_attack_shoot_random_shot = true
            return tick_aim(t)
        end
    """)
    return lua


def production_minimum():
    return timing_runtime().eval("launch_action.minimum_aim_time")


class DoomrocketAimTimingTests(unittest.TestCase):
    """Times are offsets from the production floor, so a retune keeps the proof."""

    @classmethod
    def setUpClass(cls):
        cls.minimum = production_minimum()

    def run_lua(self, script):
        lua = timing_runtime()
        lua.globals().MIN = self.minimum
        lua.execute(script)
        return lua

    def test_production_minimum_is_two_seconds(self):
        # #33 doubled the #16 one-second floor.
        self.assertEqual(self.minimum, 2.0)

    def test_firing_animation_waits_the_minimum_even_when_already_aligned(self):
        self.run_lua("""
            begin_aim(10)
            tick_aim(10)
            tick_aim(10 + MIN - 0.001)
            local data = blackboard.attack_pattern_data
            assert(data.state == 'align' and not data.is_shooting)
            assert(count_event('animations', 'attack_shoot_start') == 0)
            tick_aim(10 + MIN)
            assert(data.state == 'ready')
            assert(count_event('animations', 'attack_shoot_start') == 1)
            assert(events.spawns == 0 and blackboard.reloaded_rocket)
        """)

    def test_native_fire_callback_releases_normally_without_extra_post_cue_hold(self):
        self.run_lua("""
            begin_aim(0)
            tick_aim(MIN)
            callback_at(MIN + 0.25)
            assert(blackboard.attack_pattern_data.state == 'shoot')
            assert(blackboard.attack_pattern_data.shoot_start == MIN + 0.25)
        """)

    def test_reload_time_does_not_count_toward_aim_minimum(self):
        self.run_lua("""
            blackboard.reloaded_rocket = false
            enter_reload(0)
            assert(blackboard.attack_pattern_data.wind_up_time == 4)
            assert(run_reload(4.1, 4.1, true) == 'done')
            reload:leave(unit, blackboard, 4.1, 'done')
            launch:enter(unit, blackboard, 4.1)
            tick_aim(4.1 + MIN - 0.01)
            assert(blackboard.attack_pattern_data.state == 'align')
            tick_aim(4.1 + MIN + 0.001)
            assert(blackboard.attack_pattern_data.state == 'ready')
            assert(count_event('rpcs', 'rpc_reload_rocket') == 1)
        """)

    def test_large_turn_still_has_to_finish_after_minimum(self):
        self.run_lua("""
            begin_aim(0)
            prescribed_angle = math.pi / 2
            tick_aim(MIN + 1)
            assert(blackboard.attack_pattern_data.state == 'align')
            assert(count_event('animations', 'attack_shoot_start') == 0)
            prescribed_angle = 0
            tick_aim(MIN + 1.1)
            assert(blackboard.attack_pattern_data.state == 'ready')
        """)

    def test_missing_callback_never_fires_from_timer_alone(self):
        self.run_lua("""
            begin_aim(0)
            tick_aim(MIN)
            tick_aim(20)
            assert(blackboard.attack_pattern_data.state == 'ready')
            assert(not blackboard.attack_pattern_data.is_shooting and events.spawns == 0)
        """)

    def test_callback_from_alignment_is_discarded_before_new_firing_event(self):
        self.run_lua("""
            begin_aim(0)
            callback_at(0.5)
            assert(blackboard.attack_pattern_data.state == 'align')
            tick_aim(MIN)
            tick_aim(MIN + 0.1)
            assert(blackboard.attack_pattern_data.state == 'ready')
            assert(not blackboard.anim_cb_attack_shoot_random_shot)
            callback_at(MIN + 0.25)
            assert(blackboard.attack_pattern_data.shoot_start == MIN + 0.25)
        """)

    def test_alignment_floor_is_frame_rate_independent(self):
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                lua = timing_runtime()
                lua.execute("begin_aim(0)")
                for frame in range(round(fps * self.minimum)):
                    lua.globals().tick_aim(frame / fps)
                    self.assertEqual(lua.eval("blackboard.attack_pattern_data.state"), "align")
                lua.globals().tick_aim(self.minimum)
                self.assertEqual(lua.eval("blackboard.attack_pattern_data.state"), "ready")

    def test_target_switch_restarts_the_full_window_and_clears_old_callback(self):
        self.run_lua("""
            begin_aim(0)
            launch._update_target = function() return true end
            callback_at(0.75)
            local data = blackboard.attack_pattern_data
            assert(data.state == 'align' and data.align_start == 0.75)
            assert(not blackboard.anim_cb_attack_shoot_random_shot)
            launch._update_target = function() return false end
            tick_aim(0.75 + MIN - 0.01)
            assert(data.state == 'align')
            tick_aim(0.75 + MIN)
            assert(data.state == 'ready')
            assert(not data.is_shooting)
        """)

    def test_close_target_cannot_reach_fire_cue_at_deadline(self):
        self.run_lua("""
            begin_aim(0)
            become_close()
            assert(tick_aim(1) == 'done')
            assert(count_event('animations', 'attack_shoot_start') == 0)
            assert(not blackboard.attack_pattern_data.is_shooting and events.spawns == 0)
            launch:leave(unit, blackboard, 1, 'done')
            assert(not blackboard.attack_pattern_data.align_start)
            assert(blackboard.reloaded_rocket)
        """)

    def test_deleted_target_cannot_reach_fire_cue_at_deadline(self):
        self.run_lua("""
            begin_aim(0)
            target.alive = false
            assert(tick_aim(1) == 'done')
            assert(count_event('animations', 'attack_shoot_start') == 0)
            launch:leave(unit, blackboard, 1, 'done')
            assert(not blackboard.attack_pattern_data.align_start)
        """)

    def test_shove_interrupt_preserves_round_but_restarts_aim_minimum(self):
        self.run_lua("""
            begin_aim(0)
            tick_aim(0.5)
            launch:leave(unit, blackboard, 0.75, 'aborted')
            assert(not blackboard.attack_pattern_data.align_start)
            finish_shove(0.75)
            assert(blackboard.reloaded_rocket and weapon.rocket_visible)
            begin_aim(2)
            tick_aim(2 + MIN - 0.1)
            assert(blackboard.attack_pattern_data.state == 'align')
            tick_aim(2 + MIN)
            assert(blackboard.attack_pattern_data.state == 'ready')
            assert(count_event('rpcs', 'rpc_reload_rocket') == 0)
        """)

    def test_zero_minimum_preserves_original_angular_transition(self):
        self.run_lua("""
            launch_action.minimum_aim_time = 0
            begin_aim(0)
            tick_aim(0)
            assert(blackboard.attack_pattern_data.state == 'ready')
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
