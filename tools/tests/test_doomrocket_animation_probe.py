"""Execute passive telemetry in Lua and mutation-test its offline log parser."""
import copy
import json
from pathlib import Path
import sys
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/animation_rig"))
from parse_animation_probe import BONES, validate

MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_animation_probe.lua"
CLOCK = ROOT / "scripts/mods/doomrocket/utils/doomrocket_animation_clock.lua"
BOOTSTRAP = ROOT / "scripts/mods/doomrocket/doomrocket.lua"
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"
HARNESS = r'''
world={};other_world={};owner={alive=true,world=world};outfit={alive=true,world=world};helper={alive=true,world=world}
messages={};callbacks={};reads=0;writes=0;temp_restores=0;commands={};clock_reads=0;illegal_clock_reads=0
mod={_doomrocket_version='0.1.93-dev',_warlock_outfits={[owner]=outfit}}
HEALTH_ALIVE={[owner]=true}
function get_mod() return mod end
function printf(...) messages[#messages+1]=string.format(...) end
function mod:echo(...) end
function mod:command(name,help,fn) commands[name]=fn end
function action(value) commands.warlock_animation_probe(value) end
function valid(u) assert(u and u.alive and u.world==world,'native access after release') end
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) valid(u);return u.world end,
 get_data=function(u,key)
  valid(u)
  assert(key=='warlock_rig_profile');return marker
 end,
 has_animation_state_machine=function(u) valid(u);return not u.no_asm end,
 animation_get_state=function(u)
  valid(u)
  if u.no_layers then return end
  if u.empty_layer then return nil end
  if u.two_layers then return 31,42 end
  return 31
 end,
 has_node=function(u,name) valid(u);return not missing_bone end,
 node=function(u,name) valid(u);return 1 end,
 local_pose=function(u,node) valid(u);reads=reads+1;if bad_pose then error('unsupported pose API') end;return {} end,
 animation_layer_info=function(u,layer)
  clock_reads=clock_reads+1
  if not u or not u.alive or u.no_asm or u.no_layers or u.empty_layer or u.two_layers or layer~=0 then
   illegal_clock_reads=illegal_clock_reads+1;error('native layer precondition violated')
  end
  valid(u);if bad_clock then return 0/0,1 end;return clock or .1,clock_length or 2
 end,
}
setmetatable(Unit,{__index=function(_,key) if key:find('set_',1,true) then return function() writes=writes+1;error('native write') end end end})
Matrix4x4={x=function() return {x=1,y=0,z=0} end,y=function() return {x=0,y=1,z=0} end,
 z=function() return {x=0,y=0,z=1} end,translation=function() return {x=0,y=0,z=0} end}
Script={temp_count=function() return 1,2,3 end,set_temp_count=function(a,b,c) assert(a==1 and b==2 and c==3);temp_restores=temp_restores+1 end}
World=setmetatable({},{__index=function() return function() writes=writes+1;error('probe performed world operation') end end})
animation={add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn end}
Managers={state={entity={system=function(self,name) assert(name=='animation_system');return animation end}}}
snapshot={status='blending',helper=helper,outfit=outfit,manifest_id=string.rep('a',64),state='base/idle',
 event='idle',event_frame=1,frame=2,active=true,blocked=false,clock_reset=false,elapsed=.1,duration=.25,
 sample_dt=.1,sample_rate=1,release_serial=0,sampler_mesh_count=3,
 helper_visibility_policy='per-mesh-default-and-shadow-hidden-configured',pose_owner='authored',clip='diagnostic'}
function mod._warlock_animation_blend_snapshot(u) assert(u==owner);return snapshot end
function tick(dt)
 mod._queue_warlock_animation_probe(world,dt)
 local pending=callbacks;callbacks={};for _,fn in ipairs(pending) do fn() end
end
'''


