"""Build/check the opt-in stock-asset native-controller rehearsal.

This never edits an artist asset, shipping Unit/ASM, original clip or default
manifest. It reuses the actual integration graph builders, with the existing
idle resource classified as authored strictly for a controller/clock rehearsal.
It is not Blender-export or localized garment acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import stage_integration as stage

ROOT = Path(__file__).resolve().parents[2]
UNIT = stage.UNIT
VISIBLE = UNIT + "/native_controller_rehearsal"
SAMPLER = stage.SAMPLER_STATE_MACHINE
PROFILE = "native-controller-rehearsal-v1"
COMPANION = "scripts/mods/doomrocket/utils/doomrocket_native_rehearsal_manifest.lua"
CONTRACT = "tools/fixtures/native_animation_rehearsal.json"
REHEARSAL_CLIP = "units/warlock_bombardier/anims/combat_idle"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def create(root=ROOT, *, with_manifest=False):
    """Return deterministic engineering text outputs; all original inputs read-only."""
    root = Path(root)
    source = (root / (UNIT + ".state_machine")).read_text(encoding="utf8")
    parsed = stage.Sjson(source).parse()
    visible, profile = stage.build_state_manifest(parsed, {"base/idle": "existing_idle"},
        {"existing_idle": {"resource": REHEARSAL_CLIP}}, source)
    sampler = stage.build_sampler_state_machine(visible)
    bones = re.findall(r'"([^"\n]+)"', (root / (UNIT + ".bones")).read_text())
    require(len(bones) == len(set(bones)) == 138, "Rehearsal requires the exact 138 ordered bones")
    require(stage.sha256(root / (UNIT + ".fbx")) == stage.APPROVED_BODY_SHA,
            "Rehearsal must use the unchanged shipping body")
    require(stage.sha256(root / (UNIT + ".bones")) == stage.APPROVED_BONES_SHA,
            "Rehearsal must use the unchanged shipping skeleton")
    original = parsed.value["layers"][0]["states"]
    changed = stage.Sjson(visible).parse().value["layers"][0]["states"]
    helper = stage.Sjson(sampler).parse().value["layers"][0]["states"]
    require(len(original) == len(changed) == len(helper) == 12, "Rehearsal graph inventory changed")
    edges = 0
    for old, new, pure in zip(original, changed, helper):
        require(old["name"] == new["name"] == pure["name"], "Rehearsal reordered states")
        require(old["animations"] == new["animations"], "Rehearsal changed an animation resource")
        require(old["transitions"] == new["transitions"], "Rehearsal changed a visible transition")
        edges += len(old["transitions"])
        expected = dict(old)
        if old["name"] == "base/idle":
            expected["constraints"] = [x for x in old["constraints"] if x != "warlock_aim"]
            expected["speed"] = "1"
        require(new == expected, "Rehearsal changed unsupported state fields")
        pure_expected = dict(new)
        pure_expected["transitions"] = [dict(edge, blend_time=0) for edge in new["transitions"]]
        require(pure == pure_expected, "Rehearsal sampler changed more than edge duration")
    require(edges == 154, "Rehearsal must retain all 154 visible transition durations")
    inputs = {path: stage.sha256(root / path) for path in
              (*stage.SOURCE_FILES, stage.RESOURCE_PACKAGE)}
    text_outputs = {VISIBLE + ".state_machine": visible.encode("utf8"),
                    SAMPLER + ".state_machine": sampler.encode("utf8")}
    profile.update({"bone_names": bones, "native_rehearsal_only": True,
        "visible_state_machine": VISIBLE,
        "validation": {"scope": "existing-stock-clip-native-controller-rehearsal",
            "artist_export_acceptance": False, "localized_garment_acceptance": False,
            "source_files_sha256": inputs,
            "visible_state_machine_sha256": sha(text_outputs[VISIBLE + ".state_machine"]),
            "sampler_state_machine_sha256": sha(text_outputs[SAMPLER + ".state_machine"])}})
    payload = {"schema": 1, "profiles": {PROFILE: profile}}
    ident = sha(stage.canonical(payload))
    profile["manifest_id"] = ident
    text_outputs[COMPANION] = ("-- Generated opt-in existing-clip native controller rehearsal; not artist export acceptance.\nreturn "
                               + stage.lua(payload) + "\n").encode("utf8")
    contract = {"schema": 1, "scope": "existing-stock-clip-native-controller-rehearsal",
        "profile_id": PROFILE, "manifest_id": ident, "unit": UNIT,
        "visible_state_machine": VISIBLE, "sampler_state_machine": SAMPLER,
        "stock_assets_unchanged": True, "existing_clip": REHEARSAL_CLIP,
        "authored_states": ["base/idle"], "ordered_bones": 138,
        "visible_transition_durations_preserved": edges, "sampler_zero_edges": edges,
        "artist_export_acceptance": False, "localized_garment_acceptance": False,
        "source_files_sha256": inputs,
        "generated_files_sha256": {path: sha(data) for path, data in text_outputs.items()}}
    text_outputs[CONTRACT] = (json.dumps(contract, indent=2) + "\n").encode("utf8")
    return (text_outputs, payload) if with_manifest else text_outputs


def verify_controllers(baseline_payload, visible_payload, helper_payload, bones, manifest):
    """Decode real compiled graphs; only idle ownership/aim/speed may differ."""
    import compiled_integration as compiled
    from test_warlock_weapon_pipeline import murmur64a
    from test_doomrocket_visible_aim import verify_aim
    baseline, old = compiled.state_bindings(baseline_payload)
    visible, new = compiled.state_bindings(visible_payload)
    helper, pure = compiled.state_bindings(helper_payload)
    profile = manifest["profiles"][PROFILE]
    expected_states = {murmur64a(name.encode()): name for name in profile["states"]}
    require(set(old) == set(new) == set(pure) == set(expected_states), "Compiled rehearsal changed state inventory")
    require(len(bones) == 138 and list(bones) == profile["bone_names"], "Compiled rehearsal skeleton differs")
    for graph in (baseline, visible, helper):
        verify_aim(graph, tuple(bones))
    count = 0
    for ident, name in expected_states.items():
        expected = dict(old[ident])
        if name == "base/idle":
            expected["constraints"] = ()
        require(new[ident] == expected, "Compiled rehearsal changed clip/edge/aim: " + name)
        require(new[ident]["animations"] == (murmur64a(profile["states"][name]["clip"].encode()),),
                "Compiled rehearsal clip differs from manifest")
        count += len(new[ident]["transitions"])
    require(count == 154 and compiled.verify_sampler_states(new, pure) == 154,
            "Compiled rehearsal visible/helper edge coverage differs")
    return {"status": "compiled-native-rehearsal-controller-contract-passed", "states": len(new),
            "ordered_bones": len(bones), "visible_edges_preserved": count, "sampler_zero_edges": count,
            "native_pose_samples": 0, "artist_export_acceptance": False, "localized_garment_acceptance": False}


def verify_bundle(resources, root=ROOT):
    """Check the actual canonical built mod package, never just loose SDK files."""
    sys.path.insert(0, str(ROOT / "tools/tests"))
    from test_warlock_weapon_pipeline import resource_key
    from test_doomrocket_visible_aim import compiled_bones
    from compiled_lua_table import verify_manifest
    from package_closure import require_members
    from verify_compiled_animation import decode_animation

    def resource(kind, name):
        hits = resources.get(resource_key(kind, name), [])
        require(len(hits) == 1, "Missing/duplicate compiled rehearsal resource: " + kind + ":" + name)
        return hits[0][1]

    _, manifest = create(root, with_manifest=True)
    profile = manifest["profiles"][PROFILE]
    from compiled_integration import unit_metadata
    metadata = unit_metadata(resource("unit", UNIT))
    require(metadata["asm"] == UNIT and metadata["data"] == {},
            "Default compiled stock Unit was globally activated or marked")
    bones = compiled_bones(resource("bones", UNIT))
    result = verify_controllers(resource("state_machine", UNIT), resource("state_machine", VISIBLE),
                                resource("state_machine", SAMPLER), bones, manifest)
    companion = verify_manifest(resource("lua", COMPANION.removesuffix(".lua")), manifest,
                                "@" + COMPANION)
    required = [("unit", UNIT), ("state_machine", UNIT), ("state_machine", VISIBLE),
                ("state_machine", SAMPLER), ("lua", COMPANION.removesuffix(".lua"))]
    referenced = sorted({state["clip"] for state in profile["states"].values()})
    required += [("animation", name) for name in referenced]
    for name in referenced:
        animation = decode_animation(resource("animation", name))
        require(animation["bones"] == 138, "Compiled rehearsal animation lost original tracks")
    members = require_members(resource("package", stage.RESOURCE_PACKAGE.removesuffix(".package")), required)
    result.update({"compiled_package_members": members, "required_loaded_resources": len(required),
                   "original_referenced_animation_resources": len(referenced),
                   "compiled_companion": companion})
    return result


def run(root=ROOT, write=False):
    outputs = create(root)
    for relative, data in outputs.items():
        path = Path(root) / relative
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        else:
            require(path.is_file() and path.read_bytes() == data,
                    "Native rehearsal generated contract differs: " + relative)
    return {"status": "native-rehearsal-source-contract-passed", "files": len(outputs),
            "stock_assets_modified": False, "native_pose_samples": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate only the four engineering text outputs")
    parser.add_argument("--compiled", action="store_true", help="Also verify actual canonical bundle package/graphs/manifest")
    args = parser.parse_args()
    print(json.dumps(run(write=args.write)))
    if args.compiled:
        sys.path.insert(0, str(ROOT / "tools/tests"))
        from test_warlock_weapon_pipeline import compiled_bundle_resources
        print(json.dumps(verify_bundle(compiled_bundle_resources())))


if __name__ == "__main__":
    main()
