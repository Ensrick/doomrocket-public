#!/usr/bin/env python3
"""Issue #15 native small pickup-torch controller, executed in real Lua 5.1.

Strict particle/package/world doubles cover exact ownership, compensated anchor,
retired size commands, resource and creation failure, reload and teardown. The
native resource and its direct dependency closure have a separate pinned audit;
these tests do not establish rendered size, color, or in-game acceptance.
"""

import json
import math
from pathlib import Path
import re
import subprocess
import sys
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_crystal_flame.lua"
ANCHOR = ROOT / "scripts/mods/doomrocket/utils/doomrocket_crystal_anchor.lua"
FIXTURE = json.loads((ROOT / "tools/fixtures/warlock_crystal_anchor.json").read_text(encoding="utf-8"))
PACKAGE_HELPER = ROOT / "scripts/mods/doomrocket/utils/doomrocket_effect_package.lua"
BOOTSTRAP = ROOT / "scripts/mods/doomrocket/doomrocket.lua"
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"
BUNDLE_ROOT = ROOT / "bundleV2"

HARNESS = r"""
events={created=0,linked=0,destroyed=0,queried=0,loads=0,unloads=0,nodes=0}
logs={}
function printf(format,...) logs[#logs+1]=string.format(format,...) end
local function v(x,y,z) return {x=x,y=y,z=z} end
Vector3=setmetatable({length=function(a) return math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z) end},
 {__call=function(_,x,y,z) return v(x,y,z) end})
Matrix4x4={
 identity=function() return {x=v(1,0,0),y=v(0,1,0),z=v(0,0,1),p=v(0,0,0)} end,
 set_x=function(m,x) m.x=x end,set_y=function(m,x) m.y=x end,
 set_z=function(m,x) m.z=x end,set_translation=function(m,x) m.p=x end,
 translation=function(m) return m.p end,
 rotation=function(m) return m end,
}
local function transform(m,a,point)
 return v(m.x.x*a.x+m.y.x*a.y+m.z.x*a.z+(point and m.p.x or 0),
  m.x.y*a.x+m.y.y*a.y+m.z.y*a.z+(point and m.p.y or 0),
  m.x.z*a.x+m.y.z*a.y+m.z.z*a.z+(point and m.p.z or 0))
end
-- Stingray composition is local then parent world, as used by native action_sweep.
function Matrix4x4.multiply(local_pose,parent)
 return {x=transform(parent,local_pose.x),y=transform(parent,local_pose.y),
  z=transform(parent,local_pose.z),p=transform(parent,local_pose.p,true)}
end
function Matrix4x4.set_scale(m,scale)
 local function axis(a,s)
  local n=Vector3.length(a)
  return v(a.x/n*s,a.y/n*s,a.z/n*s)
 end
 m.x=axis(m.x,scale.x); m.y=axis(m.y,scale.y); m.z=axis(m.z,scale.z)
end
function Matrix4x4.scale(m)
 return v(Vector3.length(m.x),Vector3.length(m.y),Vector3.length(m.z))
end
world={alive=true}
weapon_name='units/rocket/pRocketLauncher'
function new_owner() return {alive=true,world=world} end
function new_weapon() return {alive=true,world=world,name=weapon_name,has_node=true,item={dropped=false}} end
owner=new_owner(); weapon=new_weapon()
function new_inventory(o,w) return {unit=o or owner,inventory_item_units={{alive=true,world=world,name='units/bombadier/Backpack'},w or weapon}} end
inventory=new_inventory()
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) assert(u and u.alive,'dead Unit.world'); return u.world end,
 get_data=function(u,key) assert(u and u.alive and key=='unit_name'); return u.name end,
 has_node=function(u,node) assert(u.alive and node=='pRocketLauncher'); return u.has_node end,
 node=function(u,node)
  assert(u.alive and u.has_node and node=='pRocketLauncher','unsafe node lookup')
  events.nodes=events.nodes+1; return 7
 end,
 world_pose=function(u,node)
  assert(u.alive and node==7,'dead or wrong Unit.world_pose')
  return u.pose or {x=v(100,0,0),y=v(0,100,0),z=v(0,0,100),p=v(10,20,30)}
 end,
}
ScriptUnit={has_extension=function(u,system)
 assert(system=='ai_inventory_item_system'); return u.item
end}
wm={_worlds={level_world=world},_disabled_worlds={}}
function wm:has_world(name) return self._worlds[name] ~= nil end
function wm:world(name) assert(self._worlds[name]); return self._worlds[name] end
package_name='resource_packages/pickups'
legacy_package='resource_packages/breeds/skaven_warpfire_thrower'
legacy_owned=false
package_reference='doomrocket_crystal_flame'
effect_name='fx/doomrocket/crystal_torch_green_small'
variant_package='resource_packages/doomrocket/warlock_crystal'
variant_refs={}; variant_loaded=true
package_available=true; particles_available=true; loaded=true
refs={global=3}
pm={}
function pm:has_loaded(name,reference)
 if name==legacy_package then return legacy_owned end
 assert(name==package_name)
 return loaded and (not reference or refs[reference] ~= nil)
end
function pm:reference_count(name,reference)
 if name==legacy_package then return legacy_owned and 1 or 0 end
 assert(name==package_name); return refs[reference] or 0
end
function pm:is_loading(name,reference)
 assert(name==package_name); return not loaded and refs[reference] ~= nil
end
function pm:load(name,reference,callback,asynchronous)
 assert(name==package_name and reference==package_reference)
 if not asynchronous then events.sync_loads=(events.sync_loads or 0)+1 end
 assert(callback==nil and asynchronous==true,'cosmetic package must load asynchronously')
 refs[reference]=(refs[reference] or 0)+1; loaded=not defer_loading; events.loads=events.loads+1
end
function pm:unload(name,reference)
 if name==legacy_package then
  assert(reference==package_reference and legacy_owned)
  legacy_owned=false; events.legacy_unloads=(events.legacy_unloads or 0)+1; return
 end
 assert(name==package_name and reference==package_reference)
 assert(refs[reference] and refs[reference] > 0,'unowned package decrement')
 refs[reference]=refs[reference]-1
 if refs[reference]==0 then refs[reference]=nil end
 events.unloads=events.unloads+1
end
Managers={world=wm,package=pm}
Application={can_get=function(kind,name)
 if kind=='package' then
  assert(name~=variant_package,'mod package queried through global Application API')
  assert(name==package_name); return package_available
 end
 assert(kind=='particles' and name==effect_name)
 assert(refs[package_reference],'residency queried before own package load')
 return particles_available
end}
effects={}; next_id=1
local function check_world(w) assert(w and w.alive,'released world touched') end
World={
 create_particles=function(w,name,position,rotation,scale)
  check_world(w); assert(name==effect_name)
  assert(position and not rotation and not scale,'use the native scaled link-pose pattern')
  local id=next_id; next_id=id+1
  effects[id]={world=w}; events.created=events.created+1
  events.latest_id=id
  return id
 end,
 link_particles=function(w,id,u,node,pose,policy)
  check_world(w); assert(effects[id] and u.alive and u.world==w)
  assert(node==7 and policy=='destroy')
  effects[id].weapon=u; effects[id].node=node; effects[id].pose=pose
  events.linked=events.linked+1; events.last_pose=pose
 end,
 are_particles_playing=function(w,id)
  check_world(w); events.queried=events.queried+1
  assert(effects[id] and effects[id].world==w,'stale particle queried')
  return true
 end,
 destroy_particles=function(w,id)
  check_world(w); assert(effects[id] and effects[id].world==w,'stale particle destroyed')
  assert(not effects[id].foreign,'recycled foreign particle destroyed')
  effects[id]=nil; events.destroyed=events.destroyed+1
 end,
 find_particles_variable=function(w,name,variable)
  error('native small torch must not use the rejected variable-size experiment')
 end,
 set_particles_variable=function(w,id,variable,value)
  error('native small torch must not use the rejected variable-size experiment')
 end,
}
mod={commands={},echoes={}}
function mod:package_status(name)
 assert(name==variant_package)
 if not variant_refs[package_reference] or variant_cancelled then return nil end
 return variant_loaded and 'loaded' or 'loading'
end
function finish_variant()
 variant_loaded=true
 if variant_cancelled then
  variant_refs[package_reference]=nil; variant_callback=nil; variant_cancelled=false
  events.variant_cancelled_releases=(events.variant_cancelled_releases or 0)+1; return
 end
 if variant_refs[package_reference] and variant_callback then
  local callback=variant_callback; variant_callback=nil; callback(variant_package)
 end
end
function mod:load_package(name,callback,sync)
 assert(name==variant_package and type(callback)=='function' and sync==false)
 assert(pm:has_loaded(package_name,package_reference),'variant queued before native dependencies')
 if variant_package_available==false then return end
 if variant_cancelled then
  variant_cancelled=false; variant_callback=callback
  events.variant_revivals=(events.variant_revivals or 0)+1; return
 end
 assert(not variant_refs[package_reference],'duplicate VMF package request')
 variant_refs[package_reference]=1; variant_loaded=not defer_variant_loading
 events.variant_loads=(events.variant_loads or 0)+1
 variant_callback=callback
 if variant_loaded then finish_variant() end
end
function mod:unload_package(name)
 assert(name==variant_package and self:package_status(name)=='loaded','premature VMF package unload')
 variant_refs[package_reference]=nil; variant_callback=nil
 events.variant_unloads=(events.variant_unloads or 0)+1
end
function mod:command(name,description,fn) self.commands[name]=fn end
function mod:echo(message,...) self.echoes[#self.echoes+1]=string.format(message,...) end
function get_mod(name) assert(name=='doomrocket'); return mod end
function delete_weapon(w)
 w=w or weapon
 -- Native linking destroys the emitter with the launcher and may recycle its ID.
 for id,e in pairs(effects) do
  if e.weapon==w then effects[id]={world=e.world,foreign=true} end
 end
 w.alive=false
end
function particles_pose(id)
 local e=effects[id]
 assert(e and not e.foreign)
 return Matrix4x4.multiply(e.pose,Unit.world_pose(e.weapon,e.node))
end
function count() local n=0; for _ in pairs(effects) do n=n+1 end; return n end
function start(o,inv) return mod._start_warlock_crystal_flame(o or owner,inv or inventory) end
"""


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.globals().mod._warlock_effect_package = lua.execute(PACKAGE_HELPER.read_text(encoding="utf-8"))
    lua.execute("mod._doomrocket_crystal_anchor = (function()\n"
                + ANCHOR.read_text(encoding="utf-8") + "\nend)()")
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


