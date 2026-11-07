"""Adapt only seven dormant shipping tracks for the corrective-weight body.

Run in Blender 5.2. This uses Blender's official FBX transform evaluator and
exporter to avoid hand-written Maya/Blender Euler conversion. Only the seven
reserved channels are transplanted into the original binary FBX; all other
property payloads, model defaults, object IDs, connections, bind data, geometry,
skin, and the calibrated aim helper remain byte-identical. Changed curve sizes
require rebuilding binary node offsets. Fresh FBX imports verify the final
poses at the calibrated target sampling rate (at least 60 samples per second,
240 for fast death/stagger clips), with an additional probe between every
corrective key, before output is accepted.

Engine candidates require --native-targets: the seven correction locals must
cancel the SDK-compressed shipping parent motion. Raw FBX pelvis calibration
is retained only as a Blender comparison mode and makes no native fit claim.

These are isolated candidate clips. Never overwrite production animations.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
import tempfile

import bpy
from mathutils import Matrix
from io_scene_fbx import encode_bin, parse_fbx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_animation as bridge
from accessory_weights import BELT_BONES, COAT_BONES

RESERVED = COAT_BONES + BELT_BONES
TICKS_PER_SECOND = 46186158000
EXPECTED_CLIPS = {
    "combat_idle", "combat_reload_loop", "combat_reload_start", "combat_run",
    "combat_run_start_fwd", "combat_shoot_loop", "combat_shoot_start",
    "combat_walk", "combat_wind_up_loop", "combat_wind_up_start", "death_shot",
    "stagger_bwd", "stagger_fwd",
}


def decoded(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def model_name(elem):
    value = decoded(elem.props[1]).split("\x00", 1)[0]
    return value.split("::", 1)[-1].removeprefix("Model")


def child(elem, name):
    matches = [e for e in elem.elems if e.id == name]
    bridge.require(len(matches) == 1, f"Expected one {name!r} child of {elem.id!r}")
    return matches[0]


class RawFbx:
    """Retain original encoded property bytes while using the official parser."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.root, self.version = parse_fbx.parse(str(self.path))
        self.header_size = 27
        self.meta_format = "<QQQB" if self.version >= 7500 else "<IIIB"
        self.meta_size = struct.calcsize(self.meta_format)
        self.raw = {}
        self._read_locations(self.header_size, self.root.elems)
        self.objects = {
            elem.props[0]: elem for elem in child(self.root, b"Objects").elems
            if elem.props
        }
        self.connections = [elem.props for elem in child(self.root, b"Connections").elems]
        self.models = {model_name(e): e for e in self.objects.values() if e.id == b"Model"}

    def _read_locations(self, offset, elements):
        for elem in elements:
            end, count, length, name_length = struct.unpack_from(self.meta_format, self.data, offset)
            at = offset + self.meta_size + name_length
            start = at
            properties = []
            for _ in range(count):
                begin = at
                kind = chr(self.data[at])
                at += 1
                if kind in "YCFDLI":
                    at += {"Y": 2, "C": 1, "F": 4, "D": 8, "L": 8, "I": 4}[kind]
                elif kind in "SR":
                    size = struct.unpack_from("<I", self.data, at)[0]
                    at += 4 + size
                elif kind in "fdlibc":
                    _, _, size = struct.unpack_from("<III", self.data, at)
                    at += 12 + size
                else:
                    raise ValueError(f"Unknown FBX property encoding {kind!r}")
                properties.append(self.data[begin:at])
            bridge.require(at - start == length and count == len(elem.props), "FBX property layout mismatch")
            self.raw[id(elem)] = properties
            self._read_locations(at, elem.elems)
            offset = end

    def encoded(self, elem, replacements):
        result = encode_bin.FBXElem(elem.id)
        properties = self.raw[id(elem)]
        result.props_type = bytearray(p[0] for p in properties)
        result.props = [p[1:] for p in properties]
        if id(elem) in replacements:
            donor, donor_elem = replacements[id(elem)]
            result.elems = [donor.encoded(e, {}) for e in donor_elem.elems]
        else:
            result.elems = [self.encoded(e, replacements) for e in elem.elems]
        return result

    def serialized(self, replacements=None):
        encode_bin.init_version(self.version)
        root = encode_bin.FBXElem(b"")
        root.elems = [self.encoded(e, replacements or {}) for e in self.root.elems]
        stream = io.BytesIO()
        stream.write(self.data[:self.header_size])
        root._calc_offsets_children(stream.tell(), False)
        root._write_children(stream.write, stream.tell, False)
        stream.write(encode_bin._FOOT_ID)
        stream.write(b"\x00" * 4)
        padding = ((stream.tell() + 15) & ~15) - stream.tell()
        stream.write(b"\x00" * (padding or 16))
        stream.write(struct.pack("<I", self.version))
        stream.write(b"\x00" * 120)
        stream.write(b"\xf8\x5a\x8c\x6a\xde\xf5\xd9\x7e\xec\xe9\x0c\xe3\x75\x8f\x29\x0b")
        return stream.getvalue()

    def channels(self, bone):
        bridge.require(bone in self.models, "Clip missing model " + bone)
        model = self.models[bone]
        tracks = {}
        for row in self.connections:
            if len(row) == 4 and row[0] == b"OP" and row[2] == model.props[0]:
                property_name = decoded(row[3])
                bridge.require(property_name in {"Lcl Translation", "Lcl Rotation", "Lcl Scaling"},
                               f"Unknown animated property for {bone}: {property_name}")
                bridge.require(property_name not in tracks, "Duplicated bone curve node")
                node = self.objects[row[1]]
                bridge.require(node.id == b"AnimationCurveNode", "Expected animation curve node")
                axes = {}
                for axis_row in self.connections:
                    if len(axis_row) == 4 and axis_row[0] == b"OP" and axis_row[2] == node.props[0]:
                        axis = decoded(axis_row[3])
                        bridge.require(axis in {"d|X", "d|Y", "d|Z"} and axis not in axes,
                                       "Unknown or duplicated animation axis")
                        axes[axis] = self.objects[axis_row[1]]
                        bridge.require(axes[axis].id == b"AnimationCurve", "Expected animation curve")
                bridge.require(set(axes) == {"d|X", "d|Y", "d|Z"}, "Incomplete bone channel")
                tracks[property_name] = (node, axes)
        bridge.require(set(tracks) == {"Lcl Translation", "Lcl Rotation", "Lcl Scaling"},
                       "Incomplete TRS channels for " + bone)
        return tracks

    def except_reserved_digest(self):
        curves, curve_nodes = set(), set()
        for name in RESERVED:
            for node, axes in self.channels(name).values():
                curves.update(curve.props[0] for curve in axes.values())
                curve_nodes.add(node.props[0])
        digest = hashlib.sha256()

        def walk(elem):
            digest.update(elem.id)
            for prop in self.raw[id(elem)]:
                digest.update(struct.pack("<I", len(prop)))
                digest.update(prop)
            if elem.id == b"AnimationCurve" and elem.props[0] in curves:
                return
            for sub in elem.elems:
                if elem.id == b"AnimationCurveNode" and elem.props[0] in curve_nodes and sub.id == b"Properties70":
                    continue
                walk(sub)
        for elem in self.root.elems:
            walk(elem)
        return digest.hexdigest()


