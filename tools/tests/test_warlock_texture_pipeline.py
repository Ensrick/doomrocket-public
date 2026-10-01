#!/usr/bin/env python3
"""Offline regressions for the Warlock texture/material adapter pipeline.

These tests preserve the native dark-pact Ratling parent contract established
by the live material probe:

* 02af90f8: sRGB base color;
* 8bf37d8e: linear tangent normal, roughness in alpha;
* 27b67fd2: linear metallic/AO/feature data, emission mask in alpha.

They intentionally test source assets and splice inputs rather than rendered
screenshots so a bad channel conversion fails before build/deploy.
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    from PIL import Image, ImageChops
except ImportError as exc:  # Make a missing build dependency actionable.
    raise SystemExit("Pillow is required for Warlock texture regressions") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
TEXTURE_DIR = REPO_ROOT / "textures" / "warlock_bombardier"
PROP_TEXTURE_DIR = REPO_ROOT / "textures" / "rocket"
ART_ROOT = REPO_ROOT.parent / "_warlock_bombardier_art" / "crunch_textures"

sys.path.insert(0, str(TOOLS_DIR))
from build_warlock_texture_adapters import build as build_adapters  # noqa: E402
from strip_bundle_resource import murmur64a  # noqa: E402


# SHA-256 over decoded RGBA bytes, not PNG container bytes. Intentional master
# art changes must regenerate the adapters and update this reviewed baseline.
EXPECTED_RGBA = {
    "wb_armor_df": "177596753ab3041564d4fb924af4c7ee1e6efe731eebd55074c42df2a1ae4d44",
    "wb_armor_nm": "e6dea31699ce3c8335b341170300853091e3f462cc7eda1d0f8f5974475a7c8f",
    "wb_armor_ma": "5b76c74645fe11beee4e09dd987b3d8cfa1f088facdc8b7ab06d03a0fb2e8988",
    "wb_backpack_df": "a95c864e8469488c10cd187e16c0b6929315f8c119db05be3807e65c0a456e24",
    "wb_backpack_nm": "09098aa7262c90fee6fcd03dcc5cdd845468445e2102bcd3f52c4aa08a6181b2",
    "wb_backpack_ma": "1be155bf010ba3d650c493260b1e3f0a97de6e8d0e07a2c993fd399eb64a84b3",
}

# These two alpha digests are the original MASE alpha channels. The Fix files
# are RGB-only and would otherwise silently become alpha=255 during RGBA load.
EXPECTED_MASE_ALPHA = {
    "armor": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "backpack": "c9d6150d407f6a740e235eecae420fd7128be1f94c75a812a1ed2dd3f47f39fa",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def texture_field(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^\s*{re.escape(name)}\s*=\s*(?:\"([^\"]+)\"|([^\s/}}]+))",
        source,
    )
    if not match:
        raise AssertionError(f"texture descriptor has no {name!r} field")
    return match.group(1) or match.group(2)


def without_line_comments(source: str) -> str:
    return re.sub(r"//[^\r\n]*", "", source)


def named_block(source: str, name: str) -> str:
    match = re.search(rf"(?s)\b{re.escape(name)}\s*=\s*\{{(.*?)\}}", source)
    if not match:
        raise AssertionError(f"missing {name} block")
    return match.group(1)


class WarlockSourceTextureTests(unittest.TestCase):
    def test_committed_pixel_baseline(self) -> None:
        for name, expected in EXPECTED_RGBA.items():
            with self.subTest(texture=name):
                image = rgba(TEXTURE_DIR / f"{name}.png")
                self.assertEqual(sha256(image.tobytes()), expected)
                self.assertEqual(image.size, (2048, 2048))

    def test_mask_rgb_is_fix_rgb_and_alpha_is_original_mase_mask(self) -> None:
        for target in ("armor", "backpack"):
            with self.subTest(texture=target):
                mask = rgba(TEXTURE_DIR / f"wb_{target}_ma.png")
                fix = rgba(TEXTURE_DIR / f"wb_{target}_s.png")

                self.assertIsNone(
                    ImageChops.difference(mask.convert("RGB"), fix.convert("RGB")).getbbox(),
                    f"{target}: MA RGB must remain the artist's MASE_Fix RGB",
                )
                self.assertEqual(
                    sha256(mask.getchannel("A").tobytes()),
                    EXPECTED_MASE_ALPHA[target],
                    f"{target}: MA alpha must remain the original MASE alpha",
                )

        armor_alpha = rgba(TEXTURE_DIR / "wb_armor_ma.png").getchannel("A")
        self.assertEqual(armor_alpha.getextrema(), (0, 0), "armor must not emit")

        backpack_alpha = rgba(TEXTURE_DIR / "wb_backpack_ma.png").getchannel("A")
        self.assertEqual(backpack_alpha.getextrema(), (0, 136))
        nonzero = sum(value != 0 for value in backpack_alpha.tobytes())
        self.assertEqual(nonzero, 130_443, "backpack emission mask must stay localized")
        self.assertLess(nonzero, backpack_alpha.width * backpack_alpha.height // 10)

    @unittest.skipUnless(ART_ROOT.is_dir(), "Crunch master-art checkout is not present")
    def test_adapter_rebuild_matches_committed_outputs(self) -> None:
        """Exercise the adapter itself without mutating the working tree."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "body"
            prop_output = Path(temporary) / "props"
            with redirect_stdout(io.StringIO()):
                build_adapters(ART_ROOT, output, prop_output)
            for name in EXPECTED_RGBA:
                with self.subTest(texture=name):
                    self.assertEqual(
                        rgba(output / f"{name}.png").tobytes(),
                        rgba(TEXTURE_DIR / f"{name}.png").tobytes(),
                    )
            for target in ("weapon", "rocket"):
                suffixes = ("df", "nm", "e", "r", "m", "ao")
                if target == "weapon":
                    suffixes += ("ma",)
                for suffix in suffixes:
                    name = f"wb_{target}_{suffix}.png"
                    with self.subTest(texture=name):
                        self.assertEqual(
                            rgba(prop_output / name).tobytes(),
                            rgba(PROP_TEXTURE_DIR / name).tobytes(),
                        )