class CrystalFlameInitializationTests(unittest.TestCase):
    def test_dedicated_server_never_touches_native_resources(self):
        lua = runtime()
        lua.execute("""
            DEDICATED_SERVER=true
            local function forbidden() error('dedicated server touched native API') end
            Unit=setmetatable({}, {__index=function() return forbidden end})
            World=setmetatable({}, {__index=function() return forbidden end})
            Application=setmetatable({}, {__index=function() return forbidden end})
            Managers=setmetatable({}, {__index=function() return forbidden end})
            assert(not start())
            assert(events.created==0 and events.loads==0)
        """)

    def test_retired_tuning_is_a_no_op_before_and_after_spawn(self):
        lua = runtime()
        lua.execute("""
            assert(mod._doomrocket_crystal_flame_state.size==nil)
            for phase=1,2 do
                for _,args in ipairs({{0.0001,0.0001},{0.1,0.35},{'big'}, {}}) do
                    local valid,reason=mod._set_warlock_crystal_flame_size(unpack(args))
                    assert(not valid and reason=='native_effect')
                    mod.commands.warlock_crystal_flame(unpack(args))
                    local message=mod.echoes[#mod.echoes]
                    assert(message:find('Numeric size tuning is retired',1,true))
                    assert(message:find('colour and rendered appearance await',1,true))
                    assert(not message:find('resized',1,true))
                end
                assert(events.created==phase-1 and events.destroyed==0)
                if phase==1 then assert(start()) end
            end
            assert(events.created==1 and events.loads==1)
        """)

    def test_reload_disposes_owned_flame_and_can_spawn_new_candidate(self):
        lua = runtime()
        lua.execute("assert(start())")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
            assert(events.created==1 and events.destroyed==1 and events.unloads==1)
            assert(count()==0 and not refs[package_reference] and refs.global==3)
            assert(not next(mod._doomrocket_crystal_flame_state.entries))
            assert(not next(mod._doomrocket_crystal_flame_state.weapons))
            assert(start())
            assert(events.created==2 and events.loads==2)
            mod._reset_warlock_crystal_flame('second_reset')
            assert(events.destroyed==2 and events.unloads==2 and refs.global==3)
        """)

    def test_reload_never_reclaims_native_deleted_launchers_recycled_id(self):
        lua = runtime()
        lua.execute("assert(start()); delete_weapon()")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
            assert(events.created==1 and events.destroyed==0 and events.queried==0)
            assert(effects[events.latest_id].foreign)
            assert(not next(mod._doomrocket_crystal_flame_state.entries))
            assert(not start())
            mod._reset_warlock_crystal_flame('second_reset')
            assert(events.destroyed==0 and events.queried==0)
        """)

    def test_reload_during_world_release_leaves_teardown_to_the_engine(self):
        lua = runtime()
        lua.execute("assert(start()); mod._release_warlock_crystal_flame_world(world)")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
            assert(events.destroyed==0 and events.queried==0 and events.unloads==0)
            assert(not start())
            world.alive=false; wm._worlds.level_world=nil
            mod._reset_warlock_crystal_flame('after_world_release')
            assert(events.destroyed==0 and events.queried==0 and events.unloads==1)
            assert(refs.global==3 and not refs[package_reference])
        """)

    def test_legacy_package_and_old_size_state_migrate_without_wrong_unload(self):
        lua = runtime()
        lua.execute("""
            local s=mod._doomrocket_crystal_flame_state
            s.owns_package=true; s.package_manager=pm; legacy_owned=true
            s.size={0.01,2}; s.unknown_worlds[world]=true
            mod._reset_warlock_crystal_flame=function(reason)
                assert(reason=='module_reload'); old_reset_called=true
            end
        """)
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
            local s=mod._doomrocket_crystal_flame_state
            assert(old_reset_called and s.size==nil and s.package_manager==nil)
            assert(s.packages[legacy_package]==pm and legacy_owned)
            assert(not start() and events.loads==0 and events.unloads==0)
            mod._release_warlock_crystal_flame_world(world)
            assert(legacy_owned and events.unloads==0)
            world.alive=false; wm._worlds.level_world=nil
            mod._reset_warlock_crystal_flame('after_legacy_world_release')
            assert(not legacy_owned and events.legacy_unloads==1 and refs.global==3)
            world={alive=true}; wm._worlds.level_world=world
            owner=new_owner(); weapon=new_weapon(); inventory=new_inventory()
            assert(start())
            assert(events.loads==1 and refs[package_reference]==1)
            mod._reset_warlock_crystal_flame('current_reset')
            assert(events.unloads==1 and events.legacy_unloads==1 and refs.global==3)
        """)


