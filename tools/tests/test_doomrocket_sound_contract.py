#!/usr/bin/env python3
"""Offline contracts for the Doomrocket custom sound integration.

The game is the final authority for spatialisation and lifecycle behaviour,
but a candidate must not reach a tester with a missing bank, a commented-out
package dependency, stale marker-bearing source audio, or the old Warpfire
placeholder events.  These checks intentionally inspect both the authored
Wwise products and the Lua call sites that consume them.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = REPO_ROOT / "tools"
BUNDLE_ROOT = REPO_ROOT / "bundleV2"
WWISE_ROOT = REPO_ROOT / "wwise"
SOURCE_AUDIO_ROOT = REPO_ROOT / "audio_src" / "doomrocket"
PACKAGE_PATH = REPO_ROOT / "resource_packages" / "doomrocket" / "doomrocket.package"
BOOTSTRAP_PATH = REPO_ROOT / "scripts" / "mods" / "doomrocket" / "doomrocket.lua"
PROJECTILE_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "projectile_rocket.lua"
)
AUDIO_RUNTIME_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "doomrocket_audio.lua"
)
HOOKS_PATH = REPO_ROOT / "scripts" / "mods" / "doomrocket" / "utils" / "hooks.lua"
DEATH_REACTIONS_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "death_reactions.lua"
)
RPC_PATH = REPO_ROOT / "scripts" / "mods" / "doomrocket" / "rpc.lua"
LAUNCH_ACTION_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "behavior"
    / "nodes"
    / "skaven_doomrocket"
    / "bt_doomrocket_launch_action.lua"
)
BREED_PATH = REPO_ROOT / "scripts" / "mods" / "doomrocket" / "breeds" / "skaven_doomrocket.lua"

BANK_PATH = WWISE_ROOT / "doomrocket.wwise_bank"
BANK_METADATA_PATH = WWISE_ROOT / "doomrocket.wwise_bank_metadata"
DEPENDENCY_PATH = WWISE_ROOT / "doomrocket.wwise_dep"
INIT_BANK_PATH = WWISE_ROOT / "Init.wwise_bank"
INIT_DEPENDENCY_PATH = WWISE_ROOT / "Init.wwise_dep"
PROJECT_METADATA_PATH = WWISE_ROOT / "doomrocket_project.wwise_metadata"
MANIFEST_PATH = WWISE_ROOT / "doomrocket.bank_manifest.json"
BUILDER_PATH = REPO_ROOT / "tools" / "build_doomrocket_wwise_bank.py"

sys.path.insert(0, str(TOOLS_ROOT))

from splice_bundle_resource import walk as walk_bundle  # noqa: E402
from strip_bundle_resource import murmur64a, read_bundle  # noqa: E402

VOICE_COMBAT_EVENTS = {
    "Play_enemy_doomrocket_voice_01",
    "Play_enemy_doomrocket_voice_02",
    "Play_enemy_doomrocket_voice_03",
    "Play_enemy_doomrocket_voice_04",
    "Play_enemy_doomrocket_voice_05",
    "Play_enemy_doomrocket_voice_laugh_01",
}
VOICE_DEATH_EVENTS = {
    "Play_enemy_doomrocket_voice_death_01",
    "Play_enemy_doomrocket_voice_death_02",
}
EXPECTED_EVENTS = {
    "Play_enemy_doomrocket_backpack_loop",
    "Stop_enemy_doomrocket_backpack_loop",
    "Play_enemy_doomrocket_launch",
    "Play_enemy_doomrocket_impact",
} | VOICE_COMBAT_EVENTS | VOICE_DEATH_EVENTS

# SHA-256 pins the clean, markerless mono handoff from 2026-08-25.  The old
# files in Downloads had different hashes and embedded full-file `smpl` loops.
EXPECTED_SOURCE_HASHES = {
    "SFX_unit_WarlockEngineer_DoomRocket_backpack_loop.wav":
        "483d8ccb127ba01cd172c2b7e47f6f6d0eaf476e13e678032092df12771c173e",
    "SFX_unit_WarlockEngineer_DoomRocket_shot.wav":
        "e6f2a145ba4c4d1ca09b83de11b829c187fc27ba4bf1b7cbe04a77a1fdfcc883",
    "SFX_unit_WarlockEngineer_DoomRocket_Explosion_Ground.wav":
        "662c912f3c6804838e02dca97c0f33da36cea01ffb49e7c34257c7771c9db6fb",
    "SFX_unit_WarlockEngineer_DoomRocket_Explosion_Air.wav":
        "ccd097981acd434fa182b3fb0b85b2b1872a2800f16cffc87fda7560f33ac2fe",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_01.wav":
        "f11d5da39d082ff4d865417bdb03d701cbe455cd137846c544edc96914854ebb",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_02.wav":
        "0b17488038ab637c24663600f22a8dcd6e28f43423e82a2e8e8f4f368dfb80bf",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_03.wav":
        "9e2cd95cecd3bc638392eb649fb9d228619a455ed67106b3077b0cca5d1dc294",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_04.wav":
        "5a64d634353b202c269ef9e873f50202558963314559bac4436c2533de0514c7",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_05.wav":
        "441b4e819d6095dd98451d3906be193c80beadbd772d79595b520f73a20b4279",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_laugh_01.wav":
        "965de6b579d01afc1cd6c25755ed42168b371c4869bf901155d186a2b9163c53",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_death_01.wav":
        "22724110ea478ec2f7af6cf1fe1a4d21a7bb57a6c1ae9fc86cf3131c88f5ebb7",
    "SFX_unit_WarlockEngineer_DoomRocket_voice_death_02.wav":
        "312ae63d60942c090e5590f006893456c81736d6338b6fa122f0b538cf527fbf",
}

FORBIDDEN_PLACEHOLDER_EVENTS = {
    "Play_enemy_warpfire_thrower_shoot",
    "player_enemy_warpfire_thrower_shoot_end",
}
SAFE_IMPACT_FALLBACK_EVENT = "Play_enemy_combat_warpfire_backpack_explode"

# Stingray stores the BKHD generator field XOR-obfuscated. The current VT2 SDK
# plugin (SHA-256 4a1eb054...dc08) contains the little-endian XOR word
# 0x9211BCAC at file offsets 0x15026 and 0x1510F. A native Ratling bank and the
# proven Pusfume/Loremasters custom banks each store 0x9211BC28 in BKHD, so the
# independently recovered generator version is 0x9211BC28 ^ 0x9211BCAC = 132.
VT2_BKHD_XOR_WORD = 0x9211BCAC
VT2_STORED_BKHD_GENERATOR_WORD = 0x9211BC28
VT2_WWISE_BANK_GENERATOR_VERSION = 132
EXPECTED_INIT_BANK_SHA256 = (
    "4d9f6ff2d487c5a56e40fe2b5ebda001d281d1762d707ad2e8d239701121c3c9"
)

KNOWN_PLACEHOLDER_BANK_HASHES = {
    # Loremasters' Armoury custom bank
    "7d57e53e6e981c31905089a0a398b1e74b62c03269262d2cb5de5b7b66d3a322",
    # Pusfume custom bank
    "759a92205d68e67ea8a00db3f1210cca13e23decfda4874b0648e140daf78f8b",
    # Native Ratling Gunner bank
    "1916328710629e9faf114f3d863a5796801d0246f528cb874c8e08988902eadd",
}


def without_lua_comments(source: str) -> str:
    """Remove Lua comments without treating comment text as live wiring."""

    result: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote:
            result.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                result.append(source[index])
            elif char == quote:
                quote = None
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            result.append(char)
            index += 1
            continue

        if source.startswith("--[[", index):
            end = source.find("]]", index + 4)
            end = len(source) - 2 if end < 0 else end
            result.extend(
                "\n" if value == "\n" else " "
                for value in source[index : end + 2]
            )
            index = end + 2
            continue

        if source.startswith("--", index):
            end = source.find("\n", index + 2)
            end = len(source) if end < 0 else end
            result.extend(" " for _ in source[index:end])
            index = end
            continue

        result.append(char)
        index += 1

    return "".join(result)


def quoted_values(source: str) -> set[str]:
    return set(re.findall(r'["\']([^"\']+)["\']', source))


def riff_chunks(path: Path) -> list[tuple[bytes, bytes]]:
    """Read RIFF chunks without silently ignoring an unwanted `smpl` chunk."""

    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AssertionError(f"{path.name}: not a RIFF/WAVE file")

    chunks: list[tuple[bytes, bytes]] = []
    cursor = 12
    while cursor + 8 <= len(data):
        chunk_id = data[cursor : cursor + 4]
        size = struct.unpack_from("<I", data, cursor + 4)[0]
        start = cursor + 8
        end = start + size
        if end > len(data):
            raise AssertionError(f"{path.name}: truncated {chunk_id!r} chunk")
        chunks.append((chunk_id, data[start:end]))
        cursor = end + (size & 1)
    return chunks


def discover_staged_wavs() -> dict[str, Path]:
    """Return repository WAVs by basename, excluding generated/private trees."""

    staged: dict[str, Path] = {}
    for root in (SOURCE_AUDIO_ROOT, WWISE_ROOT):
        if not root.is_dir():
            continue
        for path in root.rglob("*.wav"):
            if path.name in staged:
                raise AssertionError(
                    f"duplicate staged source basename {path.name!r}: "
                    f"{staged[path.name]} and {path}"
                )
            staged[path.name] = path
    return staged


def compiled_resource_payloads(resource_type: str, resource_name: str) -> list[bytes]:
    """Return every compiled version of one named resource across mod bundles."""

    key = (murmur64a(resource_type.encode()), murmur64a(resource_name.encode()))
    payloads: list[bytes] = []
    for bundle in sorted(BUNDLE_ROOT.glob("*.mod_bundle")):
        bundle_format, _, data = read_bundle(bundle)
        _, _, records = walk_bundle(data, bundle_format)
        for record in records:
            if (record["type"], record["name"]) != key:
                continue
            for version in record["versions"]:
                start = version["payload_offset"]
                payloads.append(data[start : start + version["size"]])
    return payloads


class DoomrocketWwiseProductsTests(unittest.TestCase):
    def test_package_compiles_wwise_dependencies(self) -> None:
        source = PACKAGE_PATH.read_text(encoding="utf-8")
        active = re.sub(r"(?m)^\s*//.*$", "", source)
        self.assertRegex(
            active,
            r'(?s)\bwwise_dep\s*=\s*\[\s*["\']wwise/\*["\']\s*\]',
            "doomrocket.package must actively compile wwise/* (not a commented block)",
        )

    def test_complete_stingray_bank_product_set_exists(self) -> None:
        required = (
            BANK_PATH,
            BANK_METADATA_PATH,
            DEPENDENCY_PATH,
            INIT_BANK_PATH,
            INIT_DEPENDENCY_PATH,
            PROJECT_METADATA_PATH,
        )
        missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
        self.assertEqual(
            missing,
            [],
            "custom audio is not testable until every Wwise/Stingray product exists: "
            + ", ".join(missing),
        )
        for path in required:
            self.assertGreater(path.stat().st_size, 0, f"{path.name} is empty")
        self.assertFalse(
            (WWISE_ROOT / "project.wwise_metadata").exists(),
            "the legacy generic metadata resource would reintroduce a compiled collision",
        )

    def test_bank_has_wrapped_wwise_sections(self) -> None:
        if not BANK_PATH.is_file():
            self.skipTest("bank absent; complete-product-set test reports the blocking artifact")
        data = BANK_PATH.read_bytes()
        self.assertGreater(
            len(data),
            100_000,
            "bank is too small to contain the approved embedded audio assets",
        )
        self.assertNotIn(
            hashlib.sha256(data).hexdigest(),
            KNOWN_PLACEHOLDER_BANK_HASHES,
            "bank is an unchanged donor/native placeholder rather than a Doomrocket bank",
        )
        self.assertIn(b"win32\x00", data[:128], "bank lacks the VT2 win32 wrapper")
        for section in (b"BKHD", b"DIDX", b"DATA", b"HIRC"):
            self.assertIn(section, data, f"bank lacks required Wwise {section!r} section")
        bank_header = data.index(b"BKHD")
        self.assertGreaterEqual(len(data), bank_header + 12)
        stored_version = struct.unpack_from("<I", data, bank_header + 8)[0]
        self.assertEqual(
            stored_version,
            VT2_STORED_BKHD_GENERATOR_WORD,
            "bank's stored BKHD generator word differs from proven VT2 banks",
        )
        self.assertEqual(
            stored_version ^ VT2_BKHD_XOR_WORD,
            VT2_WWISE_BANK_GENERATOR_VERSION,
            "bank's BKHD generator word does not decode to version 132 with the "
            "XOR word recovered independently from VT2's SDK plugin",
        )

    def test_hirc_order_matches_working_vt2_authoring_banks(self) -> None:
        data = BANK_PATH.read_bytes()
        hirc_header = data.index(b"HIRC")
        hirc_size = struct.unpack_from("<I", data, hirc_header + 4)[0]
        hirc = data[hirc_header + 8 : hirc_header + 8 + hirc_size]
        object_count = struct.unpack_from("<I", hirc, 0)[0]
        objects: list[tuple[int, int, bytes]] = []
        cursor = 4
        for _ in range(object_count):
            object_type = hirc[cursor]
            body_size = struct.unpack_from("<I", hirc, cursor + 1)[0]
            body = hirc[cursor + 5 : cursor + 5 + body_size]
            self.assertGreaterEqual(len(body), 4)
            objects.append((object_type, struct.unpack_from("<I", body, 0)[0], body))
            cursor += 5 + body_size
        self.assertEqual(cursor, len(hirc), "HIRC parser did not consume the section")

        types = [item[0] for item in objects]
        first_sound = types.index(0x02)
        first_action = types.index(0x03)
        self.assertTrue(all(kind == 0x0E for kind in types[:first_sound]))
        self.assertTrue(all(kind == 0x02 for kind in types[first_sound:first_action]))
        self.assertTrue(all(kind in (0x03, 0x04) for kind in types[first_action:]))

        event_ids = [short_id for kind, short_id, _ in objects if kind == 0x04]
        self.assertEqual(event_ids, sorted(event_ids), "Event groups must be ShortID ordered")
        for event_index, (kind, _, body) in enumerate(objects):
            if kind != 0x04:
                continue
            action_count = body[4]
            action_ids = list(struct.unpack_from(f"<{action_count}I", body, 5))
            preceding = objects[event_index - action_count : event_index]
            self.assertEqual([item[0] for item in preceding], [0x03] * action_count)
            self.assertEqual(
                [item[1] for item in preceding],
                action_ids,
                "each Event must immediately follow the Action object(s) it references",
            )

    def test_dependency_and_metadata_name_the_bank_and_all_events(self) -> None:
        required = (
            DEPENDENCY_PATH,
            INIT_DEPENDENCY_PATH,
            BANK_METADATA_PATH,
            PROJECT_METADATA_PATH,
        )
        if not all(path.is_file() for path in required):
            self.skipTest("metadata absent; complete-product-set test reports the blocking artifacts")
        dependency = DEPENDENCY_PATH.read_text(encoding="utf-8")
        init_dependency = INIT_DEPENDENCY_PATH.read_text(encoding="utf-8")
        bank_metadata = BANK_METADATA_PATH.read_text(encoding="utf-8")
        project_metadata = PROJECT_METADATA_PATH.read_text(encoding="utf-8")

        self.assertIn('"wwise/doomrocket"', dependency)
        self.assertIn('"wwise/Init"', init_dependency)
        self.assertIn('metadata = "wwise/doomrocket_project"', dependency)
        self.assertIn('metadata = "wwise/doomrocket_project"', init_dependency)
        self.assertRegex(project_metadata, r"\bInit\s*=\s*\{")
        for event in sorted(EXPECTED_EVENTS):
            with self.subTest(event=event):
                self.assertIn(
                    event,
                    quoted_values(bank_metadata),
                    f"{event} is absent from doomrocket.wwise_bank_metadata",
                )
                self.assertIn(
                    event,
                    quoted_values(project_metadata),
                    f"{event} is absent from doomrocket_project.wwise_metadata",
                )

        backpack_metadata = re.search(
            r"Play_enemy_doomrocket_backpack_loop\s*=\s*\{(?P<body>.*?)\n\s*\}",
            project_metadata,
            re.DOTALL,
        )
        self.assertIsNotNone(backpack_metadata)
        self.assertIn(
            'duration_type = "Infinite"',
            backpack_metadata.group("body"),
            "metadata must agree with the bank's infinite Sound loop property",
        )
        for event in EXPECTED_EVENTS - {"Play_enemy_doomrocket_backpack_loop"}:
            with self.subTest(one_shot_metadata=event):
                event_metadata = re.search(
                    rf"{re.escape(event)}\s*=\s*\{{(?P<body>.*?)\n\s*\}}",
                    project_metadata,
                    re.DOTALL,
                )
                self.assertIsNotNone(event_metadata)
                self.assertIn('duration_type = "OneShot"', event_metadata.group("body"))

    def test_staged_source_wavs_are_the_clean_mono_handoff(self) -> None:
        staged = discover_staged_wavs()
        if not staged:
            self.skipTest(
                "source WAVs are not staged under audio_src/doomrocket or wwise/; "
                "validating compiled products only"
            )

        self.assertEqual(
            set(staged),
            set(EXPECTED_SOURCE_HASHES),
            "stage exactly the approved clean masters; do not retain obsolete duplicate files",
        )
        for name, expected_hash in EXPECTED_SOURCE_HASHES.items():
            with self.subTest(source=name):
                path = staged[name]
                data = path.read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected_hash)
                chunks = riff_chunks(path)
                chunk_ids = [chunk_id for chunk_id, _ in chunks]
                self.assertNotIn(b"smpl", chunk_ids, "loop markers must be authored in Wwise")

                fmt = next((body for chunk_id, body in chunks if chunk_id == b"fmt "), None)
                self.assertIsNotNone(fmt, "missing fmt chunk")
                self.assertGreaterEqual(len(fmt), 16, "truncated fmt chunk")
                codec, channels, sample_rate, _, _, bits = struct.unpack_from("<HHIIHH", fmt)
                self.assertEqual(codec, 1, "approved handoff must remain PCM")
                self.assertEqual(channels, 1, "approved handoff must remain mono")
                self.assertEqual(sample_rate, 44100)
                self.assertEqual(bits, 16)

    def test_manifest_proves_media_and_event_provenance(self) -> None:
        self.assertTrue(MANIFEST_PATH.is_file(), "missing deterministic bank manifest")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        bank = BANK_PATH.read_bytes()

        self.assertEqual(manifest.get("schema"), 1)
        self.assertEqual(manifest["bank"]["resource"], "wwise/doomrocket")
        self.assertEqual(
            manifest["bank"]["decrypted_bank_version"],
            VT2_WWISE_BANK_GENERATOR_VERSION,
        )
        self.assertEqual(manifest["bank"]["wrapped_bytes"], len(bank))
        self.assertEqual(
            manifest["bank"]["wrapped_sha256"],
            hashlib.sha256(bank).hexdigest(),
        )
        self.assertEqual(
            hashlib.sha256(INIT_BANK_PATH.read_bytes()).hexdigest(),
            EXPECTED_INIT_BANK_SHA256,
        )
        self.assertEqual(
            manifest["init_bank"],
            {
                "bytes": 1552,
                "evidence": (
                    "byte-identical Wwise 2018.1 product in Pusfume and "
                    "Loremasters' Armoury"
                ),
                "resource": "wwise/Init",
                "sha256": EXPECTED_INIT_BANK_SHA256,
            },
        )
        self.assertEqual(
            {event["name"] for event in manifest["events"]},
            EXPECTED_EVENTS,
        )

        media = manifest["media"]
        expected_by_role = {
            "backpack": "SFX_unit_WarlockEngineer_DoomRocket_backpack_loop.wav",
            "launch": "SFX_unit_WarlockEngineer_DoomRocket_shot.wav",
            "ground": "SFX_unit_WarlockEngineer_DoomRocket_Explosion_Ground.wav",
            "air": "SFX_unit_WarlockEngineer_DoomRocket_Explosion_Air.wav",
            "voice_01": "SFX_unit_WarlockEngineer_DoomRocket_voice_01.wav",
            "voice_02": "SFX_unit_WarlockEngineer_DoomRocket_voice_02.wav",
            "voice_03": "SFX_unit_WarlockEngineer_DoomRocket_voice_03.wav",
            "voice_04": "SFX_unit_WarlockEngineer_DoomRocket_voice_04.wav",
            "voice_05": "SFX_unit_WarlockEngineer_DoomRocket_voice_05.wav",
            "voice_laugh_01": "SFX_unit_WarlockEngineer_DoomRocket_voice_laugh_01.wav",
            "voice_death_01": "SFX_unit_WarlockEngineer_DoomRocket_voice_death_01.wav",
            "voice_death_02": "SFX_unit_WarlockEngineer_DoomRocket_voice_death_02.wav",
        }
        self.assertEqual(set(media), set(expected_by_role))
        for role, filename in expected_by_role.items():
            with self.subTest(media=role):
                self.assertEqual(
                    media[role]["source_sha256"],
                    EXPECTED_SOURCE_HASHES[filename],
                )
                self.assertEqual(media[role]["loop"], role == "backpack")
                self.assertGreater(media[role]["wem_bytes"], 0)

        self.assertEqual(
            manifest["authoring"]["impact_layers"],
            ["ground", "air"],
            "impact event must play both supplied explosion assets as layers",
        )
        self.assertIsNone(
            manifest["authoring"]["flight_asset"],
            "do not invent or loop the launch transient as a projectile-flight asset",
        )
        self.assertEqual(
            manifest["authoring"]["combat_voice_pool"],
            ["voice_01", "voice_02", "voice_03", "voice_04", "voice_05", "voice_laugh_01"],
        )
        self.assertEqual(
            manifest["authoring"]["death_voice_pool"],
            ["voice_death_01", "voice_death_02"],
        )

    def test_committed_bank_rebuilds_byte_for_byte_from_approved_sources(self) -> None:
        self.assertTrue(BUILDER_PATH.is_file(), "missing deterministic bank builder")
        with tempfile.TemporaryDirectory(prefix="doomrocket-wwise-contract-") as temp:
            clean_root = Path(temp)
            completed = subprocess.run(
                (
                    sys.executable,
                    str(BUILDER_PATH),
                    "--source-dir",
                    str(SOURCE_AUDIO_ROOT),
                    "--repo-root",
                    str(clean_root),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.returncode,
                0,
                "clean-room bank rebuild failed:\n"
                + completed.stdout
                + completed.stderr,
            )
            for relative in (
                Path("wwise/doomrocket.wwise_bank"),
                Path("wwise/doomrocket.wwise_bank_metadata"),
                Path("wwise/doomrocket.wwise_dep"),
                Path("wwise/Init.wwise_bank"),
                Path("wwise/Init.wwise_dep"),
                Path("wwise/doomrocket_project.wwise_metadata"),
                Path("wwise/doomrocket.bank_manifest.json"),
            ):
                with self.subTest(product=relative.as_posix()):
                    rebuilt = clean_root / relative
                    committed = REPO_ROOT / relative
                    self.assertTrue(rebuilt.is_file())
                    self.assertEqual(
                        rebuilt.read_bytes(),
                        committed.read_bytes(),
                        f"{relative} is stale or was not produced by the documented builder",
                    )

    def test_compiled_bundle_contains_the_exact_bank_dependency_and_metadata(self) -> None:
        if not any(BUNDLE_ROOT.glob("*.mod_bundle")):
            self.skipTest("bundleV2 is absent; source-only checkout")

        bank_payloads = compiled_resource_payloads("wwise_bank", "wwise/doomrocket")
        init_bank_payloads = compiled_resource_payloads("wwise_bank", "wwise/Init")
        dependency_payloads = compiled_resource_payloads("wwise_dep", "wwise/doomrocket")
        init_dependency_payloads = compiled_resource_payloads("wwise_dep", "wwise/Init")
        metadata_payloads = compiled_resource_payloads(
            "wwise_metadata", "wwise/doomrocket_project"
        )
        self.assertEqual(len(bank_payloads), 1, "expected one compiled Doomrocket bank")
        self.assertEqual(len(init_bank_payloads), 1, "expected one compiled Wwise Init bank")
        self.assertEqual(len(dependency_payloads), 1, "expected one compiled Doomrocket dependency")
        self.assertEqual(len(init_dependency_payloads), 1, "expected one compiled Init dependency")
        self.assertEqual(len(metadata_payloads), 1, "expected one compiled Wwise metadata resource")

        # Stingray replaces the 44-byte source-platform wrapper with its own
        # 16-byte compiled-resource wrapper. The raw Wwise bank must otherwise
        # survive byte-for-byte; compiler acceptance alone is insufficient.
        source_bank = BANK_PATH.read_bytes()
        compiled_bank = bank_payloads[0]
        self.assertEqual(struct.unpack_from("<I", compiled_bank, 0)[0], 5)
        compiled_raw_size = struct.unpack_from("<I", compiled_bank, 4)[0]
        self.assertEqual(compiled_raw_size, len(compiled_bank) - 16)
        self.assertEqual(compiled_bank[16:], source_bank[44:])

        source_init_bank = INIT_BANK_PATH.read_bytes()
        compiled_init_bank = init_bank_payloads[0]
        self.assertEqual(struct.unpack_from("<I", compiled_init_bank, 0)[0], 5)
        self.assertEqual(compiled_init_bank[16:], source_init_bank[44:])

        expected_dependency = struct.pack("<II", 5, 17) + b"wwise/doomrocket\0"
        self.assertEqual(dependency_payloads[0], expected_dependency)
        expected_init_dependency = struct.pack("<II", 5, 11) + b"wwise/Init\0"
        self.assertEqual(init_dependency_payloads[0], expected_init_dependency)

        compiled_metadata = metadata_payloads[0]
        record_bytes = 24 * len(EXPECTED_EVENTS)
        self.assertEqual(struct.unpack_from("<II", compiled_metadata, 0), (5, record_bytes))
        self.assertEqual(len(compiled_metadata), 8 + record_bytes)
        records: dict[int, tuple[float, float, float, int, int]] = {}
        for offset in range(8, len(compiled_metadata), 24):
            event_id, attenuation, duration_max, duration_min, duration_type, positioning = (
                struct.unpack_from("<IfffII", compiled_metadata, offset)
            )
            records[event_id] = (
                attenuation,
                duration_max,
                duration_min,
                duration_type,
                positioning,
            )

        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        event_ids = {event["name"]: event["short_id"] for event in manifest["events"]}
        self.assertEqual(set(records), set(event_ids.values()))
        for name, event_id in event_ids.items():
            with self.subTest(event=name):
                expected_type = 1 if name == "Play_enemy_doomrocket_backpack_loop" else 0
                self.assertEqual(
                    records[event_id][3],
                    expected_type,
                    "compiled metadata lost the Infinite/OneShot event contract",
                )


class DoomrocketRuntimeSoundContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bootstrap = without_lua_comments(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
        cls.projectile = without_lua_comments(PROJECTILE_PATH.read_text(encoding="utf-8"))
        cls.lua_sources = {
            path: without_lua_comments(path.read_text(encoding="utf-8"))
            for path in (REPO_ROOT / "scripts" / "mods" / "doomrocket").rglob("*.lua")
        }
        cls.runtime = "\n".join(cls.lua_sources.values())
        cls.runtime_strings = set().union(
            *(quoted_values(source) for source in cls.lua_sources.values())
        )
        cls.audio = cls.lua_sources.get(AUDIO_RUNTIME_PATH, "")
        cls.hooks = cls.lua_sources.get(HOOKS_PATH, "")
        cls.death_reactions = cls.lua_sources.get(DEATH_REACTIONS_PATH, "")
        cls.rpc = cls.lua_sources.get(RPC_PATH, "")
        cls.launch_action = cls.lua_sources.get(LAUNCH_ACTION_PATH, "")
        cls.breed = cls.lua_sources.get(BREED_PATH, "")

    def test_bank_is_loaded_by_the_mod(self) -> None:
        self.assertRegex(
            self.runtime,
            r'Wwise\.load_bank\s*\(\s*["\']wwise/doomrocket["\']\s*\)',
        )

    def test_audio_helper_loads_before_every_consumer(self) -> None:
        audio_load = self.bootstrap.find(
            'mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_audio")'
        )
        self.assertGreaterEqual(audio_load, 0, "bootstrap does not load doomrocket_audio")
        for consumer in (
            "scripts/mods/doomrocket/extensions/projectile_rocket",
            "scripts/mods/doomrocket/extensions/death_reactions",
            "scripts/mods/doomrocket/utils/hooks",
        ):
            with self.subTest(consumer=consumer):
                consumer_load = self.bootstrap.find(f'mod:dofile("{consumer}")')
                self.assertGreaterEqual(consumer_load, 0, f"bootstrap does not load {consumer}")
                self.assertLess(
                    audio_load,
                    consumer_load,
                    "audio helper must exist before a consumer can call its mod functions",
                )

    def test_runtime_references_every_authored_event(self) -> None:
        self.assertTrue(
            EXPECTED_EVENTS <= self.runtime_strings,
            "runtime is missing authored events: "
            + ", ".join(sorted(EXPECTED_EVENTS - self.runtime_strings)),
        )

    def test_warpfire_shot_placeholders_are_gone_from_live_paths(self) -> None:
        found = sorted(FORBIDDEN_PLACEHOLDER_EVENTS & self.runtime_strings)
        self.assertEqual(
            found,
            [],
            "custom audio candidate still calls borrowed Warpfire event(s): "
            + ", ".join(found),
        )

    def test_impact_template_uses_loaded_custom_event_with_resource_fallback(self) -> None:
        self.assertRegex(
            self.bootstrap,
            r"sound_event_name\s*=\s*mod\._doomrocket_select_impact_event\(\)",
            "the replicated explosion template must use the centralized event selection",
        )
        self.assertIn("Wwise.has_event", self.audio)
        self.assertIn("Play_enemy_doomrocket_impact", self.audio)
        self.assertIn(SAFE_IMPACT_FALLBACK_EVENT, self.audio)
        self.assertRegex(
            self.audio,
            r"local\s+selected_event\s*=\s*available\s+and\s+IMPACT_EVENT\s+or\s+IMPACT_FALLBACK_EVENT",
            "a missing bank/runtime must fail closed to the known native event",
        )
        ensure_start = self.audio.find("local function ensure_bank_for_event")
        ensure_body = self.audio[ensure_start : ensure_start + 2600]
        self.assertIn('return true, "metadata_unverified"', ensure_body)
        self.assertIn("action=attempt_playback", ensure_body)
        self.assertNotIn('return false, "event_missing"', ensure_body)

    def test_loop_start_and_stop_are_both_live_and_cleanup_is_idempotent(self) -> None:
        self.assertIn("Play_enemy_doomrocket_backpack_loop", self.runtime)
        self.assertIn("Stop_enemy_doomrocket_backpack_loop", self.runtime)
        self.assertRegex(
            self.runtime,
            r"WwiseWorld\.(?:trigger_event|stop_event)\s*\(",
            "custom events are declared but never sent to WwiseWorld",
        )

        self.assertIn("mod._start_warlock_backpack_sound(", self.runtime)
        self.assertIn("mod._stop_warlock_backpack_sound(", self.runtime)
        self.assertIn("mod._update_warlock_backpack_sounds(", self.bootstrap)
        self.assertEqual(
            self.hooks.count("mod._start_warlock_backpack_sound("),
            1,
            "visible outfit setup must own exactly one backpack-loop start call",
        )
        self.assertEqual(
            self.hooks.count("mod._stop_warlock_backpack_sound("),
            1,
            "the shared owner/husk death preparation must own one explicit stop call",
        )

        # One shared reset must own both the custom-audio shutdown and the
        # persistent death-driver reset.  Every lifecycle exit must call it;
        # otherwise a level transition/hot reload can strand playing IDs or
        # stale death drivers.  Disable/unload additionally release our bank.
        reset_start = self.bootstrap.find("local function reset_warlock_runtime_state")
        self.assertGreaterEqual(reset_start, 0, "missing shared Warlock runtime reset")
        reset_body = self.bootstrap[reset_start : reset_start + 700]
        self.assertRegex(
            reset_body,
            r"_shutdown_doomrocket_audio\s*\(",
            "shared runtime reset must own the custom-audio cleanup path",
        )

        lifecycle_calls = {
            "on_game_state_changed": r'reset_warlock_runtime_state\s*\(\s*"state_ingame_exit"\s*,\s*false\s*\)',
            "on_disabled": r'reset_warlock_runtime_state\s*\(\s*"mod_disabled"\s*,\s*true\s*\)',
            "on_unload": r'reset_warlock_runtime_state\s*\(\s*"mod_unload"\s*,\s*true\s*\)',
        }
        for lifecycle, call_pattern in lifecycle_calls.items():
            with self.subTest(lifecycle=lifecycle):
                start = self.bootstrap.find(f"function mod.{lifecycle}")
                self.assertGreaterEqual(start, 0, f"missing mod.{lifecycle}")
                body = self.bootstrap[start : start + 1800]
                self.assertRegex(
                    body,
                    call_pattern,
                    f"mod.{lifecycle} must call the shared cleanup with the correct bank policy",
                )

    def test_launch_is_one_per_projectile_replica_and_destroy_is_silent(self) -> None:
        self.assertEqual(
            self.projectile.count("mod._play_doomrocket_launch_sound("),
            1,
            "ProjectileRocket.init must own exactly one launch event per peer",
        )
        init_start = self.projectile.find("ProjectileRocket.init = function")
        update_start = self.projectile.find("ProjectileRocket.update = function")
        self.assertGreaterEqual(init_start, 0)
        self.assertGreater(update_start, init_start)
        self.assertIn(
            "mod._play_doomrocket_launch_sound(",
            self.projectile[init_start:update_start],
        )

        destroy_start = self.projectile.find("ProjectileRocket.destroy = function")
        self.assertGreaterEqual(destroy_start, 0)
        self.assertNotIn(
            "WwiseWorld.",
            self.projectile[destroy_start:],
            "a one-shot launch owns no playing ID and needs no destroy-time stop event",
        )

    def test_combat_voice_variant_replicates_with_the_projectile(self) -> None:
        self.assertEqual(self.launch_action.count("mod._choose_warlock_combat_voice("), 1)
        self.assertIn("combat_voice_variant", self.rpc)
        self.assertEqual(self.projectile.count("mod._play_warlock_combat_voice("), 1)
        self.assertIn("COMBAT_VOICE_COOLDOWN_SECONDS", self.audio)

    def test_death_stops_any_active_combat_voice_before_playing_death_take(self) -> None:
        self.assertIn("active_combat_voices", self.audio)
        self.assertIn("WwiseWorld.stop_event(", self.audio)
        death_start = self.audio.find("mod._play_warlock_death_voice = function")
        death_end = self.audio.find("local function stop_backpack_entry", death_start)
        self.assertGreaterEqual(death_start, 0)
        self.assertGreater(death_end, death_start)
        death_body = self.audio[death_start:death_end]
        stop_call = death_body.find('stop_combat_voice_entry(owner_unit, "death")')
        death_play = death_body.find('play_voice_event(owner_unit, event_name, "death_voice"')
        self.assertGreaterEqual(stop_call, 0)
        self.assertGreater(
            death_play,
            stop_call,
            "the active bark must stop before the death take starts",
        )
        shutdown_start = self.audio.find("mod._shutdown_doomrocket_audio = function")
        shutdown = self.audio[shutdown_start:]
        self.assertIn("mod._stop_all_warlock_combat_voices(", shutdown)

    def test_custom_death_voice_replaces_the_inherited_ratling_event(self) -> None:
        self.assertRegex(
            self.breed,
            r"Breeds\.skaven_doomrocket\.death_sound_event\s*=\s*nil",
        )
        self.assertEqual(
            self.death_reactions.count("mod._play_warlock_death_voice("),
            2,
            "unit and husk death pre-start must each own one local playback call",
        )
        guarded_calls = re.findall(
            r"if\s+not\s+is_hot_join_sync\(killing_blow\)\s+then\s+"
            r"mod\._play_warlock_death_voice\(unit\)",
            self.death_reactions,
        )
        self.assertEqual(len(guarded_calls), 2, "both custom death calls must suppress hot-join audio")

    def test_impact_helper_is_telemetry_only(self) -> None:
        helper_start = self.audio.find(
            "mod._doomrocket_sound_impact_requested = function"
        )
        shutdown_start = self.audio.find(
            "mod._shutdown_doomrocket_audio = function", helper_start
        )
        self.assertGreaterEqual(helper_start, 0)
        self.assertGreater(shutdown_start, helper_start)
        helper = self.audio[helper_start:shutdown_start]
        self.assertNotIn(
            "WwiseWorld.trigger_event",
            helper,
            "impact helper must not duplicate explosion-template playback",
        )
        self.assertEqual(
            self.projectile.count("mod._doomrocket_sound_impact_requested("),
            1,
        )

    def test_projectile_defers_damage_to_one_server_rpc(self) -> None:
        self.assertEqual(
            self.projectile.count(
                'network_transmit:send_rpc_server("rpc_create_explosion"'
            ),
            1,
            "mod.update must make one server-directed request and let the native RPC handler own damage/replication",
        )
        self.assertNotIn(':system("area_damage_system")', self.projectile)
        self.assertNotIn("area_damage_system:create_explosion(", self.projectile)
        self.assertNotIn("DamageUtils.create_explosion(", self.projectile)
        self.assertNotIn('send_rpc_clients("rpc_create_explosion"', self.projectile)
        self.assertNotIn(
            'send_rpc_clients_except("rpc_create_explosion"', self.projectile
        )

    def test_loaded_warhead_death_keeps_authoritative_area_damage(self) -> None:
        self.assertEqual(
            self.death_reactions.count(':system("area_damage_system")'),
            1,
        )
        self.assertEqual(
            self.death_reactions.count("area_damage_system:create_explosion("),
            1,
        )
        self.assertNotIn("DamageUtils.create_explosion(", self.death_reactions)
        self.assertNotIn(
            'send_rpc_server("rpc_create_explosion"', self.death_reactions
        )
        self.assertNotIn(
            'send_rpc_clients("rpc_create_explosion"', self.death_reactions
        )

    def test_custom_audio_never_passes_a_unit_world_to_wwise_utils(self) -> None:
        self.assertIn('world_manager:world("level_world")', self.audio)
        self.assertIn("world_manager:wwise_world(world)", self.audio)
        self.assertNotIn(
            "Unit.world(",
            self.audio,
            "custom audio must validate a WorldManager-owned world before native Wwise calls",
        )

    def test_audio_contract_emits_auditable_runtime_telemetry(self) -> None:
        for phase in ("bank", "backpack_start", "backpack_stop", "launch", "impact"):
            with self.subTest(phase=phase):
                self.assertIn(
                    f"phase={phase}",
                    self.audio,
                    f"missing [doomrocket:SOUND] telemetry for {phase}",
                )
        for phase in ("combat_voice", "death_voice"):
            with self.subTest(dynamic_phase=phase):
                self.assertIn(
                    f'"{phase}"',
                    self.audio,
                    f"voice helper never emits the {phase} telemetry phase",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
