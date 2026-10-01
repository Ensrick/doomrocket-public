#!/usr/bin/env python3
"""Build the Doomrocket VT2/Wwise 2018.1 embedded sound bank.

This is a deterministic bank builder for the deliberately small Doomrocket
sound graph.  It exists because the historical Wwise 2018.1 authoring tools
and Fatshark's ``wwise_exporter`` are not distributed with the VT2 SDK.

The structures emitted here were checked independently against all of:

* a native VT2 Ratling Gunner bank;
* the proven Loremasters' Armoury custom bank; and
* wwiser's Wwise version-132 parser.

The generated bank contains no donor media or donor HIRC records.  Every ID,
object, curve and PCM WEM is assembled from the documented v132 fields below.
The VT2 SDK compiler still needs to package the resulting ``wwise/*`` source
products, and an in-game test remains the final runtime authority.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STORED_VT2_WWISE_VERSION = 0x9211BC28
DECRYPTED_WWISE_VERSION = 132  # Wwise 2018.1
SFX_BUS_ID = 393239870
PCM_PLUGIN_ID = 0x00010001
LINEAR_CURVE = 4
DB_SCALING = 2
LOOP_PROPERTY_ID = 0x3A
ATTENUATION_PROPERTY_ID = 0x46
TRANSITION_TIME_PROPERTY_ID = 0x10

# Wwise 2018.1's generated Init bank establishes the standard VT2 custom-bank
# project buses and output sink. This 1,552-byte product is byte-identical in
# two independently shipped VT2 custom-audio projects (Pusfume and
# Loremasters' Armoury), SHA-256
# 4d9f6ff2d487c5a56e40fe2b5ebda001d281d1762d707ad2e8d239701121c3c9.
# v0.1.59 omitted Init entirely; the game could load the Doomrocket resource,
# but no event registered. Keep this generated prerequisite deterministic and
# verify its digest before writing it.
INIT_BANK_SHA256 = "4d9f6ff2d487c5a56e40fe2b5ebda001d281d1762d707ad2e8d239701121c3c9"
INIT_BANK_BASE64 = (
    "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"
)

EVENT_BACKPACK_PLAY = "Play_enemy_doomrocket_backpack_loop"
EVENT_BACKPACK_STOP = "Stop_enemy_doomrocket_backpack_loop"
EVENT_LAUNCH = "Play_enemy_doomrocket_launch"
EVENT_IMPACT = "Play_enemy_doomrocket_impact"
VOICE_COMBAT_ASSET_KEYS = (
    "voice_01",
    "voice_02",
    "voice_03",
    "voice_04",
    "voice_05",
    "voice_laugh_01",
)
VOICE_DEATH_ASSET_KEYS = (
    "voice_death_01",
    "voice_death_02",
)
VOICE_ASSET_KEYS = VOICE_COMBAT_ASSET_KEYS + VOICE_DEATH_ASSET_KEYS
VOICE_EVENT_BY_ASSET = {
    key: f"Play_enemy_doomrocket_{key}" for key in VOICE_ASSET_KEYS
}
EVENTS = (
    EVENT_BACKPACK_PLAY,
    EVENT_BACKPACK_STOP,
    EVENT_LAUNCH,
    EVENT_IMPACT,
    *(VOICE_EVENT_BY_ASSET[key] for key in VOICE_ASSET_KEYS),
)

EXPECTED_SOURCE_HASHES = {
    "backpack": "483d8ccb127ba01cd172c2b7e47f6f6d0eaf476e13e678032092df12771c173e",
    "launch": "e6f2a145ba4c4d1ca09b83de11b829c187fc27ba4bf1b7cbe04a77a1fdfcc883",
    "ground": "662c912f3c6804838e02dca97c0f33da36cea01ffb49e7c34257c7771c9db6fb",
    "air": "ccd097981acd434fa182b3fb0b85b2b1872a2800f16cffc87fda7560f33ac2fe",
    "voice_01": "f11d5da39d082ff4d865417bdb03d701cbe455cd137846c544edc96914854ebb",
    "voice_02": "0b17488038ab637c24663600f22a8dcd6e28f43423e82a2e8e8f4f368dfb80bf",
    "voice_03": "9e2cd95cecd3bc638392eb649fb9d228619a455ed67106b3077b0cca5d1dc294",
    "voice_04": "5a64d634353b202c269ef9e873f50202558963314559bac4436c2533de0514c7",
    "voice_05": "441b4e819d6095dd98451d3906be193c80beadbd772d79595b520f73a20b4279",
    "voice_laugh_01": "965de6b579d01afc1cd6c25755ed42168b371c4869bf901155d186a2b9163c53",
    "voice_death_01": "22724110ea478ec2f7af6cf1fe1a4d21a7bb57a6c1ae9fc86cf3131c88f5ebb7",
    "voice_death_02": "312ae63d60942c090e5590f006893456c81736d6338b6fa122f0b538cf527fbf",
}

CANONICAL_SOURCE_NAMES = {
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

SOURCE_NAME_ALIASES = {
    key: (filename,) for key, filename in CANONICAL_SOURCE_NAMES.items()
}
SOURCE_NAME_ALIASES.update({
    # Crunch's clean markerless mono handoff arrived with ``(1)`` because an
    # older stereo/marker-bearing file already occupied the canonical name.
    "air": (CANONICAL_SOURCE_NAMES["air"], "SFX_unit_WarlockEngineer_DoomRocket_Explosion_Air(1).wav"),
})


@dataclass(frozen=True)
class MediaAsset:
    key: str
    source_path: Path
    canonical_path: Path
    source_sha256: str
    media_id: int
    sound_id: int
    attenuation_id: int
    wem: bytes
    duration_seconds: float
    loop: bool


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fnv1_32(name: str) -> int:
    """Return Wwise's lowercase FNV-1 ShortID."""

    value = 2166136261
    for byte in name.lower().encode("utf-8"):
        value = ((value * 16777619) & 0xFFFFFFFF) ^ byte
    return value