class CrystalFlameLifecycleTests(unittest.TestCase):
    def test_start_links_one_native_flame_with_only_inverse_node_compensation(self):
        lua = runtime()
        lua.execute("""
            assert(start()); assert(start())
            assert(events.created==1 and events.linked==1 and events.loads==1)
            local a, p = mod._doomrocket_crystal_anchor, events.last_pose
            local function close(a,b) return math.abs(a-b)<1e-12 end
            assert(close(p.z.x,a.x_axis[1]) and close(p.z.y,a.x_axis[2]))
            assert(close(p.x.x,a.y_axis[1]) and close(p.y.x,a.z_axis[1]))
            -- The measured crystal tip, moved 2 cm along the crystal toward its mount.
            local base={}
            for i=1,3 do base[i]=a.position[i]-a.x_axis[i]*.02 end
            assert(close(p.p.x,base[1]) and close(p.p.y,base[2]) and close(p.p.z,base[3]))
            local global=particles_pose(1)
            local scale=Matrix4x4.scale(global)
            assert(close(scale.x,1) and close(scale.y,1) and close(scale.z,1))
            assert(close(global.p.x,10+base[1]*100) and close(global.p.y,20+base[2]*100) and close(global.p.z,30+base[3]*100))
            assert(logs[#logs]:find('profile=green_small_pickup_torch',1,true))
            assert(logs[#logs]:find('native_scale=0.6 tint=green rendered_size=unverified',1,true))
        """)

    def test_stop_destroys_its_own_flame_and_releases_the_package_on_reset(self):
        lua = runtime()
        lua.execute("""
            assert(start())
            assert(mod._stop_warlock_crystal_flame(owner,'test'))
            assert(not mod._stop_warlock_crystal_flame(owner,'again'))
            assert(events.destroyed==1 and count()==0)
            mod._reset_warlock_crystal_flame('test')
            assert(events.unloads==1 and refs[package_reference]==nil and refs.global==3)
        """)

    def test_dropping_or_disabling_launcher_stops_only_its_flame(self):
        lua = runtime()
        lua.execute("""
            assert(start())
            assert(not mod._stop_warlock_crystal_flame_item(owner,{alive=true},'other_item'))
            assert(count()==1)
            assert(mod._stop_warlock_crystal_flame_item(owner,weapon,'inventory_drop'))
            assert(events.destroyed==1 and count()==0)
        """)

    def test_deleted_launcher_is_forgotten_without_touching_recycled_id(self):
        lua = runtime()
        lua.execute("""
            assert(start()); delete_weapon()
            mod._update_warlock_crystal_flame()
            assert(events.destroyed==0 and events.queried==0)
            assert(not mod._stop_warlock_crystal_flame(owner,'late'))
        """)

    def test_world_release_forgets_without_particle_or_package_calls(self):
        lua = runtime()
        lua.execute("""
            assert(start()); mod._release_warlock_crystal_flame_world(world)
            assert(events.destroyed==0 and events.queried==0 and events.unloads==0)
            assert(not start(), 'no spawning while the old world releases')
            world.alive=false; wm._worlds.level_world=nil
            mod._reset_warlock_crystal_flame('after_release')
            assert(events.unloads==1)
            world={alive=true}; wm._worlds.level_world=world
            owner=new_owner(); weapon=new_weapon(); inventory=new_inventory()
            assert(start())
        """)

    def test_paused_disabled_world_retains_existing_ownership_without_duplication(self):
        lua = runtime()
        lua.execute("""
            assert(start())
            wm._worlds.level_world=nil; wm._disabled_worlds.level_world=world
            mod._update_warlock_crystal_flame()
            assert(events.destroyed==0 and events.queried==0)
            assert(not start() and events.created==1)
            mod._reset_warlock_crystal_flame('disabled_world_reset')
            assert(events.destroyed==1 and events.unloads==1 and refs.global==3)
        """)

    def test_no_flame_without_carried_launcher(self):
        lua = runtime()
        lua.execute("""
            weapon.item.dropped=true; assert(not start())
            weapon.item.dropped=false
            assert(not start(owner,{unit=new_owner(),inventory_item_units={weapon}}))
            weapon.has_node=false; assert(not start())
            weapon.has_node=true; assert(start() and events.created==1)
        """)

    def test_invalid_anchor_never_reaches_native_node_lookup(self):
        for anchor in ("{}", "{node='wrong'}", "{node='pRocketLauncher',x_axis={0,0,0},y_axis={0,0.01,0},z_axis={0,0,0.01},position={0,0,0}}",
                       "{node='pRocketLauncher',x_axis={0.01,0,0},y_axis={0,0.01,0},z_axis={0,0,-0.01},position={0,0,0}}",
                       "{node='pRocketLauncher',x_axis={math.huge,0,0},y_axis={0,0.01,0},z_axis={0,0,0.01},position={0,0,0}}"):
            with self.subTest(anchor=anchor):
                lua = runtime()
                lua.execute("mod._doomrocket_crystal_anchor=" + anchor)
                lua.execute("""
                    Unit.has_node=function() error('bad anchor reached native node lookup') end
                    assert(not start())
                    assert(events.loads==0 and events.created==0 and events.nodes==0)
                """)

    def test_replaced_launcher_moves_flame(self):
        lua = runtime()
        lua.execute("""
            assert(start())
            local replacement=new_weapon()
            assert(start(owner,new_inventory(owner,replacement)))
            assert(events.created==2 and events.destroyed==1 and count()==1)
        """)

    def test_other_engineers_do_not_share_or_reclaim_handles(self):
        lua = runtime()
        lua.execute("""
            assert(start())
            local other_owner,other_weapon=new_owner(),new_weapon()
            assert(not start(other_owner,new_inventory(other_owner,weapon)))
            assert(start(other_owner,new_inventory(other_owner,other_weapon)))
            assert(events.created==2 and count()==2 and events.loads==1)
            assert(mod._stop_warlock_crystal_flame(owner,'death'))
            assert(events.destroyed==1 and count()==1)
            mod._reset_warlock_crystal_flame('reset_all')
            assert(events.destroyed==2 and events.unloads==1 and refs.global==3)
        """)

    def test_link_follows_rotated_translated_scale100_launcher_without_respawning(self):
        lua = runtime()
        lua.execute("""
            assert(start())
            weapon.pose={x=Vector3(0,100,0),y=Vector3(-100,0,0),z=Vector3(0,0,100),p=Vector3(50,60,70)}
            mod._update_warlock_crystal_flame()
            local pose,a=particles_pose(events.latest_id),mod._doomrocket_crystal_anchor
            assert(events.created==1 and events.linked==1)
            local base={a.position[1]-a.x_axis[1]*.02,a.position[2]-a.x_axis[2]*.02}
            assert(math.abs(pose.p.x-(50-base[2]*100))<1e-9 and math.abs(pose.p.y-(60+base[1]*100))<1e-9)
            assert(math.abs(pose.z.x+a.x_axis[2]*100)<1e-12)
            assert(math.abs(pose.z.y-a.x_axis[1]*100)<1e-12)
            local scale=Matrix4x4.scale(pose)
            assert(math.abs(scale.x-1)<1e-12 and math.abs(scale.z-1)<1e-12)
            mod._release_warlock_crystal_flame_world(world)
            world.alive=false; wm._worlds.level_world=nil
            mod._update_warlock_crystal_flame()
            assert(events.queried==0)
        """)


