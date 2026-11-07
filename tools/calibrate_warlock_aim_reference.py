#!/usr/bin/env python3
"""Calibrate only the constant aim helper in the existing animation FBXs.

The native Ratling aim constraint uses a positional reference. Its authored
root-relative reference is (0.1, 5, 0.6) metres. The Warlock clips kept the
source model's different (0, 3, 1.25) reference when helper curves were stripped.
These FBXs compile translation values at 1/100 scale beneath the existing
100-scale armature wrapper, so the same FBX values express the native point.

This deliberately patches fixed-size, uncompressed numeric fields in place;
it never re-exports a clip, changes offsets, or rewrites another channel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "tests"))
from test_warlock_weapon_pipeline import BinaryFbx, clean_fbx_name  # noqa: E402

EXPECTED_HELPER_TRANSLATION = (0.1, 5.0, 0.6)
EXPECTED_COMPILED_LOCAL = (0.001, 0.05, 0.006)
MANIFEST = ROOT / "tools" / "fixtures" / "warlock_aim_reference.json"
CLIP_ROOT = ROOT / "units" / "warlock_bombardier" / "anims"


def _property_locations(fbx: BinaryFbx) -> dict[int, list[tuple[int, int]]]:
    """Associate the existing reader's nodes with their original property bytes."""
    locations: dict[int, list[tuple[int, int]]] = {}
    header = "<QQQB" if fbx.wide else "<IIIB"
    header_size = struct.calcsize(header)

    def walk(offset, nodes):
        for node in nodes:
            end, count, property_length, name_length = struct.unpack_from(header, fbx.data, offset)
            start = offset + header_size + name_length
            at = start
            props = []
            for _ in range(count):
                begin = at
                kind = chr(fbx.data[at])
                at += 1
                if kind in "YCFDLI":
                    at += {"Y": 2, "C": 1, "F": 4, "D": 8, "L": 8, "I": 4}[kind]
                elif kind in "SR":
                    length = struct.unpack_from("<I", fbx.data, at)[0]
                    at += 4 + length
                elif kind in "fdlibc":
                    _count, _encoding, length = struct.unpack_from("<III", fbx.data, at)
                    at += 12 + length
                else:
                    raise ValueError(f"unsupported FBX property type {kind!r}")
                props.append((begin, at))
            if at != start + property_length or len(props) != len(node.properties):
                raise ValueError("FBX property layout disagrees with parsed tree")
            locations[id(node)] = props
            walk(at, node.children)
            offset = end

    walk(len(BinaryFbx.MAGIC) + 4, fbx.nodes)
    return locations