def frame_set_seconds(scene, seconds, fps):
    frame = seconds * fps
    whole = math.floor(frame)
    scene.frame_set(whole, subframe=frame - whole)
    bpy.context.view_layer.update()


def load_native_targets(path, source_body, body, names):
    """Bind SDK-decoded samples to the exact shipping sources and bone bases."""
    document = json.loads(path.read_text(encoding="utf-8"))
    bridge.require(document.get("schema") == 1 and
                   document.get("status") == "decoded-shipping-hip-targets",
                   "Unknown native target schema/status")
    bridge.require(document["shipping_body_sha256"] == bridge.sha256(source_body),
                   "Native targets belong to a different shipping body")
    bridge.require(document["shipping_bones_sha256"] == bridge.sha256(bridge.BONES_PATH),
                   "Native targets belong to a different shipping bones contract")
    bridge.require(set(document["rest_contract"]) == set(names), "Native target skeleton differs")
    for name in names:
        bone = body.data.bones[name]
        reference = document["rest_contract"][name]
        bridge.require(reference["parent"] == (bone.parent.name if bone.parent else None),
                       "Native target bone parent changed: " + name)
        bridge.require(bridge.matrix_error(Matrix(reference["rest_matrix"]), bone.matrix_local) <= 5e-5,
                       "Native target bone coordinate basis changed: " + name)
    clips = {clip["clip"]: clip for clip in document["clips"]}
    bridge.require(len(clips) == 13 and {Path(name).stem for name in clips} == EXPECTED_CLIPS,
                   "Native target clip inventory differs")
    provenance = {key: value for key, value in document.items() if key not in {"clips", "rest_contract"}}
    provenance["targets_sha256"] = bridge.sha256(path)
    for clip in clips.values():
        samples = clip["samples"]
        fps = clip["sample_fps"]
        bridge.require(fps in {60, 120, 240, 480, 960} and len(samples) >= 2,
                       "Invalid native target timeline")
        bridge.require(len(clip.get("midpoint_samples", [])) == len(samples) - 1,
                       "Native targets must include every between-key sample")
        for collection, phase in ((samples, 0.0), (clip["midpoint_samples"], 0.5)):
            for index, sample in enumerate(collection):
                bridge.require(abs(sample["seconds"] - (index + phase) / fps) < 1e-9,
                               "Native target timeline is not continuous")
                bridge.require(set(sample["reserved_local"]) == set(RESERVED),
                               "Native targets contain unknown/missing correction channels")
                for name in RESERVED:
                    bridge.validate_matrix(Matrix(sample["reserved_local"][name]),
                                           "native local target " + name)
        clip["native_calibration"] = {**provenance,
            "source_fbx_sha256": clip["source_fbx_sha256"],
            "source_sidecar_sha256": clip["source_sidecar_sha256"],
            "compiled_animation_sha256": clip["compiled_animation_sha256"],
            "pose_validation_space": "parent-local against SDK-compressed shipping parents",
            "compiled_world_acceptance": "pending separate fixed-2mm SDK verification"}
    return clips, provenance


