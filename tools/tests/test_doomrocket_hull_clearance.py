"""Execute the shipped Lua solver against the actual convex rocket bounds.

These regressions distinguish the old point endpoint from clearance for the
1.28 m rocket. They do not claim runtime aim or collision acceptance.
"""
from pathlib import Path
import math
import re
import unittest

from lupa.lua51 import LuaRuntime

from test_warlock_weapon_pipeline import BinaryFbx, geometry_by_vertex_count, raw_geometry_points

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/mods/doomrocket/utils/doomrocket_ballistics.lua"
LAUNCH = ROOT / "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_launch_action.lua"
PROJECTILE = ROOT / "scripts/mods/doomrocket/extensions/projectile_rocket.lua"

LUA_VECTORS = """
local mt={}
function v(x,y,z) return setmetatable({x=x,y=y,z=z},mt) end
mt.__add=function(a,b) return v(a.x+b.x,a.y+b.y,a.z+b.z) end
mt.__sub=function(a,b) return v(a.x-b.x,a.y-b.y,a.z-b.z) end
Vector3=setmetatable({}, {__call=function(_,x,y,z) return v(x,y,z) end})
Vector3.flat=function(a) return v(a.x,a.y,0) end
Vector3.length_squared=function(a) return a.x*a.x+a.y*a.y+a.z*a.z end
Vector3.length=function(a) return math.sqrt(Vector3.length_squared(a)) end
Vector3.is_valid=function(a)
 return a and a.x==a.x and a.y==a.y and a.z==a.z
  and math.abs(a.x)<math.huge and math.abs(a.y)<math.huge and math.abs(a.z)<math.huge
end
math.clamp=function(x,a,b) return math.min(math.max(x,a),b) end
AiAnimUtils={velocity_network_scale=function(a,sending)
 if sending then return {math.floor(a.x*10+.5),math.floor(a.y*10+.5),math.floor(a.z*10+.5)} end
 return v(a[1]*.1,a[2]*.1,a[3]*.1)
end}
mod={}
get_mod=function() return mod end
"""


class RocketHullClearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lua = LuaRuntime(unpack_returned_tuples=True)
        cls.lua.execute(LUA_VECTORS)
        cls.lua.execute(HELPER.read_text(encoding="utf-8"))
        cls.ballistics = cls.lua.globals().mod.doomrocket_ballistics
        cls.vec = cls.lua.globals().v
        fbx = BinaryFbx(ROOT / "units/rocket/SM_Rocket.fbx")
        cls.points = raw_geometry_points(geometry_by_vertex_count(fbx, 622))

    def shot(self, distance, start_z, floor_z):
        start = self.vec(0, 0, start_z)
        floor = self.vec(distance, 0, floor_z)
        target = self.ballistics.clear_target_position(start, floor, .25)
        velocity, duration = self.ballistics.solve_launch_velocity(start, target)
        return target, velocity, duration

    def test_bounds_enclose_every_shipped_convex_hull_vertex(self):
        b = self.ballistics
        for x, y, z in self.points:
            self.assertGreaterEqual(y, -b.ROCKET_REAR_EXTENT)
            self.assertLessEqual(y, b.ROCKET_FORWARD_EXTENT)
            self.assertLessEqual(math.hypot(x, z), b.ROCKET_RADIUS + 1e-6)

    def test_old_quarter_metre_endpoint_intersects_ground_at_close_range(self):
        # A 5 m shot from a 1 m muzzle reaches its point target correctly,
        # but the descending 54 cm nose is already below the target's floor.
        b = self.ballistics
        velocity, duration = b.solve_launch_velocity(self.vec(0, 0, 1), self.vec(5, 0, .25))
        incoming = self.vec(velocity.x, velocity.y, velocity.z - b.GRAVITY * duration)
        self.assertLess(.25 - b.lower_hull_extent(incoming), -.1)

    def test_endpoint_clears_ground_for_near_medium_long_and_height_changes(self):
        b = self.ballistics
        for distance in (1, 1.34, 2, 3, 5, 8, 15, 30, 50):
            for floor_z in (-6, -3, 0, 3, 6):
                with self.subTest(distance=distance, floor_z=floor_z):
                    target, velocity, duration = self.shot(distance, 1, floor_z)
                    incoming = self.vec(velocity.x, velocity.y, velocity.z - b.GRAVITY * duration)
                    clearance = target.z - floor_z - b.lower_hull_extent(incoming)
                    # Corrected point may be lower when the actual quantizer
                    # raises the decoded endpoint; physics clearance is below.
                    self.assertGreater(clearance, -.15)
                    self.assertEqual(target.x, distance)
                    self.assertEqual(duration, min(max(distance * .13, .4), 3.4))
                    landed_z = 1 + velocity.z * duration - .5 * b.GRAVITY * duration**2
                    self.assertAlmostEqual(landed_z, target.z, places=10)
                    # The production 0.1 m/s quantizer still clears the floor.
                    quantized = [math.floor(c * 10 + .5) / 10 for c in (velocity.x, velocity.y, velocity.z)]
                    final_z = 1 + quantized[2] * duration - .5 * b.GRAVITY * duration**2
                    quant_incoming = self.vec(quantized[0], quantized[1], quantized[2] - b.GRAVITY * duration)
                    self.assertGreaterEqual(final_z - floor_z - b.lower_hull_extent(quant_incoming),
                                            b.TARGET_GROUND_CLEARANCE - 1e-5)

    def test_flat_near_shots_clear_ground_through_entire_flight(self):
        b = self.ballistics
        for distance in (1.34, 2, 3, 5, 8):
            target, ideal_velocity, duration = self.shot(distance, 1, 0)
            velocity = self.vec(*(math.floor(c * 10 + .5) / 10
                                  for c in (ideal_velocity.x, ideal_velocity.y, ideal_velocity.z)))
            for step in range(101):
                t = duration * step / 100
                height = 1 + velocity.z * t - .5 * b.GRAVITY * t**2
                tangent = self.vec(velocity.x, velocity.y, velocity.z - b.GRAVITY * t)
                self.assertGreater(height - b.lower_hull_extent(tangent), 0)

    def test_quantizer_plateaus_cannot_exhaust_clearance_without_moving_physics(self):
        b = self.ballistics
        # Include the formerly failing 5.70 m near shot and long/elevated
        # plateau discovered by review, alongside a dense range/height sweep.
        distances = [1 + step * .05 for step in range(981)] + [5.70, 16.84, 83.13]
        for distance in distances:
            for floor_z in (-6, -3, 0, 3, 6):
                target, ideal, duration = self.shot(distance, 1, floor_z)
                decoded = [math.floor(c * 10 + .5) / 10 for c in (ideal.x, ideal.y, ideal.z)]
                height = 1 + decoded[2] * duration - .5 * b.GRAVITY * duration**2
                incoming = self.vec(decoded[0], decoded[1], decoded[2] - b.GRAVITY * duration)
                clearance = height - floor_z - b.lower_hull_extent(incoming)
                self.assertGreaterEqual(clearance, b.TARGET_GROUND_CLEARANCE - 1e-5,
                                        (distance, floor_z, target.z, decoded))

    def test_time_clamps_remain_continuous_after_clearance(self):
        for boundary in (.4 / .13, 3.4 / .13):
            left = self.shot(boundary - 1e-6, 1, 0)
            right = self.shot(boundary + 1e-6, 1, 0)
            self.assertLess(abs(left[2] - right[2]), 1e-5)
            # The endpoint accounts for a discrete velocity quantizer, so the
            # vertical correction may step by <= one velocity bin * T.
            self.assertLess(abs(left[0].z - right[0].z), .1 * right[2] + .01)

    def test_physics_starts_on_decoded_tangent_without_globe_spin(self):
        launch = re.sub(r"--[^\n]*", "", LAUNCH.read_text(encoding="utf-8"))
        shot = launch[launch.index("BTDoomrocketLaunchAction._shoot ="):]
        self.assertIn("Quaternion.look(replicated_velocity, Vector3.up())", shot)
        self.assertIn("network_angular_velocity = {0, 0, 0}", shot)
        self.assertLess(shot.index("local rotation = Quaternion.look"), shot.index("rotation_network_scale(rotation, true)"))
        projectile = re.sub(r"--[^\n]*", "", PROJECTILE.read_text(encoding="utf-8"))
        init = projectile[projectile.index("ProjectileRocket.init ="):projectile.index("ProjectileRocket.update =")]
        self.assertIn("self:straighten_rocket(launch_velocity)", init)
        self.assertIn("self:_remember_path(Actor.position(actor), launch_velocity)", init)
        self.assertIn("Actor.set_angular_velocity(actor, Vector3.zero())", init)
        # Contact detonation and shooter/rocket exclusions must survive this fix.
        self.assertIn("hit_unit ~= self.unit and hit_unit ~= self.attacker_unit", projectile)
        self.assertIn("self:_left_ballistic_path(vel, dt)", projectile)

    def test_both_lanes_solve_from_the_actual_decoded_muzzle_position(self):
        source = LAUNCH.read_text(encoding="utf-8")
        helper = source[source.index("BTDoomrocketLaunchAction._fire_from_position_direction ="):
                        source.index("BTDoomrocketLaunchAction._shoot =")]
        self.assertIn("AiAnimUtils.position_network_scale(fire_position, true)", helper)
        self.assertIn("fire_position = AiAnimUtils.position_network_scale(network_fire_position)", helper)
        self.assertLess(helper.index("fire_position = AiAnimUtils.position_network_scale(network_fire_position)"),
                        helper.index("return fire_position, direction"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