def runtime():
    result = LuaRuntime(unpack_returned_tuples=True)
    result.execute(HARNESS)
    result.globals().mod._warlock_animation_clock = result.execute(CLOCK.read_text(encoding="utf-8"))
    result.execute(MODULE.read_text(encoding="utf-8"))
    return result


def lines(lua):
    return [lua.eval(f"messages[{i}]") for i in range(1, lua.eval("#messages") + 1)]


class AnimationProbeLua(unittest.TestCase):
    def test_unready_owned_layers_never_attempt_native_layer_reads(self):
        for unit in ("helper", "outfit"):
            for mutation in ("no_asm=true", "no_layers=true", "empty_layer=true", "two_layers=true"):
                with self.subTest(unit=unit, mutation=mutation):
                    lua = runtime()
                    lua.execute("marker='custom';" + unit + "." + mutation + ";action('on');tick(.1)")
                    report = validate(lines(lua), "0.1.93-dev")
                    self.assertEqual(report["status"], "diagnostic-unavailable")
                    self.assertEqual(report["sample_count"], 0)
                    # A valid helper may be read first; an unready helper must
                    # stop before either native layer query is attempted.
                    self.assertEqual(lua.eval("clock_reads"), 0 if unit == "helper" else 1)
                    self.assertEqual(lua.eval("illegal_clock_reads + reads + writes"), 0)

    def test_finite_native_sentinel_is_not_emitted_as_clock_evidence(self):
        lua = runtime()
        lua.execute("marker='custom';clock_length=1e37;action('on');tick(.1)")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["status"], "diagnostic-unavailable")
        self.assertEqual(report["sample_count"], 0)
        self.assertEqual(lua.eval("illegal_clock_reads + reads + writes"), 0)

    def test_missing_shared_reader_stops_before_native_queries(self):
        lua = runtime()
        lua.execute("marker='custom';mod._warlock_animation_clock=nil;action('on');tick(.1)")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["status"], "diagnostic-unavailable")
        self.assertEqual(lua.eval("clock_reads + illegal_clock_reads + reads + writes"), 0)

    def test_default_off_has_no_native_work_or_queued_callbacks(self):
        lua = runtime()
        lua.execute("tick(.1)")
        self.assertEqual(lua.eval("reads + writes + #messages + #callbacks"), 0)

    def test_default_profile_is_explicitly_absent_and_never_reads_poses(self):
        lua = runtime()
        lua.execute("action('on');tick(.1);action('off')")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["status"], "no-custom-profile-observed")
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(lua.eval("reads + writes"), 0)

    def test_registered_custom_profile_records_post_presentation_matrices_without_writes(self):
        lua = runtime()
        lua.execute("marker='custom';action('on');tick(.1);clock=.4;tick(.25);action('off')")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["status"], "passive-native-animation-observations-recorded")
        self.assertEqual(report["units_with_helper_clock_progress"], [1])
        self.assertEqual(lua.eval("reads"), 40)
        self.assertEqual(lua.eval("temp_restores"), 40)
        self.assertEqual(lua.eval("writes"), 0)
        self.assertEqual(report["native_fixed_frame_oracle_samples"], 0)

    def test_clock_failure_is_contained_without_partial_sample(self):
        lua = runtime()
        lua.execute("marker='custom';bad_clock=true;action('on');tick(.1)")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["status"], "diagnostic-unavailable")
        self.assertEqual(report["sample_count"], 0)
        self.assertEqual(lua.eval("writes"), 0)

    def test_pose_failure_restores_owned_native_temporaries(self):
        lua = runtime()
        lua.execute("marker='custom';bad_pose=true;action('on');tick(.1)")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["status"], "diagnostic-unavailable")
        self.assertEqual(lua.eval("temp_restores"), 1)

    def test_missing_native_lifetime_api_in_queued_callback_is_contained(self):
        lua = runtime()
        lua.execute("action('on');mod._queue_warlock_animation_probe(world,.1);Unit.world=nil;for _,fn in ipairs(callbacks) do fn() end")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["status"], "diagnostic-unavailable")

    def test_queue_preflight_and_registration_fail_once_then_stay_off(self):
        for failure in ("Unit.world=nil", "Managers.state=nil",
                        "animation.add_safe_animation_callback=function() error('unsupported callback API') end",
                        "animation.add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn;error('partial registration') end"):
            with self.subTest(failure=failure):
                lua = runtime()
                lua.execute("action('on');" + failure + ";for i=1,20 do tick(.1) end")
                report = validate(lines(lua), "0.1.93-dev")
                self.assertEqual(report["status"], "diagnostic-unavailable")
                self.assertEqual(report["sample_count"], 0)
                self.assertEqual(lua.eval("#messages"), 3)
                self.assertEqual(lua.eval("reads + writes"), 0)

    def test_compositor_snapshot_is_detached_and_reads_no_native_api(self):
        from test_doomrocket_animation_blend import runtime as blend_runtime
        lua = blend_runtime()
        lua.execute("assert(mod._start_warlock_animation_blend(owner,outfit,profile));before=calls.native;"
                    "view=mod._warlock_animation_blend_snapshot(owner);view.status='changed';view.frame=999;"
                    "fresh=mod._warlock_animation_blend_snapshot(owner)")
        self.assertEqual(lua.eval("calls.native"), lua.eval("before"))
        self.assertEqual(lua.eval("fresh.status"), "ready")
        self.assertEqual(lua.eval("fresh.frame"), 0)
        self.assertIsNone(lua.eval("fresh.profile"))

    def test_stopping_and_world_release_invalidate_queued_closures(self):
        for operation in ("action('off')", "mod._release_warlock_animation_probe_world(world)",
                          "mod._reset_warlock_animation_probe('mod_disabled')"):
            with self.subTest(operation=operation):
                lua = runtime()
                lua.execute("marker='custom';action('on');mod._queue_warlock_animation_probe(world,.1);" + operation +
                            ";owner.alive=false;outfit.alive=false;helper.alive=false;for _,fn in ipairs(callbacks) do fn() end")
                report = validate(lines(lua), "0.1.93-dev")
                self.assertEqual(report["sample_count"], 0)
                self.assertEqual(lua.eval("reads + writes"), 0)

    def test_hot_reload_closes_prior_session_and_stays_off(self):
        lua = runtime()
        lua.execute("action('on');tick(.1)")
        lua.execute(MODULE.read_text(encoding="utf-8"))
        lua.execute("tick(.1)")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["completion_reason"], "reload")
        self.assertEqual(report["sample_count"], 1)

    def test_budget_rate_and_invalid_dt_bound_output(self):
        lua = runtime()
        lua.execute("action('on');tick(0);tick(-1);tick(0/0);tick(.5);for i=1,2000 do tick(.05) end")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertLessEqual(report["sample_count"], 120)
        self.assertIn(report["completion_reason"], ("time_limit", "sample_limit"))

    def test_finite_hitch_is_observed_but_cap_hitch_stops_without_extra_pose_reads(self):
        lua = runtime()
        lua.execute("marker='custom';action('on');tick(.5);action('off')")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["sample_count"], 1)
        sample = json.loads(lines(lua)[1].split('[doomrocket:ANIMATION]', 1)[1])
        self.assertEqual(sample['animation_dt'], .5)
        lua = runtime()
        lua.execute("marker='custom';action('on');tick(50)")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["completion_reason"], "time_limit")
        self.assertEqual(lua.eval('reads + writes'), 0)

    def test_waits_for_outfit_and_declares_animation_time_scope(self):
        lua = runtime()
        lua.execute("mod._warlock_outfits={};action('on');for i=1,1000 do tick(.1) end;action('off')")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["sample_count"], 0)
        self.assertEqual(lua.eval('#messages'), 2)

    def test_session_selects_at_most_two_units_and_replaced_outfit_cancels(self):
        lua = runtime()
        lua.execute("mod._warlock_animation_blend_snapshot=function() return {status='off'} end;"
                    "for i=1,8 do local u={alive=true,world=world};local o={alive=true,world=world};"
                    "mod._warlock_outfits[u]=o;HEALTH_ALIVE[u]=true end;action('on');"
                    "tick(.1);tick(.25);action('off')")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["unit_count"], 2)
        lua = runtime()
        lua.execute("action('on');tick(.1);mod._warlock_outfits[owner]={alive=true,world=world};tick(.25)")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["status"], "diagnostic-unavailable")

    def test_sequential_spawns_cannot_replace_two_reserved_unit_slots(self):
        lua = runtime()
        lua.execute("mod._warlock_animation_blend_snapshot=function() return {status='off'} end;"
                    "owner2={alive=true,world=world};outfit2={alive=true,world=world};"
                    "mod._warlock_outfits[owner2]=outfit2;HEALTH_ALIVE[owner2]=true;action('on');tick(.1);"
                    "owner.alive=false;outfit.alive=false;owner2.alive=false;outfit2.alive=false;"
                    "mod._warlock_outfits={};local third={alive=true,world=world};"
                    "mod._warlock_outfits[third]={alive=true,world=world};HEALTH_ALIVE[third]=true;"
                    "tick(.25);action('off')")
        report = validate(lines(lua), "0.1.93-dev")
        self.assertEqual(report["unit_count"], 2)
        self.assertEqual(report["sample_count"], 2)


