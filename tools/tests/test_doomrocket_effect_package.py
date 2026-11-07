#!/usr/bin/env python3
"""Execute both production cosmetic controllers across asynchronous residency.

These are Lua 5.1 ownership/lifetime tests, not a native frame-time or visual pass.
The strict package double rejects even an attempted synchronous request.
"""

import unittest

import test_doomrocket_backpack_smoke as smoke
import test_doomrocket_crystal_flame as crystal


def runtime(kind):
    if kind == "smoke":
        case = smoke.BackpackSmokeTests()
        case.setUp()
        lua = case.lua
        source = smoke.MODULE
        lua.execute("""
            s=mod._doomrocket_backpack_smoke_state; attached=outfit
            effect_update=mod._update_warlock_backpack_smoke
            effect_reset=mod._reset_warlock_backpack_smoke
            effect_stop=function() return mod._stop_warlock_backpack_smoke(owner,'cancel') end
            effect_release=mod._release_warlock_smoke_world
            effect_prewarm=mod._prewarm_warlock_backpack_smoke
        """)
    else:
        lua = crystal.runtime()
        source = crystal.MODULE
        lua.execute("""
            s=mod._doomrocket_crystal_flame_state; attached=weapon
            effect_update=mod._update_warlock_crystal_flame
            effect_reset=mod._reset_warlock_crystal_flame
            effect_stop=function() return mod._stop_warlock_crystal_flame(owner,'cancel') end
            effect_release=mod._release_warlock_crystal_flame_world
            effect_prewarm=mod._prewarm_warlock_crystal_flame
        """)
    lua.execute("""
        function complete()
            loaded=true
            if finish_variant then finish_variant() end
        end
        function no_emitters()
            assert(events.created==0 and events.linked==0 and events.queried==0 and events.destroyed==0)
            assert(not events.sync_loads)
        end
    """)
    return lua, source


