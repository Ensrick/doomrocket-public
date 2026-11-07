"""Execute authored launcher following against an independently composed graph.

Native external links reset local poses, unlink removes all external links, and
the approved internal graph is restored from the vanilla boxed metadata. The
oracle composes final nodes and requires rigid world scale1 under scale100,
stretch, shear and native re-wield. No renderer or engine acceptance is claimed.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime
from test_doomrocket_grip_alignment import HARNESS, MODULE

EXTENSION = r'''
calls.weapon_writes=0;calls.links=0;calls.unlinks=0;calls.normalizes=0
-- Match the documented native rotation extractor: normalize each affine axis
-- and convert that (possibly sheared) matrix to a quaternion, without silently
-- making the returned quaternion unit length. This catches omitted normalize.
function pose_quaternion(p)
 local r=rotation(p);local t=r[1][1]+r[2][2]+r[3][3];local q={}
 if t>0 then
  local s=math.sqrt(t+1)*2;q.w=s/4;q.x=(r[3][2]-r[2][3])/s
  q.y=(r[1][3]-r[3][1])/s;q.z=(r[2][1]-r[1][2])/s
 elseif r[1][1]>r[2][2] and r[1][1]>r[3][3] then
  local s=math.sqrt(1+r[1][1]-r[2][2]-r[3][3])*2;q.x=s/4
  q.w=(r[3][2]-r[2][3])/s;q.y=(r[1][2]+r[2][1])/s;q.z=(r[1][3]+r[3][1])/s
 elseif r[2][2]>r[3][3] then
  local s=math.sqrt(1+r[2][2]-r[1][1]-r[3][3])*2;q.y=s/4
  q.w=(r[1][3]-r[3][1])/s;q.x=(r[1][2]+r[2][1])/s;q.z=(r[2][3]+r[3][2])/s
 else
  local s=math.sqrt(1+r[3][3]-r[1][1]-r[2][2])*2;q.z=s/4
  q.w=(r[2][1]-r[1][2])/s;q.x=(r[1][3]+r[3][1])/s;q.y=(r[2][3]+r[3][2])/s
 end
 return q
end
Quaternion={normalize=function(q)
 calls.normalizes=calls.normalizes+1
 local n=math.sqrt(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w)
 return {x=q.x/n,y=q.y/n,z=q.z/n,w=q.w/n}
end}
Unit.world_rotation=function(u,node) return pose_quaternion(Unit.world_pose(u,node)) end
Matrix4x4.from_quaternion_position=function(q,v)
 local x,y,z,w=q.x,q.y,q.z,q.w;local p=Matrix4x4.identity()
 p[1][1]=1-2*y*y-2*z*z;p[1][2]=2*x*y-2*z*w;p[1][3]=2*x*z+2*y*w
 p[2][1]=2*x*y+2*z*w;p[2][2]=1-2*x*x-2*z*z;p[2][3]=2*y*z-2*x*w
 p[3][1]=2*x*z-2*y*w;p[3][2]=2*y*z+2*x*w;p[3][3]=1-2*x*x-2*y*y
 Matrix4x4.set_translation(p,v);return p
end
local old_data=Unit.get_data
Unit.get_data=function(u,key)
 if key=='unit_name' then return old_data(u,key) end
 return u.data and u.data[key]
end
function composed(u,node,poses)
 if poses[node] then return poses[node] end
 local pose=Matrix4x4.copy(u.locals[node]);local external=u.external and u.external[node]
 if external then
  pose=Matrix4x4.multiply(pose,composed(external.unit,external.node,{}))
 elseif node~=0 and u.parents[node]~=nil then
  pose=Matrix4x4.multiply(pose,composed(u,u.parents[node],poses))
 end
 poses[node]=pose;return pose
end
local old_set_pose=Unit.set_local_pose
Unit.set_local_pose=function(u,node,p)
 if u~=weapon then return old_set_pose(u,node,p) end
 assert(u.alive and not released);assert(Matrix4x4.is_valid(p))
 u.locals[node]=keep(p);calls.weapon_writes=calls.weapon_writes+1
end
Unit.scene_graph_link=function(u,node,parent)
 assert(u==weapon and parent<node)
 u.external=u.external or {};u.external[node]=nil;u.parents[node]=parent
end
World.link_unit=function(w,u,target,parent,source)
 assert(w==world and u==weapon and parent.alive)
 u.external=u.external or {};u.external[target]={unit=parent,node=source}
 u.locals[target]=keep(Matrix4x4.identity());calls.links=calls.links+1
end
World.unlink_unit=function(w,u)
 assert(w==world and u==weapon and not released)
 local saved={};for node in pairs(u.external or {}) do saved[node]=keep(composed(u,node,{})) end
 for node,pose in pairs(saved) do u.locals[node]=pose;u.parents[node]=nil end
 u.external={};calls.unlinks=calls.unlinks+1
end
for i,name in ipairs({'j_leftweaponattach','j_leftweaponcomponent1'}) do
 local node=14+i;outfit.nodes[name]=node;outfit.parents[node]=outfit.nodes.j_lefthand
 outfit.locals[node]=keep(Matrix4x4.identity(1,.001*i,.002*i,.003*i))
 owner.nodes[name]=64+i;owner.parents[64+i]=0
 owner.locals[64+i]=keep(Matrix4x4.identity(1,.3+i*.05,.4,1.0))
end
weapon.nodes.a_barrel=2;weapon.nodes.handle=3
weapon.parents[1]=0;weapon.locals[1]=keep(Matrix4x4.identity(100,.1,0,0))
weapon.parents[2]=1;weapon.locals[2]=keep(Matrix4x4.identity(1,.02,0,0))
weapon.parents[3]=1;weapon.locals[3]=keep(Matrix4x4.identity(1,.03,0,0))
weapon.parents[4]=3;weapon.locals[4]=keep(Matrix4x4.identity(1,.04,0,0))
weapon.data={scene_graph_data={}}
for _,node in ipairs({2,3}) do
 local pose=keep(weapon.locals[node]);local box={unbox=function() return Matrix4x4.copy(pose) end}
 weapon.data.scene_graph_data[#weapon.data.scene_graph_data+1]={i=node,parent=1,local_pose=box}
end
definition={};item_extension={dropped=false,wielding_unit=owner}
ScriptUnit={has_extension=function(u,name) assert(u==weapon);return item_extension end}
inventory={unit=owner,wielded=true,current_item_set_index=1,item_sets={{start_index=1,end_index=1}},
 inventory_item_units={weapon},inventory_item_definitions={definition}}
semantic_links={{target=0,source='j_leftweaponattach',world_scale={1,1,1}},
 {target='a_barrel',source='j_leftweaponcomponent1',world_scale={1,1,1}},
 {target='handle',source='j_lefthand',world_scale={1,1,1}}}
mode='authored'
mod._warlock_animation_ownership=function(unit,visible)
 assert(unit==owner and visible==outfit)
 return {upper_body=mode,weapon=mode,profile={weapon_links=semantic_links}}
end
function native_wield()
 for _,link in ipairs(semantic_links) do
  local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
  World.link_unit(world,weapon,node,owner,Unit.node(owner,link.source))
 end
 World.update_unit(world,weapon)
end
native_wield();World.update_unit(world,outfit);World.update_unit(world,owner)
function weapon_gap()
 local worst=0
 for _,link in ipairs(semantic_links) do
  local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
  local actual=Unit.world_pose(weapon,node)
  local expected=Matrix4x4.from_quaternion_position(Quaternion.normalize(Unit.world_rotation(outfit,Unit.node(outfit,link.source))),
   Unit.world_position(outfit,Unit.node(outfit,link.source)))
  for r=1,4 do for c=1,4 do worst=math.max(worst,math.abs(actual[r][c]-expected[r][c])) end end
 end
 return worst
end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS + EXTENSION)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    lua.execute("assert(mod._start_warlock_grip_alignment(owner,outfit,inventory))")
    return lua


class AuthoredWeaponTests(unittest.TestCase):
    def test_all_three_frames_follow_authored_pose_without_body_writes(self):
        lua = runtime()
        lua.execute("""
          tick();assert(not mod.last_error,mod.last_error)
          assert(mod._warlock_grip_alignment_status(owner)=='authored')
          assert(calls.writes==0 and weapon_gap()<1e-8)
          assert(weapon.external[0].unit==owner and weapon.external[0].node==0)
          assert(weapon.external[2]==nil and weapon.external[3]==nil)
          assert(weapon.parents[2]==1 and weapon.parents[3]==1)
          assert(Unit.local_scale(weapon,1).x==100)
          assert(calls.normalizes>=3)
        """)

    def test_translated_rotated_scale100_and_nonuniform_stretch(self):
        lua = runtime()
        lua.execute("""
          local p=Matrix4x4.identity(100,2,-3,1)
          p[1][1]=0;p[1][2]=-100;p[2][1]=100;p[2][2]=0;outfit.locals[1]=keep(p)
          local hand=outfit.nodes.j_lefthand
          outfit.locals[hand]=keep(Matrix4x4.identity(1,.004,.003,.002))
          outfit.locals[hand][1][1]=1.7;outfit.locals[hand][2][2]=.6
          tick();assert(not mod.last_error,mod.last_error);assert(weapon_gap()<1e-8)
          assert(calls.writes==0 and Unit.local_scale(outfit,hand).x==1.7)
        """)

    def test_sheared_authored_parent_never_becomes_weapon_scale(self):
        lua = runtime()
        lua.execute("""
          local hand=outfit.nodes.j_lefthand
          outfit.locals[hand][1][2]=.6
          World.update_unit(world,outfit);local q=Unit.world_rotation(outfit,hand)
          assert(math.abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1)>.001)
          tick();assert(not mod.last_error,mod.last_error)
          assert(mod._warlock_grip_alignment_status(owner)=='authored')
          assert(calls.writes==0 and weapon_gap()<1e-8)
          local p=Unit.world_pose(weapon,0)
          assert(math.abs(Vector3.length(Matrix4x4.x(p))-1)<1e-8)
        """)

    def test_native_rewield_is_reconciled_each_frame(self):
        lua = runtime()
        lua.execute("""
          tick();native_wield();assert(weapon.external[2].unit==owner)
          outfit.locals[outfit.nodes.j_lefthand][1][4]=.005
          tick();assert(not mod.last_error,mod.last_error);assert(weapon_gap()<1e-8)
          assert(weapon.external[2]==nil and weapon.external[3]==nil)
        """)

    def test_uniform_carrier_root_scale_is_compensated(self):
        lua = runtime()
        lua.execute("""
          owner.locals[0]=keep(Matrix4x4.identity(1.75,3,-4,2))
          owner.locals[0][1][1]=-1.75;owner.locals[0][2][2]=-1.75
          tick();assert(not mod.last_error,mod.last_error);assert(weapon_gap()<1e-8)
          assert(math.abs(Unit.local_scale(weapon,0).x-1/1.75)<1e-8)
          assert(Unit.local_scale(weapon,1).x==100)
        """)

    def test_legacy_return_restores_all_three_native_links(self):
        lua = runtime()
        lua.execute("""
          tick();mode='legacy';tick();assert(not mod.last_error,mod.last_error)
          for _,link in ipairs(semantic_links) do
           local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
           assert(weapon.external[node].unit==owner and weapon.external[node].node==Unit.node(owner,link.source))
          end
          assert(weapon.data.scene_graph_data[1].parent==1 and weapon.data.scene_graph_data[2].parent==1)
        """)

    def test_ordinary_native_inventory_without_item_sets_follows_authored_frames(self):
        lua = runtime()
        lua.execute("""
          inventory.item_sets=nil;inventory.inventory_items_n=2
          inventory.inventory_item_units={outfit,weapon}
          inventory.inventory_item_definitions={{},definition}
          tick();assert(not mod.last_error,mod.last_error)
          assert(mod._warlock_grip_alignment_status(owner)=='authored')
          assert(calls.writes==0 and weapon_gap()<1e-8)
          assert(weapon.external[0].unit==owner and weapon.external[0].node==0)
          mode='legacy';tick();assert(not mod.last_error,mod.last_error)
          for _,link in ipairs(semantic_links) do
           local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
           assert(weapon.external[node].unit==owner and weapon.external[node].node==Unit.node(owner,link.source))
          end
        """)

    def test_ordinary_inventory_stop_preserves_placement_until_native_wield_resumes(self):
        lua = runtime()
        lua.execute("""
          inventory.item_sets=nil;inventory.inventory_items_n=1
          tick();local before=keep(Unit.world_pose(weapon,0))
          mod._stop_warlock_grip_alignment_item(owner,weapon)
          local after=Unit.world_pose(weapon,0)
          for r=1,4 do for c=1,4 do assert(math.abs(before[r][c]-after[r][c])<1e-8) end end
          assert(next(weapon.external)==nil and weapon.parents[2]==1 and weapon.parents[3]==1)
          local n=calls.links;tick();assert(calls.links==n and calls.writes==0)
          native_wield();mod._resume_warlock_grip_alignment_item(owner,weapon)
          tick();assert(not mod.last_error,mod.last_error);assert(weapon_gap()<1e-8)
        """)

    def test_ordinary_inventory_stowed_dropped_and_disabled_items_are_not_reclaimed(self):
        for expression in ("inventory.wielded=false", "inventory.dropped=true", "item_extension.dropped=true",
                           "item_extension.wielding_unit=nil"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(f"""
                  inventory.item_sets=nil;inventory.inventory_items_n=1
                  tick();{expression};tick();assert(not mod.last_error,mod.last_error)
                  assert(next(weapon.external)==nil)
                  local n=calls.links;tick();assert(calls.links==n and calls.writes==0)
                """)

    def test_ordinary_inventory_invalid_item_counts_fail_without_pose_or_link_writes(self):
        for count in ("nil", "0", "-1", ".5", "math.huge", "0/0", "258"):
            with self.subTest(count=count):
                lua = runtime()
                lua.execute(f"""
                  inventory.item_sets=nil;inventory.inventory_items_n={count}
                  local links=calls.links;tick();assert(not mod.last_error,mod.last_error)
                  assert(calls.links==links and calls.weapon_writes==0 and calls.writes==0)
                  assert(mod._warlock_grip_alignment_status(owner)=='authored_no_wielded_weapon')
                """)

    def test_one_owner_death_cannot_poison_another_owners_shared_weapon_definition(self):
        lua = runtime()
        lua.execute("""
          inventory.item_sets=nil;inventory.inventory_items_n=1
          tick();assert(mod._warlock_grip_alignment_status(owner)=='authored')
          local first_owner,first_weapon=owner,weapon
          local shared_definition=definition
          -- Native drop_single_item mutates the selected shared item definition
          -- as well as this owner's per-item extension. A later spawn retains
          -- that same definition and gets its own fresh extension and metadata.
          mod._stop_warlock_grip_alignment_item(owner,weapon)
          item_extension.wielding_unit=nil;item_extension.dropped=true
          shared_definition.dropped=true;inventory.dropped=true
          mod._stop_warlock_grip_alignment(owner)
          local function copy_unit(source)
           local target=make_unit(source.name)
           for name,node in pairs(source.nodes) do target.nodes[name]=node end
           for node,parent in pairs(source.parents) do target.parents[node]=parent end
           for node,pose in pairs(source.locals) do target.locals[node]=keep(pose) end
           return target
          end
          owner=copy_unit(owner);outfit=copy_unit(outfit);weapon=copy_unit(weapon)
          weapon.data={scene_graph_data={}}
          for _,node in ipairs({2,3}) do
           local pose=keep(first_weapon.data.scene_graph_data[node==2 and 1 or 2].local_pose:unbox())
           local box={unbox=function() return Matrix4x4.copy(pose) end}
           weapon.data.scene_graph_data[#weapon.data.scene_graph_data+1]={i=node,parent=1,local_pose=box}
          end
          item_extension={dropped=false,wielding_unit=owner}
          inventory={unit=owner,wielded=true,inventory_items_n=1,
           inventory_item_units={weapon},inventory_item_definitions={shared_definition}}
          HEALTH_ALIVE[owner]=true;mod._warlock_outfits[owner]=outfit
          World.update_unit(world,owner);World.update_unit(world,outfit);native_wield()
          assert(owner~=first_owner and weapon~=first_weapon)
          assert(inventory.inventory_item_definitions[1]==shared_definition and shared_definition.dropped)
          assert(mod._start_warlock_grip_alignment(owner,outfit,inventory))
          tick();assert(not mod.last_error,mod.last_error)
          assert(mod._warlock_grip_alignment_status(owner)=='authored')
          assert(calls.writes==0 and weapon_gap()<1e-8)
          for _,link in ipairs(semantic_links) do
           local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
           assert(weapon.external[node]==nil or weapon.external[node].unit~=first_owner)
          end
        """)

    def test_stowed_dropped_and_disabled_items_are_not_reclaimed(self):
        for expression in ("inventory.wielded=false", "inventory.dropped=true", "item_extension.dropped=true",
                           "inventory.current_item_set_index=2", "item_extension.wielding_unit=nil"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(f"""
                  tick();{expression};tick();assert(not mod.last_error,mod.last_error)
                  assert(next(weapon.external)==nil)
                  local n=calls.links;tick();assert(calls.links==n and calls.writes==0)
                """)

    def test_stop_before_drop_preserves_root_placement_and_original_graph(self):
        lua = runtime()
        lua.execute("""
          tick();local before=keep(Unit.world_pose(weapon,0))
          mod._stop_warlock_grip_alignment_item(owner,weapon)
          local after=Unit.world_pose(weapon,0)
          for r=1,4 do for c=1,4 do assert(math.abs(before[r][c]-after[r][c])<1e-8) end end
          assert(next(weapon.external)==nil and weapon.parents[2]==1 and weapon.parents[3]==1)
          local n=calls.links;tick();assert(calls.links==n)
          native_wield();mod._resume_warlock_grip_alignment_item(owner,weapon)
          tick();assert(weapon_gap()<1e-8)
        """)

    def test_late_invalid_candidate_does_not_change_any_link_or_pose(self):
        for expression in ("outfit.locals[outfit.nodes.j_lefthand][1][1]=0",
                           "semantic_links[3].world_scale={100,100,100}",
                           "weapon.data.scene_graph_data[2].parent=3",
                           "weapon.locals[1][1][2]=1",
                           "outfit.nodes.j_leftweaponcomponent1=nil",
                           "owner.locals[0][1][2]=.5"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(f"""
                  {expression};local n=calls.links;local writes=calls.weapon_writes
                  tick();assert(not mod.last_error,mod.last_error)
                  assert(calls.links==n and calls.weapon_writes==writes and calls.writes==0)
                """)

    def test_extra_duplicate_and_noninteger_vanilla_graph_entries_are_rejected(self):
        for expression in (
            "weapon.data.scene_graph_data[3]={i=-1,parent=-2,local_pose=weapon.data.scene_graph_data[1].local_pose}",
            "weapon.data.scene_graph_data[2].i=2",
            "weapon.data.scene_graph_data[2].parent=.5",
            "weapon.data.scene_graph_data[2].parent=-1",
            "weapon.data.scene_graph_data[2].i=3.5",
        ):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(f"""
                  {expression};local links=calls.links;local unlinks=calls.unlinks
                  tick();assert(not mod.last_error,mod.last_error)
                  assert(calls.links==links and calls.unlinks==unlinks and calls.weapon_writes==0)
                  assert(mod._warlock_grip_alignment_status(owner)=='invalid_weapon_graph')
                """)

    def test_correction_runs_after_grip_and_weapon_flush(self):
        lua = runtime()
        lua.execute("""
          local corrected=0
          mod._apply_warlock_outfit_correction=function(unit,visible,corpse)
           assert(unit==owner and visible==outfit and corpse==false)
           assert(weapon_gap()<1e-8);corrected=corrected+1
          end
          tick();assert(corrected==1)
        """)

    def test_nil_resume_is_safe_and_does_not_resume_stowed_weapon(self):
        lua = runtime()
        lua.execute("""
          tick();mod._stop_warlock_grip_alignment_item(owner,weapon)
          mod._resume_warlock_grip_alignment_item(owner,nil)
          mod._resume_warlock_grip_alignment_item(nil,weapon)
          local n=calls.links;tick();assert(calls.links==n)
        """)

    def test_death_reset_release_cancel_queued_follow_and_restore_graph(self):
        for expression in ("mod._stop_warlock_grip_alignment(owner)",
                           "HEALTH_ALIVE[owner]=nil;mod._reset_warlock_grip_alignment()",
                           "mod._release_warlock_grip_alignment_world(world)"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(f"""
                  tick();mod._queue_warlock_grip_alignment(world,1/60);{expression}
                  assert(next(weapon.external)==nil)
                  local n=calls.links;drain();assert(calls.links==n)
                """)

    def test_reset_while_alive_returns_launcher_to_native_links(self):
        lua = runtime()
        lua.execute("""
          tick();assert(next(weapon.external)~=nil)
          mod._queue_warlock_grip_alignment(world,1/60);mod._reset_warlock_grip_alignment()
          for _,link in ipairs(semantic_links) do
           local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
           assert(weapon.external[node].unit==owner and weapon.external[node].node==Unit.node(owner,link.source))
          end
          local n=calls.links;drain();assert(calls.links==n)
        """)

    def test_unsupported_mode_and_apply_error_return_launcher_to_native_links(self):
        for expression in ("mode='unsupported'",
                           "mod._apply_warlock_animation_blend=function() error('blend failure') end"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(f"""
                  tick();assert(not mod.last_error,mod.last_error)
                  {expression};tick()
          for _,link in ipairs(semantic_links) do
           local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
           assert(weapon.external[node].unit==owner and weapon.external[node].node==Unit.node(owner,link.source))
          end
                """)

    def test_missing_quaternion_normalize_uses_element_fallback(self):
        lua = runtime()
        lua.execute("""
          local normalize=Quaternion.normalize;calls.fallbacks=0
          Quaternion.to_elements=function(q) return q.x,q.y,q.z,q.w end
          Quaternion.from_elements=function(x,y,z,w) calls.fallbacks=calls.fallbacks+1;return {x=x,y=y,z=z,w=w} end
          Quaternion.normalize=nil;tick();Quaternion.normalize=normalize
          assert(not mod.last_error,mod.last_error);assert(calls.fallbacks>=3)
          assert(weapon_gap()<1e-8)
        """)


if __name__ == "__main__":
    unittest.main()
