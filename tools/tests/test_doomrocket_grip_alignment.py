"""Execute the living upper-body transfer with an independent scene graph.

Uses the real 100x ancestor and reversed Stingray row products. Native world
poses are reconstructed from final local writes, rather than accepting a
matching matrix formula as proof. This does not establish rendered acceptance.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime
import test_doomrocket_animation_blend as blend
import test_doomrocket_hose_lifecycle as lifetime

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_grip_alignment.lua"

HARNESS = lifetime.HARNESS.split("Quaternion={")[0] + r'''
function keep(p) local q=Matrix4x4.copy(p);q.epoch=nil;return q end
function rotation(p)
 local q=Matrix4x4.copy(p)
 for _,axis in ipairs({'x','y','z'}) do
  local v=Matrix4x4[axis](q);local n=Vector3.length(v)
  Matrix4x4['set_'..axis](q,Vector3(v.x/n,v.y/n,v.z/n))
 end
 Matrix4x4.set_translation(q,Vector3(0,0,0));return q
end
Matrix4x4.rotation=rotation
Matrix4x4.from_quaternion_position=function(q,v)
 local p=Matrix4x4.copy(q);Matrix4x4.set_translation(p,v);return p
end
Vector3.is_valid=function(v) return v.x==v.x and v.y==v.y and v.z==v.z
 and math.abs(v.x)<math.huge and math.abs(v.y)<math.huge and math.abs(v.z)<math.huge end
world={};other_world={};callbacks={};calls={writes=0,flushes=0}
function make_unit(name)
 return {alive=true,world=world,name=name,nodes={},parents={},locals={[0]=keep(Matrix4x4.identity())},cache={}}
end
owner=make_unit('carrier');outfit=make_unit('units/warlock_bombardier/warlock_bombardier_3p')
weapon=make_unit('units/rocket/pRocketLauncher')
local function check(u) assert(u and u.alive,'dead native handle');assert(u.world~=released,'released handle') end
function composed(u,node,poses)
 if poses[node] then return poses[node] end
 local pose=Matrix4x4.copy(u.locals[node])
 if node~=0 then pose=Matrix4x4.multiply(pose,composed(u,u.parents[node],poses)) end
 poses[node]=pose;return pose
end
World={update_unit=function(w,u)
 check(u);assert(u.world==w);u.cache={};calls.flushes=calls.flushes+1
 local poses={};for node in pairs(u.locals) do u.cache[node]=keep(composed(u,node,poses)) end
end}
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) check(u);return u.world end,
 get_data=function(u,key) check(u);assert(key=='unit_name');return u.name end,
 has_node=function(u,name) check(u);return u.nodes[name]~=nil end,
 node=function(u,name) check(u);return assert(u.nodes[name],'missing node') end,
 scene_graph_parent=function(u,node) check(u);return u.parents[node] end,
 world_pose=function(u,node) check(u);return Matrix4x4.copy(assert(u.cache[node])) end,
 world_position=function(u,node) return Matrix4x4.translation(Unit.world_pose(u,node)) end,
 world_rotation=function(u,node) return rotation(Unit.world_pose(u,node)) end,
 local_pose=function(u,node) check(u);return Matrix4x4.copy(u.locals[node]) end,
 local_scale=function(u,node)
  local p=Unit.local_pose(u,node);return Vector3(Vector3.length(Matrix4x4.x(p)),Vector3.length(Matrix4x4.y(p)),Vector3.length(Matrix4x4.z(p)))
 end,
 set_local_rotation=function(u,node,q)
  check(u);assert(u==outfit and node>2,'wrote carrier/root/lower-body')
  local p=Unit.local_pose(u,node);local s=Unit.local_scale(u,node)
  for i,axis in ipairs({'x','y','z'}) do
   local v=Matrix4x4[axis](q);local n=Vector3.length(v)
   Matrix4x4['set_'..axis](p,Vector3(v.x/n*s[i],v.y/n*s[i],v.z/n*s[i]))
  end
  u.locals[node]=keep(p);calls.writes=calls.writes+1
 end,
 set_local_position=function(u,node,v)
  check(u);assert(u==outfit and node>2,'wrote carrier/root/lower-body')
  local p=Unit.local_pose(u,node);Matrix4x4.set_translation(p,v);u.locals[node]=keep(p);calls.writes=calls.writes+1
 end,
 set_local_scale=function() error('copied scale') end,
 set_local_pose=function() error('copied raw local pose') end,
 set_animation_state_machine=function() error('foreign ASM') end,
}
outfit.nodes.j_hips=2;outfit.parents[1]=0;outfit.parents[2]=1
outfit.locals[1]=keep(Matrix4x4.identity(100));outfit.locals[2]=keep(Matrix4x4.identity(1,0,0,.008))
local names={'j_spine','j_spine1','j_leftshoulder','j_rightshoulder','j_leftarm','j_rightarm',
 'j_leftforearm','j_rightforearm','j_lefthand','j_righthand','j_leftforearmroll','j_rightforearmroll'}
for i,name in ipairs(names) do
 local node=i+2;outfit.nodes[name]=node;outfit.parents[node]=i==1 and 2 or 3
 outfit.locals[node]=keep(Matrix4x4.identity(1,(i%2==0 and -.001 or .001)*i,0,.001))
 owner.nodes[name]=node+50;owner.parents[node+50]=0
end
World.update_unit(world,outfit)
for _,name in ipairs(names) do
 local p=Unit.world_pose(outfit,outfit.nodes[name]);local q=rotation(p)
 Matrix4x4.set_translation(q,Matrix4x4.translation(p));owner.locals[owner.nodes[name]]=keep(q)
end
World.update_unit(world,owner);World.update_unit(world,weapon)
mod={_warlock_outfits={[owner]=outfit}}
function mod:pcall(fn,...)
 local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result
end
function get_mod(name) assert(name=='doomrocket');return mod end
HEALTH_ALIVE={[owner]=true}
inventory={unit=owner,inventory_item_units={outfit,weapon}}
animation={add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn end}
Managers={state={entity={system=function(self,name) assert(name=='animation_system');return animation end}}}
function drain()
 local todo=callbacks;callbacks={};for _,fn in ipairs(todo) do fn() end
 epoch=epoch+1
end
function tick()
 mod._queue_warlock_grip_alignment(world,1/60);drain()
end
function max_gap()
 local worst=0
 for _,name in ipairs(names) do
  local a=Unit.world_pose(owner,owner.nodes[name]);local b=Unit.world_pose(outfit,outfit.nodes[name])
  worst=math.max(worst,Vector3.distance(Matrix4x4.translation(a),Matrix4x4.translation(b)))
  local ar,br=rotation(a),rotation(b)
  for r=1,3 do for c=1,3 do worst=math.max(worst,math.abs(ar[r][c]-br[r][c])) end end
 end
 return worst
end
function move_source(name,x,y,z,angle)
 local p=Matrix4x4.identity();angle=angle or 0
 p[1][1]=math.cos(angle);p[1][2]=-math.sin(angle);p[2][1]=math.sin(angle);p[2][2]=math.cos(angle)
 Matrix4x4.set_translation(p,Vector3(x,y,z));owner.locals[owner.nodes[name]]=keep(p)
end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    lua.execute("assert(mod._start_warlock_grip_alignment(owner,outfit,inventory))")
    return lua


class GripAlignmentTests(unittest.TestCase):
    def test_compositor_runs_after_flush_and_before_grip_ownership_decision(self):
        lua = runtime()
        lua.execute("""
          local flushed=calls.flushes
          composed_first=false
          function mod._apply_warlock_animation_blend(carrier,target)
           assert(carrier==owner and target==outfit)
           assert(calls.flushes>=flushed+3,'presentation consumed stale native poses')
           composed_first=true
          end
          function mod._warlock_animation_ownership(carrier,target)
           assert(composed_first,'grip chose ownership before presentation composition')
           return {upper_body='authored',weapon='authored'}
          end
          move_source('j_lefthand',.4,.2,.9,.6)
          tick();assert(not mod.last_error,mod.last_error)
          assert(calls.writes==0,'legacy grip overwrote compositor-owned pose')
          assert(mod._warlock_grip_alignment_status(owner)=='authored_no_wielded_weapon')
        """)

    def test_read_only_helper_candidates_match_existing_legacy_result(self):
        lua = runtime()
        lua.execute("""
          helper=make_unit('pose-only-helper')
          for name,node in pairs(outfit.nodes) do helper.nodes[name]=node end
          for node,parent in pairs(outfit.parents) do helper.parents[node]=parent end
          for node,p in pairs(outfit.locals) do helper.locals[node]=keep(p) end
          function mod._warlock_transition_helper_valid(carrier,target)
           return carrier==owner and target==helper
          end
          move_source('j_lefthand',.4,.2,.9,.6)
          move_source('j_righthand',-.4,.2,.9,-.3)
          local originals={};for node,p in pairs(helper.locals) do originals[node]=keep(p) end
          local writes=assert(mod._prepare_warlock_legacy_grip_pose(owner,helper))
          assert(#writes==12 and calls.writes==0)
          assert(mod._warlock_grip_alignment_status(owner)=='armed')
          for node,p in pairs(originals) do
           for r=1,4 do for c=1,4 do assert(p[r][c]==helper.locals[node][r][c]) end end
          end
          tick();assert(calls.writes==24 and max_gap()<1e-8)
          for _,write in ipairs(writes) do
           for r=1,4 do for c=1,4 do
            assert(math.abs(write.pose[r][c]-outfit.locals[write.node][r][c])<1e-8)
           end end
          end
        """)

    def test_helper_candidates_require_authorized_living_pair_and_valid_graph(self):
        for mutation in (
            "mod._warlock_transition_helper_valid=nil",
            "mod._warlock_transition_helper_valid=function() return false end",
            "helper=outfit",
            "helper=owner",
            "helper.alive=false",
            "helper.world=other_world",
            "HEALTH_ALIVE[owner]=nil",
            "mod._warlock_outfits[owner]=nil",
            "helper.nodes.j_righthand=nil",
            "helper.parents[3]=4;helper.parents[4]=3",
            "helper.locals[1][1][2]=50",
            "helper.locals[helper.nodes.j_righthand][1][4]=0/0",
            "mod._note_warlock_grip_alignment_event(owner,'jump',false)",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("""
                  helper=make_unit('pose-only-helper')
                  for name,node in pairs(outfit.nodes) do helper.nodes[name]=node end
                  for node,parent in pairs(outfit.parents) do helper.parents[node]=parent end
                  for node,p in pairs(outfit.locals) do helper.locals[node]=keep(p) end
                  function mod._warlock_transition_helper_valid(carrier,target)
                   return carrier==owner and target==helper
                  end
                """)
                lua.execute(mutation + """
                  local writes,status=mod._prepare_warlock_legacy_grip_pose(owner,helper)
                  assert(writes==nil and type(status)=='string' and calls.writes==0)
                """)

    def test_phase_and_aim_deltas_use_composed_current_frame_pose(self):
        lua = runtime()
        lua.execute("""
          move_source('j_lefthand',.4,.2,.9,0.6)
          move_source('j_righthand',-.4,.2,.9,-0.3)
          mod._note_warlock_grip_alignment_event(owner,'attack_shoot_align',true)
          tick();assert(not mod.last_error,mod.last_error)
          assert(mod._warlock_grip_alignment_status(owner)=='active')
          assert(calls.writes==24 and max_gap()<1e-8)
          assert(calls.flushes>=4)
          assert(Unit.local_scale(outfit,outfit.nodes.j_lefthand).x==1)
        """)

    def test_rotated_translated_scale100_parent_preserves_world_alignment(self):
        lua = runtime()
        lua.execute("""
          local p=Matrix4x4.identity(100,2,-1,0)
          p[1][1]=0;p[1][2]=-100;p[2][1]=100;p[2][2]=0
          outfit.locals[1]=keep(p)
          -- Reposition only the pelvis so the torso stays in the supported range.
          local hip=Matrix4x4.identity(1,.01,.02,.008);outfit.locals[2]=keep(hip)
          move_source('j_lefthand',.2,.3,.9,.5)
          tick();assert(not mod.last_error,mod.last_error);assert(max_gap()<1e-8)
          assert(outfit.locals[1][1][2]==-100 and outfit.locals[2][1][4]==.01)
        """)

    def test_native_scale_is_not_copied_and_locomotion_pose_is_untouched(self):
        lua = runtime()
        lua.execute("""
          local hip=keep(outfit.locals[2]);local node=owner.nodes.j_lefthand
          local p=Matrix4x4.copy(owner.locals[node]);p[1][1]=2;p[2][2]=3;p[3][3]=4
          owner.locals[node]=keep(p);tick();assert(not mod.last_error,mod.last_error)
          assert(max_gap()<1e-8)
          for r=1,4 do for c=1,4 do assert(hip[r][c]==outfit.locals[2][r][c]) end end
          assert(Unit.local_scale(outfit,outfit.nodes.j_lefthand).x==1)
        """)

    def test_unsupported_jump_is_flushed_but_never_pulls_torso_off_pelvis(self):
        lua = runtime()
        lua.execute("""
          mod._note_warlock_grip_alignment_event(owner,'jump_up_5m',false)
          move_source('j_spine',0,0,2.5,1);tick()
          assert(calls.writes==0 and calls.flushes>=3)
          assert(mod._warlock_grip_alignment_status(owner)=='unsupported_event')
          move_source('j_spine',.001,0,.9,0)
          mod._note_warlock_grip_alignment_event(owner,'idle',true);tick()
          assert(calls.writes==24 and max_gap()<1e-8)
        """)

    def test_nan_shear_and_spawn_transient_leave_entire_candidate_unwritten(self):
        for mutation in (
            "owner.locals[owner.nodes.j_righthand][1][4]=0/0",
            "outfit.locals[1][1][2]=50",
            "move_source('j_spine',0,0,20,0)",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";tick();assert(calls.writes==0)")

    def test_death_teardown_reset_and_world_release_cancel_pending_writes(self):
        for cleanup in (
            "mod._stop_warlock_grip_alignment(owner)",
            "mod._reset_warlock_grip_alignment()",
            "mod._release_warlock_grip_alignment_world(world)",
            "HEALTH_ALIVE[owner]=nil",
            "mod._warlock_outfits[owner]=nil",
        ):
            for dt in ("1/60", "1"):
                with self.subTest(cleanup=cleanup, dt=dt):
                    lua = runtime()
                    lua.execute("mod._queue_warlock_grip_alignment(world," + dt + ");assert(#callbacks==1)")
                    lua.execute(cleanup)
                    lua.execute("owner.alive=false;outfit.alive=false;weapon.alive=false;drain();assert(calls.writes==0)")

    def test_finite_hitch_presents_once_before_legacy_correction_and_outfit(self):
        lua = runtime()
        lua.execute("""
          local presented,corrected=0,0
          local flushed=calls.flushes
          function mod._apply_warlock_animation_blend(carrier,target)
           assert(carrier==owner and target==outfit and calls.flushes>=flushed+3)
           assert(calls.writes==0,'grip ran before compositor release')
           presented=presented+1
          end
          function mod._warlock_animation_ownership(carrier,target)
           assert(presented==1,'ownership read before queued presentation')
           return {upper_body='legacy',weapon='legacy'}
          end
          function mod._apply_warlock_outfit_correction(carrier,target,corpse)
           assert(carrier==owner and target==outfit and corpse==false)
           assert(calls.writes==24 and max_gap()<1e-8,'outfit ran before current-frame grip')
           corrected=corrected+1
          end
          mod._queue_warlock_grip_alignment(world,1)
          mod._queue_warlock_grip_alignment(world,1)
          assert(#callbacks==1 and presented==0 and calls.writes==0)
          move_source('j_lefthand',.4,.2,.9,.6)
          drain();assert(not mod.last_error,mod.last_error)
          assert(presented==1 and corrected==1 and calls.writes==24)
          assert(mod._warlock_grip_alignment_status(owner)=='active')
        """)

    def test_finite_hitch_keeps_authored_pose_ownership_in_queued_callback(self):
        lua = runtime()
        lua.execute("""
          local presented=0
          local originals={};for node,p in pairs(outfit.locals) do originals[node]=keep(p) end
          function mod._apply_warlock_animation_blend(carrier,target)
           assert(carrier==owner and target==outfit);presented=presented+1
          end
          function mod._warlock_animation_ownership(carrier,target)
           assert(presented==1)
           return {upper_body='authored',weapon='authored'}
          end
          mod._queue_warlock_grip_alignment(world,1);assert(#callbacks==1)
          drain();assert(not mod.last_error,mod.last_error)
          assert(presented==1 and calls.writes==0)
          for node,p in pairs(originals) do
           for r=1,4 do for c=1,4 do assert(p[r][c]==outfit.locals[node][r][c]) end end
          end
          assert(mod._warlock_grip_alignment_status(owner)=='authored_no_wielded_weapon')
        """)

    def test_actual_compositor_completes_authored_bridge_through_hitch_callback(self):
        # Use the real 138-bone compositor and grip queue together. The clock
        # double advances independently in engine(); no direct apply call can
        # substitute for presentation on either of these two evaluated frames.
        lua = blend.runtime()
        lua.execute("""
          callbacks={}
          function mod:pcall(fn,...)
           local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result
          end
          local animation={add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn end}
          Managers={state={entity={system=function(self,name)
           assert(name=='animation_system');return animation
          end}}}
          function drain()
           local todo=callbacks;callbacks={};for _,fn in ipairs(todo) do fn() end
          end
          function mod._warlock_animation_ownership(carrier,target)
           assert(carrier==owner and target==outfit)
           return {upper_body='authored',weapon='authored'}
          end
        """)
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
          assert(mod._start_warlock_grip_alignment(owner,outfit,{}))
          begin();change('authored')
          mod._update_warlock_animation_blend(world,.1);engine(.1)
          mod._queue_warlock_grip_alignment(world,.1);assert(#callbacks==1);drain()
          assert(not mod.last_error,mod.last_error)
          assert(active() and calls.visible==138*3)
          local writes=calls.visible
          mod._update_warlock_animation_blend(world,1);engine(1)
          mod._queue_warlock_grip_alignment(world,1);assert(#callbacks==1);drain()
          assert(not mod.last_error,mod.last_error)
          assert(not active() and status()=='native' and calls.visible==writes)
          assert(calls.helper_bones==0 and calls.grip==0 and calls.accessories==0 and calls.warnings==0)
        """)

    def test_invalid_or_paused_frame_does_not_queue_presentation(self):
        for dt in ("nil", "0", "-1", "0/0", "math.huge", "-math.huge", "'1'"):
            with self.subTest(dt=dt):
                lua = runtime()
                lua.execute("mod._queue_warlock_grip_alignment(world," + dt + ");assert(#callbacks==0 and calls.writes==0)")

    def test_missing_node_and_wrong_skeleton_fail_before_unsafe_lookup(self):
        lua = runtime()
        lua.execute("""
          mod._stop_warlock_grip_alignment(owner);owner.nodes.j_lefthand=nil
          assert(not mod._start_warlock_grip_alignment(owner,outfit,inventory))
          assert(not mod._start_warlock_grip_alignment(nil,outfit,inventory))
        """)

    def test_queued_callback_is_unique_and_isolated_by_world(self):
        lua = runtime()
        lua.execute("""
          mod._queue_warlock_grip_alignment(world,1/60)
          mod._queue_warlock_grip_alignment(world,1/60)
          assert(#callbacks==1);drain();assert(calls.writes==24)
          mod._queue_warlock_grip_alignment(other_world,1/60);drain()
          assert(calls.writes==24)
        """)


if __name__ == "__main__":
    unittest.main()
