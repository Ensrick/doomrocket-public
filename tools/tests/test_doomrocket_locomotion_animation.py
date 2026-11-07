#!/usr/bin/env python3
"""Execute the visible gait controller against strict native lifetime doubles.

These verify movement/event/rate contracts and local variable ownership, not
rendered foot contact. The carrier may be engine-driven or a client husk: both
are sampled from their actual horizontal position, independent of nav commands.
"""
from pathlib import Path
import bisect
import math
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_locomotion_animation.lua"
STATE_MACHINE = ROOT / "units/warlock_bombardier/warlock_bombardier_3p.state_machine"

HARNESS = r"""
world={}; other_world={}
epoch=1
events={writes=0,finds=0,positions=0}
mod={_warlock_outfits={}}
function get_mod(name) assert(name=='doomrocket'); return mod end
HEALTH_ALIVE={}
function make_owner(w)
 local u={alive=true,world=w,x=0,y=0,z=0,kind='carrier'}
 HEALTH_ALIVE[u]=true
 return u
end
function make_outfit(w,index)
 return {alive=true,world=w,index=index,kind='outfit',has_variable=true,
  name='units/warlock_bombardier/warlock_bombardier_3p'}
end
owner=make_owner(world); outfit=make_outfit(world,83)
mod._warlock_outfits[owner]=outfit
local function live(u) assert(u and u.alive,'native access after deletion') end
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) live(u);return u.world end,
 get_data=function(u,key) live(u);assert(key=='unit_name');return u.name end,
 world_position=function(u,index)
  live(u);assert(u.kind=='carrier' and index==0)
  events.positions=events.positions+1
  local made=epoch; local p={x=u.x,y=u.y,z=u.z}
  return setmetatable({},{__index=function(_,key)
   assert(made==epoch,'retained native vector temporary');return p[key]
  end})
 end,
 animation_has_variable=function(u,name)
  live(u);assert(u.kind=='outfit' and name=='warlock_move_speed');return u.has_variable
 end,
 animation_find_variable=function(u,name)
  live(u);assert(u.kind=='outfit' and u.has_variable and name=='warlock_move_speed')
  events.finds=events.finds+1; return u.index
 end,
 animation_set_variable=function(u,index,value)
  live(u);assert(u.kind=='outfit' and index==u.index,'foreign animation variable index')
  assert(value==value and value>=0 and value<math.huge,'nonfinite or negative speed')
  events.writes=events.writes+1;u.speed=value
 end,
}
function advance(u,dx,dy,dz,w,dt)
 epoch=epoch+1;u.x=u.x+dx;u.y=u.y+dy;u.z=u.z+dz
 mod._update_warlock_locomotion_animation(w,dt)
end
"""


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


def states():
    """Read this controller's flat regular states and direct event transitions."""
    source = STATE_MACHINE.read_text(encoding="utf-8")
    result = {}
    for block in source.split("            {\n                animations = [")[1:]:
        name = re.search(r'^                name = "([^"]+)"', block, re.M)[1]
        clip = re.search(r'"(units/warlock_bombardier/anims/[^"]+)"', block)[1]
        speed = re.search(r'^                speed = "([^"]+)"', block, re.M)[1]
        transitions = dict(re.findall(r'event = "([^"]+)"\s+mode = "direct"\s+on_beat = ""\s+to = "([^"]+)"', block))
        result[name] = {"clip": clip, "speed": speed, "transitions": transitions}
    return result


