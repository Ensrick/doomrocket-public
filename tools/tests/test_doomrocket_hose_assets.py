"""Production hose source, skin, packed-material and compiled-profile gates.

Run the source class alone before a new bundle exists:
  py -3 tools/tests/test_doomrocket_hose_assets.py HoseSourceTests
The default run rejects stale or incompletely spliced local bundles; CI without
bundleV2 checks source only. None of these tests substitutes for a game session.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/hose_lab/compiled"))
from build_hose_profile import generate
from make_spliced_child import read_parent_binding, read_texture_bindings, read_variable_bindings
from test_warlock_weapon_pipeline import (
    BinaryFbx, compiled_bundle_resources, compiled_material_pairs, geometry_by_vertex_count,
    material_names, named_array, resource_key, murmur64a,
)
from test_doomrocket_chimney_anchor import fbx_positive_weights
from verify_asset import audit

CONTRACT_PATH = ROOT / "tools/hose_lab/rig/runtime_contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
PROFILE_PATH = ROOT / "scripts/mods/doomrocket/utils/doomrocket_hose_profile.lua"
UNIT = "units/warlock_hose/warlock_hose"
CHILD = "child_materials/warlock_bombardier/wb_hose_child"
CHILD_PACKAGE = "resource_packages/doomrocket/warlock_child"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frame(value):
    columns = [value[key] for key in ("x_axis", "y_axis", "z_axis", "position")]
    return [[columns[column][row] for column in range(4)] for row in range(1, 4)] + [[0, 0, 0, 1]]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class HoseSourceTests(unittest.TestCase):
    def test_reviewed_hose_fbx_and_existing_body_weapon_hashes_are_unchanged(self):
        expected = {
            UNIT + ".fbx": CONTRACT["outputs"]["fbx_sha256"],
            "units/warlock_bombardier/warlock_bombardier_3p.fbx": CONTRACT["endpoints"]["pack"]["body_fbx_sha256"],
            "units/rocket/pRocketLauncher.fbx": CONTRACT["endpoints"]["weapon"]["weapon_fbx_sha256"],
        }
        for path, wanted in expected.items():
            with self.subTest(path=path):
                self.assertEqual(digest((ROOT / path).read_bytes()), wanted)

    def test_actual_skin_contains_all_controls_and_normalized_max_two_weights(self):
        fbx = BinaryFbx(ROOT / (UNIT + ".fbx"))
        geometry = geometry_by_vertex_count(fbx, 1608)
        self.assertEqual(material_names(fbx), {"DoomRocket_Weapon"})
        weights = fbx_positive_weights(fbx, geometry, range(1608))
        self.assertEqual({name for values in weights.values() for name, weight in values},
                         {f"j_hose_{i:02d}" for i in range(29)})
        for values in weights.values():
            self.assertIn(len(values), (1, 2))
            self.assertAlmostEqual(sum(weight for name, weight in values), 1, places=7)

    def test_source_unit_is_actor_free_no_controller_and_has_safe_material_fallback(self):
        unit = re.sub(r"//[^\r\n]*", "", source(UNIT + ".unit"))
        self.assertIn('DoomRocket_Weapon = "materials/rocket/rocket_neutral"', unit)
        self.assertNotIn("child_materials", unit)
        self.assertNotRegex(unit, r"\b(?:physics|actors|animation_state_machine|constraints)\s*=")
        self.assertIn("surface_queries = false", unit)
        self.assertIn('culling = "disabled"', unit)
        for extension in (".physics", ".physx", ".state_machine", ".animation", ".bones"):
            self.assertFalse((ROOT / (UNIT + extension)).exists(), extension)

    def test_profile_rest_shape_and_lengths_exactly_preserve_authored_geometry(self):
        profile = LuaRuntime().execute(PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(profile["unit"], UNIT)
        self.assertEqual(profile["parent_node"], "hose_root")
        self.assertEqual(len(profile["controls"]), 29)
        self.assertEqual(len(profile["lengths"]), 28)
        for index, authored in enumerate(CONTRACT["controls"], 1):
            control = profile["controls"][index]
            self.assertEqual(control["name"], authored["name"])
            self.assertEqual(frame(control["rest"]), authored["frame"])
            bind = frame(control["bind"])
            self.assertTrue(all(math.isfinite(value) for row in bind for value in row))
            for axis in range(3):
                self.assertAlmostEqual(sum(bind[r][axis] ** 2 for r in range(3)) ** .5, 100, delta=.001)
        for index, length in enumerate(CONTRACT["control_rest_lengths_m"], 1):
            self.assertEqual(profile["lengths"][index], length)

    def test_profile_endpoint_frames_use_measured_live_backpack_and_launcher_nodes(self):
        profile = LuaRuntime().execute(PROFILE_PATH.read_text(encoding="utf-8"))
        for name in ("pack", "weapon"):
            endpoint = profile["endpoints"][name]
            expected = CONTRACT["endpoints"][name]
            self.assertEqual(endpoint["node"], expected["target_node"])
            self.assertEqual(frame(endpoint), expected["target_local_frame"])

    def test_profile_reviewed_bind_baseline_is_not_silently_edited(self):
        # Independent production-bundle tests below regenerate this from actual
        # decoded skin binds. This digest protects source-only CI in between.
        self.assertEqual(digest(PROFILE_PATH.read_text(encoding="utf-8").encode()),
                         "5c2240cec16284a08f00c1ae16c10e2b0a6cf42ad3451a278dfc97ba93c593fd")
        self.assertNotIn(".build", PROFILE_PATH.read_text(encoding="utf-8"))

    def test_hose_child_remains_in_delayed_package_not_boot_package(self):
        child = source(CHILD_PACKAGE + ".package")
        self.assertEqual(child.count('"' + CHILD + '"'), 1)
        self.assertNotIn("child_materials", source("resource_packages/doomrocket/doomrocket.package"))
        self.assertNotIn("warlock_child", source("doomrocket.mod"))
        self.assertIn('"units/*"', named_array(source("resource_packages/doomrocket/doomrocket.package"), "unit"))
        self.assertTrue((ROOT / (CHILD + ".material")).is_file())

    def test_hose_material_profile_requires_weapon_not_backpack_texture_set(self):
        profile = LuaRuntime().execute(PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(profile["material_slot"], "DoomRocket_Weapon")
        self.assertEqual(profile["material_child"], CHILD)
        self.assertEqual([profile["textures"][i] for i in range(1, 4)],
                         [f"textures/rocket/wb_weapon_{name}" for name in ("df", "nm", "ma")])

    def test_delayed_sdk_placeholder_does_not_duplicate_weapon_texture_dependencies(self):
        placeholder = re.sub(r"//[^\r\n]*", "", source(CHILD + ".material"))
        self.assertNotIn("textures/", placeholder)
        self.assertNotRegex(placeholder, r"\btextures\s*=")
        # Native bindings are added by the guarded splice, after compilation.
        # The main package owns these textures; retain the existing exact-once
        # compiled weapon checks rather than accepting duplicate resources.
        self.assertIn('"textures/*"', named_array(source("resource_packages/doomrocket/doomrocket.package"), "texture"))

    def test_packed_weapon_map_preserves_source_rgb_and_alpha_not_emissive_rgb(self):
        with Image.open(ROOT / "textures/rocket/wb_weapon_ma.png") as packed:
            self.assertEqual(packed.mode, "RGBA")
            self.assertEqual(packed.size, (1024, 1024))
            self.assertEqual(digest(packed.tobytes()), "e60cdd0f3b48da93388b8a6dd68f09c071124f707082e6fc660072f21d809612")
            self.assertEqual(digest(packed.getchannel("A").tobytes()), "378e2e03863b35e810a117e7ef9a50bcba2c84bf373541b5190f5cf5d6d15640")
            for channel, suffix in (("R", "m"), ("G", "ao")):
                with Image.open(ROOT / f"textures/rocket/wb_weapon_{suffix}.png") as scalar:
                    self.assertEqual(packed.getchannel(channel).tobytes(), scalar.getchannel("R").tobytes())
        descriptor = source("textures/rocket/wb_weapon_ma.texture")
        self.assertIn('format = "BC7"', descriptor)
        self.assertIn("srgb = false", descriptor)
        self.assertIn("enable_cut_alpha_threshold = false", descriptor)


@unittest.skipUnless((ROOT / "bundleV2").is_dir(), "No production bundle; source-only CI")
class HoseCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = compiled_bundle_resources()

    def resource(self, kind, name):
        found = self.resources.get(resource_key(kind, name), [])
        self.assertEqual(len(found), 1, f"Expected exactly one {kind}:{name}; stale build or incomplete splice")
        return found[0]

    def test_all_hose_resources_are_present_exactly_once(self):
        for kind, name in (("unit", UNIT), ("material", CHILD), ("texture", "textures/rocket/wb_weapon_ma"),
                           ("lua", "scripts/mods/doomrocket/utils/doomrocket_hose_profile")):
            with self.subTest(kind=kind, name=name):
                self.resource(kind, name)

    def test_shipping_lua_packages_do_not_predate_any_changed_source(self):
        # The SDK stores LuaJIT bytecode, not source bytes. No raw source snapshot
        # is retained in the VMB staging tree. As in the ballistic suite, this is
        # an mtime gate, NOT a claimed source/bytecode equivalence proof. The
        # release wrapper additionally requires committed, clean source and a
        # clean rebuild; do not edit source while that build is running.
        resources = (
            "utils/doomrocket_hose_profile", "utils/doomrocket_hose_solver",
            "utils/doomrocket_hose_frames", "extensions/doomrocket_hose",
            "doomrocket", "utils/hooks", "utils/doomrocket_action_lookup",
            "breeds/skaven_doomrocket",
            "behavior/nodes/skaven_doomrocket/bt_doomrocket_launch_action",
        )
        for relative in resources:
            name = "scripts/mods/doomrocket/" + relative
            with self.subTest(resource=name):
                bundle, _payload = self.resource("lua", name)
                current = ROOT / (name + ".lua")
                self.assertGreaterEqual(bundle.stat().st_mtime_ns, current.stat().st_mtime_ns,
                                        f"{bundle.name} predates {current.name}; clean rebuild required")

    def test_production_skin_profile_topology_and_poses_are_independently_verified(self):
        _bundle, payload = self.resource("unit", UNIT)
        with tempfile.TemporaryDirectory(prefix="doomrocket-hose-audit-") as temporary:
            unit_path = Path(temporary) / "hose.unit"
            unit_path.write_bytes(payload)
            report = audit(unit_path, ROOT / (UNIT + ".fbx"), CONTRACT_PATH)
        self.assertEqual(PROFILE_PATH.read_text(encoding="utf-8"), generate(CONTRACT, report))
        self.assertEqual(report["actors"], 0)
        self.assertEqual(report["topology"]["triangles"], 3024)

    def test_compiled_boot_slot_uses_safe_material_not_spliced_child(self):
        _bundle, payload = self.resource("unit", UNIT)
        self.assertEqual(compiled_material_pairs(payload),
                         {(murmur64a(b"DoomRocket_Weapon") >> 32, murmur64a(b"materials/rocket/rocket_neutral"))})

    def test_compiled_child_has_exact_native_parent_weapon_channels_and_no_emission(self):
        bundle, payload = self.resource("material", CHILD)
        self.assertEqual(Path(bundle).stem.lower(), f"{murmur64a(CHILD_PACKAGE.encode()):016x}")
        self.assertEqual(len(payload), 768, "SDK placeholder was not spliced")
        self.assertEqual(read_parent_binding(payload), 0x3D25339231384C80)
        channels = read_texture_bindings(payload)
        self.assertEqual(len(channels), 7)
        for channel, suffix in (("texture_map_02af90f8", "df"), ("texture_map_8bf37d8e", "nm"), ("texture_map_27b67fd2", "ma")):
            self.assertEqual(channels[murmur64a(channel.encode()) >> 32], murmur64a(f"textures/rocket/wb_weapon_{suffix}".encode()))
        components, offset = read_variable_bindings(payload)[0xC985395A]
        self.assertEqual(components, 3)
        self.assertEqual(struct.unpack_from("<3f", payload, offset), (0, 0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