class WarlockTextureDescriptorTests(unittest.TestCase):
    def test_runtime_maps_use_bc7_and_correct_color_space(self) -> None:
        expected = {
            "wb_armor_df": "true",
            "wb_armor_nm": "false",
            "wb_armor_ma": "false",
            "wb_backpack_df": "true",
            "wb_backpack_nm": "false",
            "wb_backpack_ma": "false",
        }
        for name, expected_srgb in expected.items():
            with self.subTest(texture=name):
                source = (TEXTURE_DIR / f"{name}.texture").read_text(encoding="utf-8")
                self.assertEqual(
                    texture_field(source, "filename"),
                    f"textures/warlock_bombardier/{name}",
                )
                self.assertEqual(texture_field(source, "format"), "BC7")
                self.assertEqual(texture_field(source, "srgb"), expected_srgb)
                self.assertEqual(texture_field(source, "enable_cut_alpha_threshold"), "false")

    def test_alpha_bearing_maps_are_not_dxt1_or_bc5(self) -> None:
        # Normal alpha is roughness; MA alpha is emission. Either lossy format
        # choice would silently destroy one of those native parent inputs.
        for target in ("armor", "backpack"):
            for suffix in ("nm", "ma"):
                with self.subTest(texture=f"{target}_{suffix}"):
                    source = (
                        TEXTURE_DIR / f"wb_{target}_{suffix}.texture"
                    ).read_text(encoding="utf-8")
                    self.assertNotIn(texture_field(source, "format"), {"DXT1", "BC5"})


