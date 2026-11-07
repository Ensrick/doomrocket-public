#!/usr/bin/env python3
"""Read-only, SHA-pinned direct dependency audit for the native pickup torch.

Usage: py -3 tools/check_crystal_flame_native_effect.py --extracted-root PATH

The audit CLI copies, changes, packages and executes no game payload. Its v68
reader checks the bounded cloud/component layout and billboard material slot.
The separate numeric-derivative reader additionally decodes this torch's typed
size/colour writer records and RGB gradient, grounded in the pinned SDK compiler.
Full payload hashes bind all untouched bytes to the audited donor.
Package membership and material references are offline evidence; they establish
neither runtime residency nor visible size, colour, or in-game acceptance.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct

from make_spliced_child import read_parent_binding, read_texture_bindings
from strip_bundle_resource import murmur64a


DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures/crystal_flame_native_effect.json"
RESOURCE_TYPES = {
    "effect": "particles", "child_material": "material",
    "parent_material": "material", "texture": "texture",
}
# Only the record types present in this one audited candidate are supported.
INITIALIZER_SIZES = {0: 12, 1: 16, 6: 8, 11: 44}
PARTICLE_HEADER_SIZE = 40
CLOUD_HEADER_SIZE = 208


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resource_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9A-F]{16}", value),
            "Resource ID must be sixteen uppercase hexadecimal digits")
    return int(value, 16)


def safe_path(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and
            ":" not in relative and not PurePosixPath(relative).is_absolute() and
            all(part not in ("", ".", "..") for part in relative.split("/")),
            "Invalid extracted-resource relative path")
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()),
            "Extracted resource escapes the supplied root")
    return path


def validate_fixture(fixture):
    require(isinstance(fixture, dict) and fixture.get("schema") == 1,
            "Unsupported native-effect fixture schema")
    resources = fixture["resources"]
    require(set(resources) == set(RESOURCE_TYPES), "Unexpected native resource inventory")
    for role, kind in RESOURCE_TYPES.items():
        item = resources[role]
        require(item["type"] == kind, "Unexpected resource type for " + role)
        identity = resource_id(item["id"])
        stem, extension = item["path"].rsplit(".", 1)
        require(extension == kind, "Resource extension differs from its native type")
        expected_identity = int(stem, 16) if re.fullmatch(r"[0-9A-F]{16}", stem) else murmur64a(stem.encode("utf-8"))
        require(identity == expected_identity, "Native resource path and ID differ: " + role)
    for item in [fixture["package"], *resources.values()]:
        safe_path(Path("."), item["path"])
        require(type(item["size"]) is int and item["size"] > 0,
                "Invalid pinned payload size")
        require(isinstance(item["sha256"], str) and
                re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                "Invalid pinned payload SHA-256")
    package = fixture["package"]
    require(type(package["entry_count"]) is int and 0 < package["entry_count"] <= 100000,
            "Invalid expected package entry count")
    require(type(package["trailer_size"]) is int and package["trailer_size"] >= 0,
            "Invalid expected package trailer size")
    require(fixture["particle"]["cloud"]["material_id"] == resources["child_material"]["id"],
            "Particle fixture does not bind the identified child material")
    require(fixture["child"]["parent_id"] == resources["parent_material"]["id"] and
            fixture["child"]["texture_bindings"] == {"9CA38F7D": resources["texture"]["id"]},
            "Child fixture does not describe the identified direct dependency chain")
    require(fixture["parent"] == {"parent_id": "0000000000000000", "texture_bindings": {}},
            "The audited parent must have no parent or additional texture bindings")


def load_fixture(path=DEFAULT_FIXTURE):
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_fixture(fixture)
    return fixture


def read_pinned(root, item):
    path = safe_path(root, item["path"])
    require(path.is_file(), "Missing extracted payload: " + item["path"])
    payload = path.read_bytes()
    require(len(payload) == item["size"], "Payload size differs: " + item["path"])
    require(hashlib.sha256(payload).hexdigest() == item["sha256"],
            "Payload SHA-256 differs: " + item["path"])
    return payload


def require_members(payload, fixture):
    """Read typed u64 pairs from the declared table, never a byte-string search."""
    require(len(payload) >= 4, "Truncated compiled package header")
    count = struct.unpack_from("<I", payload)[0]
    expected = fixture["package"]
    require(count == expected["entry_count"], "Compiled package entry count differs")
    end = 4 + count * 16
    require(len(payload) == end + expected["trailer_size"],
            "Compiled package table length or trailer length differs")
    members = list(struct.iter_unpack("<QQ", payload[4:end]))
    counts = Counter(members)
    require(all(count == 1 for count in counts.values()), "Duplicate typed package member")
    for role, item in fixture["resources"].items():
        pair = (murmur64a(item["type"].encode("ascii")), resource_id(item["id"]))
        require(counts[pair] == 1, "Missing or wrong-typed package member: " + role)
    return members


def inspect_particle(payload, expected):
    """Fail closed outside this single-cloud billboard candidate's known layout."""
    require(len(payload) >= PARTICLE_HEADER_SIZE, "Truncated native particle header")
    version, = struct.unpack_from("<I", payload)
    cloud_count, = struct.unpack_from("<I", payload, 0x24)
    require(version == expected["version"] == 68, "Unsupported native particle version")
    require(cloud_count == expected["cloud_count"] == 1, "Native particle cloud count differs")
    base = PARTICLE_HEADER_SIZE
    require(len(payload) >= base + CLOUD_HEADER_SIZE, "Truncated native cloud header")
    cloud = expected["cloud"]
    fields = {"capacity": 4, "initializer_offset": 0xB0, "simulator_offset": 0xB8,
              "renderer_offset": 0xBC, "visualizer_count": 0xC4,
              "visualizer_offset": 0xC8, "total_size": 0xCC}
    actual = {name: struct.unpack_from("<I", payload, base + offset)[0]
              for name, offset in fields.items()}
    require(all(actual[name] == cloud[name] for name in fields), "Native cloud layout differs")
    require(base + actual["total_size"] == len(payload), "Native cloud size or trailing bytes differ")
    offsets = [actual[name] for name in ("initializer_offset", "simulator_offset",
                                        "renderer_offset", "visualizer_offset", "total_size")]
    require(CLOUD_HEADER_SIZE <= offsets[0] and offsets == sorted(offsets),
            "Native cloud section offsets are out of bounds or unordered")
    init_count = struct.unpack_from("<I", payload, base + 0xAC)[0]
    sim_count = struct.unpack_from("<I", payload, base + 0xB4)[0]
    require(init_count == len(cloud["initializer_types"]) and
            sim_count == len(cloud["simulator_types"]), "Native cloud component counts differ")
    cursor = base + actual["initializer_offset"]
    init_end = base + actual["simulator_offset"]
    initializers = []
    for _ in range(init_count):
        require(cursor + 4 <= init_end, "Native initializer header exceeds section")
        kind = struct.unpack_from("<I", payload, cursor)[0]
        require(kind in INITIALIZER_SIZES, "Unsupported native initializer type")
        cursor += INITIALIZER_SIZES[kind]
        require(cursor <= init_end, "Native initializer exceeds section")
        initializers.append(kind)
    require(cursor == init_end and initializers == cloud["initializer_types"],
            "Native initializer layout differs")
    require(actual["renderer_offset"] - actual["simulator_offset"] == sim_count * 5,
            "Native simulator record size differs")
    simulators = [payload[init_end + index * 5] for index in range(sim_count)]
    require(simulators == cloud["simulator_types"] and 17 in simulators,
            "Native local-space simulator sequence differs")
    visualizer = base + actual["visualizer_offset"]
    require(actual["visualizer_count"] == 1 and visualizer + 4 <= len(payload),
            "Native billboard visualizer is missing or truncated")
    require(struct.unpack_from("<I", payload, visualizer)[0] == cloud["visualizer_type"] == 0,
            "Native visualizer is not the audited billboard")
    # This v68 billboard slot is pinned to the audited candidate, not a general
    # renderer parser. All unparsed writers/curves stay covered by the full hash.
    require(cloud["material_offset_from_visualizer"] == 12,
            "Unsupported native billboard material slot")
    material_offset = visualizer + 12
    require(material_offset + 8 <= len(payload), "Truncated native billboard material slot")
    material = struct.unpack_from("<Q", payload, material_offset)[0]
    require(material == resource_id(cloud["material_id"]), "Native particle material binding differs")
    return {"version": version, "cloud_count": cloud_count, "capacity": actual["capacity"],
            "initializer_types": initializers, "simulator_types": simulators,
            "billboard_material_id": f"{material:016X}",
            "opaque_renderer_and_colour_curves_decoded": False}