def native_sidecar(sidecar_bytes):
    """Keep the shipping default and disable fitting/packing only for seven bones."""
    source_text = sidecar_bytes.decode("utf-8")
    block = re.search(r'tolerance\s*=\s*\{(.*?)\}', source_text, re.S)
    bridge.require(block is not None, "Shipping sidecar has no tolerance map")
    default = re.fullmatch(r'\s*""\s*=\s*\[([^\]]+)\]\s*', block.group(1))
    bridge.require(default is not None, "Only the audited shipping default tolerance map is supported")
    fields = default.group(1).split()
    bridge.require(len(fields) == 4 and tuple(map(float, fields[:3])) == (0.00001, 0.01, 0.0)
                   and fields[3] == "false", "Shipping default compression policy changed")
    overrides = "".join('    "' + name + '" = [ 0 0 0 false false false ]\n' for name in RESERVED)
    return (source_text[:block.end(1)] + overrides + source_text[block.end(1):]).encode("utf-8")


def world_samples(scene, game, names, count, fps, offsets, sample_fps, native=None):
    samples = []
    chain = bridge.parent_chain(game)
    for frame in range(count):
        frame_set_seconds(scene, frame / sample_fps, fps)
        graph = bpy.context.evaluated_depsgraph_get()
        evaluated = game.evaluated_get(graph)
        worlds = {name: evaluated.matrix_world @ evaluated.pose.bones[name].matrix for name in names}
        original = {name: value.copy() for name, value in worlds.items()}
        if native is None:
            for name in RESERVED:
                worlds[name] = worlds["j_hips"] @ offsets[name]
        else:
            # Preserve source parent tracks. The corrected local matrices were
            # calculated from compressed SDK parents; their world appearance in
            # a raw FBX viewer deliberately differs slightly from native output.
            for name in RESERVED:
                parent = game.data.bones[name].parent.name
                worlds[name] = worlds[parent] @ Matrix(native["samples"][frame]["reserved_local"][name])
        samples.append({"frame": frame, "seconds": frame / sample_fps, "object": evaluated.matrix_world.copy(),
                        "wrappers": [obj.evaluated_get(graph).matrix_world.copy() for obj in chain],
                        "bones": worlds, "original": original})
    return chain, samples


