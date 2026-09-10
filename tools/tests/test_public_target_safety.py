#!/usr/bin/env python3
"""Exercise the public Lua actions at their engine boundary, not TEST gameplay.

The strict fake Unit API raises on nil/deleted positional access. Notification
counts enforce start/end pairing; projectile and reload checks pin the accepted
public tuning. Native animation, physics, and multiplayer still need playtests.
"""

from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
NODES = ROOT / "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket"

HARNESS = r"""
function require() end
function class(existing, parent) return { super = parent } end
BTNode = {}
script_data = {}
events = { starts = 0, ends = 0, accesses = 0, animations = {}, rpcs = {}, meshes = {} }
function printf() end
local function noop() end
local mt = {}
local function vector(x, y, z) return setmetatable({x=x or 0, y=y or 0, z=z or 0}, mt) end
mt.__add = function(a,b) return vector(a.x+b.x,a.y+b.y,a.z+b.z) end
mt.__sub = function(a,b) return vector(a.x-b.x,a.y-b.y,a.z-b.z) end
mt.__mul = function(a,b) return vector(a.x*b,a.y*b,a.z*b) end
Vector3 = setmetatable({}, { __call = function(_, ...) return vector(...) end })
Vector3.zero = function() return vector() end
Vector3.up = function() return vector(0,0,1) end
Vector3.forward = function() return vector(0,1,0) end
Vector3.right = function() return vector(1,0,0) end
Vector3.flat = function(v) return vector(v.x,v.y,0) end
Vector3.length = function(v) return math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z) end
Vector3.normalize = function(v) return v*(1/Vector3.length(v)) end
Vector3.flat_angle = function() return 0 end
function Vector3Box(v)
    return {value=v, store=function(self,x) self.value=x end, unbox=function(self) return self.value end}
end
Quaternion = setmetatable({forward=Vector3.forward, look=function() return {} end,
    multiply=function() return {} end}, {__call=function() return {} end})
math.clamp = function(x,lo,hi) return math.min(hi,math.max(lo,x)) end
Math = {random=function() return 0.5 end}
unit = {alive=true, position=vector()}
target = {alive=true, position=vector(0,10,0), status={}}
weapon = {alive=true, position=vector(), rocket_visible=true}
POSITION_LOOKUP = {[unit]=unit.position,[target]=target.position}
local function checked(u)
    assert(u and u.alive, 'nil/deleted Unit access')
    events.accesses = events.accesses + 1
    return u
end
Unit = {
    alive=function(u) return u and u.alive == true end,
    node=function(u,name) checked(u); assert(name); return name end,
    world_position=function(u) return checked(u).position end,
    local_position=function(u) return checked(u).position end,
    world_rotation=function(u) checked(u); return {} end,
    local_rotation=function(u) checked(u); return {} end,
    animation_find_constraint_target=function(u) checked(u); return 1 end,
    set_mesh_visibility=function(u,mesh,visible)
        checked(u).rocket_visible=visible
        table.insert(events.meshes,visible)
    end,
}
ScriptUnit = {extension=function(u,name)
    checked(u)
    if name == 'status_system' then return u.status end
    assert(name == 'ai_inventory_system')
    return {get_unit=function() return weapon end}
end}
local nav = {enabled=true, set_enabled=function(self,v) self.enabled=v end, set_max_speed=noop}
local locomotion = {set_wanted_velocity=noop, use_lerp_rotation=noop}
AiUtils = {
    random=function(lo,hi) return (lo+hi)/2 end,
    anim_event=function(_,_,name) table.insert(events.animations,name) end,
    clear_temp_anim_event=noop, clear_anim_event=noop,
    get_default_breed_move_speed=function() return 1 end,
}
LocomotionUtils = {look_at_position_flat=function() return {} end}
PerceptionUtils = {pick_ratling_gun_target=function(_,bb)
    return bb.perceived_target, bb.perceived_node, bb.old_target_visible
end}
bot_group = {
    ranged_attack_started=function(self,attacker,victim,kind)
        assert(victim and victim.alive, 'start requires live target')
        assert(not self.victim, 'duplicate notification')
        assert(kind == 'ratling_gun_fire')
        self.victim=victim
        events.starts=events.starts+1
    end,
    ranged_attack_ended=function(self,attacker,victim,kind)
        assert(self.victim == victim and victim, 'unpaired end notification')
        assert(kind == 'ratling_gun_fire')
        self.victim=nil
        events.ends=events.ends+1
        events.ended_target=victim
    end,
}
Managers = {state={
    entity={system=function(_,name)
        if name == 'ai_bot_group_system' then return bot_group end
        return {}
    end},
    debug={drawer=function() return {reset=noop} end},
    network={anim_event=noop},
    unit_storage={go_id=function() return 17 end},
    difficulty={get_difficulty_rank=function() return 1 end},
    unit_spawner={spawn_network_unit=function(_,name,template,data,position,rotation)
        events.spawn={name=name,template=template,data=data,position=position}
        return {},42
    end},
}}
Network = {peer_id=function() return 'host' end}
AiAnimUtils = {
    position_network_scale=function(v) return v end,
    rotation_network_scale=function(v) return v end,
    velocity_network_scale=function(v) return v end,
}
LightWeightProjectiles = {test={spread=0,attack_power_level={1},impact_push_speed=0}}
ProjectileRocket = {new=function(self,...)
    events.projectile_args={...}
    return {}
end}
mod = {projectiles={}, network_send=function(self,...)
    table.insert(events.rpcs,{...})
end}
function get_mod() return mod end
blackboard = {
    perceived_target=target, perceived_node='head',
    navigation_extension=nav, locomotion_extension=locomotion,
    breed={default_inventory_template='gun',walk_speed=1},
}
launch_action = {fire_rate_at_start=1,fire_rate_at_end=1,max_fire_rate_at_percentage=1,
    target_switch_distance={1,1},attack_time={1,1},light_weight_projectile_template_name='test'}
function attach()
    launch=setmetatable({_tree_node={action_data=launch_action}}, {__index=BTDoomrocketLaunchAction})
    reload=setmetatable({_tree_node={action_data={}}}, {__index=BTDoomrocketReloadAction})
end
"""


