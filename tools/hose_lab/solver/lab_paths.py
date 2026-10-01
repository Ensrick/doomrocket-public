"""Paths shared by the offline solver tools; generated output stays ignored."""
from pathlib import Path
import sys

if sys.flags.optimize:
    raise RuntimeError('Run the offline hose lab without -O/PYTHONOPTIMIZE; validation assertions are required.')

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "tools/hose_lab/rig/runtime_contract.json"
DEFAULT_TRAJECTORY = ROOT / ".build/hose_solver_probe/trajectory.json"


def generated_output(value):
    """Reject output outside this checkout's ignored .build directory."""
    path = Path(value).resolve()
    boundary = (ROOT / ".build").resolve()
    if path == boundary or boundary not in path.parents:
        raise ValueError(f"Generated output must be a file below {boundary}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