def chunk(tag: bytes, body: bytes) -> bytes:
    if len(tag) != 4:
        raise ValueError(f"chunk tag must have four bytes: {tag!r}")
    return tag + struct.pack("<I", len(body)) + body


def hirc_object(object_type: int, body: bytes) -> bytes:
    return struct.pack("<BI", object_type, len(body)) + body


def find_approved_source(source_dir: Path, key: str) -> Path:
    expected = EXPECTED_SOURCE_HASHES[key]
    candidates: list[Path] = []
    for filename in SOURCE_NAME_ALIASES[key]:
        candidate = source_dir / filename
        if candidate.is_file():
            candidates.append(candidate)

    for candidate in candidates:
        if sha256(candidate.read_bytes()) == expected:
            return candidate

    detail = ", ".join(str(path) for path in candidates) or "no matching filenames"
    raise ValueError(
        f"{key}: approved source SHA-256 {expected} was not found in {source_dir} ({detail})"
    )


def read_pcm_wave(path: Path) -> tuple[bytes, float]:
    raw = path.read_bytes()
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        frame_count = reader.getnframes()
        compression = reader.getcomptype()
        pcm = reader.readframes(frame_count)

    if (channels, sample_width, sample_rate, compression) != (1, 2, 44100, "NONE"):
        raise ValueError(
            f"{path.name}: expected PCM mono/44.1 kHz/16-bit, got "
            f"channels={channels}, width={sample_width}, rate={sample_rate}, codec={compression}"
        )
    if len(pcm) != frame_count * channels * sample_width:
        raise ValueError(f"{path.name}: truncated PCM payload")
    if b"smpl" in riff_chunk_ids(raw):
        raise ValueError(f"{path.name}: contains a forbidden RIFF smpl marker")
    return pcm, frame_count / float(sample_rate)


def riff_chunk_ids(raw: bytes) -> tuple[bytes, ...]:
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("source is not a RIFF/WAVE file")
    ids: list[bytes] = []
    cursor = 12
    while cursor + 8 <= len(raw):
        chunk_id = raw[cursor : cursor + 4]
        size = struct.unpack_from("<I", raw, cursor + 4)[0]
        end = cursor + 8 + size
        if end > len(raw):
            raise ValueError(f"truncated {chunk_id!r} RIFF chunk")
        ids.append(chunk_id)
        cursor = end + (size & 1)
    return tuple(ids)


