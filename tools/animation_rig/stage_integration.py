#!/usr/bin/env python3
"""Stage opt-in animation integration without editing shipping assets.

This stdlib tool consumes hash-pinned export receipts and a small JSON plan.
It creates a new isolated overlay under SOURCE/.build/animation_integration*.
It does not compile, publish, deploy, or modify the frozen artist package.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any

UNIT = "units/warlock_bombardier/warlock_bombardier_3p"
SAMPLER_STATE_MACHINE = UNIT + "/presentation_sampler"
RESOURCE_PACKAGE = "resource_packages/doomrocket/doomrocket.package"
MANIFEST = "scripts/mods/doomrocket/utils/doomrocket_animation_manifest.lua"
APPROVED_BODY_SHA = "cb2eba0224d1eff044a30b1bf0269d1a10395e8db9244af5c011e5c0ba0bd0bc"
APPROVED_BONES_SHA = "6e4eb323ba5a21db1e2f09f91d73cfa1e3234a03d7b183223f48ccd96c51a197"
APPROVED_REST_SHA = "b3da934daa268f11d5153cb06d581cfcf9cc2f61584b601fa72b7ec8378470c5"
APPROVED_EXPORTERS = {
    "1f4263bbe95299ac88aece4bf0b2e122fb98d2426a46fa1d84c25e24fc037f74",
    "501db4fbb8c48141b94e5efa74813516ea237cf9a608641799de2a500e81f1aa",
}
APPROVED_BODY_EXPORTERS = {
    "ca93a59cdf2d3ef7cbcc0abce21bf8249406a9f4f3e5074380ff9ef25287115d",
    "e493703735774ff9a9698e6378fdbb71bf9de49bb8ca7e45f073aa404c628977",
}
CLIPS = ("combat_idle", "combat_reload_loop", "combat_reload_start", "combat_run",
         "combat_run_start_fwd", "combat_shoot_loop", "combat_shoot_start", "combat_walk",
         "combat_wind_up_loop", "combat_wind_up_start", "death_shot", "stagger_bwd", "stagger_fwd")
RESERVED = ("j_whip_parent", "j_whip_dynamic", *(f"j_loot_sack_component{i}" for i in range(1, 6)))
SOURCE_FILES = tuple(UNIT + ext for ext in (".fbx", ".bones", ".unit", ".dcc_asset", ".state_machine")) + tuple(
    f"units/warlock_bombardier/anims/{clip}.{ext}" for clip in CLIPS for ext in ("fbx", "animation"))
REVIEWED_RESOURCE_PACKAGE = {
    "mod": ["doomrocket"],
    "package": ["resource_packages/doomrocket/doomrocket"],
    "lua": ["scripts/mods/doomrocket/*", "materials/*"],
    "material": ["materials/*"],
    "unit": ["units/*"],
    "state_machine": ["units/*"],
    "texture": ["textures/*"],
    "wwise_dep": ["wwise/*"],
    "network_config": ["scripts/mods/doomrocket/utils/*"],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + value)))


def digest_value(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), label + " must be lowercase SHA256")
    return value


def relative_path(root, relative):
    require(isinstance(relative, str), "Resource path must be text")
    part = PurePosixPath(relative)
    require(bool(relative) and not part.is_absolute() and ".." not in part.parts
            and "\\" not in relative and part.as_posix() == relative and ":" not in relative,
            "Unsafe relative path: " + relative)
    path = (root / relative).resolve()
    require(path.is_relative_to(root), "Path escapes its root: " + relative)
    return path


def input_path(base, value):
    require(isinstance(value, str) and value and not any(ord(c) < 32 for c in value), "Input path must be text")
    path = Path(value)
    return path.resolve() if path.is_absolute() else relative_path(base, value)


def pinned_input(base, value, expected, inputs):
    path = input_path(base, value)
    expected = digest_value(expected, "Input hash")
    require(path.is_file() and sha256(path) == expected, "Input hash mismatch: " + str(path))
    if path in inputs:
        require(inputs[path] == expected, "One input has contradictory hashes")
    inputs[path] = expected
    return path


@dataclass
class Node:
    value: Any
    start: int
    end: int
    fields: dict[str, "Node"] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)


class Sjson:
    """Strict span-preserving parser for the existing SDK object/array syntax."""
    token = re.compile(r'\s+|//[^\r\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}\[\]=,:;]|[^\s{}\[\]=,:;]+', re.S)

    def __init__(self, text):
        self.text, self.tokens, self.index = text, [], 0
        position = 0
        for match in self.token.finditer(text):
            require(match.start() == position, "Unrecognized SJSON token")
            position = match.end()
            token = match.group()
            if token.isspace() or token.startswith(("//", "/*")):
                continue
            self.tokens.append((token, match.start(), match.end()))
        require(position == len(text), "Unrecognized SJSON suffix")

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def take(self, expected=None):
        require(self.index < len(self.tokens), "Unexpected end of SJSON")
        result = self.tokens[self.index]
        self.index += 1
        require(expected is None or result[0] == expected, "Expected SJSON " + str(expected))
        return result

    def object(self, opening=False):
        start = self.take("{")[1] if opening else 0
        fields, values = {}, {}
        while self.peek() is not None and (not opening or self.peek() != "}"):
            if self.peek() in (",", ";"):
                self.take()
                continue
            key = self.take()[0]
            key = json.loads(key) if key.startswith('"') else key
            require(isinstance(key, str) and key not in fields, "Duplicate/invalid SJSON key: " + str(key))
            require(self.peek() in ("=", ":"), "SJSON assignment missing for " + key)
            self.take()
            fields[key] = self.value()
            values[key] = fields[key].value
        end = self.take("}")[2] if opening else len(self.text)
        return Node(values, start, end, fields=fields)

    def value(self):
        if self.peek() == "{":
            return self.object(True)
        if self.peek() == "[":
            start = self.take("[")[1]
            children = []
            while self.peek() != "]":
                require(self.peek() is not None, "Unterminated SJSON array")
                if self.peek() in (",", ";"):
                    self.take()
                else:
                    children.append(self.value())
            return Node([node.value for node in children], start, self.take("]")[2], children=children)
        token, start, end = self.take()
        if token.startswith('"'):
            value = json.loads(token)
        elif token in ("true", "false", "null"):
            value = {"true": True, "false": False, "null": None}[token]
        else:
            require(re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token),
                    "Unsupported bare SJSON value: " + token)
            value = float(token) if any(c in token for c in ".eE") else int(token)
        return Node(value, start, end)

    def parse(self):
        result = self.object()
        require(self.index == len(self.tokens), "Unexpected trailing SJSON")
        return result


def patches(text, replacements):
    last = len(text)
    for start, end, replacement in sorted(replacements, reverse=True):
        require(0 <= start <= end <= last, "Overlapping SJSON patch")
        text = text[:start] + replacement + text[end:]
        last = start
    return text


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def matrix(value):
    require(isinstance(value, list) and len(value) == 4 and all(isinstance(row, list) and len(row) == 4 for row in value)
            and all(finite(x) for row in value for x in row), "Invalid rest/offset matrix")
    require(max(abs(value[3][i] - (1 if i == 3 else 0)) for i in range(4)) <= 1e-8, "Non-affine matrix")
    return value


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]


def inverse3(a):
    c = [[a[(i+1)%3][(j+1)%3]*a[(i+2)%3][(j+2)%3] - a[(i+1)%3][(j+2)%3]*a[(i+2)%3][(j+1)%3]
          for j in range(3)] for i in range(3)]
    determinant = sum(a[0][j] * c[0][j] for j in range(3))
    require(finite(determinant) and determinant > 1e-10, "Rest basis must be positive handed and nonsingular")
    return [[c[j][i] / determinant for j in range(3)] for i in range(3)]


def rigid(rest):
    rest = matrix(rest)
    rotation = [row[:3] for row in rest[:3]]
    for _ in range(30):
        inv = inverse3(rotation)
        updated = [[.5 * (rotation[i][j] + inv[j][i]) for j in range(3)] for i in range(3)]
        error = max(abs(updated[i][j] - rotation[i][j]) for i in range(3) for j in range(3))
        rotation = updated
        if error < 1e-13:
            break
    require(error < 1e-10, "Rest polar normalization did not converge")
    return [rotation[i] + [rest[i][3]] for i in range(3)] + [[0., 0., 0., 1.]]


def inverse_rigid(value):
    return [[value[j][i] for j in range(3)] + [-sum(value[j][i] * value[j][3] for j in range(3))]
            for i in range(3)] + [[0., 0., 0., 1.]]


def validate_rest(receipt, rest, names):
    require(receipt.get("bone_names") == names, "Export must retain the exact ordered 138 shipping bones")
    contract = receipt.get("rest_contract")
    require(isinstance(contract, dict) and set(contract) == set(names), "Export rest contract is incomplete")
    for record in rest:
        actual = contract[record["name"]]
        require(actual.get("parent") == record["parent"] and actual.get("inherit_scale") == record["inherit_scale"],
                "Export parent/scale inheritance changed: " + record["name"])
        require(actual.get("use_local_location") is True and actual.get("use_inherit_rotation") is True,
                "Export shipping local/inheritance settings changed: " + record["name"])
        actual_matrix = matrix(actual.get("rest_matrix"))
        require(max(abs(actual_matrix[i][j] - record["rest"][i][j]) for i in range(4) for j in range(4)) <= 1e-6,
                "Export shipping rest matrix changed: " + record["name"])


def lua(value, depth=0):
    if isinstance(value, dict):
        return "{\n" + "".join("    " * (depth+1) + "[" + json.dumps(key) + "] = " + lua(item, depth+1) + ",\n"
                                    for key, item in sorted(value.items())) + "    " * depth + "}"
    if isinstance(value, list):
        return "{" + ", ".join(lua(item, depth) for item in value) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        require(all(ord(character) >= 32 for character in value), "Lua manifest contains a control character")
        return json.dumps(value, ensure_ascii=True)
    require(finite(value), "Unsupported Lua manifest value")
    return repr(value)


def validate_sdk_diagnostic(sdk, count, first_frame):
    require(sdk.get("schema") == 1 and sdk.get("diagnostic_status") == "sdk-compiled-and-decoded"
            and sdk.get("production_units_modified") is False, "Authored SDK diagnostic did not pass")
    for field in ("compiled_unit_sha256", "compiled_animation_sha256"):
        digest_value(sdk.get(field), field)
    animation, deformation = sdk.get("animation", {}), sdk.get("deformation", {})
    require(animation.get("fidelity_errors") == [] and deformation.get("fidelity_errors") == []
            and animation.get("bones") == 138 and animation.get("sampled_world_bone_comparisons") == count*138,
            "Authored SDK diagnostic coverage is incomplete")
    frames, skin = animation.get("frames"), deformation.get("pose_samples")
    require(isinstance(frames, list) and len(frames) == count and isinstance(skin, list) and len(skin) == count,
            "Authored SDK diagnostic must sample every authored frame")
    require(finite(deformation.get("tolerance_m")) and 0 < deformation["tolerance_m"] <= .002,
            "Authored SDK skin tolerance is invalid")
    def bounded(value, limit, label):
        require(finite(value) and 0 <= value <= limit, "Authored SDK fidelity failed: " + label)
    for key in ("max_world_head_error_m", "max_world_axis_probe_error_m"):
        bounded(animation.get(key), .002, key)
    bounded(deformation.get("max_weighted_skin_error_m"), deformation["tolerance_m"], "weighted skin")
    vertices = 0
    for index, (frame, pose) in enumerate(zip(frames, skin)):
        require(isinstance(frame, dict) and isinstance(pose, dict)
                and frame.get("frame") == first_frame+index and pose.get("frame") == first_frame+index,
                "Authored SDK frame numbering changed")
        for record in (frame, pose):
            require(finite(record.get("time")) and abs(record["time"]-index/60) <= 1e-6,
                    "Authored SDK frame timing changed")
        bounded(frame.get("head_error_m"), .002, "frame head")
        bounded(frame.get("axis_error_m"), .002, "frame axis")
        bounded(pose.get("max_weighted_skin_error_m"), deformation["tolerance_m"], "frame skin")
        require(type(pose.get("vertices")) is int and pose["vertices"] > 0, "Authored SDK skin sample is empty")
        vertices += pose["vertices"]
    require(deformation.get("weighted_comparisons") == vertices, "Authored SDK skin comparison count changed")
    halfway = sdk.get("midpoint_motion")
    if halfway is not None:
        require(isinstance(halfway, dict) and halfway.get("status") == "sdk-compiled-and-decoded"
                and halfway.get("fidelity_errors") == [] and halfway.get("pose_samples") == count-1
                and halfway.get("bone_comparisons") == (count-1)*138,
                "Authored SDK halfway pose coverage is incomplete")
        samples = halfway.get("samples")
        require(isinstance(samples, list) and len(samples) == count-1
                and finite(halfway.get("tolerance_m")) and 0 < halfway["tolerance_m"] <= .002,
                "Authored SDK halfway samples/tolerance changed")
        for key in ("max_head_error_m", "max_axis_probe_error_m"):
            bounded(halfway.get(key), halfway["tolerance_m"], key)
        for index, sample in enumerate(samples):
            require(isinstance(sample, dict) and finite(sample.get("time_seconds"))
                    and abs(sample["time_seconds"]-(index+.5)/60) <= 1e-6,
                    "Authored SDK halfway timing changed")
            bounded(sample.get("head_error_m"), halfway["tolerance_m"], "halfway head")
            bounded(sample.get("axis_probe_error_m"), halfway["tolerance_m"], "halfway axis")


def validate_export(base, spec, inputs, rest, names, body_hash, bones_hash,
                    selected_body_hash=None, rest_manifest_hash=None):
    receipt_path = pinned_input(base, spec.get("receipt"), spec.get("receipt_sha256"), inputs)
    receipt = read_json(receipt_path)
    require(receipt.get("schema") == 1 and receipt.get("status") == "fbx-roundtrip-passed", "Authored export has not passed FBX verification")
    require(receipt.get("export_script_sha256") in APPROVED_EXPORTERS, "Authored export uses an unreviewed exporter")
    fbx = pinned_input(base, spec.get("fbx"), receipt.get("fbx_sha256"), inputs)
    require(fbx.suffix.lower() == ".fbx", "Authored source must be an FBX")
    sidecar = pinned_input(base, str(fbx.with_suffix(".animation")), receipt.get("animation_sha256"), inputs)
    require(receipt.get("shipping_sha256") == body_hash and receipt.get("shipping_bones_sha256") == bones_hash,
            "Authored export references a different shipping body or skeleton")
    validate_rest(receipt, rest, names)
    side_data = Sjson(sidecar.read_text(encoding="utf-8")).parse().value
    require(side_data == {"bones": UNIT, "tolerance": {"": [0, 0, 0, False, False, False]}},
            "Authored sidecar must retain exact bones and zero-fitting/no-packing settings")
    # bool == 0 in Python: keep the six settings' actual types unambiguous.
    settings = side_data["tolerance"][""]
    require(all(type(value) in (int, float) and value == 0 for value in settings[:3])
            and all(value is False for value in settings[3:]), "Authored sidecar setting types changed")
    require(receipt.get("fps") == 60 and type(receipt.get("frame_start")) is int
            and type(receipt.get("frame_end")) is int and receipt["frame_end"] >= receipt["frame_start"],
            "Authored export must retain its validated 60 fps frame range")
    count = receipt["frame_end"] - receipt["frame_start"] + 1
    require(receipt.get("exported_frame_start") == 0 and receipt.get("exported_frame_end") == count-1,
            "Authored export frame origin changed")
    roundtrip = receipt.get("roundtrip", {})
    require(roundtrip.get("frames") == count and roundtrip.get("bones_per_frame") == 138
            and roundtrip.get("comparisons") == count * 138, "Authored export roundtrip coverage is incomplete")
    tolerance = receipt.get("position_tolerance_m")
    require(finite(tolerance) and 0 < tolerance <= 5e-5, "Authored export roundtrip tolerance is invalid")
    for key in ("max_rest_matrix_component_error", "max_head_error_m", "max_axis_tip_error_m"):
        require(finite(roundtrip.get(key)) and 0 <= roundtrip[key] <= tolerance, "Authored export fidelity failed: " + key)
    sdk = None
    require(bool(spec.get("sdk_report")) == bool(spec.get("sdk_report_sha256")), "SDK report and hash must be supplied together")
    if spec.get("sdk_report"):
        sdk_path = pinned_input(base, spec["sdk_report"], spec["sdk_report_sha256"], inputs)
        sdk = read_json(sdk_path)
        binding = sdk.get("input_receipt", {})
        validate_sdk_diagnostic(sdk, count, receipt["frame_start"])
        for field, expected in (("animation_fbx_sha256", inputs[fbx]), ("animation_sidecar_sha256", inputs[sidecar]),
                                ("animation_manifest_sha256", inputs[receipt_path]), ("shipping_fbx_sha256", body_hash),
                                ("shipping_bones_sha256", bones_hash)):
            require(binding.get(field) == expected, "Authored SDK receipt hash mismatch: " + field)
        require(binding.get("body_fbx_sha256") == (selected_body_hash or body_hash), "Authored SDK body hash differs from the staged profile")
        if rest_manifest_hash is not None:
            require(binding.get("skin_profile_sha256") == rest_manifest_hash, "Authored SDK rest/skin manifest hash differs")
    return {"fbx": fbx, "sidecar": sidecar, "receipt": receipt_path, "data": receipt, "sdk": sdk,
            "resource": spec.get("resource")}


def validate_localized(base, spec, inputs, rest, names, rest_manifest_hash, body_hash, bones_hash):
    require(isinstance(spec, dict), "Explicit localized profile requires its body and offsets")
    receipt_path = pinned_input(base, spec.get("body_receipt"), spec.get("body_receipt_sha256"), inputs)
    body_receipt = read_json(receipt_path)
    require(body_receipt.get("schema") == 1 and body_receipt.get("status") == "body-roundtrip-passed"
            and body_receipt.get("export_script_sha256") in APPROVED_BODY_EXPORTERS
            and body_receipt.get("weight_changes_only") is True
            and body_receipt.get("production_units_modified") is False
            and body_receipt.get("shipping_fbx_sha256") == body_hash, "Localized body has no validated weight-only shipping receipt")
    operation = body_receipt.get("weight_only_operation", {})
    semantic_hash = digest_value(operation.get("approved_non_weight_semantic_sha256"), "Body semantic hash")
    require(operation.get("candidate_non_weight_semantic_sha256") == semantic_hash,
            "Localized body changes shipping semantics beyond skin weights")
    geometry, roundtrip = body_receipt.get("approved_geometry_comparison", {}), body_receipt.get("roundtrip", {})
    copied_geometry = roundtrip.get("geometry", {})
    for field in ("vertices", "polygons", "loops", "uv_layers"):
        require(type(geometry.get(field)) is int and geometry[field] > 0
                and copied_geometry.get(field) == geometry[field], "Localized body geometry coverage changed: " + field)
    for comparison, vertex_limit in ((geometry, 1e-6), (copied_geometry, 5e-5)):
        for field, limit in (("max_vertex_error_source_units", vertex_limit), ("max_uv_error", 2e-6),
                             ("max_normal_component_error", 5e-5), ("max_mesh_transform_component_error", 2e-6)):
            require(finite(comparison.get(field)) and 0 <= comparison[field] <= limit,
                    "Localized body geometry changed: " + field)
    for field, limit in (("max_rest_matrix_component_error", 5e-5), ("max_weight_error", 2e-6), ("max_neutral_skin_error_m", 5e-5)):
        require(finite(roundtrip.get(field)) and 0 <= roundtrip[field] <= limit,
                "Localized body roundtrip fidelity failed: " + field)
    validate_rest(body_receipt, rest, names)
    body = pinned_input(base, spec.get("body"), body_receipt.get("fbx_sha256"), inputs)
    offsets_path = pinned_input(base, spec.get("offsets"), spec.get("offsets_sha256"), inputs)
    offsets = read_json(offsets_path)
    require(offsets.get("schema") == 1 and offsets.get("profile_id") == "localized-v1-runtime"
            and offsets.get("skin_profile") == "localized-v1" and offsets.get("unit_resource") == UNIT
            and offsets.get("reference_bone") == "j_hips"
            and offsets.get("shipping_body_sha256") == body_hash and offsets.get("shipping_bones_sha256") == bones_hash
            and offsets.get("rig_manifest_sha256") == rest_manifest_hash
            and offsets.get("rest_contract_sha256") == APPROVED_REST_SHA
            and offsets.get("candidate_body_receipt_sha256") == inputs[receipt_path], "Localized offset provenance differs from the reviewed body/rest")
    records = {record["name"]: record for record in rest}
    channels = offsets.get("channels", [])
    require([channel.get("bone") for channel in channels] == list(RESERVED), "Localized profile must use exactly seven ordered existing channels")
    inverse_hips = inverse_rigid(rigid(records["j_hips"]["rest"]))
    for channel in channels:
        require(set(channel) == {"bone", "parent", "bind_offset"}, "Unsupported localized channel fields")
        record = records[channel["bone"]]
        require(channel.get("parent") == record["parent"], "Localized channel parent changed")
        actual = matrix(channel.get("bind_offset"))
        expected = multiply(inverse_hips, rigid(record["rest"]))
        require(max(abs(actual[i][j] - expected[i][j]) for i in range(4) for j in range(4)) <= 1e-8,
                "Localized offset is not the verified rigid hips-relative rest: " + channel["bone"])
    return body, {"accessory_skin": "localized-v1", "native_bind_scale": 100,
                  "reference_bone": "j_hips", "channels": channels, "body_fbx_sha256": inputs[body],
                  "shipping_body_sha256": body_hash, "shipping_bones_sha256": bones_hash,
                  "rest_contract_sha256": APPROVED_REST_SHA}


def build_state_manifest(asm, mapping, exports, text, aim_policies=None):
    require(asm.value.get("bones") == UNIT, "ASM skeleton resource differs from the shipping unit")
    layers = asm.fields.get("layers")
    require(layers is not None and len(layers.children) == 1, "Only the reviewed single-layer ASM is supported")
    layer = layers.children[0]
    state_nodes = layer.fields["states"].children
    states = {node.value.get("name"): node for node in state_nodes}
    require(len(states) == len(state_nodes) and all(isinstance(name, str) for name in states), "ASM state names are duplicated")
    require(set(mapping).issubset(states), "Unknown state or event alias in authored state mapping")
    require("base/death" not in mapping, "Authored base/death playback is unsupported: live death uses PhysX bone ownership")
    events = asm.value.get("events", {})
    require(isinstance(events, dict), "ASM event registry is missing")
    replacements, manifest, used_events = [], {}, set()
    legacy_resources = {f"units/warlock_bombardier/anims/{clip}" for clip in CLIPS}
    for name, node in states.items():
        state = node.value
        require(state.get("state_type") == "regular" and state.get("root_driving") == "ignore"
                and isinstance(state.get("animations"), list) and len(state["animations"]) == 1
                and state["animations"][0] in legacy_resources and state.get("weights") == ["1.0"],
                "Mixed, aliased or unsupported ASM animation state: " + name)
        require(type(state.get("loop_animation")) is bool, "ASM loop_animation must be an actual boolean: " + name)
        require(isinstance(state.get("speed"), str) and state["speed"].strip()
                and all(ord(character) >= 32 for character in state["speed"]),
                "Invalid ASM speed expression: " + name)
        transition_map = {}
        require(isinstance(state.get("transitions", []), list), "Invalid ASM transition list")
        transition_nodes = node.fields.get("transitions")
        for transition_node in transition_nodes.children if transition_nodes is not None else ():
            transition = transition_node.value
            event = transition.get("event")
            require(event in events and event not in transition_map and transition.get("to") in states
                    and transition.get("mode") == "direct" and transition.get("on_beat") == ""
                    and finite(transition.get("blend_time")) and 0 <= transition["blend_time"] <= 1,
                    "Automatic, ambiguous or unsupported ASM transition: " + name)
            transition_map[event] = {"to": transition["to"], "blend_time": transition["blend_time"]}
            used_events.add(event)
        authored = name in mapping
        aim_policy = (aim_policies or {}).get(name, "authored")
        require(aim_policy in ("authored", "gameplay"), "Unknown authored aim policy")
        resource = exports[mapping[name]]["resource"] if authored else state["animations"][0]
        constraints = state.get("constraints", [])
        require(isinstance(constraints, list) and all(isinstance(item, str) for item in constraints), "Invalid ASM constraints")
        if authored:
            replacements.append((node.fields["animations"].start, node.fields["animations"].end, json.dumps([resource])))
            replacements.append((node.fields["speed"].start, node.fields["speed"].end, '"1"'))
            require(aim_policy != "gameplay" or "warlock_aim" in constraints,
                    "Gameplay aim policy requires the existing warlock_aim constraint: " + name)
            if aim_policy == "authored" and "warlock_aim" in constraints:
                replacements.append((node.fields["constraints"].start, node.fields["constraints"].end,
                                     json.dumps([item for item in constraints if item != "warlock_aim"])))
        manifest[name] = {"clip": resource, "owner": "authored" if authored else "legacy",
                          "speed": "authored" if authored else "measured",
                          "speed_expression": "1" if authored else state["speed"],
                          "loop_animation": state["loop_animation"],
                          "visible_aim": aim_policy == "gameplay" if authored else "warlock_aim" in constraints,
                          "transitions": transition_map}
        if authored:
            manifest[name]["aim_policy"] = aim_policy
    default = layer.value.get("default_state")
    require(default in states, "ASM default state is unknown")
    profile = {"unit": UNIT, "default_state": default, "states": manifest,
        "auxiliary_events": {event: True for event in sorted(set(events)-used_events)},
        "max_blend_time": max((edge["blend_time"] for state in manifest.values() for edge in state["transitions"].values()), default=0),
        "weapon_links": [{"target": 0, "source": "j_leftweaponattach", "world_scale": [1, 1, 1]},
                         {"target": "a_barrel", "source": "j_leftweaponcomponent1", "world_scale": [1, 1, 1]},
                         {"target": "handle", "source": "j_lefthand", "world_scale": [1, 1, 1]}]}
    profile["cross_owner_transition_policy"] = "snapshot-blend-v1"
    profile["sampler_state_machine"] = SAMPLER_STATE_MACHINE
    return patches(text, replacements), profile


def build_sampler_state_machine(visible_text):
    """Sample the exact destination clip without a second native crossfade.

    The helper is bound to a hidden clone of the existing outfit, never to a
    new unit or mesh. Only its transition durations differ from the visible
    state machine; runtime blends a frozen outgoing presentation pose.
    """
    asm = Sjson(visible_text).parse()
    require(asm.value.get("bones") == UNIT, "Sampler must use the existing own skeleton")
    layers = asm.fields.get("layers")
    require(layers is not None and len(layers.children) == 1, "Sampler requires the reviewed single layer")
    replacements = []
    for state in layers.children[0].fields["states"].children:
        transitions = state.fields.get("transitions")
        for transition in transitions.children if transitions is not None else ():
            value = transition.fields["blend_time"]
            if value.value != 0:
                replacements.append((value.start, value.end, "0"))
    return patches(visible_text, replacements)


def patch_unit(text, profile_id, manifest_id):
    unit = Sjson(text).parse()
    require(unit.value.get("animation_state_machine") == UNIT, "Unit does not use the reviewed own-skeleton ASM")
    values = {"warlock_rig_profile": profile_id, "warlock_animation_manifest_id": manifest_id}
    if "data" in unit.fields:
        data = unit.fields["data"]
        require(isinstance(data.value, dict) and not (set(data.value) & set(values)), "Unit already has conflicting integration markers")
        at = data.end-1
        addition = "\n" + "".join("    " + key + " = " + json.dumps(value) + "\n" for key, value in values.items())
        return patches(text, [(at, at, addition)])
    return text.rstrip() + "\ndata = {\n" + "".join("    " + key + " = " + json.dumps(value) + "\n" for key, value in values.items()) + "}\n"


def copy_verified(source, target, expected):
    require(sha256(source) == expected, "Source changed before copy: " + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    require(not target.exists(), "Staged resource already exists: " + str(target))
    shutil.copy2(source, target)
    require(sha256(source) == expected and sha256(target) == expected, "Source/payload changed during copy")


def publish_directory(staged, output):
    require(not output.exists(), "Integration output already exists; choose a new directory")
    if os.name == "nt":
        # MoveFileEx without replacement is atomic and refuses a race winner.
        os.rename(staged, output)
    else:
        # This tool is also useful on Linux. renameat2 provides the same
        # explicit no-replacement semantics for nonempty and empty directories.
        import ctypes
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        require(rename is not None, "This platform lacks atomic no-replacement directory publication")
        result = rename(-100, os.fsencode(staged), -100, os.fsencode(output), 1)
        if result:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))


def prepare_integration(config_path: Path, source_root: Path, enable_localized=False):
    """Validate all source and plan gates without creating staging resources."""
    config_path, source_root = config_path.resolve(), source_root.resolve()
    config = read_json(config_path)
    require(isinstance(config, dict) and config.get("schema") == 1
            and set(config) <= {"schema", "source_files", "rest_manifest", "authored_clips", "states", "localized_profile"},
            "Unsupported integration plan schema/fields")
    inputs = {config_path: sha256(config_path)}
    source_hashes = config.get("source_files")
    require(isinstance(source_hashes, dict) and set(source_hashes) == set(SOURCE_FILES),
            "Plan must pin the body/bones/unit/ASM/DCC and every shipping clip/sidecar")
    sources = {}
    for relative in SOURCE_FILES:
        path = relative_path(source_root, relative)
        sources[relative] = pinned_input(source_root, relative, source_hashes[relative], inputs)
    package_path = relative_path(source_root, RESOURCE_PACKAGE)
    require(package_path.is_file(), "Reviewed mod resource package is missing")
    package_bytes = package_path.read_bytes()
    package_hash = hashlib.sha256(package_bytes).hexdigest()
    require(Sjson(package_bytes.decode("utf-8")).parse().value == REVIEWED_RESOURCE_PACKAGE,
            "Unsupported mod resource package: reviewed unit/Lua/state_machine load globs are required")
    sources[RESOURCE_PACKAGE] = pinned_input(source_root, RESOURCE_PACKAGE, package_hash, inputs)
    body_hash, bones_hash = inputs[sources[UNIT+".fbx"]], inputs[sources[UNIT+".bones"]]
    require(body_hash == APPROVED_BODY_SHA and bones_hash == APPROVED_BONES_SHA, "Shipping source is not the approved Warlock body/skeleton")
    names = Sjson(sources[UNIT+".bones"].read_text(encoding="utf-8")).parse().value.get("bones")
    require(isinstance(names, list) and len(names) == 138 and len(set(names)) == 138, "Shipping skeleton must have exactly 138 unique names")
    rest_spec = config.get("rest_manifest", {})
    rest_path = pinned_input(config_path.parent, rest_spec.get("path"), rest_spec.get("sha256"), inputs)
    rest_manifest = read_json(rest_path)
    rest = rest_manifest.get("skeleton")
    require(isinstance(rest, list) and [record.get("name") for record in rest] == names
            and hashlib.sha256(canonical(rest)).hexdigest() == APPROVED_REST_SHA
            and rest_manifest.get("sources", {}).get("body_sha256") == body_hash,
            "Rest manifest must preserve the approved ordered shipping skeleton")
    for record in rest:
        matrix(record.get("rest"))
        require(record.get("parent") is None or record["parent"] in names, "Unknown shipping bone parent")
    localized = config.get("localized_profile")
    require(bool(localized) == bool(enable_localized), "Localized profile declaration requires explicit opt-in and its validated body")
    selected_body, accessory = (validate_localized(config_path.parent, localized, inputs, rest, names,
                                inputs[rest_path], body_hash, bones_hash) if enable_localized else
                                (sources[UNIT+".fbx"], {}))
    specs, declared_mapping = config.get("authored_clips"), config.get("states")
    require(isinstance(specs, dict) and isinstance(declared_mapping, dict) and (specs or enable_localized),
            "Plan requires opted-in authored clips or an explicit localized profile")
    mapping, aim_policies = {}, {}
    for state, declaration in declared_mapping.items():
        require(isinstance(state, str), "State mapping keys must be existing state names")
        if isinstance(declaration, str):
            mapping[state], aim_policies[state] = declaration, "authored"
        else:
            require(isinstance(declaration, dict) and set(declaration) <= {"clip", "aim_policy"}
                    and isinstance(declaration.get("clip"), str), "Unsupported authored state mapping schema")
            mapping[state] = declaration["clip"]
            aim_policies[state] = declaration.get("aim_policy", "authored")
            require(aim_policies[state] in ("authored", "gameplay"), "Unknown authored aim policy")
    require(set(mapping.values()) == set(specs), "Each authored clip must be mapped; unknown/unused clip IDs are forbidden")
    exports, resources, fbx_sources = {}, set(), set()
    for name, spec in specs.items():
        require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                and isinstance(spec, dict) and set(spec) <= {"fbx", "receipt", "receipt_sha256", "resource", "sdk_report", "sdk_report_sha256"},
                "Invalid authored clip identifier/schema")
        resource = spec.get("resource")
        require(isinstance(resource, str) and re.fullmatch(r"units/warlock_bombardier/anims/authored/[a-z0-9_/-]+", resource)
                and "." not in resource and resource not in resources, "Aliased or unsafe authored resource")
        relative_path(source_root / ".build", resource + ".fbx")
        require(not relative_path(source_root, resource + ".fbx").exists()
                and not relative_path(source_root, resource + ".animation").exists(), "Authored resource aliases an existing shipping resource")
        resources.add(resource)
        exports[name] = validate_export(config_path.parent, spec, inputs, rest, names, body_hash, bones_hash,
                                        inputs[selected_body], inputs[rest_path])
        require(exports[name]["fbx"] not in fbx_sources, "One authored source is aliased by multiple resources")
        fbx_sources.add(exports[name]["fbx"])
    asm_bytes, unit_bytes = sources[UNIT+".state_machine"].read_bytes(), sources[UNIT+".unit"].read_bytes()
    asm_text = asm_bytes.decode("utf-8")
    staged_asm, profile = build_state_manifest(Sjson(asm_text).parse(), mapping, exports, asm_text, aim_policies)
    existing_sampler = relative_path(source_root, SAMPLER_STATE_MACHINE + ".state_machine")
    if existing_sampler.exists():
        # The default stock-body native rehearsal deliberately uses this same
        # own-skeleton helper path. Permit only its complete reproducible text
        # contract, never an arbitrary helper/partial profile. The new overlay
        # writes its own matching helper; the shipping source remains untouched.
        import build_native_rehearsal as rehearsal
        for relative, expected in rehearsal.create(source_root).items():
            existing = relative_path(source_root, relative)
            require(existing.is_file() and existing.read_bytes() == expected,
                    "Presentation sampler aliases an existing source resource: unverified rehearsal " + relative)
            pinned_input(source_root, relative, hashlib.sha256(expected).hexdigest(), inputs)
        producer = Path(rehearsal.__file__).resolve()
        inputs[producer] = sha256(producer)
    sampler_asm = build_sampler_state_machine(staged_asm)
    profile["bone_names"] = list(names)
    profile.update(accessory)
    profile_id = "localized-v1-runtime" if enable_localized else "authored-v1-runtime"
    profile["validation"] = {"shipping_body_sha256": body_hash, "shipping_bones_sha256": bones_hash,
                             "rest_manifest_sha256": inputs[rest_path], "rest_contract_sha256": APPROVED_REST_SHA,
                             "source_state_machine_sha256": source_hashes[UNIT+".state_machine"],
                             "staged_state_machine_sha256": hashlib.sha256(staged_asm.encode("utf-8")).hexdigest(),
                             "sampler_state_machine_sha256": hashlib.sha256(sampler_asm.encode("utf-8")).hexdigest(),
                             "resource_package": RESOURCE_PACKAGE, "resource_package_sha256": package_hash,
                             "authored_exports": {name: {"resource": export["resource"], "fbx_sha256": inputs[export["fbx"]],
                                  "sidecar_sha256": inputs[export["sidecar"]], "receipt_sha256": inputs[export["receipt"]]}
                                                  for name, export in exports.items()}}
    payload = {"schema": 1, "profiles": {profile_id: profile}}
    manifest_id = hashlib.sha256(canonical(payload)).hexdigest()
    profile["manifest_id"] = manifest_id
    staged_unit = patch_unit(unit_bytes.decode("utf-8"), profile_id, manifest_id)
    return {"config": config, "inputs": inputs, "sources": sources, "source_hashes": source_hashes,
            "selected_body": selected_body, "exports": exports, "payload": payload,
            "manifest_id": manifest_id, "profile_id": profile_id, "staged_unit": staged_unit,
            "staged_asm": staged_asm, "sampler_asm": sampler_asm, "rest_path": rest_path, "mapping": mapping}


def stage_integration(config_path: Path, source_root: Path, output: Path, enable_localized=False):
    config_path, source_root, output = config_path.resolve(), source_root.resolve(), output.resolve()
    build_root = (source_root / ".build").resolve()
    require(build_root.parent == source_root and build_root == source_root / ".build",
            "The integration build directory must stay inside the source repository")
    require(output.parent == build_root and output.name.startswith("animation_integration")
            and output.name != "animation_integration" and not output.exists(),
            "Output must be a new .build/animation_integration... directory")
    require(not output.is_relative_to(source_root / "units"), "Production output is forbidden")
    prepared = prepare_integration(config_path, source_root, enable_localized)
    config, inputs, sources = prepared["config"], prepared["inputs"], prepared["sources"]
    source_hashes, selected_body, exports = prepared["source_hashes"], prepared["selected_body"], prepared["exports"]
    payload, manifest_id, profile_id = prepared["payload"], prepared["manifest_id"], prepared["profile_id"]
    staged_unit, staged_asm = prepared["staged_unit"], prepared["staged_asm"]
    rest_path, mapping = prepared["rest_path"], prepared["mapping"]
    specs, localized = config["authored_clips"], config.get("localized_profile")
    build_root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".stage-animation-integration-", dir=build_root)).resolve()
    require(staged.parent == build_root.resolve(), "Temporary output escaped the intended build directory")
    try:
        for relative, source in sources.items():
            if relative in (UNIT+".state_machine", UNIT+".unit", UNIT+".fbx"):
                continue
            copy_verified(source, relative_path(staged, relative), inputs[source])
        copy_verified(selected_body, relative_path(staged, UNIT+".fbx"), inputs[selected_body])
        for name, export in exports.items():
            for source, relative in ((export["fbx"], export["resource"]+".fbx"),
                                     (export["sidecar"], export["resource"]+".animation"),
                                     (export["receipt"], f"integration_evidence/{name}.export.json")):
                copy_verified(source, relative_path(staged, relative), inputs[source])
            spec = specs[name]
            if spec.get("sdk_report"):
                source = input_path(config_path.parent, spec["sdk_report"])
                copy_verified(source, relative_path(staged, f"integration_evidence/{name}.sdk.json"), inputs[source])
        copy_verified(rest_path, staged/"integration_evidence/rig_manifest.json", inputs[rest_path])
        copy_verified(config_path, staged/"integration_evidence/integration_plan.json", inputs[config_path])
        if enable_localized:
            for field, relative in (("body_receipt", "localized.body-export.json"), ("offsets", "localized.bind-offsets.json")):
                source = input_path(config_path.parent, localized[field])
                copy_verified(source, staged/"integration_evidence"/relative, inputs[source])
        generated = {
            UNIT + ".state_machine": staged_asm.encode("utf-8"),
            SAMPLER_STATE_MACHINE + ".state_machine": prepared["sampler_asm"].encode("utf-8"),
            UNIT + ".unit": staged_unit.encode("utf-8"),
            MANIFEST: ("-- Generated trusted integration manifest; no game acceptance implied.\nreturn " + lua(payload) + "\n").encode("utf-8"),
            "integration_manifest.json": (json.dumps(payload, indent=2, allow_nan=False)+"\n").encode("utf-8"),
        }
        for relative, contents in generated.items():
            generated_path = relative_path(staged, relative)
            generated_path.parent.mkdir(parents=True, exist_ok=True)
            generated_path.write_bytes(contents)
        for path, expected in inputs.items():
            require(sha256(path) == expected, "Input changed during staging: " + str(path))
        payload_files = {path.relative_to(staged).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
                         for path in sorted(staged.rglob("*")) if path.is_file()}
        for relative, contents in generated.items():
            require(payload_files[relative]["sha256"] == hashlib.sha256(contents).hexdigest(),
                    "Generated integration payload changed before publication: " + relative)
        require(payload_files[RESOURCE_PACKAGE]["sha256"] == inputs[sources[RESOURCE_PACKAGE]],
                "Reviewed resource package changed before publication")
        for clip in CLIPS:
            for extension in ("fbx", "animation"):
                relative = f"units/warlock_bombardier/anims/{clip}.{extension}"
                require(payload_files[relative]["sha256"] == source_hashes[relative], "A shipping clip/sidecar changed")
        receipt = {"schema": 1, "status": "isolated-integration-staged", "manifest_id": manifest_id,
                   "staging_script_sha256": sha256(Path(__file__)),
                   "profile_id": profile_id, "output": str(output), "localized_profile_opt_in": bool(enable_localized),
                   "cross_owner_transition_policy": payload["profiles"][profile_id].get("cross_owner_transition_policy"),
                   "sampler_state_machine": SAMPLER_STATE_MACHINE,
                   "resource_package": RESOURCE_PACKAGE,
                   "resource_package_sha256": inputs[sources[RESOURCE_PACKAGE]],
                   "sampler_resource_in_mod_package": True,
                   "all_visible_transition_blends_preserved": True,
                   "sampler_transition_blends_zero": True,
                   "sampler_presentation": "hidden existing-outfit clone; pure target sample, not a visible cut",
                   "same_owner_transition_blends_preserved": True,
                   "shipping_clips_and_sidecars_preserved": 26, "legacy_sources_unchanged": True,
                   "source_inputs_sha256": {str(path): value for path, value in inputs.items()},
                   "authored_states": sorted(mapping), "payload_files": payload_files,
                   "sdk_staged_unit_acceptance": "pending; optional prior SDK receipts only cover their original diagnostic inputs",
                   "native_pose_acceptance": "pending", "game_runtime_acceptance": "pending",
                   "production_assets_modified": False, "published": False}
        (staged/"integration_receipt.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
        publish_directory(staged, output)
        return receipt
    finally:
        if staged.exists():
            require(staged.resolve().parent == build_root.resolve()
                    and staged.name.startswith(".stage-animation-integration-"), "Unsafe temporary cleanup target")
            # Project rule: no recursive deletes. Keep the failed staging tree
            # under a .failed name in the ignored build directory for review.
            failed = staged.with_name(".failed-animation-integration-"
                                      + staged.name[len(".stage-animation-integration-"):])
            os.rename(staged, failed)
            print("WARLOCK_STAGING_FAILED_KEPT", failed)


def create_plan(plan_path: Path, source_root: Path, rest_manifest: Path, clip: Path | None = None,
                states=(), body: Path | None = None, offsets: Path | None = None,
                aim_policy="authored", resource_name=None, enable_localized=False, sdk_report: Path | None = None):
    """Make a new plan with automatic hashes, then run every staging input gate.

    This convenience path accepts one authored export mapped to one or more
    existing states. More complex mappings can use the same validated JSON schema.
    It never edits an existing plan or creates an integration overlay.
    """
    plan_path, source_root, rest_manifest = plan_path.resolve(), source_root.resolve(), rest_manifest.resolve()
    require(not plan_path.exists() and plan_path.suffix.lower() == ".json", "Plan must be a new JSON file")
    require("units" not in {part.lower() for part in plan_path.parts}, "Plan creation cannot write production units")
    require(aim_policy in ("authored", "gameplay"), "Unknown authored aim policy")
    require(bool(body) == bool(enable_localized) and bool(offsets) == bool(enable_localized),
            "Localized plan creation requires explicit opt-in, candidate body, and verified offsets")
    require(bool(clip) == bool(states) and (clip or enable_localized),
            "Plan creation requires an authored FBX and states, or an explicit localized body profile")
    require(sdk_report is None or clip is not None, "SDK evidence requires an authored clip")
    state_names = list(states)
    require(all(isinstance(state, str) for state in state_names) and len(state_names) == len(set(state_names)),
            "Repeated or invalid state mapping")
    plan = {"schema": 1, "source_files": {relative: sha256(relative_path(source_root, relative)) for relative in SOURCE_FILES},
            "rest_manifest": {"path": str(rest_manifest), "sha256": sha256(rest_manifest)},
            "authored_clips": {}, "states": {}}
    if clip is not None:
        clip = clip.resolve()
        require(clip.suffix.lower() == ".fbx", "Authored source must be an FBX")
        name = resource_name if resource_name is not None else clip.stem.lower()
        require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name),
                "Clip ID must use lowercase letters, digits and underscores")
        receipt = clip.with_suffix(".export.json")
        spec = {"fbx": str(clip), "receipt": str(receipt), "receipt_sha256": sha256(receipt),
                "resource": "units/warlock_bombardier/anims/authored/" + name}
        if sdk_report is not None:
            sdk_report = sdk_report.resolve()
            spec.update(sdk_report=str(sdk_report), sdk_report_sha256=sha256(sdk_report))
        plan["authored_clips"][name] = spec
        plan["states"] = {state: {"clip": name, "aim_policy": aim_policy} for state in state_names}
    if enable_localized:
        body, offsets = body.resolve(), offsets.resolve()
        receipt = body.with_suffix(".body-export.json")
        plan["localized_profile"] = {"body": str(body), "body_receipt": str(receipt),
            "body_receipt_sha256": sha256(receipt), "offsets": str(offsets), "offsets_sha256": sha256(offsets)}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".plan-animation-integration-", suffix=".json", dir=plan_path.parent)
    temporary = Path(temporary_name).resolve()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(plan, stream, indent=2, allow_nan=False)
            stream.write("\n")
        prepared = prepare_integration(temporary, source_root, enable_localized)
        for path, expected in prepared["inputs"].items():
            require(sha256(path) == expected, "Input changed during plan creation: " + str(path))
        if os.name == "nt":
            os.rename(temporary, plan_path)  # Atomic, no replacement on Windows.
        else:
            os.link(temporary, plan_path)  # Atomic exclusive publication on the same volume.
            temporary.unlink()
        return {"schema": 1, "status": "validated-integration-plan-created", "plan": str(plan_path),
                "staging_script_sha256": sha256(Path(__file__)),
                "plan_sha256": sha256(plan_path), "profile_id": prepared["profile_id"],
                "authored_states": sorted(state_names), "shipping_files_pinned": len(SOURCE_FILES),
                "resource_package_sha256": prepared["payload"]["profiles"][prepared["profile_id"]]["validation"]["resource_package_sha256"],
                "localized_profile_opt_in": bool(enable_localized), "integration_staged": False}
    finally:
        if temporary.exists():
            require(temporary.parent == plan_path.parent and temporary.name.startswith(".plan-animation-integration-"),
                    "Unsafe temporary plan cleanup target")
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--plan", type=Path, help="Stage an existing validated JSON plan")
    operation.add_argument("--create-plan", type=Path, help="Create and validate a new plan; no overlay is staged")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, help="New .build/animation_integration... directory")
    parser.add_argument("--enable-localized-profile", action="store_true")
    parser.add_argument("--rig-manifest", type=Path)
    parser.add_argument("--clip", type=Path)
    parser.add_argument("--clip-id")
    parser.add_argument("--state", action="append", default=[])
    parser.add_argument("--aim-policy", choices=("authored", "gameplay"), default="authored")
    parser.add_argument("--body", type=Path)
    parser.add_argument("--offsets", type=Path)
    parser.add_argument("--sdk-report", type=Path)
    args = parser.parse_args()
    if args.create_plan:
        require(args.rig_manifest is not None and args.output is None, "Plan creation requires --rig-manifest and no --output")
        receipt = create_plan(args.create_plan, args.source_root, args.rig_manifest, args.clip, args.state,
                              args.body, args.offsets, args.aim_policy, args.clip_id, args.enable_localized_profile, args.sdk_report)
    else:
        require(args.output is not None, "Staging requires --output")
        require(not any((args.rig_manifest, args.clip, args.clip_id, args.state, args.body, args.offsets, args.sdk_report))
                and args.aim_policy == "authored", "Creation-only options cannot change an existing staging plan")
        receipt = stage_integration(args.plan, args.source_root, args.output, args.enable_localized_profile)
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"source_inputs_sha256", "payload_files"}}, indent=2))


if __name__ == "__main__":
    main()