def compare_native_local(scene, game, targets, tolerance):
    """Verify final FBX locals against actual SDK targets, without a raw-hip claim."""
    bridge.select_scene(scene)
    fps = scene.render.fps / scene.render.fps_base
    maximum = 0.0
    worst = None
    for sample in targets:
        frame_set_seconds(scene, sample["seconds"], fps)
        evaluated = game.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name in RESERVED:
            bone = evaluated.pose.bones[name]
            actual = bone.parent.matrix.inverted() @ bone.matrix
            expected = Matrix(sample["reserved_local"][name])
            error = max((a - b).length for a, b in zip(bridge.probe_points(actual),
                                                     bridge.probe_points(expected)))
            if error > maximum:
                maximum = error
                worst = {"bone": name, "seconds": sample["seconds"], "error_m": error}
    bridge.require(maximum <= tolerance, f"Native parent-local FBX error exceeds {tolerance} m: {worst}")
    return {"comparisons": len(targets) * len(RESERVED),
            "max_head_or_axis_tip_error_m": maximum, "tolerance_m": tolerance,
            "space": "parent-local metres", "worst": worst}


def donor_bake_names(game, names):
    """Only seven donated tracks and their ancestors need dense authoring keys."""
    needed = set()
    for name in RESERVED:
        bone = game.data.bones[name]
        while bone:
            needed.add(bone.name)
            bone = bone.parent
    return [name for name in names if name in needed]


def compare_final(scene, game, names, samples, tolerance):
    fps = scene.render.fps / scene.render.fps_base
    maxima = {"unchanged_head_m": 0.0, "unchanged_axis_tip_m": 0.0,
              "reserved_head_m": 0.0, "reserved_axis_tip_m": 0.0,
              "unadapted_reserved_head_m": 0.0}
    worst = None
    for sample in samples:
        frame_set_seconds(scene, sample["seconds"], fps)
        evaluated = game.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name in names:
            actual = evaluated.matrix_world @ evaluated.pose.bones[name].matrix
            expected = sample["bones"][name] if name in RESERVED else sample["original"][name]
            a, b = bridge.probe_points(actual), bridge.probe_points(expected)
            head = (a[0] - b[0]).length
            axis = max((x - y).length for x, y in zip(a[1:], b[1:]))
            prefix = "reserved" if name in RESERVED else "unchanged"
            maxima[prefix + "_head_m"] = max(maxima[prefix + "_head_m"], head)
            maxima[prefix + "_axis_tip_m"] = max(maxima[prefix + "_axis_tip_m"], axis)
            if worst is None or max(head, axis) > worst["error_m"]:
                worst = {"bone": name, "frame60": sample["seconds"] * 60, "error_m": max(head, axis)}
            if name in RESERVED:
                prior = sample["original"][name]
                maxima["unadapted_reserved_head_m"] = max(maxima["unadapted_reserved_head_m"],
                    (prior.translation - expected.translation).length)
    bridge.require(max(maxima[k] for k in maxima if not k.startswith("unadapted")) <= tolerance,
                   f"Adapted clip failed independent pose comparison: {maxima}, worst={worst}")
    return {**maxima, "worst": worst, "sample_count": len(samples),
            "bone_comparisons": len(samples) * len(names)}


