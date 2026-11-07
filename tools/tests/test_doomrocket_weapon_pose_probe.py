"""Exercise the read-only same-frame grip probe against strict unit doubles."""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_weapon_pose_probe.lua"
BOOTSTRAP = ROOT / "scripts/mods/doomrocket/doomrocket.lua"
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"

HARNESS = r"""
world={}; other_world={}; epoch=1; reads=0; writes=0; messages={}; callbacks={}
local pi=math.pi
local function vector(x,y,z)
 local made=epoch;local values={x=x,y=y,z=z}
 return setmetatable({},{__index=function(_,key)
  assert(made==epoch,'retained native vector');return values[key]
 end})
end
Vector3=setmetatable({}, {__call=function(_,x,y,z) return vector(x,y,z) end})
Quaternion={
 inverse=function(a) return -a end,
 rotate=function(a,v)
  return vector(math.cos(a)*v.x-math.sin(a)*v.y,math.sin(a)*v.x+math.cos(a)*v.y,v.z)
 end,
 angle=function(a,b) return math.abs(a-b) end,
}
function printf(...) messages[#messages+1]=string.format(...) end
mod={_warlock_outfits={}}
function mod:pcall(fn,...)
 local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result
end
function get_mod(name) assert(name=='doomrocket');return mod end
HEALTH_ALIVE={}
local function unit(kind,name)
 return {kind=kind,name=name,alive=true,world=world,poses={}}
end
owner=unit('owner','carrier')
outfit=unit('outfit','units/warlock_bombardier/warlock_bombardier_3p')
weapon=unit('weapon','units/rocket/pRocketLauncher')
mod._warlock_outfits[owner]=outfit;HEALTH_ALIVE[owner]=true
owner.poses[0]={0,0,0,pi/2}
owner.poses.j_lefthand={1,0,0,0}
owner.poses.j_righthand={0,1,0,0}
owner.poses.j_leftweaponattach={2,0,0,0}
owner.poses.j_leftweaponcomponent1={2,1,0,0}
outfit.poses[0]={0,0,0,pi/2}
outfit.poses.j_lefthand={1,0.1,0,0.1}
outfit.poses.j_righthand={0,1.3,0,0.2}
outfit.poses.j_leftweaponattach={2,0.2,0,0.3}
outfit.poses.j_leftweaponcomponent1={2,1,0,0}
weapon.poses[0]={2,0,0,0}
weapon.poses.handle={1,0,0,0}
weapon.poses.a_barrel={2,1,0,0}
inventory={unit=owner,inventory_item_units={outfit,weapon}}
local function valid(u) assert(u and u.alive,'stale native unit') end
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) valid(u);return u.world end,
 get_data=function(u,key) valid(u);assert(key=='unit_name');return u.name end,
 has_node=function(u,name) valid(u);return u.poses[name]~=nil end,
 node=function(u,name) valid(u);assert(u.poses[name],'missing native node');return name end,
 world_position=function(u,node)
  valid(u);reads=reads+1;local p=assert(u.poses[node]);return vector(p[1],p[2],p[3])
 end,
 world_rotation=function(u,node)
  valid(u);reads=reads+1;return assert(u.poses[node])[4]
 end,
 set_local_rotation=function(...) writes=writes+1;error('probe wrote a bone') end,
 set_local_pose=function(...) writes=writes+1;error('probe wrote a pose') end,
}
animation={add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn end}
World={update_unit=function(w,u) valid(u);assert(u.world==w) end}
Managers={state={entity={system=function(self,name)
 assert(name=='animation_system');return animation
end}}}
function drain()
 local pending=callbacks;callbacks={}
 for _,fn in ipairs(pending) do fn() end
 epoch=epoch+1
end
function tick(dt,w)
 mod._queue_warlock_weapon_pose_probe(w or world,dt);drain()
end
function grip_lines()
 local count=0
 for _,line in ipairs(messages) do if line:find('left_vn_cm=',1,true) then count=count+1 end end
 return count
end
"""


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


