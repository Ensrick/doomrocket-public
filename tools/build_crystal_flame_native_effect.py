#!/usr/bin/env python3
"""Derive the small green torch from the exact audited native pickup effect.

The output is game-derived and belongs under ignored .build, never Git. This
tool changes only parsed numeric fields: native size, spawn radius/height,
acceleration and active RGB gradient values. It preserves every other byte.
The canonical build hook splices the result over the mod-only SDK placeholder.
It never replaces the game's torch identity, shader, texture or material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from check_crystal_flame_native_effect import (
    audit, inspect_editable_particle, load_fixture, read_pinned, require,
)
from splice_bundle_resource import murmur64a, read_bundle, walk


def derive(payload, fixture):
    spec = fixture["resources"]["effect"]
    require(len(payload) == spec["size"] and
            hashlib.sha256(payload).hexdigest() == spec["sha256"],
            "Native torch donor size or SHA-256 differs")
    contract = inspect_editable_particle(payload, fixture)
    recipe = fixture["derivative"]
    require(recipe["effect"] == "fx/doomrocket/crystal_torch_green_small" and
            recipe["scale"] == 0.6 and recipe["tint"] == [0.12, 1.0, 0.06],
            "Unsupported crystal flame transform recipe")
    output = bytearray(payload)
    allowed = set()

    def floats(offset, values):
        values = list(values)
        struct.pack_into("<" + "f" * len(values), output, offset, *values)
        allowed.update(range(offset, offset + 4 * len(values)))

    scale = recipe["scale"]
    for key, count in (("size_range_offset", 2), ("cylinder_dimensions_offset", 4),
                       ("acceleration_vector_offset", 3)):
        offset = contract[key]
        floats(offset, (value * scale for value in
                        struct.unpack_from("<" + "f" * count, payload, offset)))
    for offset, rgb in zip(contract["gradient_rgb_offsets"], contract["gradient_rgb"]):
        # Preserve each key's peak channel and fade-to-black; tint every active
        # key green. Opacity, key times and all unused curve slots stay exact.
        peak = max(rgb)
        floats(offset, (peak * channel for channel in recipe["tint"]))
    require(len(output) == len(payload) and all(
        before == after or index in allowed
        for index, (before, after) in enumerate(zip(payload, output))),
        "Crystal flame transform changed a byte outside its parsed numeric fields")
    result = bytes(output)
    require(hashlib.sha256(result).hexdigest() == recipe["sha256"],
            "Derived crystal torch SHA-256 differs from the reviewed recipe")
    return result


def boot_packages(path):
    """Read the literal package table used by this mod's source/runtime entry."""
    text = Path(path).read_text(encoding="utf-8")
    tables = re.findall(r"\bpackages\s*=\s*\{([^}]*)\}", text)
    require(len(tables) == 1, "Expected one literal mod boot-package table")
    body = re.sub(r"--[^\n]*", "", tables[0])
    names = re.findall(r'"([^"\\]*)"', body)
    residue = re.sub(r'"[^"\\]*"', "", body)
    require(re.fullmatch(r"[\s,]*", residue) is not None and names and
            len(names) == len(set(names)), "Unsupported mod boot-package declaration")
    return names


