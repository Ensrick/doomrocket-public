"""Check own-skeleton aiming in Lua and in the actual compiled controller.

The binary reader uses only repository-local bundle/cursor helpers. It checks
the compiler's output rather than trusting source keys, which the SDK may
silently ignore. These checks do not establish rendered hand contact.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import json
import struct
import sys
import unittest

from lupa.lua51 import LuaRuntime

from test_warlock_weapon_pipeline import (
    PackedCursor, compiled_bundle_resources, compiled_node_index,
    compiled_unit_structure, murmur64a, resource_key,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from calibrate_warlock_aim_reference import inspect_clip

UNIT = "units/warlock_bombardier/warlock_bombardier_3p"
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_aim_template.lua"
AIM_STATES = {
    "base/idle", "base/walk", "base/run", "base/shoot_start", "base/shoot_loop",
    "base/wind_up_start", "base/wind_up_loop", "base/reload_start", "base/reload_loop",
}
NO_AIM_STATES = {"base/death", "base/stagger_fwd", "base/stagger_bwd"}
REFERENCE_POINT_METRES = (.1, 5., .6)
CALIBRATED_CLIPS = {
    "combat_idle", "combat_reload_loop", "combat_reload_start", "combat_run_start_fwd",
    "combat_run", "combat_shoot_loop", "combat_shoot_start", "combat_walk",
    "combat_wind_up_loop", "combat_wind_up_start", "death_shot", "stagger_bwd", "stagger_fwd",
}


def array(cursor, stride):
    return cursor.take(cursor.u32() * stride)


def words(cursor):
    data = array(cursor, 4)
    return tuple(value[0] for value in struct.iter_unpack("<I", data))


def count(cursor, maximum=4096):
    value = cursor.u32()
    if value > maximum:
        raise AssertionError("Unreasonable compiled animation record count")
    return value


@dataclass(frozen=True)
class CompiledController:
    states: dict[int, tuple[int, ...]]
    masks: tuple[tuple[bytes, tuple[int, ...]], ...]
    targets: tuple[int, ...]
    target_positions: tuple[tuple[float, float, float], ...]
    constraints: bytes


def compiled_controller(payload: bytes) -> CompiledController:
    """Read the packed VT2 AnimationStateMachineResource, with bounded reads.

