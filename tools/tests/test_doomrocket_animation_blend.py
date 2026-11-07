"""Execute the corrected-pose transition compositor in Lua 5.1.

Native doubles have 138 independently changing TRS channels, zero-edge helper
events, distinct target indices, and expiring native temporaries. These test
composition/lifetimes, not engine hidden-mesh evaluation or rendered acceptance.
"""
from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_animation_blend.lua"
CLOCK = ROOT / "scripts/mods/doomrocket/utils/doomrocket_animation_clock.lua"
LOCOMOTION = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_locomotion_animation.lua"
OUTFIT_CORRECTION = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_outfit_correction.lua"
BONES = re.findall(r'"([^"\n]+)"', (ROOT / "units/warlock_bombardier/warlock_bombardier_3p.bones").read_text())

HARNESS = r'''
epoch=1;world={alive=true};other_world={alive=true}
calls={visible=0,helper_bones=0,helper_root=0,variables=0,constraints=0,spawns=0,destroys=0,native=0,structural=0,grip=0,accessories=0,events=0,warnings=0,clock=0,illegal_clock=0}
local function native(u)
 assert(u and u.alive,'native access after unit deletion')
 assert(u.world and u.world.alive,'native access after world release')
 calls.native=calls.native+1
end
function vec(x,y,z) return {x=x,y=y,z=z} end
Vector3=setmetatable({is_valid=function(v) return v and type(v.x)=='number' and type(v.y)=='number' and type(v.z)=='number'
 and v.x==v.x and v.y==v.y and v.z==v.z
 and math.abs(v.x)<math.huge and math.abs(v.y)<math.huge and math.abs(v.z)<math.huge end},
 {__call=function(_,x,y,z) return vec(x,y,z) end})
Quaternion={to_elements=function(q) return q.x,q.y,q.z,q.w end,
 from_elements=function(x,y,z,w) return {x=x,y=y,z=z,w=w} end}
Matrix4x4={is_valid=function(m) return m and m.matrix==true end,
 x=function(m) return m.axes[1] end,y=function(m) return m.axes[2] end,z=function(m) return m.axes[3] end,
 translation=function(m) return m.translation end}
function q(angle,sign)
 local s=sign or 1;return Quaternion.from_elements(0,0,math.sin(angle/2)*s,math.cos(angle/2)*s)
end
local function temporary(v)
 local created=epoch
 return setmetatable({},{__index=function(_,key)
  assert(created==epoch,'retained native temporary');return v[key]
 end})
end
function unit(kind)
 local u={alive=true,kind=kind,world=world,locals={},nodes={},parents={},time=0,length=2,state='idle',
  position=vec(0,0,0),speed=0,data={warlock_animation_manifest_id=string.rep('a',64)}}
 for i=0,138 do u.locals[i]={p=vec(i*.01,.2,.3),r=q(0),s=vec(1,1,1)};u.parents[i]=i==0 and -1 or 0 end
 for i,name in ipairs(bone_names) do u.nodes[name]=i end
 return u
end
owner=unit('owner');outfit=unit('outfit');owner.aim_index=7;outfit.aim_index=3
owner.aim=vec(5,7,9)
mod={_warlock_outfits={[owner]=outfit}}
mod.warning=function(self,format,...)
 assert(self==mod);calls.warnings=calls.warnings+1;calls.warning=string.format(format,...)
end
HEALTH_ALIVE={[owner]=true}
function get_mod() return mod end
Application={can_get=function(kind,name)
 assert(kind=='state_machine' and name==profile.sampler_state_machine)
 return not unloaded_sampler
end}
profile={unit='units/warlock_bombardier/warlock_bombardier_3p',manifest_id=string.rep('a',64),accessory_skin='localized-v1',
 cross_owner_transition_policy='snapshot-blend-v1',sampler_state_machine='units/warlock_bombardier/warlock_bombardier_3p/presentation_sampler',
 bone_names=bone_names,default_state='idle',states={}}
for _,name in ipairs({'idle','legacy2','authored','authored2','walk','run'}) do
 profile.states[name]={owner=(name=='authored' or name=='authored2') and 'authored' or 'legacy',
  clip=name,visible_aim=name~='authored' and name~='authored2',loop_animation=name~='authored2',
  speed_expression=name=='walk' and 'warlock_move_speed / 1.9' or name=='run' and 'warlock_move_speed / 4' or '1',transitions={}}
 for _,to in ipairs({'idle','legacy2','authored','authored2','walk','run'}) do
  profile.states[name].transitions[to]={to=to,blend_time=.25}
 end
end
Unit={
 alive=function(u) return u and u.alive or false end,
 world=function(u) native(u);return u.world end,
 get_data=function(u,key) native(u);return key=='unit_name' and profile.unit or u.data[key] end,
 has_node=function(u,name) native(u);calls.structural=calls.structural+1;return u.nodes[name]~=nil end,
 node=function(u,name) native(u);calls.structural=calls.structural+1;assert(u.nodes[name]~=nil);return u.nodes[name] end,
 scene_graph_parent=function(u,node) native(u);calls.structural=calls.structural+1;return u.parents[node] end,
 local_position=function(u,node) native(u);return temporary(u.locals[node].p) end,
 local_rotation=function(u,node) native(u);return temporary(u.locals[node].r) end,
 local_scale=function(u,node) native(u);return temporary(u.locals[node].s) end,
 world_position=function(u,node) native(u);assert(u==owner and node==0);return temporary(u.position) end,
 num_meshes=function(u) native(u);return 3 end,
 set_mesh_visibility=function(u,index,visible,group)
  native(u);assert(u==helper and index>=0 and index<3 and not visible and (group=='default' or group=='shadow_caster'))
  u.hidden_meshes=u.hidden_meshes or {};u.hidden_meshes[group]=(u.hidden_meshes[group] or 0)+1
 end,
 set_unit_visibility=function() error('whole-unit hiding can stop helper evaluation') end,
 set_animation_state_machine=function(u,asm)
  native(u);assert(u==helper and asm==profile.sampler_state_machine);u.sampler=asm
 end,
 enable_animation_state_machine=function(u) native(u);assert(u==helper);u.enabled=true end,
 set_animation_bone_mode=function(u,mode) native(u);assert(u==helper and mode=='transform') end,
 set_animation_root_mode=function(u,mode) native(u);assert(u==helper and mode=='ignore') end,
 set_bones_lod=function(u,index) native(u);assert(u==helper and index==0) end,
 animation_has_variable=function(u,name) native(u);assert((u==helper or u==outfit) and name=='warlock_move_speed');return true end,
 animation_find_variable=function(u,name) native(u);assert((u==helper or u==outfit) and name=='warlock_move_speed');return u==helper and 83 or 41 end,
 animation_set_variable=function(u,index,value)
  native(u);assert((u==helper and index==83) or (u==outfit and index==41));u.speed=value;calls.variables=calls.variables+1
 end,
 animation_has_constraint_target=function(u,name) native(u);assert(name=='aim_target');return true end,
 animation_find_constraint_target=function(u,name) native(u);assert(name=='aim_target');return u.aim_index end,
 animation_get_constraint_target=function(u,index)
  native(u);assert(u==owner and index==7);if broken_aim then error('native aim unavailable') end;return temporary(u.aim)
 end,
 animation_set_constraint_target=function(u,index,value)
  native(u);assert(u==helper and index==19);calls.constraints=calls.constraints+1
  if value.matrix then
   assert(Matrix4x4.is_valid(value));u.aim_matrix=true;u.aim=vec(value.translation.x,value.translation.y,value.translation.z)
  else assert(Vector3.is_valid(value));u.aim=vec(value.x,value.y,value.z) end
 end,
 has_animation_event=function(u,event) native(u);return not missing_event and profile.states[event]~=nil end,
 has_animation_state_machine=function(u) native(u);return not u.no_asm end,
 animation_get_state=function(u)
  native(u)
  if u.no_layers then return end
  if u.empty_layer then return nil end
  if u.two_layers then return 17,23 end
  return 17
 end,
 animation_event=function(u,event)
  native(u);if broken_event and u==helper then error('native event unavailable') end
  assert(profile.states[event]);u.state=event;u.time=0;calls.events=calls.events+1
 end,
 animation_layer_info=function(u,index)
  calls.clock=calls.clock+1
  if not u or not u.alive or u.no_asm or u.no_layers or u.empty_layer or u.two_layers or index~=0 then
   calls.illegal_clock=calls.illegal_clock+1;error('native layer precondition violated')
  end
  native(u);assert(u==helper or u==outfit)
  if broken_clock then error('native clock unavailable') end
  return u.time,u.length
 end,
}
local function setter(u,node)
 native(u);assert(u~=owner,'compositor wrote carrier')
 if u==outfit then assert(node~=0,'compositor overwrote external wrapper root');calls.visible=calls.visible+1
 elseif node~=0 then calls.helper_bones=calls.helper_bones+1
 else calls.helper_root=calls.helper_root+1 end
end
Unit.set_local_position=function(u,node,value) setter(u,node);assert(Vector3.is_valid(value));u.locals[node].p=vec(value.x,value.y,value.z) end
Unit.set_local_rotation=function(u,node,value) setter(u,node);u.locals[node].r=Quaternion.from_elements(value.x,value.y,value.z,value.w) end
Unit.set_local_scale=function(u,node,value)
 setter(u,node);assert(Vector3.is_valid(value) and value.x>0 and value.y>0 and value.z>0)
 u.locals[node].s=vec(value.x,value.y,value.z)
end
World={
 spawn_unit=function(w,name)
  assert(w.alive and w==world and name==profile.unit)
  calls.spawns=calls.spawns+1;helper=unit('helper');helper.aim_index=19;return helper
 end,
 destroy_unit=function(w,u)
  native(u);assert(w==u.world and u==helper);if broken_destroy then error('native cleanup unavailable') end
  calls.destroys=calls.destroys+1;u.alive=false
 end,
 link_unit=function(w,u,node,parent,source)
  native(u);native(parent)
  assert(w==world and u==helper and node==0 and parent==owner and source==owner.nodes.root_point)
  if broken_link then error('native link unavailable') end
  u.linked=true;u.link_parent=parent;u.link_source=source
 end,
 update_unit=function(w,u) native(u);assert(w==u.world) end,
}
function mod._prepare_warlock_legacy_grip_pose(owner_unit,sampler,token)
 calls.grip=calls.grip+1;assert(mod._warlock_transition_helper_valid(owner_unit,sampler,nil,token))
 if bad_grip then return nil,'bad_grip' end
 local result={}
 for i=1,12 do result[i]={node=i,position=vec(100+i,2,3),rotation=q(.2)} end
 return result
end
function mod._prepare_warlock_legacy_outfit_pose(owner_unit,sampler,p,grip,token)
 calls.accessories=calls.accessories+1;assert(mod._warlock_transition_helper_valid(owner_unit,sampler,p,token))
 assert(#grip==12 and sampler.locals[1].p.x~=101,'grip applied before accessory preflight')
 if bad_accessories then return nil,'bad_accessories' end
 local result={}
 for i=13,19 do result[#result+1]={node=i,position=vec(200+i,2,3),rotation=q(.4)} end
 if duplicate then result[7].node=1 end
 if invalid_candidate then result[7].position.x=0/0 end
 return result
end
function engine(dt)
 epoch=epoch+1
 if not helper or not helper.alive then return end
 local state=profile.states[helper.state]
 local rate=state.speed_expression=='warlock_move_speed / 1.9' and helper.speed/1.9
  or state.speed_expression=='warlock_move_speed / 4' and helper.speed/4 or 1
 if not frozen_helper then
  local time=helper.time+dt*rate
  helper.time=state.loop_animation and time%helper.length or math.min(helper.length,time)
 end
 local visible_state=profile.states[outfit.state]
 local visible_rate=visible_state.speed_expression=='warlock_move_speed / 1.9' and outfit.speed/1.9
  or visible_state.speed_expression=='warlock_move_speed / 4' and outfit.speed/4 or 1
 local visible_time=outfit.time+dt*visible_rate
 outfit.time=visible_state.loop_animation and visible_time%outfit.length or math.min(outfit.length,visible_time)
 for i=1,138 do
  helper.locals[i]={p=vec(10+i*.01,1,2),r=q(math.pi/2,negative_quaternion and -1 or 1),s=vec(1.4,.6,1.2)}
 end
end
function frame(dt,w)
 if mod._update_warlock_locomotion_animation then mod._update_warlock_locomotion_animation(w or world,dt) end
 mod._update_warlock_animation_blend(w or world,dt)
 if not w or w==world then engine(dt) end
 return mod._apply_warlock_animation_blend(owner,outfit)
end
function begin()
 assert(mod._start_warlock_animation_blend(owner,outfit,profile));assert(not frame(0))
end
function change(to,duration)
 duration=duration or .25
 local from=helper.state
 assert(mod._note_warlock_animation_blend_event(owner,to,from,to,duration))
 Unit.animation_event(outfit,to)
end
function active() return mod._warlock_animation_blend_active(owner) end
function status() return mod._warlock_animation_blend_status(owner) end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().bone_names = lua.table_from(BONES)
    lua.execute(HARNESS)
    lua.globals().mod._warlock_animation_clock = lua.execute(CLOCK.read_text(encoding="utf-8"))
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


class AnimationBlendTests(unittest.TestCase):
    def test_unready_sampler_layer_blocks_before_native_query_or_visible_writes(self):
        for mutation in ("helper.no_asm=true", "helper.no_layers=true", "helper.empty_layer=true",
                         "helper.two_layers=true", "Unit.animation_get_state=nil",
                         "mod._warlock_animation_clock=nil"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');mod._update_warlock_animation_blend(world,.1);engine(.1);"
                            "local clocks=calls.clock;" + mutation + ";"
                            "assert(not mod._apply_warlock_animation_blend(owner,outfit));"
                            "assert(calls.clock==clocks and calls.illegal_clock==0 and calls.visible==0);"
                            "assert(status()=='invalid_sampler_clock' and active())")

    def test_unready_visible_layer_retains_guard_without_attempting_its_native_query(self):
        for mutation in ("outfit.no_asm=true", "outfit.no_layers=true", "outfit.empty_layer=true",
                         "outfit.two_layers=true"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');mod._update_warlock_animation_blend(world,.25);engine(.25);"
                            "local clocks=calls.clock;" + mutation + ";"
                            "assert(not mod._apply_warlock_animation_blend(owner,outfit));"
                            # The helper clock is valid; the visible query is forbidden.
                            "assert(calls.clock==clocks+1 and calls.illegal_clock==0 and calls.visible==0);"
                            "assert(status()=='invalid_visible_clock' and active())")

    def test_finite_native_sentinel_blocks_sampler_and_visible_release(self):
        for unit, status in (("helper", "invalid_sampler_clock"), ("outfit", "invalid_visible_clock")):
            with self.subTest(unit=unit):
                lua = runtime()
                lua.execute("begin();change('authored');mod._update_warlock_animation_blend(world,.25);engine(.25);"
                            + unit + ".length=1e37;assert(not mod._apply_warlock_animation_blend(owner,outfit));"
                            "assert(calls.visible==0 and calls.illegal_clock==0 and active());"
                            "assert(status()=='" + status + "');"
                            "assert(calls.warning:find('clock_read_reason=invalid_clock',1,true))")

    def test_helper_uses_own_rig_hidden_meshes_named_indices_and_root_only_link(self):
        lua = runtime()
        lua.execute("begin();assert(helper.hidden_meshes.default==3 and helper.hidden_meshes.shadow_caster==3 and helper.enabled and helper.linked);assert(calls.visible==0)")
        lua.execute("frame(.1);assert(helper.aim.x==5 and helper.aim.y==7 and helper.aim.z==9)")

    def test_helper_shares_visible_carrier_parent_and_copies_only_its_wrapper_trs(self):
        lua = runtime()
        lua.execute('''
          -- A named carrier root may have a different index/frame from node
          -- zero. Visible outfit attachment already uses this named parent.
          owner.nodes.root_point=321
          outfit.locals[0]={p=vec(.7,-.8,.9),r=q(.4),s=vec(1.2,.8,.5)}
          begin();frame(.1)
          assert(helper.link_parent==owner and helper.link_source==321)
          assert(helper.locals[0].p.x==.7 and helper.locals[0].p.y==-.8 and helper.locals[0].p.z==.9)
          assert(helper.locals[0].r.z==outfit.locals[0].r.z and helper.locals[0].r.w==outfit.locals[0].r.w)
          assert(helper.locals[0].s.x==1.2 and helper.locals[0].s.y==.8 and helper.locals[0].s.z==.5)
          assert(calls.visible==0 and calls.helper_bones==0)
        ''')

    def test_named_carrier_root_may_resolve_to_zero(self):
        lua = runtime()
        lua.execute("owner.nodes.root_point=0;begin();assert(helper.link_source==0 and calls.spawns==1)")

    def test_missing_carrier_root_is_rejected_before_unsafe_lookup_or_spawn(self):
        lua = runtime()
        lua.execute('''
          owner.nodes.root_point=nil
          local query=Unit.node;local missing_queries=0
          Unit.node=function(u,name)
            if u==owner and name=='root_point' then missing_queries=missing_queries+1 end
            return query(u,name)
          end
          assert(not mod._start_warlock_animation_blend(owner,outfit,profile))
          assert(missing_queries==0 and calls.spawns==0 and status()=='off')
        ''')

    def test_invalid_carrier_root_index_is_rejected_before_spawn(self):
        for expression in ("-1", ".5", "0/0", "math.huge", "'1'", "{}"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute("owner.nodes.root_point=" + expression)
                lua.execute("assert(not mod._start_warlock_animation_blend(owner,outfit,profile));assert(calls.spawns==0 and status()=='off')")

    def test_failed_native_parent_link_destroys_helper_without_leaving_an_entry(self):
        lua = runtime()
        lua.execute('''
          broken_link=true
          assert(not mod._start_warlock_animation_blend(owner,outfit,profile))
          assert(calls.spawns==1 and calls.destroys==1 and not helper.alive and status()=='off')
          mod._reset_warlock_animation_blend();assert(calls.destroys==1)
        ''')

    def test_all_138_trs_mix_from_corrected_displayed_pose_to_moving_authored_target(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');assert(active());assert(frame(.125))
          assert(calls.visible==138*3 and calls.grip==0 and calls.accessories==0 and calls.helper_bones==0)
          for i=1,138 do
           local p=outfit.locals[i]
           assert(math.abs(p.p.x-(5+i*.01))<1e-10)
           assert(math.abs(p.s.x-1.2)<1e-10 and math.abs(p.s.y-.8)<1e-10)
           assert(math.abs(p.r.z-math.sin(math.pi/8))<1e-10)
           assert(math.abs(p.r.w-math.cos(math.pi/8))<1e-10)
          end
        ''')

    def test_antipodal_quaternions_use_shortest_normalized_rotation(self):
        lua = runtime()
        lua.execute('''
          negative_quaternion=true;begin();change('authored');frame(.125)
          local r=outfit.locals[138].r
          assert(math.abs(r.z-math.sin(math.pi/8))<1e-10)
          assert(math.abs(r.z*r.z+r.w*r.w-1)<1e-10)
        ''')

    def test_outgoing_corrected_pose_is_frozen_and_target_continues_moving(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.05)
          local first=outfit.locals[138].p.x
          helper.locals[138].p.x=999
          frame(.05)
          assert(math.abs(first-(2+1.38))<1e-10)
          assert(math.abs(outfit.locals[138].p.x-(4+1.38))<1e-10)
        ''')

    def test_legacy_target_preflights_both_groups_and_corrects_only_19_helper_channels(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.25);assert(not active())
          change('idle');assert(frame(.125))
          assert(calls.grip==1 and calls.accessories==1 and calls.helper_bones==19*2)
          assert(math.abs(outfit.locals[1].p.x-(.01+101)/2)<1e-10)
          assert(math.abs(outfit.locals[13].p.x-(.13+213)/2)<1e-10)
          assert(math.abs(outfit.locals[20].p.x-(.2+10.2)/2)<1e-10)
        ''')

    def test_stock_body_return_to_legacy_needs_no_outfit_correction_registration(self):
        lua = runtime()
        lua.execute(OUTFIT_CORRECTION.read_text(encoding="utf-8"))
        lua.execute('''
          profile.accessory_skin=nil
          assert(not mod._start_warlock_outfit_correction(owner,outfit))
          local builder=mod._prepare_warlock_legacy_outfit_pose
          mod._prepare_warlock_legacy_outfit_pose=function(...)
            calls.accessories=calls.accessories+1;return builder(...)
          end
          begin();change('authored');frame(.25);change('idle')
          local candidate,reason=builder(owner,helper,profile,{})
          assert(candidate==nil and reason=='inactive_helper')
          calls.structural=0;assert(frame(.125))
          assert(calls.grip==1 and calls.accessories==0 and calls.helper_bones==12*2)
          assert(calls.structural==2*138*6 and calls.visible==138*3 and calls.warnings==0)
          assert(math.abs(outfit.locals[1].p.x-(.01+101)/2)<1e-10)
          assert(math.abs(outfit.locals[13].p.x-(.13+10.13)/2)<1e-10)
          local writes=calls.helper_bones;assert(not frame(.125))
          assert(not active() and status()=='native' and calls.helper_bones==writes)
        ''')

    def test_stock_body_interruption_returns_to_authored_without_legacy_pose_writes(self):
        lua = runtime()
        lua.execute('''
          profile.accessory_skin=nil
          mod._prepare_warlock_legacy_outfit_pose=function() error('stock profile has no outfit registration') end
          begin();change('authored');assert(frame(.1))
          assert(calls.grip==0 and calls.accessories==0 and calls.helper_bones==0)
          change('idle');assert(frame(.05));assert(calls.helper_bones==24)
          local shown=outfit.locals[138].p.x
          local writes=calls.helper_bones;change('authored');assert(frame(0))
          assert(outfit.locals[138].p.x==shown and calls.helper_bones==writes)
          assert(frame(.1) and calls.helper_bones==writes and calls.grip==1 and calls.warnings==0)
        ''')

    def test_stock_body_grip_builder_keeps_full_precommit_guards(self):
        for mutation, expected in (
            ("helper.parents[138]=1", "changed_skeleton"),
            ("outfit.parents[138]=1", "changed_skeleton"),
            ("HEALTH_ALIVE[owner]=false", "off"),
            ("mod._warlock_outfits[owner]=nil", "off"),
            ("helper.world=other_world", "missing_sampler"),
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("profile.accessory_skin=nil;begin();change('authored');frame(.25);change('idle')")
                lua.execute('''
                  local builder=mod._prepare_warlock_legacy_grip_pose
                  mod._prepare_warlock_legacy_grip_pose=function(...)
                    local candidate,reason=builder(...)
                    MUTATION
                    return candidate,reason
                  end
                  assert(not frame(.1) and status()==EXPECTED)
                  assert(calls.helper_bones==0 and calls.visible==0 and calls.accessories==0)
                '''.replace("MUTATION", mutation).replace("EXPECTED", repr(expected)))

    def test_unknown_accessory_profile_is_rejected_before_helper_spawn(self):
        for value in ("'unknown'", "false", "true", "7", "{}"):
            with self.subTest(value=value):
                lua = runtime()
                lua.execute("profile.accessory_skin=" + value)
                lua.execute("assert(not mod._start_warlock_animation_blend(owner,outfit,profile));assert(calls.spawns==0 and status()=='off')")

    def test_stock_profile_does_not_bypass_other_manifest_checks(self):
        for mutation in (
            "profile.manifest_id='bad'",
            "profile.states.idle.owner='unknown'",
            "profile.states.idle.loop_animation='true'",
            "profile.states.idle.speed_expression='untrusted_expression'",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("profile.accessory_skin=nil;" + mutation)
                lua.execute("assert(not mod._start_warlock_animation_blend(owner,outfit,profile));assert(calls.spawns==0 and status()=='off')")

    def test_skin_profile_change_inside_grip_builder_cannot_commit_partial_pose(self):
        for original, replacement in (("nil", "'localized-v1'"), ("'localized-v1'", "nil"),
                                      ("nil", "'unknown'"), ("'localized-v1'", "'unknown'")):
            with self.subTest(original=original, replacement=replacement):
                lua = runtime()
                lua.execute("profile.accessory_skin=" + original + ";begin();change('authored');frame(.25);change('idle')")
                lua.execute('''
                  local builder=mod._prepare_warlock_legacy_grip_pose
                  mod._prepare_warlock_legacy_grip_pose=function(...)
                    local rows,reason=builder(...);profile.accessory_skin=REPLACEMENT;return rows,reason
                  end
                  assert(not frame(.1) and status()=='invalid_accessory_profile')
                  assert(calls.helper_bones==0 and calls.visible==0 and active())
                '''.replace("REPLACEMENT", replacement))

    def test_localized_profile_requires_exactly_seven_outfit_candidates(self):
        for mutation in (
            "mod._prepare_warlock_legacy_outfit_pose=nil",
            "mod._prepare_warlock_legacy_outfit_pose=function() return {} end",
            "local builder=mod._prepare_warlock_legacy_outfit_pose;mod._prepare_warlock_legacy_outfit_pose=function(...) local rows=builder(...);rows[7]=nil;return rows end",
            "local builder=mod._prepare_warlock_legacy_outfit_pose;mod._prepare_warlock_legacy_outfit_pose=function(...) local rows=builder(...);rows[8]=rows[7];return rows end",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');frame(.25);change('idle');" + mutation)
                lua.execute("assert(not frame(.1));assert(active() and calls.helper_bones==0 and calls.visible==0)")

    def test_legacy_apply_keeps_entry_and_precommit_sweeps_and_expires_its_token(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.25);change('idle')
          local prepare=mod._prepare_warlock_legacy_grip_pose
          mod._prepare_warlock_legacy_grip_pose=function(o,h,token)
            saved_token=token;return prepare(o,h,token)
          end
          calls.structural=0;assert(frame(.1))
          assert(calls.structural==2*138*6 and calls.helper_bones==38 and calls.visible==414)
          local checks=calls.structural
          assert(not mod._warlock_transition_helper_valid(owner,helper,profile,saved_token))
          assert(calls.structural==checks and status()=='blending')
          assert(mod._warlock_transition_helper_valid(owner,helper,profile))
          assert(calls.structural==checks+138*6)
          for _,foreign in ipairs({{},true,17,'token'}) do
            assert(not mod._warlock_transition_helper_valid(owner,helper,profile,foreign))
          end
          helper.parents[138]=1
          assert(not mod._warlock_transition_helper_valid(owner,helper,profile))
        ''')

    def test_steady_and_authored_apply_still_validate_all_138_bones(self):
        lua = runtime()
        lua.execute('''
          begin();calls.structural=0;assert(not frame(.1));assert(calls.structural==138*6)
          change('authored');calls.structural=0;assert(frame(.1))
          assert(calls.structural==138*6 and calls.helper_bones==0)
        ''')

    def test_graph_mutation_after_either_builder_latches_before_any_pose_setter(self):
        for stage in ("grip", "outfit"):
            for mutation in ("helper.parents[138]=1", "outfit.parents[138]=1",
                             "helper.nodes[bone_names[138]]=137", "outfit.nodes[bone_names[138]]=137"):
                with self.subTest(stage=stage, mutation=mutation):
                    lua = runtime()
                    lua.execute("begin();change('authored');frame(.25);change('idle')")
                    lua.execute('''
                      local name=STAGE=='grip' and '_prepare_warlock_legacy_grip_pose' or '_prepare_warlock_legacy_outfit_pose'
                      local prepare=mod[name]
                      mod[name]=function(...)
                        local result,reason=prepare(...)
                        MUTATION
                        return result,reason
                      end
                      assert(not frame(.1));assert(active() and status()=='changed_skeleton')
                      assert(calls.visible==0 and calls.helper_bones==0 and calls.warnings==1)
                      helper.parents[138]=0;outfit.parents[138]=0
                      helper.nodes[bone_names[138]]=138;outfit.nodes[bone_names[138]]=138
                      assert(not frame(.1) and status()=='changed_skeleton')
                      assert(calls.visible==0 and calls.helper_bones==0 and calls.warnings==1)
                    '''.replace("STAGE", repr(stage)).replace("MUTATION", mutation))

    def test_changed_graph_after_a_successful_legacy_frame_still_fails_closed(self):
        for mutation in ("helper.parents[138]=1", "helper.nodes[bone_names[138]]=137"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');frame(.25);change('idle');assert(frame(.05));" + mutation)
                lua.execute('''
                  local visible,bones=calls.visible,calls.helper_bones
                  assert(not frame(.05) and status()=='changed_skeleton' and active())
                  assert(calls.visible==visible and calls.helper_bones==bones)
                ''')

    def test_event_between_builders_invalidates_old_token_and_keeps_new_custom_pose(self):
        for stage in ("grip", "outfit"):
            with self.subTest(stage=stage):
                lua = runtime()
                lua.execute("begin();change('authored');frame(.25);change('idle')")
                lua.execute('''
                  local name=STAGE=='grip' and '_prepare_warlock_legacy_grip_pose' or '_prepare_warlock_legacy_outfit_pose'
                  local prepare=mod[name]
                  mod[name]=function(...)
                    local result,reason=prepare(...)
                    change('authored')
                    return result,reason
                  end
                  assert(not frame(.1));assert(active() and status()=='blending' and helper.state=='authored')
                  assert(calls.visible==0 and calls.helper_bones==0 and calls.warnings==0)
                  -- The valid replacement transition may still present its
                  -- zero-weight source in this same frame, without legacy writes.
                  assert(mod._apply_warlock_animation_blend(owner,outfit))
                  assert(calls.visible==414 and calls.helper_bones==0)
                  assert(frame(.1));assert(calls.helper_bones==0 and calls.warnings==0)
                '''.replace("STAGE", repr(stage)))

    def test_reentrant_apply_revokes_outer_builder_scope_without_pose_writes(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.25);change('idle')
          local prepare=mod._prepare_warlock_legacy_grip_pose
          mod._prepare_warlock_legacy_grip_pose=function(o,h,token)
            saved_token=token;local result=prepare(o,h,token)
            assert(not mod._apply_warlock_animation_blend(owner,outfit))
            return result
          end
          assert(not frame(.1));assert(calls.visible==0 and calls.helper_bones==0)
          assert(not mod._warlock_transition_helper_valid(owner,helper,profile,saved_token))
          mod._prepare_warlock_legacy_grip_pose=prepare
          assert(frame(.05));assert(calls.visible==414 and calls.helper_bones==38 and calls.warnings==0)
        ''')

    def test_builder_exception_revokes_scope_and_latches_failure_without_pose_writes(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.25);change('idle')
          mod._prepare_warlock_legacy_grip_pose=function(o,h,token)
            saved_token=token
            assert(mod._warlock_transition_helper_valid(o,h,nil,token))
            error('builder failed')
          end
          assert(not frame(.1));assert(status()=='sampler_api_error' and active())
          assert(calls.visible==0 and calls.helper_bones==0 and calls.warnings==1)
          assert(not mod._warlock_transition_helper_valid(owner,helper,profile,saved_token))
          assert(not frame(.05));assert(calls.visible==0 and calls.helper_bones==0 and calls.warnings==1)
        ''')

    def test_precommit_keeps_health_binding_world_and_manifest_guards(self):
        for mutation, expected in (
            ("HEALTH_ALIVE[owner]=false", "off"),
            ("owner.alive=false", "off"),
            ("outfit.alive=false", "off"),
            ("owner.world=other_world", "off"),
            ("mod._warlock_outfits[owner]=nil", "off"),
            ("outfit.data.warlock_animation_manifest_id='wrong'", "off"),
            ("helper.alive=false", "missing_sampler"),
            ("helper.world=other_world", "missing_sampler"),
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');frame(.25);change('idle')")
                lua.execute('''
                  local prepare=mod._prepare_warlock_legacy_outfit_pose
                  mod._prepare_warlock_legacy_outfit_pose=function(...)
                    local result,reason=prepare(...)
                    MUTATION
                    return result,reason
                  end
                  assert(not frame(.1));assert(status()==EXPECTED)
                  assert(calls.visible==0 and calls.helper_bones==0)
                '''.replace("MUTATION", mutation).replace("EXPECTED", repr(expected)))

    def test_teardown_or_frame_advance_inside_builder_revokes_scope(self):
        for action in ("mod._stop_warlock_animation_blend(owner)",
                       "mod._reset_warlock_animation_blend()",
                       "mod._release_warlock_animation_blend_world(world)",
                       "mod._update_warlock_animation_blend(world,.01)"):
            with self.subTest(action=action):
                lua = runtime()
                lua.execute("begin();change('authored');frame(.25);change('idle')")
                lua.execute('''
                  local prepare=mod._prepare_warlock_legacy_grip_pose
                  mod._prepare_warlock_legacy_grip_pose=function(o,h,token)
                    saved_token=token;local result=prepare(o,h,token)
                    ACTION
                    return result
                  end
                  assert(not frame(.1));assert(calls.visible==0 and calls.helper_bones==0)
                  assert(not mod._warlock_transition_helper_valid(owner,helper,profile,saved_token))
                '''.replace("ACTION", action))

    def test_failed_legacy_preflight_cannot_partly_correct_helper_or_visible_pose(self):
        for mutation in ("bad_grip=true", "bad_accessories=true", "duplicate=true", "invalid_candidate=true"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');frame(.25);change('idle');" + mutation)
                lua.execute("assert(not frame(.1));assert(calls.helper_bones==0 and calls.visible==0 and active())")

    def test_ordinary_same_owner_edges_preserve_native_blends_without_compositor_writes(self):
        lua = runtime()
        lua.execute('''
          begin();change('legacy2');frame(.1);assert(not active() and calls.visible==0)
          change('authored');frame(.25);change('authored2');frame(.1)
          assert(not active() and calls.visible==0 and calls.helper_bones==0)
        ''')

    def test_interruption_snapshots_last_displayed_blend_and_restarts_continuously(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.1)
          local displayed=outfit.locals[138].p.x
          -- Native evaluation may have replaced locals between callbacks; the
          -- outgoing transition is the compositor's last actual displayed pose.
          outfit.locals[138].p.x=-999
          change('idle');assert(frame(0))
          assert(outfit.locals[138].p.x==displayed)
          change('authored');assert(frame(0));assert(outfit.locals[138].p.x==displayed)
          frame(.125);assert(math.abs(outfit.locals[138].p.x-(displayed+11.38)/2)<1e-10)
        ''')

    def test_same_frame_interruption_before_first_apply_uses_original_snapshot(self):
        lua = runtime()
        lua.execute("begin();change('authored');change('idle');assert(frame(0));assert(math.abs(outfit.locals[138].p.x-1.38)<1e-10)")

    def test_same_owner_event_during_active_crossing_restarts_from_displayed_pose(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(.1);local shown=outfit.locals[138].p.x
          change('authored2');assert(frame(0));assert(active() and outfit.locals[138].p.x==shown)
          assert(frame(.125));assert(math.abs(outfit.locals[138].p.x-(shown+11.38)/2)<1e-10)
          assert(not frame(.125));assert(not active() and calls.grip==0 and calls.accessories==0)
        ''')

    def test_completed_transition_releases_writer_without_an_extra_frame(self):
        lua = runtime()
        lua.execute("begin();change('authored');frame(.125);local writes=calls.visible;assert(not frame(.125));assert(not active() and calls.visible==writes)")

    def test_repeated_apply_in_same_animation_frame_cannot_double_write_or_advance(self):
        lua = runtime()
        lua.execute("begin();change('authored');frame(.1);local writes=calls.visible;assert(mod._apply_warlock_animation_blend(owner,outfit));assert(calls.visible==writes)")

    def test_helper_speed_uses_owner_displacement_and_actual_walk_expression(self):
        lua = runtime()
        lua.execute('''
          begin();change('walk');frame(.1)
          owner.position.x=.19;frame(.1)
          assert(math.abs(helper.speed-1.9)<1e-10 and math.abs(helper.time-.1)<1e-10)
          assert(calls.visible==0)
        ''')

    def test_hidden_helper_clock_stall_and_invalid_clock_fail_closed(self):
        for mutation in ("frozen_helper=true", "broken_clock=true", "helper.time=0/0", "helper.length=0"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');" + mutation)
                lua.execute("assert(not frame(.1));assert(active() and calls.visible==0)")

    def test_clock_failure_rearms_on_next_valid_edge_but_structural_failure_stays_latched(self):
        lua = runtime()
        lua.execute("""
          begin();change('authored');frozen_helper=true
          assert(not frame(.1));assert(active())
          local reason=status();assert(reason=='stale_sampler_clock' or reason=='invalid_sampler_clock',reason)
          frozen_helper=false;change('idle')
          assert(frame(.1) and active() and status()=='blending')
          frame(.25);assert(not active() and status()=='native')
        """)
        lua = runtime()
        lua.execute("""
          begin();change('authored');helper.alive=false
          assert(not frame(.1));assert(active() and status()=='missing_sampler')
          assert(not mod._note_warlock_animation_blend_event(owner,'idle','authored','idle',.25))
        """)

    def test_terminal_nonloop_clock_is_allowed_to_stop(self):
        lua = runtime()
        lua.execute("begin();change('authored');frame(.25);change('authored2');helper.length=.1;frame(.1);frame(.1);assert(not active() and status()=='native')")

    def test_pause_and_unrelated_world_cannot_consume_transition_duration(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');frame(0);local p=outfit.locals[138].p.x
          mod._update_warlock_animation_blend(other_world,.25)
          assert(mod._apply_warlock_animation_blend(owner,outfit));assert(outfit.locals[138].p.x==p and active())
          frame(.249999);assert(active());frame(.0000011);assert(not active())
        ''')

    def test_invalid_dt_latches_failure_without_releasing_legacy_writers(self):
        for expression in ("nil", "-1", "0/0", "math.huge", "'0.1'"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute("begin();change('authored');mod._update_warlock_animation_blend(world," + expression + ")")
                lua.execute("assert(active() and status()=='invalid_animation_dt');assert(not mod._apply_warlock_animation_blend(owner,outfit));assert(calls.visible==0)")

    def test_finite_hitch_recovers_steady_state_and_allows_future_transitions(self):
        lua = runtime()
        lua.execute('''
          begin();change('walk');owner.position.x=.19;frame(.1)
          assert(helper.speed==0);owner.position.x=2;assert(not frame(1));assert(not active())
          assert(helper.speed==0 and status()=='native' and calls.warnings==0)
          owner.position.x=2.19;frame(.1);assert(helper.speed==0)
          owner.position.x=2.38;frame(.1);assert(math.abs(helper.speed-1.9)<1e-10)
          change('authored');assert(frame(.1));assert(active())
        ''')

    def test_finite_hitch_completes_active_bridge_without_extra_pose_writer_frame(self):
        lua = runtime()
        lua.execute('''
          begin();change('authored');assert(frame(.1));local writes=calls.visible
          assert(not frame(1));assert(not active() and status()=='native' and calls.visible==writes)
          change('idle');assert(frame(.1));assert(active() and calls.warnings==0)
        ''')

    def test_first_moving_frame_and_hitch_use_same_speed_as_actual_visible_locomotion(self):
        lua = runtime()
        lua.execute("mod._warlock_animation_ownership=function() return {speed='measured'} end")
        lua.execute(LOCOMOTION.read_text(encoding="utf-8"))
        lua.execute('''
          assert(mod._start_warlock_animation_blend(owner,outfit,profile))
          assert(mod._start_warlock_locomotion_animation(owner,outfit));change('walk')
          owner.position.x=.19;frame(.1)
          assert(math.abs(helper.speed-1.9)<1e-10 and helper.speed==outfit.speed)
          assert(math.abs(helper.time-outfit.time)<1e-10)
          owner.position.x=2.09;frame(1);assert(helper.speed==0 and outfit.speed==0)
          owner.position.x=2.28;frame(.1);assert(helper.speed==0 and outfit.speed==0)
          owner.position.x=2.47;frame(.1)
          assert(math.abs(helper.speed-1.9)<1e-10 and helper.speed==outfit.speed)
          assert(math.abs(helper.time-outfit.time)<1e-10 and calls.warnings==0)
        ''')

    def test_authored_to_measured_legacy_keeps_destination_clock_synced_through_release(self):
        lua = runtime()
        lua.execute("mod._warlock_animation_ownership=function() return {speed=profile.states[outfit.state].owner=='legacy' and 'measured' or 'authored'} end")
        lua.execute(LOCOMOTION.read_text(encoding="utf-8"))
        lua.execute('''
          assert(mod._start_warlock_animation_blend(owner,outfit,profile))
          assert(mod._start_warlock_locomotion_animation(owner,outfit));frame(0)
          change('authored');frame(.25);assert(not active())
          owner.position.x=.19;frame(.1);change('walk')
          owner.position.x=.38;assert(frame(.1));assert(active() and helper.speed==outfit.speed)
          owner.position.x=.57;assert(frame(.1));assert(active() and helper.speed==outfit.speed)
          owner.position.x=.665;assert(not frame(.05))
          assert(not active() and status()=='native' and calls.warnings==0)
          assert(math.abs(helper.time-outfit.time)<1e-10 and calls.grip==2)
        ''')

    def test_root_trs_is_preflighted_atomically_before_any_sampler_setter(self):
        for mutation in ("outfit.locals[0].p.x=0/0", "outfit.locals[0].r.w=math.huge",
                         "outfit.locals[0].r=q(0);outfit.locals[0].r.w=0",
                         "outfit.locals[0].s.x=0", "outfit.locals[0].s.y=-1"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();writes=calls.helper_root;variables=calls.variables;targets=calls.constraints;" + mutation)
                lua.execute("mod._update_warlock_animation_blend(world,.1);assert(active() and status()=='invalid_sampler_root');assert(calls.helper_root==writes and calls.variables==variables and calls.constraints==targets and calls.visible==0)")

    def test_vector_and_matrix_aim_targets_are_finite_and_preflighted_before_setters(self):
        lua = runtime()
        lua.execute('''
          begin();owner.aim={matrix=true,axes={vec(1,0,0),vec(0,1,0),vec(0,0,1)},translation=vec(8,9,10)}
          frame(.1);assert(not helper.aim_matrix and helper.aim.x==8 and helper.aim.y==9 and calls.warnings==0)
        ''')
        for mutation in ("owner.aim.x=0/0", "owner.aim.x=math.huge",
                         "owner.aim={matrix=true,axes={vec(1,0,0),vec(0,0/0,0),vec(0,0,1)},translation=vec(8,9,10)}",
                         "owner.aim={matrix=true,axes={vec(1,0,0),vec(0,1,0),vec(0,0,1)},translation=vec(8,9,math.huge)}"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();writes=calls.helper_root;variables=calls.variables;targets=calls.constraints;" + mutation)
                lua.execute("mod._update_warlock_animation_blend(world,.1);assert(active() and status()=='invalid_sampler_aim');assert(calls.helper_root==writes and calls.variables==variables and calls.constraints==targets and calls.visible==0)")

    def test_native_update_and_event_errors_latch_once_and_cleanup_errors_do_not_escape(self):
        for mutation, action in (("broken_aim=true", "mod._update_warlock_animation_blend(world,.1)"),
                                 ("broken_event=true", "assert(not mod._note_warlock_animation_blend_event(owner,'authored','idle','authored',.25))")):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();" + mutation + ";" + action)
                lua.execute("assert(active() and status()=='sampler_api_error' and calls.warnings==1);assert(calls.visible==0);mod._update_warlock_animation_blend(world,.1);mod._apply_warlock_animation_blend(owner,outfit);assert(calls.warnings==1)")
        lua = runtime()
        lua.execute("begin();broken_destroy=true;mod._stop_warlock_animation_blend(owner);assert(not active() and status()=='off' and calls.warnings==1);mod._reset_warlock_animation_blend();assert(calls.warnings==1)")

    def test_release_requires_matching_native_visible_and_sampler_target_clocks(self):
        for mutation, reason in (("outfit.time=.6", "mismatched_target_clock"),
                                 ("outfit.length=3", "mismatched_target_clock"),
                                 ("outfit.time=0/0", "invalid_visible_clock"),
                                 ("outfit.length=0", "invalid_visible_clock")):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');mod._update_warlock_animation_blend(world,.25);engine(.25);" + mutation)
                lua.execute("assert(not mod._apply_warlock_animation_blend(owner,outfit));assert(active() and status()=='" + reason + "' and calls.visible==0)")
                lua.execute("assert(calls.warning:find('visible_time=',1,true) and calls.warning:find('visible_length=',1,true));assert(calls.warnings==1)")
        lua = runtime()
        lua.execute('''
          begin();change('authored');helper.length=.25;outfit.length=.25
          assert(not frame(.25));assert(not active() and calls.warnings==0)
        ''')

    def test_event_after_pre_animation_update_keeps_zero_elapsed_and_next_clock_progression(self):
        for already_evaluated in (False, True):
            with self.subTest(already_evaluated=already_evaluated):
                lua = runtime()
                lua.execute("begin();mod._update_warlock_animation_blend(world,.1);change('authored')")
                if already_evaluated:
                    lua.execute("engine(.1)")
                lua.execute("assert(mod._apply_warlock_animation_blend(owner,outfit));assert(active() and math.abs(outfit.locals[138].p.x-1.38)<1e-10);assert(frame(.1));assert(active() and calls.warnings==0)")

    def test_startup_nil_health_preserves_events_without_spawn_rest_snapshot(self):
        lua = runtime()
        lua.execute('''
          HEALTH_ALIVE[owner]=nil;assert(mod._start_warlock_animation_blend(owner,outfit,profile))
          change('authored');mod._update_warlock_animation_blend(world,.1)
          assert(not mod._apply_warlock_animation_blend(owner,outfit) and calls.visible==0)
          HEALTH_ALIVE[owner]=true;assert(not frame(.1));assert(helper.state=='authored' and not active())
          change('idle');frame(.1);assert(active())
        ''')

    def test_declared_false_health_rejects_start_without_spawning(self):
        lua = runtime()
        lua.execute("HEALTH_ALIVE[owner]=false;assert(not mod._start_warlock_animation_blend(owner,outfit,profile));assert(calls.spawns==0)")

    def test_health_loss_and_invalid_bindings_destroy_helper_and_cannot_reactivate(self):
        for mutation, restore in (
            ("HEALTH_ALIVE[owner]=nil", "HEALTH_ALIVE[owner]=true"),
            ("HEALTH_ALIVE[owner]=false", "HEALTH_ALIVE[owner]=true"),
            ("owner.alive=false", "owner.alive=true"),
            ("outfit.alive=false", "outfit.alive=true"),
            ("mod._warlock_outfits[owner]=nil", "mod._warlock_outfits[owner]=outfit"),
            ("owner.world=other_world", "owner.world=world"),
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');" + mutation)
                lua.execute("assert(not active());assert(calls.destroys==1);" + restore + ";assert(not active() and status()=='off')")

    def test_helper_deletion_preserves_failure_guard_until_explicit_teardown(self):
        lua = runtime()
        lua.execute("begin();change('authored');helper.alive=false;assert(active());assert(status()=='missing_sampler');assert(not frame(.1));assert(active())")

    def test_graph_and_pose_invalidity_are_atomic_before_visible_writes(self):
        for mutation in ("helper.parents[138]=1", "helper.nodes[bone_names[138]]=137"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("begin();change('authored');" + mutation)
                lua.execute("assert(not frame(.1));assert(active() and calls.visible==0)")
        lua = runtime()
        lua.execute("begin();change('authored');mod._update_warlock_animation_blend(world,.1);engine(.1);helper.locals[138].s.x=0;assert(not mod._apply_warlock_animation_blend(owner,outfit));assert(calls.visible==0 and active())")

    def test_untrusted_profile_and_missing_138_bones_fail_registration(self):
        for mutation in ("profile.bone_names[138]=nil", "profile.bone_names[138]=profile.bone_names[1]",
                         "profile.sampler_state_machine='foreign/rig'", "profile.states.idle.speed_expression='unknown'",
                         "profile.states.idle.loop_animation=nil", "outfit.data.warlock_animation_manifest_id='wrong'"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";assert(not mod._start_warlock_animation_blend(owner,outfit,profile));assert(calls.visible==0)")

    def test_unloaded_sampler_is_rejected_before_spawn_or_any_native_setter(self):
        for mutation in ("unloaded_sampler=true", "Application=nil", "Application.can_get=nil"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation + ";assert(not mod._start_warlock_animation_blend(owner,outfit,profile))")
                lua.execute('''
                  assert(calls.spawns==0 and calls.visible==0 and calls.helper_root==0 and calls.helper_bones==0)
                  assert(calls.variables==0 and calls.constraints==0 and calls.warnings==1 and status()=='off')
                  assert(not mod._start_warlock_animation_blend(owner,outfit,profile))
                  assert(calls.spawns==0 and calls.warnings==1)
                ''')

    def test_wrong_optional_outfit_does_not_stop_valid_compositor(self):
        lua = runtime()
        lua.execute("begin();change('authored');local other=unit('other');assert(not mod._apply_warlock_animation_blend(owner,other));assert(active());assert(frame(.1))")

    def test_stop_reset_and_world_release_cancel_helper_and_ignore_released_handles(self):
        for cleanup in ("mod._stop_warlock_animation_blend(owner)", "mod._reset_warlock_animation_blend()",
                        "mod._release_warlock_animation_blend_world(world)"):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute("begin();change('authored');" + cleanup)
                lua.execute('''
                  assert(calls.destroys==1);world.alive=false;owner.alive=false;outfit.alive=false
                  local native=calls.native;mod._update_warlock_animation_blend(world,.1)
                  assert(not mod._apply_warlock_animation_blend(owner,outfit) and not active())
                  assert(calls.native==native)
                ''')

    def test_unrelated_world_release_preserves_current_transition(self):
        lua = runtime()
        lua.execute("begin();change('authored');mod._release_warlock_animation_blend_world(other_world);assert(active() and calls.destroys==0);assert(frame(.1))")


if __name__ == "__main__":
    unittest.main()