class EffectPackageAsyncTests(unittest.TestCase):
    kinds = ("smoke", "crystal")

    def test_first_spawn_never_flushes_or_duplicates_and_pending_owner_eventually_starts(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    defer_loading=true; loaded=false
                    assert(not start()); no_emitters()
                    assert(refs[package_reference]==1 and events.loads==1)
                    for i=1,20 do assert(not start()); effect_update() end
                    assert(events.loads==1); no_emitters()
                    complete(); effect_update()
                    assert(events.created==1 and events.linked==1)
                    for i=1,20 do assert(start()); effect_update() end
                    assert(events.created==1 and events.loads==1 and not events.sync_loads)
                    effect_reset('done'); assert(events.unloads==1 and refs.global==3)
                """)

    def test_variant_package_waits_for_native_dependencies_then_completes_without_new_spawn(self):
        lua, _ = runtime("crystal")
        lua.execute("""
            defer_loading=true; loaded=false; defer_variant_loading=true; variant_loaded=false
            assert(not start()); assert(not events.variant_loads); no_emitters()
            loaded=true; effect_update()
            assert(events.variant_loads==1 and variant_refs[package_reference]==1); no_emitters()
            for i=1,10 do effect_update() end
            assert(events.loads==1 and events.variant_loads==1); no_emitters()
            finish_variant(); effect_update()
            assert(events.created==1 and events.linked==1)
            effect_reset('done')
            assert(events.unloads==1 and events.variant_unloads==1 and refs.global==3)
        """)

    def test_prewarm_retains_one_reference_without_owners_and_survives_disabled_world(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    defer_loading=true; loaded=false
                    assert(not effect_prewarm())
                    for i=1,20 do effect_prewarm(); effect_update() end
                    assert(events.loads==1 and events.unloads==0); no_emitters()
                    wm._worlds.level_world=nil; wm._disabled_worlds.level_world=world
                    complete(); effect_update(); assert(not effect_prewarm()); no_emitters()
                    assert(events.unloads==0 and refs[package_reference]==1)
                    wm._disabled_worlds.level_world=nil; wm._worlds.level_world=world
                    effect_prewarm(); assert(start())
                    assert(events.created==1 and events.loads==1 and not events.sync_loads)
                    effect_reset('done'); assert(events.unloads==1 and refs.global==3)
                """)

    def test_pending_owner_death_attachment_deletion_movement_and_explicit_cancel_do_not_resurrect(self):
        actions = ("owner.alive=false", "attached.alive=false", "owner.world={alive=true}",
                   "attached.world={alive=true}", "assert(effect_stop())", "effect_reset('reset')")
        for kind in self.kinds:
            for action in actions:
                with self.subTest(kind=kind, action=action):
                    lua, _ = runtime(kind)
                    lua.execute("""
                        defer_loading=true; loaded=false
                        assert(not start()); no_emitters()
                    """ + action + """
                        effect_update(); complete(); effect_update()
                        no_emitters()
                        assert(not next(s.pending_owners) and not next(s.entries))
                        assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                    """)

    def test_pending_drop_or_inventory_replacement_does_not_create_on_completion(self):
        for action in ("weapon.item.dropped=true", "inventory.dropped=true",
                       "inventory.inventory_item_units={}", "inventory.unit=new_owner()"):
            with self.subTest(action=action):
                lua, _ = runtime("crystal")
                lua.execute("""
                    defer_loading=true; loaded=false; assert(not start())
                """ + action + """
                    complete(); effect_update(); no_emitters()
                    assert(not next(s.pending_owners) and not next(s.entries))
                    assert(events.unloads==1 and refs.global==3)
                """)

    def test_completion_while_disabled_waits_until_resume_without_duplicate_load(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    defer_loading=true; loaded=false; assert(not start())
                    wm._worlds.level_world=nil; wm._disabled_worlds.level_world=world
                    complete(); effect_update(); no_emitters()
                    assert(events.loads==1 and events.unloads==0 and s.pending_owners[owner])
                    wm._disabled_worlds.level_world=nil; wm._worlds.level_world=world
                    effect_update(); assert(events.created==1 and events.loads==1)
                """)

    def test_world_release_cancels_pending_without_native_calls_and_defers_unload_until_gone(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    defer_loading=true; loaded=false; assert(not start())
                    effect_release(world); complete(); effect_update(); no_emitters()
                    assert(events.unloads==0 and not next(s.pending_owners))
                    world.alive=false; wm._worlds.level_world=nil
                    effect_update(); assert(events.unloads==1 and refs.global==3); no_emitters()
                """)

    def test_reload_cancels_uncompleted_request_and_later_completion_does_not_create(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, source = runtime(kind)
                lua.execute("defer_loading=true; loaded=false; assert(not start())")
                lua.execute(source.read_text(encoding="utf-8"))
                lua.execute("""
                    complete(); effect_update(); no_emitters()
                    assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                    defer_loading=false; assert(start()); assert(events.loads==2 and events.created==1)
                """)

    def test_replaced_package_manager_is_not_touched_and_new_owner_retries_asynchronously(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    defer_loading=true; loaded=false; assert(not start())
                    local old=pm
                    local replacement={load=pm.load,unload=pm.unload,has_loaded=pm.has_loaded,
                        is_loading=pm.is_loading,reference_count=pm.reference_count}
                    local function retired() error('retired manager touched') end
                    old.load=retired; old.unload=retired; old.has_loaded=retired
                    old.is_loading=retired; old.reference_count=retired
                    pm=replacement; Managers.package=replacement
                    refs={global=3}; if variant_package then variant_refs={} end
                    effect_update(); no_emitters()
                    assert(events.loads==2 and refs[package_reference]==1)
                    complete(); effect_update(); assert(events.created==1)
                    effect_reset('done'); assert(events.unloads==1 and refs.global==3)
                """)

    def test_prewarm_dedicated_server_never_calls_native_package_or_world_apis(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    DEDICATED_SERVER=true
                    Managers=setmetatable({}, {__index=function() error('dedicated manager access') end})
                    assert(not effect_prewarm()); no_emitters()
                """)

    def test_reset_death_or_world_release_during_enqueue_cannot_create_or_release_in_use_refs(self):
        actions = ("effect_reset('during_enqueue')", "assert(effect_stop())",
                   "effect_release(world)", "effect_release(world); world.alive=false; wm._worlds.level_world=nil")
        for kind in self.kinds:
            for action in actions:
                with self.subTest(kind=kind, action=action):
                    lua, _ = runtime(kind)
                    lua.execute("""
                        local load=pm.load
                        local invoked=false
                        pm.load=function(...)
                            load(...)
                            if not invoked then
                                invoked=true
                    """ + action + """
                                assert(events.unloads==0,'enqueue operation must retain residency until unwound')
                            end
                        end
                        assert(not start()); no_emitters()
                        assert(not next(s.entries) and not next(s.pending_owners))
                        if s.releasing_worlds[world] then
                            assert(events.unloads==0)
                            world.alive=false; wm._worlds.level_world=nil
                            effect_update()
                        end
                        assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                        complete(); effect_update(); no_emitters()
                    """)

    def test_package_request_error_after_acquiring_pending_ref_cleans_own_reference(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    defer_loading=true; loaded=false
                    local load=pm.load
                    pm.load=function(...) load(...); error('wrapper failed after queueing') end
                    assert(not start()); no_emitters()
                    assert(not next(s.entries) and not next(s.pending_owners))
                    assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                    complete(); effect_update(); no_emitters()
                """)

    def test_prewarm_reset_and_reload_before_or_after_native_enqueue_retire_the_actual_request(self):
        for kind in self.kinds:
            for boundary in ("before", "after"):
                for action in ("effect_reset('prewarm_reset')", "reload_modules()"):
                    with self.subTest(kind=kind, boundary=boundary, action=action):
                        lua, source = runtime(kind)
                        lua.globals().module_source = source.read_text(encoding="utf-8")
                        lua.globals().helper_source = smoke.PACKAGE_HELPER.read_text(encoding="utf-8")
                        lua.execute("""
                            function reload_modules()
                                mod._warlock_effect_package=assert(loadstring(helper_source))()
                                assert(loadstring(module_source))()
                            end
                            defer_loading=true; loaded=false
                            local raw=pm.load; local invoked=false
                            pm.load=function(self,...)
                                if invoked then return raw(self,...) end
                                invoked=true
                        """ + (action if boundary == "before" else "") + """
                                raw(self,...)
                        """ + (action if boundary == "after" else "") + """
                            end
                            assert(not effect_prewarm()); no_emitters()
                            assert(not next(s.packages) and not s.prewarm_world)
                            assert(not refs[package_reference] and events.loads==1 and events.unloads==1)
                            complete(); effect_update(); no_emitters()
                        """)

    def test_prewarm_world_release_before_or_after_enqueue_retains_until_native_world_is_gone(self):
        for kind in self.kinds:
            for boundary in ("before", "after"):
                with self.subTest(kind=kind, boundary=boundary):
                    lua, _ = runtime(kind)
                    lua.execute("""
                        defer_loading=true; loaded=false
                        local raw=pm.load; local invoked=false
                        pm.load=function(self,...)
                            if invoked then return raw(self,...) end
                            invoked=true
                    """ + ("effect_release(world)" if boundary == "before" else "") + """
                            raw(self,...)
                    """ + ("effect_release(world)" if boundary == "after" else "") + """
                        end
                        assert(not effect_prewarm()); no_emitters()
                        assert(not s.prewarm_world and refs[package_reference]==1 and events.unloads==0)
                        complete(); effect_update(); no_emitters()
                        world.alive=false; wm._worlds.level_world=nil
                        effect_update(); no_emitters()
                        assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                    """)

    def test_nested_reset_claims_unloads_once_and_keeps_variant_before_native_donor(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    assert(start())
                    local raw=pm.unload; local nested=false
                    pm.unload=function(self,name,reference)
                        if not nested then
                            nested=true; effect_reset('nested_reset')
                            assert(not effect_prewarm(),'cannot acquire while ordered unload is active')
                        end
                        if variant_package and name==package_name then
                            assert(not variant_refs[reference],'native donor unloaded before dependent effect')
                        end
                        return raw(self,name,reference)
                    end
                    effect_reset('outer_reset')
                    assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                    if variant_package then assert(events.variant_unloads==1) end
                    assert(not next(s.packages))
                """)

    def test_unload_error_preserves_ownership_and_donor_until_safe_retry(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                lua, _ = runtime(kind)
                lua.execute("""
                    assert(start())
                    local raw=pm.unload
                    local mod_raw=mod.unload_package
                    pm.unload=function() error('wrapper failed before native unload') end
                    if mod_raw then mod.unload_package=function() error('wrapper failed before mod unload') end end
                    effect_reset('failed_unload')
                    assert(events.unloads==0 and refs[package_reference]==1 and next(s.packages))
                    if variant_package then assert(variant_refs[package_reference]==1) end
                    pm.unload=raw; if mod_raw then mod.unload_package=mod_raw end
                    effect_reset('retry_unload')
                    assert(events.unloads==1 and not refs[package_reference] and refs.global==3)
                    if variant_package then assert(events.variant_unloads==1) end
                    assert(not next(s.packages))
                """)

    def test_reentrant_prewarm_or_start_cannot_forget_provisional_request_before_native_load(self):
        for kind in self.kinds:
            for boundary in ("before", "after"):
                for action in ("effect_prewarm()", "start()"):
                    with self.subTest(kind=kind, boundary=boundary, action=action):
                        lua, _ = runtime(kind)
                        lua.execute("""
                            defer_loading=true; loaded=false
                            local raw=pm.load; local nested=false
                            pm.load=function(self,...)
                                if nested then return raw(self,...) end
                                nested=true
                        """ + (action if boundary == "before" else "") + """
                                raw(self,...)
                        """ + (action if boundary == "after" else "") + """
                            end
                            assert(not effect_prewarm()); no_emitters()
                            assert(s.packages[package_name]==pm and refs[package_reference]==1)
                            assert(events.loads==1 and events.unloads==0)
                            complete(); effect_prewarm(); effect_update()
                            assert(start()); assert(events.created==1 and events.loads==1)
                            effect_reset('done'); assert(events.unloads==1 and refs.global==3)
                        """)

    def test_pending_vmf_variant_retires_only_after_completion_and_keeps_native_donor(self):
        lua, _ = runtime("crystal")
        lua.execute("""
            defer_variant_loading=true; variant_loaded=false
            assert(not start()); no_emitters()
            effect_reset('cancel_loading_variant')
            assert(variant_refs[package_reference]==1 and refs[package_reference]==1)
            assert(events.unloads==0 and not events.variant_unloads)
            assert(not next(s.pending_owners))
            finish_variant() -- completion retires packages even without mod.update
            no_emitters()
            assert(events.unloads==1 and events.variant_unloads==1)
            assert(not next(s.packages) and not refs[package_reference] and refs.global==3)
        """)

    def test_new_live_lease_reuses_pending_vmf_request_and_cancels_deferred_retirement(self):
        lua, _ = runtime("crystal")
        lua.execute("""
            defer_variant_loading=true; variant_loaded=false
            assert(not start()); effect_reset('old_cancelled_request')
            assert(events.loads==1 and events.variant_loads==1 and events.unloads==0)
            assert(not start()); assert(events.variant_loads==1)
            finish_variant(); effect_update()
            assert(events.created==1 and events.loads==1 and events.variant_loads==1 and events.unloads==0)
            effect_reset('done'); assert(events.unloads==1 and events.variant_unloads==1)
        """)

    def test_vmf_enqueue_reset_reload_and_release_cannot_dispose_native_donor_early(self):
        for boundary in ("before", "after"):
            for action in ("effect_reset('during_vmf_enqueue')", "reload_modules()", "effect_release(world)"):
                with self.subTest(boundary=boundary, action=action):
                    lua, source = runtime("crystal")
                    lua.globals().module_source = source.read_text(encoding="utf-8")
                    lua.globals().helper_source = smoke.PACKAGE_HELPER.read_text(encoding="utf-8")
                    lua.execute("""
                        function reload_modules()
                            mod._warlock_effect_package=assert(loadstring(helper_source))()
                            assert(loadstring(module_source))()
                        end
                        defer_variant_loading=true; variant_loaded=false
                        local raw=mod.load_package; local nested=false
                        mod.load_package=function(self,...)
                            if nested then return raw(self,...) end
                            nested=true
                    """ + (action if boundary == "before" else "") + """
                            raw(self,...)
                    """ + (action if boundary == "after" else "") + """
                        end
                        assert(not effect_prewarm()); no_emitters()
                        assert(refs[package_reference]==1 and variant_refs[package_reference]==1 and events.unloads==0)
                        if s.releasing_worlds[world] then
                            finish_variant(); no_emitters(); assert(events.unloads==0)
                            world.alive=false; wm._worlds.level_world=nil; effect_update()
                        else
                            finish_variant()
                        end
                        no_emitters()
                        assert(events.unloads==1 and events.variant_unloads==1 and not next(s.packages))
                    """)

    def test_nested_reset_in_vmf_unload_keeps_donor_until_native_variant_release_returns(self):
        lua, _ = runtime("crystal")
        lua.execute("""
            assert(start())
            local raw=mod.unload_package; local nested=false
            mod.unload_package=function(self,...)
                if not nested then
                    nested=true; effect_reset('nested_vmf_unload')
                    assert(refs[package_reference]==1 and events.unloads==0)
                    assert(not effect_prewarm())
                end
                return raw(self,...)
            end
            effect_reset('outer_reset')
            assert(events.unloads==1 and events.variant_unloads==1)
            assert(not next(s.packages) and refs.global==3)
        """)

    def test_hidden_vmf_cancellation_is_revived_for_live_world_without_a_reset(self):
        for native_finished in (False, True):
            with self.subTest(native_finished=native_finished):
                lua, _ = runtime("crystal")
                lua.execute("""
                    defer_variant_loading=true; variant_loaded=false
                    assert(not start()); no_emitters()
                    variant_cancelled=true
                    assert(mod:package_status(variant_package)==nil and refs[package_reference]==1)
                """ + ("finish_variant()" if native_finished else "") + """
                    effect_prewarm(); effect_update(); no_emitters()
                    assert(mod:package_status(variant_package)=='loading')
                    assert(refs[package_reference]==1 and events.unloads==0)
                    finish_variant(); effect_update()
                    assert(events.created==1 and events.linked==1 and events.loads==1)
                    effect_reset('done'); assert(events.unloads==1 and events.variant_unloads==1)
                """)

    def test_hidden_vmf_cancellation_during_retirement_keeps_donor_and_finishes_owned_cleanup(self):
        lua, _ = runtime("crystal")
        lua.execute("""
            defer_variant_loading=true; variant_loaded=false
            assert(not start()); variant_cancelled=true
            effect_reset('cancel_hidden_vmf_request'); no_emitters()
            assert(events.unloads==0 and refs[package_reference]==1)
            assert(events.variant_revivals==1 and mod:package_status(variant_package)=='loading')
            finish_variant(); no_emitters()
            assert(events.unloads==1 and events.variant_unloads==1 and not next(s.packages))
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