class AnimationProbeIntegration(unittest.TestCase):
    def test_both_world_dispatch_methods_queue_probe_after_all_presentation_callbacks(self):
        from test_doomrocket_animation_callbacks import runtime as callback_runtime
        for method in ('update_animations', 'update_animations_with_callback'):
            with self.subTest(method=method):
                lua = callback_runtime()
                lua.execute('''
                mod._queue_warlock_grip_alignment=function(w,dt)
                 callbacks[#callbacks+1]=function() w.grip_done=true end
                end
                mod._queue_warlock_weapon_pose_probe=function(w,dt)
                 callbacks[#callbacks+1]=function() w.weapon_done=true end
                end
                mod._queue_warlock_animation_probe=function(w,dt)
                 assert(#callbacks==3,'probe queued before grip/hose/weapon presentation')
                 callbacks[#callbacks+1]=function()
                  assert(w.grip_done and w.weapon_done,'probe observed stale presentation')
                  assert(events[#events]=='hose_pose:game','probe ran before hose presentation')
                  w.probe_done=true
                 end
                end
                ''')
                lua.globals().method = method
                lua.execute("values=pack(World[method](world,.5));drain_and_update_scene(world);"
                            "assert(world.probe_done and values.n==5 and values[4]==47)")

    def test_bootstrap_loads_probe_after_compositor_and_reset_stops_it_first(self):
        source = BOOTSTRAP.read_text(encoding='utf-8')
        self.assertLess(source.index('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_blend")'),
                        source.index('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_probe")'))
        start = source.index('local function reset_warlock_runtime_state(')
        end = source.index('\nfunction mod.on_game_state_changed', start)
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''events={};mod=setmetatable({},{__index=function(_,key)
         return function(...) events[#events+1]=key end
        end})''')
        lua.execute(source[start:end] + '\nreset_warlock_runtime_state("mod_unload",true)')
        self.assertEqual(lua.eval('events[1]'), '_reset_warlock_animation_probe')
        self.assertGreater(lua.eval('#events'), 5)

    def test_world_release_stops_diagnostic_before_controllers_and_engine(self):
        source = HOOKS.read_text(encoding='utf-8')
        start = source.index('mod:hook(Application, "release_world",')
        end = source.index('\n-- these functions', start)
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''events={};Application={};world={};mod=setmetatable({},{__index=function(_,key)
         return function(...) events[#events+1]=key end
        end})
        function mod:hook(obj,name,fn) assert(obj==Application and name=='release_world');release=fn end''')
        lua.execute(source[start:end])
        lua.execute('release(function(w) assert(w==world);events[#events+1]="native_release" end,world)')
        self.assertEqual(lua.eval('events[1]'), '_release_warlock_animation_probe_world')
        self.assertEqual(lua.eval('events[#events-1]'), 'native_release')