State transitions/blends are structurally consumed; named state constraint
indices and actual expression buffers are retained. No external parser,
Blender module, guessed byte-pattern search, or donor file is required.
    """
    c = PackedCursor(payload)
    states = {}
    for _ in range(count(c, 32)):
        layer_count = count(c)
        for _ in range(layer_count):
            name = struct.unpack("<Q", c.take(8))[0]
            c.skip(16)  # other state identifiers
            if c.u32() not in range(5):
                raise AssertionError("Unknown animation state type")
            array(c, 8)  # animations
            array(c, 4)  # probabilities
            c.skip(9)  # randomization, loop bool, blend type
            array(c, 9)  # transitions: event, index, conditional bool
            array(c, 28)  # blend settings
            for _ in range(count(c)):
                c.skip(4)  # switch bytecode index
                array(c, 14)  # switch exits
            array(c, 12)  # timeline markers
            c.skip(4)
            array(c, 12)
            c.skip(8)  # exit event
            array(c, 4)  # expression bytecode, including state speed
            array(c, 4)  # weights
            c.skip(16)  # state speed/root/bone/blend fields
            indices = words(c)
            c.skip(12)  # time variable, muted layers, ragdoll
            if name in states:
                raise AssertionError("Duplicate compiled state name")
            states[name] = indices
        if c.u32() >= layer_count:
            raise AssertionError("Invalid compiled default state")
    array(c, 4)  # events
    array(c, 4)  # variable names
    array(c, 4)  # variable defaults
    array(c, 8)  # variable bounds
    masks = []
    for _ in range(count(c, 40)):
        bytecode = array(c, 4)
        indices = words(c)
        if c.u8() not in (0, 1):
            raise AssertionError("Invalid compiled mask constant flag")
        masks.append((bytecode, indices))
    targets = words(c)
    positions = tuple(struct.iter_unpack("<3f", array(c, 12)))
    constraints = c.byte_array()
    for _ in range(count(c)):
        array(c, 4)  # dynamic ragdoll actors
        array(c, 4)  # keyframed ragdoll actors
    array(c, 28)
    c.skip(4)
    if c.offset != len(payload):
        raise AssertionError("Unexpected compiled controller trailing data")
    return CompiledController(states, tuple(masks), targets, positions, constraints)


def constant_mask(mask):
    bytecode, indices = mask
    result = []
    for index in indices:
        offset = index * 4
        if offset + 8 > len(bytecode):
            raise AssertionError("Mask expression index exceeds bytecode")
        value, end = struct.unpack_from("<fI", bytecode, offset)
        if end != 0x7FA00000 or not math.isfinite(value):
            raise AssertionError("Aim mask must contain finite constant expressions")
        result.append(value)
    return tuple(result)


def compiled_bones(payload):
    c = PackedCursor(payload)
    bone_count, lod_count = count(c), count(c)
    hashes = struct.unpack(f"<{bone_count}I", c.take(bone_count * 4))
    c.take(lod_count * 4)
    names = c.take(len(payload) - c.offset).split(b"\0")
    if names[-1:] == [b""]:
        names.pop()
    decoded = tuple(name.decode("ascii") for name in names)
    if len(decoded) != bone_count or tuple(murmur64a(n.encode()) >> 32 for n in decoded) != hashes:
        raise AssertionError("Compiled bone names/order do not match their hashes")
    return decoded


def verify_aim(controller, bone_names):
    if len(controller.constraints) != 24:
        raise AssertionError("Expected exactly one native aim constraint")
    total, offset, kind, mask, target, bone = struct.unpack("<6I", controller.constraints)
    if (total, offset, kind) != (1, 8, 1):
        raise AssertionError("Compiled controller does not contain one type-1 aim constraint")
    if mask >= len(controller.masks) or target >= len(controller.targets) or bone >= len(bone_names):
        raise AssertionError("Constraint contains an out-of-range binding")
    if bone_names[bone] != "aim_target":
        raise AssertionError("Constraint reference bone was not resolved on its own skeleton")
    if controller.targets[target] != murmur64a(b"aim_target") >> 32:
        raise AssertionError("Wrong named aim constraint target")
    if len(controller.targets) != len(controller.target_positions):
        raise AssertionError("Constraint target positions/count do not match")
    if not all(math.isfinite(v) for v in controller.target_positions[target]):
        raise AssertionError("Nonfinite initial aim target")
    weights = constant_mask(controller.masks[mask])
    if len(weights) != len(bone_names):
        raise AssertionError("Aim blend mask uses a foreign skeleton bone count")
    if {name: value for name, value in zip(bone_names, weights) if value} != {"j_spine": .5, "j_spine1": 1.}:
        raise AssertionError("Aim blend mask does not match the native spine weights")
    return mask, target, bone


def compiled_reference_positions(payload, reference_index, include_times=False):
    """Read the reference's initial position and every position key.

