"""Execute traversal presentation with checked world/local reconstruction.

The existing strict scene double expires math temporaries between frames and
implements Stingray's reversed products and the real 100x custom ancestor.
These tests establish engineering invariants, not rendered game acceptance.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime
import test_doomrocket_grip_alignment as grip

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_traversal_pose.lua"
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"

HARNESS = grip.HARNESS.replace("u==outfit and node>2", "u==outfit and node>=2") + r'''
messages={}
function printf(...) messages[#messages+1]=string.format(...) end
mod._doomrocket_version='test'
local original_data=Unit.get_data
Unit.get_data=function(u,key)
 if key=='warlock_rig_profile' then return u.profile end
 return original_data(u,key)
end
Quaternion={}
function Quaternion.to_elements(m)
 local tr=m[1][1]+m[2][2]+m[3][3]
 if tr>0 then
  local s=math.sqrt(tr+1)*2
  return (m[3][2]-m[2][3])/s,(m[1][3]-m[3][1])/s,(m[2][1]-m[1][2])/s,.25*s
 elseif m[1][1]>m[2][2] and m[1][1]>m[3][3] then
  local s=math.sqrt(1+m[1][1]-m[2][2]-m[3][3])*2
  return .25*s,(m[1][2]+m[2][1])/s,(m[1][3]+m[3][1])/s,(m[3][2]-m[2][3])/s
 elseif m[2][2]>m[3][3] then
  local s=math.sqrt(1+m[2][2]-m[1][1]-m[3][3])*2
  return (m[1][2]+m[2][1])/s,.25*s,(m[2][3]+m[3][2])/s,(m[1][3]-m[3][1])/s
 else
  local s=math.sqrt(1+m[3][3]-m[1][1]-m[2][2])*2
  return (m[1][3]+m[3][1])/s,(m[2][3]+m[3][2])/s,.25*s,(m[2][1]-m[1][2])/s
 end
end
function Quaternion.from_elements(x,y,z,w)
 local p=Matrix4x4.identity()
 p[1][1]=1-2*(y*y+z*z);p[1][2]=2*(x*y-z*w);p[1][3]=2*(x*z+y*w)
 p[2][1]=2*(x*y+z*w);p[2][2]=1-2*(x*x+z*z);p[2][3]=2*(y*z-x*w)
 p[3][1]=2*(x*z-y*w);p[3][2]=2*(y*z+x*w);p[3][3]=1-2*(x*x+y*y)
 return p
end
local additions={'j_head','j_leftupleg','j_leftleg','j_leftfoot','j_rightupleg','j_rightleg','j_rightfoot',
 'j_leftweaponattach','j_spine_scale'}
for i,name in ipairs(additions) do
 local node=20+i;outfit.nodes[name]=node
 outfit.parents[node]=name=='j_head' and 3 or 2
 outfit.locals[node]=keep(Matrix4x4.identity(1,i*.0001,0,i*.0003))
 owner.nodes[name]=node+50;owner.parents[node+50]=0
end
owner.nodes.j_hips=102;owner.parents[102]=0
World.update_unit(world,outfit)
for name,node in pairs(outfit.nodes) do
 local p=Unit.world_pose(outfit,node);local q=rotation(p)
 Matrix4x4.set_translation(q,Matrix4x4.translation(p));owner.locals[owner.nodes[name]]=keep(q)
end
World.update_unit(world,owner)
AttachmentNodeLinking={doomrocket_warlock_bridge={{target=0,source='root_point'}}}
for name in pairs(outfit.nodes) do
 table.insert(AttachmentNodeLinking.doomrocket_warlock_bridge,{target=name,source=name})
end
channels={upper_body='legacy',weapon='legacy'}
function mod._warlock_animation_ownership() return channels end
function mod._apply_warlock_outfit_correction(o,u,death)
 assert(o==owner and u==outfit and not death)
 calls.correction=(calls.correction or 0)+1
 calls.corrected_hip=Unit.world_position(outfit,outfit.nodes.j_hips).z
end
BLACKBOARDS={}
base={}
function save_base()
 base={};for node,p in pairs(outfit.locals) do if node>1 then base[node]=keep(p) end end
end
save_base()
function evaluate()
 for node,p in pairs(base) do outfit.locals[node]=keep(p) end
end
function tick(dt)
 evaluate()
 mod._queue_warlock_traversal_pose(world,dt or .12);drain()
 assert(not mod.last_error,mod.last_error)
end
function event(name,mirrored) mod._note_warlock_traversal_event(owner,name,mirrored or false) end
function assert_native()
 World.update_unit(world,owner);World.update_unit(world,outfit)
 for name,node in pairs(outfit.nodes) do if not name:match('_scale$') then
  local a=Unit.world_pose(owner,owner.nodes[name]);local b=Unit.world_pose(outfit,node)
  assert(Vector3.distance(Matrix4x4.translation(a),Matrix4x4.translation(b))<1e-8,'position '..name)
  local ar,br=rotation(a),rotation(b)
  for r=1,3 do for c=1,3 do assert(math.abs(ar[r][c]-br[r][c])<1e-8,'rotation '..name) end end
 end end
end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    lua.execute("assert(mod._start_warlock_traversal_pose(owner,outfit))")
    return lua


class TraversalPoseTests(unittest.TestCase):
    def test_ordinary_events_do_not_queue_or_write(self):
        lua = runtime()
        lua.execute("""
          for _,name in ipairs({'idle','move_fwd_run','attack_shoot_align','unknown'}) do
           event(name,true);tick();assert(calls.writes==0 and #callbacks==0)
          end
        """)

    def test_upward_vault_transfers_pelvis_legs_hands_head_in_same_frame(self):
        lua = runtime()
        lua.execute("""
          move_source('j_hips',0,.2,3,.4);move_source('j_leftfoot',-.2,.2,2.2,1.1)
          move_source('j_lefthand',-.4,.8,4,1.7);move_source('j_head',0,.4,4.3,.7)
          event('jump_up_5m');tick();assert_native()
          assert(mod._warlock_traversal_pose_status(owner)=='active')
          assert(calls.writes==2*(#AttachmentNodeLinking.doomrocket_warlock_bridge-2))
          assert(calls.corrected_hip==3,'accessories did not see final traversal hips')
        """)

    def test_root_offset_rotation_and_100x_wrapper_are_not_applied_twice(self):
        lua = runtime()
        lua.execute("""
          local root=Matrix4x4.identity(1,5,-4,2)
          root[1][1]=0;root[1][2]=-1;root[2][1]=1;root[2][2]=0
          outfit.locals[0]=keep(root);owner.locals[0]=keep(root)
          outfit.locals[1]=keep(Matrix4x4.identity(100,.1,-.05,.02))
          move_source('j_hips',.2,.3,3,.8);move_source('j_leftfoot',-.1,.3,2.5,-1.2)
          event('jump_up_5m');tick();assert_native()
          assert(outfit.locals[1][1][1]==100 and outfit.locals[1][1][4]==.1)
          assert(outfit.locals[0][1][4]==5 and outfit.locals[0][2][4]==-4)
        """)

    def test_entry_and_recovery_blend_then_release_fresh_legacy_pose(self):
        lua = runtime()
        lua.execute("""
          move_source('j_hips',0,0,3,1)
          event('jump_up_5m');tick(.06)
          assert(math.abs(Unit.world_position(outfit,2).z-1.9)<1e-8)
          tick(.06);assert_native()
          event('move_fwd',true);tick(.06)
          assert(math.abs(Unit.world_position(outfit,2).z-1.9)<1e-8)
          local writes=calls.writes;tick(.06)
          assert(calls.writes==writes and mod._warlock_traversal_pose_status(owner)=='native')
          World.update_unit(world,outfit);assert(math.abs(Unit.world_position(outfit,2).z-.8)<1e-8)
        """)

    def test_landing_continues_until_native_completion_event(self):
        lua = runtime()
        lua.execute("""
          event('jump_down');tick();event('jump_down_land');tick(.4)
          assert(mod._warlock_traversal_pose_status(owner)=='active')
          move_source('j_leftfoot',-.1,.1,.2,-.8);tick(.4);assert_native()
          event('move_fwd',true);tick(.12)
          assert(mod._warlock_traversal_pose_status(owner)=='native')
        """)

    def test_recorded_vault_fall_landing_sequence_keeps_continuous_pose_ownership(self):
        lua = runtime()
        lua.execute("""
          event('jump_up_5m');tick()
          for _,name in ipairs({'falling_fwd','jump_down_land'}) do
           event(name);tick(.016)
           assert(mod._warlock_traversal_pose_status(owner)=='active');assert_native()
           assert(messages[#messages]:find('weight=1.000',1,true))
          end
          event('move_fwd',true);tick(.12)
          assert(mod._warlock_traversal_pose_status(owner)=='native')
        """)

    def test_all_native_special_template_fence_gap_and_fall_events_are_supported(self):
        lua = runtime()
        lua.execute("""
          for _,name in ipairs({'jump_up_1m','jump_up_3m','jump_up_5m',
           'jump_up_fence_1m','jump_up_fence_3m','jump_up_fence_5m',
           'jump_down','jump_down_1m','jump_down_land',
           'jump_down_fence_1m','jump_down_fence_3m','jump_down_fence_5m',
           'jump_over_gap_4m','falling_fwd','falling_bwd'}) do
           event(name);tick();assert(mod._warlock_traversal_pose_status(owner)=='active')
          end
        """)

    def test_nested_leg_across_untouched_scale_ancestor_and_distinct_root_point(self):
        lua = runtime()
        lua.execute("""
          -- Actual 100x wrapper, with native carrier root_point displaced from
          -- its entity root, and nested scale/upper/lower/foot ancestors.
          local up=outfit.nodes.j_rightupleg;local leg=outfit.nodes.j_rightleg;local foot=outfit.nodes.j_rightfoot
          local scale=outfit.nodes.j_spine_scale
          outfit.parents[scale]=2;outfit.parents[up]=scale;outfit.parents[leg]=up;outfit.parents[foot]=leg
          outfit.locals[scale]=keep(Matrix4x4.identity(1,0,0,.001))
          outfit.locals[0]=keep(Matrix4x4.identity(1,.3,-.2,.5))
          owner.locals[0]=keep(Matrix4x4.identity(1,-.1,.1,.2))
          assert(mod._start_warlock_traversal_pose(owner,outfit))
          save_base()
          move_source('j_hips',.1,.2,3,.3);move_source('j_rightupleg',.4,.3,2.8,.8)
          move_source('j_rightleg',.4,.5,2.2,-.8);move_source('j_rightfoot',.2,.8,1.6,1.4)
          event('jump_up_5m');tick(.06)
          local mid=Unit.world_position(outfit,foot)
          assert(Vector3.is_valid(mid))
          tick(.06);assert_native()
          assert(outfit.locals[scale][3][4]==.001)
          event('move_fwd',true);tick(.06);tick(.06)
          assert(mod._warlock_traversal_pose_status(owner)=='native')
          World.update_unit(world,outfit)
          local restored=Unit.world_position(outfit,foot);evaluate();World.update_unit(world,outfit)
          assert(Vector3.distance(restored,Unit.world_position(outfit,foot))<1e-8)
        """)

    def test_missing_core_joint_or_cyclic_initial_parent_graph_cannot_arm(self):
        for mutation in ("owner.nodes.j_rightfoot=nil", "outfit.parents[outfit.nodes.j_rightfoot]=outfit.nodes.j_rightfoot"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";assert(not mod._start_warlock_traversal_pose(owner,outfit));event('jump_up_5m');tick();assert(calls.writes==0)")

    def test_interrupted_native_action_and_timeout_do_not_latch(self):
        for mode in ("action", "timeout", "unknown_event"):
            with self.subTest(mode=mode):
                lua = runtime()
                lua.globals().mode = mode
                lua.execute("""
                  event('jump_up_5m');BLACKBOARDS[owner]={is_climbing=true};tick()
                  if mode=='action' then BLACKBOARDS[owner].is_climbing=nil
                  elseif mode=='unknown_event' then event('unknown_traversal_cancel',false)
                  else BLACKBOARDS={};tick(8) end
                  tick(.12);assert(mod._warlock_traversal_pose_status(owner)=='native')
                  local writes=calls.writes;tick();assert(calls.writes==writes)
                """)

    def test_marked_custom_profile_or_authored_pose_never_receives_writes(self):
        for guard in ("outfit.profile='artist'", "channels.upper_body='authored'",
                      "channels.upper_body='unsupported'", "channels.transitioning=true"):
            with self.subTest(guard=guard):
                lua = runtime()
                lua.execute("event('jump_up_5m');mod._queue_warlock_traversal_pose(world,.12);" + guard + ";drain();assert(calls.writes==0)")
                lua.execute("channels={upper_body='legacy',weapon='legacy'};outfit.profile=nil;tick();assert(calls.writes==0)")
        lua = runtime()
        lua.execute("outfit.profile='artist';assert(not mod._start_warlock_traversal_pose(owner,outfit));event('jump_up_5m');tick();assert(calls.writes==0)")

    def test_invalid_late_candidate_or_graph_causes_zero_partial_writes(self):
        for mutation in ("owner.locals[owner.nodes.j_rightfoot][1][4]=0/0",
                         "move_source('j_head',0,0,20)",
                         "outfit.locals[1][1][2]=.25",
                         "outfit.parents[outfit.nodes.j_rightfoot]=outfit.nodes.j_rightfoot",
                         "owner.nodes.j_rightfoot=999"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("event('jump_up_5m');" + mutation + ";tick();assert(calls.writes==0)")

    def test_source_scale_is_ignored_custom_scale_and_original_lower_tracks_remain(self):
        lua = runtime()
        lua.execute("""
          local p=Matrix4x4.copy(owner.locals[owner.nodes.j_leftfoot])
          p[1][1]=2;p[2][2]=3;p[3][3]=4;owner.locals[owner.nodes.j_leftfoot]=keep(p)
          local old=keep(outfit.locals[outfit.nodes.j_spine_scale])
          event('jump_down_1m');tick();assert_native()
          for node,p in pairs(base) do
           local scale=Unit.local_scale(outfit,node)
           assert(math.abs(scale.x-1)<1e-8 and math.abs(scale.y-1)<1e-8 and math.abs(scale.z-1)<1e-8)
          end
          assert(outfit.locals[outfit.nodes.j_spine_scale][1][4]==old[1][4])
          event('idle',true);tick();evaluate();World.update_unit(world,outfit)
          assert(outfit.locals[outfit.nodes.j_leftfoot][1][4]==base[outfit.nodes.j_leftfoot][1][4])
        """)

    def test_teardown_and_replacement_invalidate_queued_native_handles(self):
        for cleanup in ("mod._stop_warlock_traversal_pose(owner);owner.alive=false;outfit.alive=false",
                        "mod._reset_warlock_traversal_pose();owner.alive=false;outfit.alive=false",
                        "mod._release_warlock_traversal_world(world);released=world",
                        "mod._warlock_outfits[owner]=weapon",
                        "HEALTH_ALIVE[owner]=nil"):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute("event('jump_up_5m');mod._queue_warlock_traversal_pose(world,.12);" + cleanup + ";drain();assert(calls.writes==0 and not mod.last_error,mod.last_error)")

    def test_wrong_world_duplicate_queues_and_paused_dt_do_not_duplicate_pose(self):
        lua = runtime()
        lua.execute("""
          event('jump_up_5m')
          for _,dt in ipairs({0,-1,0/0,math.huge}) do mod._queue_warlock_traversal_pose(world,dt) end
          mod._queue_warlock_traversal_pose(other_world,.12);assert(#callbacks==0)
          mod._queue_warlock_traversal_pose(world,.12);mod._queue_warlock_traversal_pose(world,.12)
          assert(#callbacks==1);drain();local writes=calls.writes
          mod._queue_warlock_traversal_pose(other_world,.12);drain();assert(calls.writes==writes)
        """)

    def test_hot_reload_invalidates_old_closure_and_accepts_new_registration(self):
        lua = runtime()
        lua.execute("event('jump_up_5m');mod._queue_warlock_traversal_pose(world,.12);assert(#callbacks==1)")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("drain();assert(calls.writes==0);assert(mod._start_warlock_traversal_pose(owner,outfit));event('jump_up_5m');tick();assert(calls.writes>0)")

    def test_initial_health_cache_gap_defers_first_vault_without_losing_it(self):
        lua = runtime()
        lua.execute("""
          -- Match production ownership: startup health nil is unsupported,
          -- so provisional event storage must not require legacy permission.
          function mod._warlock_animation_ownership()
           local mode=HEALTH_ALIVE[owner]==true and 'legacy' or 'unsupported'
           return {upper_body=mode,weapon=mode}
          end
          HEALTH_ALIVE[owner]=nil
          assert(mod._start_warlock_traversal_pose(owner,outfit))
          event('jump_up_5m');tick();assert(calls.writes==0)
          HEALTH_ALIVE[owner]=true;tick();assert_native();assert(calls.writes>0)
          HEALTH_ALIVE[owner]=nil;tick();local writes=calls.writes
          HEALTH_ALIVE[owner]=true;tick();assert(calls.writes==writes)
          assert(mod._warlock_traversal_pose_status(owner)=='off')
        """)

    def test_scheduler_runs_traversal_after_grip_before_hose(self):
        # Execute the real shared animation scheduler rather than matching text.
        import test_doomrocket_animation_callbacks as callbacks
        lua = callbacks.runtime()
        lua.execute("""
          function mod._queue_warlock_grip_alignment(w,dt)
           callbacks[#callbacks+1]=function() events[#events+1]='grip_pose' end
          end
          function mod._queue_warlock_traversal_pose(w,dt)
           assert(w.animated);callbacks[#callbacks+1]=function() events[#events+1]='traversal_pose' end
          end
          World.update_animations(world,.016);drain_and_update_scene(world)
          assert(table.concat(events,','):find('grip_pose,traversal_pose,hose_pose:game,scene:game',1,true))
        """)


if __name__ == "__main__":
    unittest.main()