class CrystalFlameFailureTests(unittest.TestCase):
    def test_missing_package_and_effect_skip_spawn_and_release_only_own_reference(self):
        lua = runtime()
        lua.execute("""
            package_available=false
            assert(not start() and events.loads==0 and events.created==0)
            package_available=true; particles_available=false
            assert(not start() and events.loads==1 and events.unloads==1)
            assert(not refs[package_reference] and refs.global==3 and count()==0)
            particles_available=true
            assert(start() and events.created==1 and events.loads==2)
        """)

    def test_unaccepted_async_request_skips_particle_access(self):
        lua = runtime()
        lua.execute("""
            pm.load=function() events.loads=events.loads+1 end
            assert(not start())
            assert(events.loads==1 and events.created==0 and events.unloads==0)
            assert(not next(mod._doomrocket_crystal_flame_state.packages))
        """)

    def test_load_error_after_acquiring_reference_does_not_escape_or_leak(self):
        lua = runtime()
        lua.execute("""
            local load=pm.load
            pm.load=function(...) load(...); error('load failed after reference acquired') end
            assert(not start())
            assert(events.loads==1 and events.unloads==1 and events.created==0)
            assert(not refs[package_reference] and refs.global==3)
        """)

    def test_creation_error_or_invalid_handle_cannot_link_or_claim_owner(self):
        for failure in ("return nil", "error('native create failed')", "return -1", "return 0/0", "return math.huge", "return 0.5"):
            with self.subTest(failure=failure):
                lua = runtime()
                lua.execute("World.create_particles=function() " + failure + " end")
                lua.execute("""
                    assert(not start())
                    assert(events.linked==0 and events.created==0 and events.unloads==0)
                    assert(not next(mod._doomrocket_crystal_flame_state.entries))
                    assert(not next(mod._doomrocket_crystal_flame_state.weapons))
                    assert(not next(mod._doomrocket_crystal_flame_state.creating_worlds))
                    assert(not next(mod._doomrocket_crystal_flame_state.pending_owners))
                    assert(not next(mod._doomrocket_crystal_flame_state.pending_weapons))
                    assert(mod._doomrocket_crystal_flame_state.unknown_worlds[world])
                    assert(refs[package_reference]==1 and refs.global==3)
                    mod._release_warlock_crystal_flame_world(world)
                    world.alive=false; wm._worlds.level_world=nil
                    mod._reset_warlock_crystal_flame('uncertain_creation_world_gone')
                    assert(events.unloads==1 and events.queried==0 and events.destroyed==0)
                    assert(not refs[package_reference] and refs.global==3)
                """)

    def test_create_then_error_defers_unknown_emitter_and_package_to_world_release(self):
        lua = runtime()
        lua.execute("""
            local create=World.create_particles
            World.create_particles=function(...)
                create(...); error('wrapper failed after allocating')
            end
            assert(not start())
            assert(events.created==1 and events.linked==0 and events.queried==0 and events.destroyed==0)
            assert(events.unloads==0 and refs[package_reference]==1)
            assert(mod._doomrocket_crystal_flame_state.unknown_worlds[world])
            assert(not next(mod._doomrocket_crystal_flame_state.pending_owners))
            assert(not start() and events.created==1)
            mod._release_warlock_crystal_flame_world(world)
            world.alive=false; wm._worlds.level_world=nil
            mod._reset_warlock_crystal_flame('world_gone')
            assert(events.unloads==1 and events.queried==0 and events.destroyed==0)
        """)

    def test_link_error_destroys_only_newly_created_emitter(self):
        lua = runtime()
        lua.execute("""
            World.link_particles=function() error('native link failed') end
            assert(not start())
            assert(events.created==1 and events.destroyed==1 and count()==0)
            assert(events.unloads==1 and refs.global==3)
            assert(not mod._stop_warlock_crystal_flame(owner,'late_cleanup'))
        """)

    def test_link_then_launcher_deletion_never_queries_recycled_handle(self):
        for failure in ("error('link wrapper failed after native link')", "return"):
            with self.subTest(failure=failure):
                lua = runtime()
                lua.execute("""
                    local link=World.link_particles
                    World.link_particles=function(...)
                        link(...); delete_weapon()
                """ + failure + " end")
                lua.execute("""
                    assert(not start())
                    assert(events.created==1 and events.queried==0 and events.destroyed==0)
                    assert(effects[events.latest_id].foreign)
                    assert(not next(mod._doomrocket_crystal_flame_state.entries))
                    assert(not next(mod._doomrocket_crystal_flame_state.creating_worlds))
                    assert(events.unloads==0)
                    mod._release_warlock_crystal_flame_world(world)
                    world.alive=false; wm._worlds.level_world=nil
                    mod._reset_warlock_crystal_flame('world_gone')
                    assert(events.unloads==1 and events.queried==0 and events.destroyed==0)
                """)

    def test_release_during_native_create_or_link_makes_no_further_particle_call(self):
        for boundary in ("create_particles", "link_particles"):
            for failure in ("error('native wrapper failed after releasing world')", "return result"):
                with self.subTest(boundary=boundary, failure=failure):
                    lua = runtime()
                    lua.execute("""
                        local native=World[""" + repr(boundary) + """]
                        World[""" + repr(boundary) + """]=function(...)
                            local result=native(...)
                            mod._release_warlock_crystal_flame_world(world)
                            world.alive=false; wm._worlds.level_world=nil
                    """ + failure + " end")
                    lua.execute("""
                        assert(not start())
                        assert(events.created==1 and events.queried==0 and events.destroyed==0)
                        assert(not next(mod._doomrocket_crystal_flame_state.entries))
                        assert(not next(mod._doomrocket_crystal_flame_state.creating_worlds))
                        assert(events.unloads==1 and refs.global==3)
                    """)

    def test_reset_death_or_drop_during_load_create_or_link_cancels_pending_owner(self):
        actions = (
            "mod._reset_warlock_crystal_flame('reentrant_reset')",
            "assert(mod._stop_warlock_crystal_flame(owner,'reentrant_death'))",
            "assert(mod._stop_warlock_crystal_flame_item(owner,weapon,'reentrant_drop'))",
        )
        for boundary in ("pm.load", "World.create_particles", "World.link_particles"):
            for action in actions:
                with self.subTest(boundary=boundary, action=action):
                    lua = runtime()
                    lua.execute("local native=" + boundary + "\n" + boundary + """=function(...)
                            local result=native(...)
                    """ + action + """
                            assert(events.unloads==0, 'pending operation must retain residency')
                            return result
                        end
                        assert(not start(), 'reset/death/drop cancels the pending emitter')
                        assert(count()==0)
                        assert(events.unloads==1 and refs.global==3 and not refs[package_reference])
                        local s=mod._doomrocket_crystal_flame_state
                        assert(not next(s.entries) and not next(s.weapons))
                        assert(not next(s.creating_worlds))
                        assert(not next(s.pending_owners) and not next(s.pending_weapons))
                    """)
                    events = lua.globals().events
                    self.assertEqual(events.created, int(boundary != "pm.load"))
                    self.assertEqual(events.destroyed, events.created)
                    self.assertEqual(events.linked, int(boundary == "World.link_particles"))

    def test_pre_release_hook_during_create_or_link_retains_package_until_world_is_gone(self):
        for boundary in ("create_particles", "link_particles"):
            for failure in ("error('wrapper failed after pre-release hook')", "return result"):
                with self.subTest(boundary=boundary, failure=failure):
                    lua = runtime()
                    lua.execute("""
                        local native=World[""" + repr(boundary) + """]
                        World[""" + repr(boundary) + """]=function(...)
                            local result=native(...)
                            mod._release_warlock_crystal_flame_world(world)
                    """ + failure + " end")
                    lua.execute("""
                        assert(not start())
                        assert(events.created==1 and events.queried==0 and events.destroyed==0)
                        assert(events.unloads==0 and refs[package_reference]==1)
                        assert(mod._doomrocket_crystal_flame_state.releasing_worlds[world])
                        assert(not next(mod._doomrocket_crystal_flame_state.creating_worlds))
                        assert(not start() and events.created==1)
                        world.alive=false; wm._worlds.level_world=nil
                        mod._reset_warlock_crystal_flame('released_world')
                        assert(events.unloads==1 and events.queried==0 and events.destroyed==0)
                    """)

    def test_failed_link_cleanup_holds_residency_until_world_release(self):
        lua = runtime()
        lua.execute("""
            World.link_particles=function() error('native link failed') end
            World.are_particles_playing=function() error('native query failed') end
            assert(not start())
            assert(events.created==1 and events.unloads==0 and refs[package_reference]==1)
            assert(mod._doomrocket_crystal_flame_state.unknown_worlds[world])
            assert(not start() and events.created==1)
            mod._release_warlock_crystal_flame_world(world)
            assert(events.unloads==0 and events.destroyed==0)
            world.alive=false; wm._worlds.level_world=nil
            mod._reset_warlock_crystal_flame('world_gone')
            assert(events.unloads==1 and refs.global==3)
        """)

    def test_repeated_failure_diagnostics_are_bounded(self):
        lua = runtime()
        lua.execute("""
            particles_available=false
            for i=1,20 do assert(not start()) end
            assert(#logs==1 and logs[1]:find('reason=effect_unavailable',1,true))
            assert(events.created==0 and events.loads==20 and events.unloads==20)
        """)


