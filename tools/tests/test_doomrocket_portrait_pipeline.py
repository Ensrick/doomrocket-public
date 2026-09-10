#!/usr/bin/env python3
"""Verify artist provenance, exact portrait pixels, atlas encoding and UI wiring."""

from __future__ import annotations

import hashlib
import io
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from build_doomrocket_portrait_atlas import (  # noqa: E402
    DEFAULT_OUTPUT, DEFAULT_SOURCE, build, encode_atlas,
)
from splice_bundle_resource import walk as walk_bundle  # noqa: E402
from strip_bundle_resource import murmur64a, read_bundle  # noqa: E402

SOURCE_SHA256 = "62dfcc74716e983a865231de9e54a04cda4d009df62cde6d72a017865694d613"
ENTRY = "unit_frame_portrait_enemy_doomrocket"
ATLAS = "doomrocket_atlas"
MATERIAL = "materials/doomrocket/doomrocket_atlas"
TEXTURE = "textures/doomrocket/doomrocket_atlas"


def field(source: str, name: str) -> str:
    source = re.sub(r"//[^\r\n]*", "", source)
    match = re.search(rf'\b{re.escape(name)}\s*=\s*(?:"([^"]+)"|([^\s}}]+))', source)
    if not match:
        raise AssertionError(f"Missing descriptor field: {name}")
    return match.group(1) or match.group(2)


class DoomrocketPortraitSourceTests(unittest.TestCase):
    def test_provided_artist_file_is_preserved_exactly(self):
        self.assertEqual(hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest(), SOURCE_SHA256)
        with Image.open(DEFAULT_SOURCE) as source:
            self.assertEqual(source.size, (60, 70))
            self.assertEqual(source.mode, "RGB")
            self.assertEqual(source.convert("RGBA").getchannel("A").getextrema(), (255, 255))

    def test_atlas_portrait_pixels_and_opaque_alpha_match_source(self):
        with Image.open(DEFAULT_SOURCE) as source, Image.open(DEFAULT_OUTPUT) as atlas:
            self.assertEqual(atlas.size, (128, 128))
            self.assertEqual(atlas.mode, "RGBA")
            portrait = atlas.crop((0, 0, 60, 70))
            self.assertEqual(portrait.tobytes(), source.convert("RGBA").tobytes())

    def test_all_padding_is_transparent_black(self):
        with Image.open(DEFAULT_OUTPUT) as atlas:
            for bounds in ((60, 0, 128, 128), (0, 70, 60, 128)):
                with self.subTest(bounds=bounds):
                    padding = atlas.crop(bounds).convert("RGBA")
                    self.assertEqual(padding.tobytes(), bytes(padding.width * padding.height * 4))

    def test_dds_is_uncompressed_bgra32_with_alpha_and_one_level(self):
        payload = DEFAULT_OUTPUT.read_bytes()
        self.assertEqual(payload[:4], b"DDS ")
        self.assertEqual(len(payload), 128 + 128 * 128 * 4)
        header = struct.unpack("<31I", payload[4:128])
        self.assertEqual(header[:7], (124, 0x100F, 128, 128, 512, 0, 0))
        self.assertEqual(header[18:26], (32, 0x41, 0, 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000))
        self.assertEqual(header[26:], (0x1000, 0, 0, 0, 0))

    def test_rebuild_is_byte_identical_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = build(DEFAULT_SOURCE, Path(temporary) / "one.dds")
            second = build(DEFAULT_SOURCE, Path(temporary) / "two.dds")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), DEFAULT_OUTPUT.read_bytes())

    def test_wrong_dimensions_fail_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "wrong.png"
            output = Path(temporary) / "output.dds"
            Image.new("RGB", (61, 70)).save(source)
            with self.assertRaisesRegex(ValueError, "exactly 60x70"):
                build(source, output)
            self.assertFalse(output.exists())

    def test_encoder_preserves_semitransparent_rgba_without_alpha_compositing(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "rgba.png"
            original = Image.new("RGBA", (60, 70), (25, 100, 220, 64))
            original.save(source)
            with Image.open(io.BytesIO(encode_atlas(source))) as atlas:
                self.assertEqual(atlas.crop((0, 0, 60, 70)).tobytes(), original.tobytes())


class DoomrocketPortraitWiringTests(unittest.TestCase):
    def test_texture_descriptor_keeps_alpha_format_and_no_art_processing(self):
        descriptor = (ROOT / f"{TEXTURE}.texture").read_text(encoding="utf-8")
        self.assertEqual(field(descriptor, "filename"), TEXTURE)
        self.assertEqual(field(descriptor, "format"), "A8R8G8B8")
        self.assertEqual(field(descriptor, "apply_processing"), "false")
        self.assertEqual(field(descriptor, "enable_cut_alpha_threshold"), "false")
        self.assertEqual(field(descriptor, "srgb"), "true")

    def test_atlas_entry_retains_name_dimensions_and_top_left_uvs(self):
        atlas = LuaRuntime().execute((ROOT / f"{MATERIAL}.lua").read_text(encoding="utf-8"))
        self.assertEqual(set(atlas.keys()), {ENTRY})
        entry = atlas[ENTRY]
        self.assertEqual(tuple(entry["size"][i] for i in (1, 2)), (60, 70))
        self.assertEqual(tuple(entry["uv00"][i] for i in (1, 2)), (0, 0))
        self.assertEqual(tuple(entry["uv11"][i] for i in (1, 2)), (60 / 128, 70 / 128))

    def test_vmf_registers_normal_masked_materials_and_ingame_renderer(self):
        lua = LuaRuntime()
        lua.execute('function get_mod() return {localize=function(_,key) return key end} end')
        menu = lua.execute((ROOT / "scripts/mods/doomrocket/doomrocket_data.lua").read_text(encoding="utf-8"))
        gui = menu["custom_gui_textures"]
        registration = gui["atlases"][1]
        self.assertEqual(tuple(registration[i] for i in (1, 2, 3, 6)), (MATERIAL, ATLAS, f"{ATLAS}_masked", ATLAS))
        self.assertIn(("ingame_ui", MATERIAL), [(entry[1], entry[2]) for entry in gui["ui_renderer_injections"].values()])
        material = (ROOT / f"{MATERIAL}.material").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'diffuse_map\s*=\s*"([^"]+)"', material), [TEXTURE, TEXTURE])
        self.assertRegex(material, r'\bdoomrocket_atlas\s*=')
        self.assertRegex(material, r'\bdoomrocket_atlas_masked\s*=')

    def test_breed_keeps_the_registered_killfeed_entry(self):
        source = (ROOT / "scripts/mods/doomrocket/doomrocket.lua").read_text(encoding="utf-8")
        self.assertRegex(source, rf'UISettings\.breed_textures\[([\"\'])skaven_doomrocket\1\]\s*=\s*([\"\']){ENTRY}\2')


