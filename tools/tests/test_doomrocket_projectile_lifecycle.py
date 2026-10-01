#!/usr/bin/env python3
"""Regression contracts for the Doomrocket projectile's terminal lifecycle.

Issue #8 showed why this ordering is safety-critical: an engine exception during
``create_explosion`` aborted ``rocket_explode`` before the old implementation set
``self.exploded`` or queued deletion.  The still-live physics object therefore
entered the same path every frame.  These tests keep the one-shot claim and the
irreversible cleanup ahead of every fallible engine/audio callback while retaining
the registry entry that the deletion hook needs to run ``destroy``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTILE_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "projectile_rocket.lua"
)
HOOKS_PATH = (
    REPO_ROOT / "scripts" / "mods" / "doomrocket" / "utils" / "hooks.lua"
)
DEATH_REACTIONS_PATH = (
    REPO_ROOT
    / "scripts"
    / "mods"
    / "doomrocket"
    / "extensions"
    / "death_reactions.lua"
)


def without_lua_comments(source: str) -> str:
    """Remove Lua comments so prose cannot satisfy a runtime contract."""

    source = re.sub(r"--\[\[.*?\]\]", "", source, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", source)


def method_body(source: str, method: str, next_method: str | None) -> str:
    start_marker = f"ProjectileRocket.{method} = function"
    start = source.find(start_marker)
    if start < 0:
        raise AssertionError(f"missing {start_marker}")

    if next_method is None:
        end = len(source)
    else:
        end_marker = f"ProjectileRocket.{next_method} = function"
        end = source.find(end_marker, start + len(start_marker))
        if end < 0:
            raise AssertionError(f"missing {end_marker} after {start_marker}")

    return source[start:end]


class DoomrocketProjectileLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = without_lua_comments(PROJECTILE_PATH.read_text(encoding="utf-8"))
        cls.hooks = without_lua_comments(HOOKS_PATH.read_text(encoding="utf-8"))
        cls.death_reactions = without_lua_comments(
            DEATH_REACTIONS_PATH.read_text(encoding="utf-8")
        )
        cls.update = method_body(cls.source, "update", "straighten_rocket")
        cls.explode = method_body(cls.source, "rocket_explode", "destroy")
        cls.destroy = method_body(cls.source, "destroy", None)

    def test_explosion_entry_is_an_early_idempotency_guard(self) -> None:
        self.assertRegex(
            self.explode,
            r"ProjectileRocket\.rocket_explode\s*=\s*function\(self\)\s*"
            r"if\s+self\.exploded\s+or\s+not\s+Managers\.player\.is_server\s+then\s*"
            r"return\s+false\s*end",
            "an already-claimed explosion or a non-authoritative peer must return before side effects",
        )

    def test_terminal_claim_and_deletion_precede_fallible_work(self) -> None:
        expected_once = (
            "self.exploded = true",
            "local unit = self.unit",
            "local position = actor and Actor.position(actor)",
            "local rotation = actor and Actor.rotation(actor)",
            "Managers.state.unit_spawner:mark_for_deletion(unit)",
            "mod._doomrocket_sound_impact_requested(position)",
            'network_transmit:send_rpc_server("rpc_create_explosion"',
        )
        for statement in expected_once:
            with self.subTest(statement=statement):
                self.assertEqual(
                    self.explode.count(statement),
                    1,
                    f"terminal path must own exactly one {statement!r}",
                )

        claim = self.explode.index("self.exploded = true")
        position_snapshot = self.explode.index(
            "local position = actor and Actor.position(actor)"
        )
        rotation_snapshot = self.explode.index(
            "local rotation = actor and Actor.rotation(actor)"
        )
        deletion = self.explode.index(
            "Managers.state.unit_spawner:mark_for_deletion(unit)"
        )
        telemetry = self.explode.index("mod._doomrocket_sound_impact_requested(position)")
        server_request = self.explode.index(
            'network_transmit:send_rpc_server("rpc_create_explosion"'
        )

        self.assertLess(claim, position_snapshot, "claim before reading engine state")
        self.assertLess(position_snapshot, rotation_snapshot)
        self.assertLess(
            rotation_snapshot,
            deletion,
            "snapshot the final transform before queuing its unit for deletion",
        )
        self.assertLess(
            deletion,
            telemetry,
            "queue deletion before the first mod callback can raise",
        )
        self.assertLess(
            telemetry,
            server_request,
            "impact telemetry must describe the one server-directed request",
        )

    def test_projectile_uses_one_server_rpc_and_no_unsafe_local_damage(self) -> None:
        self.assertEqual(
            self.explode.count(
                'network_transmit:send_rpc_server("rpc_create_explosion"'
            ),
            1,
        )
        self.assertNotIn('send_rpc_clients("rpc_create_explosion"', self.explode)
        self.assertNotIn('send_rpc_clients_except("rpc_create_explosion"', self.explode)
        self.assertNotIn(':system("area_damage_system")', self.explode)
        self.assertNotIn("area_damage_system:create_explosion(", self.explode)
        self.assertNotIn("DamageUtils.create_explosion(", self.explode)
        self.assertIn(
            "local attacker_unit_id = self.attacker_goid",
            self.explode,
        )
        self.assertRegex(
            self.explode,
            r'network_transmit:send_rpc_server\("rpc_create_explosion",\s*'
            r"attacker_unit_id,\s*false,\s*position,\s*rotation,\s*"
            r"explosion_template_id,\s*1,\s*damage_source_id,\s*power_level,\s*"
            r"false,\s*attacker_unit_id\s*\)",
            "native RPC fields must match AreaDamageSystem.rpc_create_explosion",
        )

    def test_loaded_warhead_keeps_authoritative_area_damage_path(self) -> None:
        self.assertEqual(
            self.death_reactions.count(':system("area_damage_system")'),
            1,
        )
        self.assertEqual(
            self.death_reactions.count("area_damage_system:create_explosion("),
            1,
        )
        self.assertNotIn('send_rpc_server("rpc_create_explosion"', self.death_reactions)
        self.assertNotIn('send_rpc_clients("rpc_create_explosion"', self.death_reactions)

    def test_explosion_retains_registry_entry_for_deferred_destroy(self) -> None:
        self.assertNotIn(
            "mod.projectiles[unit] = nil",
            self.explode,
            "GrowQueue.pop_first looks up this entry to invoke projectile destroy",
        )
        self.assertEqual(
            self.destroy.count("mod.projectiles[unit] = nil"),
            1,
            "only destroy may release the deletion hook's projectile lookup",
        )
        self.assertRegex(
            self.hooks,
            r"mod\.projectiles\[unit\][\s\S]*?prj_rckt:destroy\(\)",
            "the deferred-deletion hook must still resolve and destroy the retained object",
        )

    def test_missing_actor_cannot_bypass_live_unit_deletion(self) -> None:
        deletion = self.explode.index(
            "Managers.state.unit_spawner:mark_for_deletion(unit)"
        )
        missing_actor = self.explode.index("if not actor then")
        self.assertLess(
            deletion,
            missing_actor,
            "a live projectile unit must be queued even if its cached actor vanished",
        )
        self.assertRegex(
            self.explode,
            r"if\s+not\s+unit\s+or\s+not\s+Unit\.alive\(unit\)\s+then\s*"
            r"self:destroy\(\)\s*return\s+false\s*end",
            "an already-removed unit must release its orphan registry/particle state",
        )

    def test_update_stops_mutating_after_an_explosion_attempt(self) -> None:
        self.assertRegex(
            self.update,
            r"if\s+self\.exploded\s+then\s*return\s*end",
            "terminal projectiles must leave update immediately",
        )
        self.assertRegex(
            self.update,
            r"if\s+not\s+Unit\.alive\(self\.unit\)\s+then\s*"
            r"self:rocket_explode\(\)\s*return\s*end",
            "a dead unit must not fall through into actor/particle updates",
        )
        self.assertRegex(
            self.update,
            r"if\s+self\.time_pass\s*>\s*0\.35\s+and\s+speed\s*<\s*1\.5\s+then\s*"
            r"self:rocket_explode\(\)\s*return\s*end",
            "an impact transition must not mutate projectile state afterward",
        )

    def test_destroy_is_terminal_and_cannot_rearm_the_projectile(self) -> None:
        self.assertIn("self.exploded = true", self.destroy)
        self.assertNotRegex(
            self.destroy,
            r"self\.exploded\s*=\s*(?:false|nil)",
            "destroy must preserve the terminal guard for any late callback",
        )
        terminal = self.destroy.index("self.exploded = true")
        detach = self.destroy.index("mod.projectiles[unit] = nil")
        self.assertLess(terminal, detach)
        self.assertRegex(
            self.destroy,
            r"if\s+unit\s+and\s+Unit\.alive\(unit\)\s+then\s*"
            r"Unit\.destroy_actor\(unit,\s*['\"]pRocket['\"]\)",
            "cleanup of an already-removed unit must not touch its stale actor",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
