"""Build a spliced child-material payload from installed game data.

Extracts an exact compiled child material from a donor bundle and patches
selected texture ids and reflected variables for Pusfume. The
output payload is written under .build and is never committed: it derives
from Fatshark game data (a binding table containing the parent hash, slot keys,
texture ids, and variable defaults, with no embedded shader payload).

Each mapping must match exactly once; anything else aborts, so a game patch
that changes the child's layout fails the build instead of shipping garbage.

Usage:
  py make_spliced_child.py --game-bundle <path> --resource hash:<16-hex> \
      --map OLDHEX=NEWHEX [--map ...] --out <payload file>
"""

import argparse
import struct
import sys

import importlib.util
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "splice_bundle_resource", _HERE / "splice_bundle_resource.py")
_splice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_splice)


def _short_hash(name):
    return _splice.murmur64a(name.encode("utf-8")) >> 32


def _parse_short_hash(name):
    if len(name) == 8 and all(character in "0123456789abcdefABCDEF"
                              for character in name):
        return int(name, 16)
    return _short_hash(name)


def read_texture_bindings(payload):
    """Return a compiled single material's short-hash -> resource-id table."""
    if len(payload) < 40:
        raise ValueError("payload is too short for a VT2 material header")

    version, is_single, material_offset = struct.unpack_from("<III", payload, 0)
    if version != 43 or is_single != 1:
        raise ValueError(
            f"expected VT2 single material version 43, got {version}/{is_single}")

    position = material_offset + 12  # shader short hash + parent resource id
    texture_count = struct.unpack_from("<I", payload, position)[0]
    position += 4
    end = position + texture_count * 12
    if end > len(payload):
        raise ValueError("material texture table extends beyond payload")

    bindings = {}
    for _ in range(texture_count):
        channel, resource = struct.unpack_from("<IQ", payload, position)
        if channel in bindings:
            raise ValueError(f"duplicate texture channel {channel:08X}")
        bindings[channel] = resource
        position += 12
    return bindings


def read_parent_binding(payload):
    """Return the compiled material's parent resource id."""
    if len(payload) < 36:
        raise ValueError("payload is too short for a VT2 material header")

    version, is_single, material_offset = struct.unpack_from("<III", payload, 0)
    if version != 43 or is_single != 1 or material_offset + 12 > len(payload):
        raise ValueError("expected a VT2 single material version 43")

    return struct.unpack_from("<Q", payload, material_offset + 4)[0]


