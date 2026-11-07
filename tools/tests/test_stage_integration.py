#!/usr/bin/env python3
"""Exercise opt-in staging with byte-pinned temporary assets, without Blender/SDK.

Small placeholder FBXs stand in for exporter payloads. Approved source constants
are patched only inside each test, so these checks verify staging and receipt
gates rather than claiming that synthetic bytes are valid animation resources.
The state machine, unit description, and bone inventory use the actual repository
fixtures; no production asset, frozen artist package, or external folder is edited.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools/animation_rig/stage_integration.py"
spec = importlib.util.spec_from_file_location("doomrocket_stage_integration", MODULE)
stage = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stage
spec.loader.exec_module(stage)
UNIT = "units/warlock_bombardier/warlock_bombardier_3p"
SAMPLER = UNIT + "/presentation_sampler"
RESOURCE_PACKAGE = "resource_packages/doomrocket/doomrocket.package"
RESOURCE_PREFIX = "units/warlock_bombardier/anims/authored/"
MANIFEST_PATH = "scripts/mods/doomrocket/utils/doomrocket_animation_manifest.lua"
CLIPS = ("combat_idle", "combat_reload_loop", "combat_reload_start", "combat_run",
         "combat_run_start_fwd", "combat_shoot_loop", "combat_shoot_start", "combat_walk",
         "combat_wind_up_loop", "combat_wind_up_start", "death_shot", "stagger_bwd", "stagger_fwd")
SOURCE_FILES = tuple(UNIT + extension for extension in (".fbx", ".bones", ".unit", ".dcc_asset", ".state_machine")) + tuple(
    f"units/warlock_bombardier/anims/{clip}.{extension}" for clip in CLIPS for extension in ("fbx", "animation"))
RESERVED = ("j_whip_parent", "j_whip_dynamic", *(f"j_loot_sack_component{index}" for index in range(1, 6)))
BONE_BYTES = (ROOT / (UNIT + ".bones")).read_bytes()
ASM_BYTES = (ROOT / (UNIT + ".state_machine")).read_bytes()
UNIT_BYTES = (ROOT / (UNIT + ".unit")).read_bytes()
PACKAGE_BYTES = (ROOT / RESOURCE_PACKAGE).read_bytes()
BONES = re.findall(r'"([^"\r\n]+)"', BONE_BYTES.decode("utf-8"))


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def root_sjson(value):
    return ("\n".join(key + " = " + json.dumps(item) for key, item in value.items()) + "\n").encode("utf-8")


def parsed_states(text):
    """Independently index regular state records in the real ASM fixture."""
    chunks = text.split("            {\n                animations = [")[1:]
    states = {}
    for chunk in chunks:
        state = re.search(r'\bname\s*=\s*"(base/[^"\r\n]+)"', chunk)
        if state:
            states[state.group(1)] = {
                "resource": re.search(r'\s*"([^"]+)"', chunk).group(1),
                "speed": re.search(r'\bspeed\s*=\s*"([^"]+)"', chunk).group(1),
                "aim": '"warlock_aim"' in chunk.split("\n            },", 1)[0],
            }
    return states


def expected_staged_asm(plan):
    """Compute the allowed semantic edits from the source graph and selections."""
    expected = copy.deepcopy(stage.Sjson(ASM_BYTES.decode()).parse().value)
    authored = set(plan["states"])
    for state in expected["layers"][0]["states"]:
        name = state["name"]
        if name in authored:
            declaration = plan["states"][name]
            clip_id = declaration if isinstance(declaration, str) else declaration["clip"]
            aim = "authored" if isinstance(declaration, str) else declaration.get("aim_policy", "authored")
            state["animations"] = [plan["authored_clips"][clip_id]["resource"]]
            state["speed"] = "1"
            if aim == "authored" and "warlock_aim" in state.get("constraints", []):
                state["constraints"] = [value for value in state["constraints"] if value != "warlock_aim"]
    return expected


def edge_inventory(asm):
    return {(state["name"], transition["event"]): transition
            for state in asm["layers"][0]["states"] for transition in state.get("transitions", [])}


class Fixture:
    def __init__(self, root):
        # Match stager canonicalization when Windows temp roots use 8.3 aliases.
        root = Path(root).resolve()
        self.root = root
        self.output = root / ".build/animation_integration_test"
        self.plan_path = root / "authoring/plan.json"
        self.plan = {"schema": 1, "source_files": {}, "authored_clips": {}, "states": {}}
        self.tracked = set()
        for relative in SOURCE_FILES:
            contents = {UNIT + ".bones": BONE_BYTES, UNIT + ".unit": UNIT_BYTES,
                        UNIT + ".state_machine": ASM_BYTES}.get(relative, ("shipping " + relative).encode())
            path = self.write(relative, contents)
            self.plan["source_files"][relative] = digest(path.read_bytes())
        self.write(RESOURCE_PACKAGE, PACKAGE_BYTES)
        self.body_hash = self.plan["source_files"][UNIT + ".fbx"]
        self.bones_hash = self.plan["source_files"][UNIT + ".bones"]
        parents = {name: "root_point" for name in BONES}
        parents.update(root_point=None, j_hips="root_point", j_whip_parent="j_hips",
                       j_whip_dynamic="j_whip_parent")
        for index in range(1, 6):
            parents[f"j_loot_sack_component{index}"] = "j_loot_sack"
        self.rest = [{"name": name, "parent": parents[name], "inherit_scale": "FULL",
                      "rest": [[100., 0., 0., index * .001], [0., 100., 0., 0.],
                               [0., 0., 100., 0.], [0., 0., 0., 1.]]}
                     for index, name in enumerate(BONES)]
        self.rest_hash = digest(canonical(self.rest))
        self.rest_path = self.write_json("authoring/rest.json", {
            "skeleton": self.rest, "sources": {"body_sha256": self.body_hash}})
        self.plan["rest_manifest"] = {"path": "rest.json", "sha256": digest(self.rest_path.read_bytes())}
        self.add_export("walk", "base/walk")
        self.add_export("shoot", "base/shoot_start")
        self.save()

    def write(self, relative, contents):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        self.tracked.add(path)
        return path

    def write_json(self, relative, value):
        return self.write(relative, json.dumps(value, indent=2, allow_nan=False).encode("utf-8"))

    def save(self):
        self.write_json("authoring/plan.json", self.plan)

    def contract(self):
        return {record["name"]: {"parent": record["parent"], "rest_matrix": copy.deepcopy(record["rest"]),
                "inherit_scale": record["inherit_scale"], "use_local_location": True,
                "use_inherit_rotation": True} for record in self.rest}

    def add_export(self, clip_id, state_name=None):
        fbx = self.write(f"authoring/{clip_id}.fbx", ("authored " + clip_id).encode())
        sidecar = self.write(f"authoring/{clip_id}.animation",
                            ('bones = "' + UNIT + '"\ntolerance = { "" = [ 0 0 0 false false false ] }\n').encode())
        receipt = {"schema": 1, "status": "fbx-roundtrip-passed",
                   "export_script_sha256": sorted(stage.APPROVED_EXPORTERS)[0],
                   "shipping_sha256": self.body_hash, "shipping_bones_sha256": self.bones_hash,
                   "fbx_sha256": digest(fbx.read_bytes()), "animation_sha256": digest(sidecar.read_bytes()),
                   "bone_names": BONES[:], "rest_contract": self.contract(), "fps": 60,
                   "position_tolerance_m": 5e-5,
                   "frame_start": 1, "frame_end": 3, "exported_frame_start": 0, "exported_frame_end": 2,
                   "roundtrip": {"frames": 3, "bones_per_frame": 138, "comparisons": 414,
                                 "max_rest_matrix_component_error": 0., "max_head_error_m": 0.,
                                 "max_axis_tip_error_m": 0.}}
        path = self.write_json(f"authoring/{clip_id}.export.json", receipt)
        self.plan["authored_clips"][clip_id] = {
            "fbx": f"{clip_id}.fbx", "receipt": f"{clip_id}.export.json",
            "receipt_sha256": digest(path.read_bytes()), "resource": RESOURCE_PREFIX + clip_id}
        if state_name is not None:
            self.plan["states"][state_name] = clip_id

    def mutate_receipt(self, clip_id, mutation):
        path = self.root / f"authoring/{clip_id}.export.json"
        receipt = json.loads(path.read_text())
        mutation(receipt)
        self.write_json(path.relative_to(self.root), receipt)
        self.plan["authored_clips"][clip_id]["receipt_sha256"] = digest(path.read_bytes())

    def add_localized(self):
        body = self.write("authoring/localized.fbx", b"localized corrective weight body")
        receipt = {"schema": 1, "status": "body-roundtrip-passed", "weight_changes_only": True,
                   "production_units_modified": False, "shipping_fbx_sha256": self.body_hash,
                   "fbx_sha256": digest(body.read_bytes()), "bone_names": BONES[:], "rest_contract": self.contract(),
                   "export_script_sha256": "e493703735774ff9a9698e6378fdbb71bf9de49bb8ca7e45f073aa404c628977",
                   "weight_only_operation": {"changed_vertices": 1, "changed_skin_clusters": list(RESERVED),
                       "approved_non_weight_semantic_sha256": "d" * 64, "candidate_non_weight_semantic_sha256": "d" * 64,
                       "preserved": ["geometry", "topology", "normals", "UVs", "materials", "skeleton", "bind_matrices",
                                     "object_wrappers", "animation_takes", "metadata"]}}
        geometry = {"vertices": 3, "polygons": 1, "loops": 3, "uv_layers": 1,
                    "max_vertex_error_source_units": 0., "max_uv_error": 0.,
                    "max_normal_component_error": 0., "max_mesh_transform_component_error": 0.}
        receipt["approved_geometry_comparison"] = geometry
        receipt["roundtrip"] = {"geometry": copy.deepcopy(geometry), "max_rest_matrix_component_error": 0.,
                                "max_weight_error": 0., "max_neutral_skin_error_m": 0.}
        body_receipt = self.write_json("authoring/localized.body-export.json", receipt)
        records = {record["name"]: record for record in self.rest}
        hips_x = records["j_hips"]["rest"][0][3]
        offsets = {"schema": 1, "profile_id": "localized-v1-runtime", "skin_profile": "localized-v1",
                   "unit_resource": UNIT, "reference_bone": "j_hips", "shipping_body_sha256": self.body_hash,
                   "shipping_bones_sha256": self.bones_hash, "rig_manifest_sha256": digest(self.rest_path.read_bytes()),
                   "rest_contract_sha256": self.rest_hash, "candidate_body_receipt_sha256": digest(body_receipt.read_bytes()),
                   "channels": [{"bone": name, "parent": records[name]["parent"], "bind_offset": [
                       [1., 0., 0., records[name]["rest"][0][3] - hips_x], [0., 1., 0., 0.],
                       [0., 0., 1., 0.], [0., 0., 0., 1.]]} for name in RESERVED]}
        offset_path = self.write_json("authoring/offsets.json", offsets)
        self.plan["localized_profile"] = {"body": "localized.fbx", "body_receipt": "localized.body-export.json",
            "body_receipt_sha256": digest(body_receipt.read_bytes()), "offsets": "offsets.json",
            "offsets_sha256": digest(offset_path.read_bytes())}

    def mutate_localized(self, document, mutation):
        field, relative = {"body": ("body_receipt_sha256", "authoring/localized.body-export.json"),
                           "offsets": ("offsets_sha256", "authoring/offsets.json")}[document]
        path = self.root / relative
        value = json.loads(path.read_text())
        mutation(value)
        self.write_json(relative, value)
        self.plan["localized_profile"][field] = digest(path.read_bytes())
        if document == "body":
            # Keep downstream provenance valid so a receipt mutation exercises
            # its own semantic gate rather than failing an old linked digest.
            offset_path = self.root / "authoring/offsets.json"
            offsets = json.loads(offset_path.read_text())
            offsets["candidate_body_receipt_sha256"] = digest(path.read_bytes())
            self.write_json("authoring/offsets.json", offsets)
            self.plan["localized_profile"]["offsets_sha256"] = digest(offset_path.read_bytes())

    def add_sdk(self, clip_id="walk", halfway=False):
        export = self.plan["authored_clips"][clip_id]
        receipt_path = self.root / ("authoring/" + export["receipt"])
        export_receipt = json.loads(receipt_path.read_text())
        count = export_receipt["frame_end"] - export_receipt["frame_start"] + 1
        report = {"schema": 1, "diagnostic_status": "sdk-compiled-and-decoded",
                  "production_units_modified": False, "compiled_unit_sha256": "a" * 64,
                  "compiled_animation_sha256": "b" * 64,
                  "input_receipt": {"animation_fbx_sha256": export_receipt["fbx_sha256"],
                    "animation_sidecar_sha256": export_receipt["animation_sha256"],
                    "animation_manifest_sha256": digest(receipt_path.read_bytes()),
                    "shipping_fbx_sha256": self.body_hash, "shipping_bones_sha256": self.bones_hash,
                    "body_fbx_sha256": digest((self.root / "authoring/localized.fbx").read_bytes())
                        if "localized_profile" in self.plan else self.body_hash,
                    "skin_profile_sha256": digest(self.rest_path.read_bytes())},
                  "animation": {"fidelity_errors": [], "bones": 138,
                    "sampled_world_bone_comparisons": count * 138,
                    "max_world_head_error_m": 0., "max_world_axis_probe_error_m": 0.,
                    "frames": [{"frame": export_receipt["frame_start"] + index, "time": index / 60,
                                "head_error_m": 0., "axis_error_m": 0.} for index in range(count)]},
                  "deformation": {"fidelity_errors": [], "tolerance_m": .002,
                    "max_weighted_skin_error_m": 0., "weighted_comparisons": count * 10,
                    "pose_samples": [{"frame": export_receipt["frame_start"] + index, "time": index / 60,
                        "vertices": 10, "max_weighted_skin_error_m": 0.} for index in range(count)]}}
        if halfway:
            report["midpoint_motion"] = {"status": "sdk-compiled-and-decoded", "fidelity_errors": [],
                "pose_samples": count - 1, "bone_comparisons": (count - 1) * 138, "tolerance_m": .002,
                "max_head_error_m": 0., "max_axis_probe_error_m": 0.,
                "samples": [{"time_seconds": (index + .5) / 60, "head_error_m": 0.,
                             "axis_probe_error_m": 0.} for index in range(count - 1)]}
        path = self.write_json(f"authoring/{clip_id}.sdk.json", report)
        export.update(sdk_report=f"{clip_id}.sdk.json", sdk_report_sha256=digest(path.read_bytes()))

    def mutate_sdk(self, mutation, clip_id="walk"):
        path = self.root / f"authoring/{clip_id}.sdk.json"
        report = json.loads(path.read_text())
        mutation(report)
        self.write_json(path.relative_to(self.root), report)
        self.plan["authored_clips"][clip_id]["sdk_report_sha256"] = digest(path.read_bytes())

    def snapshot(self):
        return {path: path.read_bytes() for path in self.tracked}

    def run(self, localized=False, output=None, config_path=None):
        if config_path is None:
            self.save()
        with patch.multiple(stage, APPROVED_BODY_SHA=self.body_hash, APPROVED_BONES_SHA=self.bones_hash,
                            APPROVED_REST_SHA=self.rest_hash):
            return stage.stage_integration(config_path or self.plan_path, self.root, output or self.output, localized)

    def create(self, **kwargs):
        options = {"plan_path": self.root / "authoring/generated-plan.json", "source_root": self.root,
                   "rest_manifest": self.rest_path, "clip": self.root / "authoring/walk.fbx",
                   "states": ("base/walk",)}
        options.update(kwargs)
        with patch.multiple(stage, APPROVED_BODY_SHA=self.body_hash, APPROVED_BONES_SHA=self.bones_hash,
                            APPROVED_REST_SHA=self.rest_hash):
            return stage.create_plan(**options)


class StageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="doomrocket-stage-test-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture(Path(self.temp.name))

    def assert_rejected(self, localized=False, output=None, expected=ValueError, expected_message=None):
        fixture = self.fixture
        fixture.save()
        before = fixture.snapshot()
        rejection = (self.assertRaisesRegex(expected, expected_message) if expected_message else self.assertRaises(expected))
        with rejection:
            fixture.run(localized, output)
        self.assertEqual(before, fixture.snapshot(), "Rejected staging changed a source input")
        self.assertFalse(fixture.output.exists(), "Rejected staging published an output")
        self.assertEqual([], list((fixture.root / ".build").glob(".stage-animation-integration-*")),
                         "Rejected staging leaked temporary payloads")

    def test_stock_staging_preserves_sources_and_all_shipping_clips(self):
        fixture = self.fixture
        before = fixture.snapshot()
        receipt = fixture.run()
        self.assertEqual(before, fixture.snapshot())
        self.assertEqual(receipt, json.loads((fixture.output / "integration_receipt.json").read_text()))
        self.assertEqual("isolated-integration-staged", receipt["status"])
        self.assertEqual("authored-v1-runtime", receipt["profile_id"])
        self.assertEqual(["base/shoot_start", "base/walk"], receipt["authored_states"])
        self.assertEqual(26, receipt["shipping_clips_and_sidecars_preserved"])
        self.assertTrue(receipt["legacy_sources_unchanged"])
        self.assertFalse(receipt["production_assets_modified"])
        self.assertFalse(receipt["published"])
        for relative in SOURCE_FILES:
            if relative not in (UNIT + ".unit", UNIT + ".state_machine"):
                self.assertEqual((fixture.root / relative).read_bytes(), (fixture.output / relative).read_bytes(), relative)
        for clip_id, export in fixture.plan["authored_clips"].items():
            for suffix in (".fbx", ".animation"):
                self.assertEqual((fixture.root / f"authoring/{clip_id}{suffix}").read_bytes(),
                                 (fixture.output / (export["resource"] + suffix)).read_bytes())
        for relative, info in receipt["payload_files"].items():
            payload = (fixture.output / relative).read_bytes()
            self.assertEqual(len(payload), info["bytes"])
            self.assertEqual(digest(payload), info["sha256"])
        self.assertEqual("pending", receipt["native_pose_acceptance"])
        self.assertEqual("pending", receipt["game_runtime_acceptance"])

    def test_selected_state_edits_preserve_other_fields_and_visible_blends(self):
        fixture = self.fixture
        fixture.run()
        patched_text = (fixture.output / (UNIT + ".state_machine")).read_text()
        result = stage.Sjson(patched_text).parse().value
        expected = expected_staged_asm(fixture.plan)
        self.assertEqual(expected, result)
        states = parsed_states(patched_text)
        self.assertEqual(12, len(states))
        self.assertEqual(RESOURCE_PREFIX + "walk", states["base/walk"]["resource"])
        self.assertEqual("1", states["base/walk"]["speed"])
        self.assertFalse(states["base/walk"]["aim"])
        self.assertEqual("warlock_move_speed / 4", states["base/run"]["speed"])
        self.assertTrue(states["base/shoot_loop"]["aim"])
        self.assertEqual("units/warlock_bombardier/anims/death_shot", states["base/death"]["resource"])

    def test_gameplay_aim_policy_retains_existing_constraint(self):
        fixture = self.fixture
        fixture.plan["states"]["base/shoot_start"] = {"clip": "shoot", "aim_policy": "gameplay"}
        fixture.run()
        states = parsed_states((fixture.output / (UNIT + ".state_machine")).read_text())
        self.assertTrue(states["base/shoot_start"]["aim"])
        self.assertFalse(states["base/walk"]["aim"])
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"]["authored-v1-runtime"]
        self.assertTrue(profile["states"]["base/shoot_start"]["visible_aim"])
        self.assertEqual("gameplay", profile["states"]["base/shoot_start"]["aim_policy"])
        self.assertEqual("authored", profile["states"]["base/walk"]["aim_policy"])

    def test_invalid_aim_policy_or_state_object_is_rejected(self):
        for declaration in ({"clip": "walk", "aim_policy": "unknown"}, {"clip": "walk", "extra": True},
                            {"aim_policy": "authored"}, {"clip": True}, ["walk"]):
            with self.subTest(declaration=declaration):
                self.fixture.plan["states"]["base/walk"] = declaration
                self.assert_rejected()

    def test_gameplay_aim_requires_existing_source_constraint(self):
        self.fixture.plan["states"] = {"base/stagger_fwd": {"clip": "walk", "aim_policy": "gameplay"},
                                       "base/shoot_start": "shoot"}
        self.assert_rejected()

    def test_manifest_unit_marker_and_event_aliases_match(self):
        fixture = self.fixture
        receipt = fixture.run()
        manifest = json.loads((fixture.output / "integration_manifest.json").read_text())
        profile = manifest["profiles"]["authored-v1-runtime"]
        self.assertEqual(receipt["manifest_id"], profile.pop("manifest_id"))
        self.assertEqual(receipt["manifest_id"], digest(canonical(manifest)))
        unit = stage.Sjson((fixture.output / (UNIT + ".unit")).read_text()).parse().value
        self.assertEqual("authored-v1-runtime", unit["data"]["warlock_rig_profile"])
        self.assertEqual(receipt["manifest_id"], unit["data"]["warlock_animation_manifest_id"])
        original_unit = stage.Sjson(UNIT_BYTES.decode()).parse().value
        unit.pop("data")
        self.assertEqual(original_unit, unit)
        self.assertEqual("base/idle", profile["default_state"])
        edges = profile["states"]["base/idle"]["transitions"]
        self.assertEqual("base/shoot_start", edges["attack_shoot_align"]["to"])
        self.assertEqual("base/shoot_loop", edges["attack_shoot_start"]["to"])
        self.assertEqual("base/shoot_loop", edges["attack_shoot_loop"]["to"])
        self.assertEqual("base/stagger_fwd", edges["hit_reaction"]["to"])
        self.assertEqual("base/death", edges["ragdoll"]["to"])
        self.assertEqual("base/death", edges["death"]["to"])
        self.assertEqual({}, profile["states"]["base/death"]["transitions"])
        lua = (fixture.output / MANIFEST_PATH).read_text()
        self.assertIn('["authored-v1-runtime"]', lua)
        self.assertIn(receipt["manifest_id"], lua)
        self.assertNotIn("localized-v1-runtime", lua)

    def test_explicit_localized_profile_stages_verified_body_and_offsets(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.save()
        before = fixture.snapshot()
        receipt = fixture.run(True)
        self.assertEqual(before, fixture.snapshot())
        self.assertTrue(receipt["localized_profile_opt_in"])
        self.assertEqual("localized-v1-runtime", receipt["profile_id"])
        self.assertEqual((fixture.root / "authoring/localized.fbx").read_bytes(),
                         (fixture.output / (UNIT + ".fbx")).read_bytes())
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"]["localized-v1-runtime"]
        self.assertEqual("localized-v1", profile["accessory_skin"])
        self.assertEqual(100, profile["native_bind_scale"])
        self.assertEqual("j_hips", profile["reference_bone"])
        self.assertEqual(list(RESERVED), [channel["bone"] for channel in profile["channels"]])
        self.assertEqual(digest((fixture.root / "authoring/localized.fbx").read_bytes()), profile["body_fbx_sha256"])

    def test_localized_only_plan_is_supported(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.plan["authored_clips"] = {}
        fixture.plan["states"] = {}
        receipt = fixture.run(True)
        self.assertEqual([], receipt["authored_states"])
        self.assertEqual(ASM_BYTES, (fixture.output / (UNIT + ".state_machine")).read_bytes())
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"]["localized-v1-runtime"]
        self.assertEqual("snapshot-blend-v1", profile["cross_owner_transition_policy"])
        self.assertTrue(all(state["owner"] == "legacy" for state in profile["states"].values()))

    def test_localized_presentation_bridge_preserves_every_visible_transition(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.run(True)
        actual = stage.Sjson((fixture.output / (UNIT + ".state_machine")).read_text()).parse().value
        self.assertEqual(expected_staged_asm(fixture.plan), actual)
        for clip in CLIPS:
            for extension in ("fbx", "animation"):
                relative = f"units/warlock_bombardier/anims/{clip}.{extension}"
                self.assertEqual((fixture.root / relative).read_bytes(), (fixture.output / relative).read_bytes(), relative)

    def test_localized_manifest_matches_all_154_unchanged_visible_edges(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.run(True)
        original = edge_inventory(stage.Sjson(ASM_BYTES.decode()).parse().value)
        actual = edge_inventory(stage.Sjson((fixture.output / (UNIT + ".state_machine")).read_text()).parse().value)
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"]["localized-v1-runtime"]
        manifest_edges = {(name, event): edge for name, state in profile["states"].items()
                          for event, edge in state["transitions"].items()}
        source_states = {state["name"] for state in stage.Sjson(ASM_BYTES.decode()).parse().value["layers"][0]["states"]}
        self.assertEqual(source_states, set(profile["states"]))
        for name, state in profile["states"].items():
            self.assertEqual("authored" if name in fixture.plan["states"] else "legacy", state["owner"], name)
        self.assertEqual(154, len(original))
        self.assertEqual(set(original), set(actual))
        self.assertEqual(set(original), set(manifest_edges))
        cross_edges, same_edges = 0, 0
        authored = set(fixture.plan["states"])
        for key, before in original.items():
            after, manifest_edge = actual[key], manifest_edges[key]
            cross_owner = (key[0] in authored) != (before["to"] in authored)
            expected_blend = before["blend_time"]
            self.assertEqual(expected_blend, after["blend_time"], key)
            self.assertEqual({**before, "blend_time": expected_blend}, after, key)
            self.assertEqual({"to": before["to"], "blend_time": expected_blend}, manifest_edge, key)
            if cross_owner:
                cross_edges += 1
            else:
                same_edges += 1
                self.assertGreater(after["blend_time"], 0, key)
        self.assertEqual((42, 112), (cross_edges, same_edges))

    def test_localized_gameplay_aim_retains_constraint_and_original_blends(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.plan["states"]["base/shoot_start"] = {"clip": "shoot", "aim_policy": "gameplay"}
        fixture.run(True)
        actual = stage.Sjson((fixture.output / (UNIT + ".state_machine")).read_text()).parse().value
        self.assertEqual(expected_staged_asm(fixture.plan), actual)
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"]["localized-v1-runtime"]
        self.assertEqual("snapshot-blend-v1", profile["cross_owner_transition_policy"])
        self.assertEqual("gameplay", profile["states"]["base/shoot_start"]["aim_policy"])
        self.assertTrue(profile["states"]["base/shoot_start"]["visible_aim"])
        states = {state["name"]: state for state in actual["layers"][0]["states"]}
        self.assertIn("warlock_aim", states["base/shoot_start"]["constraints"])
        self.assertEqual(.25, edge_inventory(actual)[("base/idle", "attack_shoot_align")]["blend_time"])

    def test_stock_profile_preserves_all_visible_blends(self):
        fixture = self.fixture
        fixture.run()
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"]["authored-v1-runtime"]
        self.assertEqual("snapshot-blend-v1", profile["cross_owner_transition_policy"])
        original = edge_inventory(stage.Sjson(ASM_BYTES.decode()).parse().value)
        actual = edge_inventory(stage.Sjson((fixture.output / (UNIT + ".state_machine")).read_text()).parse().value)
        self.assertEqual(set(original), set(actual))
        self.assertEqual(154, len(actual))
        cross_edges, same_edges = 0, 0
        for (name, event), edge in original.items():
            cross_owner = (name in fixture.plan["states"]) != (edge["to"] in fixture.plan["states"])
            expected_blend = edge["blend_time"]
            self.assertEqual({**edge, "blend_time": expected_blend}, actual[(name, event)])
            self.assertEqual({"to": edge["to"], "blend_time": expected_blend},
                             profile["states"][name]["transitions"][event])
            cross_edges += cross_owner
            same_edges += not cross_owner
        self.assertEqual((42, 112), (cross_edges, same_edges))

    def test_source_transition_blends_above_one_second_are_rejected(self):
        fixture = self.fixture
        relative = UNIT + ".state_machine"
        original = ASM_BYTES.decode()
        for value in ("1.0001", "1.1", "2"):
            with self.subTest(blend_time=value):
                mutated, count = re.subn(r"\bblend_time\s*=\s*[0-9.]+", "blend_time = " + value, original, count=1)
                self.assertEqual(1, count)
                path = fixture.write(relative, mutated.encode())
                fixture.plan["source_files"][relative] = digest(path.read_bytes())
                self.assert_rejected()

    def test_plan_cannot_override_trusted_cross_owner_policy(self):
        fixture = self.fixture
        for localized in (False, True):
            if localized:
                fixture.add_localized()
            for policy in ("cut", "blend", "unknown", False, {"legacy": "cut"}):
                with self.subTest(localized=localized, policy=policy):
                    fixture.plan["cross_owner_transition_policy"] = policy
                    self.assert_rejected(localized)

    def test_localized_canonical_manifest_hash_binds_presentation_policy(self):
        fixture = self.fixture
        fixture.add_localized()
        receipt = fixture.run(True)
        manifest = json.loads((fixture.output / "integration_manifest.json").read_text())
        profile = manifest["profiles"]["localized-v1-runtime"]
        self.assertEqual("snapshot-blend-v1", profile["cross_owner_transition_policy"])
        self.assertEqual(receipt["manifest_id"], profile.pop("manifest_id"))
        self.assertEqual(receipt["manifest_id"], digest(canonical(manifest)))
        profile["cross_owner_transition_policy"] = "blend"
        self.assertNotEqual(receipt["manifest_id"], digest(canonical(manifest)))
        lua = (fixture.output / MANIFEST_PATH).read_text()
        self.assertIn('["cross_owner_transition_policy"] = "snapshot-blend-v1"', lua)

    def test_localized_event_aliases_preserve_original_target_and_blend(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.run(True)
        actual = edge_inventory(stage.Sjson((fixture.output / (UNIT + ".state_machine")).read_text()).parse().value)
        expected = edge_inventory(stage.Sjson(ASM_BYTES.decode()).parse().value)
        self.assertEqual("base/shoot_start", actual[("base/idle", "attack_shoot_align")]["to"])
        self.assertEqual(expected[("base/idle", "attack_shoot_align")]["blend_time"],
                         actual[("base/idle", "attack_shoot_align")]["blend_time"])
        for event in ("attack_shoot_start", "attack_shoot_loop"):
            self.assertEqual("base/shoot_loop", actual[("base/idle", event)]["to"])
            self.assertEqual(expected[("base/idle", event)]["blend_time"], actual[("base/idle", event)]["blend_time"])
        for event in ("ragdoll", "death"):
            self.assertEqual("base/death", actual[("base/walk", event)]["to"])
            self.assertEqual(expected[("base/walk", event)]["blend_time"],
                             actual[("base/walk", event)]["blend_time"])

    def test_sampler_only_zeros_internal_edges_and_keeps_destination_semantics(self):
        for localized in (False, True):
            with self.subTest(localized=localized):
                fixture = Fixture(Path(self.temp.name) / ("sampler-" + str(localized)))
                if localized:
                    fixture.add_localized()
                fixture.plan["states"]["base/shoot_start"] = {"clip": "shoot", "aim_policy": "gameplay"}
                fixture.save()
                before = fixture.snapshot()
                receipt = fixture.run(localized)
                self.assertEqual(before, fixture.snapshot())
                visible = stage.Sjson((fixture.output / (UNIT + ".state_machine")).read_text()).parse().value
                sampler = stage.Sjson((fixture.output / (SAMPLER + ".state_machine")).read_text()).parse().value
                expected_sampler = copy.deepcopy(visible)
                for state in expected_sampler["layers"][0]["states"]:
                    for transition in state.get("transitions", []):
                        transition["blend_time"] = 0
                self.assertEqual(expected_staged_asm(fixture.plan), visible)
                self.assertEqual(expected_sampler, sampler)
                self.assertEqual(UNIT, sampler["bones"])
                self.assertEqual(154, len(edge_inventory(sampler)))
                self.assertTrue(all(edge["blend_time"] == 0 for edge in edge_inventory(sampler).values()))
                self.assertTrue(receipt["all_visible_transition_blends_preserved"])
                self.assertTrue(receipt["sampler_transition_blends_zero"])
                self.assertEqual(SAMPLER, receipt["sampler_state_machine"])
                self.assertEqual([UNIT + ".unit"], sorted(path.relative_to(fixture.output).as_posix()
                                                       for path in fixture.output.rglob("*.unit")))
                self.assertFalse((fixture.output / (SAMPLER + ".fbx")).exists())
                self.assertFalse((fixture.output / (SAMPLER + ".bones")).exists())

    def test_manifest_binds_sampler_bone_inventory_and_exact_loop_speed_metadata(self):
        fixture = self.fixture
        receipt = fixture.run()
        manifest = json.loads((fixture.output / "integration_manifest.json").read_text())
        profile = manifest["profiles"]["authored-v1-runtime"]
        self.assertEqual(SAMPLER, profile["sampler_state_machine"])
        self.assertEqual(BONES, profile["bone_names"])
        self.assertEqual(138, len(profile["bone_names"]))
        self.assertEqual(fixture.bones_hash, profile["validation"]["shipping_bones_sha256"])
        self.assertEqual(digest((fixture.output / (SAMPLER + ".state_machine")).read_bytes()),
                         profile["validation"]["sampler_state_machine_sha256"])
        self.assertEqual(digest((fixture.output / (UNIT + ".state_machine")).read_bytes()),
                         profile["validation"]["staged_state_machine_sha256"])
        original = stage.Sjson(ASM_BYTES.decode()).parse().value
        for state in original["layers"][0]["states"]:
            record = profile["states"][state["name"]]
            self.assertIs(type(record["loop_animation"]), bool)
            self.assertEqual(state["loop_animation"], record["loop_animation"])
            self.assertEqual("1" if state["name"] in fixture.plan["states"] else state["speed"],
                             record["speed_expression"])
        self.assertEqual(receipt["manifest_id"], profile.pop("manifest_id"))
        self.assertEqual(receipt["manifest_id"], digest(canonical(manifest)))
        for mutate in (lambda value: value["bone_names"].reverse(),
                       lambda value: value.update(sampler_state_machine=UNIT),
                       lambda value: value["states"]["base/walk"].update(loop_animation=False),
                       lambda value: value["states"]["base/run"].update(speed_expression="1")):
            changed = copy.deepcopy(manifest)
            mutate(changed["profiles"]["authored-v1-runtime"])
            self.assertNotEqual(receipt["manifest_id"], digest(canonical(changed)))

    def test_visible_nonuniform_durations_are_preserved_while_sampler_zeros_them(self):
        fixture = self.fixture
        relative = UNIT + ".state_machine"
        text, count = re.subn(r"\bblend_time\s*=\s*[0-9.]+", "blend_time = 0.137", ASM_BYTES.decode(), count=1)
        self.assertEqual(1, count)
        path = fixture.write(relative, text.encode())
        fixture.plan["source_files"][relative] = digest(path.read_bytes())
        fixture.run()
        original = edge_inventory(stage.Sjson(text).parse().value)
        visible = edge_inventory(stage.Sjson((fixture.output / relative).read_text()).parse().value)
        sampler = edge_inventory(stage.Sjson((fixture.output / (SAMPLER + ".state_machine")).read_text()).parse().value)
        self.assertEqual(original, visible)
        self.assertEqual(set(original), set(sampler))
        self.assertTrue(all(edge["blend_time"] == 0 for edge in sampler.values()))

    def test_invalid_loop_or_speed_metadata_is_rejected_before_staging(self):
        fixture = self.fixture
        relative = UNIT + ".state_machine"
        for field, pattern, values in (
            ("loop_animation", r"\bloop_animation\s*=\s*(?:true|false)", ('"true"', "1", "null")),
            ("speed", r'\bspeed\s*=\s*"[^"\r\n]*"', ('""', "1", "false", '"\\n"')),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    text, count = re.subn(pattern, lambda match: field + " = " + value, ASM_BYTES.decode(), count=1)
                    self.assertEqual(1, count)
                    path = fixture.write(relative, text.encode())
                    fixture.plan["source_files"][relative] = digest(path.read_bytes())
                    self.assert_rejected()

    def test_sampler_resource_alias_and_plan_overrides_are_rejected(self):
        fixture = self.fixture
        for key, value in (("sampler_state_machine", UNIT), ("bone_names", BONES),
                           ("validation", {"sampler_state_machine_sha256": "a" * 64}),
                           ("resource_package", "other.package")):
            with self.subTest(field=key):
                fixture.plan[key] = value
                self.assert_rejected()
                fixture.plan.pop(key)
        fixture.write(SAMPLER + ".state_machine", b"unreviewed existing helper")
        self.assert_rejected()

    def rehearsal(self, fixture):
        sys.path.insert(0, str(ROOT / "tools/animation_rig"))
        import build_native_rehearsal as rehearsal
        with patch.object(rehearsal, "stage", stage), patch.multiple(stage,
                APPROVED_BODY_SHA=fixture.body_hash, APPROVED_BONES_SHA=fixture.bones_hash):
            outputs = rehearsal.create(fixture.root)
        for relative, contents in outputs.items():
            fixture.write(relative, contents)
        return rehearsal, outputs

    def test_verified_stock_rehearsal_sampler_can_be_replaced_only_in_isolated_overlay(self):
        fixture = self.fixture
        rehearsal, outputs = self.rehearsal(fixture)
        before = fixture.snapshot()
        with patch.object(rehearsal, "stage", stage):
            receipt = fixture.run()
        self.assertEqual(before, fixture.snapshot())
        for relative, contents in outputs.items():
            self.assertEqual((fixture.root / relative).read_bytes(), contents)
            self.assertEqual(receipt["source_inputs_sha256"][str((fixture.root / relative).resolve())], digest(contents))
        self.assertNotEqual((fixture.root / (SAMPLER + ".state_machine")).read_bytes(),
                            (fixture.output / (SAMPLER + ".state_machine")).read_bytes())

    def test_partial_or_changed_rehearsal_contract_does_not_waive_source_alias_guard(self):
        for mutation in ("sampler", "visible", "profile", "contract", "missing"):
            with self.subTest(mutation=mutation):
                fixture = Fixture(Path(self.temp.name) / mutation)
                rehearsal, outputs = self.rehearsal(fixture)
                path = {"sampler": SAMPLER + ".state_machine", "visible": rehearsal.VISIBLE + ".state_machine",
                        "profile": rehearsal.COMPANION, "contract": rehearsal.CONTRACT,
                        "missing": rehearsal.COMPANION}[mutation]
                target = fixture.root / path
                if mutation == "missing": target.unlink(); fixture.tracked.remove(target)
                else: fixture.write(path, target.read_bytes() + b"\nmutation")
                before = fixture.snapshot()
                with patch.object(rehearsal, "stage", stage), self.assertRaises(ValueError): fixture.run()
                self.assertEqual(before, fixture.snapshot())
                self.assertFalse(fixture.output.exists())

    def test_sampler_write_failure_rolls_back_without_publishing_or_mutating_sources(self):
        fixture = self.fixture
        write = Path.write_bytes

        def failed_write(path, data):
            if path.name == "presentation_sampler.state_machine":
                raise OSError("injected helper write failure")
            return write(path, data)

        with patch.object(Path, "write_bytes", failed_write):
            self.assert_rejected(expected=OSError)

    def test_silent_visible_or_sampler_asm_mutation_is_rejected_before_publication(self):
        write = Path.write_bytes
        for filename in ("warlock_bombardier_3p.state_machine", "presentation_sampler.state_machine"):
            with self.subTest(filename=filename):
                def changed_write(path, data):
                    if path.name == filename:
                        data, count = re.subn(rb"\bblend_time\s*=\s*[0-9.]+", b"blend_time = 0.137", data, count=1)
                        self.assertEqual(1, count)
                    return write(path, data)

                with patch.object(Path, "write_bytes", changed_write):
                    self.assert_rejected()

    def test_silent_generated_unit_or_manifest_mutation_is_rejected_before_publication(self):
        write = Path.write_bytes
        for filename in ("warlock_bombardier_3p.unit", "doomrocket_animation_manifest.lua", "integration_manifest.json"):
            with self.subTest(filename=filename):
                def changed_write(path, data):
                    if path.name == filename:
                        data += b"\n"
                    return write(path, data)

                with patch.object(Path, "write_bytes", changed_write):
                    self.assert_rejected()

    def test_reviewed_resource_package_is_copied_and_hash_bound_without_changing_plan_pins(self):
        fixture = self.fixture
        before = fixture.snapshot()
        receipt = fixture.run()
        self.assertEqual(before, fixture.snapshot())
        self.assertEqual(set(SOURCE_FILES), set(fixture.plan["source_files"]))
        self.assertEqual(31, len(fixture.plan["source_files"]))
        self.assertEqual(PACKAGE_BYTES, (fixture.output / RESOURCE_PACKAGE).read_bytes())
        package_hash = digest(PACKAGE_BYTES)
        self.assertEqual(RESOURCE_PACKAGE, receipt["resource_package"])
        self.assertEqual(package_hash, receipt["resource_package_sha256"])
        self.assertTrue(receipt["sampler_resource_in_mod_package"])
        self.assertEqual(package_hash, receipt["source_inputs_sha256"][str(fixture.root / RESOURCE_PACKAGE)])
        self.assertEqual(package_hash, receipt["payload_files"][RESOURCE_PACKAGE]["sha256"])
        profile = json.loads((fixture.output / "integration_manifest.json").read_text())["profiles"][receipt["profile_id"]]
        self.assertEqual(RESOURCE_PACKAGE, profile["validation"]["resource_package"])
        self.assertEqual(package_hash, profile["validation"]["resource_package_sha256"])
        profile["validation"]["resource_package_sha256"] = "f" * 64
        profile.pop("manifest_id")
        altered = {"schema": 1, "profiles": {receipt["profile_id"]: profile}}
        self.assertNotEqual(receipt["manifest_id"], digest(canonical(altered)))

    def test_localized_legacy_only_profile_also_closes_sampler_package_loading(self):
        fixture = self.fixture
        fixture.add_localized()
        fixture.plan["authored_clips"], fixture.plan["states"] = {}, {}
        fixture.save()
        before = fixture.snapshot()
        receipt = fixture.run(True)
        self.assertEqual(before, fixture.snapshot())
        self.assertEqual([], receipt["authored_states"])
        self.assertTrue(receipt["sampler_resource_in_mod_package"])
        self.assertEqual(PACKAGE_BYTES, (fixture.output / RESOURCE_PACKAGE).read_bytes())

    def test_missing_resource_package_is_rejected(self):
        fixture = self.fixture
        package = fixture.root / RESOURCE_PACKAGE
        package.unlink()
        fixture.tracked.remove(package)
        self.assert_rejected()

    def test_unsupported_resource_package_or_missing_load_globs_are_rejected(self):
        fixture = self.fixture
        reviewed = stage.Sjson(PACKAGE_BYTES.decode()).parse().value
        mutations = (
            lambda value: value.pop("state_machine"),
            lambda value: value.update(state_machine=[UNIT]),
            lambda value: value.update(state_machine=["other_units/*"]),
            lambda value: value.update(unit=[]),
            lambda value: value.update(lua=["scripts/mods/other/*"]),
            lambda value: value.update(mod=["other"]),
            lambda value: value.update(package=["resource_packages/other/other"]),
            lambda value: value.update(unknown_resource=["units/*"]),
            lambda value: value.update(state_machine=["units/*", "units/*"]),
            lambda value: value.update(state_machine=["units/*", "../other/*"]),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                value = copy.deepcopy(reviewed)
                mutation(value)
                encoded = root_sjson(value)
                self.assertEqual(value, stage.Sjson(encoded.decode()).parse().value)
                fixture.write(RESOURCE_PACKAGE, encoded)
                self.assert_rejected(expected_message="Unsupported mod resource package")

    def test_resource_package_source_mutation_during_copy_is_rejected(self):
        fixture = self.fixture
        package = fixture.root / RESOURCE_PACKAGE
        original = stage.shutil.copy2
        changed = False

        def changed_copy(source, target, *args, **kwargs):
            nonlocal changed
            result = original(source, target, *args, **kwargs)
            if Path(source).resolve() == package:
                package.write_bytes(PACKAGE_BYTES + b"\n// external package mutation\n")
                changed = True
            return result

        with patch.object(stage.shutil, "copy2", changed_copy):
            with self.assertRaises(ValueError):
                fixture.run()
        self.assertTrue(changed)
        self.assertFalse(fixture.output.exists())
        self.assertEqual([], list((fixture.root / ".build").glob(".stage-animation-integration-*")))

    def test_resource_package_semantics_use_the_same_bytes_as_its_hash(self):
        fixture = self.fixture
        package = fixture.root / RESOURCE_PACKAGE
        unsupported = stage.Sjson(PACKAGE_BYTES.decode()).parse().value
        unsupported.pop("state_machine")
        encoded = root_sjson(unsupported)
        self.assertEqual(unsupported, stage.Sjson(encoded.decode()).parse().value)
        fixture.write(RESOURCE_PACKAGE, encoded)
        original = Path.read_text

        def transient_approved_text(path, *args, **kwargs):
            if path.resolve() == package:
                return PACKAGE_BYTES.decode()
            return original(path, *args, **kwargs)

        # Hashing unreviewed A but parsing transient reviewed B must never
        # approve and publish A. The validator hashes and parses one buffer.
        with patch.object(Path, "read_text", transient_approved_text):
            self.assert_rejected(expected_message="Unsupported mod resource package")

    def test_silent_late_resource_package_payload_mutation_rolls_back(self):
        fixture = self.fixture
        original = Path.write_bytes
        changed = False

        def changed_write(path, data):
            nonlocal changed
            if path.name == "presentation_sampler.state_machine":
                package = path.parents[3] / RESOURCE_PACKAGE
                self.assertTrue(package.is_file())
                original(package, PACKAGE_BYTES + b"\n")
                changed = True
            return original(path, data)

        with patch.object(Path, "write_bytes", changed_write):
            self.assert_rejected()
        self.assertTrue(changed)

    def test_localized_declaration_requires_explicit_flag(self):
        self.fixture.add_localized()
        self.assert_rejected()

    def test_localized_flag_requires_body_profile(self):
        self.assert_rejected(True)

    def test_unknown_states_and_event_aliases_are_rejected(self):
        for state_name in ("base/unknown", "attack_shoot_align", "attack_shoot_start", "death", "combat_run_start_fwd"):
            with self.subTest(state=state_name):
                self.fixture.plan["states"] = {state_name: "walk", "base/shoot_start": "shoot"}
                self.assert_rejected()

    def test_authored_death_is_rejected(self):
        self.fixture.plan["states"] = {"base/death": "walk", "base/shoot_start": "shoot"}
        self.assert_rejected()

    def test_unknown_or_unused_clip_mapping_is_rejected(self):
        for mapping in ({"base/walk": "missing", "base/shoot_start": "shoot"}, {"base/walk": "walk"}):
            with self.subTest(mapping=mapping):
                self.fixture.plan["states"] = mapping
                self.assert_rejected()

    def test_duplicate_and_unsafe_resources_are_rejected(self):
        resources = (RESOURCE_PREFIX + "walk", "units/warlock_bombardier/anims/combat_run",
                     RESOURCE_PREFIX + "../escape", RESOURCE_PREFIX + "bad\\escape",
                     RESOURCE_PREFIX + "quoted\"name", RESOURCE_PREFIX + "bad.fbx", RESOURCE_PREFIX + "//empty")
        for resource in resources:
            with self.subTest(resource=resource):
                self.fixture.plan["authored_clips"]["shoot"]["resource"] = resource
                self.assert_rejected()

    def test_authored_resource_cannot_alias_existing_source_file(self):
        self.fixture.write(RESOURCE_PREFIX + "shoot.fbx", b"unapproved existing candidate")
        self.assert_rejected()

    def test_same_fbx_source_cannot_alias_multiple_resources(self):
        export = self.fixture.plan["authored_clips"]
        export["shoot"] = {**export["walk"], "resource": RESOURCE_PREFIX + "shoot"}
        self.assert_rejected()

    def test_relative_input_escape_is_rejected(self):
        for key, path in (("fbx", "../authoring/walk.fbx"), ("receipt", "../authoring/walk.export.json"),
                          ("fbx", "walk\\walk.fbx")):
            with self.subTest(key=key, path=path):
                original = self.fixture.plan["authored_clips"]["walk"][key]
                self.fixture.plan["authored_clips"]["walk"][key] = path
                self.assert_rejected()
                self.fixture.plan["authored_clips"]["walk"][key] = original

    def test_output_must_be_new_named_build_overlay(self):
        for output in (self.fixture.root / "units/new", self.fixture.root / ".build/other",
                       self.fixture.root / ".build/animation_integration", self.fixture.root / "elsewhere/animation_integration_test"):
            with self.subTest(output=output):
                self.assert_rejected(output=output)
                self.assertFalse(output.exists())

    def test_existing_output_directory_is_preserved(self):
        fixture = self.fixture
        fixture.output.mkdir(parents=True)
        sentinel = fixture.output / "keep.bin"
        sentinel.write_bytes(b"previous integration")
        fixture.save()
        before = fixture.snapshot()
        with self.assertRaises(ValueError):
            fixture.run()
        self.assertEqual(b"previous integration", sentinel.read_bytes())
        self.assertEqual(before, fixture.snapshot())

    def test_existing_output_file_is_preserved(self):
        fixture = self.fixture
        fixture.output.parent.mkdir(parents=True)
        fixture.output.write_bytes(b"previous file")
        with self.assertRaises(ValueError):
            fixture.run()
        self.assertEqual(b"previous file", fixture.output.read_bytes())

    def test_source_inventory_must_be_complete_and_exact(self):
        original = self.fixture.plan["source_files"].copy()
        for mutation in (lambda data: data.pop(UNIT + ".dcc_asset"),
                         lambda data: data.update({"units/unexpected.fbx": "a" * 64})):
            with self.subTest(mutation=mutation):
                self.fixture.plan["source_files"] = original.copy()
                mutation(self.fixture.plan["source_files"])
                self.assert_rejected()

    def test_changed_shipping_source_is_rejected(self):
        relative = f"units/warlock_bombardier/anims/{CLIPS[0]}.animation"
        self.fixture.write(relative, b"shipping sidecar changed after plan")
        self.assert_rejected()

    def test_unapproved_body_or_bones_are_rejected_even_with_plan_hashes(self):
        fixture = self.fixture
        for constant in ("APPROVED_BODY_SHA", "APPROVED_BONES_SHA"):
            with self.subTest(constant=constant):
                fixture.save()
                with patch.multiple(stage, APPROVED_BODY_SHA=fixture.body_hash, APPROVED_BONES_SHA=fixture.bones_hash,
                                    APPROVED_REST_SHA=fixture.rest_hash):
                    with patch.object(stage, constant, "a" * 64):
                        with self.assertRaises(ValueError):
                            stage.stage_integration(fixture.plan_path, fixture.root, fixture.output)
                self.assertFalse(fixture.output.exists())

    def test_receipt_file_hash_is_required(self):
        self.fixture.plan["authored_clips"]["walk"]["receipt_sha256"] = "a" * 64
        self.assert_rejected()

    def test_export_hash_status_and_shipping_provenance_gates(self):
        original = (self.fixture.root / "authoring/walk.export.json").read_bytes()
        for field, value in (("status", "pending"), ("export_script_sha256", "a" * 64),
                             ("shipping_sha256", "a" * 64), ("shipping_bones_sha256", "a" * 64),
                             ("fbx_sha256", "a" * 64), ("animation_sha256", "a" * 64)):
            with self.subTest(field=field):
                self.fixture.write("authoring/walk.export.json", original)
                self.fixture.mutate_receipt("walk", lambda data: data.update({field: value}))
                self.assert_rejected()

    def test_roundtrip_coverage_and_measurements_are_required(self):
        original = (self.fixture.root / "authoring/walk.export.json").read_bytes()
        for field, value in (("frames", 2), ("bones_per_frame", 137), ("comparisons", 413),
                             ("max_rest_matrix_component_error", .000051), ("max_head_error_m", .000051),
                             ("max_axis_tip_error_m", .000051), ("max_head_error_m", -1),
                             ("max_axis_tip_error_m", True)):
            with self.subTest(field=field, value=value):
                self.fixture.write("authoring/walk.export.json", original)
                self.fixture.mutate_receipt("walk", lambda data: data["roundtrip"].update({field: value}))
                self.assert_rejected()

    def test_fps_frame_range_and_origin_are_required(self):
        original = (self.fixture.root / "authoring/walk.export.json").read_bytes()
        for field, value in (("fps", 30), ("frame_start", True), ("frame_end", 0),
                             ("exported_frame_start", 1), ("exported_frame_end", 3),
                             ("position_tolerance_m", 0), ("position_tolerance_m", .000051),
                             ("position_tolerance_m", True)):
            with self.subTest(field=field):
                self.fixture.write("authoring/walk.export.json", original)
                self.fixture.mutate_receipt("walk", lambda data: data.update({field: value}))
                self.assert_rejected()

    def test_mixed_clip_rest_parent_scale_matrix_and_bone_order_are_rejected(self):
        original = (self.fixture.root / "authoring/shoot.export.json").read_bytes()
        mutations = {
            "parent": lambda data: data["rest_contract"]["j_whip_parent"].update(parent="root_point"),
            "inherit_scale": lambda data: data["rest_contract"]["j_whip_parent"].update(inherit_scale="NONE"),
            "matrix": lambda data: data["rest_contract"]["j_whip_parent"]["rest_matrix"][0].__setitem__(3, 9.),
            "bone_order": lambda data: data["bone_names"].reverse(),
            "missing_bone": lambda data: data["rest_contract"].pop("j_whip_parent"),
            "local_location": lambda data: data["rest_contract"]["j_whip_parent"].update(use_local_location=False),
            "inherit_rotation": lambda data: data["rest_contract"]["j_whip_parent"].update(use_inherit_rotation=False),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                self.fixture.write("authoring/shoot.export.json", original)
                self.fixture.mutate_receipt("shoot", mutation)
                self.assert_rejected()

    def test_rest_manifest_hash_and_provenance_are_required(self):
        fixture = self.fixture
        original = fixture.rest_path.read_bytes()
        for field in ("digest", "body", "order"):
            with self.subTest(field=field):
                fixture.write("authoring/rest.json", original)
                value = json.loads(original)
                if field == "body":
                    value["sources"]["body_sha256"] = "a" * 64
                elif field == "order":
                    value["skeleton"].reverse()
                fixture.write_json("authoring/rest.json", value)
                fixture.plan["rest_manifest"]["sha256"] = "a" * 64 if field == "digest" else digest(fixture.rest_path.read_bytes())
                self.assert_rejected()

    def test_invalid_authored_sidecar_settings_are_rejected(self):
        path = self.fixture.root / "authoring/walk.animation"
        for settings in ("0 0 0 false false", "0 0 0 false true false", "0 0.0001 0 false false false",
                         "false 0 0 false false false"):
            with self.subTest(settings=settings):
                self.fixture.write("authoring/walk.animation", ('bones = "' + UNIT + '"\ntolerance = { "" = [ ' + settings + ' ] }').encode())
                self.fixture.mutate_receipt("walk", lambda data: data.update(animation_sha256=digest(path.read_bytes())))
                self.assert_rejected()

    def test_localized_body_receipt_and_payload_gates(self):
        self.fixture.add_localized()
        original = (self.fixture.root / "authoring/localized.body-export.json").read_bytes()
        mutations = {
            "schema": lambda data: data.update(schema=2),
            "status": lambda data: data.update(status="pending"),
            "exporter": lambda data: data.update(export_script_sha256="a" * 64),
            "weights": lambda data: data.update(weight_changes_only=False),
            "production": lambda data: data.update(production_units_modified=True),
            "shipping": lambda data: data.update(shipping_fbx_sha256="a" * 64),
            "body": lambda data: data.update(fbx_sha256="a" * 64),
            "rest": lambda data: data["rest_contract"]["j_whip_parent"]["rest_matrix"][0].__setitem__(3, 9.),
            "semantics": lambda data: data["weight_only_operation"].update(candidate_non_weight_semantic_sha256="e" * 64),
            "empty_geometry": lambda data: data["approved_geometry_comparison"].update(vertices=0),
            "changed_geometry": lambda data: data["approved_geometry_comparison"].update(max_vertex_error_source_units=.01),
            "roundtrip_count": lambda data: data["roundtrip"]["geometry"].update(vertices=4),
            "roundtrip_weight": lambda data: data["roundtrip"].update(max_weight_error=.000003),
            "roundtrip_rest": lambda data: data["roundtrip"].update(max_rest_matrix_component_error=.000051),
            "roundtrip_skin": lambda data: data["roundtrip"].update(max_neutral_skin_error_m=.000051),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                self.fixture.write("authoring/localized.body-export.json", original)
                self.fixture.mutate_localized("body", mutation)
                self.assert_rejected(True)

    def test_localized_offsets_provenance_and_channel_gates(self):
        self.fixture.add_localized()
        original = (self.fixture.root / "authoring/offsets.json").read_bytes()
        mutations = {
            "profile": lambda data: data.update(profile_id="foreign"),
            "shipping": lambda data: data.update(shipping_body_sha256="a" * 64),
            "bones": lambda data: data.update(shipping_bones_sha256="a" * 64),
            "manifest": lambda data: data.update(rig_manifest_sha256="a" * 64),
            "contract": lambda data: data.update(rest_contract_sha256="a" * 64),
            "body_receipt": lambda data: data.update(candidate_body_receipt_sha256="a" * 64),
            "order": lambda data: data["channels"].reverse(),
            "missing": lambda data: data["channels"].pop(),
            "parent": lambda data: data["channels"][0].update(parent="root_point"),
            "offset": lambda data: data["channels"][0]["bind_offset"][0].__setitem__(3, 9.),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                self.fixture.write("authoring/offsets.json", original)
                self.fixture.mutate_localized("offsets", mutation)
                self.assert_rejected(True)

    def test_missing_localized_body_is_rejected(self):
        self.fixture.add_localized()
        path = self.fixture.root / "authoring/localized.fbx"
        self.fixture.tracked.remove(path)
        path.unlink()
        self.assert_rejected(True)

    def test_sdk_report_and_hash_must_be_supplied_together(self):
        for values in ({"sdk_report": "missing.json"}, {"sdk_report_sha256": "a" * 64}):
            with self.subTest(values=values):
                export = self.fixture.plan["authored_clips"]["walk"]
                export.pop("sdk_report", None)
                export.pop("sdk_report_sha256", None)
                export.update(values)
                self.assert_rejected()

    def test_optional_sdk_evidence_is_copied_without_staged_unit_acceptance(self):
        fixture = self.fixture
        fixture.add_sdk(halfway=True)
        receipt = fixture.run()
        self.assertEqual((fixture.root / "authoring/walk.sdk.json").read_bytes(),
                         (fixture.output / "integration_evidence/walk.sdk.json").read_bytes())
        self.assertTrue(receipt["sdk_staged_unit_acceptance"].startswith("pending;"))
        self.assertEqual("pending", receipt["game_runtime_acceptance"])

    def test_sdk_input_hashes_are_bound_to_selected_sources(self):
        self.fixture.add_sdk()
        original = (self.fixture.root / "authoring/walk.sdk.json").read_bytes()
        fields = ("animation_fbx_sha256", "animation_sidecar_sha256", "animation_manifest_sha256",
                  "shipping_fbx_sha256", "shipping_bones_sha256", "body_fbx_sha256", "skin_profile_sha256")
        for field in fields:
            with self.subTest(field=field):
                self.fixture.write("authoring/walk.sdk.json", original)
                self.fixture.mutate_sdk(lambda data: data["input_receipt"].update({field: "c" * 64}))
                self.assert_rejected()

    def test_sdk_authored_coverage_measurements_and_halfway_are_required(self):
        self.fixture.add_sdk(halfway=True)
        original = (self.fixture.root / "authoring/walk.sdk.json").read_bytes()
        mutations = {
            "schema": lambda data: data.update(schema=2),
            "status": lambda data: data.update(diagnostic_status="pending"),
            "production": lambda data: data.update(production_units_modified=True),
            "compiled": lambda data: data.update(compiled_animation_sha256="not-a-hash"),
            "empty": lambda data: data.update(animation={}, deformation={}),
            "bones": lambda data: data["animation"].update(bones=137),
            "comparisons": lambda data: data["animation"].update(sampled_world_bone_comparisons=413),
            "frames": lambda data: data["animation"]["frames"].pop(),
            "number": lambda data: data["animation"]["frames"][1].update(frame=1),
            "time": lambda data: data["animation"]["frames"][1].update(time=0.),
            "pose": lambda data: data["animation"]["frames"][1].update(head_error_m=.0021),
            "skin_frames": lambda data: data["deformation"]["pose_samples"].pop(),
            "skin_count": lambda data: data["deformation"].update(weighted_comparisons=29),
            "skin_vertices": lambda data: data["deformation"]["pose_samples"][0].update(vertices=True),
            "skin_error": lambda data: data["deformation"]["pose_samples"][0].update(max_weighted_skin_error_m=.0021),
            "halfway_count": lambda data: data["midpoint_motion"].update(pose_samples=1),
            "halfway_samples": lambda data: data["midpoint_motion"]["samples"].pop(),
            "halfway_time": lambda data: data["midpoint_motion"]["samples"][0].update(time_seconds=0.),
            "halfway_error": lambda data: data["midpoint_motion"]["samples"][0].update(axis_probe_error_m=.0021),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                self.fixture.write("authoring/walk.sdk.json", original)
                self.fixture.mutate_sdk(mutation)
                self.assert_rejected()

    def test_localized_sdk_evidence_must_reference_candidate_body(self):
        self.fixture.add_localized()
        self.fixture.add_sdk()
        self.fixture.mutate_sdk(lambda data: data["input_receipt"].update(body_fbx_sha256=self.fixture.body_hash))
        self.assert_rejected(True)

    def test_copy_failure_rolls_back_unpublished_overlay(self):
        original = stage.shutil.copy2
        calls = 0

        def fail_second(source, target, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("deliberate temporary copy failure")
            return original(source, target, *args, **kwargs)

        with patch.object(stage.shutil, "copy2", fail_second):
            self.assert_rejected(expected=OSError)
        self.assertEqual(2, calls)

    def test_publication_failure_removes_staging_and_preserves_sources(self):
        with patch.object(stage, "publish_directory", side_effect=OSError("deliberate publication failure")):
            self.assert_rejected(expected=OSError)

    def test_source_change_during_copy_is_detected(self):
        fixture = self.fixture
        source = fixture.root / (UNIT + ".bones")
        original = stage.shutil.copy2
        changed = False

        def mutate_source(source_path, target, *args, **kwargs):
            nonlocal changed
            result = original(source_path, target, *args, **kwargs)
            if Path(source_path) == source:
                source.write_bytes(BONE_BYTES + b"\n// deliberate external mutation\n")
                changed = True
            return result

        with patch.object(stage.shutil, "copy2", mutate_source):
            with self.assertRaises(ValueError):
                fixture.run()
        self.assertTrue(changed)
        self.assertFalse(fixture.output.exists())
        self.assertEqual([], list((fixture.root / ".build").glob(".stage-animation-integration-*")))

    def test_publication_race_cannot_replace_existing_directory(self):
        fixture = self.fixture
        original = stage.publish_directory

        def race(staged, output):
            output.mkdir()
            (output / "winner.bin").write_bytes(b"concurrent winner")
            return original(staged, output)

        with patch.object(stage, "publish_directory", race):
            with self.assertRaises(ValueError):
                fixture.run()
        self.assertEqual(b"concurrent winner", (fixture.output / "winner.bin").read_bytes())
        self.assertEqual([], list((fixture.root / ".build").glob(".stage-animation-integration-*")))

    def test_duplicate_json_keys_are_rejected(self):
        self.fixture.plan_path.write_text('{"schema":1,"schema":1}', encoding="utf-8")
        with self.assertRaises(ValueError):
            stage.stage_integration(self.fixture.plan_path, self.fixture.root, self.fixture.output)
        self.assertFalse(self.fixture.output.exists())

    def test_create_plan_generates_complete_hashes_and_stages(self):
        fixture = self.fixture
        before = fixture.snapshot()
        receipt = fixture.create(states=("base/walk", "base/run"), resource_name="probe")
        plan_path = fixture.root / "authoring/generated-plan.json"
        plan = json.loads(plan_path.read_text())
        self.assertEqual(before, fixture.snapshot())
        self.assertEqual("validated-integration-plan-created", receipt["status"])
        self.assertEqual(digest(plan_path.read_bytes()), receipt["plan_sha256"])
        self.assertEqual(set(SOURCE_FILES), set(plan["source_files"]))
        for relative, expected in plan["source_files"].items():
            self.assertEqual(digest((fixture.root / relative).read_bytes()), expected)
        self.assertEqual(digest(fixture.rest_path.read_bytes()), plan["rest_manifest"]["sha256"])
        self.assertEqual(str(fixture.rest_path), plan["rest_manifest"]["path"])
        export = plan["authored_clips"]["probe"]
        self.assertEqual(RESOURCE_PREFIX + "probe", export["resource"])
        self.assertEqual(digest((fixture.root / "authoring/walk.export.json").read_bytes()), export["receipt_sha256"])
        self.assertEqual({state: {"clip": "probe", "aim_policy": "authored"}
                          for state in ("base/walk", "base/run")}, plan["states"])
        self.assertFalse(fixture.output.exists(), "Plan creation unexpectedly staged an overlay")
        staged = fixture.run(config_path=plan_path)
        self.assertEqual(["base/run", "base/walk"], staged["authored_states"])
        self.assertEqual([], list(plan_path.parent.glob(".plan-animation-integration-*")))

    def test_create_plan_can_pin_optional_sdk_and_gameplay_policy(self):
        fixture = self.fixture
        fixture.add_sdk()
        fixture.create(states=("base/shoot_start",), aim_policy="gameplay",
                       sdk_report=fixture.root / "authoring/walk.sdk.json")
        plan_path = fixture.root / "authoring/generated-plan.json"
        plan = json.loads(plan_path.read_text())
        export = plan["authored_clips"]["walk"]
        self.assertEqual(digest((fixture.root / "authoring/walk.sdk.json").read_bytes()), export["sdk_report_sha256"])
        self.assertEqual("gameplay", plan["states"]["base/shoot_start"]["aim_policy"])
        fixture.run(config_path=plan_path)
        self.assertTrue(parsed_states((fixture.output / (UNIT + ".state_machine")).read_text())["base/shoot_start"]["aim"])

    def test_create_plan_supports_explicit_localized_body_only(self):
        fixture = self.fixture
        fixture.add_localized()
        receipt = fixture.create(clip=None, states=(), body=fixture.root / "authoring/localized.fbx",
                                 offsets=fixture.root / "authoring/offsets.json", enable_localized=True)
        plan_path = fixture.root / "authoring/generated-plan.json"
        plan = json.loads(plan_path.read_text())
        self.assertEqual("localized-v1-runtime", receipt["profile_id"])
        self.assertEqual({}, plan["authored_clips"])
        self.assertEqual({}, plan["states"])
        self.assertIn("localized_profile", plan)
        fixture.run(True, config_path=plan_path)
        self.assertEqual(ASM_BYTES, (fixture.output / (UNIT + ".state_machine")).read_bytes())

    def test_create_plan_rejects_existing_plan_and_production_output(self):
        fixture = self.fixture
        before = fixture.snapshot()
        with self.assertRaises(ValueError):
            fixture.create(plan_path=fixture.plan_path)
        self.assertEqual(before, fixture.snapshot())
        for plan_path in (fixture.root / "units/new-plan.json", fixture.root / "authoring/not-json.txt"):
            with self.subTest(path=plan_path):
                with self.assertRaises(ValueError):
                    fixture.create(plan_path=plan_path)
                self.assertFalse(plan_path.exists())

    def test_create_plan_rejects_unvalidated_export_and_removes_temporary_plan(self):
        fixture = self.fixture
        fixture.mutate_receipt("walk", lambda data: data.update(status="pending"))
        before = fixture.snapshot()
        with self.assertRaises(ValueError):
            fixture.create()
        self.assertEqual(before, fixture.snapshot())
        self.assertFalse((fixture.root / "authoring/generated-plan.json").exists())
        self.assertEqual([], list((fixture.root / "authoring").glob(".plan-animation-integration-*")))

    def test_create_plan_rejects_bad_alias_death_and_duplicate_states(self):
        fixture = self.fixture
        for states in (("unknown",), ("attack_shoot_start",), ("base/death",), ("base/walk", "base/walk")):
            with self.subTest(states=states):
                with self.assertRaises(ValueError):
                    fixture.create(states=states)
                self.assertFalse((fixture.root / "authoring/generated-plan.json").exists())
                self.assertEqual([], list((fixture.root / "authoring").glob(".plan-animation-integration-*")))

    def test_create_plan_requires_complete_explicit_localized_inputs(self):
        fixture = self.fixture
        fixture.add_localized()
        body, offsets = fixture.root / "authoring/localized.fbx", fixture.root / "authoring/offsets.json"
        for options in ({"body": body, "offsets": offsets}, {"enable_localized": True},
                        {"enable_localized": True, "body": body}, {"enable_localized": True, "offsets": offsets}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    fixture.create(**options)
                self.assertFalse((fixture.root / "authoring/generated-plan.json").exists())

    def test_create_plan_publication_race_preserves_winning_plan(self):
        fixture = self.fixture
        plan_path = fixture.root / "authoring/generated-plan.json"
        real_prepare = stage.prepare_integration

        def race(*args, **kwargs):
            prepared = real_prepare(*args, **kwargs)
            plan_path.write_bytes(b"concurrent plan winner")
            return prepared

        with patch.object(stage, "prepare_integration", race):
            with self.assertRaises(FileExistsError):
                fixture.create()
        self.assertEqual(b"concurrent plan winner", plan_path.read_bytes())
        self.assertEqual([], list(plan_path.parent.glob(".plan-animation-integration-*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
