#!/usr/bin/env python3
"""Offline contracts for Bombardier survivability and close-range shove.

These tests deliberately inspect the Lua wiring rather than reproducing VT2's
damage or behavior-tree engine in Python. They protect the engine-facing
contracts that previously made plausible-looking changes no-op in game: donor
parity must be explicit, the generated root selector must still match its Lua
tree, and the shove cannot depend on an animation callback the Ratling carrier
does not own.
"""

from __future__ import annotations

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

BREED_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "breeds"
    / "skaven_doomrocket.lua"
)
TREE_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "behavior"
    / "nodes"
    / "skaven_doomrocket"
    / "trees"
    / "skaven"
    / "skaven_doomrocket_behavior.lua"
)
GENERATED_SELECTOR_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "behavior"
    / "nodes"
    / "skaven_doomrocket"
    / "generated"
    / "bt_selector_skaven_doomrocket.lua"
)
SHOVE_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "behavior"
    / "nodes"
    / "skaven_doomrocket"
    / "bt_doomrocket_shove_action.lua"
)
REPOSITION_PATH = SHOVE_PATH.with_name("bt_doomrocket_reposition_action.lua")
BOOTSTRAP_PATH = (
    REPO_ROOT / "scripts" / "mods" / "doomrocket" / "doomrocket.lua"
)
ITEM_CONFIG_PATH = REPO_ROOT / "itemV2.cfg"
STATE_MACHINE_PATH = (
    REPO_ROOT
    / "units"
    / "warlock_bombardier"
    / "warlock_bombardier_3p.state_machine"
)


def without_lua_comments(source: str) -> str:
    """Strip Lua comments while preserving quoted strings and line positions."""

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


def aliases_for(source: str, expression: str) -> set[str]:
    aliases = {expression}
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


def field_assignments(
    source: str, owners: set[str], field: str
) -> list[tuple[str, re.Match[str]]]:
    owner_pattern = "|".join(
        re.escape(owner) for owner in sorted(owners, key=len, reverse=True)
    )
    pattern = re.compile(
        rf"(?m)^\s*(?:{owner_pattern})\.{re.escape(field)}\s*=\s*([^\r\n]+?)\s*$"
    )
    return [(match.group(1).strip(), match) for match in pattern.finditer(source)]


def numeric_field(source: str, field: str) -> float:
    match = re.search(
        rf"(?m)^\s*(?:\w+\.)*{re.escape(field)}\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$",
        source,
    )
    if not match:
        raise AssertionError(f"missing numeric Lua field {field!r}")
    return float(match.group(1))


def compiled_resource_payloads(resource_type: str, resource_name: str) -> list[bytes]:
    """Return every compiled version of one named resource across mod bundles."""

    key = (murmur64a(resource_type.encode()), murmur64a(resource_name.encode()))
    payloads: list[bytes] = []
    for bundle in sorted(BUNDLE_ROOT.glob("*.mod_bundle")):
        bundle_format, _, data = read_bundle(bundle)
        _, _, records = walk_bundle(data, bundle_format)
        for record in records:
            if (record["type"], record["name"]) != key:
                continue
            for version in record["versions"]:
                start = version["payload_offset"]
                payloads.append(data[start : start + version["size"]])
    return payloads


