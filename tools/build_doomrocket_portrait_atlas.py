#!/usr/bin/env python3
"""Pack the artist's 60x70 portrait into the existing 128x128 GUI atlas.

This is an encoding step: source pixels are copied without resizing, color
correction, background removal, alpha keying, or mip generation. RGB sources
receive an opaque alpha channel. Everything outside the existing top-left
portrait rectangle is transparent black. The output is deterministic legacy
DDS A8R8G8B8 (BGRA bytes), matching the runtime texture descriptor.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "textures/unit_frame_portrait_enemy_doomrocket.png"
DEFAULT_OUTPUT = ROOT / "textures/doomrocket/doomrocket_atlas.dds"
PORTRAIT_SIZE = (60, 70)
ATLAS_SIZE = (128, 128)


def encode_atlas(source: Path) -> bytes:
    """Return one lossless, single-level DDS image with the fixed atlas layout."""
    with Image.open(source) as portrait:
        if portrait.size != PORTRAIT_SIZE:
            raise ValueError(
                f"Portrait must be exactly {PORTRAIT_SIZE[0]}x{PORTRAIT_SIZE[1]} "
                f"pixels; got {portrait.width}x{portrait.height}: {source}"
            )
        pixels = portrait.convert("RGBA")

    atlas = Image.new("RGBA", ATLAS_SIZE, (0, 0, 0, 0))
    # No mask: paste copies source alpha instead of compositing it a second time.
    atlas.paste(pixels, (0, 0))
    width, height = ATLAS_SIZE
    header = (
        124,             # DDS_HEADER size
        0x100F,          # CAPS | HEIGHT | WIDTH | PITCH | PIXELFORMAT
        height, width, width * 4, 0, 0,
        *([0] * 11),
        32, 0x41, 0, 32,  # DDS_PIXELFORMAT: RGB | ALPHAPIXELS, no FourCC
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000,
        0x1000, 0, 0, 0, 0,  # DDSCAPS_TEXTURE; no mipmaps or cubemap
    )
    return b"DDS " + struct.pack("<31I", *header) + atlas.tobytes("raw", "BGRA")


def build(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> Path:
    """Validate and encode before changing the output file."""
    payload = encode_atlas(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true",
        help="Verify the tracked atlas matches its source without writing files.",
    )
    args = parser.parse_args()
    try:
        payload = encode_atlas(args.source)
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != payload:
                parser.exit(1, f"Atlas is missing or stale: {args.output}\n")
            operation = "Verified"
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(payload)
            operation = "Wrote"
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Portrait atlas error: {exc}\n")
    print(f"{operation} {args.output} ({len(payload)} bytes; SHA256 {hashlib.sha256(payload).hexdigest()})")


if __name__ == "__main__":
    main()