def inspect_material(payload, expected, role):
    try:
        parent = read_parent_binding(payload)
        textures = read_texture_bindings(payload)
    except (ValueError, struct.error) as error:
        raise ValueError("Invalid compiled " + role + ": " + str(error)) from error
    require(parent == resource_id(expected["parent_id"]), role + " parent binding differs")
    bindings = {f"{key:08X}": f"{value:016X}" for key, value in textures.items()}
    require(bindings == expected["texture_bindings"], role + " texture bindings differ")
    return {"parent_id": f"{parent:016X}", "texture_bindings": bindings}


def inspect_editable_particle(payload, fixture):
    """Read the bounded numeric edit contract for this exact native torch.

    v68 writer type IDs, body sizes and curve layouts are recovered from the
    installed SDK compiler listed in the fixture. Offsets come from the typed
    cloud/simulator/writer records, never a search for matching float bytes.
    Unknown layouts fail closed; the donor's full SHA remains a separate gate.
    """
    inspect_particle(payload, fixture["particle"])
    expected = fixture["derivative"]
    cloud = fixture["particle"]["cloud"]
    base = PARTICLE_HEADER_SIZE
    cursor = base + cloud["initializer_offset"]
    initializers = []
    for kind in cloud["initializer_types"]:
        route, = struct.unpack_from("<I", payload, cursor + 4)
        initializers.append((kind, route, cursor))
        cursor += INITIALIZER_SIZES[kind]
    require([(kind, route) for kind, route, _ in initializers] ==
            [tuple(item) for item in expected["initializer_routes"]],
            "Native initializer routing differs")
    size = next(offset for kind, route, offset in initializers if kind == 1 and route == 40)
    cylinder = next(offset for kind, route, offset in initializers if kind == 11 and route == 0)
    require(list(struct.unpack_from("<2f", payload, size + 8)) == expected["source_size_range"],
            "Native size initializer differs")
    require(list(struct.unpack_from("<4f", payload, cylinder + 8)) ==
            expected["source_cylinder_radius_height"], "Native cylinder dimensions differ")
    require(struct.unpack_from("<3i", payload, cylinder + 32) == (-1, -1, -1),
            "Native cylinder unexpectedly binds variables")
    sim_base = base + cloud["simulator_offset"]
    simulators = [struct.unpack_from("<BI", payload, sim_base + index * 5)
                  for index in range(len(cloud["simulator_types"]))]
    require(simulators == [tuple(item) for item in expected["simulator_routes"]],
            "Native simulator routing differs")
    constants = base + cloud["renderer_offset"]
    acceleration = constants + next(route for kind, route in simulators if kind == 3)
    require(acceleration + 16 <= base + cloud["visualizer_offset"],
            "Native acceleration record exceeds simulator data")
    require(struct.unpack_from("<I", payload, acceleration)[0] == 16 and
            list(struct.unpack_from("<3f", payload, acceleration + 4)) ==
            expected["source_acceleration"], "Native acceleration record differs")

    visualizer = base + cloud["visualizer_offset"]
    body = visualizer + 4  # billboard type precedes its 248-byte body header
    stride, count, start, total = struct.unpack_from("<4I", payload, body + 228)
    require((stride, count, start, total) == (36, 6, 248, 696),
            "Native billboard writer-table header differs")
    require(body + total == len(payload), "Native billboard writer table end differs")
    writer_sizes = {0: 8, 3: 108, 4: 268, 5: 12, 18: 16}
    cursor = body + start
    writers = []
    for _ in range(count):
        require(cursor + 4 <= body + total, "Truncated native vertex writer")
        kind, = struct.unpack_from("<I", payload, cursor)
        require(kind in writer_sizes, "Unsupported native vertex-writer type")
        record = cursor + 4
        cursor = record + writer_sizes[kind]
        require(cursor <= body + total, "Native vertex writer exceeds its table")
        writers.append((kind, record))
    require(cursor == body + total and [kind for kind, _ in writers] ==
            expected["writer_types"], "Native vertex-writer topology differs")
    size_writer = next(offset for kind, offset in writers if kind == 3)
    require(struct.unpack_from("<4I", payload, size_writer) == (40, 32, 36, 16),
            "Native size writer no longer reads the resized channel")
    colour = next(offset for kind, offset in writers if kind == 4)
    require(struct.unpack_from("<2I", payload, colour) == (32, 36) and
            struct.unpack_from("<3I", payload, colour + 256) == (12, 0, 0),
            "Native colour writer routing or luminance binding differs")
    # A scalar curve is ten times, ten values, count. A vector3 gradient is
    # ten times, ten packed RGB values, count. The two curves are independent.
    opacity = colour + 8
    gradient = opacity + 84
    alpha_count, = struct.unpack_from("<I", payload, opacity + 80)
    colour_count, = struct.unpack_from("<I", payload, gradient + 160)
    require(alpha_count == colour_count == 3, "Native colour curve cardinality differs")
    times = list(struct.unpack_from("<3f", payload, gradient))
    values = [list(struct.unpack_from("<3f", payload, gradient + 40 + index * 12))
              for index in range(colour_count)]
    require(times == expected["source_gradient_times"] and
            values == expected["source_gradient_rgb"], "Native RGB gradient differs")
    require(all(math.isfinite(value) and 0 <= value <= 255
                for row in values for value in row) and
            0 <= times[0] < times[1] < times[2] <= 1,
            "Invalid native RGB gradient")
    return {"size_range_offset": size + 8, "cylinder_dimensions_offset": cylinder + 8,
            "acceleration_vector_offset": acceleration + 4,
            "gradient_rgb_offsets": [gradient + 40 + index * 12
                                     for index in range(colour_count)],
            "gradient_times": times, "gradient_rgb": values,
            "writer_types": [kind for kind, _ in writers]}


