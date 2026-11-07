"""Exercise production animation dispatch before either unit evaluates a clip."""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"
HARNESS = r'''
calls={}; owner={alive=true,breed={name='skaven_doomrocket'}}
outfit={alive=true}; other={alive=true}; supported=true
mod={_warlock_outfits={[owner]=outfit},_warlock_outfit_owners={[outfit]=owner}}
local function record(s) calls[#calls+1]=s end
unit_get_data=function(u,key) assert(key=='breed');return u.breed end
has_animation_event=function(u,event) return supported end
Unit={alive=function(u) return u.alive end}
function mod._note_warlock_animation_ownership_event(u,event,mirrored)
 assert(u==owner); record('ownership:'..event..':'..tostring(mirrored))
end
function mod._note_warlock_weapon_pose_event(u,event,mirrored) record('probe') end
function mod._note_warlock_grip_alignment_event(u,event,mirrored) record('grip') end
local function original(u,event,...)
 record((u==outfit and 'outfit:' or u==owner and 'owner:' or 'other:')..event)
 last_args={n=select('#',...),...}
 return nil,'native-result',nil,17,nil
end
function mod:hook(object,name,handler)
 assert(object==Unit and name=='animation_event')
 Unit.animation_event=function(...) return handler(original,...) end
end
function pack(...) return {n=select('#',...),...} end
'''


def runtime():
    source = HOOKS.read_text(encoding="utf-8")
    start = source.index('\nmod:hook(Unit, "animation_event", function(func, unit, event, ...)') + 1
    end = source.index('-- NO raw-index animation mirroring.', start)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS + source[start:end])
    return lua


class AnimationDispatchTests(unittest.TestCase):
    def test_carrier_protection_precedes_outfit_dispatch_and_preserves_returns(self):
        lua = runtime()
        lua.execute('''
            local results=pack(Unit.animation_event(owner,'idle',23,nil,'tail'))
            assert(table.concat(calls,',')=='ownership:idle:true,outfit:idle,probe,grip,owner:idle')
            assert(results.n==5 and results[2]=='native-result' and results[4]==17)
            assert(last_args.n==3 and last_args[1]==23 and last_args[2]==nil and last_args[3]=='tail')
        ''')

    def test_direct_outfit_event_is_protected_before_native_dispatch(self):
        lua = runtime()
        lua.execute('''
            Unit.animation_event(outfit,'attack_shoot_loop')
            assert(table.concat(calls,',')=='ownership:attack_shoot_loop:true,outfit:attack_shoot_loop')
        ''')

    def test_unrelated_units_and_unsupported_carrier_event_preserve_existing_behavior(self):
        lua = runtime()
        lua.execute('''
            Unit.animation_event(other,'idle')
            assert(table.concat(calls,',')=='other:idle')
            calls={};supported=false
            assert(pack(Unit.animation_event(owner,'unknown')).n==0 and #calls==0)
        ''')

    def test_missing_direct_outfit_event_never_reaches_native_dispatch(self):
        lua = runtime()
        lua.execute('''
            supported=false
            assert(pack(Unit.animation_event(outfit,'unknown')).n==0)
            assert(table.concat(calls,',')=='ownership:unknown:false')
        ''')

    def test_stale_outfit_is_removed_without_ownership_or_outfit_dispatch(self):
        lua = runtime()
        lua.execute('''
            outfit.alive=false;Unit.animation_event(owner,'idle')
            assert(table.concat(calls,',')=='owner:idle')
            assert(mod._warlock_outfits[owner]==nil and mod._warlock_outfit_owners[outfit]==nil)
        ''')

    def test_replaced_outfit_cannot_change_the_new_outfit_owner(self):
        lua = runtime()
        lua.execute('''
            mod._warlock_outfits[owner]=other
            Unit.animation_event(outfit,'idle')
            assert(table.concat(calls,',')=='outfit:idle')
            assert(mod._warlock_outfit_owners[outfit]==nil)
        ''')


if __name__ == "__main__":
    unittest.main()