def compare_midpoints(source_scene, source_game, source_fps, final_scene, final_game, offsets, count, sample_fps):
    """Bound interpolation between every corrective key to half a millimetre."""
    final_fps = final_scene.render.fps / final_scene.render.fps_base
    maximum = 0.0
    worst = None
    for frame in range(count - 1):
        seconds = (frame + 0.5) / sample_fps
        bridge.select_scene(source_scene)
        frame_set_seconds(source_scene, seconds, source_fps)
        original = source_game.evaluated_get(bpy.context.evaluated_depsgraph_get())
        hips = original.matrix_world @ original.pose.bones["j_hips"].matrix
        expected = {name: hips @ offsets[name] for name in RESERVED}
        bridge.select_scene(final_scene)
        frame_set_seconds(final_scene, seconds, final_fps)
        final = final_game.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name in RESERVED:
            actual = final.matrix_world @ final.pose.bones[name].matrix
            error = max((a - b).length for a, b in zip(bridge.probe_points(actual),
                                                     bridge.probe_points(expected[name])))
            if error > maximum:
                maximum = error
                worst = {"bone": name, "frame60": seconds * 60, "error_m": error}
    bridge.require(maximum <= 0.0005, f"Reserved-channel inter-key error exceeds 0.5mm: {worst}")
    return {"comparisons": (count - 1) * len(RESERVED),
            "max_head_or_axis_tip_error_m": maximum, "tolerance_m": 0.0005, "worst": worst}


