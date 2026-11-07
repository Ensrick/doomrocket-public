#!/usr/bin/env python3
"""Fast repository checks that do not require the VT2 SDK or compiled bundles."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

# Steamworks' char buffers include the terminating NUL: 8000 and 128 + 1.
# https://partner.steamgames.com/doc/api/ISteamUGC#SetItemDescription
# https://partner.steamgames.com/doc/api/ISteamRemoteStorage#k_cchPublishedDocumentDescriptionMax
# Reserve the terminator, measure encoded bytes, and reject embedded NULs.
WORKSHOP_DESCRIPTION_MAX_BYTES = 7999
WORKSHOP_TITLE_MAX_BYTES = 128


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def cfg_value(text: str, key: str) -> str:
    match = re.search(
        rf'^\s*{re.escape(key)}\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(\d+)L?)\s*;',
        text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(f"itemV2.cfg is missing {key!r}")
    if match.group(1) is None:
        return match.group(2)
    # Match the canonical launcher's ModDiscovery.Unescape order. In particular,
    # count the decoded quote/newline/tab, not the cfg escape's source spelling.
    return (match.group(1).replace('\\"', '"').replace('\\\\', '\\')
            .replace('\\n', '\n').replace('\\t', '\t'))


def check_workshop_metadata_limits(failures: list[str], title: str, description: str) -> None:
    """Validate the parsed strings passed through canonical VMB upload staging."""
    for key, value, maximum in (("title", title, WORKSHOP_TITLE_MAX_BYTES),
                                 ("description", description, WORKSHOP_DESCRIPTION_MAX_BYTES)):
        if "\0" in value:
            failures.append(f"Workshop {key} contains an embedded NUL")
            continue
        # UploadStager.EscapeForCfg removes CRs before libconfig reads the
        # staged string. Preserve LF/tab/Unicode, as that process does.
        size = len(value.replace("\r", "").encode("utf-8"))
        if size > maximum:
            failures.append(
                f"Workshop {key} is {size} UTF-8 bytes; maximum is {maximum} "
                "bytes excluding the terminating NUL"
            )


def loaded_version() -> str:
    lua = read("scripts/mods/doomrocket/doomrocket.lua")
    match = re.search(r'local\s+MOD_VERSION\s*=\s*"([^"]+)"', lua)
    if not match:
        raise ValueError("doomrocket.lua is missing the MOD_VERSION constant")
    return match.group(1)


def tracked_generated_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "bundleV2", ".build", "*.mod_bundle", "*.processed"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def check_issue_forms(failures: list[str], version: str) -> None:
    template_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
    config = yaml.safe_load((template_dir / "config.yml").read_text(encoding="utf-8"))
    if config.get("blank_issues_enabled") is not False:
        failures.append("public repository must use the issue chooser instead of blank issues")

    expected = {
        "bug_report.yml": "Gameplay or presentation bug",
        "crash_report.yml": "Crash report",
        "feedback.yml": "Balance or design feedback",
    }
    for filename, expected_name in expected.items():
        path = template_dir / filename
        if not path.is_file():
            failures.append(f"missing public issue form: {filename}")
            continue
        form = yaml.safe_load(path.read_text(encoding="utf-8"))
        if form.get("name") != expected_name:
            failures.append(f"{filename}: unexpected chooser name")
        if not form.get("description") or not isinstance(form.get("body"), list):
            failures.append(f"{filename}: name, description, and body are required")
            continue
        ids = [entry.get("id") for entry in form["body"] if entry.get("id")]
        if len(ids) != len(set(ids)):
            failures.append(f"{filename}: field ids must be unique")
        if filename in {"bug_report.yml", "crash_report.yml"}:
            uploads = [entry for entry in form["body"] if entry.get("type") == "upload"]
            log_uploads = [
                entry
                for entry in uploads
                if ".log" in entry.get("validations", {}).get("accept", "")
            ]
            if not log_uploads:
                failures.append(f"{filename}: must explicitly accept a .log upload")
            elif log_uploads[0].get("validations", {}).get("required") is not True:
                failures.append(f"{filename}: console log upload must be required")
            if version not in path.read_text(encoding="utf-8"):
                failures.append(f"{filename}: loaded-banner guidance must name v{version}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=("public", "development"), required=True)
    args = parser.parse_args()

    failures: list[str] = []
    try:
        cfg = read("itemV2.cfg")
        version = loaded_version()
        title = cfg_value(cfg, "title")
        description = cfg_value(cfg, "description")
        workshop_id = cfg_value(cfg, "published_id")
        visibility = cfg_value(cfg, "visibility")
        preview = cfg_value(cfg, "preview")
    except (OSError, ValueError) as exc:
        print(f"[repository-check] FAIL - {exc}")
        return 1

    if visibility != "public":
        failures.append("Workshop visibility must remain public")
    if title != ("Warlock Engineer v" + version if args.channel == "public" else "Warlock Engineer TEST v" + version):
        failures.append("Workshop title and Lua MOD_VERSION are out of sync")
    check_workshop_metadata_limits(failures, title, description)

    if args.channel == "public":
        if workshop_id != "3771657344":
            failures.append("public channel must target Workshop item 3771657344")
        if preview != "item_preview.png":
            failures.append("public channel must use item_preview.png")
        if not version.endswith("-alpha"):
            failures.append("public version must use the -alpha suffix")
        if re.search(r"TEST|Currently Unstable|-dev", title, re.IGNORECASE):
            failures.append("public title must not contain TEST, Currently Unstable, or -dev")
        for required in (
            "[h2]Bug reports and feedback[/h2]",
            "1369573612",
            "Modded Realm",
            "doomrocket-public/issues/new/choose",
            f"[doomrocket:LOAD] v{version}",
        ):
            if required not in cfg:
                failures.append(f"public Workshop description is missing: {required}")
        for required_file in (
            "README.md",
            "PROJECT_STATUS.md",
            "CONTRIBUTING.md",
            "docs/BUG_REPORTING.md",
            "docs/RELEASE_CHANNELS.md",
            "docs/TESTER_CHECKLIST.md",
            "tools/Invoke-DoomrocketRelease.ps1",
        ):
            if not (ROOT / required_file).is_file():
                failures.append(f"missing public guidance: {required_file}")
        check_issue_forms(failures, version)
    else:
        if workshop_id != "3794172730":
            failures.append("development channel must target Workshop item 3794172730")
        if preview != "item_preview_test.png":
            failures.append("development channel must use item_preview_test.png")
        if not version.endswith("-dev"):
            failures.append("development version must use the -dev suffix")
        for required in ("DEVELOPMENT TEST BUILD", "Do not enable it together with the public"):
            if required not in cfg:
                failures.append(f"development Workshop description is missing: {required}")

    generated = tracked_generated_files()
    if generated:
        failures.append("generated/game-derived files are tracked: " + ", ".join(generated))

    if failures:
        print("[repository-check] FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"[repository-check] OK - {args.channel} channel v{version}, Workshop {workshop_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