class WeaponPoseProbeTests(unittest.TestCase):
    def test_same_frame_carrier_root_metrics_are_read_only(self):
        lua = runtime()
        lua.execute("assert(mod._start_warlock_weapon_pose_probe(owner,outfit,inventory));tick(0.05)")
        line = lua.eval("messages[#messages]")
        self.assertIn("stage=post_unit_update", line)
        self.assertIn("alignment=off", line)
        self.assertIn("left_vn_cm=10.00,0.00,0.00", line)
        self.assertIn("handle_n_cm=0.00,0.00,0.00", line)
        self.assertRegex(line, r"handle_v_cm=-10\.00,-?0\.00,0\.00")
        self.assertIn("right_vn_cm=30.00,0.00,0.00", line)
        self.assertIn("left_rot_deg=5.7", line)
        self.assertEqual(lua.eval("writes"), 0)

    def test_event_and_speed_are_sampled_without_native_writes(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_weapon_pose_probe(owner,outfit,inventory)
            tick(0.1)
            mod._note_warlock_weapon_pose_event(owner,'move_fwd_run',true)
            owner.poses[0][1]=0.4
            tick(0.1);tick(0.1)
        """)
        line = lua.eval("messages[#messages]")
        self.assertIn("event=move_fwd_run mirrored=true", line)
        self.assertRegex(line, r"speed_mps=[12]\.\d+")
        self.assertEqual(lua.eval("writes"), 0)

    def test_missing_optional_visible_attachment_keeps_hand_probe(self):
        lua = runtime()
        lua.execute("""
            outfit.poses.j_leftweaponattach=nil
            assert(mod._start_warlock_weapon_pose_probe(owner,outfit,inventory))
            tick(0.1)
        """)
        self.assertIn("attach_source=hand_fallback", lua.eval("messages[#messages]"))
        self.assertIn("left_vn_cm=", lua.eval("messages[#messages]"))

    def test_rate_limit_and_sixty_second_lifetime(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_weapon_pose_probe(owner,outfit,inventory)
            for i=1,1205 do tick(0.05) end
        """)
        count = lua.eval("grip_lines()")
        self.assertGreaterEqual(count, 200)
        self.assertLessEqual(count, 300)
        self.assertEqual(lua.eval("#callbacks"), 0)
        lua.execute("local before=grip_lines();tick(0.05);assert(grip_lines()==before)")

    def test_death_and_world_release_invalidate_queued_callbacks(self):
        for action in (
            "mod._stop_warlock_weapon_pose_probe(owner)",
            "mod._release_warlock_weapon_pose_probe_world(world)",
            "mod._reset_warlock_weapon_pose_probe()",
        ):
            with self.subTest(action=action):
                lua = runtime()
                lua.execute("mod._start_warlock_weapon_pose_probe(owner,outfit,inventory)")
                lua.execute("mod._queue_warlock_weapon_pose_probe(world,0.1)")
                lua.execute(action)
                lua.execute("owner.alive=false;outfit.alive=false;weapon.alive=false;drain()")
                self.assertEqual(lua.eval("grip_lines()"), 0)

    def test_callback_error_is_contained_and_probe_stops(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_weapon_pose_probe(owner,outfit,inventory)
            local original=Quaternion.angle
            Quaternion.angle=function() error('simulated angle failure') end
            tick(0.1)
            Quaternion.angle=original
            tick(0.1)
        """)
        self.assertIn("simulated angle failure", lua.eval("mod.last_error"))
        self.assertEqual(lua.eval("grip_lines()"), 0)

    def test_existing_hook_and_lifecycle_wiring(self):
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        hooks = HOOKS.read_text(encoding="utf-8")
        self.assertIn('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_weapon_pose_probe")', bootstrap)
        self.assertIn("mod._reset_warlock_weapon_pose_probe()", bootstrap)
        self.assertIn("mod:pcall(mod._queue_warlock_weapon_pose_probe, world, dt)", hooks)
        self.assertEqual(len(re.findall(r'mod:hook\(World, "update_animations"', hooks)), 1)
        for call in (
            "mod:pcall(mod._start_warlock_weapon_pose_probe, unit, outfit_unit, self)",
            "mod._stop_warlock_weapon_pose_probe(owner_unit)",
            "mod._stop_warlock_weapon_pose_probe_item(self.unit, item_unit)",
            "mod._release_warlock_weapon_pose_probe_world(world)",
        ):
            self.assertIn(call, hooks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