def _adapt_clip_impl(path, output, offsets, names, tolerance, native=None):
    source_sidecar = path.with_suffix(".animation")
    bridge.require(source_sidecar.is_file(), "Shipping animation sidecar is missing")
    sidecar_bytes = source_sidecar.read_bytes()
    source = RawFbx(path)
    bridge.require(source.serialized() == source.data,
                   "Source FBX cannot be regenerated byte-identically; refusing surgical patch")
    original_digest = source.except_reserved_digest()
    _, aim_axes = source.channels("aim_target")["Lcl Translation"]
    for axis, expected in zip(("d|X", "d|Y", "d|Z"), (0.1, 5.0, 0.6)):
        values = child(aim_axes[axis], b"KeyValueFloat").props[0]
        bridge.require(all(abs(value - expected) < 1e-6 for value in values),
                       "Shipping aim helper is no longer calibrated to (0.1, 5, 0.6)")
    all_times = [int(t) for obj in source.objects.values() if obj.id == b"AnimationCurve"
                 for t in child(obj, b"KeyTime").props[0]]
    bridge.require(min(all_times) == 0, "Only zero-origin shipping clips are supported")
    end60 = max(all_times) / TICKS_PER_SECOND * 60
    bridge.require(abs(end60 - round(end60)) < 1e-6, "Clip duration does not end on a 60fps sample")
    base_fps = 240 if path.stem == "death_shot" or path.stem.startswith("stagger_") else 60
    sample_fps = native["sample_fps"] if native is not None else base_fps
    bridge.require(sample_fps / base_fps in {1, 2, 4},
                   "Native targets must use an audited integer refinement of the base sampling rate")
    count = round(end60 * sample_fps / 60) + 1
    if native is not None:
        native_calibration = native["native_calibration"]
        bridge.require(isinstance(native_calibration, dict), "Native calibration provenance is missing")
        bridge.require(native["source_fbx_sha256"] == bridge.sha256(path),
                       "Native targets belong to a different shipping clip")
        bridge.require(native["source_sidecar_sha256"] == hashlib.sha256(sidecar_bytes).hexdigest(),
                       "Native targets belong to a different shipping compression policy")
        bridge.require(len(native["samples"]) == count,
                       "Native target timeline differs from the shipping FBX")
        candidate_sidecar_bytes = native_sidecar(sidecar_bytes)
    else:
        candidate_sidecar_bytes = sidecar_bytes
    previous_scene = bpy.context.scene
    scene, objects, game = bridge.independent_import(path, animation=True)
    temporary_scenes = [(scene, objects)]
    fps = scene.render.fps / scene.render.fps_base
    manifest = {"schema": 1, "clip": path.name, "status": "pending",
                "source_sha256": bridge.sha256(path), "reserved_bones": list(RESERVED),
                "source_animation_sidecar_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
                "candidate_animation_sidecar_sha256": hashlib.sha256(candidate_sidecar_bytes).hexdigest(),
                "unchanged_bones": [name for name in names if name not in RESERVED],
                "candidate_only": True, "requires_corrective_weight_body": True,
                "production_files_modified": False, "source_fps": fps, "sample_fps": sample_fps,
                "source_unreserved_payload_sha256": original_digest,
                "calibration_mode": "sdk-compressed-parent-local" if native else "source-fbx-test-only",
                "game_runtime_acceptance": "pending; SDK compilation is a separate gate"}
    if native is not None:
        manifest["native_calibration"] = native_calibration
        manifest["reserved_compression_overrides"] = {
            name: {"position": 0, "rotation_rad": 0, "scale": 0,
                   "pack_positions": False, "pack_rotations": False, "pack_scales": False}
            for name in RESERVED}
        manifest["unreserved_compression_policy_unchanged"] = True
    try:
        bridge.select_scene(scene)
        bridge.require(list(game.data.bones.keys()) == names, "Clip bone inventory/order changed")
        chain, samples = world_samples(scene, game, names, count, fps, offsets, sample_fps, native)
        scene.render.fps = sample_fps
        scene.render.fps_base = 1.0
        bake_names = donor_bake_names(game, names)
        manifest["donor_baked_bones"] = bake_names
        generated_scene, generated_objects, baked = bridge.bake_copy(
            game, chain, samples, bake_names, "WARLOCK_RESERVED_CLIP_EXPORT", scene,
            tracked_scenes=temporary_scenes)
        with bridge.scratch_directory("adapt-", output.parent) as tmp:
            donor_path = Path(tmp) / "donor.fbx"
            bridge.select_scene(generated_scene)
            for obj in generated_scene.objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = baked
            bridge.write_animation_fbx(donor_path)
            donor = RawFbx(donor_path)
            replacements = {}
            for name in RESERVED:
                old, new = source.channels(name), donor.channels(name)
                for channel in old:
                    old_node, old_axes = old[channel]
                    new_node, new_axes = new[channel]
                    replacements[id(child(old_node, b"Properties70"))] = (donor, child(new_node, b"Properties70"))
                    for axis in old_axes:
                        replacements[id(old_axes[axis])] = (donor, new_axes[axis])
            final_path = Path(tmp) / output.name
            final_path.write_bytes(source.serialized(replacements))
            staged_sidecar = final_path.with_suffix(".animation")
            staged_sidecar.write_bytes(candidate_sidecar_bytes)
            final_doc = RawFbx(final_path)
            final_digest = final_doc.except_reserved_digest()
            bridge.require(final_digest == original_digest, "An unreserved FBX property payload changed")
            manifest["unreserved_payload_bytes_identical"] = True
            manifest["output_unreserved_payload_sha256"] = final_digest
            final_scene, final_objects, final_game = bridge.independent_import(final_path, animation=True)
            temporary_scenes.append((final_scene, final_objects))
            bridge.select_scene(final_scene)
            manifest["independent_roundtrip"] = compare_final(final_scene, final_game, names, samples, tolerance)
            if native is not None:
                manifest["native_local_roundtrip"] = compare_native_local(
                    final_scene, final_game, native["samples"], tolerance)
                manifest["inter_key_roundtrip"] = compare_native_local(
                    final_scene, final_game, native["midpoint_samples"], 0.0005)
                manifest["independent_roundtrip"]["reserved_pose_space"] = (
                    "source parent world composed with SDK-calibrated local; native world gate pending")
            else:
                manifest["inter_key_roundtrip"] = compare_midpoints(
                    scene, game, fps, final_scene, final_game, offsets, count, sample_fps)
            manifest["calibrated_aim_payload_unchanged"] = True
            manifest["sha256"] = bridge.sha256(final_path)
            manifest["fbx_bytes"] = final_path.stat().st_size
            manifest["animation_sidecar_sha256"] = bridge.sha256(staged_sidecar)
            manifest["adapter_script_sha256"] = bridge.sha256(Path(__file__))
            manifest["status"] = "adapted-fbx-roundtrip-passed"
            staged_manifest = Path(tmp) / output.with_suffix(".adapt.json").name
            staged_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            bridge.publish_bundle([(staged_sidecar, output.with_suffix(".animation")),
                                   (final_path, output),
                                   (staged_manifest, output.with_suffix(".adapt.json"))])
    except Exception as error:
        manifest["status"] = "failed"
        manifest["failure"] = str(error)
        output.with_suffix(".adapt.failure.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        raise
    finally:
        bridge.select_scene(previous_scene)
        for temporary_scene, temporary_objects in reversed(temporary_scenes):
            bridge.dispose_scene(temporary_scene, temporary_objects)
    print("WARLOCK_CLIP_ADAPTED", json.dumps({key: manifest[key] for key in (
        "clip", "status", "unreserved_payload_bytes_identical", "independent_roundtrip",
        "inter_key_roundtrip", "sha256", "fbx_bytes")}), flush=True)
    return manifest


def adapt_clip(path, output, offsets, names, tolerance, native=None):
    """Keep the previous matching bundle; record failed attempts separately."""
    bridge.validate_output_path(output, path)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(".adapt.failure.json")
    pending = {"schema": 1, "clip": path.name, "status": "pending", "candidate_only": True}
    try:
        with bridge.preserve_ui_state():
            return _adapt_clip_impl(path, output, offsets, names, tolerance, native)
    except Exception as error:
        manifest = pending
        manifest.update(status="failed", failure=str(error), production_files_modified=False)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips-root", type=Path, default=bridge.ROOT / "units/warlock_bombardier/anims")
    parser.add_argument("--source-body", type=Path, default=bridge.SOURCE_FBX)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clip", action="append", choices=sorted(EXPECTED_CLIPS))
    parser.add_argument("--native-targets", type=Path,
                        help="Hash-bound SDK shipping parent targets, including between-key samples")
    parser.add_argument("--tolerance", type=float, default=5e-5)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    bridge.require(0 < args.tolerance <= 5e-5, "Tolerance cannot exceed 50 micrometres")
    output = args.output.resolve()
    source_root = args.clips_root.resolve()
    bridge.validate_output_path(output, args.source_body)
    bridge.require(output != source_root and not output.is_relative_to(bridge.ROOT / "units"),
                   "Adapted clips must not overwrite production animations")
    bridge.require(all(part.lower() != "units" for part in output.parts),
                   "Adapted clips must be outside every units directory; SDK staging is a separate step")
    paths = sorted(source_root.glob("*.fbx"))
    bridge.require({p.stem for p in paths} == EXPECTED_CLIPS, "Shipping 13-clip inventory differs")
    output.mkdir(parents=True, exist_ok=True)
    baseline_scene, baseline_objects, body = bridge.independent_import(args.source_body, animation=False)
    native_clips, native_provenance = {}, None
    try:
        names = bridge.required_names()
        bridge.require(list(body.data.bones.keys()) == names, "Shipping body skeleton inventory/order differs")
        rest_world = {name: body.matrix_world @ body.data.bones[name].matrix_local for name in names}
        offsets = {name: rest_world["j_hips"].inverted() @ rest_world[name] for name in RESERVED}
        if args.native_targets:
            native_clips, native_provenance = load_native_targets(args.native_targets, args.source_body, body, names)
    finally:
        bridge.dispose_scene(baseline_scene, baseline_objects)
    summary = {"schema": 1, "status": "pending", "clips": [],
               "shipping_body_sha256": bridge.sha256(args.source_body),
               "calibration_mode": "sdk-compressed-parent-local" if args.native_targets else "source-fbx-test-only",
               "all_thirteen_adapted": False,
               "requires_candidate_body_and_clips_together": True,
               "production_files_modified": False, "game_runtime_acceptance": "pending"}
    if native_provenance:
        summary["native_calibration"] = native_provenance
    summary_path = output / "adapted-clips.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    try:
        for path in paths:
            if args.clip and path.stem not in args.clip:
                continue
            summary["clips"].append(adapt_clip(path, output / path.name, offsets, names, args.tolerance,
                                              native_clips.get(path.name)))
        summary["status"] = "adapted-fbx-roundtrip-passed"
        summary["all_thirteen_adapted"] = len(summary["clips"]) == 13
    except Exception as error:
        summary["status"] = "failed"
        summary["failure"] = str(error)
        raise
    finally:
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

