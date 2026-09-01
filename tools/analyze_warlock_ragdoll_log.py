#!/usr/bin/env python3
"""Validate one Warlock ragdoll telemetry capture.

The source-policy suite prevents known-dangerous implementations from shipping.
This analyzer covers the part a static check cannot prove: one corpse must stay
correlatable, visible, and spatially coherent for the observation window.

Telemetry schema (one whitespace-delimited record per line)::

    [doomrocket:LOAD] v0.1.55-alpha
    [doomrocket:RAGDOLL] phase=begin id=unit-0017 source=unit ...
    [doomrocket:RAGDOLL] phase=sample id=unit-0017 source=unit elapsed_ms=16 pose_writes=1 sleep_skips=0 ...
    [doomrocket:RAGDOLL] phase=stop id=unit-0017 source=unit callbacks=300 pose_writes=300 sleep_skips=0 ...

Every marked line needs ``id`` and ``source``.  ``id`` is globally unique in a
capture and therefore cannot silently switch between the unit and husk lanes.
Use ``--expected-version`` for acceptance runs so a stale Workshop payload
cannot satisfy the current telemetry contract.  Omitting it intentionally
keeps historical-log triage possible.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


MARKER = "[doomrocket:RAGDOLL]"
LOAD_RE = re.compile(r"\[doomrocket:LOAD\]\s+v([^\s]+)")
FIELD_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)=(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s]+)"
)
VALID_PHASES = {"begin", "sample", "stop", "carrier_reveal"}
STANDARD_CHECKPOINTS_MS = (0.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0)
EXPECTED_NODE_COUNT = 90
ZERO_COUNTERS = (
    "custom_actor_count",
    "custom_actors",
    "carrier_reveal_count",
    "carrier_reveals",
    "native_meshes_visible",
    "parent_mismatch",
    "scale_mutations",
    "nonhips_translation_mutations",
)
FALSE_FLAGS = ("carrier_visible", "solver_explosion", "physics_anomaly", "escape")
REQUIRED_SAMPLE_FIELDS = (
    "checkpoint_ms",
    "wall_gap_ms",
    "nodes",
    "custom_actors",
    "carrier_reveals",
    "parent_mismatch",
    "root_delta",
    "named_root_drift",
    "hips_delta",
    "hips_drift",
    "anchor_max_drift",
    "scale_mutations",
    "nonhips_translation_mutations",
    "bounds_ratio",
    "max_bone_radius_ratio",
    "pose_writes",
    "sleep_skips",
)


@dataclass(frozen=True)
class Record:
    line_number: int
    text: str
    fields: dict[str, str]


@dataclass
class CorpseTrace:
    identifier: str
    source: str
    begin: Record | None = None
    samples: list[Record] = field(default_factory=list)
    stop: Record | None = None
    last_elapsed_seconds: float = -math.inf
    node_count: int | None = None
    last_sample_pose_writes: int = 0
    last_sample_sleep_skips: int = 0


def parse_fields(payload: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(payload):
        value = match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[match.group(1)] = value.rstrip(",")
    return fields


def parse_bool(value: str) -> bool | None:
    normalized = value.lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def finite_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def integer_value(value: str, *, minimum: int = 0) -> int | None:
    parsed = finite_float(value)
    if parsed is None or not parsed.is_integer() or parsed < minimum:
        return None
    return int(parsed)


def elapsed_seconds(record: Record) -> float | None:
    if "elapsed_ms" in record.fields:
        value = finite_float(record.fields["elapsed_ms"])
        return None if value is None else value / 1000.0
    if "elapsed_s" in record.fields:
        return finite_float(record.fields["elapsed_s"])
    return None


def analyze(
    lines: Iterable[str],
    *,
    max_hips_drift: float,
    min_survival_seconds: float,
    min_samples: int,
    max_frame_ms: float,
    max_deformation_ratio: float,
    max_root_delta: float,
    max_hips_delta: float,
    max_anchor_drift: float,
    expected_nodes: int,
    expected_version: str | None = None,
) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    records: list[Record] = []
    traces: dict[tuple[str, str], CorpseTrace] = {}
    id_sources: dict[str, str] = {}
    missing_schema: dict[tuple[str, ...], list[int]] = {}
    legacy_max_hips_delta: tuple[float, int] | None = None
    legacy_carrier_reveals: list[int] = []
    legacy_disappearances: list[int] = []
    load_versions: list[str] = []

    for line_number, text in enumerate(lines, 1):
        load_match = LOAD_RE.search(text)
        if load_match:
            load_versions.append(load_match.group(1).rstrip(","))
        if MARKER not in text:
            continue
        payload = text.split(MARKER, 1)[1]
        record = Record(line_number, text.rstrip("\r\n"), parse_fields(payload))
        records.append(record)

        missing = [name for name in ("phase", "id", "source") if not record.fields.get(name)]
        if missing:
            missing_schema.setdefault(tuple(missing), []).append(line_number)
            hips_delta_text = record.fields.get("hips_delta")
            hips_delta = finite_float(hips_delta_text) if hips_delta_text is not None else None
            if hips_delta is not None and (
                legacy_max_hips_delta is None or abs(hips_delta) > legacy_max_hips_delta[0]
            ):
                legacy_max_hips_delta = (abs(hips_delta), line_number)
            if re.search(r"donor\s+fallback\s+visibility=true", payload, re.IGNORECASE):
                legacy_carrier_reveals.append(line_number)
            if (
                parse_bool(record.fields.get("owner_alive", "")) is True
                and parse_bool(record.fields.get("outfit_alive", "")) is False
            ):
                legacy_disappearances.append(line_number)
            continue

        phase = record.fields["phase"]
        identifier = record.fields["id"]
        source = record.fields["source"]
        if phase not in VALID_PHASES:
            errors.append(f"line {line_number}: unknown phase={phase!r}")
            continue
        if source not in {"unit", "husk"}:
            errors.append(f"line {line_number}: invalid source={source!r}, expected unit or husk")
            continue
        previous_source = id_sources.get(identifier)
        if previous_source is not None and previous_source != source:
            errors.append(
                f"line {line_number}: id={identifier} changed source "
                f"from {previous_source!r} to {source!r}"
            )
            continue
        if re.fullmatch(re.escape(source) + r"-[0-9]+", identifier) is None:
            errors.append(
                f"line {line_number}: id={identifier!r} must match {source}-<digits>"
            )
            continue
        id_sources[identifier] = source

        key = (identifier, source)
        trace = traces.setdefault(key, CorpseTrace(identifier, source))
        if phase == "begin":
            if trace.begin is not None:
                errors.append(
                    f"line {line_number}: duplicate begin for id={identifier} source={source}"
                )
            elif trace.samples or trace.stop is not None:
                errors.append(
                    f"line {line_number}: begin follows sample/stop for id={identifier} source={source}"
                )
            trace.begin = record
        elif phase == "sample":
            if trace.begin is None:
                errors.append(
                    f"line {line_number}: sample precedes begin for id={identifier} source={source}"
                )
            if trace.stop is not None:
                errors.append(
                    f"line {line_number}: sample follows stop for id={identifier} source={source}"
                )
            trace.samples.append(record)
        elif phase == "stop":
            if trace.begin is None:
                errors.append(
                    f"line {line_number}: stop precedes begin for id={identifier} source={source}"
                )
            if trace.stop is not None:
                errors.append(
                    f"line {line_number}: duplicate stop for id={identifier} source={source}"
                )
            trace.stop = record
        else:
            errors.append(
                f"line {line_number}: native carrier reveal incident for "
                f"id={identifier} source={source}"
            )

        elapsed = elapsed_seconds(record)
        if elapsed is None:
            errors.append(f"line {line_number}: missing/invalid elapsed_ms or elapsed_s")
        elif elapsed < trace.last_elapsed_seconds:
            errors.append(
                f"line {line_number}: elapsed time regressed for id={identifier} source={source}"
            )
        else:
            trace.last_elapsed_seconds = elapsed

        if "outfit_alive" in record.fields:
            outfit_alive = parse_bool(record.fields["outfit_alive"])
            if outfit_alive is None:
                errors.append(f"line {line_number}: invalid outfit_alive value")
            elif not outfit_alive and phase in {"begin", "sample"}:
                errors.append(f"line {line_number}: custom corpse disappeared (outfit_alive=false)")
        elif phase in {"begin", "sample"}:
            errors.append(f"line {line_number}: phase={phase} missing outfit_alive")

        if phase in {"begin", "sample"}:
            owner_alive = parse_bool(record.fields.get("owner_alive", ""))
            if owner_alive is None:
                errors.append(f"line {line_number}: phase={phase} missing/invalid owner_alive")
            elif not owner_alive:
                errors.append(f"line {line_number}: phase={phase} has owner_alive=false")

        for field_name in ZERO_COUNTERS:
            if field_name not in record.fields:
                continue
            value = finite_float(record.fields[field_name])
            if value is None:
                errors.append(f"line {line_number}: invalid {field_name} value")
            elif value != 0:
                errors.append(f"line {line_number}: {field_name}={value:g}, expected 0")

        for field_name in FALSE_FLAGS:
            if field_name not in record.fields:
                continue
            value = parse_bool(record.fields[field_name])
            if value is None:
                errors.append(f"line {line_number}: invalid {field_name} value")
            elif value:
                errors.append(f"line {line_number}: {field_name}=true")

        # checkpoint_ms is a requested sampling deadline and elapsed_ms is the
        # trace lifetime. Only explicit frame/gap durations are performance
        # signals.
        for frame_field in ("frame_ms", "wall_gap_ms"):
            if frame_field not in record.fields:
                continue
            frame_ms = finite_float(record.fields[frame_field])
            if frame_ms is None or frame_ms < 0:
                errors.append(f"line {line_number}: invalid {frame_field} value")
            elif frame_ms > max_frame_ms:
                errors.append(
                    f"line {line_number}: {frame_field}={frame_ms:g} exceeds {max_frame_ms:g} ms"
                )

        for ratio_field in ("bounds_ratio", "max_bone_radius_ratio"):
            if ratio_field not in record.fields:
                continue
            ratio = finite_float(record.fields[ratio_field])
            if ratio is None or ratio <= 0:
                errors.append(f"line {line_number}: invalid {ratio_field} value")
            elif ratio > max_deformation_ratio or ratio < 1.0 / max_deformation_ratio:
                errors.append(
                    f"line {line_number}: {ratio_field}={ratio:g} is outside "
                    f"[{1.0 / max_deformation_ratio:g}, {max_deformation_ratio:g}]x baseline"
                )

        if phase == "sample":
            missing_sample_fields = [
                name for name in REQUIRED_SAMPLE_FIELDS if name not in record.fields
            ]
            if missing_sample_fields:
                errors.append(
                    f"line {line_number}: sample missing "
                    f"{', '.join(missing_sample_fields)}"
                )

            pose_writes_text = record.fields.get("pose_writes")
            pose_writes = (
                integer_value(pose_writes_text, minimum=1)
                if pose_writes_text is not None
                else None
            )
            if pose_writes_text is not None and pose_writes is None:
                errors.append(f"line {line_number}: pose_writes must be a positive integer")
            elif pose_writes is not None:
                if pose_writes <= trace.last_sample_pose_writes:
                    errors.append(
                        f"line {line_number}: pose_writes={pose_writes} did not increase "
                        f"from {trace.last_sample_pose_writes} at the prior sample"
                    )
                trace.last_sample_pose_writes = pose_writes

            sleep_skips_text = record.fields.get("sleep_skips")
            sleep_skips = (
                integer_value(sleep_skips_text)
                if sleep_skips_text is not None
                else None
            )
            if sleep_skips_text is not None and sleep_skips is None:
                errors.append(f"line {line_number}: sleep_skips must be a non-negative integer")
            elif sleep_skips is not None:
                if sleep_skips < trace.last_sample_sleep_skips:
                    errors.append(
                        f"line {line_number}: sleep_skips={sleep_skips} regressed from "
                        f"{trace.last_sample_sleep_skips} at the prior sample"
                    )
                if sleep_skips != 0:
                    errors.append(
                        f"line {line_number}: sleep_skips={sleep_skips}, expected 0 "
                        "during the pre-monitor window"
                    )
                trace.last_sample_sleep_skips = sleep_skips

            nodes_text = record.fields.get("nodes")
            nodes_value = finite_float(nodes_text) if nodes_text is not None else None
            if nodes_text is not None and nodes_value is None:
                errors.append(f"line {line_number}: invalid nodes value")
            elif nodes_value is not None:
                if nodes_value <= 0 or not nodes_value.is_integer():
                    errors.append(f"line {line_number}: nodes must be a positive integer")
                elif int(nodes_value) != expected_nodes:
                    errors.append(
                        f"line {line_number}: nodes={int(nodes_value)}, expected {expected_nodes}"
                    )
                elif trace.node_count is None:
                    trace.node_count = int(nodes_value)
                elif int(nodes_value) != trace.node_count:
                    errors.append(
                        f"line {line_number}: nodes changed from {trace.node_count} "
                        f"to {int(nodes_value)}"
                    )

            root_delta_text = record.fields.get("root_delta")
            root_delta = finite_float(root_delta_text) if root_delta_text is not None else None
            if root_delta_text is not None and root_delta is None:
                errors.append(f"line {line_number}: invalid root_delta value")
            elif root_delta is not None and (root_delta < 0 or root_delta > max_root_delta):
                errors.append(
                    f"line {line_number}: root_delta={root_delta:g} m exceeds "
                    f"{max_root_delta:g} m"
                )

            named_root_text = record.fields.get("named_root_drift")
            named_root = (
                finite_float(named_root_text) if named_root_text is not None else None
            )
            if named_root_text is not None and (named_root is None or named_root < 0):
                errors.append(f"line {line_number}: invalid named_root_drift value")
            elif named_root is not None and named_root > max_root_delta:
                errors.append(
                    f"line {line_number}: named_root_drift={named_root:g} m exceeds "
                    f"{max_root_delta:g} m"
                )

            hips_delta_text = record.fields.get("hips_delta")
            hips_delta = finite_float(hips_delta_text) if hips_delta_text is not None else None
            if hips_delta_text is not None and (hips_delta is None or hips_delta < 0):
                errors.append(f"line {line_number}: invalid hips_delta value")
            elif hips_delta is not None and hips_delta > max_hips_delta:
                errors.append(
                    f"line {line_number}: hips_delta={hips_delta:g} m exceeds "
                    f"{max_hips_delta:g} m"
                )

            anchor_text = record.fields.get("anchor_max_drift")
            anchor = finite_float(anchor_text) if anchor_text is not None else None
            if anchor_text is not None and (anchor is None or anchor < 0):
                errors.append(f"line {line_number}: invalid anchor_max_drift value")
            elif anchor is not None and anchor > max_anchor_drift:
                errors.append(
                    f"line {line_number}: anchor_max_drift={anchor:g} m exceeds "
                    f"{max_anchor_drift:g} m"
                )

            checkpoint_text = record.fields.get("checkpoint_ms")
            checkpoint = finite_float(checkpoint_text) if checkpoint_text is not None else None
            if checkpoint_text is not None and (checkpoint is None or checkpoint < 0):
                errors.append(f"line {line_number}: invalid checkpoint_ms value")

            drift_text = record.fields.get("hips_drift")
            drift = finite_float(drift_text) if drift_text is not None else None
            if drift is None:
                errors.append(f"line {line_number}: sample missing/invalid hips_drift")
            elif abs(drift) > max_hips_drift:
                errors.append(
                    f"line {line_number}: hips_drift={drift:g} m exceeds "
                    f"{max_hips_drift:g} m"
                )

        if phase == "stop":
            for counter_name in ("callbacks", "pose_writes", "sleep_skips"):
                if counter_name not in record.fields:
                    errors.append(f"line {line_number}: stop missing {counter_name}")

            callbacks_text = record.fields.get("callbacks")
            callbacks = (
                integer_value(callbacks_text)
                if callbacks_text is not None
                else None
            )
            pose_writes_text = record.fields.get("pose_writes")
            pose_writes = (
                integer_value(pose_writes_text)
                if pose_writes_text is not None
                else None
            )
            sleep_skips_text = record.fields.get("sleep_skips")
            sleep_skips = (
                integer_value(sleep_skips_text)
                if sleep_skips_text is not None
                else None
            )
            if callbacks_text is not None and callbacks is None:
                errors.append(f"line {line_number}: callbacks must be a non-negative integer")
            if pose_writes_text is not None and pose_writes is None:
                errors.append(f"line {line_number}: pose_writes must be a non-negative integer")
            if sleep_skips_text is not None and sleep_skips is None:
                errors.append(f"line {line_number}: sleep_skips must be a non-negative integer")

            reason = record.fields.get("reason")
            # A stop record is emitted only before the monitor closes or at
            # monitor completion. Therefore every callback represented by it
            # belongs to the mandatory-write window, even if a malformed log
            # changes/omits reason=monitor_complete.
            if sleep_skips is not None and sleep_skips != 0:
                errors.append(
                    f"line {line_number}: sleep_skips={sleep_skips}, expected 0 "
                    "before monitor completion"
                )
            if callbacks is not None and pose_writes is not None and callbacks != pose_writes:
                errors.append(
                    f"line {line_number}: callbacks={callbacks} but pose_writes={pose_writes}; "
                    "every pre-monitor callback must write the pose"
                )
            if reason == "monitor_complete":
                if callbacks is not None and callbacks <= 0:
                    errors.append(f"line {line_number}: monitor completed without callbacks")
                if pose_writes is not None and pose_writes <= 0:
                    errors.append(f"line {line_number}: monitor completed without pose writes")
                if (
                    pose_writes is not None
                    and pose_writes < trace.last_sample_pose_writes
                ):
                    errors.append(
                        f"line {line_number}: stop pose_writes={pose_writes} is below "
                        f"the final sample value {trace.last_sample_pose_writes}"
                    )

    schema_errors: list[str] = []
    for missing, line_numbers in missing_schema.items():
        first_lines = ", ".join(str(number) for number in line_numbers[:5])
        suffix = "..." if len(line_numbers) > 5 else ""
        schema_errors.append(
            f"telemetry missing {', '.join(missing)} on {len(line_numbers)} line(s) "
            f"(first: {first_lines}{suffix})"
        )
    if legacy_max_hips_delta is not None and legacy_max_hips_delta[0] > max_hips_drift:
        schema_errors.append(
            f"uncorrelated hips_delta={legacy_max_hips_delta[0]:g} m exceeds "
            f"{max_hips_drift:g} m (line {legacy_max_hips_delta[1]})"
        )
    if legacy_carrier_reveals:
        schema_errors.append(
            f"legacy native carrier reveal on {len(legacy_carrier_reveals)} line(s) "
            f"(first: {legacy_carrier_reveals[0]})"
        )
    if legacy_disappearances:
        schema_errors.append(
            f"legacy custom corpse disappearance on {len(legacy_disappearances)} line(s) "
            f"(first: {legacy_disappearances[0]})"
        )
    errors = schema_errors + errors

    if expected_version is not None:
        normalized_expected_version = expected_version.removeprefix("v")
        unique_versions = sorted(set(load_versions))
        if not unique_versions:
            errors.append(
                f"expected [doomrocket:LOAD] v{normalized_expected_version} banner, found none"
            )
        elif unique_versions != [normalized_expected_version]:
            rendered_versions = ", ".join(f"v{version}" for version in unique_versions)
            errors.append(
                f"version banner mismatch: expected v{normalized_expected_version}, "
                f"found {rendered_versions}"
            )

    if not records:
        errors.append(f"no {MARKER} telemetry records found")

    trace_summaries: list[dict[str, object]] = []
    for trace in traces.values():
        label = f"id={trace.identifier} source={trace.source}"
        if trace.begin is None:
            errors.append(f"{label}: missing begin record")
        if trace.stop is None:
            errors.append(f"{label}: missing stop record")
        if len(trace.samples) < min_samples:
            errors.append(
                f"{label}: only {len(trace.samples)} sample(s), expected at least {min_samples}"
            )
        if trace.last_elapsed_seconds < min_survival_seconds:
            observed = max(trace.last_elapsed_seconds, 0.0)
            errors.append(
                f"{label}: observed for {observed:.3f} s, expected at least "
                f"{min_survival_seconds:g} s"
            )
        checkpoints = [
            finite_float(sample.fields["checkpoint_ms"])
            for sample in trace.samples
            if "checkpoint_ms" in sample.fields
        ]
        finite_checkpoints = [value for value in checkpoints if value is not None]
        required_checkpoint = min_survival_seconds * 1000.0
        if not finite_checkpoints or max(finite_checkpoints) < required_checkpoint:
            observed_checkpoint = max(finite_checkpoints, default=0.0)
            errors.append(
                f"{label}: last checkpoint_ms={observed_checkpoint:g}, expected at least "
                f"{required_checkpoint:g}"
            )
        if math.isclose(required_checkpoint, STANDARD_CHECKPOINTS_MS[-1]):
            missing_checkpoints = [
                expected
                for expected in STANDARD_CHECKPOINTS_MS
                if not any(math.isclose(actual, expected, abs_tol=0.5) for actual in finite_checkpoints)
            ]
            duplicate_checkpoints = sorted({
                actual
                for actual in finite_checkpoints
                if sum(math.isclose(other, actual, abs_tol=0.5) for other in finite_checkpoints) > 1
            })
            if missing_checkpoints:
                rendered = ", ".join(f"{value:g}" for value in missing_checkpoints)
                errors.append(f"{label}: missing required checkpoint_ms value(s): {rendered}")
            if duplicate_checkpoints:
                rendered = ", ".join(f"{value:g}" for value in duplicate_checkpoints)
                errors.append(f"{label}: duplicate checkpoint_ms value(s): {rendered}")
        trace_summaries.append(
            {
                "id": trace.identifier,
                "source": trace.source,
                "samples": len(trace.samples),
                "observed_seconds": max(trace.last_elapsed_seconds, 0.0),
                "stopped": trace.stop is not None,
            }
        )

    # Keep repeated semantic failures readable after schema failures have been
    # grouped above (legacy logs can contain hundreds of unkeyed records).
    errors = list(dict.fromkeys(errors))
    summary: dict[str, object] = {
        "records": len(records),
        "traces": trace_summaries,
        "max_hips_drift_m": max_hips_drift,
        "min_survival_seconds": min_survival_seconds,
        "max_deformation_ratio": max_deformation_ratio,
        "max_root_delta_m": max_root_delta,
        "max_hips_delta_m": max_hips_delta,
        "max_anchor_drift_m": max_anchor_drift,
        "expected_nodes": expected_nodes,
        "expected_version": expected_version.removeprefix("v") if expected_version else None,
        "load_versions": sorted(set(load_versions)),
        "passed": not errors,
    }
    return errors, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Vermintide 2 console log")
    parser.add_argument("--max-hips-drift", type=float, default=0.25, metavar="METERS")
    parser.add_argument("--min-survival-seconds", type=float, default=5.0, metavar="SECONDS")
    parser.add_argument("--min-samples", type=int, default=len(STANDARD_CHECKPOINTS_MS))
    parser.add_argument("--max-frame-ms", type=float, default=250.0, metavar="MS")
    parser.add_argument("--max-deformation-ratio", type=float, default=2.0, metavar="RATIO")
    parser.add_argument("--max-root-delta", type=float, default=0.25, metavar="METERS")
    parser.add_argument("--max-hips-delta", type=float, default=0.25, metavar="METERS")
    parser.add_argument("--max-anchor-drift", type=float, default=0.5, metavar="METERS")
    parser.add_argument("--expected-nodes", type=int, default=EXPECTED_NODE_COUNT, metavar="COUNT")
    parser.add_argument(
        "--expected-version",
        metavar="VERSION",
        help="require the exact [doomrocket:LOAD] version banner (leading v optional)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        args.max_hips_drift < 0
        or args.min_survival_seconds < 0
        or args.min_samples < 1
        or args.max_frame_ms < 0
        or args.max_deformation_ratio < 1
        or args.max_root_delta < 0
        or args.max_hips_delta < 0
        or args.max_anchor_drift < 0
        or args.expected_nodes < 1
        or (args.expected_version is not None and not args.expected_version.removeprefix("v"))
    ):
        raise SystemExit("thresholds must be non-negative and --min-samples must be at least 1")
    try:
        lines = args.log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"[ragdoll-log] ERROR: {exc}", file=sys.stderr)
        return 2

    errors, summary = analyze(
        lines,
        max_hips_drift=args.max_hips_drift,
        min_survival_seconds=args.min_survival_seconds,
        min_samples=args.min_samples,
        max_frame_ms=args.max_frame_ms,
        max_deformation_ratio=args.max_deformation_ratio,
        max_root_delta=args.max_root_delta,
        max_hips_delta=args.max_hips_delta,
        max_anchor_drift=args.max_anchor_drift,
        expected_nodes=args.expected_nodes,
        expected_version=args.expected_version,
    )
    if args.json:
        summary["errors"] = errors
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif errors:
        print(
            f"[ragdoll-log] FAIL - {len(errors)} violation(s), "
            f"{summary['records']} telemetry record(s)",
            file=sys.stderr,
        )
        for error in errors:
            print(f"[ragdoll-log]   {error}", file=sys.stderr)
    else:
        traces = summary["traces"]
        observed = min(float(trace["observed_seconds"]) for trace in traces)  # type: ignore[index]
        print(
            f"[ragdoll-log] OK - {len(traces)} corpse trace(s), "
            f">={observed:.3f} s, hips drift <= {args.max_hips_drift:g} m"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