def make_pcm_wem(pcm: bytes) -> bytes:
    """Wrap PCM in the v132 Wwise embedded-media RIFF form.

    Wwise 2018.1's PCM writer uses a 24-byte WAVE_FORMAT_EXTENSIBLE ``fmt``
    body followed by a four-byte zero ``JUNK`` chunk.  ``00 00 01 41 00 00``
    is the observed Wwise mono channel configuration for this version.
    """

    fmt = struct.pack(
        "<HHIIHHH",
        0xFFFE,  # WAVE_FORMAT_EXTENSIBLE
        1,
        44100,
        88200,
        2,
        16,
        6,
    ) + bytes.fromhex("000001410000")
    body = chunk(b"fmt ", fmt) + chunk(b"JUNK", b"\0\0\0\0") + chunk(b"data", pcm)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


def make_attenuation(attenuation_id: int, max_distance: float) -> bytes:
    # One dB-scaled volume curve: full level at the emitter, Wwise's -1.0
    # terminal/silence value at max distance.  This is the exact standalone
    # v132 curve shape used by Loremasters' Armoury's validated 3D sounds.
    body = struct.pack("<I", attenuation_id)
    body += struct.pack("<B", 0)  # cone disabled
    body += bytes((0, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF))
    body += struct.pack("<BBH", 1, DB_SCALING, 2)
    body += struct.pack("<ffI", 0.0, 0.0, LINEAR_CURVE)
    body += struct.pack("<ffI", max_distance, -1.0, LINEAR_CURVE)
    body += struct.pack("<H", 0)  # no attenuation RTPCs
    if len(body) != 0x2A:
        raise AssertionError(f"unexpected attenuation body size: {len(body)}")
    return hirc_object(0x0E, body)


def make_sound(asset: MediaAsset) -> bytes:
    body = struct.pack("<II", asset.sound_id, PCM_PLUGIN_ID)
    body += struct.pack("<BII", 0, asset.media_id, len(asset.wem))  # embedded data
    body += struct.pack("<B", 0)  # source flags
    body += bytes((0, 0, 0))  # FX override/count + attachment override
    body += struct.pack("<II", SFX_BUS_ID, 0)  # output bus + no parent
    body += struct.pack("<B", 0)  # node option bits

    properties: list[tuple[int, int]] = []
    if asset.loop:
        properties.append((LOOP_PROPERTY_ID, 0))  # zero means infinite
    properties.append((ATTENUATION_PROPERTY_ID, asset.attenuation_id))
    properties.sort()
    body += struct.pack("<B", len(properties))
    # v132 serializes AkPropBundle as one packed ID array followed by one
    # packed value array (not as interleaved ID/value pairs).
    body += bytes(property_id for property_id, _ in properties)
    for _, value in properties:
        body += struct.pack("<I", value)
    body += struct.pack("<B", 0)  # no ranged property modifiers

    # Standalone emitter-relative 3D positioning with position+orientation.
    body += bytes((0x03, 0x02))
    body += struct.pack("<B", 0)  # no auxiliary sends
    body += struct.pack("<BBHBB", 0, 1, 0, 0, 0)  # advanced settings
    body += bytes((0, 0))  # no state properties/groups (varints)
    body += struct.pack("<H", 0)  # no node RTPCs

    expected = 0x37 if asset.loop else 0x32
    if len(body) != expected:
        raise AssertionError(f"{asset.key}: unexpected Sound body size {len(body):#x}")
    return hirc_object(0x02, body)


def make_play_action(action_id: int, target_sound_id: int, bank_id: int) -> bytes:
    body = struct.pack("<IH", action_id, 0x0403)  # Play_E_O
    body += struct.pack("<I", target_sound_id)
    body += bytes((0, 0, 0, 0x04))  # target flags, props, ranges, linear fade bits
    body += struct.pack("<I", bank_id)
    if len(body) != 0x12:
        raise AssertionError(f"unexpected Play action body size: {len(body)}")
    return hirc_object(0x03, body)