class RatlingBreakpointContractTests(unittest.TestCase):
    """#33: the Engineer keeps every Ratling Gunner breakpoint (glass cannon)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_lua(BREED_PATH)
        cls.doomrocket_aliases = aliases_for(cls.source, "Breeds.skaven_doomrocket")

    def test_breed_is_a_deep_clone_of_the_ratling_gunner(self) -> None:
        clone = re.search(
            r"Breeds\.skaven_doomrocket\s*=\s*table\.clone\(Breeds\.skaven_ratling_gunner\)",
            self.source,
        )
        self.assertIsNotNone(clone, "native Ratling carrier and stats must remain")

    def test_no_durability_field_overrides_the_ratling(self) -> None:
        for field in (
            "max_health",
            "armor_category",
            "primary_armor_category",
            "hitzone_armor_categories",
            "hitzone_primary_armor_categories",
            "hitzone_multiplier_types",
            "hit_zones",
            "diff_stagger_resist",
            "stagger_resistance",
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    field_assignments(self.source, self.doomrocket_aliases, field),
                    [],
                    f"{field} would move the Engineer off Ratling Gunner breakpoints",
                )

        self.assertNotRegex(
            self.source,
            r"Breeds\.skaven_storm_vermin\.(?:max_health|armor_category)",
            "Stormvermin durability must not be copied onto the Engineer",
        )


class DoomrocketShoveWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.breed = read_lua(BREED_PATH)
        cls.tree = read_lua(TREE_PATH)
        cls.generated = read_lua(GENERATED_SELECTOR_PATH)
        cls.bootstrap = read_lua(BOOTSTRAP_PATH)
        cls.item_config = ITEM_CONFIG_PATH.read_text(encoding="utf-8")
        cls.state_machine = STATE_MACHINE_PATH.read_text(encoding="utf-8")
        cls.shove = read_lua(SHOVE_PATH) if SHOVE_PATH.is_file() else ""
        cls.runtime = "\n".join((cls.breed, cls.tree, cls.bootstrap, cls.shove))
        version_match = re.search(
            r'local\s+MOD_VERSION\s*=\s*"([^"]+)"', cls.bootstrap
        )
        if not version_match:
            raise AssertionError("doomrocket.lua is missing MOD_VERSION")
        cls.mod_version = version_match.group(1)

    def test_source_and_workshop_metadata_versions_match(self) -> None:
        title_match = re.search(
            r'(?m)^title\s*=\s*"[^"]*\bv([^" ]+)(?:\s+[^\"]*)?"\s*;',
            self.item_config,
        )
        self.assertIsNotNone(title_match, "itemV2.cfg title has no version suffix")
        self.assertEqual(title_match.group(1), self.mod_version)

    def test_custom_timer_driven_node_exists_and_loads_before_the_tree(self) -> None:
        self.assertTrue(SHOVE_PATH.is_file(), f"missing {SHOVE_PATH}")
        self.assertIn(
            "BTDoomrocketShoveAction = class(BTDoomrocketShoveAction, BTNode)",
            self.shove,
        )
        node_load = self.bootstrap.find(
            'mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_shove_action")'
        )
        tree_load = self.bootstrap.find(
            'mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/trees/skaven/skaven_doomrocket_behavior")'
        )
        self.assertGreaterEqual(node_load, 0, "bootstrap does not load shove node")
        self.assertGreater(tree_load, node_load, "shove class must load before tree parsing")

    def test_action_clones_stormvermin_push_and_uses_supported_visual_event(self) -> None:
        self.assertRegex(
            self.breed,
            r"table\.clone\(BreedActions\.skaven_storm_vermin\.push_attack\)",
        )
        self.assertRegex(
            self.breed,
            r"(?m)^\s*(?:\w+\.)*attack_anim\s*=\s*\"attack_shoot_align\"\s*$",
        )
        self.assertRegex(
            self.state_machine,
            r"(?m)^\s*attack_shoot_align\s*=\s*\{\}\s*$",
        )

        impact_time = numeric_field(self.breed, "impact_time")
        duration = numeric_field(self.breed, "duration")
        self.assertGreaterEqual(impact_time, 0.6)
        self.assertLessEqual(impact_time, 0.8)
        self.assertGreaterEqual(duration, 1.2)
        self.assertLessEqual(duration, 1.5)
        self.assertLess(impact_time, duration)

        # The clone is the behavior contract. Only the visual event and the two
        # timer fields may diverge; changing force, damage, fatigue, blocking,
        # intensity, or considerations would no longer be Stormvermin parity.
        for native_field in (
            "damage",
            "damage_type",
            "fatigue_type",
            "impact_push_speed",
            "max_impact_push_speed",
            "unblockable",
            "difficulty_attack_intensity",
            "considerations",
        ):
            self.assertNotRegex(
                self.breed,
                rf"BreedActions\.skaven_doomrocket\.push_attack\.{native_field}\s*=",
                f"push_attack.{native_field} must remain inherited from Stormvermin",
            )

        overrides = re.findall(
            r"(?m)^\s*BreedActions\.skaven_doomrocket\.push_attack\.(\w+)\s*=",
            self.breed,
        )
        self.assertEqual(
            set(overrides),
            {"attack_anim", "impact_time", "duration"},
            "damage, fatigue, push speeds, considerations, and intensity must stay native",
        )

    def test_reposition_is_wired_before_idle_with_supported_movement(self) -> None:
        source = read_lua(REPOSITION_PATH)
        node_load = self.bootstrap.index('mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_reposition_action")')
        tree_load = self.bootstrap.index('mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/trees/skaven/skaven_doomrocket_behavior")')
        self.assertLess(node_load, tree_load)
        self.assertLess(self.tree.index('"BTDoomrocketShoveAction"'), self.tree.index('"BTDoomrocketRepositionAction"'))
        self.assertLess(self.tree.index('"BTDoomrocketRepositionAction"'), self.tree.index('name = "wait_at_close_range"'))
        self.assertRegex(self.state_machine, r'(?m)^\s*move_fwd\s*=\s*\{\}\s*$')
        self.assertIn('move_anim = "move_fwd_run"', self.breed)
        self.assertRegex(self.state_machine, r'(?m)^\s*move_fwd_run\s*=\s*\{\}\s*$')
        self.assertIn('LocomotionUtils.ray_can_go_on_mesh(', source)
        self.assertIn('navigation:traverse_logic()', source)
        self.assertIn('Vector3Box(projected_end)', source)
        self.assertNotRegex(source, r'blackboard\.(?:reloaded_rocket|attack_pattern_data)\s*=(?!=)')
        self.assertNotRegex(source, r'Unit\.(?:set_local_position|set_world_position|set_animation_state_machine)\(')

    def test_current_compiled_bundle_contains_the_complete_combat_candidate(self) -> None:
        if not any(BUNDLE_ROOT.glob("*.mod_bundle")):
            self.skipTest("bundleV2 is absent; source-only checkout")

        expected_strings = {
            "scripts/mods/doomrocket/doomrocket": (
                self.mod_version.encode(),
                b"bt_doomrocket_shove_action",
                b"bt_doomrocket_reposition_action",
                # #33 knockback and 0.6x rocket damage against AI.
                b"_doomrocket_knockback_player",
                b"server_hit_func",
                b"calculate_damage",
                # v0.1.84: owner-routed catapult without the forced camera turn.
                b"rpc_doomrocket_catapult",
                b"force_look_rotation",
            ),
            "scripts/mods/doomrocket/extensions/projectile_rocket": (
                # #33 contact detonation; v0.1.84 velocity-deviation detector.
                b"_find_impact",
                b"filter_enemy_ray_projectile",
                b"filter_player_ray_projectile_static_only",
                b"_left_ballistic_path",
            ),
            "scripts/mods/doomrocket/breeds/skaven_doomrocket": (
                # #33: Ratling health/armor come from the clone; only the
                # Stormvermin shove is still borrowed.
                b"skaven_storm_vermin",
                b"minimum_aim_time",
                b"finish_breed_registration",
                b"push_attack",
                b"attack_shoot_align",
                b"reposition",
                b"clear_distance",
            ),
            "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/trees/skaven/skaven_doomrocket_behavior": (
                b"BTDoomrocketShoveAction",
                b"doomrocket_should_shove",
                b"close_combat_selector",
                b"doomrocket_should_wait_at_close_range",
                b"wait_at_close_range",
                b"BTDoomrocketRepositionAction",
                b"doomrocket_should_reposition",
            ),
            "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_shove_action": (
                b"BTDoomrocketShoveAction",
                b"doomrocket_shove_active",
                b"shove_begin",
                b"shove_impact",
                b"set_pushed_network",
                b"doomrocket_should_wait_at_close_range",
                b"doomrocket_reposition_request_target",
            ),
            "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_reposition_action": (
                b"BTDoomrocketRepositionAction",
                b"doomrocket_should_reposition",
                b"ray_can_go_on_mesh",
                b"traverse_logic",
                b"number_failed_move_attempts",
                b"reposition_begin",
                b"reposition_plan",
                b"reposition_end",
                b"max_plans",
                b"destination_box",
                b"heading_box",
                b"handoff_distance",
                b"handoff_attempted",
            ),
            "scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_reload_action": (
                b"reload_in_progress",
                b"reload_begin",
                b"reload_interrupted",
                b"reload_complete",
            ),
        }

        for resource_name, needles in expected_strings.items():
            with self.subTest(resource=resource_name):
                payloads = compiled_resource_payloads("lua", resource_name)
                self.assertEqual(
                    len(payloads),
                    1,
                    f"expected one compiled version of {resource_name}, found {len(payloads)}",
                )
                payload = payloads[0]
                self.assertGreater(len(payload), 64, "compiled Lua payload is unexpectedly empty")
                for needle in needles:
                    self.assertIn(
                        needle,
                        payload,
                        f"compiled {resource_name} is stale or missing {needle!r}",
                    )

    def test_inner_selector_prioritizes_shove_without_changing_generated_root(self) -> None:
        root = self.tree[self.tree.index("BreedBehaviors.skaven_doomrocket") :]
        shove = root.find('"BTDoomrocketShoveAction"')
        ranged = root.find('"BTDoomrocketReloadAction"')
        selector = root.rfind('"BTSelector"', 0, shove)
        self.assertGreaterEqual(selector, 0, "attack root is missing its inner selector")
        self.assertGreater(shove, selector)
        self.assertGreater(ranged, shove, "shove must precede the ranged sequence")

        shove_window = root[shove : shove + 500]
        self.assertRegex(shove_window, r'name\s*=\s*"push_attack"')
        self.assertRegex(
            shove_window, r'condition\s*=\s*"doomrocket_should_shove"'
        )
        self.assertRegex(shove_window, r"action_data\s*=\s*ACTIONS\.push_attack")

        self.assertRegex(
            self.generated,
            r"local\s+node_attack_pattern\s*=\s*children\[6\]",
            "the inner-selector change must not shift the generated root layout",
        )
        self.assertRegex(
            self.generated, r"local\s+node_idle\s*=\s*children\[7\]"
        )

    def test_condition_uses_responsive_shove_boundaries_without_utility_node_dependency(self) -> None:
        condition_start = self.runtime.find(
            "BTConditions.doomrocket_should_shove = function"
        )
        self.assertGreaterEqual(condition_start, 0, "missing shove BT condition")
        condition = self.runtime[condition_start : condition_start + 2400]
        active = re.search(r"shove[^\r\n]*active|active[^\r\n]*shove", condition)
        self.assertIsNotNone(active, "running shove must bypass fresh eligibility checks")
        self.assertIn("local SHOVE_MAX_DISTANCE = 2.2", self.shove)
        self.assertIn("local SHOVE_MAX_TARGET_SPEED_AWAY = 1.5", self.shove)
        self.assertIn("local SHOVE_COOLDOWN_SECONDS = 2.0", self.shove)
        self.assertNotIn(
            "Utility.get_action_utility",
            condition,
            "the Ratling selector must not depend on a Stormvermin BTUtilityNode",
        )
        self.assertNotIn(
            "confirmed_player_sighting",
            condition,
            "the Ratling attack tree can have a valid target without this Stormvermin outer gate",
        )
        self.assertRegex(condition, r"not\s+Unit\.alive\s*\(\s*target_unit\s*\)")
        self.assertIn("BTConditions.ask_target_before_attacking", condition)
        self.assertRegex(condition, r'type\(target_dist\)\s*~=\s*"number"')
        self.assertRegex(
            condition, r'type\(target_speed_away\)\s*~=\s*"number"'
        )
        self.assertRegex(condition, r'type\(utility_data\.time_since_last\)\s*~=\s*"number"')
        self.assertIn("utility_data.time_since_last < SHOVE_COOLDOWN_SECONDS", condition)
        self.assertIn("target_dist >= SHOVE_MAX_DISTANCE", condition)
        self.assertIn("target_speed_away >= SHOVE_MAX_TARGET_SPEED_AWAY", condition)
        self.assertIn("blackboard.target_is_not_downed == false", condition)
        self.assertIn("phase=shove_selected", condition)
        if "action.name" in condition:
            self.assertRegex(
                condition,
                r"local\s+action_name\s*=\s*action\.name\s+or\s+[\"']push_attack[\"']",
                "utility lookup needs a safe action-name fallback",
            )
            self.assertRegex(condition, r"utility_actions\s*\[\s*action_name\s*\]")
        else:
            self.fail("condition must derive its utility key from action.name")

        self.assertRegex(
            self.shove,
            r"utility_actions\s*\[[^\]]*(?:action_name|action\.name|push_attack)[^\]]*\]"
            r"[\s\S]{0,240}?\.last_time\s*=\s*t",
            "enter must record native utility cooldown at shove start",
        )

    def test_shove_does_not_depend_on_foreign_animation_callbacks(self) -> None:
        self.assertNotIn('"attack_push"', self.runtime)
        self.assertNotIn("BTStormVerminPushAction", self.runtime)
        self.assertNotRegex(
            self.shove, r"BTDoomrocketShoveAction\.anim_cb_\w+\s*=\s*function"
        )
        callback_reads = re.sub(
            r"(?m)^\s*blackboard\.anim_cb_\w+\s*=\s*nil\s*$", "", self.shove
        )
        self.assertNotRegex(
            callback_reads,
            r"\banim_cb_\w+",
            "clearing stale Ratling callback flags is allowed; reading one to time the shove is not",
        )
        self.assertRegex(
            self.shove,
            r"(?:network[^\r\n]*:anim_event|Unit\.animation_event)\s*\([^\n]*action\.attack_anim",
        )
        self.assertRegex(
            self.shove,
            r"t\s*>=\s*[^\r\n]*(?:end|finish|duration)[^\r\n]*",
            "completion must be driven by time rather than a missing clip callback",
        )
        for phase in ("shove_rejected", "shove_begin", "shove_impact"):
            self.assertIn(
                f"phase={phase}", self.shove, f"missing deterministic {phase} telemetry"
            )

    def test_impact_is_guarded_once_and_matches_native_zero_damage_push(self) -> None:
        self.assertRegex(
            self.shove,
            r"(?:not\s+[^\r\n]*impact|impact[^\r\n]*==\s*(?:nil|false))[\s\S]{0,500}?"
            r"(?:impact[^\r\n]*=\s*true)",
            "impact must have a one-shot guard",
        )
        self.assertEqual(self.shove.count("AiUtils.damage_target("), 1)
        self.assertEqual(self.shove.count("StatusUtils.set_pushed_network("), 1)
        self.assertEqual(self.shove.count(":add_external_velocity("), 1)
        self.assertIn("DamageUtils.check_distance(", self.shove)
        self.assertIn("DamageUtils.check_infront(", self.shove)
        self.assertRegex(
            self.shove,
            r"AiUtils\.damage_target\([^\n]+action\.damage\)",
        )
        self.assertRegex(
            self.shove,
            r"StatusUtils\.set_pushed_network\([^\n]+,\s*true\s*\)",
        )
        self.assertRegex(
            self.shove,
            r"Quaternion\.forward\([^\n]+\)\s*\*\s*action\.impact_push_speed",
        )
        self.assertRegex(
            self.shove,
            r"add_external_velocity\([^\n]+action\.max_impact_push_speed\)",
        )

    def test_enter_and_leave_restore_navigation_and_clear_transient_state(self) -> None:
        self.assertRegex(
            self.shove,
            r"BTDoomrocketShoveAction\.enter[\s\S]+?"
            r"navigation_extension:set_enabled\(false\)",
        )
        self.assertRegex(
            self.shove,
            r"BTDoomrocketShoveAction\.enter[\s\S]+?"
            r"locomotion_extension:set_wanted_velocity\(Vector3\.zero\(\)\)",
        )
        leave = self.shove[self.shove.find("BTDoomrocketShoveAction.leave") :]
        self.assertRegex(leave, r"navigation_extension:set_enabled\(true\)")
        self.assertRegex(leave, r"(?:network[^\r\n]*:anim_event|Unit\.animation_event)\([^\n]*\"idle\"")
        self.assertRegex(leave, r"shove[^\r\n]*=\s*nil|shove[^\r\n]*active[^\r\n]*=\s*false")
        for callback in (
            "anim_cb_attack_shoot_start_finished",
            "anim_cb_attack_shoot_random_shot",
        ):
            self.assertRegex(leave, rf"blackboard\.{callback}\s*=\s*nil")


if __name__ == "__main__":
    unittest.main(verbosity=2)
