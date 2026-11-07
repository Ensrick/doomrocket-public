"""Stage and validate a native, headless VT2 SDK pose oracle.

This records engine poses; it performs no interpolation or fidelity inference.
The existing SDK staging helper is reused without changing its decoder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/hose_lab"))
from compile_paths import validate_probe, indexed_resources
import verify_compiled_animation as staging


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def lua(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        require(math.isfinite(value), "Nonfinite Lua input")
        return repr(value)
    if isinstance(value, str):
        # JSON's Unicode escapes are not Lua escapes; retain Unicode directly.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "{" + ",".join(lua(v) for v in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join("[" + lua(k) + "]=" + lua(v) for k, v in value.items()) + "}"
    raise ValueError("Unsupported Lua input type")


def author_samples(manifest):
    require(manifest["status"] == "fbx-roundtrip-passed", "Author FBX roundtrip has not passed")
    names = manifest["bone_names"]
    require(len(names) == 138 and len(set(names)) == 138, "Expected all 138 distinct deform bones")
    fps = manifest["fps"]
    require(isinstance(fps, (int, float)) and math.isfinite(fps) and fps == 60, "Expected 60 fps author input")
    reference = manifest["reference_samples"]
    require(2 <= len(reference) <= 10000, "Unbounded or empty author samples")
    require(manifest["exported_frame_start"] == 0 and manifest["exported_frame_end"] == len(reference) - 1,
            "Exported sample range is inconsistent")
    samples = []
    for index, sample in enumerate(reference):
        require(sample["frame"] == manifest["frame_start"] + index, "Author frames are not consecutive")
        require(set(sample["bones_world"]) == set(names), "Author sample bone inventory differs")
        for matrix in sample["bones_world"].values():
            check_matrix(matrix)
        samples.append({"sample_index": index, "frame": sample["frame"], "time_seconds": index / fps})
    require(reference[-1]["frame"] == manifest["frame_end"], "Author final frame differs")
    return names, fps, samples


def check_matrix(matrix):
    require(isinstance(matrix, list) and len(matrix) == 4 and all(isinstance(row, list) and len(row) == 4 for row in matrix),
            "Expected a 4x4 matrix")
    require(all(type(v) in (int, float) and math.isfinite(v) for row in matrix for v in row),
            "Nonfinite or nonnumeric matrix")
    require(max(abs(matrix[3][i] - (1 if i == 3 else 0)) for i in range(4)) < 1e-5,
            "Expected affine matrix bottom row")


def compatibility_timeline(clip):
    rate=clip['sample_fps'];count=clip['independent_roundtrip']['sample_count']
    base=240 if Path(clip['clip']).stem=='death_shot' or Path(clip['clip']).stem.startswith('stagger_') else 60
    require(type(rate) in (int,float) and math.isfinite(rate) and rate/base in (1,2,4)
            and type(count) is int and 2<=count<=10000,
            'Unbounded compatibility sample rate/count')
    return rate,count


def prepare(args, probe):
    probe.mkdir(parents=True, exist_ok=True)
    pending = {"schema": 1, "status": "staged-not-validated"}
    write_json(probe / "runtime_validation.json", pending)
    for lane in ("candidate", "reference"):
        lane_root = probe / lane
        lane_root.mkdir(parents=True, exist_ok=True)
        write_json(lane_root / "runtime_validation.json", pending)
        for filename in ("native_poses.json", "runtime_expected.json", "compiled_provenance.json",
                         "runtime.stdout.log", "runtime.stderr.log", "runtime.process.json"):
            (lane_root / filename).unlink(missing_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    names, fps, samples = author_samples(manifest)
    require(digest(args.animation_fbx) == manifest["fbx_sha256"], "Animation FBX differs from author receipt")
    require(digest(args.animation_fbx.with_suffix(".animation")) == manifest["animation_sha256"],
            "Animation sidecar differs from author receipt")
    staging.stage(argparse.Namespace(animation_fbx=args.animation_fbx, body_fbx=args.body_fbx,
        manifest=args.manifest, skin_profile=None, adapted_clips=args.adapted_clips, sdk_executable=args.sdk_executable), probe)
    provenance = {
        "body_fbx_sha256": digest(args.body_fbx),
        "animation_fbx_sha256": digest(args.animation_fbx),
        "animation_sidecar_sha256": digest(args.animation_fbx.with_suffix(".animation")),
        "author_manifest_sha256": digest(args.manifest),
        "shipping_bones_sha256": manifest["shipping_bones_sha256"],
        "source_scene_sha256": manifest.get("source_rig_disk_sha256", "not supplied"),
        "author_export_script_sha256": manifest.get("export_script_sha256", "not supplied"),
        "oracle_script_sha256": digest(Path(__file__).with_name("native_pose_oracle.lua")),
    }
    adapted = None
    if args.compatibility_only:
        require(args.adapted_clips, "Compatibility mode requires the adapted clip directory")
        adapted = json.loads((args.adapted_clips / "adapted-clips.json").read_text(encoding="utf-8"))
        provenance["adapted_manifest_sha256"] = digest(args.adapted_clips / "adapted-clips.json")
        names = adapted["clips"][0]["reserved_bones"] + ["j_hips"]
        require(len(names) == len(set(names)) == 8, "Expected seven reserved bones plus j_hips")
        samples = []
        for clip in adapted["clips"]:
            require(clip["reserved_bones"] + ["j_hips"] == names, "Compatibility clips reserve different bones")
            rate,count=compatibility_timeline(clip)
            for frame in range(count):
                samples.append({"sample_index": len(samples), "frame": frame, "time_seconds": frame / rate,
                    "clip": clip["clip"], "animation_resource": "units/warlock_bombardier/anims/" + Path(clip["clip"]).stem,
                    "sample_fps": rate})
    for lane in ("candidate", "reference"):
        lane_root = probe / lane
        source = lane_root / "source"
        shutil.copyfile(Path(__file__).with_name("native_pose_oracle.lua"), source / "native_pose_oracle.lua")
        (source / "native_pose_oracle.ini").write_text(
            'autoload = true\nboot_script = "native_pose_oracle"\nboot_package = "native_pose_oracle"\n'
            'render_settings = {}\nwwise = { communication = { enabled = false } }\n', encoding="utf-8")
        animations = [staging.CLIP]
        if adapted:
            animations += ["units/warlock_bombardier/anims/" + Path(c["clip"]).stem for c in adapted["clips"]]
        (source / "native_pose_oracle.package").write_text(
            'lua = ["native_pose_oracle" "native_pose_oracle_input"]\n'
            f'unit = ["{staging.UNIT}"]\nanimation = [' + ' '.join(json.dumps(c) for c in animations) + ']\n', encoding="utf-8")
        config = {"unit_resource": staging.UNIT, "animation_resource": staging.CLIP,
            "bone_names": names, "fps": fps, "samples": samples,
            "output_file": str(lane_root / "native_poses.json").replace("\\", "/"),
            "compiled_provenance_file": str(lane_root / "compiled_provenance.json").replace("\\", "/"),
            "provenance": dict(provenance, lane=lane)}
        config["capture_mode"] = "compatibility" if adapted else "author-diagnostic"
        config["samples_per_update"] = 8 if adapted else 1
        if adapted:
            config["provenance"]["clips"] = [{"clip": clip["clip"], "fbx_sha256": clip["sha256"] if lane == "candidate" else clip["source_sha256"],
                "animation_resource": "units/warlock_bombardier/anims/" + Path(clip["clip"]).stem,
                "sidecar_sha256": digest(source / ("units/warlock_bombardier/anims/" + Path(clip["clip"]).stem + ".animation"))}
                for clip in adapted["clips"]]
        if lane == "reference":
            config["provenance"]["body_fbx_sha256"] = digest(ROOT / (staging.UNIT + ".fbx"))
        write_json(lane_root / "runtime_input.json", config)
        write_lua(source, config)
    print(f"Staged {len(samples)} author samples and {len(names)} bones below {probe}")


def write_lua(source, config):
    (source / "native_pose_oracle_input.lua").write_text("return " + lua(config) + "\n", encoding="utf-8")


def bind_compiled(args, probe):
    lane_root = probe / args.lane
    paths = indexed_resources(ROOT, probe, lane_root / "data", [staging.UNIT + ".unit", staging.CLIP + ".animation"])
    config = json.loads((lane_root / "runtime_input.json").read_text(encoding="utf-8"))
    source = lane_root / "source"
    expected_hashes = {staging.UNIT + ".fbx": "body_fbx_sha256", staging.CLIP + ".fbx": "animation_fbx_sha256",
        staging.CLIP + ".animation": "animation_sidecar_sha256", "native_pose_oracle.lua": "oracle_script_sha256"}
    for resource, key in expected_hashes.items():
        require(digest(source / resource) == config["provenance"][key], "Staged source changed before compile: " + resource)
    require(digest(probe / "animation_export.json") == config["provenance"]["author_manifest_sha256"], "Staged author receipt changed")
    config["provenance"]["sdk_executable_sha256"] = digest(args.sdk_executable)
    header, bone_count, duration = struct.unpack_from("<IIf", paths[1].read_bytes())
    require(header == 0 and bone_count == 138 and (config["capture_mode"] == "compatibility" or
            abs(duration - config["samples"][-1]["time_seconds"]) < 1e-4),
            "Compiled clip bone count/duration differs from requested author samples")
    config["provenance"].update(compiled_unit_sha256=digest(paths[0]), compiled_animation_sha256=digest(paths[1]))
    if config["capture_mode"] == "compatibility":
        for clip in config["provenance"]["clips"]:
            require(digest(source / (clip["animation_resource"] + ".fbx")) == clip["fbx_sha256"] and
                    digest(source / (clip["animation_resource"] + ".animation")) == clip["sidecar_sha256"],
                    "Staged compatibility source changed: " + clip["clip"])
            payload, = indexed_resources(ROOT, probe, lane_root / "data", [clip["animation_resource"] + ".animation"])
            header, bones, duration = struct.unpack_from("<IIf", payload.read_bytes())
            times = [sample["time_seconds"] for sample in config["samples"] if sample["clip"] == clip["clip"]]
            require(header == 0 and bones == 138 and abs(duration - times[-1]) < 1e-4,
                    "Compiled compatibility duration/bones differ: " + clip["clip"])
            clip["compiled_animation_sha256"] = digest(payload)
    # Compiled hashes are bound after compilation. The boot reads this small,
    # guarded JSON provenance supplement through io, without recompiling Lua.
    supplement = dict(config["provenance"])
    if config["capture_mode"] == "compatibility":
        for clip in config["provenance"]["clips"]:
            supplement["compiled_" + clip["clip"]] = clip["compiled_animation_sha256"]
    write_json(lane_root / "compiled_provenance.json", supplement)
    write_json(lane_root / "runtime_expected.json", config)


def validate(args, probe):
    lane_root = probe / args.lane
    expected = json.loads((lane_root / "runtime_expected.json").read_text(encoding="utf-8"))
    actual = json.loads((lane_root / "native_poses.json").read_text(encoding="utf-8"))
    require(actual["status"] == "native-sdk-poses-recorded", "Native recorder did not finish")
    # The engine prints a completion marker only after closing the JSON output.
    stdout = (lane_root / "runtime.stdout.log").read_text(encoding="utf-8", errors="replace")
    require("ANIMATION_ORACLE_COMPLETE " + str(len(expected["samples"])) in stdout, "Native completion marker missing")
    require(actual["provenance"] == expected["provenance"], "Native provenance differs from frozen inputs")
    paths = indexed_resources(ROOT, probe, lane_root / "data", [staging.UNIT + ".unit", staging.CLIP + ".animation"])
    require(digest(paths[0]) == actual["provenance"]["compiled_unit_sha256"] and
            digest(paths[1]) == actual["provenance"]["compiled_animation_sha256"], "Compiled files changed after sampling")
    require(digest(args.sdk_executable) == actual["provenance"]["sdk_executable_sha256"], "SDK executable changed after sampling")
    for clip in actual["provenance"].get("clips", []):
        payload, = indexed_resources(ROOT, probe, lane_root / "data", [clip["animation_resource"] + ".animation"])
        require(digest(payload) == clip["compiled_animation_sha256"], "Compiled compatibility clip changed after sampling")
    names = set(expected["bone_names"])
    require(actual["sample_count"] == len(expected["samples"]) == len(actual["samples"]), "Native sample count differs")
    require(actual["bone_count"] == len(names) and set(actual["unit_node_indices"]) == names, "Native node inventory differs")
    require(all(type(node) is int and node >= 0 for node in actual["unit_node_indices"].values()), "Invalid native node index")
    require(len(set(actual["unit_node_indices"].values())) == len(names), "Native node indices are not distinct")
    for wanted, sample in zip(expected["samples"], actual["samples"]):
        require(sample["sample_index"] == wanted["sample_index"] and sample["frame"] == wanted["frame"] and
                abs(sample["time_seconds"] - wanted["time_seconds"]) < 1e-12, "Native sample time/frame differs")
        if expected["capture_mode"] == "compatibility":
            require(sample["clip"] == wanted["clip"], "Native compatibility clip differs")
        for key in ("bones_world", "bones_local"):
            require(set(sample[key]) == names, "Native sample bone inventory differs")
            for matrix in sample[key].values():
                check_matrix(matrix)
        check_matrix(sample["animation_wanted_root_pose"])
    receipt = {"schema": 1, "status": "native-sdk-pose-capture-passed", "lane": args.lane,
        "sample_count": len(actual["samples"]), "bone_count": len(names), "native_poses_sha256": digest(lane_root / "native_poses.json"),
        "provenance": actual["provenance"], "fidelity_verdict": "not inferred by recorder",
        "game_runtime_acceptance": "not performed", "deployed": False, "uploaded": False}
    write_json(lane_root / "runtime_validation.json", receipt)
    print(f"Validated native poses: {len(actual['samples'])} samples x {len(names)} bones: {lane_root / 'native_poses.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "bind-compiled", "validate"))
    parser.add_argument("--probe-root", type=Path, required=True)
    parser.add_argument("--lane", choices=("candidate", "reference"), default="candidate")
    parser.add_argument("--animation-fbx", type=Path)
    parser.add_argument("--body-fbx", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--adapted-clips", type=Path)
    parser.add_argument("--compatibility-only", action="store_true")
    parser.add_argument("--sdk-executable", type=Path)
    args = parser.parse_args()
    probe = validate_probe(ROOT, args.probe_root)
    if args.mode == "stage":
        require(args.animation_fbx and args.body_fbx and args.manifest, "Stage requires all three input paths")
        prepare(args, probe)
    elif args.mode == "bind-compiled":
        require(args.sdk_executable and args.sdk_executable.is_file(), "SDK executable required for provenance")
        bind_compiled(args, probe)
    else:
        require(args.sdk_executable and args.sdk_executable.is_file(), "SDK executable required for provenance")
        validate(args, probe)
