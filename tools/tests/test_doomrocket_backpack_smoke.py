#!/usr/bin/env python3
"""Execute the isolated smoke controller with strict engine lifetime boundaries.

These prove handle/package ownership, not particle rendering or live multiplayer.
The shipping anchor is loaded unchanged; its independent geometric proof lives in
the anchor tests. A deleted outfit deliberately recycles its old ID to catch unsafe
cleanup that mistakes somebody else's effect for this mod's emitter.

Root integration tests execute unchanged, narrowly extracted shipping callbacks
with the same strict engine boundary. They do not load the entire game/VMF or
simulate the ragdoll solver. Checks that only inspect source order are explicitly
named ``structural``; those are not executable engine/hook acceptance tests.
"""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_backpack_smoke.lua"
ANCHOR = ROOT / "scripts/mods/doomrocket/utils/doomrocket_chimney_anchor.lua"
BOOTSTRAP = ROOT / "scripts/mods/doomrocket/doomrocket.lua"
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"
DEATH_REACTIONS = ROOT / "scripts/mods/doomrocket/extensions/death_reactions.lua"

HARNESS = r"""
events={created=0,linked=0,destroyed=0,queried=0,loads=0,unloads=0,nodes=0}
function printf() end
local function v(x,y,z) return {x=x,y=y,z=z} end
Vector3=v
Matrix4x4={
 identity=function() return {x=v(1,0,0),y=v(0,1,0),z=v(0,0,1),p=v(0,0,0)} end,
 set_x=function(m,x) m.x=x end,set_y=function(m,x) m.y=x end,
 set_z=function(m,x) m.z=x end,set_translation=function(m,x) m.p=x end,
}
world={alive=true}
outfit_name='units/warlock_bombardier/warlock_bombardier_3p'
function new_owner() return {alive=true,world=world} end
function new_outfit() return {alive=true,world=world,name=outfit_name,has_node=true} end
owner=new_owner(); outfit=new_outfit()
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) assert(u and u.alive,'dead Unit.world'); return u.world end,
 get_data=function(u,key) assert(u and u.alive and key=='unit_name'); return u.name end,
 has_node=function(u,node) assert(u.alive and node=='j_backpack'); return u.has_node end,
 node=function(u,node)
  assert(u.alive and u.has_node and node=='j_backpack','unsafe node lookup')
  events.nodes=events.nodes+1; return 46
 end,
}
wm={_worlds={level_world=world},_disabled_worlds={}}
function wm:has_world(name) return self._worlds[name] ~= nil end
function wm:world(name) assert(self._worlds[name]); return self._worlds[name] end
package_name='resource_packages/breeds/skaven_warpfire_thrower'
package_reference='doomrocket_backpack_smoke'
effect_name='fx/chr_warp_fire_backpack_smoke_01'
package_available=true; particles_available=true; loaded=true
refs={global=3}
pm={}
function pm:has_loaded(name,reference)
 assert(name==package_name)
 return loaded and (not reference or refs[reference] ~= nil)
end
function pm:load(name,reference,callback,asynchronous)
 assert(name==package_name and reference==package_reference)
 assert(callback==nil and asynchronous==nil,'must load synchronously')
 refs[reference]=(refs[reference] or 0)+1; loaded=true; events.loads=events.loads+1
end
function pm:unload(name,reference)
 assert(name==package_name and reference==package_reference)
 assert(refs[reference] and refs[reference] > 0,'unowned package decrement')
 refs[reference]=refs[reference]-1
 if refs[reference]==0 then refs[reference]=nil end
 events.unloads=events.unloads+1
end
Managers={world=wm,package=pm}
Application={can_get=function(kind,name)
 if kind=='package' then assert(name==package_name); return package_available end
 assert(kind=='particles' and name==effect_name)
 assert(refs[package_reference],'residency queried before own package load')
 return particles_available
end}
effects={}; next_id=1
local function check_world(w) assert(w and w.alive,'released world touched') end
World={
 create_particles=function(w,name,position)
  check_world(w); assert(name==effect_name)
  local id=next_id; next_id=id+1
  effects[id]={world=w}; events.created=events.created+1
  return id
 end,
 link_particles=function(w,id,u,node,pose,policy)
  check_world(w); assert(effects[id] and u.alive and u.world==w)
  assert(node==46 and policy=='destroy')
  effects[id].outfit=u; effects[id].pose=pose; effects[id].policy=policy
  events.linked=events.linked+1; events.last_pose=pose; events.last_id=id
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
  if on_destroy then on_destroy() end
 end,
}
-- Native ScriptWorld helper's exact create/link argument order.
ScriptWorld={create_particles_linked=function(w,name,u,node,policy,pose)
 local id=World.create_particles(w,name,Vector3(0,0,0))
 World.link_particles(w,id,u,node,pose or Matrix4x4.identity(),policy)
 return id
end}
mod={}; function get_mod(name) assert(name=='doomrocket'); return mod end
function mod:pcall(fn,...)
 local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result
end
-- Isolate smoke assertions while executing shared production lifecycle hooks.
-- Actual hose ownership/native boundary behavior is exercised independently in
-- test_doomrocket_hose_lifecycle.py; these are not mocked smoke operations.
mod._start_warlock_hose=function() end
mod._stop_warlock_hose=function() end
mod._stop_warlock_hose_item=function() end
mod._queue_warlock_hose=function() end
mod._reset_warlock_hose=function() end
mod._release_warlock_hose=function() end
mod._finish_release_warlock_hose=function() end
-- The shared callbacks also notify the independent visible gait controller.
-- Its native variable/lifetime behavior has its own executable suite; smoke
-- operations and their strict ownership assertions remain real here.
mod._start_warlock_locomotion_animation=function() end
mod._stop_warlock_locomotion_animation=function() end
mod._reset_warlock_locomotion_animation=function() end
mod._release_warlock_locomotion_world=function() end
mod._update_warlock_locomotion_animation=function() end
-- The read-only grip probe has its own strict pose and lifecycle suite.
mod._start_warlock_weapon_pose_probe=function() end
mod._stop_warlock_weapon_pose_probe=function() end
mod._stop_warlock_weapon_pose_probe_item=function() end
mod._queue_warlock_weapon_pose_probe=function() end
mod._reset_warlock_weapon_pose_probe=function() end
mod._release_warlock_weapon_pose_probe_world=function() end
mod._note_warlock_weapon_pose_event=function() end
function start(o,u) return mod._start_warlock_backpack_smoke(o or owner,u or outfit) end
function stop(reason) return mod._stop_warlock_backpack_smoke(owner,reason) end
function reset(reason) mod._reset_warlock_backpack_smoke(reason) end
function update() mod._update_warlock_backpack_smoke() end
function record_count()
 local n=0; for _ in pairs(mod._doomrocket_backpack_smoke_state.entries) do n=n+1 end; return n
end
function disable_world()
 wm._worlds.level_world=nil; wm._disabled_worlds.level_world=world
end
function resume_world()
 wm._disabled_worlds.level_world=nil; wm._worlds.level_world=world
end
function finish_world_release()
 world.alive=false; wm._worlds.level_world=nil; wm._disabled_worlds.level_world=nil
 effects={}
end
"""


class BackpackSmokeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(HARNESS)
        self.lua.globals().mod._doomrocket_chimney_anchor = self.lua.execute(ANCHOR.read_text(encoding="utf-8"))
        self.source = MODULE.read_text(encoding="utf-8")
        self.lua.execute(self.source)

    def test_duplicate_start_has_one_effect_and_one_package_reference(self):
        self.lua.execute("""
            assert(start()); assert(start()); assert(start())
            assert(events.created==1 and events.linked==1 and events.loads==1)
            assert(refs[package_reference]==1 and refs.global==3 and record_count()==1)
        """)

    def test_host_husk_and_many_owners_get_one_local_effect_each(self):
        self.lua.execute("""
            owner.is_server=true; assert(start())
            for i=1,30 do
                local o=new_owner(); o.is_server=false
                local u=new_outfit(); assert(start(o,u)); assert(start(o,u))
            end
            assert(record_count()==31 and events.created==31 and events.loads==1)
            reset('level_exit')
            assert(record_count()==0 and events.destroyed==31 and events.unloads==1)
            assert(refs.global==3)
        """)

    def test_same_outfit_cannot_be_claimed_by_second_owner(self):
        self.lua.execute("""
            assert(start()); assert(not start(new_owner(),outfit))
            assert(events.created==1 and record_count()==1)
        """)

    def test_replacement_destroys_old_before_creating_new(self):
        self.lua.execute("""
            assert(start()); local old_id=events.last_id
            local second=new_outfit(); assert(start(owner,second))
            assert(effects[old_id]==nil and effects[events.last_id].outfit==second)
            assert(events.destroyed==1 and events.created==2 and events.loads==1)
            assert(record_count()==1)
        """)

    def test_death_destroy_and_freeze_cleanup_are_idempotent(self):
        for reason in ("death_unit", "death_husk", "inventory_destroy", "inventory_freeze"):
            with self.subTest(reason=reason):
                self.setUp()
                self.lua.globals().reason = reason
                self.lua.execute("""
                    assert(start()); assert(stop(reason)); assert(not stop(reason))
                    outfit.alive=false; update(); reset(reason)
                    assert(events.destroyed==1 and events.queried==1 and record_count()==0)
                    assert(events.unloads==1 and refs.global==3)
                """)

    def test_cleanup_claims_entry_before_native_reentrancy(self):
        self.lua.execute("""
            assert(start())
            on_destroy=function() assert(not stop('reentrant')) end
            assert(stop('outer')); assert(events.destroyed==1 and record_count()==0)
        """)

    def test_dead_outfit_recycled_id_is_never_queried_or_destroyed(self):
        self.lua.execute("""
            assert(start()); local id=events.last_id
            outfit.alive=false
            effects[id]={world=world,foreign=true}
            update(); reset('disable')
            assert(events.queried==0 and events.destroyed==0 and effects[id].foreign)
            assert(record_count()==0)
        """)

    def test_dead_owner_live_outfit_stops_before_outfit_removal(self):
        self.lua.execute("""
            assert(start()); owner.alive=false; update()
            assert(events.destroyed==1 and record_count()==0)
        """)

    def test_vanished_world_discards_id_without_native_calls_or_package_unload(self):
        self.lua.execute("""
            assert(start()); finish_world_release()
            update(); reset('late_exit')
            assert(record_count()==0 and events.queried==0 and events.destroyed==0)
            assert(events.unloads==0 and refs[package_reference]==1)
        """)

    def test_unknown_world_cannot_reappear_with_duplicate_emitter(self):
        self.lua.execute("""
            assert(start()); wm._worlds.level_world=nil
            update(); wm._worlds.level_world=world
            assert(not start()); assert(events.created==1)
            assert(events.queried==0 and events.destroyed==0)
        """)

    def test_world_release_forgets_before_release_and_defers_package_unload(self):
        self.lua.execute("""
            assert(start()); mod._release_warlock_smoke_world(world)
            assert(record_count()==0 and events.queried==0 and events.destroyed==0)
            assert(not start()); reset('during_release')
            assert(events.unloads==0)
            finish_world_release(); reset('after_release')
            assert(events.unloads==1 and refs.global==3)
        """)

    def test_world_release_after_unknown_world_recovers_owned_package(self):
        self.lua.execute("""
            assert(start()); wm._worlds.level_world=nil; update()
            mod._release_warlock_smoke_world(world); finish_world_release()
            reset('after_release'); assert(events.unloads==1 and events.queried==0)
        """)

    def test_other_world_release_does_not_forget_live_effect(self):
        self.lua.execute("""
            assert(start()); mod._release_warlock_smoke_world({alive=true})
            assert(record_count()==1 and start() and events.created==1)
        """)

    def test_paused_world_retains_entry_and_resumes_without_duplicate(self):
        self.lua.execute("""
            assert(start()); disable_world(); update()
            assert(record_count()==1 and start())
            assert(not start(new_owner(),new_outfit()))
            resume_world(); assert(start()); assert(events.created==1)
        """)

    def test_reset_in_disabled_world_destroys_safely(self):
        self.lua.execute("""
            assert(start()); disable_world(); reset('disabled_world')
            assert(events.destroyed==1 and record_count()==0 and events.unloads==1)
        """)

    def test_missing_node_or_wrong_outfit_fails_before_native_creation(self):
        for setup in ("outfit.has_node=false", "outfit.name='wrong'", "outfit.world={alive=true}",
                      "owner.alive=false", "outfit.alive=false", "DEDICATED_SERVER=true",
                      "wm._worlds.level_world=nil", "mod._doomrocket_chimney_anchor=nil",
                      "mod._doomrocket_chimney_anchor.node=nil",
                      "mod._doomrocket_chimney_anchor.x_axis={0/0,0,0}"):
            with self.subTest(setup=setup):
                self.setUp()
                self.lua.execute(setup + "; assert(not start()); assert(events.created==0 and events.nodes==0 and events.loads==0)")

    def test_unavailable_package_or_effect_does_not_create(self):
        self.lua.execute("""
            package_available=false; assert(not start()); assert(events.loads==0)
            package_available=true; particles_available=false
            assert(not start()); assert(not start())
            assert(events.loads==1 and events.created==0)
            reset('missing_resource'); assert(events.unloads==1)
        """)

    def test_measured_scaled_basis_is_passed_without_normalization(self):
        self.lua.execute("""
            assert(start()); local a=mod._doomrocket_chimney_anchor; local p=events.last_pose
            local function equal(v,t) assert(v.x==t[1] and v.y==t[2] and v.z==t[3]) end
            equal(p.x,a.x_axis); equal(p.y,a.y_axis); equal(p.z,a.z_axis); equal(p.p,a.position)
            local length=math.sqrt(p.x.x^2+p.x.y^2+p.x.z^2)
            assert(math.abs(length-.01)<.000001)
        """)

    def test_reset_and_restart_reacquire_only_own_reference(self):
        self.lua.execute("""
            assert(start()); reset('disable'); reset('unload')
            assert(events.destroyed==1 and events.unloads==1 and refs.global==3)
            assert(start()); assert(events.loads==2 and refs[package_reference]==1)
        """)

    def test_hot_reload_disposes_old_owned_effect_then_restarts(self):
        self.lua.execute("assert(start())")
        self.lua.execute(self.source)
        self.lua.execute("""
            assert(events.destroyed==1 and events.unloads==1 and record_count()==0)
            assert(start()); assert(events.created==2 and events.loads==2)
            reset('again'); assert(events.destroyed==2 and events.unloads==2)
        """)

    def test_module_contains_no_hooks_physics_bone_writes_or_network_sends(self):
        for forbidden in ("mod:hook", "Actor.", "PhysicsWorld.", "Unit.set_", "network_send", "send_rpc"):
            self.assertNotIn(forbidden, self.source)


