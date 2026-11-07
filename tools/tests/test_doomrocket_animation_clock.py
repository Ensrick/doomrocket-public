"""Check native layer preconditions before the API call, not Lua error recovery.

The installed SDK documents zero-based layers, one get_state return per layer,
and nil when no state is playing. These doubles cannot prove engine playback.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/utils/doomrocket_animation_clock.lua"
HARNESS = r'''
world={};other_world={}
unit={alive=true,world=world,asm=true,
 state_mode='one',time=.25,length=2}
calls={alive=0,world=0,asm=0,states=0,clock=0,illegal=0}
local function valid(u)
 if not u or not u.alive then calls.illegal=calls.illegal+1;error('native dead-unit assertion') end
end
Unit={
 alive=function(u) calls.alive=calls.alive+1;return u and u.alive end,
 world=function(u) valid(u);calls.world=calls.world+1;return u.world end,
 has_animation_state_machine=function(u) valid(u);calls.asm=calls.asm+1;return u.asm end,
 animation_get_state=function(u)
  valid(u);calls.states=calls.states+1
  if not u.asm then calls.illegal=calls.illegal+1;error('native missing-ASM assertion') end
  if mutate then mutate(u) end
  if u.state_mode=='zero' then return end
  if u.state_mode=='nil' then return nil end
  if u.state_mode=='two' then return 17,nil end
  if u.state_mode=='fraction' then return .5 end
  if u.state_mode=='nan' then return 0/0 end
  if u.state_mode=='string' then return '17' end
  if u.state_mode=='zero_id' then return 0 end
  return 17
 end,
 animation_layer_info=function(u,index)
  calls.clock=calls.clock+1
  if not u or not u.alive or not u.asm or u.state_mode=='zero' or u.state_mode=='nil'
   or u.state_mode=='two' or index~=0 then
   calls.illegal=calls.illegal+1;error('uncatchable-native-assert analogue')
  end
  return u.time,u.length
 end,
}
function sample() time,length,reason=read_clock(unit,world) end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.globals().read_clock = lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


class AnimationClockTests(unittest.TestCase):
    def test_bare_bound_sampler_needs_no_unit_metadata_and_uses_layer_zero(self):
        lua = runtime()
        self.assertIsNone(lua.eval("unit.name"))
        self.assertIsNone(lua.eval("Unit.get_data"))
        lua.execute("sample()")
        self.assertEqual((lua.eval("time"), lua.eval("length")), (.25, 2))
        self.assertIsNone(lua.eval("reason"))
        self.assertEqual(lua.eval("calls.clock"), 1)
        self.assertEqual(lua.eval("calls.illegal"), 0)
        lua.execute("unit.state_mode='zero_id';sample()")
        self.assertEqual(lua.eval("calls.clock"), 2)

    def test_unready_or_wrong_world_unit_never_attempts_native_layer_read(self):
        for change, reason in (
            ("unit=nil", "dead_unit"),
            ("unit.alive=false", "dead_unit"),
            ("unit.world=other_world", "wrong_world"),
            ("world=nil", "wrong_world"),
            ("unit.asm=false", "missing_state_machine"),
            ("unit.state_mode='zero'", "unsupported_layer_count"),
            ("unit.state_mode='nil'", "unready_animation_state"),
            # Trailing nil is a real second layer; #table would lose it.
            ("unit.state_mode='two'", "unsupported_layer_count"),
            ("unit.state_mode='fraction'", "unready_animation_state"),
            ("unit.state_mode='nan'", "unready_animation_state"),
            ("unit.state_mode='string'", "unready_animation_state"),
        ):
            with self.subTest(change=change):
                lua = runtime()
                lua.execute(change + ";sample()")
                self.assertEqual(lua.eval("reason"), reason)
                self.assertEqual(lua.eval("calls.clock + calls.illegal"), 0)
                self.assertIsNone(lua.eval("time"))

    def test_missing_apis_fail_before_any_native_calls(self):
        for api in ("alive", "world", "has_animation_state_machine",
                    "animation_get_state", "animation_layer_info"):
            with self.subTest(api=api):
                lua = runtime()
                lua.execute(f"Unit.{api}=nil;sample()")
                self.assertEqual(lua.eval("reason"), "missing_clock_api")
                self.assertEqual(lua.eval("calls.alive + calls.states + calls.clock + calls.illegal"), 0)
        lua = runtime()
        lua.execute("Unit=nil;sample()")
        self.assertEqual(lua.eval("reason"), "missing_clock_api")

    def test_state_read_lifetime_and_controller_changes_are_rechecked_before_layer_query(self):
        for change, reason in (("u.alive=false", "dead_unit"),
                               ("u.world=other_world", "wrong_world"),
                               ("u.asm=false", "missing_state_machine")):
            with self.subTest(change=change):
                lua = runtime()
                lua.execute("mutate=function(u) " + change + " end;sample()")
                self.assertEqual(lua.eval("reason"), reason)
                self.assertEqual(lua.eval("calls.states"), 1)
                self.assertEqual(lua.eval("calls.clock + calls.illegal"), 0)

    def test_sentinel_nonfinite_and_out_of_range_clocks_never_escape(self):
        for change in ("unit.length=1e37", "unit.length=3600.001", "unit.length=0",
                       "unit.length=-1", "unit.length=math.huge", "unit.length=0/0",
                       "unit.time=0/0", "unit.time=math.huge", "unit.time=-.001", "unit.time=2.003"):
            with self.subTest(change=change):
                lua = runtime()
                lua.execute(change + ";sample()")
                self.assertEqual(lua.eval("reason"), "invalid_clock")
                self.assertIsNone(lua.eval("time"))
                self.assertIsNone(lua.eval("length"))
                self.assertEqual(lua.eval("calls.clock"), 1)
                self.assertEqual(lua.eval("calls.illegal"), 0)

    def test_documented_supported_boundaries_and_per_call_readiness(self):
        lua = runtime()
        lua.execute("unit.length=3600;unit.time=3600.001;sample()")
        self.assertEqual(lua.eval("length"), 3600)
        lua.execute("unit.state_mode='zero';sample()")
        self.assertEqual(lua.eval("calls.clock"), 1)
        self.assertEqual(lua.eval("reason"), "unsupported_layer_count")

    def test_lua_api_failure_is_contained_without_trying_the_layer(self):
        lua = runtime()
        lua.execute("Unit.animation_get_state=function() error('unsupported API') end;sample()")
        self.assertEqual(lua.eval("reason"), "clock_api_error")
        self.assertEqual(lua.eval("calls.clock + calls.illegal"), 0)


if __name__ == "__main__":
    unittest.main()