def make_stop_action(
    action_id: int,
    target_sound_id: int,
    transition_time_ms: int,
) -> bytes:
    body = struct.pack("<IH", action_id, 0x0103)  # Stop_E_O
    body += struct.pack("<I", target_sound_id)
    body += struct.pack("<BBBI", 0, 1, TRANSITION_TIME_PROPERTY_ID, transition_time_ms)
    body += bytes((0, 0x04, 0x06, 0))
    if len(body) != 0x15:
        raise AssertionError(f"unexpected Stop action body size: {len(body)}")
    return hirc_object(0x03, body)


def make_event(event_name: str, action_ids: Iterable[int]) -> bytes:
    actions = tuple(action_ids)
    if not 1 <= len(actions) <= 127:
        raise ValueError(f"{event_name}: unsupported action count {len(actions)}")
    body = struct.pack("<IB", fnv1_32(event_name), len(actions))
    body += b"".join(struct.pack("<I", action_id) for action_id in actions)
    return hirc_object(0x04, body)


def make_raw_bank(assets: tuple[MediaAsset, ...]) -> tuple[bytes, dict[str, int]]:
    bank_id = fnv1_32("doomrocket")
    action_ids = {
        "backpack_play": fnv1_32("doomrocket_action_play_backpack_loop"),
        "backpack_stop": fnv1_32("doomrocket_action_stop_backpack_loop"),
        "launch": fnv1_32("doomrocket_action_play_launch"),
        "ground": fnv1_32("doomrocket_action_play_impact_ground"),
        "air": fnv1_32("doomrocket_action_play_impact_air"),
    }
    action_ids.update({
        key: fnv1_32(f"doomrocket_action_play_{key}") for key in VOICE_ASSET_KEYS
    })

    assets_by_key = {asset.key: asset for asset in assets}
    backpack = assets_by_key["backpack"]
    launch = assets_by_key["launch"]
    ground = assets_by_key["ground"]
    air = assets_by_key["air"]

    # Keep embedded media sorted by ShortID, matching Wwise's deterministic
    # DIDX/DATA ordering.  Each media start is aligned to 16 bytes.
    data = bytearray()
    index = bytearray()
    for asset in sorted(assets, key=lambda item: item.media_id):
        while len(data) % 16:
            data.append(0)
        offset = len(data)
        data.extend(asset.wem)
        index.extend(struct.pack("<III", asset.media_id, offset, len(asset.wem)))
    while len(data) % 16:
        data.append(0)

    objects: list[tuple[int, int, bytes]] = []
    unique_attenuations = {
        asset.attenuation_id: (
            45.0
            if asset.key == "backpack"
            else 60.0
            if asset.key in VOICE_ASSET_KEYS
            else 120.0
        )
        for asset in assets
    }
    for attenuation_id, max_distance in sorted(unique_attenuations.items()):
        objects.append((0x0E, attenuation_id, make_attenuation(attenuation_id, max_distance)))
    for asset in sorted(assets, key=lambda item: item.sound_id):
        objects.append((0x02, asset.sound_id, make_sound(asset)))

    play_targets = {
        "backpack_play": backpack.sound_id,
        "launch": launch.sound_id,
        "ground": ground.sound_id,
        "air": air.sound_id,
    }
    play_targets.update({
        key: assets_by_key[key].sound_id for key in VOICE_ASSET_KEYS
    })
    action_objects = {
        action_ids[key]: (0x03, action_ids[key], make_play_action(action_ids[key], target, bank_id))
        for key, target in play_targets.items()
    }
    action_objects[action_ids["backpack_stop"]] = (
        0x03,
        action_ids["backpack_stop"],
        make_stop_action(action_ids["backpack_stop"], backpack.sound_id, 250),
    )

    event_actions = {
        EVENT_BACKPACK_PLAY: (action_ids["backpack_play"],),
        EVENT_BACKPACK_STOP: (action_ids["backpack_stop"],),
        EVENT_LAUNCH: (action_ids["launch"],),
        EVENT_IMPACT: (action_ids["ground"], action_ids["air"]),
    }
    event_actions.update({
        VOICE_EVENT_BY_ASSET[key]: (action_ids[key],) for key in VOICE_ASSET_KEYS
    })
    # Match the object ordering emitted by working VT2 Wwise 2018 banks: shared
    # attenuation and Sound objects first, then each Event's Action object(s)
    # immediately before that Event, with Event groups ordered by ShortID.
    for event_name, event_action_ids in sorted(
        event_actions.items(), key=lambda item: fnv1_32(item[0])
    ):
        for action_id in event_action_ids:
            objects.append(action_objects[action_id])
        objects.append((0x04, fnv1_32(event_name), make_event(event_name, event_action_ids)))
    hirc_body = struct.pack("<I", len(objects)) + b"".join(item[2] for item in objects)

    all_ids = {
        "bank": bank_id,
        **{f"media_{asset.key}": asset.media_id for asset in assets},
        **{f"sound_{asset.key}": asset.sound_id for asset in assets},
        **{f"attenuation_{asset.key}": asset.attenuation_id for asset in assets},
        **{f"action_{key}": value for key, value in action_ids.items()},
        **{f"event_{name}": fnv1_32(name) for name in EVENTS},
    }
    reverse: dict[int, list[str]] = {}
    for label, short_id in all_ids.items():
        reverse.setdefault(short_id, []).append(label)
    collisions = {short_id: labels for short_id, labels in reverse.items() if len(labels) > 1}
    # Ground/Air deliberately share one attenuation object, and every voice
    # uses a second shared attenuation. No other ShortID may collide.
    intentional_attenuation_groups = (
        {"attenuation_ground", "attenuation_air"},
        {f"attenuation_{key}" for key in VOICE_ASSET_KEYS},
    )
    for short_id, labels in tuple(collisions.items()):
        if set(labels) in intentional_attenuation_groups:
            del collisions[short_id]
    if collisions:
        raise AssertionError(f"ShortID collision(s): {collisions}")

    bkhd = struct.pack(
        "<IIIII12x",
        STORED_VT2_WWISE_VERSION,
        bank_id,
        SFX_BUS_ID,
        0,
        0,
    )
    raw_bank = chunk(b"BKHD", bkhd) + chunk(b"DIDX", bytes(index))
    raw_bank += chunk(b"DATA", bytes(data)) + chunk(b"HIRC", hirc_body)
    return raw_bank, all_ids