class BackpackSmokeRootIntegrationTests(unittest.TestCase):
    """Execute actual root callbacks; source-order-only checks say structural."""

    setUp = BackpackSmokeTests.setUp

    def extract_one(self, path, pattern):
        matches = re.findall(pattern, path.read_text(encoding="utf-8"), re.M | re.S)
        self.assertEqual(len(matches), 1, f"Expected one shipping callback in {path.name}")
        return matches[0]

    def load_hook(self, target, method):
        self.lua.execute("""
            AIInventoryExtension=AIInventoryExtension or {}
            captured=captured or {}
            function mod:hook(class,name,fn)
                captured[class]=captured[class] or {}
                assert(not captured[class][name],'duplicate shipping hook')
                captured[class][name]=fn
            end
        """)
        self.lua.execute(self.extract_one(
            HOOKS, rf'^mod:hook\({target}, "{method}", function.*?^end\)'))

    def load_runtime_callbacks(self):
        self.lua.execute(self.extract_one(
            BOOTSTRAP, r'^mod\.anim_emitters = \{\}.*?(?=^mod:dofile\("scripts/settings/breeds"\))'))

    def load_death_preparation(self):
        self.lua.execute("""
            mod._warlock_death_sequence=0
            mod._warlock_outfits={}
            function warlock_game_time() return 0 end
            Application.time_since_launch=function() return 0 end
            mod._stop_warlock_backpack_sound=function(u,reason)
                assert(u==owner and reason=='death_'..death_source)
                assert(record_count()==0 and events.destroyed==1,
                    'smoke must stop before audio/corpse handoff')
            end
        """)
        self.lua.execute(self.extract_one(
            HOOKS, r'^mod\._prepare_warlock_death = function.*?^end\s*$'))

    def test_structural_anchor_controller_and_hooks_load_once_in_order(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        statements = (
            'mod._doomrocket_chimney_anchor = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_chimney_anchor")',
            'mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_backpack_smoke")',
            'mod:dofile("scripts/mods/doomrocket/utils/hooks")',
        )
        for statement in statements:
            self.assertEqual(source.count(statement), 1)
        positions = [source.index(statement) for statement in statements]
        self.assertEqual(positions, sorted(positions))

    def test_actual_setup_only_starts_warlock_smoke_after_native_attachment(self):
        self.load_hook("AIInventoryExtension", "_setup_configuration")
        self.lua.execute("""
            mod._warlock_outfits={}; mod._warlock_carriers={}
            mod._prune_armor_bridge=function(u) assert(u==owner); events.pruned=true end
            local function require_attached(u) assert(u.attached,'outfit used before native attachment') end
            Unit.disable_animation_state_machine=require_attached
            Unit.set_animation_bone_mode=require_attached
            Unit.set_bones_lod=require_attached
            Unit.enable_animation_state_machine=require_attached
            Unit.has_animation_event=function(u) require_attached(u); return true end
            Unit.animation_event=require_attached
            mod._apply_warlock_child_materials=function(u) require_attached(u); u.materials=true end
            mod._start_warlock_backpack_sound=function(o,u)
                assert(o==owner and u.materials); u.sound_started=true
            end
            function hide_warlock_carrier_meshes(u) assert(u==owner); return 1,1,true end
            local smoke_start=mod._start_warlock_backpack_smoke
            events.start_calls=0
            mod._start_warlock_backpack_smoke=function(o,u)
                events.start_calls=events.start_calls+1
                assert(u.name==outfit_name and u.attached and u.materials and u.sound_started)
                return smoke_start(o,u)
            end
            local monk=new_outfit()
            monk.name='units/beings/enemies/skaven_plague_monk/chr_skaven_plague_monk'
            local unrelated=new_outfit(); unrelated.name='unrelated'
            local deleted=new_outfit(); deleted.alive=false
            local configuration={}; local init_data={}
            local inventory={unit=owner,is_server=false}
            local function original(self,u,n,c,data)
                assert(events.pruned and self==inventory and u==owner)
                assert(n==7 and c==configuration and data==init_data)
                assert(events.start_calls==0 and events.created==0)
                self.inventory_item_outfit_units={monk,unrelated,deleted,outfit}
                for _,item in ipairs(self.inventory_item_outfit_units) do item.attached=true end
                return 'native-result'
            end
            local result=captured[AIInventoryExtension]._setup_configuration(
                original,inventory,owner,7,configuration,init_data)
            assert(result=='native-result' and events.start_calls==1 and events.created==1)
            assert(mod._warlock_outfits[owner]==outfit and record_count()==1)
        """)

    def test_actual_inventory_destroy_and_freeze_stop_before_original(self):
        for method in ("destroy", "freeze"):
            with self.subTest(method=method):
                self.setUp()
                self.load_hook("AIInventoryExtension", method)
                self.lua.globals().method = method
                self.lua.execute("""
                    assert(start()); local inventory={unit=owner}
                    local function original(self,arg1,arg2)
                        assert(self==inventory and arg1=='sentinel' and arg2==17)
                        assert(record_count()==0 and events.destroyed==1 and events.queried==1)
                        outfit.alive=false
                        return 'native-result',42
                    end
                    local result,extra=captured[AIInventoryExtension][method](
                        original,inventory,'sentinel',17)
                    assert(result=='native-result' and extra==42)
                    update(); reset('later'); assert(events.destroyed==1)
                """)

    def test_actual_world_release_forgets_before_original_without_native_particle_calls(self):
        self.load_hook("Application", "release_world")
        self.lua.execute("""
            assert(start())
            local function original(w,arg)
                assert(w==world and arg=='sentinel' and record_count()==0)
                assert(events.destroyed==0 and events.queried==0 and events.unloads==0)
                assert(not start())
                finish_world_release()
                return 'released',42
            end
            local result,extra=captured[Application].release_world(original,world,'sentinel')
            assert(result=='released' and extra==42)
            update(); reset('post-release')
            assert(events.unloads==1 and events.destroyed==0 and events.queried==0)
        """)

    def test_actual_mod_update_reaps_dead_owner_and_preserves_existing_updates(self):
        self.load_runtime_callbacks()
        self.lua.execute("""
            mod._update_warlock_backpack_sounds=function() events.audio_update=true end
            mod.projectiles.one={update=function(self,dt) assert(dt==.25); events.projectile_update=true end}
            mod.anim_emitters[owner]={update=function(self,u,dt)
                assert(u==owner and dt==.25); events.animation_update=true
            end}
            assert(start()); owner.alive=false; mod.update(.25)
            assert(events.audio_update and events.projectile_update and events.animation_update)
            assert(record_count()==0 and events.destroyed==1)
        """)

    def test_actual_reset_callbacks_stop_before_audio_and_death_driver_reset(self):
        callbacks = (
            ("mod.on_game_state_changed('exit','StateIngame')", "state_ingame_exit", False),
            ("mod.on_disabled()", "mod_disabled", True),
            ("mod.on_unload()", "mod_unload", True),
        )
        for callback, reason, unload in callbacks:
            with self.subTest(callback=callback):
                self.setUp()
                self.load_runtime_callbacks()
                self.lua.globals().expected_reason = reason
                self.lua.globals().expected_unload = unload
                self.lua.execute("""
                    mod._shutdown_doomrocket_audio=function(reason,unload)
                        assert(reason==expected_reason and unload==expected_unload)
                        assert(record_count()==0 and events.destroyed==1 and events.unloads==1)
                        events.audio_reset=true
                    end
                    mod._reset_warlock_death_drivers=function()
                        assert(events.audio_reset and record_count()==0)
                        events.death_reset=true
                    end
                    assert(start())
                    mod.on_game_state_changed('enter','StateIngame')
                    mod.on_game_state_changed('exit','StateLoading')
                    assert(record_count()==1 and not events.audio_reset)
                """)
                self.lua.execute(callback + "; assert(events.death_reset)")

    def test_actual_unit_and_husk_pre_start_stop_smoke_before_native_death(self):
        source = DEATH_REACTIONS.read_text(encoding="utf-8")
        template = source[source.index("DeathReactions.templates.doomrocket = {"):]
        callbacks = re.findall(r'pre_start = (function .*?^        end),', template, re.M | re.S)
        self.assertEqual(len(callbacks), 2)
        for mode, callback in zip(("unit", "husk"), callbacks):
            with self.subTest(mode=mode):
                self.setUp()
                self.load_death_preparation()
                self.lua.globals().death_source = mode
                self.lua.execute("""
                    function is_hot_join_sync() return true end
                    function native_pre_start(u,context,t,blow)
                        assert(u==owner and context=='context' and t==2 and blow=='blow')
                        assert(record_count()==0 and events.destroyed==1)
                        events.native_death=true
                    end
                    ai_default_unit_pre_start=native_pre_start
                    ai_default_husk_pre_start=native_pre_start
                    assert(start())
                    -- No outfit in the ragdoll map exercises the actual early rejection;
                    -- the controller still owns its live outfit and must stop it first.
                """)
                self.lua.execute("pre_start=" + callback)
                self.lua.execute("pre_start(owner,'context',2,'blow'); assert(events.native_death)")

    def test_structural_death_preparation_stops_before_all_corpse_handoff_boundaries(self):
        body = self.extract_one(HOOKS, r'^mod\._prepare_warlock_death = function.*?^end\s*$')
        stop = body.index('mod._stop_warlock_backpack_smoke(owner_unit, "death_" .. tostring(source))')
        boundaries = (
            'local outfit_unit = mod._warlock_outfits[owner_unit]',
            'warlock_rigid_world_pose(owner_unit, source_index)',
            'Unit.world_pose(outfit_unit, target_index)',
            'mod._warlock_outfits[owner_unit] = nil',
            'Unit.set_animation_bone_mode(outfit_unit, "ignore")',
            'mod._warlock_pending_death_drivers[owner_unit] = driver',
        )
        for boundary in boundaries:
            self.assertLess(stop, body.index(boundary), boundary)


if __name__ == "__main__":
    unittest.main()
