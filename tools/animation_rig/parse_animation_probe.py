"""Validate bounded passive in-game logs without inferring animation acceptance.

These observations do not replace the fixed-frame oracle or prove rendered
skin, original track identity, native blend weights, or gameplay correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

PREFIX = "[doomrocket:ANIMATION]"
BONES = ("root_point", "j_hips", "j_spine", "j_head", "j_lefthand", "j_righthand",
         "j_leftweaponattach", "j_whip_parent", "j_whip_dynamic", "j_loot_sack_component1")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field: " + key)
        result[key] = value
    return result


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def finite_tree(value):
    if type(value) in (int, float):
        require(math.isfinite(value), "Nonfinite diagnostic value")
    elif isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child)


def matrix(value):
    require(isinstance(value, list) and len(value) == 4 and all(isinstance(row, list) and len(row) == 4 for row in value),
            "Expected 4x4 local matrix")
    require(all(finite_number(number) for row in value for number in row), "Invalid local matrix value")
    require(value[3] == [0, 0, 0, 1], "Non-affine local matrix")


def records(lines, expected_version):
    require(re.fullmatch(r"\d+\.\d+\.\d+-dev", expected_version) is not None, "Expected exact TEST version")
    result = []
    for line_number, line in enumerate(lines, 1):
        if PREFIX not in line:
            continue
        payload = line.split(PREFIX, 1)[1].strip()
        require(len(payload) <= 65536 and len(result) < 1024, "Diagnostic log exceeds bounded record budget")
        try:
            item = json.loads(payload, object_pairs_hook=unique_object,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + value)))
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid/truncated diagnostic JSON at line {line_number}: {error}") from error
        require(isinstance(item, dict) and type(item.get("schema")) is int and item["schema"] == 1,
                "Unsupported animation diagnostic schema")
        require(item.get("version") == expected_version, "Unexpected animation diagnostic version")
        require(type(item.get("session")) is int and item["session"] >= 0, "Invalid diagnostic session")
        require(item.get("phase") in ("start", "sample", "end", "error", "status"), "Unknown diagnostic phase")
        finite_tree(item)
        result.append(item)
    require(result, "No animation diagnostic records")
    return result


def validate(lines, expected_version, session=None):
    all_records = records(lines, expected_version)
    sessions = {item["session"] for item in all_records if item["phase"] != "status"}
    if session is None:
        require(len(sessions) == 1, "Select exactly one capture with --session")
        session, = sessions
    require(type(session) is int and session > 0 and session in sessions, "Unknown capture session")
    selected = [item for item in all_records if item["session"] == session and item["phase"] != "status"]
    require(len(selected) >= 2 and selected[0]["phase"] == "start" and selected[-1]["phase"] == "end",
            "Capture is incomplete: start/end required")
    require(sum(item["phase"] == "start" for item in selected) == 1 and
            sum(item["phase"] == "end" for item in selected) == 1, "Duplicate start/end or reused session")
    start, end = selected[0], selected[-1]
    require(start.get("interval_seconds") == .25 and start.get("max_seconds") == 30 and
            start.get("max_samples") == 120 and start.get("max_active_units") == 2 and
            start.get("bone_names") == list(BONES) and start.get("wait_for_outfit") is True and
            start.get("time_basis") == "matching-outfit-world-animation-dt", "Capture budget or bone inventory differs")
    require(end.get("reason") in ("user_off", "sample_limit", "time_limit", "reset", "reload", "restarted",
                                  "world_release", "mod_disabled", "mod_unload", "runtime_reset", "state_ingame_exit", "diagnostic_error"),
            "Unknown completion reason")
    samples = [item for item in selected if item["phase"] == "sample"]
    require(type(end.get("sample_count")) is int and end["sample_count"] == len(samples) <= 120,
            "Missing or duplicate sample records")
    errors = [item for item in selected if item["phase"] == "error"]
    require(len(errors) <= 1 and (bool(errors) == (end["reason"] == "diagnostic_error")), "Malformed diagnostic failure")
    if errors:
        require(selected[-2] == errors[0] and errors[0].get("reason") == "diagnostic_api_or_data_unavailable" and
                type(errors[0].get("sample_count")) is int and errors[0]["sample_count"] == len(samples),
                "Diagnostic error must close the capture at the exact sample count")
    require(all(item["phase"] in ("sample", "error") for item in selected[1:-1]), "Unexpected capture record")
    profiles, observed_events, releases, units, progressing = set(), set(), set(), set(), set()
    previous = {}
    statuses = {"no_custom_profile": 0, "unregistered_custom_profile": 0, "registered_custom_profile": 0}
    for index, sample in enumerate(samples):
        require(type(sample.get("sample_index")) is int and sample["sample_index"] == index, "Sample sequence gap/duplicate")
        require(type(sample.get("unit_id")) is int and 0 < sample["unit_id"] <= 2, "Invalid unit identity")
        require(finite_number(sample.get("time_seconds")) and 0 < sample["time_seconds"] < 30,
                "Invalid sample time")
        require(finite_number(sample.get("animation_dt")) and sample["animation_dt"] > 0,
                "Invalid animation update delta")
        require(sample.get("stage") == "post_presentation" and sample.get("native_fixed_frame_oracle") is False,
                "Diagnostic scope was changed")
        status = sample.get("profile_status")
        require(status in statuses, "Unknown profile status")
        statuses[status] += 1
        units.add(sample["unit_id"])
        last = previous.get(sample["unit_id"])
        require(last is None or sample["time_seconds"] > last["time_seconds"], "Repeated/backward unit sample")
        if status == "registered_custom_profile":
            sampler = sample.get("sampler")
            require(isinstance(sampler, dict) and re.fullmatch(r"[a-f0-9]{64}", sampler.get("manifest_id", "")) is not None,
                    "Missing registered manifest identity")
            require(isinstance(sample.get("profile_id"), str) and sample["profile_id"], "Missing profile ID")
            require(sampler.get("pose_owner") in ("authored", "legacy") and isinstance(sampler.get("state"), str),
                    "Missing sampler state/ownership")
            require(all(type(sampler.get(key)) is bool for key in ("active", "blocked", "clock_reset")),
                    "Missing sampler flags")
            require(type(sampler.get("frame")) is int and sampler["frame"] >= 0 and
                    type(sampler.get("release_serial")) is int and sampler["release_serial"] >= 0,
                    "Invalid sampler counters")
            require(sampler.get("helper_visibility_policy") == "per-mesh-default-and-shadow-hidden-configured" and
                    type(sampler.get("sampler_mesh_count")) is int and 0 <= sampler["sampler_mesh_count"] <= 256,
                    "Missing helper visibility configuration")
            for clock, length in (("helper_clock", "helper_length"), ("visible_clock", "visible_length")):
                require(finite_number(sample.get(clock)) and finite_number(sample.get(length)) and
                        0 < sample[length] <= 3600 and 0 <= sample[clock] <= sample[length] + .002, "Invalid native clock")
            for key in ("bones_local", "helper_bones_local"):
                require(isinstance(sample.get(key), dict) and set(sample[key]) == set(BONES), "Incomplete matrix subset")
                for value in sample[key].values():
                    matrix(value)
            profiles.add(sampler["manifest_id"])
            observed_events.add((sample["unit_id"], sampler.get("event"), sampler.get("event_frame")))
            if sampler["release_serial"] > 0:
                releases.add((sample["unit_id"], sampler["release_serial"]))
            if last and last["profile_status"] == status:
                old = last["sampler"]
                same_event = all(old.get(key) == sampler.get(key) for key in ("manifest_id", "state", "event_frame"))
                if same_event and not sampler["blocked"] and abs(sample["helper_clock"] - last["helper_clock"]) > .000001:
                    progressing.add(sample["unit_id"])
        else:
            require(not any(key in sample for key in ("sampler", "bones_local", "helper_bones_local", "helper_clock")),
                    "Unregistered profile cannot supply custom native evidence")
        previous[sample["unit_id"]] = sample
    if errors:
        status = "diagnostic-unavailable"
    elif not samples:
        status = "no-animation-samples-recorded"
    elif statuses["registered_custom_profile"]:
        status = "passive-native-animation-observations-recorded"
    elif statuses["unregistered_custom_profile"]:
        status = "custom-profile-not-registered"
    else:
        status = "no-custom-profile-observed"
    return {"schema": 1, "status": status, "version": expected_version, "session": session,
            "sample_count": len(samples), "unit_count": len(units), "profile_status_counts": statuses,
            "manifest_ids": sorted(profiles), "observed_event_count": len(observed_events),
            "observed_release_counters": len(releases), "units_with_helper_clock_progress": sorted(progressing),
            "native_fixed_frame_oracle_samples": 0, "gameplay_acceptance": "not inferred",
            "rendered_skin_acceptance": "not inferred", "track_preservation": "not inferred from logs",
            "completion_reason": end["reason"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console_log", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--session", type=int)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with args.console_log.open(encoding="utf-8", errors="strict") as source:
        report = validate(source, args.expected_version, args.session)
    report["console_log_sha256"] = hashlib.sha256(args.console_log.read_bytes()).hexdigest()
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.report:
        require(args.report.resolve() != args.console_log.resolve(), "Report cannot overwrite source log")
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