def verify_bundles(bundle_root, expected, fixture):
    """Read the SDK package container, typed index and exact particle payload.

    SDK delayed packages are named by their package-path hash and represented by
    that bundle's resource index. Unlike extracted native .package resources,
    they do not contain an additional package-type payload. Inspect all other
    bundle indexes and any embedded package tables to exclude boot leakage.
    """
    effect = fixture["derivative"]["effect"]
    package = fixture["derivative"]["package"]
    identity = (murmur64a(b"particles"), murmur64a(effect.encode()))
    donor_identity = (identity[0], int(fixture["resources"]["effect"]["id"], 16))
    package_hash = murmur64a(package.encode())
    delayed_package_identity = (murmur64a(b"package"), package_hash)
    bundle_root = Path(bundle_root)
    expected_name = f"{package_hash:016x}.mod_bundle"
    found = []
    own_bundle = None
    embedded_memberships = []
    for path in sorted(bundle_root.glob("*.mod_bundle")):
        fmt, _, data = read_bundle(path)
        count, index, records = walk(data, fmt)
        if path.name.lower() == expected_name:
            require(own_bundle is None and count == len(index) == len(records) == 1 and
                    (index[0]["type"], index[0]["name"]) == identity,
                    "Delayed crystal package bundle must contain only its typed particle")
            require(index[0]["data_size"] in (None, len(expected)),
                    "Delayed crystal package index size differs from its particle")
            own_bundle = path
        for record in records:
            pair = (record["type"], record["name"])
            require(pair != donor_identity, "Mod bundle unexpectedly overrides the game's native torch")
            if record["type"] == murmur64a(b"package"):
                require(record["version_count"] == 1,
                        "Cannot establish boot exclusion for an unknown package-version layout")
                version = record["versions"][0]
                require(version["lang"] == 0 and version["stream_size"] == 0,
                        "Cannot establish boot exclusion for locale/stream package data")
                start = version["payload_offset"]
                payload = data[start:start + version["size"]]
                require(len(payload) >= 4, "Truncated compiled resource package")
                count, = struct.unpack_from("<I", payload)
                end = 4 + 16 * count
                require(end <= len(payload), "Compiled resource package table exceeds its payload")
                members = list(struct.iter_unpack("<QQ", payload[4:end]))
                if identity in members or delayed_package_identity in members:
                    embedded_memberships.append(record["name"])
            if pair != identity:
                continue
            require(record["version_count"] == 1,
                    "Crystal flame resource must have exactly one version")
            version = record["versions"][0]
            require(version["lang"] == 0 and version["stream_size"] == 0,
                    "Crystal flame resource unexpectedly has locale or stream data")
            start = version["payload_offset"]
            found.append((path.name, data[start:start + version["size"]]))
    require(own_bundle is not None and len(found) == 1 and
            found[0][0].lower() == expected_name,
            "Expected exactly one crystal particle in its delayed SDK package bundle")
    require(found[0][1] == expected,
            "Packaged crystal flame differs from the reviewed native derivative")
    require(not embedded_memberships,
            "Crystal particle must not appear in embedded boot package tables")
    source_boot = boot_packages(Path(__file__).resolve().parents[1] / "doomrocket.mod")
    shipped_boot = boot_packages(bundle_root / "doomrocket.mod")
    require(package not in source_boot and shipped_boot == source_boot,
            "Delayed crystal package is boot-loaded or shipped boot packages differ from source")
    return {"particle": {"bundle": found[0][0], "size": len(expected),
                          "sha256": hashlib.sha256(expected).hexdigest()},
            "package": {"bundle": own_bundle.name, "path": package,
                        "identity": f"{package_hash:016X}", "typed_members": 1,
                        "size": own_bundle.stat().st_size,
                        "sha256": hashlib.sha256(own_bundle.read_bytes()).hexdigest()},
            "boot_packages": shipped_boot, "embedded_particle_memberships": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted-root", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-bundle-root", type=Path)
    args = parser.parse_args()
    try:
        require(args.out is not None or args.verify_bundle_root is not None,
                "Supply --out or --verify-bundle-root")
        fixture = load_fixture()
        donor_report = audit(args.extracted_root, fixture)
        payload = read_pinned(args.extracted_root, fixture["resources"]["effect"])
        derived = derive(payload, fixture)
        report = {"schema": 1, "status": "native-torch-numeric-derivative-verified",
                  "effect": fixture["derivative"]["effect"],
                  "package": fixture["derivative"]["package"],
                  "donor_sha256": fixture["resources"]["effect"]["sha256"],
                  "sha256": hashlib.sha256(derived).hexdigest(), "size": len(derived),
                  "native_scale": fixture["derivative"]["scale"],
                  "rgb_tint": fixture["derivative"]["tint"],
                  "dependency_fixture_sha256": donor_report["fixture_content_sha256"],
                  "runtime_verified": False, "rendered_size_verified": False,
                  "rendered_color_verified": False}
        if args.verify_bundle_root is not None:
            report["packaged"] = verify_bundles(args.verify_bundle_root, derived, fixture)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(derived)
            args.out.with_suffix(args.out.suffix + ".json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, "Crystal flame native build failed: " + str(error) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
