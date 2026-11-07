"""Execute the candidate accessory correction against an independent scene graph.

The actual Lua 5.1 module runs with native-temporary expiry and stale world
caches. This proves numerical/lifetime behavior, not rendered game acceptance.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime
import test_doomrocket_hose_lifecycle as lifetime

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_outfit_correction.lua"

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

-- Independently compose column matrices. Do not use the production row-vector
-- multiply helper to establish expected skeleton worlds or correction targets.
function product(a,b)
 local p=Matrix4x4.identity()
 for r=1,4 do for c=1,4 do
  local value=0;for k=1,4 do value=value+a[r][k]*b[k][c] end;p[r][c]=value
 end end
 return p
end
function pose(x,y,z,rx,ry,rz,scale)
 local a=Matrix4x4.identity();local b=Matrix4x4.identity();local c=Matrix4x4.identity()
 a[2][2]=math.cos(rx);a[2][3]=-math.sin(rx);a[3][2]=math.sin(rx);a[3][3]=math.cos(rx)
 b[1][1]=math.cos(ry);b[1][3]=math.sin(ry);b[3][1]=-math.sin(ry);b[3][3]=math.cos(ry)
 c[1][1]=math.cos(rz);c[1][2]=-math.sin(rz);c[2][1]=math.sin(rz);c[2][2]=math.cos(rz)
 local p=product(c,product(b,a));scale=scale or 1
 for r=1,3 do for col=1,3 do p[r][col]=p[r][col]*scale end end
 p[1][4]=x;p[2][4]=y;p[3][4]=z;return p
end
function axis_lengths(p)
 local a={};for c=1,3 do a[c]=math.sqrt(p[1][c]^2+p[2][c]^2+p[3][c]^2) end;return a
end
function rigid(p)
 local q=Matrix4x4.copy(p);local scales=axis_lengths(p)
 for r=1,3 do for c=1,3 do q[r][c]=q[r][c]/scales[c] end end;return q
end
world={alive=true};other_world={alive=true};callbacks={}
calls={writes=0,flushes=0,reads=0,scale_writes=0,native_touches=0}
function make_unit(name,w)
 return {alive=true,world=w or world,name=name,data={},nodes={},parents={},
  locals={[0]=keep(Matrix4x4.identity())},cache={},scale_overrides={}}
end
owner=make_unit('carrier');outfit=make_unit('units/warlock_bombardier/warlock_bombardier_3p')
local function check(u)
 assert(u and u.alive,'dead native handle touched')
 assert(u.world and u.world.alive,'released world touched')
 calls.native_touches=calls.native_touches+1
end
function composed(u,node,poses)
 poses=poses or {};if poses[node] then return poses[node] end
 local p=Matrix4x4.copy(assert(u.locals[node],'unknown skeleton node'))
 if node~=0 then p=product(composed(u,assert(u.parents[node]),poses),p) end
 poses[node]=p;return p
end
World={update_unit=function(w,u)
 check(u);assert(u.world==w);u.cache={};calls.flushes=calls.flushes+1
 local all={};for node in pairs(u.locals) do u.cache[node]=keep(composed(u,node,all)) end
end}
allowed={}
Unit={
 alive=function(u) return u and u.alive or false end,
 world=function(u) check(u);return u.world end,
 get_data=function(u,key) check(u);return key=='unit_name' and u.name or u.data[key] end,
 has_node=function(u,name) check(u);return name==0 or u.nodes[name]~=nil end,
 node=function(u,name) check(u);return assert(u.nodes[name],'unsafe missing-node lookup') end,
 scene_graph_parent=function(u,node) check(u);return u.parents[node] end,
 world_pose=function(u,node) check(u);calls.reads=calls.reads+1;return Matrix4x4.copy(assert(u.cache[node])) end,
 world_position=function(u,node) return Matrix4x4.translation(Unit.world_pose(u,node)) end,
 world_rotation=function(u,node) return rotation(Unit.world_pose(u,node)) end,
 local_pose=function(u,node) check(u);return Matrix4x4.copy(assert(u.locals[node])) end,
 local_scale=function(u,node)
  check(u);local a=u.scale_overrides[node] or axis_lengths(u.locals[node]);return Vector3(a[1],a[2],a[3])
 end,
 set_local_rotation=function(u,node,q)
  check(u);assert(u==outfit and allowed[node],'wrote a non-correction skeleton node')
  local p=Unit.local_pose(u,node);local scales=Unit.local_scale(u,node)
  for c,axis in ipairs({'x','y','z'}) do
   local v=Matrix4x4[axis](q);local n=Vector3.length(v)
   Matrix4x4['set_'..axis](p,Vector3(v.x/n*scales[c],v.y/n*scales[c],v.z/n*scales[c]))
  end
  u.locals[node]=keep(p);calls.writes=calls.writes+1
 end,
 set_local_position=function(u,node,v)
  check(u);assert(u==outfit and allowed[node],'wrote a non-correction skeleton node')
  local p=Unit.local_pose(u,node);Matrix4x4.set_translation(p,v)
  u.locals[node]=keep(p);calls.writes=calls.writes+1
 end,
 set_local_scale=function() calls.scale_writes=calls.scale_writes+1;error('changed existing local scale') end,
 set_local_pose=function() error('wrote raw pose instead of preserving local scale') end,
 set_animation_state_machine=function() error('changed animation ownership') end,
}
function add(name,node,parent,p)
 outfit.nodes[name]=node;outfit.parents[node]=parent;outfit.locals[node]=keep(p)
end
add('root_point',1,0,pose(2,-1,.4,0,0,.35,100))
add('j_hips',2,1,pose(.002,.004,.008,.1,-.16,.08))
add('j_spine',3,2,pose(.001,.001,.001,.12,.04,-.2))
add('j_spine_scale',4,3,pose(0,0,.001,0,.08,0))
add('j_spine1',5,4,pose(.001,0,.002,-.13,.14,.21))
add('j_loot_sack',6,5,pose(.001,.002,-.001,.17,0,-.24))
for i=1,5 do
 add('j_loot_sack_component'..i,6+i,6,pose(.001*i,-.001*i,.0005*i,.04*i,.01*i,-.03*i))
 allowed[6+i]=true
end
add('j_whip_parent',12,2,pose(.001,.002,-.004,.1,.15,-.2));allowed[12]=true
add('j_whip_dynamic',13,12,pose(.001,0,-.003,-.1,.05,.17));allowed[13]=true
add('j_backpack',14,5,pose(.002,-.003,.001,.09,.05,.01))
add('j_leftthigh',15,2,pose(.001,0,-.002,-.1,0,.07))
add('j_rightthigh',16,2,pose(-.001,0,-.002,.1,0,-.07))
add('j_leftfoot',17,15,pose(0,.001,-.003,.2,0,0))
add('j_rightfoot',18,16,pose(0,.001,-.003,-.2,0,0))
add('j_lefthand',19,5,pose(.003,.001,0,.1,0,.2))
add('j_righthand',20,5,pose(-.003,.001,0,-.1,0,-.2))

manifest_id=string.rep('a',64)
channels={
 {bone='j_whip_parent',parent='j_hips',bind_offset=keep(pose(.06,.08,-.16,.13,-.12,.24))},
 {bone='j_whip_dynamic',parent='j_whip_parent',bind_offset=keep(pose(-.05,.05,-.4,-.09,.11,-.18))},
}
for i=1,5 do channels[#channels+1]={bone='j_loot_sack_component'..i,parent='j_loot_sack',
 bind_offset=keep(pose((i-3)*.05,-.04,.07+i*.01,.04*i,-.03*i,.06*i))} end
profile={manifest_id=manifest_id,unit=outfit.name,accessory_skin='localized-v1',
 body_fbx_sha256=string.rep('b',64),
 shipping_body_sha256='cb2eba0224d1eff044a30b1bf0269d1a10395e8db9244af5c011e5c0ba0bd0bc',
 shipping_bones_sha256='6e4eb323ba5a21db1e2f09f91d73cfa1e3234a03d7b183223f48ccd96c51a197',
 rest_contract_sha256=string.rep('c',64),
 reference_bone='j_hips',native_bind_scale=100,channels=channels}
outfit.data.warlock_rig_profile='localized-v1-runtime'
outfit.data.warlock_animation_manifest_id=manifest_id
mod={_warlock_outfits={[owner]=outfit},
 _warlock_animation_manifest={schema=1,profiles={['localized-v1-runtime']=profile}}}
function mod:pcall(fn,...)
 local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result
end
function get_mod(name) assert(name=='doomrocket');return mod end
ownership_mode='legacy-pelvis'
function mod._warlock_animation_ownership(carrier,target)
 assert(carrier==owner and target==outfit)
 return ownership_mode and {accessories=ownership_mode} or nil
end
HEALTH_ALIVE={[owner]=true}
animation={add_safe_animation_callback=function() error('accessory module queued itself') end}
Managers={state={entity={system=function() return animation end}}}
World.update_unit(world,owner);World.update_unit(world,outfit)

function snapshot()
 before={};before_scales={};expected={}
 for node,p in pairs(outfit.locals) do before[node]=keep(p);before_scales[node]=axis_lengths(p) end
 local hip=composed(outfit,outfit.nodes.j_hips);local ratio=axis_lengths(hip)[1]/100
 local hip_rigid=rigid(hip)
 for _,channel in ipairs(channels) do
  local node=outfit.nodes[channel.bone]
  local offset=Matrix4x4.copy(channel.bind_offset)
  for r=1,3 do offset[r][4]=offset[r][4]*ratio end
  local desired=product(hip_rigid,offset);local scales=axis_lengths(composed(outfit,node))
  for r=1,3 do for c=1,3 do desired[r][c]=desired[r][c]*scales[c] end end
  expected[node]=keep(desired)
 end
end
function assert_result()
 assert(calls.scale_writes==0,'wrote local scale')
 for node,p in pairs(before) do
  local result=outfit.locals[node]
  if not allowed[node] then
   for r=1,4 do for c=1,4 do assert(p[r][c]==result[r][c],'modified unrelated local') end end
  else
   local scales=axis_lengths(result)
   for c=1,3 do assert(math.abs(scales[c]-before_scales[node][c])<1e-9,'changed local scale') end
   local actual=composed(outfit,node)
   for r=1,4 do for c=1,4 do
    assert(math.abs(actual[r][c]-expected[node][r][c])<1e-7,
     'composed correction world differs from rigid pelvis target at node '..node)
   end end
  end
 end
 assert(not mod.last_error,mod.last_error)
end
function apply(allow_corpse)
 return mod._apply_warlock_outfit_correction(owner,outfit,allow_corpse==true)
end
function next_frame() epoch=epoch+1 end
'''


def runtime(start=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    if start:
        lua.execute("assert(mod._start_warlock_outfit_correction(owner,outfit))")
    return lua


def helper_runtime():
    lua = runtime()
    lua.execute("""
      helper=make_unit('pose-only-helper')
      for name,node in pairs(outfit.nodes) do helper.nodes[name]=node end
      for node,parent in pairs(outfit.parents) do helper.parents[node]=parent end
      for node,p in pairs(outfit.locals) do helper.locals[node]=keep(p) end
      local names={'j_spine','j_spine1','j_leftshoulder','j_rightshoulder',
       'j_leftarm','j_rightarm','j_leftforearm','j_rightforearm',
       'j_lefthand','j_righthand','j_leftforearmroll','j_rightforearmroll'}
      local next_node=21
      candidates={}
      for i,name in ipairs(names) do
       if not helper.nodes[name] then
        helper.nodes[name]=next_node;helper.parents[next_node]=5
        helper.locals[next_node]=keep(pose(.001*i,-.001*i,.001,0,0,0))
        next_node=next_node+1
       end
       local node=helper.nodes[name]
       candidates[i]={node=node,pose=Matrix4x4.copy(helper.locals[node])}
      end
      helper_legacy=true
      function mod._warlock_transition_helper_valid(carrier,target,passed_profile)
       return carrier==owner and target==helper and passed_profile==profile and helper_legacy
      end
    """)
    return lua


class OutfitCorrectionTests(unittest.TestCase):
    def test_runtime_avoids_apis_absent_from_vt2_and_traps_corpse_callback_errors(self):
        # Matrix4x4.copy appears only in Darktide's scripts, never in VT2's.
        self.assertNotIn("Matrix4x4.copy", MODULE.read_text(encoding="utf-8"))
        # Vanilla runs safe animation callbacks without an error trap.
        hooks = (ROOT / "scripts/mods/doomrocket/utils/hooks.lua").read_text(encoding="utf-8")
        self.assertIn("mod:pcall(mod._apply_warlock_outfit_correction, driver.owner, outfit_unit, true)", hooks)
        self.assertNotIn("	mod._apply_warlock_outfit_correction(driver.owner", hooks)

    def test_pure_helper_accessories_resolve_uncommitted_grip_parent_candidates(self):
        lua = helper_runtime()
        lua.execute("""
          candidates[1].pose=pose(.001,-.001,.002,.5,-.3,.2)
          candidates[2].pose=pose(-.001,.002,.002,-.4,.6,-.3)
          local originals={};for node,p in pairs(helper.locals) do originals[node]=keep(p) end
          local writes=assert(mod._prepare_warlock_legacy_outfit_pose(owner,helper,profile,candidates))
          assert(#writes==7 and calls.writes==0)
          assert(mod._warlock_outfit_correction_status(owner)=='armed')
          for node,p in pairs(originals) do
           for r=1,4 do for c=1,4 do assert(p[r][c]==helper.locals[node][r][c]) end end
          end
          outfit.locals[3]=keep(candidates[1].pose);outfit.locals[5]=keep(candidates[2].pose)
          snapshot();assert(apply());assert_result()
          for _,write in ipairs(writes) do
           for r=1,4 do for c=1,4 do
            assert(math.abs(write.pose[r][c]-outfit.locals[write.node][r][c])<1e-7)
           end end
          end
          assert(calls.writes==14)
        """)

    def test_pure_helper_accessory_rejection_is_atomic_and_cannot_write_authored_target(self):
        for mutation in (
            "helper_legacy=false",
            "mod._warlock_transition_helper_valid=nil",
            "helper=outfit",
            "helper=owner",
            "helper.alive=false",
            "helper.world=other_world",
            "HEALTH_ALIVE[owner]=nil",
            "mod._warlock_outfits[owner]=nil",
            "profile={}",
            "helper.nodes.j_loot_sack_component5=nil",
            "helper.parents[11]=5",
            "helper.parents[4]=5",
            "helper.locals[11][1][4]=0/0",
            "helper.locals[11][1][2]=.7",
            "helper.locals[2][1][4]=math.huge",
            "table.remove(candidates)",
            "candidates[12]=candidates[11]",
            "candidates[12].node=helper.nodes.j_backpack",
            "candidates[12].pose[1][4]=0/0",
            "candidates[12].pose[1][2]=.7",
            "candidates[12].pose[1][1]=-1",
            "candidates[12].pose[1][1]=1.3",
        ):
            with self.subTest(mutation=mutation):
                lua = helper_runtime()
                lua.execute(mutation + """
                  local writes,status=mod._prepare_warlock_legacy_outfit_pose(owner,helper,profile,candidates)
                  assert(writes==nil and type(status)=='string' and calls.writes==0)
                  assert(mod._warlock_outfit_correction_status(owner)=='armed')
                """)

    def test_seven_targets_use_pelvis_metres_and_actual_corrected_parent(self):
        lua = runtime()
        lua.execute("""
          snapshot();apply();assert_result();assert(calls.writes==14)
          assert(mod._warlock_outfit_correction_status(owner)=='active-legacy')
          assert(mod._warlock_outfit_correction_owns_node(owner,outfit.nodes.j_whip_dynamic))
          for node in pairs(outfit.locals) do
           assert(mod._warlock_outfit_correction_owns_node(owner,node)==(allowed[node]==true))
          end
          assert(#callbacks==0)
        """)

    def test_spine_and_grip_changes_flush_stale_worlds_but_preserve_other_locals(self):
        lua = runtime()
        lua.execute("""
          snapshot();apply();assert_result()
          outfit.locals[outfit.nodes.j_spine]=keep(pose(.001,-.001,.002,.5,-.3,.2))
          outfit.locals[outfit.nodes.j_spine1]=keep(pose(-.001,.002,.002,-.4,.6,-.3))
          outfit.locals[outfit.nodes.j_lefthand]=keep(pose(.004,.002,.001,.3,-.2,.5))
          local old=Unit.world_pose(outfit,outfit.nodes.j_loot_sack)
          local current=composed(outfit,outfit.nodes.j_loot_sack)
          assert(Vector3.distance(Matrix4x4.translation(old),Matrix4x4.translation(current))>.01)
          next_frame();snapshot();apply();assert_result();assert(calls.writes==28)
        """)

    def test_global_unit_scale_changes_offsets_without_copying_native_scale(self):
        for scale in (50, 175):
            with self.subTest(scale=scale):
                lua = runtime()
                lua.execute(f"""
                  outfit.locals[1]=keep(pose(-3,2,.8,.2,-.3,.8,{scale}))
                  snapshot();apply();assert_result();assert(calls.writes==14)
                """)

    def test_scaled_unit_root_and_rotated_nested_parent_compose_correctly(self):
        lua = runtime()
        lua.execute("""
          outfit.locals[0]=keep(pose(-4,3,.7,-.3,.2,.6,.65))
          snapshot();apply();assert_result();assert(calls.writes==14)
          local hip=composed(outfit,2);local cloth=composed(outfit,13)
          local distance=Vector3.distance(Matrix4x4.translation(hip),Matrix4x4.translation(cloth))
          assert(math.abs(distance-math.sqrt(.05^2+.05^2+.4^2)*.65)<1e-9)
        """)

    def test_existing_positive_per_channel_scales_survive(self):
        lua = runtime()
        lua.execute("""
          for node,scale in pairs({[12]=1.2,[13]=.8,[9]=1.7}) do
           local p=outfit.locals[node];for r=1,3 do for c=1,3 do p[r][c]=p[r][c]*scale end end
          end
          snapshot();apply();assert_result();assert(calls.writes==14)
        """)

    def test_aligned_nonuniform_target_scale_is_preserved(self):
        lua = runtime()
        lua.execute("""
          local p=outfit.locals[9]
          for r=1,3 do p[r][1]=p[r][1]*1.2;p[r][2]=p[r][2]*1.3;p[r][3]=p[r][3]*1.4 end
          snapshot();apply();assert_result();assert(calls.writes==14)
        """)

    def test_nonuniform_ancestor_that_shears_child_has_no_partial_writes(self):
        lua = runtime()
        lua.execute("""
          for r=1,3 do outfit.locals[12][r][1]=outfit.locals[12][r][1]*1.4 end
          apply();assert(calls.writes==0)
        """)

    def test_late_nan_shear_singular_reflection_and_scale_mismatch_write_nothing(self):
        for mutation in (
            "outfit.locals[11][1][4]=0/0",
            "outfit.locals[11][1][2]=.7",
            "for r=1,3 do outfit.locals[11][r][3]=0 end",
            "for r=1,3 do outfit.locals[11][r][1]=-outfit.locals[11][r][1] end",
            "outfit.scale_overrides[11]={.8,1,1}",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + """;apply();assert(calls.writes==0)
                  for node in pairs(allowed) do assert(not mod._warlock_outfit_correction_owns_node(owner,node)) end
                """)

    def test_invalid_hips_and_parent_fail_preflight_without_writes(self):
        for mutation in (
            "outfit.locals[2][1][4]=math.huge",
            "outfit.locals[1][1][2]=40",
            "for r=1,3 do outfit.locals[1][r][3]=0 end",
            "for r=1,3 do outfit.locals[1][r][1]=-outfit.locals[1][r][1] end",
            "outfit.locals[6][1][2]=.7",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";apply();assert(calls.writes==0)")

    def test_authored_unknown_unmarked_or_mismatched_profile_never_starts(self):
        for mutation in (
            "outfit.data.warlock_rig_profile=nil",
            "outfit.data.warlock_rig_profile='authored'",
            "outfit.data.warlock_rig_profile='unknown-profile'",
            "outfit.data.warlock_animation_manifest_id=string.rep('d',64)",
            "profile.accessory_skin='another-skin'",
            "profile.unit='units/another/body'",
            "profile.shipping_body_sha256=string.rep('e',64)",
            "profile.shipping_bones_sha256=string.rep('f',64)",
            "mod._warlock_animation_manifest.schema=2",
            "profile.native_bind_scale=1",
            "profile.reference_bone='j_spine'",
            "profile.manifest_id='invalid'",
            "profile.body_fbx_sha256='invalid'",
            "profile.rest_contract_sha256='invalid'",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime(start=False)
                lua.execute(mutation + """
                  assert(not mod._start_warlock_outfit_correction(owner,outfit))
                  apply();assert(calls.writes==0)
                """)

    def test_missing_nodes_parent_mismatch_and_cycle_fail_before_pose_reads(self):
        for mutation in (
            "outfit.nodes.j_loot_sack_component5=nil",
            "outfit.nodes.j_hips=nil",
            "outfit.parents[11]=5",
            "outfit.parents[12]=13",
            "outfit.parents[4]=5",
            "outfit.nodes.j_loot_sack_component5=10",
            "outfit.name='units/another/body'",
            "outfit.world=other_world",
            "mod._warlock_outfits[owner]=nil",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime(start=False)
                lua.execute(mutation + """
                  assert(not mod._start_warlock_outfit_correction(owner,outfit))
                  assert(calls.reads==0 and calls.writes==0)
                """)

    def test_bad_last_bind_or_channel_contract_rejects_entire_start(self):
        for mutation in (
            "channels[7].bone='j_backpack'",
            "channels[7].parent='j_spine1'",
            "channels[7].bind_offset=nil",
            "channels[7].bind_offset[1][4]=0/0",
            "channels[7].bind_offset[1][2]=.7",
            "for r=1,3 do channels[7].bind_offset[r][3]=0 end",
            "for r=1,3 do channels[7].bind_offset[r][1]=-channels[7].bind_offset[r][1] end",
            "for r=1,3 do channels[7].bind_offset[r][1]=channels[7].bind_offset[r][1]*1.1 end",
            "channels[7].bind_offset[4][1]=.1",
            "channels[7].bind_offset[1][4]=3",
            "channels[1],channels[2]=channels[2],channels[1]",
            "table.remove(channels)",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime(start=False)
                lua.execute(mutation + """
                  assert(not mod._start_warlock_outfit_correction(owner,outfit))
                  assert(calls.reads==0 and calls.writes==0)
                """)

    def test_dead_and_lost_ownership_require_explicit_matching_corpse_handoff(self):
        for mutation in (
            "HEALTH_ALIVE[owner]=nil",
            "mod._warlock_outfits[owner]=nil",
            "outfit.data.warlock_animation_manifest_id=string.rep('d',64)",
            "outfit.data.warlock_rig_profile='authored'",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";apply(true);assert(calls.writes==0)")
        lua = runtime()
        lua.execute("""
          assert(mod._handoff_warlock_outfit_correction(owner,outfit))
          HEALTH_ALIVE[owner]=nil;mod._warlock_outfits[owner]=nil
          mod._stop_warlock_outfit_correction(owner,true)
          snapshot();apply(true);assert_result();assert(calls.writes==14)
        """)

    def test_authored_or_unsupported_animation_ownership_does_not_write(self):
        for mode in ("'authored'", "'unsupported'", "nil"):
            with self.subTest(mode=mode):
                lua = runtime()
                lua.execute(f"""
                  ownership_mode={mode};apply();assert(calls.writes==0)
                  for node in pairs(allowed) do assert(not mod._warlock_outfit_correction_owns_node(owner,node)) end
                """)

    def test_handoff_cannot_authorize_a_foreign_pair_or_changed_profile(self):
        for mutation in (
            "mod._warlock_outfits[owner]=nil",
            "outfit.data.warlock_animation_manifest_id=string.rep('d',64)",
            "outfit.world=other_world",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + """
                  assert(not mod._handoff_warlock_outfit_correction(owner,outfit))
                  HEALTH_ALIVE[owner]=nil;apply(true);assert(calls.writes==0)
                """)

    def test_handoff_accepts_registered_death_before_health_flag_and_registry_cleanup(self):
        lua = runtime()
        lua.execute("""
          HEALTH_ALIVE[owner]=nil
          assert(mod._handoff_warlock_outfit_correction(owner,outfit))
          mod._warlock_outfits[owner]=nil
          snapshot();apply(true);assert_result();assert(calls.writes==14)
          assert(mod._warlock_outfit_correction_status(owner)=='active-corpse')
        """)

    def test_authorized_corpse_cannot_follow_a_replacement_registered_outfit(self):
        lua = runtime()
        lua.execute("""
          assert(mod._handoff_warlock_outfit_correction(owner,outfit))
          HEALTH_ALIVE[owner]=nil;mod._warlock_outfits[owner]=make_unit(outfit.name)
          apply(true);assert(calls.writes==0)
        """)

    def test_corpse_flag_is_required_and_preserve_stop_does_not_authorize_it(self):
        lua = runtime()
        lua.execute("""
          assert(mod._handoff_warlock_outfit_correction(owner,outfit))
          HEALTH_ALIVE[owner]=nil;mod._warlock_outfits[owner]=nil
          apply(false);assert(calls.writes==0)
        """)
        lua = runtime()
        lua.execute("""
          mod._stop_warlock_outfit_correction(owner,true)
          HEALTH_ALIVE[owner]=nil;mod._warlock_outfits[owner]=nil
          apply(true);assert(calls.writes==0)
        """)

    def test_stop_reset_and_world_release_do_not_touch_stale_handles(self):
        for cleanup in (
            "mod._stop_warlock_outfit_correction(owner)",
            "mod._reset_warlock_outfit_correction()",
            "mod._release_warlock_outfit_correction_world(world)",
        ):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute(cleanup + """
                  local touches=calls.native_touches
                  owner.alive=false;outfit.alive=false;world.alive=false
                  next_frame();apply(true)
                  assert(calls.writes==0 and calls.native_touches==touches)
                """)

    def test_corpse_stop_reset_and_release_clear_the_handed_off_entry(self):
        for cleanup in (
            "mod._stop_warlock_outfit_correction(owner)",
            "mod._reset_warlock_outfit_correction()",
            "mod._release_warlock_outfit_correction_world(world)",
        ):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute("""
                  assert(mod._handoff_warlock_outfit_correction(owner,outfit))
                  HEALTH_ALIVE[owner]=nil;mod._warlock_outfits[owner]=nil
                """ + cleanup + """
                  local touches=calls.native_touches
                  owner.alive=false;outfit.alive=false;world.alive=false
                  next_frame();apply(true)
                  assert(calls.writes==0 and calls.native_touches==touches)
                  assert(mod._warlock_outfit_correction_status(owner)=='off')
                """)

    def test_other_world_release_preserves_this_entry(self):
        lua = runtime()
        lua.execute("""
          mod._release_warlock_outfit_correction_world(other_world)
          snapshot();apply();assert_result();assert(calls.writes==14)
        """)

    def test_failed_or_authored_frame_releases_previous_node_ownership(self):
        for mutation in (
            "outfit.locals[11][1][4]=0/0",
            "ownership_mode='authored'",
            "mod._warlock_outfits[owner]=nil",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("""
                  snapshot();apply();assert_result();assert(calls.writes==14)
                """ + mutation + """
                  apply();assert(calls.writes==14)
                  for node in pairs(allowed) do assert(not mod._warlock_outfit_correction_owns_node(owner,node)) end
                """)

    def test_preflight_exception_releases_prior_ownership_before_caller_catches_it(self):
        for mutation in (
            "mod._warlock_animation_ownership=function() error('ownership unavailable') end",
            "World.update_unit=function() error('native preflight unavailable') end",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("""
                  snapshot();apply();assert_result();assert(calls.writes==14)
                """ + mutation + """
                  local ok=pcall(apply);assert(not ok and calls.writes==14)
                  for node in pairs(allowed) do assert(not mod._warlock_outfit_correction_owns_node(owner,node)) end
                """)

    def test_profile_lookup_exception_clears_previous_active_ownership(self):
        lua = runtime()
        lua.execute("""
          snapshot();apply();assert_result();assert(calls.writes==14)
          local original_get_data=Unit.get_data
          Unit.get_data=function(unit,key)
           if key=='warlock_rig_profile' then error('profile marker unavailable') end
           return original_get_data(unit,key)
          end
          local ok=pcall(mod._apply_warlock_outfit_correction,owner,outfit,false)
          assert(not ok and calls.writes==14)
          for node in pairs(allowed) do assert(not mod._warlock_outfit_correction_owns_node(owner,node)) end
        """)

    def test_dead_owner_or_outfit_is_not_read_for_pose_data(self):
        for mutation in ("owner.alive=false", "outfit.alive=false"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";apply(true);assert(calls.reads==0 and calls.writes==0)")

    def test_foreign_outfit_argument_cannot_use_registered_entry(self):
        lua = runtime()
        lua.execute("""
          local foreign=make_unit(outfit.name)
          assert(not mod._apply_warlock_outfit_correction(owner,foreign))
          assert(calls.reads==0 and calls.writes==0)
        """)

    def test_module_reload_clears_entries_and_native_boxes(self):
        lua = runtime()
        lua.execute("snapshot();apply();assert_result();next_frame()")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
          apply();assert(calls.writes==14)
          assert(mod._warlock_outfit_correction_status(owner)=='off')
          assert(mod._start_warlock_outfit_correction(owner,outfit))
          snapshot();apply();assert_result();assert(calls.writes==28)
        """)

    def test_repeated_frames_do_not_reuse_native_temporaries(self):
        lua = runtime()
        lua.execute("""
          for frame=1,5 do
           next_frame();outfit.locals[2]=keep(pose(.002,.004,.008,.1*frame,-.16,.08*frame))
           snapshot();apply();assert_result()
          end
          assert(calls.writes==70)
        """)


if __name__ == "__main__":
    unittest.main()