class WarlockRuntimeResidencyTests(unittest.TestCase):
    def test_only_custom_armor_and_backpack_maps_are_preflighted(self) -> None:
        hooks = (
            REPO_ROOT / "scripts" / "mods" / "doomrocket" / "utils" / "hooks.lua"
        ).read_text(encoding="utf-8")
        block = named_block(hooks, "WARLOCK_CUSTOM_TEXTURES")
        actual = set(re.findall(r'"([^"]+)"', block))
        expected = {
            f"textures/warlock_bombardier/wb_{target}_{suffix}"
            for target in ("armor", "backpack")
            for suffix in ("df", "nm", "ma")
        }
        self.assertEqual(actual, expected)
        self.assertNotIn("wb_backpack_e", block)
        self.assertNotIn("wb_skin", block, "skin uses exact native Stormvermin maps")

    def test_bootstrap_loads_both_exact_native_donor_packages(self) -> None:
        source = (
            REPO_ROOT / "scripts" / "mods" / "doomrocket" / "doomrocket.lua"
        ).read_text(encoding="utf-8")
        packages = (
            "units/beings/player/dark_pact_skins/skaven_ratlinggunner/"
            "skin_1001/third_person/chr_third_person_mesh",
            "resource_packages/breeds/skaven_storm_vermin",
        )
        for package in packages:
            with self.subTest(package=package):
                call = f'Managers.package:load("{package}", "global")'
                self.assertEqual(source.count(call), 1)


class WarlockMaterialSpliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (TOOLS_DIR / "splice_warlock_materials.ps1").read_text(
            encoding="utf-8"
        )
        opaque_match = re.search(
            r"(?s)\$armorAndBackpack\s*=\s*@\((.*?)\)\s*"
            r"foreach\s*\(\$mat\s+in\s+\$armorAndBackpack\)",
            cls.source,
        )
        if not opaque_match:
            raise AssertionError("could not parse $armorAndBackpack splice table")
        row_pattern = re.compile(
            r'@\{\s*Name\s*=\s*"(?P<name>wb_[^"]+)";\s*'
            r'Df\s*=\s*"(?P<df>[0-9A-F]{16})";\s*'
            r'Nm\s*=\s*"(?P<nm>[0-9A-F]{16})";\s*'
            r'Ma\s*=\s*"(?P<ma>[0-9A-F]{16})";\s*'
            r'EmVar\s*=\s*"(?P<emvar>[^"]+)"\s*\}',
            re.IGNORECASE,
        )
        cls.rows = {
            row.group("name"): row.groupdict()
            for row in row_pattern.finditer(opaque_match.group(1))
        }

    def test_exact_native_donor_bundle_and_resource_provenance(self) -> None:
        donor_table = re.search(
            r"(?s)\$donors\s*=\s*@\((.*?)\)\s*foreach\s*\(\$donor\s+in\s+\$donors\)",
            self.source,
        )
        self.assertIsNotNone(donor_table)
        source = donor_table.group(1)
        required = (
            'Key = "ratling"',
            'Bundle = "64f9019d56c8ce61"',
            'Includes = @("*0488D08E3CE5CBC3*")',
            'Name = "0488D08E3CE5CBC3.material"; Sha256 = "0D1DA98E59642E000E954A3438A28EDAC63982F1526937DE6A3893C6F0F144EC"',
            'Key = "stormvermin"',
            'Bundle = "c43c291e4cc55d96"',
            'Name = "2CC5FCB51388A255.material"; Sha256 = "15BDECC1897BD62E2EBA055B38388840A95FCA3395CFE9E25A442817ECF16295"',
            'Name = "EB663E2D6E5EB732.material"; Sha256 = "64E8E88C1D17A54C2A774B3F1FF090B994CAF6620BD8E5C0E857C6D84C3270D2"',
            'Name = "3EB079055472D4C3.material"; Sha256 = "680284D028524BB224667DD4FF14013CF3C52C66CA62CE83E6C392C6CE47571A"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_ratling_payload_has_exact_parent_and_seven_bindings(self) -> None:
        match = re.search(
            r"(?s)foreach \(\$mat in \$armorAndBackpack\) \{(.*?)"
            r'Write-Host "\[splice\] payload wb_skin_child',
            self.source,
        )
        self.assertIsNotNone(match)
        source = match.group(1)
        self.assertIn('"--extracted", $ratlingPayload', source)
        self.assertIn('"--expect-size", "768", "--expect-parent", "3D25339231384C80"', source)
        self.assertIn('"--expect-texture-count", "7"', source)
        bindings = set(re.findall(r'"--expect-texture", "([^"]+)"', source))
        self.assertEqual(
            bindings,
            {
                "6A35771D=0B35F2C32178BB63",
                "1E706DD3=19ADB9C889F644A0",
                "E25C59E9=2E82F037A3245005",
                "EEE29B95=2E82F037A3245005",
                "texture_map_02af90f8=$($mat.Df)",
                "texture_map_27b67fd2=$($mat.Ma)",
                "texture_map_8bf37d8e=$($mat.Nm)",
            },
        )

    def test_opaque_table_ids_are_hashes_of_the_named_runtime_maps(self) -> None:
        self.assertEqual(set(self.rows), {"wb_armor", "wb_backpack", "wb_hose"})
        for name, row in self.rows.items():
            for key in ("df", "nm", "ma"):
                with self.subTest(material=name, channel=key):
                    path = (f"textures/rocket/wb_weapon_{key}" if name == "wb_hose"
                            else f"textures/warlock_bombardier/{name}_{key}")
                    expected = f"{murmur64a(path.encode('utf-8')):016X}"
                    self.assertEqual(row[key].upper(), expected)

    def test_native_parent_channels_bind_df_nm_ma_in_that_order(self) -> None:
        required = (
            '"--map", "C554581405CC782C=$($mat.Df)"',
            '"--map", "6F873A2AA7CA611C=$($mat.Nm)"',
            '"--map", "8ABCC048427DAE38=$($mat.Ma)"',
            '"--expect-texture", "texture_map_02af90f8=$($mat.Df)"',
            '"--expect-texture", "texture_map_8bf37d8e=$($mat.Nm)"',
            '"--expect-texture", "texture_map_27b67fd2=$($mat.Ma)"',
            '"--set-variable", "C985395A=$($mat.EmVar)"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.source)

    def test_separate_emissive_rgb_can_never_replace_packed_ma(self) -> None:
        self.assertNotIn("wb_backpack_e", self.source)
        self.assertNotIn("4F71D9C786EFF4D3", self.source)
        self.assertNotRegex(self.source, r"(?i)27b67fd2[^\r\n]*(?:\.Em\b|backpack_e)")

    def test_emissive_color_is_fitted_green_hue_not_white_eight(self) -> None:
        self.assertEqual(self.rows["wb_armor"]["emvar"], "0,0,0")
        self.assertEqual(self.rows["wb_hose"]["emvar"], "0,0,0")
        backpack = tuple(float(value) for value in self.rows["wb_backpack"]["emvar"].split(","))
        self.assertEqual(len(backpack), 3)
        for actual, expected in zip(backpack, (0.61224258, 1.32689383, 0.24368675)):
            self.assertAlmostEqual(actual, expected, places=8)
        self.assertNotEqual(len(set(backpack)), 1, "emissive color must not be white")
        self.assertNotIn('EmVar = "8,8,8"', self.source)

    def test_skin_uses_the_exact_stormvermin_source_material(self) -> None:
        skin_block = re.search(
            r'(?s)Write-Host "\[splice\] payload wb_skin_child.*?'
            r'Assert-Sha256 \(Join-Path \$buildDir "wb_skin_child\.payload"\) '
            r'"15BDECC1897BD62E2EBA055B38388840A95FCA3395CFE9E25A442817ECF16295"',
            self.source,
        )
        self.assertIsNotNone(skin_block, "skin child must retain its exact donor checksum")
        source = skin_block.group(0)
        self.assertIn('"--extracted", $skinPayload', source)
        self.assertIn('"--expect-size", "496", "--expect-parent", "EE15D2DA0DB8191E"', source)
        self.assertIn('"--map", "ED67ABE0A2542484=ED67ABE0A2542484"', source)
        self.assertNotIn("wb_skin_ma", self.source)

    def test_fur_uses_exact_payload_parent_hash_and_all_bindings(self) -> None:
        match = re.search(
            r'(?s)Write-Host "\[splice\] payload wb_fur_child(.*?)'
            r'Assert-Sha256 \(Join-Path \$buildDir "wb_fur_child\.payload"\) '
            r'"64E8E88C1D17A54C2A774B3F1FF090B994CAF6620BD8E5C0E857C6D84C3270D2"',
            self.source,
        )
        self.assertIsNotNone(match)
        source = match.group(1)
        self.assertIn('"--extracted", $furPayload', source)
        self.assertIn('"--expect-size", "416", "--expect-parent", "3BC475F93930640D"', source)
        self.assertIn('"--expect-texture-count", "5"', source)
        self.assertEqual(
            set(re.findall(r'"--expect-texture", "([^"]+)"', source)),
            {
                "5940AA57=328E22775ECE4D7C",
                "1E706DD3=19ADB9C889F644A0",
                "374548C2=4E1893E178945A92",
                "50736EB4=1916CFCA6ED85BFD",
                "0526F37D=E7AC0D635A39E926",
            },
        )

    def test_whiskers_use_exact_payload_parent_hash_and_all_bindings(self) -> None:
        match = re.search(
            r'(?s)Write-Host "\[splice\] payload wb_whiskers_child(.*?)'
            r'Assert-Sha256 \(Join-Path \$buildDir "wb_whiskers_child\.payload"\) '
            r'"680284D028524BB224667DD4FF14013CF3C52C66CA62CE83E6C392C6CE47571A"',
            self.source,
        )
        self.assertIsNotNone(match)
        source = match.group(1)
        self.assertIn('"--extracted", $whiskersPayload', source)
        self.assertIn('"--expect-size", "128", "--expect-parent", "64058AD3567FB490"', source)
        self.assertIn('"--expect-texture-count", "3"', source)
        self.assertEqual(
            set(re.findall(r'"--expect-texture", "([^"]+)"', source)),
            {
                "68F2A5BA=A3854CB4540799DF",
                "CDAA7E64=3E851D59331DC868",
                "552EAA73=FE1EAB79ADD8215B",
            },
        )


class RocketSourceMaterialCoverageTests(unittest.TestCase):
    EXPECTED_SLOTS = {
        "pRocketLauncher.unit": {"DoomRocket_Weapon", "DoomRocket_Rocket"},
        "SM_Rocket.unit": {"DoomRocket_Rocket"},
    }

    def test_every_fbx_slot_has_a_valid_source_material_fallback(self) -> None:
        unit_dir = REPO_ROOT / "units" / "rocket"
        for filename, expected_slots in self.EXPECTED_SLOTS.items():
            with self.subTest(unit=filename):
                source = without_line_comments((unit_dir / filename).read_text(encoding="utf-8"))
                materials = dict(
                    re.findall(r'(\w+)\s*=\s*"([^"]+)"', named_block(source, "materials"))
                )
                slots = set(re.findall(r'\bslot\d+\s*=\s*"([^"]+)"', named_block(source, "mat_slots")))

                self.assertEqual(slots, expected_slots)
                self.assertEqual(
                    slots - materials.keys(),
                    set(),
                    "unmapped FBX material slots produce MeshObject lookup warnings before Lua runs",
                )
                for slot in slots:
                    material = materials[slot]
                    self.assertNotEqual(
                        material,
                        "materials/green",
                        "transparent emissive green is not a safe rocket fallback",
                    )
                    material_path = REPO_ROOT / f"{material}.material"
                    self.assertTrue(
                        material_path.is_file(),
                        f"{slot} maps to missing source material {material}",
                    )
                    material_source = material_path.read_text(encoding="utf-8")
                    self.assertEqual(
                        texture_field(material_source, "parent_material"),
                        "core/stingray_renderer/shader_import/standard",
                        f"{slot} fallback must use the opaque standard parent",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