def create_runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    for action in ("launch", "reload"):
        lua.execute((NODES / f"bt_doomrocket_{action}_action.lua").read_text(encoding="utf-8"))
    lua.execute("attach()")
    return lua


class PublicTargetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.lua = create_runtime()

    def assert_rejected_launch(self, setup):
        self.lua.execute(setup + """
            launch:enter(unit,blackboard,0)
            assert(blackboard.attack_pattern_data.invalid_target)
            assert(blackboard.attack_pattern_data.target_unit == nil)
            assert(launch:run(unit,blackboard,0,0) == 'failed')
            launch:leave(unit,blackboard,0,'failed',false)
            assert(events.accesses == 0)
            assert(events.starts == 0 and events.ends == 0)
            assert(blackboard.navigation_extension.enabled)
            assert(not blackboard.first_shots_fired)
        """)

    def test_nil_launch_target_full_lifecycle(self):
        self.assert_rejected_launch("blackboard.perceived_target=nil\n")

    def test_deleted_new_launch_target_full_lifecycle(self):
        self.assert_rejected_launch("target.alive=false\n")

    def test_deleted_saved_launch_target_full_lifecycle(self):
        self.assert_rejected_launch("""
            target.alive=false
            blackboard.perceived_target=nil
            blackboard.attack_pattern_data={target_unit=target}
        """)

    def test_run_without_entry_data_fails_safely(self):
        self.lua.execute("assert(launch:run(unit,blackboard,0,0) == 'failed')")

    def test_destroyed_victim_still_receives_matching_end(self):
        self.lua.execute("""
            reload:enter(unit,blackboard,0)
            reload:leave(unit,blackboard,0,'done',false)
            launch:enter(unit,blackboard,0)
            assert(events.starts == 1 and events.ends == 0)
            assert(target.status.under_ratling_gunner_attack)
            target.alive=false
            local previous_accesses=events.accesses
            assert(launch:run(unit,blackboard,0,0) == 'done')
            launch:leave(unit,blackboard,0,'done',false)
            assert(events.starts == 1 and events.ends == 1)
            assert(events.ended_target == target)
            assert(events.accesses == previous_accesses)
            assert(bot_group.victim == nil)
            launch:leave(unit,blackboard,0,'done',false)
            assert(events.ends == 1)
        """)

    def test_live_victim_notification_cleanup_is_unchanged(self):
        self.lua.execute("""
            reload:enter(unit,blackboard,0)
            reload:leave(unit,blackboard,0,'done',false)
            launch:enter(unit,blackboard,0)
            launch:leave(unit,blackboard,0,'aborted',false)
            assert(events.starts == 1 and events.ends == 1)
            assert(target.status.under_ratling_gunner_attack == false)
        """)

    def test_reload_nil_and_deleted_new_target_full_lifecycle(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                self.setUp()
                self.lua.execute("target.alive=false" if deleted else "blackboard.perceived_target=nil")
                if deleted:
                    self.lua.execute("blackboard.attack_pattern_data={target_unit=target}")
                self.lua.execute("""
                    reload:enter(unit,blackboard,0)
                    assert(blackboard.attack_pattern_data.target_unit == nil)
                    assert(reload:run(unit,blackboard,0,0) == 'failed')
                    reload:leave(unit,blackboard,0,'failed',false)
                    assert(events.accesses == 0)
                    assert(#events.rpcs == 0)
                """)

    def test_reload_update_rejects_deleted_new_and_saved_target(self):
        for saved in (False, True):
            with self.subTest(saved=saved):
                self.setUp()
                self.lua.execute("""
                    reload:enter(unit,blackboard,0)
                    target.alive=false
                    blackboard.old_target_visible=true
                """)
                if saved:
                    self.lua.execute("blackboard.perceived_target=nil")
                self.lua.execute("""
                    local previous_accesses=events.accesses
                    reload:_update_target(unit,blackboard,blackboard.attack_pattern_data,1)
                    assert(blackboard.attack_pattern_data.target_unit == nil)
                    assert(blackboard.attack_pattern_data.target_obscured)
                    assert(events.accesses == previous_accesses)
                """)

    def test_live_obscured_target_survives_reload_update_and_launch_fallback(self):
        self.lua.execute("""
            reload:enter(unit,blackboard,0)
            blackboard.perceived_target=nil
            blackboard.old_target_visible=false
            local data=blackboard.attack_pattern_data
            reload:_update_target(unit,blackboard,data,1)
            assert(data.target_unit == target and data.target_obscured)
            reload:leave(unit,blackboard,1,'done',false)
            launch:enter(unit,blackboard,1)
            assert(data.target_unit == target and not data.invalid_target)
            assert(events.starts == 1)
            launch:leave(unit,blackboard,1,'aborted',false)
            assert(events.ends == 1)
        """)

    def test_reload_entry_rejection_retains_live_saved_target(self):
        self.lua.execute("""
            blackboard.perceived_target=nil
            blackboard.attack_pattern_data={target_unit=target,target_node_name='head'}
            reload:enter(unit,blackboard,0)
            assert(blackboard.attack_pattern_data.target_unit == target)
            assert(reload:run(unit,blackboard,0,0) == 'failed')
            reload:leave(unit,blackboard,0,'failed',false)
            assert(events.accesses == 0)
            launch:enter(unit,blackboard,0)
            assert(events.starts == 1)
            launch:leave(unit,blackboard,0,'aborted',false)
            assert(events.ends == 1)
        """)

    def test_target_switch_pairs_old_end_before_new_start_and_leave(self):
        self.lua.execute("""
            reload:enter(unit,blackboard,0)
            reload:leave(unit,blackboard,0,'done',false)
            launch:enter(unit,blackboard,0)
            local second={alive=true,position=Vector3(1,10,0),status={}}
            POSITION_LOOKUP[second]=second.position
            blackboard.perceived_target=second
            blackboard.taunt_unit=second
            local data=blackboard.attack_pattern_data
            assert(launch:_update_target(unit,blackboard,launch_action,data,1,0.1))
            assert(events.starts == 2 and events.ends == 1)
            assert(events.ended_target == target and bot_group.victim == second)
            assert(target.status.under_ratling_gunner_attack == false)
            assert(second.status.under_ratling_gunner_attack)
            launch:leave(unit,blackboard,1,'aborted',false)
            assert(events.starts == 2 and events.ends == 2)
            assert(events.ended_target == second and bot_group.victim == nil)
            assert(second.status.under_ratling_gunner_attack == false)
        """)

    def test_rejected_entry_can_recover_on_next_live_target(self):
        self.lua.execute("""
            blackboard.perceived_target=nil
            launch:enter(unit,blackboard,0)
            launch:leave(unit,blackboard,0,'failed',false)
            blackboard.perceived_target=target
            reload:enter(unit,blackboard,1)
            reload:leave(unit,blackboard,1,'done',false)
            launch:enter(unit,blackboard,1)
            assert(not blackboard.attack_pattern_data.invalid_target)
            assert(events.starts == 1)
            launch:leave(unit,blackboard,1,'aborted',false)
            assert(events.ends == 1)
        """)

    def test_public_reload_timing_and_early_mesh_reveal_remain_unchanged(self):
        self.lua.execute("""
            blackboard.first_shots_fired=true
            blackboard.reloaded_rocket=false
            reload:enter(unit,blackboard,0)
            assert(blackboard.attack_pattern_data.wind_up_timer == 4)
            assert(events.animations[1] == 'wind_up_start')
            blackboard.anim_cb_attack_windup_start_finished=true
            assert(reload:run(unit,blackboard,3,3) == 'running')
            assert(not blackboard.reloaded_rocket and #events.rpcs == 0)
            assert(reload:run(unit,blackboard,3.1,0.1) == 'running')
            assert(blackboard.reloaded_rocket and weapon.rocket_visible)
            assert(events.rpcs[1][1] == 'rpc_reload_rocket')
            assert(reload:run(unit,blackboard,4.1,1) == 'done')
            assert(#events.rpcs == 1)
        """)

    def test_public_initial_reload_still_finishes_without_timer_wait(self):
        self.lua.execute("""
            reload:enter(unit,blackboard,0)
            assert(reload:run(unit,blackboard,0,0) == 'done')
            assert(events.animations[1] == 'wind_up_start')
            assert(#events.rpcs == 0)
        """)

    def test_public_trajectory_and_projectile_rpc_are_unchanged(self):
        for distance, flight_time in ((1, 1.7), (20, 2.6), (40, 3.4)):
            with self.subTest(distance=distance):
                self.setUp()
                self.lua.globals().shot_distance = distance
                self.lua.globals().expected_time = flight_time
                self.lua.execute("""
                    target.position=Vector3(0,shot_distance,3)
                    blackboard.action=launch_action
                    blackboard.attack_pattern_data={target_unit=target,ratling_gun_unit=weapon}
                    launch._fire_from_position_direction=function() return unit.position,Vector3.forward() end
                    launch:_shoot(unit,blackboard,blackboard.attack_pattern_data)
                    local v=events.spawn.data.projectile_locomotion_system.network_velocity
                    assert(v.x == 0)
                    assert(math.abs(v.y-shot_distance/expected_time) < 0.000001)
                    assert(math.abs(v.z-(3.25/expected_time+0.5*9.82*expected_time)) < 0.000001)
                    assert(events.spawn.name == 'units/rocket/SM_Rocket')
                    assert(events.spawn.template == 'explosive_pickup_projectile_unit')
                    assert(#events.projectile_args == 3)
                    assert(#events.rpcs == 1 and #events.rpcs[1] == 6)
                    assert(events.rpcs[1][1] == 'rpc_launch_rocket')
                    assert(events.rpcs[1][2] == 'others' and events.rpcs[1][3] == 42)
                    assert(events.rpcs[1][4] == v and events.rpcs[1][6] == 17)
                    assert(not blackboard.reloaded_rocket and not weapon.rocket_visible)
                """)


if __name__ == "__main__":
    unittest.main()
