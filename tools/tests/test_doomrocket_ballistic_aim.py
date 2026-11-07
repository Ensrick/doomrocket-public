#!/usr/bin/env python3
"""Static and numerical contracts for Doomrocket ballistic visual aim.

The game cannot be hosted in this test process, so the numerical cases exercise
the documented pure solver contract while the source checks prove that both the
visible aiming path and the projectile spawn call that one implementation.  The
compiled-resource checks prevent a locally correct source tree from being
mistaken for a testable VMB build.
"""

from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = REPO_ROOT / "tools"
BUNDLE_ROOT = REPO_ROOT / "bundleV2"
sys.path.insert(0, str(TOOLS_ROOT))

from splice_bundle_resource import walk as walk_bundle  # noqa: E402
from strip_bundle_resource import murmur64a, read_bundle  # noqa: E402


BALLISTICS_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "utils"
    / "doomrocket_ballistics.lua"
)
LAUNCH_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "behavior"
    / "nodes"
    / "skaven_doomrocket"
    / "bt_doomrocket_launch_action.lua"
)
RELOAD_PATH = LAUNCH_PATH.with_name("bt_doomrocket_reload_action.lua")
AIM_TEMPLATE_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "doomrocket_aim_template.lua"
)
PROJECTILE_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "projectile_rocket.lua"
)
BOOTSTRAP_PATH = REPO_ROOT / "scripts" / "mods" / "doomrocket" / "doomrocket.lua"
RPC_PATH = REPO_ROOT / "scripts" / "mods" / "doomrocket" / "rpc.lua"
NETWORK_CONFIG_PATH = (
    REPO_ROOT / "scripts" / "mods" / "doomrocket" / "utils" / "doomrocket.network_config"
)
GAME_OBJECT_INITIALIZERS_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "utils"
    / "game_object_initializers_extractors.lua"
)

BALLISTICS_RESOURCE = "scripts/mods/doomrocket/utils/doomrocket_ballistics"
LAUNCH_RESOURCE = (
    "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/"
    "bt_doomrocket_launch_action"
)
AIM_TEMPLATE_RESOURCE = "scripts/mods/doomrocket/extensions/doomrocket_aim_template"
PROJECTILE_RESOURCE = "scripts/mods/doomrocket/extensions/projectile_rocket"
BOOTSTRAP_RESOURCE = "scripts/mods/doomrocket/doomrocket"

EXPORTED_NAMESPACES = ("mod.doomrocket_ballistics", "DoomrocketBallistics")
EXPECTED_MIN_LAUNCH_SPEED_SQUARED = 0.01
NETWORK_VELOCITY_STEP = 0.1


def without_lua_comments(source: str) -> str:
    """Strip Lua comments without deleting quoted comment markers."""

    result: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote:
            result.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                result.append(source[index])
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            result.append(char)
            index += 1
            continue
        if source.startswith("--[[", index):
            end = source.find("]]", index + 4)
            if end < 0:
                end = len(source) - 2
            comment = source[index : end + 2]
            result.extend("\n" if value == "\n" else " " for value in comment)
            index = end + 2
            continue
        if source.startswith("--", index):
            end = source.find("\n", index + 2)
            if end < 0:
                end = len(source)
            result.extend(" " for _ in source[index:end])
            index = end
            continue
        result.append(char)
        index += 1
    return "".join(result)


def read_lua(path: Path) -> str:
    return without_lua_comments(path.read_text(encoding="utf-8"))


def numeric_constant(source: str, name: str) -> float:
    match = re.search(
        rf"(?m)^\s*(?:local\s+)?(?:\w+\.)?{re.escape(name)}\s*=\s*"
        r"(-?[0-9]+(?:\.[0-9]+)?)\s*,?\s*$",
        source,
    )
    if not match:
        raise AssertionError(f"missing numeric Lua constant {name}")
    return float(match.group(1))


def function_slice(source: str, method: str) -> str:
    """Extract one launch-action method up to the next method assignment."""

    owner = r"BTDoomrocketLaunchAction"
    match = re.search(
        rf"(?ms)^\s*{owner}\.{re.escape(method)}\s*=\s*function\b.*?"
        rf"(?=^\s*{owner}\.\w+\s*=\s*function\b|\Z)",
        source,
    )
    if not match:
        raise AssertionError(f"missing BTDoomrocketLaunchAction.{method}")
    return match.group(0)


def namespace_aliases(source: str) -> set[str]:
    """Find local aliases which resolve to either supported public namespace."""

    aliases = set(EXPORTED_NAMESPACES)
    changed = True
    while changed:
        changed = False
        for alias, value in re.findall(
            r"(?m)^\s*local\s+(\w+)\s*=\s*([\w.]+)\s*$", source
        ):
            if value in aliases and alias not in aliases:
                aliases.add(alias)
                changed = True
    return aliases


def method_call_pattern(source: str, method: str) -> re.Pattern[str]:
    owners = "|".join(
        re.escape(value) for value in sorted(namespace_aliases(source), key=len, reverse=True)
    )
    return re.compile(rf"(?:{owners})\.{re.escape(method)}\s*\(")


def reference_solve(
    start: tuple[float, float, float],
    target: tuple[float, float, float],
    *,
    gravity: float,
    seconds_per_metre: float,
    min_flight_time: float,
    max_flight_time: float,
) -> tuple[tuple[float, float, float], float]:
    delta = tuple(right - left for left, right in zip(start, target))
    flat_distance = math.hypot(delta[0], delta[1])
    flight_time = min(
        max(flat_distance * seconds_per_metre, min_flight_time), max_flight_time
    )
    velocity = (
        delta[0] / flight_time,
        delta[1] / flight_time,
        delta[2] / flight_time + 0.5 * gravity * flight_time,
    )
    return velocity, flight_time