def wrap_stingray_bank(raw_bank: bytes) -> bytes:
    return struct.pack("<I", 1) + b"win32".ljust(32, b"\0") + struct.pack("<Q", len(raw_bank)) + raw_bank


def sjson_event_list(events: Iterable[str], indent: str = "\t") -> str:
    return "\n".join(f'{indent}"{event}"' for event in events)


def write_metadata(output_dir: Path, assets: tuple[MediaAsset, ...]) -> None:
    ordered_events = tuple(EVENTS)
    bank_metadata = "events = [\n" + sjson_event_list(ordered_events) + "\n]\n"
    dependency = (
        "win32 = {\n"
        "\tbanks = [\n"
        '\t\t"wwise/doomrocket"\n'
        "\t]\n"
        '\tmetadata = "wwise/doomrocket_project"\n'
        "\tstreams = [\n"
        "\t]\n"
        "}\n"
    )
    init_dependency = (
        "win32 = {\n"
        "\tbanks = [\n"
        '\t\t"wwise/Init"\n'
        "\t]\n"
        '\tmetadata = "wwise/doomrocket_project"\n'
        "\tstreams = [\n"
        "\t]\n"
        "}\n"
    )

    durations = {asset.key: asset.duration_seconds for asset in assets}
    event_specs = {
        # The VT2 SDK's Wwise resource plugin accepts exactly ``Infinite`` and
        # ``OneShot`` for duration_type.  The HIRC Sound property is infinite,
        # so the exported project metadata must agree with it.
        EVENT_BACKPACK_PLAY: (45, durations["backpack"], "Infinite"),
        EVENT_BACKPACK_STOP: (45, 0.25, "OneShot"),
        EVENT_LAUNCH: (120, durations["launch"], "OneShot"),
        EVENT_IMPACT: (120, max(durations["ground"], durations["air"]), "OneShot"),
    }
    event_specs.update({
        VOICE_EVENT_BY_ASSET[key]: (60, durations[key], "OneShot")
        for key in VOICE_ASSET_KEYS
    })
    event_sections = []
    for event_name in ordered_events:
        distance, duration, duration_type = event_specs[event_name]
        event_sections.append(
            f"\t{event_name} = {{\n"
            f"\t\tattenuation_max = {distance}\n"
            f"\t\tduration_max = {duration:.6f}\n"
            f"\t\tduration_min = {duration:.6f}\n"
            f'\t\tduration_type = "{duration_type}"\n'
            '\t\tpositioning = "3D"\n'
            "\t}"
        )
    project_metadata = (
        "aux_buses = [\n]\n"
        "banks = {\n"
		"\tInit = {\n"
		"\t\tevents = [\n"
		"\t\t]\n"
		"\t}\n"
        "\tdoomrocket = {\n"
        "\t\tevents = [\n"
        + sjson_event_list(ordered_events, "\t\t\t")
        + "\n\t\t]\n\t}\n}\n"
        "buses = [\n"
        '\t"Master Audio Bus"\n'
		'\t"Motion Factory Bus"\n'
		'\t"MUSIC"\n'
        '\t"SFX"\n'
		'\t"VO"\n'
        "]\n"
        "events = {\n"
        + "\n".join(event_sections)
        + "\n}\n"
        "parameters = [\n]\n"
        "state_groups = {\n}\n"
        "switch_groups = {\n}\n"
        "triggers = [\n]\n"
    )

    (output_dir / "doomrocket.wwise_bank_metadata").write_text(bank_metadata, encoding="utf-8", newline="\n")
    (output_dir / "doomrocket.wwise_dep").write_text(dependency, encoding="utf-8", newline="\n")
    init_bank = base64.b64decode(INIT_BANK_BASE64)
    if sha256(init_bank) != INIT_BANK_SHA256:
        raise AssertionError("embedded Wwise 2018.1 Init bank digest mismatch")
    (output_dir / "Init.wwise_bank").write_bytes(init_bank)
    (output_dir / "Init.wwise_dep").write_text(init_dependency, encoding="utf-8", newline="\n")
    (output_dir / "doomrocket_project.wwise_metadata").write_text(
        project_metadata, encoding="utf-8", newline="\n"
    )
    legacy_metadata = output_dir / "project.wwise_metadata"
    if legacy_metadata.is_file():
        legacy_metadata.unlink()


