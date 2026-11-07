"""Execute the opt-in new-spawn controller rehearsal and source/compiled gates."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/animation_rig"))
import build_native_rehearsal as rehearsal
import stage_integration as stage

MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_animation_rehearsal.lua"
MANIFEST = ROOT / rehearsal.COMPANION
HARNESS = r'''
calls={reads=0,writes=0,switches=0};commands={};messages={}
world={};other_world={}
owner={alive=true,world=world};outfit={alive=true,world=world,data={unit_name=stock},asm=stock}
mod={_warlock_outfits={},_warlock_outfit_owners={}}
function get_mod(name) assert(name=='doomrocket');return mod end
function mod:command(name,help,handler) commands[name]=handler end
function mod:echo(fmt,...) messages[#messages+1]=string.format(fmt,...) end
function native(u) assert(u and u.alive,'native access after delete');calls.reads=calls.reads+1 end
function modify(kind,key,value)
 if callback then callback(kind,key,value) end
 if failure_kind==kind and failure_key==key then failure_kind=nil;error('injected setter failure') end
end
Unit={
 alive=function(u) return u and u.alive or false end,
 world=function(u) native(u);return u.world end,
 get_data=function(u,k) native(u);if read_failure==k then error('read failed') end;return u.data and u.data[k] end,
 set_data=function(u,k,v) native(u);calls.writes=calls.writes+1;u.data[k]=v;modify('data',k,v) end,
 has_node=function(u,k) native(u);return k~=missing_bone end,
 has_animation_state_machine=function(u) native(u);return not no_controller end,
 set_animation_state_machine=function(u,s)
  native(u);calls.switches=calls.switches+1;u.asm=s;modify('asm',s,s)
 end,
}
Application={can_get=function(kind,name) return name~=missing_resource and kind~=missing_kind end}
function choose(action) commands.warlock_animation_rehearsal(action) end
function prepare() return mod._prepare_warlock_animation_rehearsal(owner,outfit,true) end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().stock = rehearsal.UNIT
    lua.globals().visible = rehearsal.VISIBLE
    lua.globals().sampler = rehearsal.SAMPLER
    lua.globals().profile_id = rehearsal.PROFILE
    lua.execute(HARNESS)
    lua.globals().mod._warlock_animation_manifest = lua.execute(MANIFEST.read_text())
    lua.execute(MODULE.read_text())
    return lua


class NativeRehearsalRuntimeTests(unittest.TestCase):
    def test_default_off_has_no_native_reads_writes_or_switches(self):
        lua = runtime()
        lua.execute("local ok,why=prepare();assert(not ok and why=='off');assert(calls.reads==0 and calls.writes==0 and calls.switches==0)")

    def test_command_never_sweeps_or_changes_existing_units(self):
        lua = runtime()
        lua.execute("choose('on');choose('status');choose('off');choose('junk');assert(calls.reads==0 and calls.writes==0 and calls.switches==0)")

    def test_fresh_opt_in_uses_matching_markers_and_same_skeleton_asm(self):
        lua = runtime()
        lua.execute("choose('on');local ok,why=prepare();assert(ok and why=='selected');assert(outfit.asm==visible and calls.switches==1 and calls.writes==2);assert(outfit.data.warlock_rig_profile==profile_id);assert(outfit.data.warlock_animation_manifest_id==mod._warlock_animation_manifest.profiles[profile_id].manifest_id)")

    def test_no_grant_or_repeated_outfit_never_switches(self):
        lua = runtime()
        lua.execute("choose('on');assert(not mod._prepare_warlock_animation_rehearsal(owner,outfit));assert(prepare());local a,b=calls.switches,calls.writes;assert(not prepare());assert(calls.switches==a and calls.writes==b)")

    def test_off_spawn_cannot_be_retroactively_selected(self):
        lua = runtime()
        lua.execute("assert(not prepare());choose('on');assert(not prepare());assert(calls.switches==0 and calls.writes==0)")

    def test_off_does_not_change_already_selected_outfit(self):
        lua = runtime()
        lua.execute("choose('on');assert(prepare());choose('off');assert(outfit.asm==visible and outfit.data.warlock_rig_profile==profile_id and calls.switches==1)")

    def test_reset_and_reload_default_off_do_not_rewrite_active_poses(self):
        lua = runtime()
        lua.execute("choose('on');assert(prepare());mod._reset_warlock_animation_rehearsal();assert(not mod._warlock_animation_rehearsal_status().enabled);assert(outfit.asm==visible and calls.switches==1)")
        lua.execute(MODULE.read_text())
        lua.execute("assert(not mod._warlock_animation_rehearsal_status().enabled);assert(outfit.asm==visible and calls.switches==1);choose('on');assert(not prepare());assert(calls.switches==1)")

    def test_existing_profile_or_identity_never_gets_overwritten(self):
        for key in ("warlock_rig_profile", "warlock_animation_manifest_id"):
            with self.subTest(key=key):
                lua = runtime()
                lua.globals().key = key
                lua.execute("outfit.data[key]='artist-custom';outfit.asm='custom';choose('on');local ok,why=prepare();assert(not ok and why=='existing_profile');assert(outfit.data[key]=='artist-custom' and outfit.asm=='custom' and calls.writes==0 and calls.switches==0)")

    def test_registered_pair_and_existing_controller_are_rejected(self):
        for setup in ("mod._warlock_outfits[owner]=outfit", "mod._warlock_outfit_owners[outfit]=owner",
                      "mod._warlock_animation_blend_status=function() return 'active' end",
                      "mod._warlock_grip_alignment_status=function() return 'armed' end",
                      "mod._warlock_outfit_correction_status=function() return 'active-legacy' end"):
            with self.subTest(setup=setup):
                lua = runtime()
                lua.execute(setup + ";choose('on');assert(not prepare());assert(calls.writes==0 and calls.switches==0)")

    def test_wrong_unit_dead_or_foreign_world_fails_without_writes(self):
        for setup in ("outfit.data.unit_name='foreign'", "outfit.alive=false", "owner.alive=false", "outfit.world=other_world"):
            with self.subTest(setup=setup):
                lua = runtime()
                lua.execute(setup + ";choose('on');assert(not prepare());assert(calls.writes==0 and calls.switches==0)")

    def test_missing_loaded_resources_or_bones_do_not_bind_controller(self):
        for setup in ("missing_resource=stock", "missing_resource=visible", "missing_resource=sampler",
                      "missing_kind='animation'", "missing_kind='unit'", "missing_bone='j_hips'", "no_controller=true"):
            with self.subTest(setup=setup):
                lua = runtime()
                lua.execute(setup + ";choose('on');assert(not prepare());assert(calls.writes==0 and calls.switches==0)")

    def test_untrusted_or_changed_profile_rejected(self):
        for mutation in ("p.native_rehearsal_only=false", "p.unit='foreign'", "p.visible_state_machine=stock",
                         "p.sampler_state_machine='foreign'", "p.accessory_skin='localized-v1'", "p.manifest_id='bad'",
                         "p.states['base/idle'].visible_aim=true", "p.states['base/idle'].owner='legacy'",
                         "p.validation.artist_export_acceptance=true", "p.bone_names[2]=p.bone_names[1]"):
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("local p=mod._warlock_animation_manifest.profiles[profile_id];" + mutation + ";choose('on');assert(not prepare());assert(calls.writes==0 and calls.switches==0)")

    def test_marker_and_identity_setter_failures_restore_nil_without_asm_switch(self):
        for key in ("warlock_rig_profile", "warlock_animation_manifest_id"):
            with self.subTest(key=key):
                lua = runtime()
                lua.globals().failure_key = key
                lua.execute("failure_kind='data';choose('on');assert(not prepare());assert(outfit.asm==stock and calls.switches==0);assert(outfit.data.warlock_rig_profile==nil and outfit.data.warlock_animation_manifest_id==nil)")

    def test_partial_asm_setter_failure_restores_stock_asm_and_nil_markers(self):
        lua = runtime()
        lua.execute("failure_kind='asm';failure_key=visible;choose('on');assert(not prepare());assert(outfit.asm==stock and calls.switches==2);assert(outfit.data.warlock_rig_profile==nil and outfit.data.warlock_animation_manifest_id==nil)")

    def test_profile_replaced_during_setter_is_preserved(self):
        lua = runtime()
        lua.execute("callback=function(kind,key,value) if kind=='data' and key=='warlock_rig_profile' then outfit.data.warlock_rig_profile='artist-custom';outfit.asm='custom' end end;choose('on');local ok,why=prepare();assert(not ok and why=='rollback_incomplete_protected');assert(outfit.asm=='custom' and outfit.data.warlock_rig_profile=='artist-custom' and calls.switches==0)")

    def test_foreign_profile_installed_during_rollback_asm_is_not_cleared(self):
        lua = runtime()
        lua.execute("failure_kind='asm';failure_key=visible;callback=function(kind,key) if kind=='asm' and key==stock then outfit.data.warlock_rig_profile='artist-custom';outfit.data.warlock_animation_manifest_id='artist-manifest';outfit.asm='custom' end end;choose('on');local ok,why=prepare();assert(not ok and why=='rollback_incomplete_protected');assert(outfit.asm=='custom' and outfit.data.warlock_rig_profile=='artist-custom' and outfit.data.warlock_animation_manifest_id=='artist-manifest')")

    def test_foreign_profile_installed_during_rollback_identity_clear_is_preserved(self):
        lua = runtime()
        lua.execute("failure_kind='asm';failure_key=visible;callback=function(kind,key,value) if kind=='data' and key=='warlock_animation_manifest_id' and value==nil then outfit.data.warlock_rig_profile='artist-custom';outfit.data.warlock_animation_manifest_id='artist-manifest';outfit.asm='custom' end end;choose('on');local ok,why=prepare();assert(not ok and why=='rollback_incomplete_protected');assert(outfit.asm=='custom' and outfit.data.warlock_rig_profile=='artist-custom' and outfit.data.warlock_animation_manifest_id=='artist-manifest')")

    def test_outfit_deleted_during_setter_never_gets_more_native_access(self):
        lua = runtime()
        lua.execute("callback=function() outfit.alive=false end;choose('on');local ok,why=prepare();assert(not ok and why=='rollback_incomplete_protected');assert(calls.switches==0 and calls.writes==1)")


class NativeRehearsalSourceTests(unittest.TestCase):
    def test_generated_graph_profile_and_original_source_hashes_match(self):
        self.assertEqual(rehearsal.run()["status"], "native-rehearsal-source-contract-passed")
        contract = json.loads((ROOT / rehearsal.CONTRACT).read_text())
        self.assertFalse(contract["artist_export_acceptance"])
        self.assertFalse(contract["localized_garment_acceptance"])
        for path, expected in contract["source_files_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), expected, path)

    def test_default_manifest_is_independent_and_has_no_rehearsal_activation(self):
        lua = LuaRuntime()
        manifest = lua.execute((ROOT / stage.MANIFEST).read_text())
        self.assertIsNone(manifest.profiles[rehearsal.PROFILE])

    def test_compiled_graph_verifier_rejects_changed_edges_clips_and_aim(self):
        from compiled_integration import state_bindings
        from test_warlock_weapon_pipeline import murmur64a
        outputs, manifest = rehearsal.create(with_manifest=True)
        profile = manifest["profiles"][rehearsal.PROFILE]
        names = list(profile["states"])
        graphs = []
        for text in ((ROOT / (rehearsal.UNIT + ".state_machine")).read_text(),
                     outputs[rehearsal.VISIBLE + ".state_machine"].decode(),
                     outputs[rehearsal.SAMPLER + ".state_machine"].decode()):
            states = stage.Sjson(text).parse().value["layers"][0]["states"]
            graphs.append({murmur64a(s["name"].encode()): {"animations": tuple(murmur64a(x.encode()) for x in s["animations"]),
                "constraints": (0,) if "warlock_aim" in s.get("constraints", []) else (),
                "transitions": [{"event": e["event"], "target_index": names.index(e["to"]),
                    "blend_time": e["blend_time"], "mode": 0, "on_beat": 0} for e in s["transitions"]]} for s in states})
        bones = profile["bone_names"]
        def evaluate(values):
            def read(payload): return object(), values[payload[0]]
            with patch("compiled_integration.state_bindings", side_effect=read), patch("test_doomrocket_visible_aim.verify_aim"):
                return rehearsal.verify_controllers(b"\0", b"\1", b"\2", bones, manifest)
        self.assertEqual(evaluate(graphs)["visible_edges_preserved"], 154)
        idle = murmur64a(b"base/idle")
        for mutation in ("edge", "clip", "aim", "helper"):
            with self.subTest(mutation=mutation):
                values = copy.deepcopy(graphs)
                if mutation == "edge": values[1][idle]["transitions"][0]["blend_time"] += .1
                elif mutation == "clip": values[1][idle]["animations"] = (12,)
                elif mutation == "aim": values[1][idle]["constraints"] = (0,)
                else: values[2][idle]["transitions"][0]["blend_time"] = .1
                with self.assertRaises(ValueError): evaluate(values)

    def test_bootstrap_merge_and_new_spawn_hook_precede_ownership_registration(self):
        source = (ROOT / "scripts/mods/doomrocket/doomrocket.lua").read_text()
        start = source.index('mod._warlock_animation_manifest = mod:dofile(')
        companion = source.index('local rehearsal_manifest = mod:dofile(', start)
        extension = source.index('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_rehearsal")', companion)
        owner = source.index('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_ownership")', extension)
        self.assertLess(start, companion)
        self.assertLess(companion, extension)
        self.assertLess(extension, owner)
        self.assertIn('if mod._warlock_animation_manifest.profiles[id] == nil then', source[companion:extension])
        hooks = (ROOT / "scripts/mods/doomrocket/utils/hooks.lua").read_text()
        branch = hooks.index('elseif outfit_unit_name == "' + rehearsal.UNIT + '" then')
        enable = hooks.index('Unit.enable_animation_state_machine(outfit_unit)', branch)
        prepare = hooks.index('mod._prepare_warlock_animation_rehearsal(unit, outfit_unit, true)', enable)
        register = hooks.index('mod._warlock_outfits[unit] = outfit_unit', prepare)
        ownership = hooks.index('mod._start_warlock_animation_ownership(unit, outfit_unit)', register)
        self.assertLess(enable, prepare)
        self.assertLess(prepare, register)
        self.assertLess(register, ownership)

    def test_bootstrap_companion_merge_preserves_existing_custom_profile(self):
        source = (ROOT / "scripts/mods/doomrocket/doomrocket.lua").read_text()
        start = source.index('local rehearsal_manifest = mod:dofile(')
        end = source.index('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_rehearsal")', start)
        lua = LuaRuntime()
        lua.execute("original={artist=true};other={artist=true};mod={_warlock_animation_manifest={profiles={same=original,other=other}}};function mod:dofile(path) return {profiles={same={artist=false},added={rehearsal=true}}} end")
        lua.execute(source[start:end])
        lua.execute("assert(mod._warlock_animation_manifest.profiles.same==original and mod._warlock_animation_manifest.profiles.other==other and mod._warlock_animation_manifest.profiles.added.rehearsal)")


@unittest.skipUnless(any((ROOT / "bundleV2").glob("*.mod_bundle")), "No canonical bundle; source-only CI")
class NativeRehearsalCompiledTests(unittest.TestCase):
    def test_actual_bundle_loads_matching_controllers_profile_and_unchanged_tracks(self):
        from test_warlock_weapon_pipeline import compiled_bundle_resources
        result = rehearsal.verify_bundle(compiled_bundle_resources())
        self.assertEqual(result["visible_edges_preserved"], 154)
        self.assertEqual(result["sampler_zero_edges"], 154)
        self.assertEqual(result["native_pose_samples"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