class CrystalFlameWiringTests(unittest.TestCase):
    def test_bootstrap_loads_anchor_then_controller_and_drives_update_and_reset(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        anchor = source.index('mod._doomrocket_crystal_anchor = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_crystal_anchor")')
        controller = source.index('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_crystal_flame")')
        self.assertLess(anchor, controller)
        self.assertIn("mod._update_warlock_crystal_flame()", source)
        self.assertIn('mod._reset_warlock_crystal_flame(reason or "runtime_reset")', source)

    def test_every_smoke_lifecycle_boundary_also_ends_the_flame(self):
        hooks = HOOKS.read_text(encoding="utf-8")
        for call in (
            "mod._start_warlock_crystal_flame(unit, self)",
            'mod._stop_warlock_crystal_flame(self.unit, "inventory_destroy")',
            'mod._stop_warlock_crystal_flame(self.unit, "inventory_freeze")',
            'mod._stop_warlock_crystal_flame_item(self.unit, item_unit, "inventory_drop")',
            'mod._stop_warlock_crystal_flame_item(self.unit, item_unit, "inventory_disable_item")',
            "mod._release_warlock_crystal_flame_world(world)",
            'mod._stop_warlock_crystal_flame(owner_unit, "death_" .. tostring(source))',
        ):
            with self.subTest(call=call):
                self.assertEqual(hooks.count(call), 1)


class CrystalAnchorTests(unittest.TestCase):
    def anchor(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        table = lua.execute(ANCHOR.read_text(encoding="utf-8"))
        return {key: list(table[key].values()) if key != "node" else table[key]
                for key in ("node", "x_axis", "y_axis", "z_axis", "position")}

    def test_anchor_is_the_measured_tip_frame_in_node_units(self):
        # The compiled node is a scale-100 frame at the root with a rotation of
        # about 1.6e-5 rad, so the node-local frame is 0.01 x the root frame.
        anchor = self.anchor()
        self.assertEqual(anchor["node"], FIXTURE["target_node"])
        for key, source in (("x_axis", "frame_x_axis"), ("y_axis", "frame_y_axis"),
                            ("z_axis", "frame_z_axis"), ("position", "tip_engine_m")):
            for actual, expected in zip(anchor[key], FIXTURE[source]):
                self.assertAlmostEqual(actual, expected * 0.01, delta=2e-8, msg=key)
        x, y, z = anchor["x_axis"], anchor["y_axis"], anchor["z_axis"]
        cross = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
        self.assertGreater(sum(c * w for c, w in zip(cross, z)), 0, "anchor frame must stay right-handed")
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in x)), 0.01, delta=1e-9)

    @unittest.skipUnless(BUNDLE_ROOT.is_dir() and any(BUNDLE_ROOT.glob("*.mod_bundle")), "compiled bundleV2 is not present")
    def test_anchor_regenerates_from_the_compiled_launcher_node(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/build_crystal_anchor.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
