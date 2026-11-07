"""Run the real wield hooks against native inventory relink/queue behavior."""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
calls={}; owner={}; unrelated={}; weapon={}; stowed={}
inventory={unit=owner,wielded=true,current_item_set_index=1,
 item_sets={{start_index=1,end_index=1},{start_index=2,end_index=2}},
 inventory_item_units={weapon,stowed},inventory_items_n=2}
system={units_to_wield={owner},units_to_wield_n=1,unit_extension_data={[owner]=inventory}}
mod={_warlock_outfits={[owner]={}}}
function mod._stop_warlock_grip_alignment_item(u,item)
 assert(u==owner);calls[#calls+1]=item==weapon and 'stop:weapon' or 'stop:stowed'
end
function mod._resume_warlock_grip_alignment_item(u,item)
 assert(u==owner);calls[#calls+1]=item==weapon and 'resume:weapon' or 'resume:stowed'
end
AIInventoryExtension={unwield_set=function(self,index,...)
 calls[#calls+1]='native:unwield';return nil,'unwielded',nil
end}
AIInventorySystem={update=function(self,...)
 calls[#calls+1]='native:wield';self.units_to_wield_n=0
 inventory.current_item_set_index=2
 args={n=select('#',...),...}
 if native_error then error('native wield failed') end
 return nil,'wielded',nil,9,nil
end}
function mod:hook(obj,name,handler)
 local original=obj[name];obj[name]=function(...) return handler(original,...) end
end
function pack(...) return {n=select('#',...),...} end
'''


def runtime():
    source = (ROOT / "scripts/mods/doomrocket/utils/hooks.lua").read_text(encoding="utf-8")
    start = source.index('mod:hook(AIInventoryExtension, "unwield_set",')
    end = source.index('-- Forget IDs before the engine releases the world.', start)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS + source[start:end])
    return lua


def destroy_runtime():
    source = (ROOT / "scripts/mods/doomrocket/utils/hooks.lua").read_text(encoding="utf-8")
    start = source.index('mod:hook(AIInventoryExtension, "destroy",')
    end = source.index('mod:hook(AIInventoryExtension, "freeze",', start)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(r'''
        owner={}; outfit={}; replacement={}; unrelated={}; driver={}
        inventory={unit=owner}; calls={}
        function pack(...) return {n=select('#',...),...} end
        mod={_warlock_outfits={[owner]=outfit},
             _warlock_outfit_owners={[outfit]=owner},
             _warlock_active_death_drivers={[driver]=true}}
        for _,name in ipairs({'_stop_warlock_grip_alignment',
            '_stop_warlock_animation_ownership','_stop_warlock_outfit_correction',
            '_stop_warlock_living_sounds','_forget_warlock_audio_owner',
            '_stop_warlock_locomotion_animation','_stop_warlock_hose',
            '_stop_warlock_weapon_pose_probe','_stop_warlock_backpack_smoke',
            '_stop_warlock_crystal_flame'}) do
            local phase=name
            mod[name]=function(unit)
                assert(unit==inventory.unit)
                calls[#calls+1]=phase
                if replace_during_cleanup and phase=='_stop_warlock_crystal_flame' then
                    mod._warlock_outfits[owner]=replacement
                    mod._warlock_outfit_owners[replacement]=owner
                end
            end
        end
        AIInventoryExtension={destroy=function(self,...)
            calls[#calls+1]='native:destroy'; native_args=pack(...)
            native_owner_mapping=mod._warlock_outfits[self.unit]
            if native_error then error('native destroy failed') end
            return nil,'destroyed',nil
        end}
        function mod:hook(object,name,handler)
            local original=object[name]
            object[name]=function(...) return handler(original,...) end
        end
    ''' + source[start:end])
    return lua


class InventoryDestroyRegistryTests(unittest.TestCase):
    def test_destroy_retires_both_mirror_handles_before_native_and_preserves_returns(self):
        lua = destroy_runtime()
        lua.execute('''
            local result=pack(AIInventoryExtension.destroy(inventory,0.02,nil,'tail'))
            assert(mod._warlock_outfits[owner]==nil)
            assert(mod._warlock_outfit_owners[outfit]==nil and native_owner_mapping==nil)
            assert(calls[#calls]=='native:destroy' and #calls==11)
            assert(result.n==3 and result[2]=='destroyed')
            assert(native_args.n==3 and native_args[1]==0.02 and native_args[2]==nil
                and native_args[3]=='tail')
        ''')

    def test_newer_outfit_registered_during_cleanup_survives(self):
        lua = destroy_runtime()
        lua.execute('''
            replace_during_cleanup=true; AIInventoryExtension.destroy(inventory)
            assert(mod._warlock_outfits[owner]==replacement)
            assert(mod._warlock_outfit_owners[replacement]==owner)
            assert(mod._warlock_outfit_owners[outfit]==nil)
        ''')

    def test_unrelated_inventory_does_not_retire_another_owner(self):
        lua = destroy_runtime()
        lua.execute('''
            inventory.unit=unrelated; AIInventoryExtension.destroy(inventory)
            assert(mod._warlock_outfits[owner]==outfit)
            assert(mod._warlock_outfit_owners[outfit]==owner)
        ''')

    def test_death_driver_survives_already_detached_inventory(self):
        lua = destroy_runtime()
        lua.execute('''
            mod._warlock_outfits[owner]=nil; mod._warlock_outfit_owners[outfit]=nil
            AIInventoryExtension.destroy(inventory)
            assert(mod._warlock_active_death_drivers[driver])
        ''')

    def test_native_failure_does_not_retain_dead_mirroring_handles(self):
        lua = destroy_runtime()
        lua.execute('''
            native_error=true; assert(not pcall(AIInventoryExtension.destroy,inventory))
            assert(mod._warlock_outfits[owner]==nil)
            assert(mod._warlock_outfit_owners[outfit]==nil)
        ''')

    def test_foreign_reverse_mapping_is_not_removed(self):
        lua = destroy_runtime()
        lua.execute('''
            mod._warlock_outfit_owners[outfit]=unrelated
            AIInventoryExtension.destroy(inventory)
            assert(mod._warlock_outfits[owner]==nil)
            assert(mod._warlock_outfit_owners[outfit]==unrelated)
        ''')


class InventoryAnimationLinkTests(unittest.TestCase):
    def test_unwield_stops_following_before_native_relink(self):
        lua = runtime()
        lua.execute('''
            local result=pack(AIInventoryExtension.unwield_set(inventory,1))
            assert(table.concat(calls,',')=='stop:weapon,native:unwield')
            assert(result.n==3 and result[2]=='unwielded')
        ''')

    def test_resume_uses_completed_native_wield_range_and_preserves_returns(self):
        lua = runtime()
        lua.execute('''
            local result=pack(AIInventorySystem.update(system,0.02,nil,'tail'))
            assert(table.concat(calls,',')=='native:wield,resume:stowed')
            assert(system.units_to_wield_n==0 and inventory.current_item_set_index==2)
            assert(result.n==5 and result[2]=='wielded' and result[4]==9)
            assert(args.n==3 and args[1]==0.02 and args[2]==nil and args[3]=='tail')
        ''')

    def test_dropped_unqueued_and_unrelated_units_do_not_resume(self):
        for preparation in (
            'inventory.dropped=true',
            'system.units_to_wield_n=0',
            'system.units_to_wield={unrelated}',
            'inventory.wielded=false',
        ):
            with self.subTest(preparation=preparation):
                lua = runtime()
                lua.execute(preparation + ";AIInventorySystem.update(system);assert(table.concat(calls,',')=='native:wield')")

    def test_native_failure_cannot_resume_an_incomplete_wield(self):
        lua = runtime()
        lua.execute('''
            native_error=true
            assert(not pcall(AIInventorySystem.update,system))
            assert(table.concat(calls,',')=='native:wield')
        ''')


if __name__ == "__main__":
    unittest.main()