def trajectory_position(
    start: tuple[float, float, float],
    velocity: tuple[float, float, float],
    flight_time: float,
    gravity: float,
) -> tuple[float, float, float]:
    return (
        start[0] + velocity[0] * flight_time,
        start[1] + velocity[1] * flight_time,
        start[2]
        + velocity[2] * flight_time
        - 0.5 * gravity * flight_time * flight_time,
    )


def trajectory_peak_rise(
    velocity: tuple[float, float, float],
    flight_time: float,
    gravity: float,
) -> float:
    """Highest world-Z rise reached between launch and the solved endpoint."""

    vertical_velocity = velocity[2]
    candidates = [0.0]
    endpoint_rise = (
        vertical_velocity * flight_time
        - 0.5 * gravity * flight_time * flight_time
    )
    candidates.append(endpoint_rise)
    vertex_time = vertical_velocity / gravity
    if 0.0 < vertex_time < flight_time:
        candidates.append(
            vertical_velocity * vertex_time
            - 0.5 * gravity * vertex_time * vertex_time
        )
    return max(candidates)


def launch_pitch_degrees(velocity: tuple[float, float, float]) -> float:
    horizontal_velocity = math.hypot(velocity[0], velocity[1])
    return math.degrees(math.atan2(velocity[2], horizontal_velocity))


def stopped_actor_arm_delay(source: str) -> float:
    """Read the muzzle-clear delay protecting the stopped-speed impact test."""

    match = re.search(
        r"self\.time_pass\s*>\s*([0-9]+(?:\.[0-9]+)?)\s+and\s+speed\s*<",
        source,
    )
    if not match:
        raise AssertionError("missing stopped-projectile impact arm delay")
    return float(match.group(1))


def compiled_resource_versions(
    resource_type: str, resource_name: str
) -> list[tuple[Path, bytes]]:
    key = (murmur64a(resource_type.encode()), murmur64a(resource_name.encode()))
    versions: list[tuple[Path, bytes]] = []
    for bundle in sorted(BUNDLE_ROOT.glob("*.mod_bundle")):
        bundle_format, _, data = read_bundle(bundle)
        _, _, records = walk_bundle(data, bundle_format)
        for record in records:
            if (record["type"], record["name"]) != key:
                continue
            for version in record["versions"]:
                start = version["payload_offset"]
                versions.append((bundle, data[start : start + version["size"]]))
    return versions


class BallisticSolverContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BALLISTICS_PATH.is_file():
            raise AssertionError(f"missing shared ballistic helper: {BALLISTICS_PATH}")
        cls.helper = read_lua(BALLISTICS_PATH)
        cls.gravity = numeric_constant(cls.helper, "GRAVITY")
        cls.seconds_per_metre = numeric_constant(cls.helper, "SECONDS_PER_METRE")
        cls.min_flight_time = numeric_constant(cls.helper, "MIN_FLIGHT_TIME")
        cls.max_flight_time = numeric_constant(cls.helper, "MAX_FLIGHT_TIME")
        cls.projectile = read_lua(PROJECTILE_PATH)
        cls.impact_arm_delay = stopped_actor_arm_delay(cls.projectile)

    def solve(self, start: tuple[float, float, float], target: tuple[float, float, float]):
        return reference_solve(
            start,
            target,
            gravity=self.gravity,
            seconds_per_metre=self.seconds_per_metre,
            min_flight_time=self.min_flight_time,
            max_flight_time=self.max_flight_time,
        )

    def test_reviewed_projectile_tuning_is_unchanged(self) -> None:
        self.assertEqual(self.gravity, 9.82)
        self.assertEqual(self.seconds_per_metre, 0.13)
        self.assertEqual(self.min_flight_time, 0.4)
        self.assertEqual(self.max_flight_time, 3.4)
        self.assertEqual(
            numeric_constant(self.helper, "MIN_LAUNCH_SPEED_SQUARED"),
            EXPECTED_MIN_LAUNCH_SPEED_SQUARED,
        )

    def test_minimum_flight_outlasts_stopped_projectile_arm_delay(self) -> None:
        self.assertEqual(self.impact_arm_delay, 0.35)
        self.assertGreater(
            self.min_flight_time,
            self.impact_arm_delay,
            "a close hit must not stop before the impact detector is armed",
        )

    def test_solver_source_is_the_clamped_closed_form_ballistic_solution(self) -> None:
        aliases = namespace_aliases(self.helper)
        owners = "|".join(re.escape(value) for value in aliases)
        self.assertRegex(
            self.helper,
            rf"(?:function\s+(?:{owners})\.solve_launch_velocity\s*\(|"
            rf"(?:{owners})\.solve_launch_velocity\s*=\s*function\s*\()",
        )
        self.assertRegex(
            self.helper,
            r"Vector3\.length\s*\(\s*Vector3\.flat\s*\(",
            "flight time must use horizontal range, not full 3-D distance",
        )
        self.assertRegex(
            self.helper,
            r"(?s)math\.clamp\s*\(.{0,240}?SECONDS_PER_METRE.{0,160}?"
            r"MIN_FLIGHT_TIME.{0,160}?MAX_FLIGHT_TIME.{0,80}?\)",
        )
        self.assertRegex(
            self.helper,
            r"\.z\s*/\s*\w+\s*\+\s*0\.5\s*\*\s*[^\n]*GRAVITY\s*\*",
            "vertical launch velocity must compensate downward gravity",
        )
        self.assertGreaterEqual(self.helper.count("Vector3.is_valid("), 3)
        self.assertRegex(self.helper, r"not\s+Vector3\.is_valid\s*\(\s*start_position")
        self.assertRegex(self.helper, r"not\s+Vector3\.is_valid\s*\(\s*target_position")
        self.assertRegex(self.helper, r"not\s+Vector3\.is_valid\s*\(\s*\w*velocity")
        velocity_assignment = self.helper.find("local launch_velocity")
        zero_length_guard = self.helper.find("Vector3.length_squared", velocity_assignment)
        result_return = self.helper.find("return launch_velocity", velocity_assignment)
        self.assertGreaterEqual(velocity_assignment, 0)
        self.assertGreater(zero_length_guard, velocity_assignment)
        self.assertGreater(result_return, zero_length_guard)
        self.assertRegex(
            self.helper[velocity_assignment:result_return],
            r"Vector3\.length_squared\s*\(\s*launch_velocity\s*\)\s*<=\s*"
            r"DoomrocketBallistics\.MIN_LAUNCH_SPEED_SQUARED",
            "the primitive solver must reject a zero vector before consumers normalize it",
        )

    def test_short_medium_long_and_height_cases_land_on_target(self) -> None:
        cases = {
            "short_min_clamp": ((2.0, 0.0, 1.5), (4.0, 0.0, 1.5), 0.4),
            "short_range_scaled": ((2.0, 0.0, 1.5), (7.0, 0.0, 1.5), 0.65),
            "medium_unclamped": ((1.0, -2.0, 0.5), (19.0, -2.0, 0.5), 2.34),
            "long_max_clamp": ((0.0, 0.0, 2.0), (40.0, 0.0, 2.0), 3.4),
            "elevated": ((0.0, 0.0, 1.0), (18.0, 0.0, 7.0), 2.34),
            "depressed": ((0.0, 0.0, 7.0), (18.0, 0.0, 1.0), 2.34),
        }
        for name, (start, target, expected_time) in cases.items():
            with self.subTest(case=name):
                velocity, flight_time = self.solve(start, target)
                self.assertAlmostEqual(flight_time, expected_time, places=12)
                self.assertGreaterEqual(flight_time, self.min_flight_time)
                self.assertLessEqual(flight_time, self.max_flight_time)
                self.assertTrue(all(math.isfinite(value) for value in velocity))
                landed = trajectory_position(start, velocity, flight_time, self.gravity)
                for actual, expected in zip(landed, target):
                    self.assertAlmostEqual(actual, expected, places=10)
                horizontal_delta = math.hypot(
                    target[0] - start[0], target[1] - start[1]
                )
                horizontal_velocity = math.hypot(velocity[0], velocity[1])
                line_of_sight_pitch = math.atan2(
                    target[2] - start[2], horizontal_delta
                )
                launch_tangent_pitch = math.atan2(velocity[2], horizontal_velocity)
                self.assertGreater(
                    launch_tangent_pitch,
                    line_of_sight_pitch,
                    "the visual tangent must point above the direct target line",
                )

    def test_close_range_pitch_and_peak_are_locked_to_the_smoothed_arc(self) -> None:
        cases = {
            # Physical point-blank uses 0.5 m: exact zero has no horizontal bearing.
            "point_blank": (0.5, 0.4, 57.525032537548, 0.1964),
            "close": (2.0, 0.4, 21.444899972586, 0.1964),
            "short": (5.0, 0.65, 22.533317681021, 0.51861875),
        }
        for name, (distance, expected_time, expected_pitch, expected_peak) in cases.items():
            with self.subTest(case=name):
                velocity, flight_time = self.solve((0.0, 0.0, 0.0), (distance, 0.0, 0.0))
                self.assertAlmostEqual(flight_time, expected_time, places=12)
                self.assertAlmostEqual(
                    launch_pitch_degrees(velocity), expected_pitch, places=10
                )
                self.assertAlmostEqual(
                    trajectory_peak_rise(velocity, flight_time, self.gravity),
                    expected_peak,
                    places=10,
                )

    def test_flight_time_and_level_peak_do_not_decrease_with_distance(self) -> None:
        distances = (
            0.0,
            0.25,
            0.5,
            1.0,
            2.0,
            3.0,
            self.min_flight_time / self.seconds_per_metre,
            4.0,
            5.0,
            8.0,
            13.076923076923077,
            15.0,
            18.0,
            26.153846153846153,
            30.0,
            40.0,
        )
        prior_time = -math.inf
        prior_peak = -math.inf
        for distance in distances:
            with self.subTest(distance=distance):
                velocity, flight_time = self.solve(
                    (0.0, 0.0, 0.0), (distance, 0.0, 0.0)
                )
                peak = trajectory_peak_rise(velocity, flight_time, self.gravity)
                self.assertGreaterEqual(flight_time + 1e-12, prior_time)
                self.assertGreaterEqual(peak + 1e-12, prior_peak)
                prior_time = flight_time
                prior_peak = peak

    def test_lower_clamp_transition_is_continuous(self) -> None:
        boundary = self.min_flight_time / self.seconds_per_metre
        epsilon = 1e-7
        below = self.solve((0.0, 0.0, 0.0), (boundary - epsilon, 0.0, 0.0))[1]
        at = self.solve((0.0, 0.0, 0.0), (boundary, 0.0, 0.0))[1]
        above = self.solve((0.0, 0.0, 0.0), (boundary + epsilon, 0.0, 0.0))[1]
        self.assertAlmostEqual(below, self.min_flight_time, places=12)
        self.assertAlmostEqual(at, self.min_flight_time, places=12)
        self.assertAlmostEqual(
            above, self.min_flight_time + epsilon * self.seconds_per_metre, places=12
        )
        self.assertLess(above - below, 2 * epsilon * self.seconds_per_metre)

    def test_short_elevation_cases_land_without_an_artificial_ridge(self) -> None:
        cases = {
            "elevated": (3.0, 62.151707320088, 3.0),
            "depressed": (-3.0, -47.912308759098, 0.0),
        }
        start = (0.0, 0.0, 0.0)
        for name, (height, expected_pitch, expected_peak) in cases.items():
            with self.subTest(case=name):
                target = (2.0, 0.0, height)
                velocity, flight_time = self.solve(start, target)
                self.assertAlmostEqual(flight_time, 0.4, places=12)
                landed = trajectory_position(start, velocity, flight_time, self.gravity)
                for actual, expected in zip(landed, target):
                    self.assertAlmostEqual(actual, expected, places=10)
                self.assertAlmostEqual(
                    launch_pitch_degrees(velocity), expected_pitch, places=10
                )
                self.assertAlmostEqual(
                    trajectory_peak_rise(velocity, flight_time, self.gravity),
                    expected_peak,
                    places=10,
                )
                line_of_sight_pitch = math.degrees(math.atan2(height, 2.0))
                self.assertGreater(launch_pitch_degrees(velocity), line_of_sight_pitch)

    def test_medium_and_long_solutions_match_the_previous_reviewed_curve(self) -> None:
        cases = (
            ((0.0, 0.0, 0.0), (15.0, 0.0, 0.0)),
            ((1.0, -2.0, 0.5), (19.0, -2.0, 0.5)),
            ((0.0, 0.0, 1.0), (18.0, 0.0, 7.0)),
            ((0.0, 0.0, 7.0), (18.0, 0.0, 1.0)),
            ((0.0, 0.0, 0.0), (30.0, 0.0, 0.0)),
            ((0.0, 0.0, 2.0), (40.0, 0.0, 2.0)),
        )
        for start, target in cases:
            with self.subTest(start=start, target=target):
                actual_velocity, actual_time = self.solve(start, target)
                legacy_velocity, legacy_time = reference_solve(
                    start,
                    target,
                    gravity=self.gravity,
                    seconds_per_metre=self.seconds_per_metre,
                    min_flight_time=1.7,
                    max_flight_time=self.max_flight_time,
                )
                self.assertEqual(actual_time, legacy_time)
                self.assertEqual(actual_velocity, legacy_velocity)

    def test_degenerate_range_stays_finite_and_respects_minimum_time(self) -> None:
        start = (3.0, -4.0, 2.0)
        velocity, flight_time = self.solve(start, start)
        self.assertEqual(flight_time, self.min_flight_time)
        self.assertTrue(all(math.isfinite(value) for value in velocity))
        self.assertGreater(velocity[2], 0.0)
        landed = trajectory_position(start, velocity, flight_time, self.gravity)
        for actual, expected in zip(landed, start):
            self.assertAlmostEqual(actual, expected, places=10)

    def test_zero_and_near_zero_launch_vectors_are_rejected_before_normalization(self) -> None:
        flight_time = self.min_flight_time
        cancellation_drop = -0.5 * self.gravity * flight_time * flight_time
        near_zero_vertical_speed = math.sqrt(EXPECTED_MIN_LAUNCH_SPEED_SQUARED) * 0.5
        near_zero_drop = (
            near_zero_vertical_speed - 0.5 * self.gravity * flight_time
        ) * flight_time

        for name, target_height in (
            ("exact_zero", cancellation_drop),
            ("near_zero", near_zero_drop),
        ):
            with self.subTest(case=name):
                velocity, actual_time = self.solve(
                    (0.0, 0.0, 0.0), (0.0, 0.0, target_height)
                )
                self.assertEqual(actual_time, flight_time)
                length_squared = sum(component * component for component in velocity)
                self.assertLessEqual(
                    length_squared,
                    EXPECTED_MIN_LAUNCH_SPEED_SQUARED,
                    "fixture must exercise the production zero-vector rejection branch",
                )

        guard = re.search(
            r"if\s+(?:not\s+Vector3\.is_valid\s*\(\s*launch_velocity\s*\)\s+or\s+)?"
            r"Vector3\.length_squared\s*\(\s*launch_velocity\s*\)\s*<=\s*"
            r"DoomrocketBallistics\.MIN_LAUNCH_SPEED_SQUARED\s+then"
            r"[\s\S]{0,160}?return\s+nil\s*,\s*nil",
            self.helper,
        )
        self.assertIsNotNone(
            guard,
            "zero and near-zero launch vectors must return nil before visual normalization "
            "or projectile network encoding",
        )

    def test_launch_speed_guard_cannot_pass_a_vector_that_quantizes_to_zero(self) -> None:
        # AiAnimUtils multiplies each component by 10, rounds it, and restores it
        # with a 0.1 multiplier.  For a three-component vector, |v| > 0.1
        # guarantees max(|component|) > 0.1/sqrt(3) > half a quantizer step.
        guaranteed_component = math.sqrt(
            EXPECTED_MIN_LAUNCH_SPEED_SQUARED / 3.0
        )
        self.assertGreater(guaranteed_component, NETWORK_VELOCITY_STEP * 0.5)

        just_above_guard = math.sqrt(
            (EXPECTED_MIN_LAUNCH_SPEED_SQUARED + 1e-12) / 3.0
        )
        worst_case_direction = (
            just_above_guard,
            -just_above_guard,
            just_above_guard,
        )
        encoded = tuple(
            round(component / NETWORK_VELOCITY_STEP)
            for component in worst_case_direction
        )
        self.assertNotEqual(encoded, (0, 0, 0))


class BallisticAimLaunchParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.helper = read_lua(BALLISTICS_PATH) if BALLISTICS_PATH.is_file() else ""
        cls.launch = read_lua(LAUNCH_PATH)
        cls.reload = read_lua(RELOAD_PATH)
        cls.aim_template = read_lua(AIM_TEMPLATE_PATH)
        cls.bootstrap = read_lua(BOOTSTRAP_PATH)
        cls.rpc = read_lua(RPC_PATH)
        cls.network_config = NETWORK_CONFIG_PATH.read_text(encoding="utf-8")
        cls.game_object_initializers = read_lua(GAME_OBJECT_INITIALIZERS_PATH)
        cls.aim_method = function_slice(cls.launch, "_aim_at_target")
        cls.shoot_method = function_slice(cls.launch, "_shoot")

    def test_helper_loads_before_every_consumer(self) -> None:
        helper_load = self.bootstrap.find(f'mod:dofile("{BALLISTICS_RESOURCE}")')
        launch_load = self.bootstrap.find(f'mod:dofile("{LAUNCH_RESOURCE}")')
        aim_load = self.bootstrap.find(f'mod:dofile("{AIM_TEMPLATE_RESOURCE}")')
        self.assertGreaterEqual(helper_load, 0, "bootstrap does not load ballistic helper")
        self.assertGreater(launch_load, helper_load)
        self.assertGreater(aim_load, helper_load)

    def test_deleted_target_is_rejected_before_launch_initialization(self) -> None:
        enter = function_slice(self.launch, "enter")
        run = function_slice(self.launch, "run")
        leave = function_slice(self.launch, "leave")
        notify_start = function_slice(self.launch, "_notify_attacking")
        notify_end = function_slice(self.launch, "_notify_no_longer_attacking")

        guard = re.search(
            r"if\s+not\s+target_unit\s+or\s+not\s+Unit\.alive\s*\(\s*target_unit\s*\)\s+then",
            enter,
        )
        self.assertIsNotNone(guard, "enter must guard a nil or deleted career target")
        self.assertNotIn(
            "Unit.local_position(target_unit",
            enter[: guard.start()],
            "the issue #9 crash dereferenced the deleted target before this guard",
        )
        rejected = enter[guard.start() :]
        self.assertRegex(rejected, r"data\.target_unit\s*=\s*nil")
        self.assertRegex(rejected, r"data\.invalid_target\s*=\s*true")
        self.assertIn("phase=launch_rejected", rejected)
        self.assertRegex(
            run,
            r"if\s+not\s+data\s+or\s+data\.invalid_target\s+then\s*return\s+[\"']failed[\"']",
        )
        self.assertRegex(leave, r"if\s+data\.attack_notified\s+then")
        self.assertRegex(
            notify_start,
            r"if\s+not\s+target_unit\s+or\s+not\s+Unit\.alive\s*\(\s*target_unit\s*\)\s+then",
        )
        self.assertNotRegex(
            notify_end,
            r"not\s+Unit\.alive\s*\(\s*(?:target_unit|notified_target)\s*\)\s+then\s*return",
            "career replacement destroys the victim before leave; attack-ended must still clear the attacker sentinel",
        )
        end_call = notify_end.find(":ranged_attack_ended(")
        alive_check = notify_end.find("Unit.alive(notified_target)")
        self.assertGreaterEqual(end_call, 0)
        self.assertGreater(
            alive_check,
            end_call,
            "victim liveness may guard status cleanup, never the paired group-system end",
        )
        self.assertIn("active_bot_attack_targets[self_unit] = nil", notify_end)
        self.assertIn("data.attack_notified_target", leave)

    def test_point_blank_target_cannot_fall_through_from_shove_to_launch(self) -> None:
        enter = function_slice(self.launch, "enter")
        run = function_slice(self.launch, "run")

        self.assertIn("local MIN_LAUNCH_DISTANCE = 1.8", self.launch)
        self.assertIn("target_is_inside_launch_safety", enter)
        self.assertIn("reason=target_too_close", enter)
        self.assertIn("target_is_inside_launch_safety", run)
        self.assertIn("phase=launch_aborted", run)

    def test_reload_cannot_reuse_a_deleted_career_target(self) -> None:
        self.assertRegex(
            self.reload,
            r"if\s+target_unit\s+and\s+Unit\.alive\s*\(\s*target_unit\s*\)\s+then",
        )
        self.assertRegex(
            self.reload,
            r"elseif\s+old_target_visible\s+and\s+data\.target_unit\s+and\s+"
            r"Unit\.alive\s*\(\s*data\.target_unit\s*\)\s+then",
        )
        self.assertGreaterEqual(
            len(re.findall(r"data\.target_unit\s*=\s*nil", self.reload)),
            2,
            "both reload acquisition paths must discard a destroyed player unit",
        )

    def test_visual_aim_and_shoot_call_exactly_one_shared_primitive_solver(self) -> None:
        solve_call = method_call_pattern(self.launch, "solve_launch_velocity")
        for lane, body in (("visual aim", self.aim_method), ("shoot", self.shoot_method)):
            with self.subTest(lane=lane):
                calls = solve_call.findall(body)
                self.assertEqual(
                    len(calls), 1, f"{lane} must call the shared solver exactly once"
                )

        outside_helper = "\n".join((self.launch, self.aim_template))
        for constant in ("GRAVITY", "SECONDS_PER_METRE", "MIN_FLIGHT_TIME", "MAX_FLIGHT_TIME"):
            self.assertNotRegex(
                outside_helper,
                rf"(?m)^\s*(?:local\s+)?(?:\w+\.)?{constant}\s*=",
                f"{constant} must have one source of truth in the ballistic helper",
            )
        self.assertNotRegex(
            outside_helper,
            r"\.z\s*/\s*\w+\s*\+\s*0\.5\s*\*[^\n]*(?:9\.82|GRAVITY)",
            "consumer duplicated the primitive ballistic equation",
        )

    def test_both_lanes_use_the_exact_same_spawn_and_target_helpers(self) -> None:
        fire_method = function_slice(self.launch, "_fire_from_position_direction")
        target_method = function_slice(self.launch, "_projectile_target_position")
        self.assertIn('"p_fx"', fire_method)
        self.assertRegex(fire_method, r"Unit\.world_position\s*\([^\n]+fire_node")
        self.assertRegex(
            fire_method,
            r"position\s*-\s*Vector3\.normalize\s*\([^\n]+\)\s*\*\s*"
            r"(?:\w+\.)?MUZZLE_BACKSTEP",
        )
        self.assertEqual(numeric_constant(self.helper, "MUZZLE_BACKSTEP"), 0.25)
        self.assertEqual(numeric_constant(self.launch, "PROJECTILE_TARGET_HEIGHT"), 0.25)
        self.assertRegex(
            target_method,
            r"clear_target_position\s*\(\s*fire_position\s*,\s*"
            r"Unit\.local_position\s*\(\s*data\.target_unit\s*,\s*0\s*\)\s*,\s*"
            r"PROJECTILE_TARGET_HEIGHT\s*\)",
        )

        for lane, body in (("visual aim", self.aim_method), ("shoot", self.shoot_method)):
            with self.subTest(lane=lane):
                fire_assignment = re.search(
                    r"local\s+(\w+)(?:\s*,\s*\w+)?\s*=\s*"
                    r"self:_fire_from_position_direction\s*\(\s*blackboard\s*,\s*data\s*\)",
                    body,
                )
                target_assignment = re.search(
                    r"local\s+(\w+)\s*=\s*"
                    r"self:_projectile_target_position\s*\(\s*data\s*,\s*(\w+)\s*\)",
                    body,
                )
                self.assertIsNotNone(fire_assignment)
                self.assertIsNotNone(target_assignment)
                fire_variable = fire_assignment.group(1)
                target_variable = target_assignment.group(1)
                self.assertEqual(target_assignment.group(2), fire_variable)
                self.assertRegex(
                    body,
                    rf"solve_launch_velocity\s*\(\s*{re.escape(fire_variable)}\s*,\s*"
                    rf"{re.escape(target_variable)}\s*\)",
                    f"{lane} must solve from the shared spawn point to the shared endpoint",
                )

        self.assertIn('local unit_name = "units/rocket/SM_Rocket"', self.shoot_method)
        self.assertIn(
            'local unit_template_name = "explosive_pickup_projectile_unit"',
            self.shoot_method,
        )
        self.assertIn('local collision_filter = "filter_enemy_player_afro_ray_projectile"', self.shoot_method)

    def test_invalid_solver_results_cannot_reach_engine_math_or_network_scaling(self) -> None:
        aim_solve = self.aim_method.find("solve_launch_velocity")
        aim_network_scale = self.aim_method.find("velocity_network_scale", aim_solve)
        self.assertGreater(aim_network_scale, aim_solve)
        self.assertRegex(
            self.aim_method[aim_solve:aim_network_scale],
            r"if\s+(?:not\s+\w*(?:launch_)?velocity|\w*(?:launch_)?velocity\s*==\s*nil)",
            "visual aim must reject a non-finite/nil result before engine/network vector math",
        )

        shoot_solve = self.shoot_method.find("solve_launch_velocity")
        network_scale = self.shoot_method.find("velocity_network_scale", shoot_solve)
        self.assertGreater(network_scale, shoot_solve)
        self.assertRegex(
            self.shoot_method[shoot_solve:network_scale],
            r"if\s+(?:not\s+\w*(?:impulse|launch|velocity)\w*|"
            r"\w*(?:impulse|launch|velocity)\w*\s*==\s*nil)[\s\S]{0,120}?return",
            "shoot must abort a non-finite/nil solution before network encoding",
        )

    def test_visual_tangent_uses_the_same_quantized_velocity_as_projectile_physics(self) -> None:
        encode = re.search(
            r"local\s+(\w+)\s*=\s*AiAnimUtils\.velocity_network_scale\s*\(\s*"
            r"(\w+)\s*,\s*true\s*\)",
            self.aim_method,
        )
        self.assertIsNotNone(encode, "visual path does not encode its solved velocity")
        encoded_variable = encode.group(1)
        decode = re.search(
            rf"local\s+(\w+)\s*=\s*AiAnimUtils\.velocity_network_scale\s*\(\s*"
            rf"{re.escape(encoded_variable)}\s*\)",
            self.aim_method,
        )
        self.assertIsNotNone(decode, "visual path does not decode the quantized velocity")
        replicated_variable = decode.group(1)
        self.assertRegex(
            self.aim_method,
            rf"Vector3\.normalize\s*\(\s*{re.escape(replicated_variable)}\s*\)",
            "pose must use the velocity actually decoded by projectile physics",
        )

    def test_ballistic_pose_direction_is_separate_from_target_selection_direction(self) -> None:
        self.assertIn("data.ballistic_aim_direction_box", self.aim_method)
        self.assertIn("ballistic_aim_direction_box", self.aim_template)
        self.assertIn("shoot_direction_box", self.aim_template)
        ballistic = self.aim_template.find("ballistic_aim_direction_box")
        fallback = self.aim_template.find("shoot_direction_box", ballistic)
        self.assertGreater(
            fallback,
            ballistic,
            "visual aim must prefer the ballistic tangent and retain line-of-sight fallback",
        )
        update_target = function_slice(self.launch, "_update_target")
        self.assertIn(
            "shoot_direction_box:unbox()",
            update_target,
            "steep lob tangent must not replace the 45-degree target-selection direction",
        )
        self.assertNotIn("ballistic_aim_direction_box", update_target)

    def test_ballistic_pose_state_is_cleared_on_realign_and_leave(self) -> None:
        for lifecycle, method in (
            ("realign", "_start_align_towards_target"),
            ("leave", "leave"),
        ):
            with self.subTest(lifecycle=lifecycle):
                body = function_slice(self.launch, method)
                self.assertRegex(
                    body,
                    r"data\.ballistic_aim_direction_box\s*=\s*nil",
                    f"{lifecycle} must not retain a previous target's ballistic tangent",
                )

    def test_only_a_normal_completed_shot_creates_a_bounded_pose_hold(self) -> None:
        leave = function_slice(self.launch, "leave")
        hold_time = numeric_constant(self.launch, "BALLISTIC_AIM_HOLD_TIME")
        self.assertEqual(hold_time, 0.2)
        self.assertGreater(hold_time, 0.0)
        self.assertLessEqual(hold_time, 0.5)

        success_branch = re.search(r"(?ms)^\s*if\s+([^\n]+)\s+then\s*(.*?)^\s*else\s*(.*?)^\s*end\s*$", leave)
        self.assertIsNotNone(success_branch, "leave has no explicit success/failure hold split")
        condition, completed, rejected = success_branch.groups()
        self.assertRegex(condition, r"\bnot\s+destroy\b")
        self.assertRegex(condition, r"reason\s*==\s*[\"']done[\"']")
        self.assertRegex(condition, r"data\.shots_fired\s*>\s*0")
        self.assertIn("data.ballistic_aim_direction_box", condition)
        self.assertRegex(
            completed,
            r"blackboard\.doomrocket_ballistic_aim_hold_direction_box\s*=\s*"
            r"Vector3Box\s*\(\s*data\.ballistic_aim_direction_box:unbox\s*\(\s*\)\s*\)",
            "completed shot must copy its tangent to persistent blackboard state",
        )
        self.assertRegex(
            completed,
            r"blackboard\.doomrocket_ballistic_aim_hold_until\s*=\s*"
            r"t\s*\+\s*BALLISTIC_AIM_HOLD_TIME",
        )
        for field in (
            "doomrocket_ballistic_aim_hold_direction_box",
            "doomrocket_ballistic_aim_hold_until",
        ):
            self.assertRegex(
                rejected,
                rf"blackboard\.{field}\s*=\s*nil",
                f"aborted, failed, and destroyed actions must clear {field}",
            )

    def test_realign_cancels_any_previous_completed_shot_hold(self) -> None:
        start_align = function_slice(self.launch, "_start_align_towards_target")
        for field in (
            "doomrocket_ballistic_aim_hold_direction_box",
            "doomrocket_ballistic_aim_hold_until",
        ):
            self.assertRegex(start_align, rf"blackboard\.{field}\s*=\s*nil")

    def test_owner_consumes_pose_hold_only_until_its_expiry(self) -> None:
        husk_marker = re.search(r"(?m)^\s*husk\s*=\s*\{", self.aim_template)
        self.assertIsNotNone(husk_marker)
        owner = self.aim_template[: husk_marker.start()]
        husk = self.aim_template[husk_marker.start() :]

        active = owner.find("ballistic_aim_direction_box")
        held = owner.find("ballistic_aim_hold_direction_box")
        fallback = owner.find("shoot_direction_box", held)
        self.assertGreaterEqual(active, 0)
        self.assertGreater(held, active, "active tangent must take priority over held tangent")
        self.assertGreater(fallback, held, "direct LOS must remain the final fallback")
        self.assertRegex(
            owner,
            r"if\s+t\s*<=\s*\(\s*data\.blackboard\.doomrocket_ballistic_aim_hold_until\s*"
            r"or\s*-math\.huge\s*\)\s+then",
        )
        self.assertRegex(
            owner,
            r"ballistic_direction_box\s*=\s*"
            r"data\.blackboard\.doomrocket_ballistic_aim_hold_direction_box",
        )
        expiry = owner[owner.find("doomrocket_ballistic_aim_hold_until") :]
        self.assertRegex(
            expiry,
            r"else[\s\S]{0,240}?doomrocket_ballistic_aim_hold_direction_box\s*=\s*nil"
            r"[\s\S]{0,160}?doomrocket_ballistic_aim_hold_until\s*=\s*nil",
        )
        self.assertNotIn(
            "doomrocket_ballistic_aim_hold_",
            husk,
            "husk must consume only the already replicated aim_target position",
        )

    def test_owner_and_husk_reuse_existing_aim_target_replication(self) -> None:
        husk_marker = re.search(r"(?m)^\s*husk\s*=\s*\{", self.aim_template)
        self.assertIsNotNone(husk_marker, "could not split owner and husk aim lanes")
        owner = self.aim_template[: husk_marker.start()]
        husk = self.aim_template[husk_marker.start() :]
        self.assertRegex(
            owner,
            r"GameSession\.set_game_object_field\s*\([^\n]+\"aim_target\"\s*,\s*aim_target\s*\)",
        )
        self.assertRegex(
            husk,
            r"GameSession\.game_object_field\s*\([^\n]+\"aim_target\"\s*\)",
        )
        self.assertRegex(
            self.network_config,
            r'\{\s*name\s*=\s*"aim_target"\s*,\s*type\s*=\s*"position"\s*\}',
        )
        self.assertRegex(
            self.game_object_initializers,
            r"(?m)^\s*aim_target\s*=\s*Vector3\.zero\s*\(\s*\)\s*,?\s*$",
        )

        network_surfaces = "\n".join(
            (self.rpc, self.network_config, self.game_object_initializers)
        )
        for transient_field in (
            "ballistic_aim_direction_box",
            "doomrocket_ballistic_aim_hold_direction_box",
            "doomrocket_ballistic_aim_hold_until",
        ):
            self.assertNotIn(
                transient_field,
                network_surfaces,
                "ballistic pose state belongs on the blackboard, not in network schema",
            )
        self.assertNotRegex(
            self.rpc,
            r"(?i)(?:network_register|network_send)\s*\([^\n]*ballistic",
            "the existing aim_target game-object field makes a new ballistic RPC unnecessary",
        )

    def test_resolved_velocity_drives_pose_and_network_projectile(self) -> None:
        self.assertRegex(
            self.aim_method,
            r"ballistic_aim_direction_box(?::store\s*\(|\s*=\s*Vector3Box\s*\()",
        )
        self.assertRegex(
            self.shoot_method,
            r"velocity_network_scale\s*\(\s*(?:impulse_vector|launch_velocity)",
        )
        self.assertRegex(
            self.shoot_method,
            r"spawn_network_unit\s*\([^\n]+(?:from_position|fire_position)",
        )