class AnimationProbeParser(unittest.TestCase):
    def fixture(self):
        lua = runtime()
        lua.execute("marker='custom';action('on');tick(.1);action('off')")
        return [json.loads(line.split("[doomrocket:ANIMATION]", 1)[1]) for line in lines(lua)]

    def encode(self, records):
        return ["log [doomrocket:ANIMATION] " + json.dumps(record) for record in records]

    def test_finite_native_sentinel_and_unsupported_clip_lengths_are_rejected(self):
        for clock, length in (("helper_clock", "helper_length"), ("visible_clock", "visible_length")):
            for value in (3600.001, 1e37):
                with self.subTest(length=length, value=value):
                    candidate = self.fixture()
                    candidate[1][clock], candidate[1][length] = 0, value
                    with self.assertRaisesRegex(ValueError, "Invalid native clock"):
                        validate(self.encode(candidate), "0.1.93-dev")

    def test_truncation_duplicate_indices_keys_and_nonfinite_rejected(self):
        original = self.fixture()
        invalid = [self.encode(original[:-1]), self.encode(original)[:-1] + ['[doomrocket:ANIMATION] {"schema":1'],
                   ['[doomrocket:ANIMATION] {"schema":1,"schema":1}']]
        duplicate = copy.deepcopy(original)
        duplicate.insert(2, copy.deepcopy(duplicate[1]))
        duplicate[-1]["sample_count"] = 2
        invalid.append(self.encode(duplicate))
        for number in (float('nan'), float('inf'), -float('inf')):
            candidate = copy.deepcopy(original)
            candidate[1]["helper_clock"] = number
            invalid.append(self.encode(candidate))
        for candidate in invalid:
            with self.subTest(candidate=candidate[-1][:100]):
                with self.assertRaises(ValueError):
                    validate(candidate, "0.1.93-dev")

    def test_schema_version_bone_scope_and_counter_mutations_rejected(self):
        for index, key, value in ((1, "schema", 2), (1, "version", "0.1.92-dev"),
                                  (1, "native_fixed_frame_oracle", True), (1, "sample_index", False),
                                  (1, "unit_id", True), (1, "unit_id", 3), (2, "sample_count", 0), (1, "phase", "pass")):
            candidate = self.fixture()
            candidate[index][key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate(self.encode(candidate), "0.1.93-dev")
        candidate = self.fixture()
        candidate[1]["bones_local"].pop(BONES[0])
        with self.assertRaises(ValueError):
            validate(self.encode(candidate), "0.1.93-dev")

    def test_missing_profile_cannot_be_relabelled_native(self):
        candidate = self.fixture()
        candidate[1]["profile_status"] = "no_custom_profile"
        with self.assertRaises(ValueError):
            validate(self.encode(candidate), "0.1.93-dev")

    def test_multiple_sessions_require_explicit_selection(self):
        records = self.fixture()
        second = copy.deepcopy(records)
        for record in second:
            record["session"] = 2
        with self.assertRaises(ValueError):
            validate(self.encode(records + second), "0.1.93-dev")
        self.assertEqual(validate(self.encode(records + second), "0.1.93-dev", 2)["session"], 2)

    def test_empty_capture_is_not_an_absent_profile_verdict(self):
        lua = runtime()
        lua.execute("action('on');action('off')")
        self.assertEqual(validate(lines(lua), "0.1.93-dev")["status"], "no-animation-samples-recorded")


if __name__ == "__main__":
    unittest.main()
