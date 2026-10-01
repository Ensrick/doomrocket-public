#!/usr/bin/env python3
"""Execute the World hook/queue path with VMF's one-hook-per-mod rule.

The v0.1.75 regression registered normal hooks for gait and then safe hooks for
ragdoll/hose on the same methods. VMF rejected the latter registrations, so the
visible death skeleton entered ignore mode without receiving a single pose.
This harness runs the production scheduler, with only the pose math and native
engine calls doubled; retarget math has its own suite.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"

HARNESS = r"""
events={}; warnings={}; errors={}; callbacks={}; registrations={}
world={name='game'}; other_world={name='preview'}
mod={_warlock_active_death_drivers={}}
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) assert(u.alive,'access after unit deletion'); return u.world end,
}
local function event(name) events[#events+1]=name end
local function engine(w,dt,...)
 event('animation:'..w.name)
 assert(w.gait_dt==dt,'gait must precede native animation')
 w.engine_args={n=select('#',...),...}
 if w.engine_error then error('engine failed') end
 for driver in pairs(mod._warlock_active_death_drivers) do
  if driver.owner.world==w then driver.owner.pose=driver.owner.pose+1 end
 end
 w.animated=true
 if w.no_returns then return end
 return nil, 'native-result', nil, 47, nil
end
World={update_animations=engine,update_animations_with_callback=engine}
local function register(self,kind,obj,method,handler)
 -- VMF modules/core/hooks.lua create_hook keys _registry[mod][unique_id].
 -- A later registration, even of another hook type, is rejected.
 if registrations[method] then warnings[#warnings+1]=method; return end
 registrations[method]=kind
 local original=obj[method]
 if kind=='normal' then
  obj[method]=function(...) return handler(original,...) end
 else
  obj[method]=function(...) original(...); self:pcall(handler,...) end
 end
end
function mod:hook(obj,method,handler) register(self,'normal',obj,method,handler) end
function mod:hook_safe(obj,method,handler) register(self,'safe',obj,method,handler) end
function mod:pcall(fn,...)
 local ok,err=pcall(fn,...)
 if not ok then errors[#errors+1]=err end
 return ok
end
function mod._update_warlock_locomotion_animation(w,dt)
 event('gait:'..w.name); w.gait_dt=dt
end
function mod._queue_warlock_hose(w,dt)
 assert(w.animated,'hose queued before native animation')
 event('hose_queue:'..w.name)
 if w.hose_error then error('hose failed') end
 callbacks[#callbacks+1]=function() event('hose_pose:'..w.name) end
end
-- The independent grip probe's queue and lifetime are covered by its own suite.
function mod._queue_warlock_weapon_pose_probe(w,dt) end
animation_system={add_safe_animation_callback=function(self,cb)
 event('ragdoll_queue'); callbacks[#callbacks+1]=cb
end}
Managers={state={entity={system=function(self,name)
 assert(name=='animation_system'); return animation_system
end}}}
local function stop_warlock_death_driver(driver,reason)
 driver.stopped=true; driver.stop_reason=reason
 mod._warlock_active_death_drivers[driver]=nil
end
local function warlock_carrier_ragdoll_sleeping(driver)
 driver.sleep_queries=(driver.sleep_queries or 0)+1
 return driver.sleeping
end
local function apply_warlock_death_pose(driver)
 assert(driver.owner.world.animated,'pose applied before animation')
 assert(driver.owner.alive and driver.outfit.alive)
 driver.outfit.pose=driver.owner.pose
 driver.writes=driver.writes+1
 event('ragdoll_pose:'..driver.source)
end
local queue_warlock_death_pose
function make_driver(w,source)
 local driver={owner={alive=true,world=w,pose=0},
  outfit={alive=true,world=w,pose=0}, source=source,writes=0}
 mod._warlock_active_death_drivers[driver]=true
 return driver
end
function drain_and_update_scene(w)
 local pending=callbacks; callbacks={}
 for _,cb in ipairs(pending) do cb() end
 event('scene:'..w.name)
end
function pack(...) return {n=select('#',...),...} end
"""


def runtime():
    source = HOOKS.read_text(encoding="utf-8")
    start = source.index("queue_warlock_death_pose = function(driver)")
    stop = source.index("mod._reset_warlock_death_drivers = function()", start)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS + "\n" + source[start:stop])
    return lua


class AnimationCallbackTests(unittest.TestCase):
    def test_each_world_method_has_one_accepted_registration(self):
        lua = runtime()
        lua.execute("""
            assert(#warnings==0,'VMF rejected a duplicate animation hook')
            assert(registrations.update_animations=='normal')
            assert(registrations.update_animations_with_callback=='normal')
        """)

    def test_both_methods_schedule_host_and_husk_pose_and_hose_after_animation(self):
        for method in ("update_animations", "update_animations_with_callback"):
            for source in ("unit", "husk"):
                with self.subTest(method=method, source=source):
                    lua = runtime()
                    lua.globals().method = method
                    lua.globals().source = source
                    lua.execute("""
                        driver=make_driver(world,source)
                        World[method](world,0.016,'native-callback',nil,23)
                        assert(driver.callback_pending and driver.writes==0)
                        assert(#callbacks==2,'ragdoll and hose both need callbacks')
                        assert(table.concat(events,',')==
                            'gait:game,animation:game,ragdoll_queue,hose_queue:game')
                        assert(world.engine_args.n==3 and world.engine_args[1]=='native-callback'
                            and world.engine_args[2]==nil and world.engine_args[3]==23)
                        drain_and_update_scene(world)
                        assert(driver.writes==1 and driver.outfit.pose==1)
                        assert(not driver.callback_pending)
                        assert(table.concat(events,',')==
                            'gait:game,animation:game,ragdoll_queue,hose_queue:game,'..
                            'ragdoll_pose:'..source..',hose_pose:game,scene:game')
                    """)

    def test_native_return_count_and_nil_slots_are_preserved(self):
        lua = runtime()
        lua.execute("""
            for _,name in ipairs({'update_animations','update_animations_with_callback'}) do
                local values=pack(World[name](world,0.02))
                assert(values.n==5 and values[1]==nil and values[2]=='native-result'
                    and values[3]==nil and values[4]==47 and values[5]==nil)
                world.no_returns=true
                assert(pack(World[name](world,0.02)).n==0)
                world.no_returns=false
            end
        """)

    def test_other_world_does_not_enqueue_corpse_and_pending_callback_is_unique(self):
        lua = runtime()
        lua.execute("""
            driver=make_driver(world,'unit')
            World.update_animations(other_world,0.01)
            drain_and_update_scene(other_world)
            assert(driver.writes==0 and not driver.callback_pending)
            World.update_animations(world,0.02)
            World.update_animations_with_callback(world,0.02)
            assert(#callbacks==3,'one corpse callback plus two hose queue calls')
            drain_and_update_scene(world)
            assert(driver.writes==1 and driver.outfit.pose==2)
        """)

    def test_monitor_sleep_wake_and_deleted_units_keep_existing_lifetime_rules(self):
        lua = runtime()
        lua.execute("""
            driver=make_driver(world,'husk'); driver.sleeping=true
            World.update_animations(world,0.02); drain_and_update_scene(world)
            assert(driver.writes==1 and not driver.sleep_queries,
                'pre-monitor sleeping actors must not freeze the pose')
            driver.monitor_complete=true
            World.update_animations(world,0.02); drain_and_update_scene(world)
            assert(driver.writes==1 and driver.sleep_queries==1)
            driver.sleeping=false
            World.update_animations(world,0.02); drain_and_update_scene(world)
            assert(driver.writes==2 and driver.outfit.pose==3)
            driver.outfit.alive=false
            World.update_animations(world,0.02); drain_and_update_scene(world)
            assert(driver.stopped and driver.stop_reason=='unit_not_alive')
            assert(mod._warlock_active_death_drivers[driver]==nil and driver.writes==2)
        """)

    def test_stopped_pending_callback_does_not_write_pose(self):
        lua = runtime()
        lua.execute("""
            driver=make_driver(world,'unit')
            World.update_animations(world,0.02)
            driver.stopped=true
            drain_and_update_scene(world)
            assert(driver.writes==0 and not driver.callback_pending)
        """)

    def test_post_hook_errors_are_contained_without_losing_native_results(self):
        lua = runtime()
        lua.execute("""
            driver=make_driver(world,'unit'); world.hose_error=true
            local values=pack(World.update_animations(world,0.02))
            assert(values.n==5 and values[4]==47 and #errors==1)
            drain_and_update_scene(world)
            assert(driver.writes==1,'hose error must not suppress corpse callback')
        """)

    def test_engine_failure_does_not_queue_unsafe_pose_work(self):
        lua = runtime()
        lua.execute("""
            driver=make_driver(world,'unit'); world.engine_error=true
            assert(not pcall(World.update_animations,world,0.02))
            assert(#callbacks==0 and not driver.callback_pending)
        """)


if __name__ == "__main__":
    unittest.main()
