"""Replace one resource's payload inside a compiled VT2 mod bundle.

Track D: our SDK-compiled child material renders rigid because its shader
binding was baked at compile time against the stub parent (live-verified
2026-07-16 11:24). The game's own compiled mtr_outfit child carries the real
skinning binding. This tool splices an arbitrary payload (the game child with
its texture ids patched to ours - see make_spliced_child.py) over a resource
that already exists in the built bundle, so the mod ships a child material
with the game's compile-time binding and Pusfume's textures.

Bundle layout (validated against the vt2_bundle_unpacker Rust reader):
  u32 file_count, 256-byte header,
  index: file_count x (u64 type, u64 name [VT2X: + u32 zero + u32 data_size]),
  records: (u64 type, u64 name, u32 version_count, u32 stream_offset,
            version_count x (u32 lang, u32 size, u32 stream_size),
            payloads back to back).
The index stores sizes, not offsets, so a size-changing splice only rewrites
the target record's size field and its index data_size.

Usage:
  py splice_bundle_resource.py <bundle> --type material \
      --name <resource path | hash:16-hex> --payload <file> [--dry-run]

Exits non-zero if the resource is not found exactly once or verification
fails.
"""

import argparse
import struct
import sys

import importlib.util
import pathlib

_STRIP = pathlib.Path(__file__).resolve().parent / "strip_bundle_resource.py"
_spec = importlib.util.spec_from_file_location("strip_bundle_resource", _STRIP)
_strip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_strip)

murmur64a = _strip.murmur64a
read_bundle = _strip.read_bundle
write_bundle = _strip.write_bundle
VT2_FORMAT = _strip.VT2_FORMAT
VT2X_FORMAT = _strip.VT2X_FORMAT

HEADER_SIZE = 256


def parse_name(value):
    """Accept a resource path string or 'hash:<16 hex digits>'."""
    if value.lower().startswith("hash:"):
        return int(value[5:], 16)
    return murmur64a(value.encode())


def walk(data, fmt):
    """Yield dicts describing the bundle index and records.

    Returns (file_count, index_entries, records); every offset refers to the
    decompressed image.
    """
    (file_count,) = struct.unpack_from("<I", data, 0)
    offset = 4 + HEADER_SIZE

    index_entries = []
    for _ in range(file_count):
        type_hash, name_hash = struct.unpack_from("<QQ", data, offset)
        entry = {"offset": offset, "type": type_hash, "name": name_hash,
                 "data_size": None}
        offset += 16
        if fmt == VT2X_FORMAT:
            zero, data_size = struct.unpack_from("<II", data, offset)
            if zero != 0:
                raise SystemExit(f"index entry at {entry['offset']} has "
                                 f"non-zero reserved field {zero:08X}")
            entry["data_size"] = data_size
            entry["data_size_offset"] = offset + 4
            offset += 8
        else:
            offset += 4
        index_entries.append(entry)

    records = []
    for expected in index_entries:
        type_hash, name_hash = struct.unpack_from("<QQ", data, offset)
        if type_hash != expected["type"] or name_hash != expected["name"]:
            raise SystemExit(
                f"record at {offset} is ({type_hash:016X}, {name_hash:016X}) "
                f"but index expects ({expected['type']:016X}, "
                f"{expected['name']:016X})")
        version_count, stream_offset = struct.unpack_from("<II", data, offset + 16)
        record = {"offset": offset, "type": type_hash, "name": name_hash,
                  "version_count": version_count, "versions": []}
        cursor = offset + 24
        total_payload = 0
        for _ in range(version_count):
            lang, size, stream_size = struct.unpack_from("<III", data, cursor)
            record["versions"].append(
                {"def_offset": cursor, "lang": lang, "size": size,
                 "stream_size": stream_size})
            cursor += 12
            total_payload += size
        payload_offset = cursor
        for version in record["versions"]:
            version["payload_offset"] = payload_offset
            payload_offset += version["size"]
        record["end"] = payload_offset
        record["total_payload"] = total_payload
        records.append(record)
        offset = payload_offset

    if offset != len(data):
        raise SystemExit(
            f"bundle walk ended at {offset} but image is {len(data)} bytes")
    return file_count, index_entries, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--type", required=True,
                        help="resource type (e.g. material) or hash:<16 hex>")
    parser.add_argument("--name", required=True,
                        help="resource path, or hash:<16-hex-digit id>")
    parser.add_argument("--payload", required=True,
                        help="file whose bytes replace the resource payload")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    type_hash = parse_name(args.type)
    name_hash = parse_name(args.name)
    with open(args.payload, "rb") as payload_file:
        payload = payload_file.read()
    if not payload:
        raise SystemExit("refusing to splice an empty payload")

    fmt, padding, data = read_bundle(args.bundle)
    _, index_entries, records = walk(data, fmt)

    matches = [i for i, r in enumerate(records)
               if r["type"] == type_hash and r["name"] == name_hash]
    if len(matches) != 1:
        print(f"resource ({args.type}, {args.name}) found {len(matches)} "
              f"time(s); need exactly 1", file=sys.stderr)
        return 1

    record = records[matches[0]]
    if record["version_count"] != 1:
        print(f"resource has {record['version_count']} versions; only "
              f"single-version resources are supported", file=sys.stderr)
        return 1

    version = record["versions"][0]
    print(f"{args.bundle}: splicing ({args.type}, {name_hash:016X}) "
          f"{version['size']} -> {len(payload)} bytes")

    if args.dry_run:
        print("dry run; bundle unchanged")
        return 0

    patched = bytearray(data)
    # Payload swap first (offsets shift after this point).
    start = version["payload_offset"]
    end = start + version["size"]
    patched[start:end] = payload
    # Record's version-definition size field (offset unaffected by the swap:
    # definitions precede payloads).
    struct.pack_into("<I", patched, version["def_offset"] + 4, len(payload))
    # Index data_size (VT2X only; VT2 index carries no size).
    entry = index_entries[matches[0]]
    if entry["data_size"] is not None:
        if entry["data_size"] != record["total_payload"]:
            print(f"index data_size {entry['data_size']} != walked payload "
                  f"total {record['total_payload']}; aborting", file=sys.stderr)
            return 1
        struct.pack_into("<I", patched, entry["data_size_offset"], len(payload))

    patched = bytes(patched)
    write_bundle(args.bundle, fmt, padding, patched)

    _, _, verify_data = read_bundle(args.bundle)
    _, _, verify_records = walk(verify_data, fmt)
    spliced = verify_records[matches[0]]
    got = verify_data[spliced["versions"][0]["payload_offset"]:
                      spliced["versions"][0]["payload_offset"]
                      + spliced["versions"][0]["size"]]
    if got != payload:
        print("post-write verification failed: payload mismatch", file=sys.stderr)
        return 1

    print(f"spliced {len(payload)} bytes; walk and payload round-trip verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
