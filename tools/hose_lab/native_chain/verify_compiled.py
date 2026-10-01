"""Verify differential behavior in actual SDK output; never invoke compiler/game."""
import argparse
import copy
import json
import math
import re
from pathlib import Path

from chain_descriptor import parse_single_chain
from generate_fixtures import CASES, DEFAULT_PROBE, load_base


def check(condition, message):
    if not condition:
        raise ValueError(message)


def read_cases(data_root: Path) -> dict:
    root = data_root.resolve()
    index = (root / "debug_file_index.sjson").read_text(encoding="utf-8")
    entries = re.findall(r'"([^"]+)"\s*=\s*"([^"]+)"', index)
    results = {}
    for name in CASES:
        matches = [path for path, source in entries if source == f"chain_{name}.state_machine"]
        check(len(matches) == 1, f"Expected one compiled resource for {name}")
        path = (root / matches[0]).resolve()
        check(path.is_relative_to(root), "Compiled resource path escapes data root")
        results[name] = parse_single_chain(path.read_bytes())
    return results


def verify(results: dict) -> list[dict]:
    base = results["base"]
    authored = load_base()["constraints"]["hose"]
    for key in ("gravity", "global_damping", "vector_field_multiplier"):
        check(math.isclose(base[key], float(authored[key]), abs_tol=1e-6), f"Wrong base {key}")
    check(base["link_count"] == 3 and base["enabled"] == 1 and base["debug_draw"] == 0,
          "Wrong base count or flags")
    for i, link in enumerate(base["links"]):
        check(link["bone_index"] == i + 1, f"Wrong base bone {i}")
        for key, value in authored[f"link_{i}"].items():
            if key != "bone":
                check(math.isclose(link[key], float(value), abs_tol=1e-6), f"Wrong base {i}.{key}")
    mutations = {
        "mass_zero": {"mass": 0}, "mass_numeric": {"mass": 1}, "mass_string": {"mass": 7.5},
        "bone_swap": {"bone_index": 0}, "no_tip_bone": {"bone_index": 0xFFFFFFFF},
        "flags": {"constraint_type": 2, "constraint_torsion_spring": 1},
        "expressions": {"constraint_rotation": .625, "length": .875, "damping": .875,
                        "constraint_damping": .625, "torsion_coef": 6, "constraint_angle": 90},
    }
    metadata = {"sha256", "_blob"}
    summaries = []
    for name in CASES:
        expected = {k: copy.deepcopy(v) for k, v in base.items() if k not in metadata}
        expected["links"][2].update(mutations.get(name, {}))
        if name == "expressions":
            expected.update(gravity=1.25, global_damping=.5, vector_field_multiplier=.75)
        actual = {k: v for k, v in results[name].items() if k not in metadata}
        check(actual == expected, f"Unexpected semantic mutation in {name}")
        offsets = [i for i, (a, b) in enumerate(zip(base["_blob"], results[name]["_blob"])) if a != b]
        check(bool(offsets) == (name not in ("base", "unknown_pin")), f"Wrong byte-difference result for {name}")
        summaries.append({"fixture": name, "descriptor_sha256": results[name]["sha256"],
                          "changed_byte_offsets": offsets})
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_PROBE / "data")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    summaries = verify(read_cases(args.data_root))
    if not args.quiet:
        print(json.dumps(summaries, indent=2))
    print("PASS: nine compiler-produced chain cases; constants, bindings, flags, default traps and ignored pin keys")