def _inspect(path: Path):
    fbx = BinaryFbx(path)
    locations = _property_locations(fbx)
    models = fbx.object_nodes("Model")
    helpers = [node for node in models if clean_fbx_name(node.properties[1]) == "aim_target"]
    if len(helpers) != 1:
        raise ValueError("expected exactly one aim_target model")
    helper = helpers[0]
    objects = {node.properties[0]: node for section in fbx.nodes if section.name == "Objects"
               for node in section.children if node.properties}
    connections = [node.properties for node in fbx.descendants("C")]
    parents = [objects[p[2]] for p in connections if p[0] == "OO"
               and p[1] == helper.properties[0] and p[2] in objects
               and objects[p[2]].name == "Model"]
    if len(parents) != 1 or clean_fbx_name(parents[0].properties[1]) != "root_point":
        raise ValueError("aim_target must remain a direct child of root_point")
    model_translation = [p for p in helper.child("Properties70").children
                         if p.properties[0] == "Lcl Translation"]
    if len(model_translation) != 1:
        raise ValueError("missing unique aim_target translation property")
    curves = [objects[p[1]] for p in connections if len(p) == 4 and p[0] == "OP"
              and p[2] == helper.properties[0] and p[3] == "Lcl Translation"]
    if len(curves) != 1:
        raise ValueError("expected one aim_target translation curve node")
    curve_node = curves[0]
    spans: list[tuple[int, int, int, str, int]] = []
    values = []

    def scalar(node, index, axis):
        begin, end = locations[id(node)][index]
        kind = chr(fbx.data[begin])
        if kind not in "DF":
            raise ValueError("aim translation scalar is not floating point")
        spans.append((begin + 1, end, axis, kind.lower(), 1))

    for axis, name in enumerate(("d|X", "d|Y", "d|Z")):
        scalar(model_translation[0], axis + 4, axis)
        defaults = [p for p in curve_node.child("Properties70").children if p.properties[0] == name]
        links = [objects[p[1]] for p in connections if len(p) == 4 and p[0] == "OP"
                 and p[2] == curve_node.properties[0] and p[3] == name]
        if len(defaults) != 1 or len(links) != 1 or links[0].name != "AnimationCurve":
            raise ValueError(f"expected one constant translation channel {name}")
        scalar(defaults[0], len(defaults[0].properties) - 1, axis)
        curve = links[0]
        scalar(curve.child("Default"), 0, axis)
        key_node = curve.child("KeyValueFloat")
        channel_values = key_node.properties[0]
        if not channel_values or any(not math.isfinite(value) for value in channel_values):
            raise ValueError("non-finite or empty helper translation")
        if max(channel_values) - min(channel_values) > 1e-7:
            raise ValueError("refusing to overwrite an animated aim helper")
        begin, end = locations[id(key_node)][0]
        count, encoding, length = struct.unpack_from("<III", fbx.data, begin + 1)
        if fbx.data[begin:begin + 1] != b"f" or encoding != 0 or length != count * 4:
            raise ValueError("helper keys must be uncompressed Float32 for an in-place patch")
        if count != len(channel_values) or end != begin + 13 + length:
            raise ValueError("helper key layout mismatch")
        spans.append((begin + 13, end, axis, "f", count))
        values.append(float(channel_values[0]))

    masked = bytearray(fbx.data)
    for begin, end, _axis, _kind, _count in spans:
        masked[begin:end] = bytes(end - begin)
    rotation = [p for p in connections if len(p) == 4 and p[0] == "OP"
                and p[2] == helper.properties[0] and p[3] == "Lcl Rotation"]
    rotation_nodes = [p for p in helper.child("Properties70").children
                      if p.properties[0] == "Lcl Rotation"]
    for p in rotation:
        rotation_nodes.append(objects[p[1]])
        rotation_nodes.extend(objects[c[1]] for c in connections if len(c) == 4
                              and c[0] == "OP" and c[2] == p[1])
    def node_bytes(node):
        return (node.name.encode("utf-8") + b"\x00"
                + b"".join(fbx.data[start:end] for start, end in locations[id(node)])
                + b"".join(node_bytes(child) for child in node.children))

    # nonhelper_sha256 is the stronger invariant: every other original byte,
    # including helper rotation/scaling, remains part of that exact digest.
    metadata = {
        "translation": values,
        "model_translation": list(model_translation[0].properties[4:7]),
        "translation_channels_constant": True,
        "parent": "root_point",
        "nonhelper_sha256": hashlib.sha256(masked).hexdigest(),
        "helper_rotation_sha256": hashlib.sha256(b"".join(map(node_bytes, rotation_nodes))).hexdigest(),
        "sha256": hashlib.sha256(fbx.data).hexdigest(),
        "file_size": len(fbx.data),
    }
    return fbx.data, spans, metadata


def inspect_clip(path: Path) -> dict:
    return _inspect(path)[2]


def calibrated_bytes(path: Path) -> bytes:
    data, spans, _metadata = _inspect(path)
    result = bytearray(data)
    for begin, end, axis, kind, count in spans:
        payload = struct.pack("<" + kind * count, *([EXPECTED_HELPER_TRANSLATION[axis]] * count))
        if len(payload) != end - begin:
            raise ValueError("patch would change the FBX file layout")
        result[begin:end] = payload
    return bytes(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the reviewed helper-only patch")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = sorted(CLIP_ROOT.glob("*.fbx"))
    if {path.name for path in paths} != set(manifest["files"]):
        raise ValueError("clip inventory differs from the reviewed calibration manifest")
    for path in paths:
        expected = manifest["files"][path.name]
        before = inspect_clip(path)
        if before["sha256"] not in (expected["before_sha256"], expected["after_sha256"]):
            raise ValueError(f"{path.name}: source bytes differ from the reviewed calibration")
        if before["nonhelper_sha256"] != expected["nonhelper_sha256"]:
            raise ValueError(f"{path.name}: a non-helper byte changed")
        patched = calibrated_bytes(path)
        if hashlib.sha256(patched).hexdigest() != expected["after_sha256"]:
            raise ValueError(f"{path.name}: calibrated output hash differs")
        if args.apply:
            path.write_bytes(patched)
        elif path.read_bytes() != patched:
            raise ValueError(f"{path.name}: helper still needs calibration; run --apply")
        print(f"[aim-reference] {path.name}: helper calibrated; all other bytes preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