class DoomrocketPortraitCompiledTests(unittest.TestCase):
    def test_compiled_atlas_contains_current_art_with_observed_sdk_channel_layout(self):
        bundles = sorted((ROOT / "bundleV2").glob("*.mod_bundle"))
        if not bundles:
            self.skipTest("bundleV2 is absent; source-only checkout")
        key = murmur64a(b"texture"), murmur64a(TEXTURE.encode())
        payloads = []
        for bundle in bundles:
            bundle_format, _, contents = read_bundle(bundle)
            _, _, records = walk_bundle(contents, bundle_format)
            for record in records:
                if (record["type"], record["name"]) == key:
                    for version in record["versions"]:
                        self.assertEqual(version["stream_size"], 0)
                        start = version["payload_offset"]
                        payloads.append(contents[start:start + version["size"]])
        self.assertEqual(len(payloads), 1, "Expected exactly one packaged portrait texture")
        compiled = payloads[0]
        self.assertEqual(compiled[:4], b"DDS ")
        header = struct.unpack("<31I", compiled[4:128])
        self.assertEqual(header[2:4], (128, 128))
        self.assertEqual(header[18:26], (32, 0x41, 0, 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000))
        # The installed SDK emits RGBA byte order while retaining the legacy
        # BGRA masks, plus an engine footer. This was measured on the previous
        # atlas and must not be "corrected" by altering the artist's source.
        # This check proves the current art was compiled with the same observed
        # convention; only an in-game view can accept the renderer's colors.
        with Image.open(DEFAULT_OUTPUT) as atlas:
            expected_pixels = atlas.convert("RGBA").tobytes()
        self.assertGreaterEqual(len(compiled), 128 + len(expected_pixels))
        self.assertTrue(
            compiled[128:128 + len(expected_pixels)] == expected_pixels,
            "Packaged portrait is stale or the SDK channel convention changed",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
