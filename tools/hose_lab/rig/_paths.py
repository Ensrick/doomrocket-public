"""Resolve this offline lab's source/output paths; never target shipping assets."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compile_paths import validate_probe

def resolve_paths(*, blender=False):
    if sys.flags.optimize:
        raise RuntimeError("Rig validation requires Python assertions; do not use -O or PYTHONOPTIMIZE")
    default_repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=default_repo)
    parser.add_argument("--output", type=Path, help="Owned output directory inside the checkout's ignored .build")
    argv = sys.argv[sys.argv.index("--")+1:] if blender and "--" in sys.argv else ([] if blender else sys.argv[1:])
    args = parser.parse_args(argv)
    try:
        base = validate_probe(args.repo, args.output or Path(".build/hose_rig_probe"))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    repo = args.repo.resolve()
    if not (repo / "AGENTS.md").is_file() or not (repo / "tools").is_dir():
        parser.error("--repo must identify the Doomrocket checkout")
    base.mkdir(parents=True, exist_ok=True)
    return base, repo
