"""Summarize hose execution evidence; pose writes do not prove rendered pixels."""
import argparse
import json
from pathlib import Path
import re


def analyze(text, expected_version):
    versions = sorted(set(re.findall(r"\[doomrocket:LOAD\] v([^\s]+)", text)))
    if versions != [expected_version]:
        raise ValueError(f"Expected only v{expected_version}; found {versions}")
    hoses = {}
    for line in text.splitlines():
        if "[doomrocket:HOSE]" not in line:
            continue
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line))
        identity, phase = fields.get("id"), fields.get("phase")
        if not identity:
            continue
        hose = hoses.setdefault(identity, {
            "created": 0, "pose_write_observed": False, "sample_observed": False,
            "diagnostics": [], "stop": None,
        })
        if phase == "start":
            hose["created"] += 1
        elif phase == "pose_write":
            hose["pose_write_observed"] = True
        elif phase == "sample":
            hose["sample_observed"] = True
        elif phase == "diagnostic":
            hose["diagnostics"].append(fields)
        elif phase == "stop":
            hose["stop"] = fields
    for hose in hoses.values():
        reasons = sorted({event.get("reason", "unknown") for event in hose["diagnostics"]})
        if reasons:
            hose["finding"] = "Recorded controller conditions: " + ", ".join(reasons)
        elif hose["pose_write_observed"] or hose["sample_observed"]:
            hose["finding"] = "Pose updates observed; visible rendering needs visual evidence."
        else:
            hose["finding"] = "No completed pose-update evidence; cause unresolved."
    return {"version": expected_version, "hoses": hoses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    try:
        result = analyze(args.log.read_text(encoding="utf-8-sig", errors="replace"), args.expected_version)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
