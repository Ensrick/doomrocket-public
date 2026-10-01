#!/usr/bin/env python3
"""Execute shipping hose controller with strict native lifetime doubles.

This is not a rendered game session. Matrix/vector temporaries expire when the
test advances a frame, unit/world APIs reject stale handles, and writes to the
carrier, outfit or launcher are fatal. The actual Lua solver/frame builder run.
"""
from pathlib import Path
import re
import sys
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'scripts/mods/doomrocket/extensions/doomrocket_hose.lua'
UTILS = ROOT / 'scripts/mods/doomrocket/utils'
HOOKS = UTILS / 'hooks.lua'
BOOTSTRAP = ROOT / 'scripts/mods/doomrocket/doomrocket.lua'
sys.path.insert(0, str(ROOT / 'tools'))
from analyze_hose_log import analyze

HARNESS = r'''
epoch=1
events={spawn_attempts=0,spawned=0,destroyed=0,poses=0,updated=0,materials=0,queued=0,reads=0}
messages={}
function printf(...) messages[#messages+1]=string.format(...) end
local function current(v)
 assert(v and (not v.epoch or v.epoch==epoch),'expired native temporary')
 return v
end
local function vec(x,y,z)
 local values={x=x,y=y,z=z,[1]=x,[2]=y,[3]=z}
 return setmetatable({epoch=epoch},{__index=function(v,key)
  current(v);return values[key]
 end})
end
Vector3=setmetatable({
 x=function(v) return current(v).x end,
 y=function(v) return current(v).y end,
 z=function(v) return current(v).z end,
 zero=function() return vec(0,0,0) end,
 up=function() return vec(0,0,1) end,
 length=function(v) current(v); return math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z) end,
 dot=function(a,b) current(a);current(b);return a.x*b.x+a.y*b.y+a.z*b.z end,
 cross=function(a,b) current(a);current(b);return vec(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x) end,
 distance=function(a,b) current(a);current(b);return math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+(a.z-b.z)^2) end,
}, {__call=function(_,x,y,z) return vec(x,y,z) end})
local function fresh(m)
 current(m); local out={epoch=epoch}
 for r=1,4 do out[r]={}; for c=1,4 do out[r][c]=m[r][c] end end
 return out
end
local function identity(scale,x,y,z)
 local m={epoch=epoch};scale=scale or 1
 for r=1,4 do m[r]={}; for c=1,4 do m[r][c]=r==c and (r==4 and 1 or scale) or 0 end end
 m[1][4]=x or 0;m[2][4]=y or 0;m[3][4]=z or 0
 return m
end
local function stored(m) local out=fresh(m);out.epoch=nil;return out end
local function mm(a,b)
 current(a);current(b);local out=identity()
 for r=1,4 do for c=1,4 do
  local v=0;for k=1,4 do v=v+a[r][k]*b[k][c] end;out[r][c]=v
 end end
 return out
end
local function inv(a)
 current(a);local x={};for r=1,4 do
 x[r]={};for c=1,8 do x[r][c]=c<=4 and a[r][c] or (c-4==r and 1 or 0) end
 end
 for c=1,4 do
  local p=c;for r=c+1,4 do if math.abs(x[r][c])>math.abs(x[p][c]) then p=r end end
  assert(math.abs(x[p][c])>1e-15,'native singular matrix inverse')
  x[c],x[p]=x[p],x[c];local d=x[c][c]
  for k=1,8 do x[c][k]=x[c][k]/d end
  for r=1,4 do if r~=c then local v=x[r][c];for k=1,8 do x[r][k]=x[r][k]-v*x[c][k] end end end
 end
 local out=identity();for r=1,4 do for c=1,4 do out[r][c]=x[r][c+4] end end;return out
end
Matrix4x4={
 identity=identity,
 is_valid=function(m)
  current(m);for r=1,4 do for c=1,4 do
   local v=m[r][c];if v~=v or math.abs(v)==math.huge then return false end
  end end;return true
 end,
 copy=fresh,
 x=function(m) current(m);return vec(m[1][1],m[2][1],m[3][1]) end,
 y=function(m) current(m);return vec(m[1][2],m[2][2],m[3][2]) end,
 z=function(m) current(m);return vec(m[1][3],m[2][3],m[3][3]) end,
 translation=function(m) current(m);return vec(m[1][4],m[2][4],m[3][4]) end,
 set_x=function(m,v) current(m);current(v);m[1][1]=v.x;m[2][1]=v.y;m[3][1]=v.z end,
 set_y=function(m,v) current(m);current(v);m[1][2]=v.x;m[2][2]=v.y;m[3][2]=v.z end,
 set_z=function(m,v) current(m);current(v);m[1][3]=v.x;m[2][3]=v.y;m[3][3]=v.z end,
 set_translation=function(m,v) current(m);current(v);m[1][4]=v.x;m[2][4]=v.y;m[3][4]=v.z end,
 -- Stingray API uses row-vector products: reverse for this column-matrix double.
 multiply=function(a,b) return mm(b,a) end,
 inverse=inv,
 transform=function(m,v)
  current(m);current(v)
  return vec(m[1][1]*v.x+m[1][2]*v.y+m[1][3]*v.z+m[1][4],
   m[2][1]*v.x+m[2][2]*v.y+m[2][3]*v.z+m[2][4],
   m[3][1]*v.x+m[3][2]*v.y+m[3][3]*v.z+m[3][4])
 end,
}
function Matrix4x4Box(m)
 local box={value=stored(m or identity())}
 function box:store(v) self.value=stored(v) end
 function box:unbox() return fresh(self.value) end
 return box
end
function Vector3Box(x,y,z)
 local v=type(x)=='table' and current(x) or vec(x or 0,y or 0,z or 0)
 local box={x=v.x,y=v.y,z=v.z}
 function box:store(a,b,c)
  local v=type(a)=='table' and current(a) or vec(a,b,c);self.x=v.x;self.y=v.y;self.z=v.z
 end
 function box:unbox() return vec(self.x,self.y,self.z) end
 return box
end
Quaternion={identity=function() return {0,0,0,1} end}
world={alive=true};other_world={alive=true}
local function check_world(w) assert(w and w.alive,'released world touched') end
local function check_unit(u)
 assert(u and u.alive,'dead unit touched');check_world(u.world);events.reads=events.reads+1
end
outfit_name='units/warlock_bombardier/warlock_bombardier_3p'
weapon_name='units/rocket/pRocketLauncher'
hose_name='units/warlock_hose/warlock_hose'
function new_unit(name,w)
 return {alive=true,name=name,world=w or world,nodes={},pose=stored(identity()),visible=true}
end
function new_owner() return new_unit('carrier') end
function new_outfit()
 local u=new_unit(outfit_name);u.nodes.j_backpack=25
 u.pose=stored(identity(100,0,0,1));return u
end
function new_weapon()
 local u=new_unit(weapon_name);u.nodes.pRocketLauncher=7
 u.pose=stored(identity(100,.5,0,1));u.extension={dropped=false};return u
end
owner=new_owner();outfit=new_outfit();weapon=new_weapon()
weapon.extension.wielding_unit=owner
inventory={unit=owner,world=world,inventory_item_units={outfit,weapon},
 inventory_item_outfit_units={outfit},inventory_item_weapon_units={weapon},
 inventory_item_units_by_category={doomrocket_inventory=weapon},dropped=false,
 inventory_item_definitions={{unit_extension_template='ai_outfit_unit',drop_reasons={death=true}},
  {unit_extension_template='ai_inventory_item',drop_reasons={death=true}}},dropped_items={},
 inventory_items_n=2,hidden_item_index=nil}
owner.inventory=inventory
Unit={
 alive=function(u) return u and u.alive or false end,
 world=function(u) check_unit(u);return u.world end,
 get_data=function(u,key) check_unit(u);if key=='unit_name' then return u.name end; return u[key] end,
 set_data=function(u,key,value) check_unit(u);assert(u.name==hose_name);u[key]=value end,
 has_node=function(u,node) check_unit(u);return node==0 or u.nodes[node]~=nil end,
 node=function(u,node) check_unit(u);assert(u.nodes[node]~=nil,'unsafe node lookup');return u.nodes[node] end,
 world_pose=function(u,node) check_unit(u);assert(type(node)=='number');return fresh(u.pose) end,
 local_pose=function(u,node) check_unit(u);assert(type(node)=='number');return fresh(u.local_poses and u.local_poses[node] or u.pose) end,
 world_position=function(u,node) check_unit(u);return Matrix4x4.translation(u.pose) end,
 scene_graph_parent=function(u,node) check_unit(u);return u.bad_parent and 99 or (node==1 and 0 or 1) end,
 num_actors=function(u) check_unit(u);return u.actor_count or 0 end,
 set_unit_visibility=function(u,value) check_unit(u);assert(u.name==hose_name,'changed source visibility');u.visible=value end,
 set_local_pose=function(u,node,pose)
  check_unit(u);current(pose);assert(u.name==hose_name,'wrote source bone');assert(type(node)=='number')
  u.local_poses=u.local_poses or {};u.local_poses[node]=stored(pose);events.poses=events.poses+1
 end,
 set_local_position=function(u,node,v)
  check_unit(u);current(v);assert(u.name==hose_name,'moved source');assert(node==0)
  u.pose[1][4]=v.x;u.pose[2][4]=v.y;u.pose[3][4]=v.z
 end,
 -- The production hose has a skin but no animation blender/controller (#20).
 -- These APIs must not silently succeed for it in the native test double.
 set_animation_bone_mode=function(u,mode) check_unit(u);error('hose has no animation blender') end,
 set_bones_lod=function(u,lod) check_unit(u);error('hose has no animation blender') end,
 disable_animation_state_machine=function(u) check_unit(u);error('hose has no animation state machine') end,
 set_material=function(u,slot,name) check_unit(u);assert(u.name==hose_name);events.materials=events.materials+1 end,
}
World={
 spawn_unit=function(w,name,position,rotation)
  events.spawn_attempts=events.spawn_attempts+1
  check_world(w);assert(name==hose_name);if position then current(position) end
  if position then for i=1,3 do
   assert(position[i]==position[i] and math.abs(position[i])<=1e6,'unsafe world spawn location')
  end end
  if spawn_failure then return nil end
  if spawn_dead_unit then return {alive=false} end
  local u=new_unit(name,w);u.nodes.hose_root=1;u.actor_count=spawn_actor_count or 0
  if position then u.pose=stored(identity(1,position.x,position.y,position.z)) end
  for i=0,28 do u.nodes[string.format('j_hose_%02d',i)]=i+2 end
  if missing_hose_node then u.nodes[missing_hose_node]=nil end
  u.bad_parent=spawn_bad_parent;events.spawned=events.spawned+1;last_hose=u;return u
 end,
 destroy_unit=function(w,u)
  check_world(w);check_unit(u);assert(u.world==w and u.name==hose_name,'wrong unit/world destroyed')
  u.alive=false;events.destroyed=events.destroyed+1;if on_destroy then on_destroy(u) end
 end,
 update_unit=function(w,u) check_world(w);check_unit(u);assert(u.world==w and u.name==hose_name);events.updated=events.updated+1 end,
 get_data=function(w,key) check_world(w);return w[key] end,
}
wm={_worlds={level_world=world},_disabled_worlds={}}
function wm:has_world(name) return self._worlds[name]~=nil end
function wm:world(name) assert(self._worlds[name]);return self._worlds[name] end
callbacks={}
animation={}
function animation:add_safe_animation_callback(fn)
 callbacks[#callbacks+1]=fn;events.queued=events.queued+1
end
entity={}
function entity:system(name) assert(name=='animation_system');return animation end
Managers={world=wm,state={entity=entity},time={time=function() return epoch/60 end}}
Application={can_get=function(kind,name) return not unavailable_resource end,
 time_since_launch=function() return epoch/60 end}
ScriptUnit={has_extension=function(u,kind)
 check_unit(u);if kind=='ai_inventory_item_system' then return u.extension end
 if kind=='ai_inventory_system' then return u.inventory end
end}
ScriptUnit.extension=ScriptUnit.has_extension
mod={_warlock_outfits={[owner]=outfit}}
-- Shared hooks also notify the independent visible gait controller. Its native
-- variable/lifetime contract is exercised in test_doomrocket_locomotion_animation.py;
-- retain the strict hose engine doubles and all hose assertions in this harness.
mod._start_warlock_locomotion_animation=function() end
mod._stop_warlock_locomotion_animation=function() end
mod._reset_warlock_locomotion_animation=function() end
mod._release_warlock_locomotion_world=function() end
mod._update_warlock_locomotion_animation=function() end
function mod:package_status(name)
 assert(name=='resource_packages/doomrocket/warlock_child')
 return unavailable_package and 'not_loaded' or 'loaded'
end
function get_mod(name) assert(name=='doomrocket');return mod end
function start(o,u,inv) return mod._start_warlock_hose(o or owner,u or outfit,inv or inventory) end
function stop(reason) return mod._stop_warlock_hose(owner,reason or 'test') end
function queue(w,dt) return mod._queue_warlock_hose(w or world,dt or 1/60) end
function reset(reason) return mod._reset_warlock_hose(reason or 'test') end
function drain()
 local todo=callbacks;callbacks={};for i=1,#todo do todo[i]() end
end
function tick(dt)
 epoch=epoch+1;queue(world,dt or 1/60);drain()
end
function record_count()
 local n=0;for _ in pairs(mod._doomrocket_hose_state.entries) do n=n+1 end;return n
end
function disable_world() wm._worlds.level_world=nil;wm._disabled_worlds.level_world=world end
function resume_world() wm._disabled_worlds.level_world=nil;wm._worlds.level_world=world end
function release_world()
 world.alive=false;wm._worlds.level_world=nil;wm._disabled_worlds.level_world=nil
 if last_hose then last_hose.alive=false end
end
'''


class HoseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(HARNESS)
        for name in ('profile', 'solver', 'frames'):
            self.lua.globals().mod['_doomrocket_hose_' + name] = self.lua.execute(
                (UTILS / ('doomrocket_hose_' + name + '.lua')).read_text(encoding='utf-8'))
        self.source = MODULE.read_text(encoding='utf-8')
        self.lua.execute(self.source)

    def test_spawn_without_animation_blender_updates_skin_and_cleans_up(self):
        self.lua.execute('''
            assert(start());tick()
            assert(events.spawned==1 and events.materials==1 and last_hose.visible)
            assert(events.poses==30 and events.updated==1)
            for node=2,30 do assert(last_hose.local_poses[node]) end
            tick();assert(events.poses==60 and events.updated==2)
            assert(stop('death_host') and events.destroyed==1 and record_count()==0)
            assert(owner.alive and outfit.alive and weapon.alive)
        ''')

    def diagnostic_report(self):
        text = '[doomrocket:LOAD] v0.1.73-dev\n' + self.lua.eval("table.concat(messages,'\\n')")
        return analyze(text, '0.1.73-dev')['hoses']['1']

    def test_diagnostics_prove_pose_updates_without_claiming_rendered_pixels(self):
        self.lua.execute("assert(start()); for i=1,240 do tick() end; stop('death_unit')")
        report = self.diagnostic_report()
        self.assertTrue(report['pose_write_observed'])
        self.assertTrue(report['sample_observed'])
        self.assertEqual(int(report['stop']['writes']), 240)
        self.assertEqual(int(report['stop']['callbacks']), 240)
        self.assertIn('visible rendering needs visual evidence', report['finding'])

    def test_rejected_endpoint_reports_scale_once_and_preserves_failure_guard(self):
        self.lua.execute('''
            assert(start());tick()
            outfit.pose[1][1]=1;outfit.pose[2][2]=1;outfit.pose[3][3]=1
            for i=1,240 do tick() end
            stop('death_unit')
        ''')
        report = self.diagnostic_report()
        self.assertEqual(len(report['diagnostics']), 1)
        self.assertEqual(report['diagnostics'][0]['reason'], 'pack_pose_rejected')
        self.assertIn('scale', report['diagnostics'][0])
        self.assertEqual(int(report['stop']['writes']), 1)
        self.assertEqual(report['stop']['last_reason'], 'pack_pose_rejected')

    def test_native_size_variation_keeps_hose_alive_after_first_animation_frame(self):
        self.lua.execute('''
            assert(start());tick()
            local visual=last_hose
            -- v0.1.76 rejected the backpack's 1.1 scale after its first write.
            -- Exercise that native spawn-scale transition on both endpoints.
            for _,u in ipairs({outfit,weapon}) do
                for axis=1,3 do u.pose[axis][axis]=110 end
            end
            for i=1,240 do tick() end
            local entry=mod._doomrocket_hose_state.entries[owner]
            assert(entry.visual==visual and visual.visible)
            assert(events.spawned==1 and events.destroyed==0)
            assert(entry.written_frames==241 and entry.solver.steps>0)
            for _,frame in ipairs({entry.pack,entry.weapon_frame}) do
                for _,axis in ipairs({'x_axis','y_axis','z_axis'}) do
                    local v=frame[axis]
                    assert(math.abs(v[1]^2+v[2]^2+v[3]^2-1)<1e-6)
                end
            end
            -- The correction must not resize the 100x compiled control bind
            -- or change the authored segment lengths / physical dynamics.
            local parent=Matrix4x4.multiply(entry.parent_to_root:unbox(),Unit.local_pose(visual,0))
            local pose=Matrix4x4.multiply(Unit.local_pose(visual,visual.nodes.j_hose_00),parent)
            assert(math.abs(Vector3.length(Matrix4x4.x(pose))-100)<.001)
            local length=0
            for _,value in ipairs(mod._doomrocket_hose_profile.lengths) do length=length+value end
            assert(entry.solver.length==length)
            stop('death_unit')
            assert(events.destroyed==1)
        ''')
        report = self.diagnostic_report()
        self.assertEqual(report['diagnostics'], [])
        self.assertTrue(report['sample_observed'])
        self.assertEqual(int(report['stop']['writes']), 241)

    def test_size_variation_normalizes_orientation_without_moving_endpoint(self):
        self.lua.execute('''
            -- Rotate both endpoint parents 90 degrees and translate far from
            -- the world origin: stripping scale must never divide translation.
            for _,u in ipairs({outfit,weapon}) do
                u.pose[1][1]=0;u.pose[1][2]=-110
                u.pose[2][1]=110;u.pose[2][2]=0;u.pose[3][3]=110
                u.pose[1][4]=u.pose[1][4]+288
                u.pose[2][4]=-300;u.pose[3][4]=5
            end
            assert(start());tick()
            local entry=mod._doomrocket_hose_state.entries[owner]
            for _,item in ipairs({
                {unit=outfit,node=entry.pack_node,offset=entry.pack_local,frame=entry.pack},
                {unit=weapon,node=entry.weapon_node,offset=entry.weapon_local,frame=entry.weapon_frame}
            }) do
                local expected=Matrix4x4.multiply(item.offset:unbox(),Unit.world_pose(item.unit,item.node))
                local position=Matrix4x4.translation(expected)
                local x,y,z=Matrix4x4.x(expected),Matrix4x4.y(expected),Matrix4x4.z(expected)
                for i=1,3 do
                    assert(math.abs(item.frame.position[i]-position[i])<1e-9)
                    assert(math.abs(item.frame.x_axis[i]-x[i]/Vector3.length(x))<1e-9)
                    assert(math.abs(item.frame.y_axis[i]-y[i]/Vector3.length(y))<1e-9)
                    assert(math.abs(item.frame.z_axis[i]-z[i]/Vector3.length(z))<1e-9)
                end
            end
            assert(last_hose.visible and entry.written_frames==1)
        ''')

    def test_size_variation_does_not_admit_invalid_endpoint_frames(self):
        mutations = {
            'nonuniform': 'u.pose[1][1]=110;u.pose[2][2]=105;u.pose[3][3]=110',
            'shear': 'u.pose[1][1]=110;u.pose[2][2]=110;u.pose[3][3]=110;u.pose[1][2]=11',
            'reflection': 'u.pose[1][1]=-110;u.pose[2][2]=110;u.pose[3][3]=110',
            'zero': 'u.pose[1][1]=0',
            'nan': 'u.pose[1][1]=0/0',
            'infinity': 'u.pose[1][1]=math.huge',
            'uncancelled_wrapper': 'u.pose[1][1]=10000;u.pose[2][2]=10000;u.pose[3][3]=10000',
            'unsupported_scale': 'u.pose[1][1]=150;u.pose[2][2]=150;u.pose[3][3]=150',
            'invalid_position': 'u.pose[1][4]=math.huge',
        }
        for endpoint in ('outfit', 'weapon'):
            for name, mutation in mutations.items():
                with self.subTest(endpoint=endpoint, mutation=name):
                    self.setUp()
                    self.lua.execute('assert(start());tick();local u=' + endpoint + ';' + mutation)
                    self.lua.execute('''
                        for i=1,10 do tick() end
                        local entry=mod._doomrocket_hose_state.entries[owner]
                        assert(entry.written_frames==1)
                        assert(entry.visual==nil and events.destroyed==1 and events.spawned==1)
                    ''')
                    report = self.diagnostic_report()
                    reason = 'pack_pose_rejected' if endpoint == 'outfit' else 'weapon_pose_rejected'
                    self.assertEqual([event['reason'] for event in report['diagnostics']], [reason])

    def test_lost_visual_is_reported_without_respawning_or_touching_dead_handle(self):
        self.lua.execute('''
            assert(start());tick();last_hose.alive=false
            for i=1,240 do tick() end
            stop('death_unit');assert(events.spawned==1 and events.destroyed==0)
        ''')
        report = self.diagnostic_report()
        self.assertEqual([event['reason'] for event in report['diagnostics']], ['visual_dead'])
        self.assertEqual(int(report['stop']['writes']), 1)

    def test_start_only_legacy_log_does_not_establish_simulation_or_visibility(self):
        report = analyze('[doomrocket:LOAD] v0.1.72-dev\n'
                         '[doomrocket:HOSE] phase=start id=1 controls=29\n'
                         '[doomrocket:HOSE] phase=stop id=1 reason=death_unit', '0.1.72-dev')
        self.assertEqual(report['hoses']['1']['finding'],
                         'No completed pose-update evidence; cause unresolved.')
        with self.assertRaises(ValueError):
            analyze('[doomrocket:LOAD] v0.1.72-dev', '0.1.73-dev')

    def test_one_cosmetic_per_owner_duplicate_is_idempotent(self):
        self.lua.execute('''
            assert(start());tick();assert(start());tick();assert(record_count()==1 and events.spawned==1)
            tick();tick();assert(events.poses>0 and events.updated>0)
            assert(owner.alive and outfit.alive and weapon.alive)
        ''')

    def test_each_peer_has_only_local_owned_hose(self):
        self.lua.execute('''
            assert(start());tick();owner.is_server=true
            local o=new_owner();o.is_server=false
            local b=new_outfit();local w=new_weapon();w.extension.wielding_unit=o
            local inv={unit=o,world=world,inventory_item_units={b,w},
                inventory_item_weapon_units={w},inventory_item_outfit_units={b}}
            o.inventory=inv;mod._warlock_outfits[o]=b
            assert(start(o,b,inv));tick();assert(record_count()==2 and events.spawned==2)
            tick();reset('test_complete')
            assert(events.destroyed==2 and record_count()==0)
        ''')

    def test_outfit_cannot_be_claimed_by_another_owner(self):
        self.lua.execute('''
            assert(start());tick();local o=new_owner();assert(not start(o,outfit,inventory))
            assert(events.spawned==1 and record_count()==1)
        ''')

    def test_pending_world_callback_is_deduplicated(self):
        self.lua.execute('''
            assert(start());tick();queue();queue();queue()
            assert(#callbacks==1);local queued=events.queued;drain()
            assert(#callbacks==0 and events.queued==queued,'callback re-enqueued itself')
            local writes=events.poses;queue(other_world);drain()
            assert(events.poses==writes,'foreign world advanced hose')
        ''')

    def test_stop_cancels_pending_callback_and_is_idempotent(self):
        self.lua.execute('''
            assert(start());tick();queue();local writes=events.poses
            stop('death_unit');stop('death_husk');drain();reset()
            assert(record_count()==0 and events.destroyed==1 and events.poses==writes)
            assert(not start(),'dead owner was re-registered')
        ''')

    def test_stop_claims_ownership_before_native_reentrancy(self):
        self.lua.execute('''
            assert(start());tick();on_destroy=function() stop('reentrant') end
            stop('outer');assert(events.destroyed==1 and record_count()==0)
        ''')

    def test_replacing_outfit_destroys_old_hose_before_new_one(self):
        self.lua.execute('''
            assert(start());tick();queue();local old_hose=last_hose
            outfit=new_outfit();inventory.inventory_item_units[1]=outfit
            inventory.inventory_item_outfit_units={outfit};mod._warlock_outfits[owner]=outfit
            assert(start());tick();drain();assert(not old_hose.alive and last_hose~=old_hose)
            assert(events.spawned==2 and events.destroyed==1 and record_count()==1)
            tick()
        ''')

    def test_inventory_weapon_replacement_invalidates_old_endpoints(self):
        self.lua.execute('''
            assert(start());tick();queue();local old_hose=last_hose
            local replacement=new_weapon();replacement.extension.wielding_unit=owner
            inventory.inventory_item_units[2]=replacement
            inventory.inventory_item_weapon_units={replacement}
            inventory.inventory_item_units_by_category.doomrocket_inventory=replacement
            drain();assert(not old_hose.alive and record_count()==0)
        ''')

    def test_dropped_weapon_never_keeps_live_tether(self):
        for mutation in ('weapon.extension.dropped=true',
                         'weapon.extension.wielding_unit=nil',
                         'inventory.dropped=true'):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.lua.execute('assert(start());tick();queue();' + mutation + '''
                    drain();assert(record_count()==0 and events.destroyed==1)
                ''')

    def test_destroyed_source_handles_are_not_read(self):
        for target in ('owner', 'outfit', 'weapon'):
            with self.subTest(target=target):
                self.setUp()
                self.lua.execute('assert(start());tick();queue();' + target + '''.alive=false
                    drain();assert(record_count()==0 and events.destroyed==1)
                ''')

    def test_deleted_cosmetic_is_not_destroyed_twice_or_replaced_per_frame(self):
        self.lua.execute('''
            assert(start());tick();last_hose.alive=false;tick();tick();reset()
            assert(record_count()==0 and events.destroyed==0 and events.spawned==1)
        ''')

    def test_world_release_invalidates_before_native_release_without_native_cleanup(self):
        self.lua.execute('''
            assert(start());tick();queue();local writes=events.poses
            mod._release_warlock_hose(world);assert(record_count()==0)
            assert(events.destroyed==0);release_world();drain();reset()
            assert(events.destroyed==0 and events.poses==writes)
        ''')

    def test_unknown_world_does_not_invoke_native_cleanup(self):
        self.lua.execute('''
            assert(start());tick();queue();wm._worlds.level_world=nil
            world.alive=false;drain();reset()
            assert(record_count()==0 and events.destroyed==0)
        ''')

    def test_replaced_active_world_never_reads_old_unit_or_world_handles(self):
        self.lua.execute('''
            assert(start());tick();world.alive=false
            wm._worlds.level_world=other_world
            queue(other_world,1/60);drain()
            assert(record_count()==0 and events.destroyed==0)
        ''')

    def test_unknown_live_world_cannot_return_with_unowned_duplicate_hose(self):
        self.lua.execute('''
            assert(start());tick();local old_hose=last_hose
            wm._worlds.level_world=nil;reset('unknown_world')
            assert(old_hose.alive and events.destroyed==0)
            wm._worlds.level_world=world
            start();tick();assert(events.spawned==1,'orphan plus replacement in same world')
        ''')

    def test_unknown_world_quarantine_survives_module_reload(self):
        self.lua.execute('''
            assert(start());tick();wm._worlds.level_world=nil;reset('unknown_world')
        ''')
        self.lua.execute(self.source)
        self.lua.execute('''
            wm._worlds.level_world=world;start();tick()
            assert(events.spawned==1 and events.destroyed==0,'reload forgot orphan quarantine')
        ''')

    def test_other_world_release_does_not_touch_hose(self):
        self.lua.execute('''
            assert(start());tick();mod._release_warlock_hose(other_world)
            assert(record_count()==1 and events.destroyed==0);tick()
        ''')

    def test_paused_world_retains_hose_and_cleans_up_without_duplicate(self):
        self.lua.execute('''
            assert(start());tick();tick();disable_world();queue(world,0);drain()
            assert(record_count()==1 and events.spawned==1)
            resume_world();tick();assert(start());tick();assert(events.spawned==1)
            disable_world();reset();assert(events.destroyed==1)
        ''')

    def test_paused_dt_does_not_advance_actual_solver(self):
        self.lua.execute('''
            assert(start());tick();tick();local state=mod._doomrocket_hose_state
            local solver=state.entries[owner].solver;local steps=solver.steps
            queue(world,0);drain();assert(solver.steps==steps)
            tick();assert(solver.steps>steps)
        ''')

    def test_reset_and_restart_never_reuses_old_queued_callback(self):
        self.lua.execute('''
            assert(start());tick();queue();reset('disabled');assert(start())
            local writes=events.poses;drain();assert(events.poses==writes)
            tick();assert(events.poses>writes and events.spawned==2 and events.destroyed==1)
        ''')

    def test_hot_reload_disposes_owned_hose_and_cancels_old_closure(self):
        self.lua.execute('assert(start());tick();queue()')
        self.lua.execute(self.source)
        self.lua.execute('''
            assert(record_count()==0 and events.destroyed==1);local writes=events.poses
            drain();assert(events.poses==writes);assert(start());tick();tick()
            assert(events.spawned==2)
        ''')

    def test_resource_failure_does_not_spawn_or_retry_every_callback(self):
        self.lua.execute('''
            unavailable_resource=true;assert(start());tick();tick()
            assert(events.spawned==0 and record_count()==1)
            unavailable_resource=false;tick();assert(events.spawned==1)
            tick();assert(events.spawned==1)
        ''')

    def test_start_registers_only_and_never_spawns_inside_inventory_setup(self):
        self.lua.execute('''
            assert(start());assert(record_count()==1 and events.spawned==0)
            queue();assert(events.spawned==0);drain();assert(events.spawned==1)
        ''')

    def test_missing_animation_system_does_not_spawn_outside_safe_phase(self):
        self.lua.execute('''
            assert(start());Managers.state.entity=nil;queue();drain()
            assert(events.spawned==0 and events.poses==0)
            Managers.state.entity=entity;tick();assert(events.spawned==1)
        ''')

    def test_render_budget_is_bounded_and_deterministic(self):
        self.lua.execute('''
            assert(start());local owners={owner}
            for i=1,19 do
                local o=new_owner();local b=new_outfit();local w=new_weapon()
                w.extension.wielding_unit=o
                local inv={unit=o,world=world,inventory_item_units={b,w}}
                o.inventory=inv;mod._warlock_outfits[o]=b
                assert(start(o,b,inv));owners[#owners+1]=o
            end
            assert(record_count()==20);tick();assert(events.spawned==8)
            for i=1,20 do
                local entry=mod._doomrocket_hose_state.entries[owners[i]]
                assert((entry.visual~=nil)==(i<=8),'budget tie order unstable')
            end
            for i=1,60 do tick() end
            assert(events.spawned==8 and events.destroyed==0,'budget causes spawn/destroy churn')
            reset();assert(events.destroyed==8)
        ''')

    def test_far_hose_culls_then_restores_with_fresh_simulation(self):
        self.lua.execute('''
            local player_unit=new_unit('player');Managers.player={local_player=function()
                return {player_unit=player_unit}
            end}
            assert(start());tick();assert(events.spawned==1)
            outfit.pose[1][4]=100;weapon.pose[1][4]=100.5;tick()
            assert(events.destroyed==1 and record_count()==1)
            for i=1,10 do tick() end;assert(events.spawned==1)
            outfit.pose[1][4]=0;weapon.pose[1][4]=.5;tick();assert(events.spawned==2)
            tick();assert(last_hose.visible)
        ''')

    def test_bad_sources_rejected_before_spawn(self):
        for mutation in ('owner.alive=false', 'outfit.alive=false', 'weapon.alive=false',
                         "outfit.name='unrelated'", "weapon.name='unrelated'",
                         'outfit.nodes.j_backpack=nil', 'weapon.nodes.pRocketLauncher=nil',
                         'outfit.world=other_world', 'weapon.world=other_world',
                         'owner.world=other_world', 'DEDICATED_SERVER=true'):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.lua.execute(mutation + '''
                    assert(not start());assert(events.spawned==0 and record_count()==0)
                ''')

    def test_bad_asset_actor_node_or_hierarchy_rejected_and_owned_unit_destroyed(self):
        for mutation in ('spawn_actor_count=1', 'spawn_bad_parent=true',
                         "missing_hose_node='j_hose_28'", "missing_hose_node='hose_root'"):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.lua.execute(mutation + '''
                    assert(start());tick();assert(record_count()==1 and events.destroyed==1)
                    assert(mod._doomrocket_hose_state.entries[owner].failed)
                    tick();tick();assert(events.poses==0 and events.spawned==1)
                    reset();assert(record_count()==0 and events.destroyed==1)
                ''')

    def test_native_spawn_failure_is_not_retried_every_animation_frame(self):
        for mutation in ('spawn_failure=true', 'spawn_dead_unit=true'):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.lua.execute(mutation + '''
                    assert(start());tick();assert(events.spawn_attempts==1)
                    assert(mod._doomrocket_hose_state.entries[owner].failed)
                    for i=1,60 do tick() end
                    assert(events.spawn_attempts==1 and events.spawned==0)
                    assert(events.poses==0 and events.destroyed==0)
                    reset();assert(record_count()==0)
                ''')

    def test_nonfinite_live_pose_never_reaches_native_bone_write(self):
        self.lua.execute('''
            assert(start());tick();tick();local writes=events.poses
            outfit.pose[1][1]=0/0;tick();assert(events.poses==writes)
            assert(not last_hose.visible or not last_hose.alive)
        ''')

    def test_finite_but_extreme_world_position_is_rejected_before_native_spawn(self):
        self.lua.execute('''
            assert(start());outfit.pose[1][4]=1e30;tick()
            assert(events.spawned==0 and events.poses==0)
        ''')

    def test_multiple_frames_expire_native_temporaries_without_stale_reuse(self):
        self.lua.execute('''
            assert(start());tick()
            for i=1,180 do
                weapon.pose[1][4]=.5+.1*math.sin(i/30)
                tick()
            end
            assert(events.poses>=180*29 and events.spawned==1)
            reset();assert(events.destroyed==1)
        ''')