def audit(extracted_root, fixture):
    validate_fixture(fixture)
    root = Path(extracted_root).resolve()
    require(root.is_dir(), "Supplied extracted game root is not a directory")
    package = read_pinned(root, fixture["package"])
    payloads = {role: read_pinned(root, item) for role, item in fixture["resources"].items()}
    members = require_members(package, fixture)
    particle = inspect_particle(payloads["effect"], fixture["particle"])
    child = inspect_material(payloads["child_material"], fixture["child"], "child material")
    parent = inspect_material(payloads["parent_material"], fixture["parent"], "parent material")
    return {
        "schema": 1, "status": "native-effect-direct-dependencies-verified",
        "scope": "pinned extracted payloads, typed package table and direct material/texture chain only",
        "extracted_root": str(root),
        "fixture_content_sha256": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
        "package": dict(fixture["package"], verified_members=len(members)),
        "resources": fixture["resources"], "particle": particle,
        "child_material": child, "parent_material": parent,
        "material_parser": "tools/make_spliced_child.py:read_parent_binding,read_texture_bindings",
        "runtime_verified": False, "color_verified": False, "rendered_size_verified": False,
        "native_payloads_copied": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted-root", required=True, type=Path)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    try:
        report = audit(args.extracted_root, load_fixture(args.fixture))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, "Native flame dependency audit failed: " + str(error) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
