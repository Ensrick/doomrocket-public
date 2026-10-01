"""Generate compiler-only chain experiments under the repository's ignored .build.

Some negative cases are unsafe to simulate. This tool never launches the game.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEFAULT_PROBE = REPO / ".build/hose_lab_native_chain_probe"
CASES = ("base", "mass_zero", "mass_numeric", "mass_string", "bone_swap",
         "flags", "unknown_pin", "expressions", "no_tip_bone")


def load_base() -> dict:
    return json.loads((HERE / "chain_base.json").read_text(encoding="utf-8"))


def make_cases(base: dict) -> dict[str, dict]:
    cases = {name: copy.deepcopy(base) for name in CASES}
    for name, value in (("mass_zero", "0"), ("mass_numeric", 7.5), ("mass_string", "7.5")):
        cases[name]["constraints"]["hose"]["link_2"]["mass"] = value
    cases["bone_swap"]["constraints"]["hose"]["link_2"]["bone"] = "root"
    cases["flags"]["constraints"]["hose"]["link_2"].update(
        constraint_type=2, constraint_torsion_spring=1)
    unknown = cases["unknown_pin"]["constraints"]["hose"]
    unknown["tip_target"] = "root"
    unknown["link_2"].update(fixed=True, pin=True, inverse_mass="0", target="root")
    expressions = cases["expressions"]["constraints"]["hose"]
    expressions.update(gravity="1.25", global_damping="0.5", vector_field_multiplier="0.75")
    expressions["link_2"].update(constraint_rotation="0.625", length="0.875", damping="0.875",
                                 constraint_damping="0.625", torsion_coef="6", constraint_angle="90")
    del cases["no_tip_bone"]["constraints"]["hose"]["link_2"]["bone"]
    return cases


def sjson(value, depth: int = 0) -> str:
    if isinstance(value, dict):
        rows = [" " * (2 * (depth + 1)) + json.dumps(key) + " = " + sjson(item, depth + 1)
                for key, item in value.items()]
        return "{\n" + "\n".join(rows) + "\n" + " " * (2 * depth) + "}"
    if isinstance(value, list):
        return "[ " + ", ".join(sjson(item, depth + 1) for item in value) + " ]"
    return json.dumps(value, allow_nan=False)


def render_case(value: dict) -> str:
    return "\n".join(f"{key} = {sjson(item)}" for key, item in value.items()) + "\n"


def checked_output(path: Path) -> Path:
    resolved = path.resolve()
    build = (REPO / ".build").resolve()
    if resolved == build or not resolved.is_relative_to(build):
        raise ValueError("Generated output must be a dedicated directory below this repo's .build")
    return resolved


def generate(output_dir: Path) -> dict:
    output = checked_output(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, case in make_cases(load_base()).items():
        filename = f"chain_{name}.state_machine"
        content = render_case(case).encode("utf-8")
        (output / filename).write_bytes(content)
        manifest[filename] = hashlib.sha256(content).hexdigest()
    bones = (HERE / "probe.bones").read_bytes()
    (output / "probe.bones").write_bytes(bones)
    manifest["probe.bones"] = hashlib.sha256(bones).hexdigest()
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PROBE / "source")
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir), indent=2, sort_keys=True))
