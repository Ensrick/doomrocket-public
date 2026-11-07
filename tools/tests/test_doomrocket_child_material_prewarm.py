#!/usr/bin/env python3
"""First-spawn stall (#69): the Warlock child materials load ahead of any spawn.

The v0.1.96 log stalled 216 ms flushing #ID[f5283f95], this package's hash prefix,
on the first spawn. These run the production functions from hooks.lua.
"""
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from splice_bundle_resource import murmur64a

HOOKS = (ROOT / "scripts/mods/doomrocket/utils/hooks.lua").read_text(encoding="utf-8")
PACKAGE = "resource_packages/doomrocket/warlock_child"

HARNESS = r"""
DEDICATED_SERVER=false
mod={}; status=nil; loads={}; printed={}
function printf(...) printed[#printed+1]=string.format(...) end
function mod:package_status(name) return status end
function mod:load_package(name,callback,sync)
    loads[#loads+1]={name=name,sync=sync==true}
    if sync then status='loaded' else status='loading' end
end
level_ready,donors_ready=true,true
Managers={
    world={has_world=function(_,name) return name=='level_world' and level_ready end},
    package={has_loaded=function() return donors_ready end},
}
Application={can_get=function() return false end}
Unit={set_material=function() end}
"""


def runtime():
    start = HOOKS.index("mod._prewarm_warlock_child_materials = function()")
    end = HOOKS.index('mod:hook(AIInventoryExtension, "_setup_configuration"')
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(
        f'local WARLOCK_CHILD_PACKAGE = "{PACKAGE}"\n'
        'local WARLOCK_ARMOR_DONOR_PACKAGE, WARLOCK_NATIVE_BODY_PACKAGE = "armor", "body"\n'
        "local WARLOCK_CUSTOM_TEXTURES, WARLOCK_SLOT_MATERIALS = {}, {}\n"
        "local warlock_child_package_requested = false\n" + HOOKS[start:end])
    return lua


class ChildMaterialPrewarmTests(unittest.TestCase):
    def test_log_stall_identifier_is_this_package(self):
        self.assertTrue(format(murmur64a(PACKAGE.encode()), "016x").startswith("f5283f95"))

    def test_prewarm_requests_once_without_blocking(self):
        runtime().execute("""
            for i=1,5 do mod._prewarm_warlock_child_materials() end
            assert(#loads==1 and loads[1].name=='resource_packages/doomrocket/warlock_child')
            assert(not loads[1].sync)
        """)

    def test_prewarm_waits_for_a_level_world_and_native_donors(self):
        runtime().execute("""
            level_ready=false; mod._prewarm_warlock_child_materials(); assert(#loads==0)
            level_ready,donors_ready=true,false; mod._prewarm_warlock_child_materials(); assert(#loads==0)
            donors_ready=true; mod._prewarm_warlock_child_materials(); assert(#loads==1)
        """)

    def test_finished_prewarm_never_blocks_a_spawn(self):
        runtime().execute("""
            mod._prewarm_warlock_child_materials(); status='loaded'
            mod._apply_warlock_child_materials({})
            assert(#loads==1 and not loads[1].sync)
        """)

    def test_spawn_that_beats_the_prewarm_still_gets_materials(self):
        runtime().execute("""
            mod._prewarm_warlock_child_materials()
            mod._apply_warlock_child_materials({})
            assert(#loads==2 and loads[2].sync and status=='loaded')
        """)

    def test_dedicated_server_skips_the_prewarm(self):
        runtime().execute("DEDICATED_SERVER=true; mod._prewarm_warlock_child_materials(); assert(#loads==0)")

    def test_update_prewarms_before_any_spawn(self):
        source = (ROOT / "scripts/mods/doomrocket/doomrocket.lua").read_text(encoding="utf-8")
        update = source[source.index("function mod.update(dt)"):]
        self.assertIn("mod._prewarm_warlock_child_materials()", update[:400])


if __name__ == "__main__":
    unittest.main()