@unittest.skipUnless(BUNDLE_ROOT.is_dir(), "compiled bundleV2 is not present")
class BallisticCompiledBundleTests(unittest.TestCase):
    def require_one(self, resource_name: str) -> tuple[Path, bytes]:
        versions = compiled_resource_versions("lua", resource_name)
        self.assertEqual(
            len(versions),
            1,
            f"compiled Lua {resource_name} must occur exactly once; found {len(versions)}",
        )
        return versions[0]

    def test_compiled_bundle_contains_shared_solver_and_both_consumers(self) -> None:
        expectations = {
            BALLISTICS_RESOURCE: (
                b"solve_launch_velocity",
                b"clear_target_position",
                b"lower_hull_extent",
                b"ROCKET_FORWARD_EXTENT",
                b"ROCKET_REAR_EXTENT",
                b"ROCKET_RADIUS",
                b"SECONDS_PER_METRE",
                b"MIN_FLIGHT_TIME",
                b"MAX_FLIGHT_TIME",
                b"MIN_LAUNCH_SPEED_SQUARED",
                b"length_squared",
            ),
            LAUNCH_RESOURCE: (
                b"solve_launch_velocity",
                b"clear_target_position",
                b"hull_clearance_m",
                b"spawn_clearance_m",
                b"ballistic_aim_direction_box",
                b"BALLISTIC_AIM_HOLD_TIME",
                b"doomrocket_ballistic_aim_hold_direction_box",
                b"doomrocket_ballistic_aim_hold_until",
            ),
            AIM_TEMPLATE_RESOURCE: (
                b"ballistic_aim_direction_box",
                b"doomrocket_ballistic_aim_hold_direction_box",
                b"doomrocket_ballistic_aim_hold_until",
                b"shoot_direction_box",
            ),
            PROJECTILE_RESOURCE: (b"time_pass", b"speed", b"rocket_explode"),
            BOOTSTRAP_RESOURCE: (b"doomrocket_ballistics",),
        }
        for resource_name, needles in expectations.items():
            with self.subTest(resource=resource_name):
                _bundle, payload = self.require_one(resource_name)
                self.assertGreater(len(payload), 64)
                for needle in needles:
                    self.assertTrue(
                        needle in payload,
                        f"compiled {resource_name} is missing {needle!r}",
                    )

    def test_compiled_lua_is_not_older_than_its_source(self) -> None:
        source_resources = {
            BALLISTICS_PATH: BALLISTICS_RESOURCE,
            LAUNCH_PATH: LAUNCH_RESOURCE,
            AIM_TEMPLATE_PATH: AIM_TEMPLATE_RESOURCE,
            PROJECTILE_PATH: PROJECTILE_RESOURCE,
            BOOTSTRAP_PATH: BOOTSTRAP_RESOURCE,
        }
        for source_path, resource_name in source_resources.items():
            with self.subTest(resource=resource_name):
                bundle, _payload = self.require_one(resource_name)
                self.assertGreaterEqual(
                    bundle.stat().st_mtime_ns,
                    source_path.stat().st_mtime_ns,
                    f"{bundle.name} predates {source_path.name}; rebuild before testing",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
