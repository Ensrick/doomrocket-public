"""Rename a resource identity inside a compiled VT2 mod bundle.

The SDK material compiler requires a stub parent SOURCE at the donor's exact
path and then bundles the compiled stub as a package dependency AT THE GAME'S
RESOURCE PATH, where it shadows the real game resource (2026-07-16 live test:
black rigid body). This tool decompresses the bundle, rewrites every
(type_hash, name_hash) pair of the stub to an unused name hash - covering the
bundle index, the file data header, and compiled package listings - and
recompresses. The compiled child material's parent REFERENCE is a bare name
hash without the preceding type hash, so it is untouched and resolves against
the game's copy once the stub identity is gone.

The same mechanism runs in reverse for donor texture shadowing: renaming our
compiled atlas textures' identities TO the game's texture ids makes the game's
own mtr_outfit child bind Janfon's maps once our package registers them first.
Texture references inside compiled materials are bare 8-byte name hashes, so
that direction uses --bare, which rewrites every occurrence of the name hash
(bundle index, file header, package listings, and material references alike).
--new-hash takes a literal hash for targets whose path string is unknown
(the donor texture paths are not in any dictionary; their ids came from
parsing the game's compiled mtr_outfit).

Usage:
  py strip_bundle_resource.py <bundle> --type material \
      --old <resource path> --new <resource path> [--expect N] [--dry-run]
  py strip_bundle_resource.py <bundle> --type texture --bare \
      --old <resource path> --new-hash <16-hex-digit id> [--expect N]

Exits non-zero if the occurrence count does not match --expect (when given)
or if nothing was replaced.
"""

import argparse
import struct
import sys
import zlib

MASK = (1 << 64) - 1
VT2_FORMAT = 0xF0000005
VT2X_FORMAT = 0xF0000006
SUPPORTED_FORMATS = (VT2_FORMAT, VT2X_FORMAT)
BLOCK_RAW_SIZE = 0x10000


def murmur64a(key: bytes, seed: int = 0) -> int:
    m = 0xC6A4A7935BD1E995
    r = 47
    h = (seed ^ (len(key) * m)) & MASK
    n = len(key) // 8
    for i in range(n):
        k = int.from_bytes(key[i * 8 : i * 8 + 8], "little")
        k = (k * m) & MASK
        k ^= k >> r
        k = (k * m) & MASK
        h ^= k
        h = (h * m) & MASK
    tail = key[n * 8 :]
    if tail:
        h ^= int.from_bytes(tail, "little")
        h = (h * m) & MASK
    h ^= h >> r
    h = (h * m) & MASK
    h ^= h >> r
    return h


def read_bundle(path):
    with open(path, "rb") as bundle_file:
        raw = bundle_file.read()
    fmt, inflate_size = struct.unpack_from("<II", raw, 0)
    if fmt not in SUPPORTED_FORMATS:
        raise SystemExit(f"unsupported bundle format 0x{fmt:08X}")

    padding = raw[8:12]
    data = bytearray()
    offset = 12

    while offset < len(raw):
        (block_size,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        if block_size == BLOCK_RAW_SIZE:
            raise SystemExit(
                "bundle contains a raw 0x10000 block; refusing to rewrite it blind"
            )
        block = raw[offset : offset + block_size]
        if len(block) != block_size:
            raise SystemExit("truncated block")
        offset += block_size
        data.extend(zlib.decompress(block))

    if len(data) < inflate_size:
        raise SystemExit(f"decompressed {len(data)} bytes, header claims {inflate_size}")
    del data[inflate_size:]
    return fmt, padding, bytes(data)


def write_bundle(path, fmt, padding, data):
    out = bytearray()
    out += struct.pack("<II", fmt, len(data))
    out += padding
    for start in range(0, len(data), BLOCK_RAW_SIZE):
        block = zlib.compress(data[start : start + BLOCK_RAW_SIZE], 9)
        if len(block) >= BLOCK_RAW_SIZE:
            raise SystemExit(
                f"compressed block would be {len(block)} bytes (>= 0x10000); aborting"
            )
        out += struct.pack("<I", len(block))
        out += block
    with open(path, "wb") as bundle_file:
        bundle_file.write(bytes(out))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--type", required=True, help="resource type, e.g. material")
    parser.add_argument("--old", required=True, help="resource path to rename")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--new", help="replacement resource path")
    group.add_argument("--new-hash",
                       help="literal 16-hex-digit replacement name hash")
    parser.add_argument("--bare", action="store_true",
                        help="rewrite every bare 8-byte name hash occurrence "
                             "instead of (type, name) pairs")
    parser.add_argument("--expect", type=int, default=None,
                        help="require exactly N occurrences")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    type_hash = murmur64a(args.type.encode())
    old_hash = murmur64a(args.old.encode())
    if args.new_hash is not None:
        new_hash = int(args.new_hash, 16)
        new_label = args.new_hash.upper()
    else:
        new_hash = murmur64a(args.new.encode())
        new_label = args.new

    if args.bare:
        old_needle = struct.pack("<Q", old_hash)
        new_needle = struct.pack("<Q", new_hash)
        what = f"bare name hash of {args.old}"
    else:
        old_needle = struct.pack("<QQ", type_hash, old_hash)
        new_needle = struct.pack("<QQ", type_hash, new_hash)
        what = f"({args.type}, {args.old})"

    fmt, padding, data = read_bundle(args.bundle)
    count = data.count(old_needle)
    preexisting_new = data.count(new_needle)

    print(f"{args.bundle}: {count} occurrence(s) of {what}")

    if args.expect is not None and count != args.expect:
        print(f"expected {args.expect} occurrence(s), found {count}", file=sys.stderr)
        return 1
    if count == 0:
        if args.expect == 0:
            return 0
        print("nothing to replace", file=sys.stderr)
        return 1

    if args.dry_run:
        print("dry run; bundle unchanged")
        return 0

    patched = data.replace(old_needle, new_needle)
    assert len(patched) == len(data)
    write_bundle(args.bundle, fmt, padding, patched)

    _, _, verify = read_bundle(args.bundle)
    if (verify.count(old_needle) != 0
            or verify.count(new_needle) != preexisting_new + count):
        print("post-write verification failed", file=sys.stderr)
        return 1

    print(f"renamed to {new_label}; {count} occurrence(s) rewritten; "
          f"round-trip verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
