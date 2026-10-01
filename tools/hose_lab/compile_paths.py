"""Read-only path preflight shared by the isolated SDK compile runners.

Reject redirects, including existing nested output files, before any writer is
started. This is a local workflow guard, not a lock against concurrent hostile
filesystem changes; maintainers must still coordinate use of the SDK compiler.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PureWindowsPath
import re
import stat


def lexical_path(value: Path | str, relative_to: Path) -> Path:
    path = Path(value)
    return Path(os.path.abspath(path if path.is_absolute() else relative_to / path))


def normalize_repo_prefix(repo_root: Path, value: Path) -> tuple[Path, Path]:
    """Expand only the supplied repo prefix, never uninspected descendants.

    Windows may supply an 8.3 alias for an otherwise ordinary directory. Resolve
    that known root once and carry over the lexical suffix, so .build and every
    descendant still undergo lstat/reparse inspection before being resolved.
    """
    lexical_repo = lexical_path(repo_root, Path.cwd())
    repo = lexical_repo.resolve(strict=True)
    path = lexical_path(value, lexical_repo)
    if path.is_relative_to(lexical_repo):
        path = repo / path.relative_to(lexical_repo)
    return repo, path


def reject_redirect(path: Path) -> None:
    try:
        info = path.lstat()  # Do not follow a dangling symlink or Windows junction.
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Reparse points, junctions and symlinks are forbidden in probe outputs: {path}")
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError(f"Hard-linked output files are forbidden because writes affect another path: {path}")


def validate_probe(repo_root: Path, probe_root: Path) -> Path:
    repo, probe = normalize_repo_prefix(repo_root, probe_root)
    boundary = repo / ".build"
    if probe == boundary or not probe.is_relative_to(boundary):
        raise ValueError("ProbeRoot must be a dedicated directory below this repository .build")
    # Inspect .build itself and every ancestor before resolving the target. In
    # particular, resolving .build first would silently bless an external mount.
    cursor = boundary
    for part in (None, *probe.relative_to(boundary).parts):
        if part is not None:
            cursor /= part
        reject_redirect(cursor)
        if cursor.exists() and not cursor.is_dir():
            raise ValueError(f"Probe output ancestor is not a directory: {cursor}")
    if not probe.resolve().is_relative_to(boundary):
        raise ValueError("Resolved probe escapes .build")
    if probe.exists():
        def walk_error(error):
            raise error

        # Checking only source/data/bundle roots misses a redirected individual
        # FBX, log, material, generated descriptor or nested compiler directory.
        for directory, dirs, files in os.walk(probe, followlinks=False, onerror=walk_error):
            reject_redirect(Path(directory))
            for name in (*dirs, *files):
                reject_redirect(Path(directory) / name)
    return probe


def indexed_resources(repo_root: Path, probe_root: Path, data_root: Path,
                      resources: list[str]) -> list[Path]:
    probe = validate_probe(repo_root, probe_root)
    _, data = normalize_repo_prefix(repo_root, data_root)
    if data == probe or not data.is_relative_to(probe) or not data.is_dir():
        raise ValueError("Data root must be an existing directory inside the dedicated probe")
    entries = re.findall(r'^"([^"\r\n]+)"\s*=\s*"([^"\r\n]+)"\s*$',
                         (data / "debug_file_index.sjson").read_text(encoding="utf-8"), re.MULTILINE)
    results = []
    for resource in resources:
        matches = [name for name, source in entries if source == resource]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one SDK index entry for {resource}; found {len(matches)}")
        name = matches[0]
        if (PureWindowsPath(name).drive or name.startswith("/") or "\\" in name
                or any(part in ("", ".", "..") or ":" in part for part in name.split("/"))):
            raise ValueError(f"SDK index path must be a plain relative path: {name}")
        path = (data / name).resolve(strict=True)
        if not path.is_relative_to(data) or not path.is_file():
            raise ValueError(f"SDK index path is not a file inside the data root: {name}")
        results.append(path)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--probe-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--resource", action="append", default=[])
    args = parser.parse_args()
    if bool(args.data_root) != bool(args.resource):
        parser.error("--data-root and at least one --resource must be supplied together")
    if args.resource:
        for path in indexed_resources(args.repo_root, args.probe_root, args.data_root, args.resource):
            print(path)
    else:
        validate_probe(args.repo_root, args.probe_root)