def build(source_dir: Path, repo_root: Path) -> dict[str, object]:
    source_dir = source_dir.resolve()
    repo_root = repo_root.resolve()
    staged_dir = repo_root / "audio_src" / "doomrocket"
    output_dir = repo_root / "wwise"
    staged_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    attenuation_names = {
        "backpack": "doomrocket_attenuation_backpack_45m",
        "launch": "doomrocket_attenuation_weapon_120m",
        "ground": "doomrocket_attenuation_impact_120m",
        "air": "doomrocket_attenuation_impact_120m",
    }
    attenuation_names.update({
        key: "doomrocket_attenuation_voice_60m" for key in VOICE_ASSET_KEYS
    })
    assets: list[MediaAsset] = []
    for key in ("backpack", "launch", "ground", "air", *VOICE_ASSET_KEYS):
        source = find_approved_source(source_dir, key)
        raw_source = source.read_bytes()
        canonical = staged_dir / CANONICAL_SOURCE_NAMES[key]
        if source.resolve() != canonical.resolve():
            shutil.copyfile(source, canonical)
        elif not canonical.is_file():
            raise AssertionError(f"staged source vanished: {canonical}")
        if sha256(canonical.read_bytes()) != EXPECTED_SOURCE_HASHES[key]:
            raise AssertionError(f"staged source hash changed during copy: {canonical}")

        pcm, duration = read_pcm_wave(canonical)
        wem = make_pcm_wem(pcm)
        assets.append(
            MediaAsset(
                key=key,
                source_path=source,
                canonical_path=canonical,
                source_sha256=sha256(raw_source),
                media_id=fnv1_32(f"doomrocket_media_{key}"),
                sound_id=fnv1_32(f"doomrocket_sound_{key}"),
                attenuation_id=fnv1_32(attenuation_names[key]),
                wem=wem,
                duration_seconds=duration,
                loop=(key == "backpack"),
            )
        )

    asset_tuple = tuple(assets)
    raw_bank, ids = make_raw_bank(asset_tuple)
    wrapped_bank = wrap_stingray_bank(raw_bank)
    bank_path = output_dir / "doomrocket.wwise_bank"
    bank_path.write_bytes(wrapped_bank)
    write_metadata(output_dir, asset_tuple)

    manifest: dict[str, object] = {
        "schema": 1,
        "bank": {
            "resource": "wwise/doomrocket",
            "platform": "win32",
            "wwise_release": "2018.1",
            "decrypted_bank_version": DECRYPTED_WWISE_VERSION,
            "stored_vt2_bank_version": f"0x{STORED_VT2_WWISE_VERSION:08X}",
            "wrapper_bytes": 44,
            "raw_bytes": len(raw_bank),
            "wrapped_bytes": len(wrapped_bank),
            "wrapped_sha256": sha256(wrapped_bank),
        },
        "provenance": {
            "builder": "tools/build_doomrocket_wwise_bank.py",
            "method": "deterministic Wwise v132 structure assembly; no donor media or donor HIRC payloads",
            "validated_references": [
                "native VT2 enemy_ratling_gunner bank",
                "Loremasters' Armoury VT2 custom bank",
                "wwiser Wwise v132 parser",
            ],
            "runtime_validation": "pending in-game VT2 sound test",
        },
        "init_bank": {
            "resource": "wwise/Init",
            "sha256": INIT_BANK_SHA256,
            "bytes": len(base64.b64decode(INIT_BANK_BASE64)),
            "evidence": "byte-identical Wwise 2018.1 product in Pusfume and Loremasters' Armoury",
        },
        "authoring": {
            "positioning": "3D emitter-relative, position and orientation",
            "attenuation_m": {"backpack": 45, "launch": 120, "impact": 120, "voice": 60},
            "backpack_loop": "infinite (Sound property 0x3A = 0)",
            "backpack_stop_fade_ms": 250,
            "impact_layers": ["ground", "air"],
            "flight_asset": None,
            "combat_voice_pool": list(VOICE_COMBAT_ASSET_KEYS),
            "death_voice_pool": list(VOICE_DEATH_ASSET_KEYS),
        },
        "events": [
            {
                "name": event,
                "short_id": fnv1_32(event),
                "layers": (["ground", "air"] if event == EVENT_IMPACT else None),
            }
            for event in EVENTS
        ],
        "media": {
            asset.key: {
                "canonical_source": asset.canonical_path.relative_to(repo_root).as_posix(),
                "source_sha256": asset.source_sha256,
                "pcm_sha256": sha256(read_pcm_wave(asset.canonical_path)[0]),
                "wem_sha256": sha256(asset.wem),
                "wem_bytes": len(asset.wem),
                "duration_seconds": round(asset.duration_seconds, 6),
                "media_id": asset.media_id,
                "sound_id": asset.sound_id,
                "attenuation_id": asset.attenuation_id,
                "loop": asset.loop,
            }
            for asset in asset_tuple
        },
        "object_ids": ids,
    }
    manifest_path = output_dir / "doomrocket.bank_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="directory containing Crunch's approved markerless mono WAVs",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Doomrocket source root (defaults to this script's repository)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build(args.source_dir, args.repo_root)
    bank = manifest["bank"]
    print(
        "built wwise/doomrocket.wwise_bank "
        f"({bank['wrapped_bytes']} bytes, sha256={bank['wrapped_sha256']})"
    )
    print(f"staged {len(manifest['media'])} approved masters under audio_src/doomrocket")
    print("runtime validation: pending in-game VT2 sound test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