VT2 interleaved animations use an explicit initial pose and tagged packed or
unpacked keys. Other channels are consumed without decoding rotations. Reject
unknown/truncated streams rather than skipping bytes until a guessed marker.
    """
    c = PackedCursor(payload)
    if c.u32() != 0:
        raise AssertionError("Expected VT2 interleaved animation header")
    bones = count(c, 1024)
    duration, size = struct.unpack("<fI", c.take(8))
    if not 0 <= reference_index < bones or not math.isfinite(duration) or duration <= 0:
        raise AssertionError("Invalid animation reference or duration")
    if size != len(payload):
        raise AssertionError("Animation header size does not match payload")
    array(c, 8)  # beat times

    def packed_vector():
        return tuple(v * (20 / 65536) - 10 for v in struct.unpack("<3H", c.take(6)))

    def vector():
        return struct.unpack("<3f", c.take(12))

    sync_type = c.u16()
    if sync_type not in (1, 7):
        raise AssertionError("Unknown animation initial pose encoding")
    positions = []
    times = []
    for bone in range(bones):
        if sync_type == 1:
            position = packed_vector()
            c.skip(10)  # packed rotation + scale
        else:
            position = vector()
            c.skip(28)  # quaternion + scale
        if bone == reference_index:
            positions.append(position)
            times.append(0.)
    ended = False
    while c.offset < len(payload):
        tag = c.u16()
        kind = tag & 0xC000
        if kind:
            combined = tag << 16 | c.u16()
            bone = combined >> 20 & 0x3FF
            time = (combined & 0xFFFFF) * .001
            if bone >= bones:
                raise AssertionError("Packed key references a foreign bone")
            if kind == 0x8000:
                position = packed_vector()
                if bone == reference_index:
                    positions.append(position)
                    times.append(time)
            else:
                c.skip(4 if kind == 0xC000 else 6)
        elif tag in (4, 5, 6):
            bone = c.u16()
            time = struct.unpack("<f", c.take(4))[0]
            if bone >= bones:
                raise AssertionError("Unpacked key references a foreign bone")
            if tag == 4:
                position = vector()
                if bone == reference_index:
                    positions.append(position)
                    times.append(time)
            else:
                c.skip(16 if tag == 5 else 12)
        elif tag == 2:
            c.skip(8)  # trigger
        elif tag == 3:
            ended = True
            break
        else:
            raise AssertionError(f"Unknown interleaved animation item {tag}")
    if not ended or c.offset != len(payload) or not positions:
        raise AssertionError("Animation is incomplete or contains trailing bytes")
    if not all(math.isfinite(value) for position in positions for value in position):
        raise AssertionError("Animation contains nonfinite reference positions")
    if not all(math.isfinite(t) and t >= 0 for t in times) or times != sorted(times):
        raise AssertionError("Animation contains invalid position key times")
    return tuple(zip(times, positions)) if include_times else tuple(positions)


HARNESS = r"""
local mt={}
function vec(x,y,z) return setmetatable({x=x,y=y,z=z},mt) end
mt.__add=function(a,b) return vec(a.x+b.x,a.y+b.y,a.z+b.z) end
mt.__mul=function(a,b) return vec(a.x*b,a.y*b,a.z*b) end
Vector3={
 is_valid=function(v) return v and v.x==v.x and v.y==v.y and v.z==v.z
  and math.abs(v.x)<math.huge and math.abs(v.y)<math.huge and math.abs(v.z)<math.huge end,
 length_squared=function(v) return v.x*v.x+v.y*v.y+v.z*v.z end,
 normalize=function(v) local n=math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z);return vec(v.x/n,v.y/n,v.z/n) end,
}
Quaternion={forward=function(rotation) return type(rotation)=='table' and rotation or vec(0,1,0) end}
owner={alive=true,index=7,kind='owner',has_target=true,writes=0,finds=0}
function make_outfit(index) return {alive=true,index=index,kind='outfit',has_target=true,writes=0,finds=0} end
outfit=make_outfit(0)
mod={_warlock_outfits={[owner]=outfit},_doomrocket_version='test-version'}
logs={}
function printf(format,...) logs[#logs+1]=string.format(format,...) end
function get_mod(name) assert(name=='doomrocket');return mod end
HEALTH_ALIVE={[owner]=true}; POSITION_LOOKUP={[owner]=vec(10,20,30)}
BLACKBOARDS={[owner]={}}
AimTemplates={}
Unit={
 alive=function(u) return u.alive end,
 local_rotation=function(u,i) assert(u.alive and i==0);return u.forward or true end,
 world_rotation=function(u,i) assert(u.alive and i==0);return u.forward or true end,
 world_position=function(u,i) assert(u.alive and i==0);return POSITION_LOOKUP[u] or vec(10,20,30) end,
 animation_layer_info=function(u,i) layer_reads=(layer_reads or 0)+1;error('native layer assertion cannot be contained') end,
 has_animation_event=function(u,n) assert(n=='doomrocket_reload_start');return u.reload or false end,
 animation_has_constraint_target=function(u,n) assert(u.alive and n=='aim_target');return u.has_target end,
 animation_find_constraint_target=function(u,n)
  assert(u.alive and u.has_target and n=='aim_target','find called without named constraint')
  u.finds=u.finds+1;return u.index
 end,
 animation_set_constraint_target=function(u,index,target)
  assert(u.alive and index==u.index,'foreign constraint index or dead native unit')
  assert(Vector3.is_valid(target),'invalid native or visual target')
  u.writes=u.writes+1;u.target=target
 end,
}
net_game={}; net_id=5; replicated=vec(1,4,2)
Managers={state={network={game=function() return net_game end},unit_storage={go_id=function() return net_id end}}}
GameSession={
 set_game_object_field=function(g,id,name,v) assert(g==net_game and id==5 and name=='aim_target');published=v end,
 game_object_field=function(g,id,name) assert(g==net_game and id==5 and name=='aim_target');return replicated end,
}
function begin(lane) data={};template=AimTemplates.doomrocket[lane];template.init(owner,data) end
function tick(t) template.update(owner,t or 1,1/60,data) end
"""


def runtime(lane="owner"):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    lua.globals().begin(lane)
    return lua


class VisibleAimRuntimeTests(unittest.TestCase):
    def test_owner_uses_own_zero_index_and_same_ballistic_target(self):
        lua = runtime()
        lua.execute("""
         BLACKBOARDS[owner].attack_pattern_data={ballistic_aim_direction_box={unbox=function() return vec(0,4,3) end}}
         tick();tick()
         assert(owner.finds==1 and outfit.finds==1 and outfit.writes==2)
         assert(owner.target==outfit.target and outfit.target==published)
         assert(outfit.target.x==10 and outfit.target.y==24 and outfit.target.z==33)
        """)

    def test_husk_uses_replicated_target_and_its_own_index(self):
        lua = runtime("husk")
        lua.execute("outfit.index=41;tick();assert(outfit.target==replicated and owner.target==replicated)")

    def test_husk_without_game_uses_same_forward_target(self):
        lua = runtime("husk")
        lua.execute("net_game=nil;tick();assert(outfit.target==owner.target and outfit.target.y==25)")

    def test_absent_constraint_is_never_looked_up_or_written(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = runtime(lane)
                lua.execute("outfit.has_target=false;tick();tick();assert(outfit.finds==0 and outfit.writes==0)")

    def test_death_registry_removal_and_deletion_clear_cached_outfit(self):
        for change in ("HEALTH_ALIVE[owner]=nil", "mod._warlock_outfits[owner]=nil", "outfit.alive=false", "mod._warlock_outfits=nil"):
            for lane in ("owner", "husk"):
                with self.subTest(change=change, lane=lane):
                    lua = runtime(lane)
                    lua.execute("tick();assert(outfit.writes==1)")
                    lua.execute(change)
                    lua.execute("tick();assert(outfit.writes==1 and data.visible_aim_outfit==nil and data.visible_aim_constraint==nil)")

    def test_replacement_outfit_resolves_its_own_new_index(self):
        lua = runtime()
        lua.execute("""
         tick();replacement=make_outfit(93);mod._warlock_outfits[owner]=replacement;tick()
         assert(outfit.writes==1 and replacement.writes==1 and replacement.finds==1)
         assert(data.visible_aim_constraint==93)
        """)

    def test_nonfinite_replicated_target_never_reaches_visual_controller(self):
        lua = runtime("husk")
        lua.execute("tick();replicated=vec(0/0,0,0);tick();assert(outfit.writes==1 and data.visible_aim_outfit==nil)")

    def test_reload_suppression_is_shared_with_native_controller(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = runtime(lane)
                lua.execute("owner.reload=true;tick();assert(owner.writes==0 and outfit.writes==0 and outfit.finds==0)")

    def test_owner_and_husk_apply_identical_published_target_despite_different_local_facing(self):
        lua = runtime()
        lua.execute("""
         BLACKBOARDS[owner].attack_pattern_data={ballistic_aim_direction_box={unbox=function() return vec(0,4,3) end}}
         tick();local host_owner,host_outfit=owner,outfit
         replicated=published
         owner={alive=true,index=9,kind='owner',has_target=true,writes=0,finds=0,forward=vec(-1,0,0)}
         outfit=make_outfit(31);mod._warlock_outfits[owner]=outfit
         HEALTH_ALIVE[owner]=true;POSITION_LOOKUP[owner]=vec(10.1,20,30)
         begin('husk');tick()
         assert(owner.target==host_owner.target and outfit.target==host_outfit.target)
         assert(outfit.target==replicated and outfit.target.x==10 and outfit.target.y==24 and outfit.target.z==33)
         assert(host_owner.forward==nil and owner.forward.x==-1)
        """)

    def test_held_ballistic_target_survives_missing_attack_pattern_until_exact_expiry(self):
        lua = runtime()
        lua.execute("""
         local bb=BLACKBOARDS[owner]
         bb.doomrocket_ballistic_aim_hold_direction_box={unbox=function() return vec(0,4,3) end}
         bb.doomrocket_ballistic_aim_hold_until=2
         assert(bb.attack_pattern_data==nil)
         tick(1);assert(published.y==24 and published.z==33)
         tick(2);assert(published.y==24 and published.z==33)
         tick(2.001);assert(published.y==25 and published.z==30)
         assert(bb.doomrocket_ballistic_aim_hold_direction_box==nil and bb.doomrocket_ballistic_aim_hold_until==nil)
        """)

    def test_active_ballistic_target_takes_priority_over_hold_and_direct_aim(self):
        lua = runtime()
        lua.execute("""
         local bb=BLACKBOARDS[owner]
         bb.doomrocket_ballistic_aim_hold_direction_box={unbox=function() return vec(-1,0,0) end}
         bb.doomrocket_ballistic_aim_hold_until=10
         bb.attack_pattern_data={ballistic_aim_direction_box={unbox=function() return vec(1,0,0) end},
          shoot_direction_box={unbox=function() return vec(0,-1,0) end}}
         tick();assert(published.x==15 and published.y==20 and published.z==30)
        """)

    def test_invalid_replicated_target_never_reaches_either_native_constraint(self):
        for target in ("nil", "vec(0/0,0,0)", "vec(math.huge,0,0)", "vec(0,-math.huge,0)"):
            with self.subTest(target=target):
                lua = runtime("husk")
                lua.execute(f"""
                 tick();replicated={target};tick(3)
                 assert(owner.writes==1 and outfit.writes==1)
                 assert(data.visible_aim_outfit==nil and data.visible_aim_constraint==nil)
                """)

    def test_invalid_owner_direction_falls_back_before_normalizing(self):
        for direction in ("vec(0,0,0)", "vec(0/0,0,0)", "vec(math.huge,0,0)", "vec(1e308,1e308,1e308)"):
            with self.subTest(direction=direction):
                lua = runtime()
                lua.execute(f"""
                 BLACKBOARDS[owner].attack_pattern_data={{ballistic_aim_direction_box={{unbox=function() return {direction} end}}}}
                 tick();assert(owner.target==outfit.target and owner.target==published)
                 assert(published.x==10 and published.y==25 and published.z==30)
                """)

    def test_invalid_owner_position_is_neither_written_nor_published(self):
        lua = runtime()
        lua.execute("POSITION_LOOKUP[owner]=vec(math.huge,0,0);tick();assert(owner.writes==0 and outfit.writes==0 and published==nil)")

    def test_absent_carrier_constraint_never_uses_unsafe_native_lookup(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = runtime(lane)
                lua.execute(f"""
                 owner.has_target=false;owner.finds=0;begin('{lane}');tick()
                 assert(owner.finds==0 and owner.writes==0 and outfit.writes==0)
                """)

    def test_facing_evidence_identifies_roles_world_target_roots_and_animation_phase(self):
        for lane, source in (("owner", "forward"), ("husk", "replicated")):
            with self.subTest(lane=lane):
                lua = runtime(lane)
                lua.execute("""
                 BLACKBOARDS[owner].action={name='fire_rocket'}
                 BLACKBOARDS[owner].attack_pattern_data={state='align'}
                 tick()
                """)
                message = lua.globals().logs[1]
                for field in ("v=test-version", f"role={lane}", "go_id=5", "stage=aim_update",
                              f"source={source}", "result=applied", "root_pos=10.000,20.000,30.000",
                              "root_forward=0.000,1.000,0.000", "outfit_forward=0.000,1.000,0.000",
                              "owner_clock=not_sampled/not_sampled", "outfit_clock=not_sampled/not_sampled"):
                    self.assertIn(field, message)
                if lane == "owner":
                    self.assertIn("action=fire_rocket pattern=align", message)

    def test_facing_never_attempts_native_layer_read_on_owner_or_outfit(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = runtime(lane)
                lua.execute("""
                 -- Count the attempt before raising: pcall hiding a Lua mock's
                 -- error cannot disguise the native-assert regression in #65.
                 for i=1,3 do tick(i*2) end
                 assert((layer_reads or 0)==0)
                 assert(owner.writes==3 and outfit.writes==3 and #logs==3)
                 outfit.alive=false;tick(8)
                 assert((layer_reads or 0)==0 and owner.writes==4 and #logs==4)
                """)

    def test_facing_evidence_is_rate_limited_and_per_unit_bounded(self):
        lua = runtime()
        lua.execute("""
         for i=1,600 do tick(i/60) end
         assert(#logs>=4 and #logs<=6 and owner.writes==600 and outfit.writes==600)
         for i=1,500 do tick(10+i*2) end
         assert(#logs==30 and owner.writes==1100 and outfit.writes==1100)
        """)

    def test_facing_evidence_session_cap_survives_many_unit_initializations(self):
        lua = runtime()
        lua.execute("""
         for spawn=1,20 do
          begin('owner');for i=1,50 do tick(i*2) end
         end
         assert(#logs==240 and owner.writes==1000 and outfit.writes==1000)
        """)

    def test_diagnostic_api_errors_never_interrupt_aiming_and_are_bounded(self):
        lua = runtime()
        lua.execute("""
         Unit.world_rotation=function() error('diagnostic unavailable') end
         for i=1,35 do tick(i*2) end
         assert(owner.writes==35 and outfit.writes==35 and #logs==0 and data.facing_samples==30)
         Unit.world_rotation=function() return true end
         tick(100);assert(owner.writes==36 and #logs==0)
        """)


class VisibleAimSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "tools/fixtures/warlock_aim_reference.json").read_text(encoding="utf-8"))

    def test_reference_matches_native_authored_metres_and_custom_local_scale(self):
        self.assertEqual(tuple(self.manifest["expected_helper_translation"]), REFERENCE_POINT_METRES)
        self.assertEqual(tuple(self.manifest["reference_world_metres"]), REFERENCE_POINT_METRES)
        self.assertEqual(tuple(self.manifest["expected_compiled_local"]), (.001, .05, .006))
        self.assertEqual(self.manifest["compiled_parent"], "root_point")
        self.assertEqual(self.manifest["compiled_ancestor_scale"], 100)

    def test_only_constant_helper_translation_changed_in_every_clip(self):
        self.assertEqual(set(self.manifest["files"]), {name + ".fbx" for name in CALIBRATED_CLIPS})
        for name, expected in self.manifest["files"].items():
            with self.subTest(clip=name):
                actual = inspect_clip(ROOT / "units/warlock_bombardier/anims" / name)
                self.assertEqual(actual["sha256"], expected["after_sha256"])
                self.assertEqual(actual["file_size"], expected["file_size"])
                self.assertEqual(actual["nonhelper_sha256"], expected["nonhelper_sha256"])
                self.assertEqual(actual["helper_rotation_sha256"], expected["helper_rotation_sha256"])
                self.assertEqual(actual["parent"], "root_point")
                self.assertTrue(actual["translation_channels_constant"])
                for key in ("translation", "model_translation"):
                    self.assertLess(math.dist(actual[key], REFERENCE_POINT_METRES), 1e-6)


@unittest.skipUnless((ROOT / "bundleV2").is_dir(), "No production bundle; source-only CI")
class VisibleAimCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = compiled_bundle_resources()
        cls.resources = resources
        def resource(kind):
            found = resources.get(resource_key(kind, UNIT), [])
            if len(found) != 1:
                raise AssertionError(f"Expected exactly one compiled {kind}:{UNIT}")
            return found[0][1]
        cls.controller = compiled_controller(resource("state_machine"))
        cls.bones = compiled_bones(resource("bones"))
        cls.unit = compiled_unit_structure(resource("unit"))

    def test_compiled_aim_uses_own_named_bone_and_native_spine_mask(self):
        self.assertEqual(len(self.bones), 138)
        self.assertEqual(verify_aim(self.controller, self.bones), (0, 0, self.bones.index("aim_target")))

    def test_living_states_activate_aim_and_death_stagger_states_do_not(self):
        for name in AIM_STATES | NO_AIM_STATES:
            with self.subTest(state=name):
                actual = self.controller.states[murmur64a(name.encode())]
                self.assertEqual(actual, (0,) if name in AIM_STATES else ())

    def test_every_referenced_compiled_clip_uses_calibrated_constant_reference_point(self):
        root_index = compiled_node_index(self.unit, "root_point")
        reference_index = compiled_node_index(self.unit, "aim_target")
        reference = self.unit.nodes[reference_index]
        self.assertEqual((reference.parent_type, reference.parent_index), (1, root_index))
        root = self.unit.nodes[root_index].world_transform
        # The root basis is the established centimetre-to-metre wrapper. Use
        # the actual compiled basis; raw donor local coordinates are unsafe.
        for row in range(3):
            for col in range(3):
                self.assertAlmostEqual(root[row][col], 100. if row == col else 0., delta=.001)
        helper_bone = self.bones.index("aim_target")
        controller_source = (ROOT / (UNIT + ".state_machine")).read_text(encoding="utf-8")
        for clip in sorted(CALIBRATED_CLIPS):
            with self.subTest(clip=clip):
                clip_resource = f"units/warlock_bombardier/anims/{clip}"
                found = self.resources.get(resource_key("animation", clip_resource), [])
                if clip == "combat_run_start_fwd" and not found:
                    # This retained source clip is not used by the controller;
                    # the SDK correctly excludes unreferenced animations.
                    self.assertNotIn(f'"{clip_resource}"', controller_source,
                                     "A referenced run-start clip must be packaged")
                    continue
                self.assertEqual(len(found), 1, f"Missing or duplicate compiled clip {clip}")
                positions = compiled_reference_positions(found[0][1], helper_bone)
                for position in positions:
                    point = tuple(sum(root[row][col] * position[col] for col in range(3)) for row in range(3))
                    self.assertLess(math.dist(point, REFERENCE_POINT_METRES), .0001,
                                    f"{clip}: aim reference still differs from native authored frame: {point}")
                self.assertLess(max(math.dist(position, positions[0]) for position in positions), 1e-7,
                                f"{clip}: aim reference unexpectedly animates")


if __name__ == "__main__":
    unittest.main(verbosity=2)