class LocomotionAnimationRuntimeTests(unittest.TestCase):
    def test_speed_tracks_displacement_at_multiple_frame_rates(self):
        for fps in (30, 60, 120):
            for speed in (0, 0.95, 1.9, 2, 4, 6):
                with self.subTest(fps=fps, speed=speed):
                    lua = runtime()
                    lua.execute("assert(mod._start_warlock_locomotion_animation(owner,outfit))")
                    step = lua.globals().advance
                    for _ in range(fps):
                        step(lua.globals().owner, speed / fps, 0, 0, lua.globals().world, 1 / fps)
                    self.assertAlmostEqual(lua.eval("outfit.speed"), speed)

    def test_stopping_and_acceleration_follow_actual_motion(self):
        lua = runtime()
        lua.execute("""
            owner.commanded_nav_speed=4
            assert(mod._start_warlock_locomotion_animation(owner,outfit))
            advance(owner,0.02,0,0,world,0.1);assert(math.abs(outfit.speed-0.2)<1e-9)
            advance(owner,0.4,0,0,world,0.1);assert(math.abs(outfit.speed-4)<1e-9)
            advance(owner,0,0,0,world,0.1);assert(outfit.speed==0)
        """)

    def test_horizontal_diagonal_speed_excludes_vertical_motion(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_locomotion_animation(owner,outfit)
            advance(owner,0.3,0.4,20,world,0.1)
            assert(math.abs(outfit.speed-5)<1e-9)
            advance(owner,0,0,-20,world,0.1);assert(outfit.speed==0)
        """)

    def test_other_world_pass_cannot_advance_or_duplicate_the_sample(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_locomotion_animation(owner,outfit)
            local reads,writes=events.positions,events.writes
            advance(owner,0.4,0,0,other_world,0.001)
            assert(events.positions==reads and events.writes==writes)
            mod._update_warlock_locomotion_animation(world,0.1)
            assert(math.abs(outfit.speed-4)<1e-9)
        """)

    def test_host_and_husk_each_use_their_own_outfit_variable(self):
        lua = runtime()
        lua.execute("""
            client=make_owner(other_world); client_outfit=make_outfit(other_world,19)
            mod._warlock_outfits[client]=client_outfit
            mod._start_warlock_locomotion_animation(owner,outfit)
            mod._start_warlock_locomotion_animation(client,client_outfit)
            advance(owner,0.4,0,0,world,0.1)
            advance(client,0.19,0,0,other_world,0.1)
            assert(math.abs(outfit.speed-4)<1e-9)
            assert(math.abs(client_outfit.speed-1.9)<1e-9)
            assert(events.finds==2)
        """)

    def test_missing_variable_wrong_outfit_and_wrong_registry_fail_without_lookup(self):
        for mutation in (
            "outfit.has_variable=false",
            "outfit.name='unrelated'",
            "mod._warlock_outfits[owner]=nil",
            "outfit.world=other_world",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(mutation)
                lua.execute("""
                    assert(not mod._start_warlock_locomotion_animation(owner,outfit))
                    assert(events.finds==0 and events.writes==0)
                """)

    def test_death_deletion_registry_replacement_and_world_change_stop_writes(self):
        for mutation in (
            "HEALTH_ALIVE[owner]=nil",
            "owner.alive=false",
            "outfit.alive=false",
            "mod._warlock_outfits[owner]=make_outfit(world,99)",
            "owner.world=other_world",
            "outfit.world=other_world",
        ):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("mod._start_warlock_locomotion_animation(owner,outfit)")
                lua.execute(mutation)
                lua.execute("""
                    local writes=events.writes
                    mod._update_warlock_locomotion_animation(world,0.1)
                    mod._update_warlock_locomotion_animation(world,0.1)
                    assert(events.writes==writes)
                """)

    def test_teleport_is_rejected_and_next_real_step_recovers(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_locomotion_animation(owner,outfit)
            advance(owner,50,0,0,world,0.1);assert(outfit.speed==0)
            advance(owner,0.4,0,0,world,0.1)
            assert(math.abs(outfit.speed-4)<1e-9)
        """)

    def test_invalid_dt_and_pause_discard_the_unmeasured_interval(self):
        for dt in ("0", "-1", "0.5", "0/0", "math.huge"):
            with self.subTest(dt=dt):
                lua = runtime()
                lua.execute(f"""
                    mod._start_warlock_locomotion_animation(owner,outfit)
                    advance(owner,0.4,0,0,world,0.1)
                    advance(owner,100,0,0,world,{dt});assert(outfit.speed==0)
                    advance(owner,100,0,0,world,0.1);assert(outfit.speed==0)
                    advance(owner,0.4,0,0,world,0.1)
                    assert(math.abs(outfit.speed-4)<1e-8)
                """)

    def test_nonfinite_position_fails_closed_then_recovers(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_locomotion_animation(owner,outfit)
            owner.x=0/0;mod._update_warlock_locomotion_animation(world,0.1)
            assert(outfit.speed==0)
            owner.x=10;mod._update_warlock_locomotion_animation(world,0.1)
            assert(outfit.speed==0)
            advance(owner,0.4,0,0,world,0.1)
            assert(math.abs(outfit.speed-4)<1e-9)
        """)

    def test_stop_reset_and_lua_reload_drop_records_without_native_writes(self):
        for cleanup in (
            "mod._stop_warlock_locomotion_animation(owner)",
            "mod._reset_warlock_locomotion_animation()",
        ):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute("mod._start_warlock_locomotion_animation(owner,outfit)")
                lua.execute(cleanup)
                lua.execute("owner.alive=false; outfit.alive=false")
                lua.execute("""
                    mod._update_warlock_locomotion_animation(world,0.1)
                    assert(events.writes==1)
                """)
        lua = runtime()
        lua.execute("mod._start_warlock_locomotion_animation(owner,outfit)")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("""
            mod._update_warlock_locomotion_animation(world,0.1)
            assert(events.writes==1)
        """)

    def test_world_release_forgets_handles_before_even_a_lifetime_query(self):
        lua = runtime()
        lua.execute("""
            mod._start_warlock_locomotion_animation(owner,outfit)
            mod._release_warlock_locomotion_world(world)
            Unit.alive=function() error('released handle queried') end
            mod._update_warlock_locomotion_animation(other_world,0.1)
            assert(events.writes==1)
        """)


class LocomotionAnimationStateMachineTests(unittest.TestCase):
    def test_every_live_state_accepts_both_native_gait_events(self):
        graph = states()
        self.assertEqual(len(graph), 12)
        for name, state in graph.items():
            if name == "base/death":
                self.assertFalse(state["transitions"])
                continue
            with self.subTest(state=name):
                self.assertEqual(state["transitions"]["move_fwd"], "base/walk")
                self.assertEqual(state["transitions"]["move_fwd_run"], "base/run")
                self.assertEqual(state["transitions"]["idle"], "base/idle")

    def test_gaits_use_distinct_clips_and_measured_speed_only_changes_locomotion(self):
        graph = states()
        self.assertEqual(graph["base/walk"]["clip"].rsplit("/", 1)[1], "combat_walk")
        self.assertEqual(graph["base/run"]["clip"].rsplit("/", 1)[1], "combat_run")
        lua = runtime()
        lua.execute("mod._start_warlock_locomotion_animation(owner,outfit)")
        for gait, nominal in (("base/walk", 1.9), ("base/run", 4)):
            for ratio in (0, 0.5, 1, 1.5):
                lua.globals().advance(lua.globals().owner, nominal * ratio / 10, 0, 0,
                                      lua.globals().world, 0.1)
                expression = graph[gait]["speed"].replace("warlock_move_speed", "outfit.speed")
                self.assertAlmostEqual(lua.eval(expression), ratio)
        for name, state in graph.items():
            if name not in ("base/walk", "base/run"):
                self.assertEqual(state["speed"], "1", name)


def sample_linear(keys, time):
    times = [key[0] for key in keys]
    index = bisect.bisect_right(times, time)
    if index == 0:
        return keys[0][1]
    if index == len(keys):
        return keys[-1][1]
    left, right = keys[index - 1], keys[index]
    blend = (time - left[0]) / (right[0] - left[0])
    return tuple(a + (b - a) * blend for a, b in zip(left[1], right[1]))


def source_hips_keys(path):
    """Read the baked linear FBX hips position curves, without a DCC runtime."""
    from test_warlock_weapon_pipeline import BinaryFbx, model_node
    fbx = BinaryFbx(path)
    hips = model_node(fbx, "j_hips").properties[0]
    connections = [node.properties for node in fbx.descendants("C")]
    tracks = [row[1] for row in connections
              if row[0] == "OP" and row[2] == hips and row[3] == "Lcl Translation"]
    if len(tracks) != 1:
        raise AssertionError("Expected exactly one animated hips translation track")
    channels = {row[3]: row[1] for row in connections
                if row[0] == "OP" and row[2] == tracks[0]}
    curves = {node.properties[0]: node for node in fbx.object_nodes("AnimationCurve")}
    axes = []
    for axis in ("d|X", "d|Y", "d|Z"):
        curve = curves[channels[axis]]
        # The shipping exporter bakes linear keys. A different interpolation
        # requires a real evaluator instead of blessing a linear approximation.
        if any(flag & 0xF != 4 for flag in curve.child("KeyAttrFlags").properties[0]):
            raise AssertionError("Hips curve is no longer baked linear FBX data")
        times = curve.child("KeyTime").properties[0]
        values = curve.child("KeyValueFloat").properties[0]
        if len(times) != len(values) or not values:
            raise AssertionError("Incomplete hips curve")
        axes.append(tuple((time / 46186158000, (value,)) for time, value in zip(times, values)))
    times = sorted({time for axis in axes for time, _ in axis})
    return tuple((time, tuple(sample_linear(axis, time)[0] for axis in axes)) for time in times)


def hips_world_curve_error(source_keys, compiled_keys):
    # FBX centimetre import multiplies these local coordinates by .01. The
    # proven parent has uniform scale100, so the world-space error is exactly
    # the length of this difference in metres (rotation preserves its length).
    times = sorted({time for keys in (source_keys, compiled_keys) for time, _ in keys})
    return max(math.dist(sample_linear(source_keys, time),
                         tuple(100 * value for value in sample_linear(compiled_keys, time)))
               for time in times)


class AnimationCompressionSourceTests(unittest.TestCase):
    def test_all_thirteen_clips_keep_one_millimetre_position_fitting_tolerance(self):
        files = tuple((ROOT / "units/warlock_bombardier/anims").glob("*.animation"))
        self.assertEqual(len(files), 13)
        for path in files:
            with self.subTest(clip=path.stem):
                self.assertRegex(path.read_text(),
                                 r'""\s*=\s*\[\s*0\.00001\s+0\.01\s+0\s+false\s*\]')

    def test_guard_rejects_historical_sync_to_end_only_hips_curve(self):
        for clip in ("combat_idle", "combat_run"):
            with self.subTest(clip=clip):
                source = source_hips_keys(ROOT / "units/warlock_bombardier/anims" / (clip + ".fbx"))
                endpoints = tuple((time, tuple(value / 100 for value in position))
                                  for time, position in (source[0], source[-1]))
                # This is the measured failure mode of .74: all intermediate
                # hip motion was reduced to a straight line between endpoints.
                self.assertGreater(hips_world_curve_error(source, endpoints), .03)


@unittest.skipUnless(any((ROOT / "bundleV2").glob("*.mod_bundle")), "No production bundle; source-only CI")
class AnimationCompressionCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_warlock_weapon_pipeline import compiled_bundle_resources, compiled_unit_structure, resource_key
        from test_doomrocket_visible_aim import compiled_bones
        cls.resources = compiled_bundle_resources()
        unit = "units/warlock_bombardier/warlock_bombardier_3p"
        def resource(kind):
            found = cls.resources.get(resource_key(kind, unit), [])
            if len(found) != 1:
                raise AssertionError(f"Expected exactly one compiled {kind}:{unit}")
            return found[0][1]
        cls.bones = compiled_bones(resource("bones"))
        cls.unit = compiled_unit_structure(resource("unit"))

    def test_scale100_hips_parent_defines_the_world_error_conversion(self):
        from test_warlock_weapon_pipeline import compiled_node_index
        hips = self.unit.nodes[compiled_node_index(self.unit, "j_hips")]
        root = compiled_node_index(self.unit, "root_point")
        self.assertEqual((hips.parent_type, hips.parent_index), (1, root))
        matrix = self.unit.nodes[root].world_transform
        axes = [tuple(matrix[row][column] for row in range(3)) for column in range(3)]
        for axis in axes:
            self.assertAlmostEqual(math.sqrt(sum(value * value for value in axis)), 100, places=4)
        for a, b in ((0, 1), (0, 2), (1, 2)):
            self.assertAlmostEqual(sum(x * y for x, y in zip(axes[a], axes[b])), 0, places=3)

    def test_every_referenced_compiled_clip_preserves_sample_fit_and_whole_hips_curve(self):
        from test_warlock_weapon_pipeline import resource_key
        from test_doomrocket_visible_aim import compiled_reference_positions
        for clip in sorted({state["clip"] for state in states().values()}):
            with self.subTest(clip=clip):
                found = self.resources.get(resource_key("animation", clip), [])
                self.assertEqual(len(found), 1, "Missing or duplicated compiled animation")
                actual = compiled_reference_positions(found[0][1], self.bones.index("j_hips"), include_times=True)
                source = source_hips_keys(ROOT / (clip + ".fbx"))
                # The SDK evaluates the baked FBX at adaptive dyadic times.
                # Those samples must fit within the scale100-adjusted 1 mm
                # tolerance. Linear playback between them can miss FBX corners:
                # measured maxima are 7.14 mm normally and 19.04 mm in staggers.
                # Check every breakpoint of both curves as well, so reducing
                # the result to accurate endpoints cannot pass the fit check.
                sample_error = max(
                    math.dist(sample_linear(source, time), tuple(100 * value for value in position))
                    for time, position in actual
                )
                self.assertLessEqual(sample_error, .001,
                                     f"{clip}: sampled hips position error {sample_error:.6f} m")
                whole_error = hips_world_curve_error(source, actual)
                whole_budget = .020 if clip.rsplit("/", 1)[1].startswith("stagger_") else .010
                self.assertLessEqual(whole_error, whole_budget,
                                     f"{clip}: whole hips curve error {whole_error:.6f} m exceeds "
                                     f"{whole_budget:.3f} m SDK resampling budget")


if __name__ == "__main__":
    unittest.main()