def read_variable_bindings(payload):
    """Return short hash -> (component count, absolute value offset)."""
    if len(payload) < 40:
        raise ValueError("payload is too short for a VT2 material header")

    version, is_single, material_offset = struct.unpack_from("<III", payload, 0)
    if version != 43 or is_single != 1:
        raise ValueError(
            f"expected VT2 single material version 43, got {version}/{is_single}")

    position = material_offset + 12
    texture_count = struct.unpack_from("<I", payload, position)[0]
    position += 4 + texture_count * 12
    context_count = struct.unpack_from("<I", payload, position)[0]
    position += 4 + context_count * 8
    variable_count = struct.unpack_from("<I", payload, position)[0]
    position += 4
    reflection_end = position + variable_count * 20
    if reflection_end + 4 > len(payload):
        raise ValueError("material variable table extends beyond payload")

    reflections = []
    for _ in range(variable_count):
        variable_type, elements, name, offset, stride = struct.unpack_from(
            "<IIIII", payload, position)
        if variable_type > 3 or elements != 0 or stride != 0:
            raise ValueError(f"unsupported variable reflection {name:08X}")
        reflections.append((name, variable_type + 1, offset))
        position += 20

    data_length = struct.unpack_from("<I", payload, position)[0]
    data_start = position + 4
    if data_start + data_length > len(payload):
        raise ValueError("material variable data extends beyond payload")

    bindings = {}
    for name, components, offset in reflections:
        if name in bindings:
            raise ValueError(f"duplicate variable {name:08X}")
        if offset + components * 4 > data_length:
            raise ValueError(f"variable {name:08X} extends beyond variable data")
        bindings[name] = (components, data_start + offset)
    return bindings


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--game-bundle",
                        help="installed game bundle containing the donor "
                             "child (zlib formats only)")
    source.add_argument("--extracted",
                        help="raw resource payload already extracted (e.g. by "
                             "the Rust unpacker, which also reads the 2023 "
                             "zstd game format)")
    parser.add_argument("--type", default="material")
    parser.add_argument("--resource", required=True,
                        help="resource path, or hash:<16-hex-digit id>")
    parser.add_argument("--map", action="append", required=True,
                        metavar="OLDHEX=NEWHEX",
                        help="u64 id replacement, repeatable")
    parser.add_argument("--expect-size", type=int, default=None,
                        help="require the extracted payload to be exactly "
                             "this many bytes")
    parser.add_argument("--expect-parent", default=None,
                        help="require the compiled parent resource id")
    parser.add_argument("--expect-texture", action="append", default=[],
                        metavar="CHANNEL=ID",
                        help="require a compiled texture channel to reference "
                             "the given resource id after patching")
    parser.add_argument("--expect-texture-count", type=int, default=None,
                        help="require exactly this many compiled texture "
                             "bindings after patching")
    parser.add_argument("--set-variable", action="append", default=[],
                        metavar="NAME=FLOAT[,FLOAT...]",
                        help="set a reflected scalar/vector value after "
                             "validating its component count")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    type_hash = _splice.murmur64a(args.type.encode())
    name_hash = _splice.parse_name(args.resource)

    if args.extracted:
        with open(args.extracted, "rb") as extracted:
            payload = bytearray(extracted.read())
    else:
        fmt, _, data = _splice.read_bundle(args.game_bundle)
        _, _, records = _splice.walk(data, fmt)
        matches = [r for r in records
                   if r["type"] == type_hash and r["name"] == name_hash]
        if len(matches) != 1 or matches[0]["version_count"] != 1:
            print(f"resource {name_hash:016X} not found exactly once with one "
                  f"version in {args.game_bundle}", file=sys.stderr)
            return 1
        version = matches[0]["versions"][0]
        payload = bytearray(
            data[version["payload_offset"]:
                 version["payload_offset"] + version["size"]])

    print(f"extracted ({args.type}, {name_hash:016X}) = {len(payload)} bytes")
    if args.expect_size is not None and len(payload) != args.expect_size:
        print(f"payload is {len(payload)} bytes, expected "
              f"{args.expect_size}; the game data layout may have changed",
              file=sys.stderr)
        return 1

    if args.expect_parent is not None:
        try:
            actual_parent = read_parent_binding(payload)
            expected_parent = int(args.expect_parent, 16)
        except ValueError as error:
            print(f"cannot verify material parent: {error}", file=sys.stderr)
            return 1
        if actual_parent != expected_parent:
            print(f"material parent is {actual_parent:016X}, expected "
                  f"{expected_parent:016X}", file=sys.stderr)
            return 1
        print(f"verified material parent -> {expected_parent:016X}")

    for mapping in args.map:
        old_hex, _, new_hex = mapping.partition("=")
        old = struct.pack("<Q", int(old_hex, 16))
        new = struct.pack("<Q", int(new_hex, 16))
        count = payload.count(old)
        if count != 1:
            print(f"id {old_hex.upper()} occurs {count} time(s) in the "
                  f"payload; need exactly 1", file=sys.stderr)
            return 1
        payload = payload.replace(old, new)
        print(f"patched {old_hex.upper()} -> {new_hex.upper()}")

    if args.set_variable:
        try:
            variables = read_variable_bindings(payload)
        except ValueError as error:
            print(f"cannot patch material variables: {error}", file=sys.stderr)
            return 1

        for assignment in args.set_variable:
            variable_name, separator, raw_values = assignment.partition("=")
            values = ()
            try:
                variable = _parse_short_hash(variable_name)
                values = tuple(float(value) for value in raw_values.split(","))
            except ValueError:
                separator = ""
            if not separator or not values:
                print(f"invalid variable assignment {assignment!r}",
                      file=sys.stderr)
                return 1
            reflection = variables.get(variable)
            if reflection is None:
                print(f"material variable {variable_name} is missing",
                      file=sys.stderr)
                return 1
            components, offset = reflection
            if len(values) != components:
                print(f"material variable {variable_name} needs {components} "
                      f"value(s), got {len(values)}", file=sys.stderr)
                return 1
            struct.pack_into("<" + "f" * components, payload, offset, *values)
            shown = ",".join(format(value, "g") for value in values)
            print(f"set variable {variable_name} -> [{shown}]")

    if args.expect_texture:
        try:
            bindings = read_texture_bindings(payload)
        except ValueError as error:
            print(f"cannot verify texture bindings: {error}", file=sys.stderr)
            return 1

        for expectation in args.expect_texture:
            channel_name, separator, resource_hex = expectation.partition("=")
            if not separator:
                print(f"invalid texture expectation {expectation!r}",
                      file=sys.stderr)
                return 1
            try:
                channel = _parse_short_hash(channel_name)
                expected = int(resource_hex, 16)
            except ValueError:
                print(f"invalid texture expectation {expectation!r}",
                      file=sys.stderr)
                return 1
            actual = bindings.get(channel)
            if actual != expected:
                shown = "missing" if actual is None else f"{actual:016X}"
                print(f"texture channel {channel_name} is {shown}, expected "
                      f"{expected:016X}", file=sys.stderr)
                return 1
            print(f"verified texture {channel_name} -> {expected:016X}")

        if (args.expect_texture_count is not None
                and len(bindings) != args.expect_texture_count):
            print(f"material has {len(bindings)} texture bindings, expected "
                  f"{args.expect_texture_count}", file=sys.stderr)
            return 1
        if args.expect_texture_count is not None:
            print(f"verified texture binding count -> {len(bindings)}")
    elif args.expect_texture_count is not None:
        try:
            bindings = read_texture_bindings(payload)
        except ValueError as error:
            print(f"cannot verify texture binding count: {error}",
                  file=sys.stderr)
            return 1
        if len(bindings) != args.expect_texture_count:
            print(f"material has {len(bindings)} texture bindings, expected "
                  f"{args.expect_texture_count}", file=sys.stderr)
            return 1
        print(f"verified texture binding count -> {len(bindings)}")

    with open(args.out, "wb") as out:
        out.write(bytes(payload))
    print(f"wrote {len(payload)} bytes to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