class HoseHookIntegrationTests(unittest.TestCase):
    """Execute actual shipping hook bodies, with isolated native side effects."""

    setUp = HoseLifecycleTests.setUp

    def extract_one(self, path, pattern):
        matches = re.findall(pattern, path.read_text(encoding='utf-8'), re.M | re.S)
        self.assertEqual(len(matches), 1, f'Expected one actual shipping callback in {path}')
        return matches[0]

    def load_hook(self, target, method, safe=False, prefix=''):
        self.lua.execute('''
            AIInventoryExtension=AIInventoryExtension or {}
            captured=captured or {}
            function mod:hook(class,name,fn)
                captured[class]=captured[class] or {}
                assert(not captured[class][name]);captured[class][name]=fn
            end
            mod.hook_safe=mod.hook
            mod._stop_warlock_backpack_smoke=function() end
            mod._release_warlock_smoke_world=function() end
            function queue_warlock_death_drivers_for_world(w) end
        ''')
        hook_name = 'hook_safe' if safe else 'hook'
        self.lua.execute(prefix + '\n' + self.extract_one(
            HOOKS, rf'^mod:{hook_name}\({target}, "{method}", function.*?^end\)'))

    def test_inventory_destroy_and_freeze_stop_before_native_unlink(self):
        for method in ('destroy', 'freeze'):
            with self.subTest(method=method):
                self.setUp()
                self.load_hook('AIInventoryExtension', method)
                self.lua.globals().method = method
                self.lua.execute('''
                    assert(start());tick();queue()
                    local calls=0
                    local result=captured[AIInventoryExtension][method](function(self,...)
                        assert(self==inventory and record_count()==0 and events.destroyed==1)
                        outfit.alive=false;weapon.alive=false;calls=calls+1;return 'native_result'
                    end, inventory, 'argument')
                    drain();assert(calls==1 and result=='native_result' and events.destroyed==1)
                ''')

    def test_actual_inventory_setup_registers_host_and_husk_after_native_attachment(self):
        for is_server in (True, False):
            with self.subTest(is_server=is_server):
                self.setUp()
                self.load_hook('AIInventoryExtension', '_setup_configuration')
                self.lua.globals().is_server = is_server
                self.lua.execute('''
                    mod._warlock_outfits={};mod._warlock_carriers={}
                    mod._prune_armor_bridge=function(u) assert(u==owner);events.pruned=true end
                    local function attached(u) assert(u==outfit and u.attached) end
                    local original_mode,original_lod=Unit.set_animation_bone_mode,Unit.set_bones_lod
                    Unit.set_animation_bone_mode=function(u,mode)
                        if u==outfit then attached(u);assert(mode=='transform')
                        else return original_mode(u,mode) end
                    end
                    Unit.set_bones_lod=function(u,lod)
                        if u==outfit then attached(u);assert(lod==0)
                        else return original_lod(u,lod) end
                    end
                    Unit.enable_animation_state_machine=attached
                    Unit.has_animation_event=function(u,name) attached(u);assert(name=='idle');return true end
                    Unit.animation_event=function(u,name) attached(u);assert(name=='idle') end
                    mod._apply_warlock_child_materials=attached
                    mod._start_warlock_backpack_sound=function(o,u) assert(o==owner);attached(u) end
                    mod._start_warlock_backpack_smoke=function(o,u) assert(o==owner);attached(u) end
                    function hide_warlock_carrier_meshes(u) assert(u==owner);return 1,1,true end
                    inventory.is_server=is_server;inventory.inventory_items_n=nil
                    inventory.inventory_item_units={};inventory.inventory_item_outfit_units={}
                    local result=captured[AIInventoryExtension]._setup_configuration(
                        function(self,u,n,configuration,data)
                            assert(self==inventory and u==owner and n==1 and events.pruned)
                            assert(configuration=='configuration' and data=='init_data')
                            assert(record_count()==0 and events.spawn_attempts==0)
                            outfit.attached=true
                            self.inventory_item_units={outfit,weapon}
                            self.inventory_item_outfit_units={outfit}
                            -- Both items have the same category. Its final value is
                            -- not a trustworthy substitute for the exact launcher.
                            self.inventory_item_units_by_category.doomrocket_inventory=outfit
                            return 'native_result'
                        end,inventory,owner,1,'configuration','init_data')
                    assert(result=='native_result' and record_count()==1 and events.spawn_attempts==0)
                    assert(mod._doomrocket_hose_state.entries[owner].weapon==weapon)
                    tick();assert(events.spawned==1 and events.poses>0)
                ''')

    def test_drop_single_item_stops_before_native_actor_creation(self):
        self.load_hook('AIInventoryExtension', 'drop_single_item')
        self.lua.execute('''
            assert(start());tick();queue()
            local result=captured[AIInventoryExtension].drop_single_item(function(self,index,reason)
                assert(self==inventory and index==2 and reason=='death')
                assert(record_count()==0 and events.destroyed==1)
                weapon.extension.dropped=true;return 'dropped'
            end,inventory,2,'death')
            drain();assert(result=='dropped' and events.destroyed==1)
        ''')

    def test_drop_unrelated_item_does_not_stop_hose(self):
        self.load_hook('AIInventoryExtension', 'drop_single_item')
        self.lua.execute('''
            assert(start());tick();inventory.inventory_item_units[3]=new_unit('unrelated')
            inventory.inventory_item_units[3].extension={dropped=false}
            inventory.inventory_item_definitions[3]={drop_reasons={shield_break=true}}
            captured[AIInventoryExtension].drop_single_item(function()
                assert(record_count()==1 and events.destroyed==0)
            end,inventory,3,'shield_break')
            tick();assert(record_count()==1)
        ''')

    def test_drop_ineligible_item_preserves_hose_until_native_changes_it(self):
        cases = {
            'wrong_reason': "inventory.inventory_item_definitions[2].drop_reasons.death=nil",
            'already_recorded': "inventory.dropped_items[2]=false",
            'extension_dropped': "weapon.extension.dropped=true",
            'missing_extension': "weapon.extension=nil",
            'missing_definition': "inventory.inventory_item_definitions[2]=nil",
            'missing_reasons': "inventory.inventory_item_definitions[2].drop_reasons=nil",
            'helmet': "inventory.inventory_item_definitions[2].unit_extension_template='ai_helmet_unit'",
            'outfit': "inventory.inventory_item_definitions[2].unit_extension_template='ai_outfit_unit'",
            'skin': "inventory.inventory_item_definitions[2].unit_extension_template='ai_skin_unit'",
        }
        for name, setup in cases.items():
            with self.subTest(case=name):
                self.setUp()
                self.load_hook('AIInventoryExtension', 'drop_single_item')
                self.lua.execute('assert(start());tick();' + setup + '''
                    local calls=0
                    local result=captured[AIInventoryExtension].drop_single_item(function(self,index,reason)
                        assert(record_count()==1 and events.destroyed==0)
                        assert(self==inventory and index==2 and reason=='death')
                        calls=calls+1;return false
                    end,inventory,2,'death')
                    assert(calls==1 and result==false and record_count()==1)
                ''')

    def test_drop_missing_template_uses_native_inventory_item_default(self):
        self.load_hook('AIInventoryExtension', 'drop_single_item')
        self.lua.execute('''
            assert(start());tick();inventory.inventory_item_definitions[2].unit_extension_template=nil
            captured[AIInventoryExtension].drop_single_item(function()
                assert(record_count()==0 and events.destroyed==1)
            end,inventory,2,'death')
        ''')

    def test_disable_item_stops_before_native_hide(self):
        self.load_hook('AIInventoryExtension', 'disable_inventory_item')
        self.lua.execute('''
            assert(start());tick()
            captured[AIInventoryExtension].disable_inventory_item(function(self,item,u)
                assert(self==inventory and u==weapon)
                assert(record_count()==0 and events.destroyed==1)
            end,inventory,{},weapon)
        ''')

    def test_animation_hooks_queue_only_until_safe_callback_drain(self):
        for method in ('update_animations', 'update_animations_with_callback'):
            with self.subTest(method=method):
                self.setUp()
                finish = self.extract_one(
                    HOOKS, r'^local function finish_warlock_animation_update\(.*?^end\s*$')
                self.load_hook('World', method, prefix=finish)
                self.lua.globals().method = method
                self.lua.execute('''
                    function mod:pcall(fn,...)
                        local ok,err=pcall(fn,...)
                        assert(ok,err);return ok
                    end
                    local order={}
                    mod._update_warlock_locomotion_animation=function(w,dt)
                        assert(w==world);order[#order+1]='gait'
                    end
                    local queue_before=animation.add_safe_animation_callback
                    function animation:add_safe_animation_callback(fn)
                        assert(order[#order]=='engine','hose queued before native animation')
                        order[#order+1]='queue';return queue_before(self,fn)
                    end
                    local function native(w,dt,arg)
                        assert(w==world and arg=='native_callback')
                        assert(order[#order]=='gait','gait must run before native animation')
                        assert(#callbacks==0,'pose work already queued before native animation')
                        order[#order+1]='engine';return 'native_result'
                    end
                    assert(start())
                    local result=captured[World][method](native,world,1/60,'native_callback')
                    assert(result=='native_result' and table.concat(order,',')=='gait,engine,queue')
                    assert(#callbacks==1 and events.spawned==0 and events.poses==0)
                    drain();assert(events.spawned==1 and events.poses>0)
                    local solver=mod._doomrocket_hose_state.entries[owner].solver
                    local steps=solver.steps
                    local writes=events.poses
                    captured[World][method](native,world,0,'native_callback')
                    assert(events.poses==writes,'hook wrote hose bones before safe callback drain')
                    drain();assert(solver.steps==steps)
                ''')

    def test_application_world_release_hook_forgets_before_engine(self):
        self.load_hook('Application', 'release_world')
        self.lua.execute('''
            assert(start());tick();queue()
            local result=captured[Application].release_world(function(w)
                assert(w==world and record_count()==0 and events.destroyed==0)
                release_world();return 'released'
            end,world)
            drain();assert(result=='released' and events.destroyed==0)
        ''')

    def test_application_world_release_blocks_reentrant_start_but_allows_recycled_pointer(self):
        self.load_hook('Application', 'release_world')
        self.lua.execute('''
            assert(start());tick();queue()
            captured[Application].release_world(function(w)
                assert(w==world and record_count()==0 and events.destroyed==0)
                assert(not start(),'native release must keep start quarantined')
                queue();assert(record_count()==0)
                release_world()
            end,world)
            -- The engine can reuse a native world pointer in a later level. Old
            -- entry callbacks must remain cancelled, but the handle cannot remain
            -- globally blacklisted once native destruction has returned.
            world.alive=true;wm._worlds.level_world=world
            owner=new_owner();outfit=new_outfit();weapon=new_weapon()
            weapon.extension.wielding_unit=owner
            inventory={unit=owner,world=world,inventory_item_units={outfit,weapon}}
            owner.inventory=inventory;mod._warlock_outfits[owner]=outfit
            assert(start());drain();assert(events.spawned==1 and record_count()==1)
            tick();assert(events.spawned==2 and record_count()==1)
            reset();assert(events.destroyed==1)
        ''')

    def test_death_preparation_stops_before_corpse_handoff_on_host_and_husk(self):
        for source in ('unit', 'husk'):
            with self.subTest(source=source):
                self.setUp()
                self.lua.globals().death_source = source
                self.lua.execute('''
                    mod._warlock_death_sequence=0
                    function warlock_game_time() return 0 end
                    mod._stop_warlock_backpack_smoke=function() end
                    mod._stop_warlock_backpack_sound=function()
                        assert(record_count()==0 and events.destroyed==1,
                            'hose must end before audio/ragdoll handoff')
                    end
                ''')
                self.lua.execute(self.extract_one(
                    HOOKS, r'^mod\._prepare_warlock_death = function.*?^end\s*$'))
                self.lua.execute('''
                    assert(start());tick();queue();mod._warlock_outfits={}
                    mod._prepare_warlock_death(owner,death_source);drain()
                    assert(record_count()==0 and events.destroyed==1 and not start())
                ''')

    def test_mod_exit_disable_and_unload_reset_actual_hose_owner(self):
        for callback in ("mod.on_game_state_changed('exit','StateIngame')",
                         'mod.on_disabled()', 'mod.on_unload()'):
            with self.subTest(callback=callback):
                self.setUp()
                self.lua.execute('''
                    mod._reset_warlock_backpack_smoke=function() end
                    mod._shutdown_doomrocket_audio=function() end
                    mod._reset_warlock_death_drivers=function() end
                ''')
                self.lua.execute(self.extract_one(
                    BOOTSTRAP, r'^mod\.anim_emitters = \{\}.*?(?=^mod:dofile\("scripts/settings/breeds"\))'))
                self.lua.execute('assert(start());tick();queue();' + callback + '''
                    drain();assert(record_count()==0 and events.destroyed==1)
                ''')


if __name__ == '__main__':
    unittest.main(verbosity=2)
