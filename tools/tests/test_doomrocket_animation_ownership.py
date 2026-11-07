"""Execute authored/legacy pose ownership with strict Lua 5.1 lifetime doubles.

The production module owns the decision; the tests supply an independent graph
and assert which downstream writers are allowed. No rendered game acceptance
or animation-event timing beyond the declared blend durations is claimed.
"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime
import test_doomrocket_locomotion_animation as locomotion
import test_doomrocket_visible_aim as visible_aim
import test_doomrocket_authored_weapon as authored_weapon

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_animation_ownership.lua"
HOOKS = ROOT / "scripts/mods/doomrocket/utils/hooks.lua"

HARNESS = r'''
world={alive=true}; other_world={alive=true}
unit_name='units/warlock_bombardier/warlock_bombardier_3p'
manifest_id=string.rep('a',64)
calls={native=0}
function make_unit(name,w)
 return {alive=true,name=name,world=w or world,data={}}
end
owner=make_unit('carrier');outfit=make_unit(unit_name)
mod={_warlock_outfits={[owner]=outfit}}
HEALTH_ALIVE={[owner]=true}
function get_mod(name) assert(name=='doomrocket');return mod end
local function live(u)
 assert(u and u.alive,'native access after unit deletion')
 assert(u.world and u.world.alive,'native access after world release')
 calls.native=calls.native+1
end
Unit={
 alive=function(u) return u and u.alive or false end,
 world=function(u) live(u);return u.world end,
 get_data=function(u,key)
  live(u);assert(not (u.read_errors and u.read_errors[key]),'unreadable unit metadata')
  return key=='unit_name' and u.name or u.data[key]
 end,
 set_local_position=function() error('ownership must not write animation tracks') end,
 set_local_rotation=function() error('ownership must not write animation tracks') end,
 set_local_scale=function() error('ownership must not write animation tracks') end,
 set_animation_state_machine=function() error('ownership must not replace the controller') end,
}
profile={unit=unit_name,manifest_id=manifest_id,accessory_skin='localized-v1',
 default_state='base/idle',max_blend_time=.25,auxiliary_events={sound=true},states={}}
profile.states['base/idle']={clip='original/idle',owner='legacy',speed='measured',visible_aim=true,
 transitions={custom={to='base/custom',blend_time=.25},idle={to='base/idle',blend_time=.05},
  death={to='base/death',blend_time=.25},fixed_speed={to='base/fixed_speed',blend_time=.25}}}
profile.states['base/custom']={clip='authored/custom',owner='authored',speed='authored',visible_aim=false,
 transitions={idle={to='base/idle',blend_time=.25},custom={to='base/custom',blend_time=.25},
  custom_gait={to='base/custom_gait',blend_time=.25},death={to='base/death',blend_time=.25}}}
profile.states['base/custom_gait']={clip='authored/gait',owner='authored',speed='measured',visible_aim=false,
 transitions={idle={to='base/idle',blend_time=.25},custom={to='base/custom',blend_time=.25}}}
profile.states['base/fixed_speed']={clip='original/fixed',owner='legacy',speed='authored',visible_aim=true,
 transitions={idle={to='base/idle',blend_time=.25}}}
profile.states['base/death']={clip='original/death',owner='legacy',speed='authored',visible_aim=false,
 transitions={}}
mod._warlock_animation_manifest={schema=1,profiles={candidate=profile}}
function mark()
 outfit.data.warlock_rig_profile='candidate'
 outfit.data.warlock_animation_manifest_id=manifest_id
end
function start()
 mark();return mod._start_warlock_animation_ownership(owner,outfit)
end
function query() return mod._warlock_animation_ownership(owner,outfit) end
function note(event,mirrored)
 if mirrored==nil then mirrored=true end
 mod._note_warlock_animation_ownership_event(owner,event,mirrored)
end
function tick(dt,w) mod._update_warlock_animation_ownership(w or world,dt) end
function mode(expected)
 local o=query()
 assert(o.upper_body==expected,'upper body: '..tostring(o.upper_body)..' instead of '..expected)
 assert(o.weapon==expected,'weapon: '..tostring(o.weapon)..' instead of '..expected)
 return o
end
'''

CUT_PROFILE = r'''
profile.cross_owner_transition_policy='cut'
profile.states['base/idle'].transitions.custom.blend_time=0
profile.states['base/custom'].transitions.idle.blend_time=0
profile.states['base/custom'].transitions.death.blend_time=0
profile.states['base/custom_gait'].transitions.idle.blend_time=0
'''

SNAPSHOT_PROFILE = r'''
profile.cross_owner_transition_policy='snapshot-blend-v1'
profile.sampler_state_machine=unit_name..'/presentation_sampler'
profile.bone_names={}
for i=1,138 do profile.bone_names[i]='bone_'..i end
for _,state in pairs(profile.states) do state.loop_animation=true end
blend={active=false,start=true,ack=true,starts=0,notes=0,stops=0,resets=0,releases=0}
mod._start_warlock_animation_blend=function(o,u,p)
 assert(o==owner and u==outfit and p==profile)
 blend.starts=blend.starts+1;return blend.start
end
mod._note_warlock_animation_blend_event=function(o,event,from,to,duration)
 assert(o==owner and profile.states[from].transitions[event].to==to)
 assert(profile.states[from].transitions[event].blend_time==duration)
 -- The helper acknowledges before the owner advances its state.
 if HEALTH_ALIVE[owner]==true then assert(query().state==from) end
 blend.notes=blend.notes+1;return blend.ack
end
mod._warlock_animation_blend_active=function(o) assert(o==owner);return blend.active end
mod._stop_warlock_animation_blend=function(o) blend.stops=blend.stops+1;blend.active=false end
mod._reset_warlock_animation_blend=function() blend.resets=blend.resets+1;blend.active=false end
mod._release_warlock_animation_blend_world=function(w) assert(w==world);blend.releases=blend.releases+1;blend.active=false end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


def add_ownership(lua):
    """Load the real owner into the existing independent consumer scene."""
    lua.execute(r'''
      unit_name='units/warlock_bombardier/warlock_bombardier_3p'
      manifest_id=string.rep('a',64)
      world=world or {};owner.world=owner.world or world;outfit.world=outfit.world or world
      outfit.data={}
      local original_get_data=Unit.get_data
      Unit.get_data=function(u,key)
       assert(u and u.alive,'metadata read after deletion')
       if key=='unit_name' then
        if original_get_data then return original_get_data(u,key) end
        return u.kind=='outfit' and unit_name or 'carrier'
       end
       return u.data and u.data[key]
      end
      Unit.world=Unit.world or function(u)
       assert(u and u.alive,'world read after deletion');return u.world
      end
    ''')
    fixture = HARNESS[HARNESS.index("profile="):HARNESS.index("function query()")]
    lua.execute(fixture)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


class AnimationOwnershipTests(unittest.TestCase):
    def test_unmarked_shipping_unit_retains_existing_legacy_behavior(self):
        lua = runtime()
        lua.execute('''
          assert(not mod._start_warlock_animation_ownership(owner,outfit))
          local o=mode('legacy')
          assert(o.accessories=='unsupported' and o.speed=='measured' and o.visible_aim)
          note('custom');tick(.25);mode('legacy')
        ''')

    def test_valid_legacy_profile_controls_only_approved_correction_channels(self):
        lua = runtime()
        lua.execute('''
          assert(start());local o=mode('legacy')
          assert(o.accessories=='legacy-pelvis' and o.visible_aim and o.speed=='measured')
          assert(o.profile==profile and o.profile_id=='candidate' and o.state=='base/idle')
          assert(o.clip=='original/idle' and not o.transitioning)
          assert(mod._warlock_animation_channel_ownership(owner,outfit).upper_body=='legacy')
        ''')

    def test_stock_snapshot_profile_keeps_custom_ownership_without_localized_skin(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE)
        lua.execute('''
          profile.accessory_skin=nil;assert(start())
          local o=mode('legacy');assert(o.accessories=='unsupported' and blend.starts==1)
          note('custom');o=mode('authored')
          assert(o.accessories=='authored' and o.speed=='authored' and not o.visible_aim)
          blend.active=true;note('idle');o=mode('authored')
          assert(o.transitioning and o.accessories=='authored')
          blend.active=false;o=mode('legacy')
          assert(not o.transitioning and o.accessories=='unsupported' and o.visible_aim)
        ''')

    def test_unknown_accessory_profile_fails_before_compositor_registration(self):
        for value in ("'unknown'", "false", "true", "7", "{}"):
            with self.subTest(value=value):
                lua = runtime()
                lua.execute(SNAPSHOT_PROFILE)
                lua.execute("profile.accessory_skin=" + value)
                lua.execute("assert(not start());mode('unsupported');assert(blend.starts==0)")

    def test_authored_entry_is_protected_before_any_animation_update(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');local o=mode('authored')
          assert(o.state=='base/custom' and o.clip=='authored/custom')
          assert(o.accessories=='authored' and o.speed=='authored' and not o.visible_aim)
          tick(.25);mode('authored')
        ''')

    def test_authored_default_is_protected_without_receiving_an_event(self):
        lua = runtime()
        lua.execute('''
          profile.default_state='base/custom';assert(start())
          local o=mode('authored');assert(o.state=='base/custom' and not o.visible_aim)
        ''')

    def test_outgoing_custom_blend_remains_protected_for_entire_duration(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle')
          local o=mode('authored');assert(o.transitioning and o.state=='base/idle')
          tick(.125);mode('authored');tick(.124999);mode('authored')
          tick(.0000011);o=mode('legacy')
          assert(not o.transitioning and o.accessories=='legacy-pelvis' and o.visible_aim)
        ''')

    def test_exact_full_blend_tick_does_not_delay_legacy_by_an_extra_frame(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle');tick(.25)
          local o=mode('legacy');assert(not o.transitioning)
          tick(.01);mode('legacy')
        ''')

    def test_repeated_short_transition_cannot_shorten_an_existing_outgoing_blend(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle');tick(.1)
          note('idle');tick(.05);mode('authored');tick(.199999);mode('authored')
          tick(.0000011);mode('legacy')
        ''')

    def test_reentry_to_custom_cancels_legacy_release(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle');tick(.2)
          note('custom');tick(.25);local o=mode('authored')
          assert(o.state=='base/custom' and not o.transitioning)
        ''')

    def test_auxiliary_unknown_and_unmirrored_events_cannot_relinquish_authored_state(self):
        for event, mirrored in (("sound", True), ("unknown", True), ("idle", False)):
            with self.subTest(event=event, mirrored=mirrored):
                lua = runtime()
                lua.execute("assert(start());note('custom')")
                lua.globals().note(event, mirrored)
                lua.execute("tick(.25);assert(mode('authored').state=='base/custom')")

    def test_auxiliary_and_unmapped_events_preserve_existing_outgoing_protection(self):
        for event, mirrored in (("sound", True), ("unknown", True), ("idle", False)):
            with self.subTest(event=event, mirrored=mirrored):
                lua = runtime()
                lua.execute("assert(start());note('custom');note('idle');tick(.1)")
                lua.globals().note(event, mirrored)
                lua.execute("tick(.149999);mode('authored')")

    def test_unknown_delivered_event_latches_outgoing_authored_ownership(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle');tick(.1);note('unknown')
          for i=1,8 do tick(.25);mode('authored') end
          note('idle');tick(.249999);mode('authored');tick(.0000011);mode('legacy')
        ''')

    def test_auxiliary_event_does_not_extend_the_declared_blend(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle');tick(.1);note('sound')
          tick(.15);mode('legacy')
        ''')

    def test_unmapped_legacy_event_blocks_writes_until_a_declared_transition(self):
        for mirrored in (True, False):
            with self.subTest(mirrored=mirrored):
                lua = runtime()
                lua.execute("assert(start())")
                lua.globals().note("unknown", mirrored)
                lua.execute('''
                  local o=mode('unsupported')
                  assert(o.accessories=='unsupported' and o.speed=='unsupported' and not o.visible_aim)
                  tick(.25);mode('unsupported');note('custom');mode('authored')
                ''')

    def test_declared_auxiliary_event_retains_legacy_state(self):
        lua = runtime()
        lua.execute("assert(start());note('sound');assert(mode('legacy').state=='base/idle')")

    def test_speed_is_independently_owned_by_the_declared_state(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('custom_gait')
          local o=mode('authored');assert(o.speed=='measured' and not o.visible_aim)
          note('idle');tick(.25);note('fixed_speed')
          o=mode('legacy');assert(o.speed=='authored' and o.visible_aim)
        ''')

    def test_outgoing_blend_does_not_reenable_measured_speed_or_visible_aim_early(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('idle');tick(.249999)
          local o=mode('authored');assert(o.speed=='authored' and not o.visible_aim)
        ''')

    def test_authored_measured_gait_retains_its_speed_policy_during_outgoing_blend(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');note('custom_gait');note('idle');tick(.249999)
          local o=mode('authored');assert(o.speed=='measured' and not o.visible_aim)
          tick(.0000011);mode('legacy')
        ''')

    def test_gameplay_aim_requires_explicit_opt_in_for_authored_state(self):
        lua = runtime()
        lua.execute('''
          profile.states['base/custom'].visible_aim=true
          profile.states['base/custom'].aim_policy='gameplay'
          assert(start());note('custom');local o=mode('authored');assert(o.visible_aim)
          note('idle');tick(.249999);assert(mode('authored').visible_aim)
        ''')

    def test_previous_gameplay_aim_cannot_leak_into_a_new_authored_state(self):
        lua = runtime()
        lua.execute('''
          profile.states['base/custom'].visible_aim=true
          profile.states['base/custom'].aim_policy='gameplay'
          assert(start());note('custom');note('idle');tick(.1)
          assert(mode('authored').visible_aim)
          note('custom');note('custom_gait')
          local o=mode('authored');assert(not o.visible_aim)
          note('idle');tick(.249999);assert(not mode('authored').visible_aim)
        ''')

    def test_paused_invalid_and_unrelated_world_updates_cannot_consume_blend_time(self):
        for dt in (0, -1, 0.250001, float("inf"), float("nan")):
            with self.subTest(dt=dt):
                lua = runtime()
                lua.execute("assert(start());note('custom');note('idle')")
                for _ in range(3):
                    lua.globals().tick(dt)
                lua.execute("tick(.125,other_world);tick(.249999);mode('authored')")
        for expression in ("nil", "'0.25'", "false", "{}"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute("assert(start());note('custom');note('idle');tick(" + expression + ")")
                lua.execute("tick(.249999);mode('authored')")

    def test_validated_profile_and_manifest_id_are_required_for_marked_units(self):
        mutations = (
            "mod._warlock_animation_manifest=nil",
            "mod._warlock_animation_manifest=true",
            "mod._warlock_animation_manifest=17",
            "mod._warlock_animation_manifest='invalid'",
            "mod._warlock_animation_manifest.schema=2",
            "mod._warlock_animation_manifest.profiles=false",
            "outfit.data.warlock_rig_profile='missing'",
            "outfit.data.warlock_animation_manifest_id=nil",
            "outfit.data.warlock_animation_manifest_id=string.rep('b',64)",
            "profile.unit='other/unit'",
            "profile.manifest_id=string.rep('A',64)",
            "profile.manifest_id='short'",
            "profile.default_state='missing'",
            "profile.auxiliary_events=true",
            "profile.auxiliary_events=17",
            "profile.auxiliary_events='invalid'",
            "profile.max_blend_time=-1",
            "profile.max_blend_time=math.huge",
            "profile.max_blend_time=1.001",
            "profile.states['base/custom'].owner='unknown'",
            "profile.states['base/custom'].speed='unknown'",
            "profile.states['base/custom'].visible_aim=true",
            "profile.states['base/custom'].transitions.idle.to='missing'",
            "profile.states['base/custom'].transitions.idle.blend_time=0/0",
            "profile.states['base/custom'].transitions.idle.blend_time=.250001",
            "profile.states['base/custom'].transitions.idle.blend_time=-.1",
            "profile.states['base/death'].owner='authored'",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("mark();" + mutation)
                lua.execute('''
                  assert(not mod._start_warlock_animation_ownership(owner,outfit))
                  local o=mode('unsupported')
                  assert(o.accessories=='unsupported' and o.speed=='unsupported' and not o.visible_aim)
                  note('custom');tick(.25);mode('unsupported')
                ''')

    def test_absent_entry_for_a_marked_unit_fails_closed_before_and_after_reset(self):
        for cleanup in ("", "mod._reset_warlock_animation_ownership()", "mod._stop_warlock_animation_ownership(owner)"):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute("mark();" + (cleanup + ";" if cleanup else "") + "mode('unsupported')")
                lua.execute("assert(start());note('custom');" + (cleanup or "mod._reset_warlock_animation_ownership()"))
                lua.execute("mode('unsupported')")

    def test_unreadable_marker_cannot_be_mistaken_for_an_unmarked_unit(self):
        for phase in ("before_start", "after_reset"):
            with self.subTest(phase=phase):
                lua = runtime()
                lua.execute("mark()")
                if phase == "after_reset":
                    lua.execute("assert(start());note('custom');mod._reset_warlock_animation_ownership()")
                lua.execute('''
                  outfit.read_errors={warlock_rig_profile=true}
                  mode('unsupported')
                  assert(not mod._start_warlock_animation_ownership(owner,outfit))
                  note('custom');tick(.25);mode('unsupported')
                ''')

    def test_bad_initial_handles_and_registration_return_false_without_native_access(self):
        for mutation, call in (
            ("", "nil,outfit"), ("", "owner,nil"),
            ("owner.alive=false", "owner,outfit"),
            ("outfit.alive=false", "owner,outfit"),
            ("HEALTH_ALIVE[owner]=false", "owner,outfit"),
            ("mod._warlock_outfits[owner]=nil", "owner,outfit"),
        ):
            with self.subTest(mutation=mutation, call=call):
                lua = runtime()
                lua.execute("mark();" + mutation)
                lua.execute("assert(not mod._start_warlock_animation_ownership(" + call + "));assert(calls.native==0)")

    def test_stale_registration_world_and_health_are_never_legacy_fallbacks(self):
        mutations = (
            "owner.alive=false", "outfit.alive=false", "HEALTH_ALIVE[owner]=nil",
            "mod._warlock_outfits[owner]=nil",
            "mod._warlock_outfits[owner]=make_unit(unit_name)",
            "owner.world=other_world", "outfit.world=other_world",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute("assert(start());note('custom');" + mutation)
                lua.execute("mode('unsupported');note('idle');tick(.25);mode('unsupported')")

    def test_query_with_a_replaced_outfit_does_not_reuse_previous_ownership(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom');local other=make_unit(unit_name)
          assert(mod._warlock_animation_ownership(owner,other).upper_body=='unsupported')
          mode('authored')
        ''')

    def test_world_release_is_isolated_and_cancels_ownership_lifetime(self):
        lua = runtime()
        lua.execute('''
          assert(start());note('custom')
          mod._release_warlock_animation_ownership_world(other_world);mode('authored')
          mod._release_warlock_animation_ownership_world(world)
          world.alive=false;owner.alive=false;outfit.alive=false
          local native=calls.native
          note('idle');tick(.25);mode('unsupported');assert(calls.native==native)
        ''')


class AnimationOwnershipStartupTests(unittest.TestCase):
    def test_inventory_before_health_retains_early_custom_event_without_enabling_writers(self):
        lua = runtime()
        lua.execute('''
          HEALTH_ALIVE[owner]=nil;assert(start())
          local o=mode('unsupported')
          assert(o.accessories=='unsupported' and o.speed=='unsupported' and not o.visible_aim)
          note('custom');tick(.25);tick(.25)
          o=mode('unsupported');assert(o.speed=='unsupported' and not o.visible_aim)
          HEALTH_ALIVE[owner]=true;o=mode('authored')
          assert(o.state=='base/custom' and o.clip=='authored/custom'
           and o.accessories=='authored' and o.speed=='authored' and not o.visible_aim)
        ''')

    def test_actual_setup_and_direct_dispatch_preserve_initial_idle_before_health(self):
        source = HOOKS.read_text(encoding="utf-8")
        dispatch_start = source.index('\nmod:hook(Unit, "animation_event", function(func, unit, event, ...)') + 1
        dispatch_end = source.index('-- NO raw-index animation mirroring.', dispatch_start)
        setup_start = source.index('mod._warlock_outfits[unit] = outfit_unit',
                                   source.index('mod:hook(AIInventoryExtension, "_setup_configuration"'))
        setup_end = source.index('mod._start_warlock_locomotion_animation(unit, outfit_unit)', setup_start)
        lua = runtime()
        lua.execute(CUT_PROFILE + r'''
          profile.default_state='base/custom';mark();HEALTH_ALIVE[owner]=nil
          mod._warlock_outfit_owners={}
          function mod._start_warlock_outfit_correction(unit,visible)
           assert(unit==owner and visible==outfit);mode('unsupported')
          end
          function mod._note_warlock_weapon_pose_event() end
          function mod._note_warlock_grip_alignment_event() end
          function unit_get_data(u,key) assert(key=='breed');return u.breed end
          function has_animation_event(u,event)
           assert(u.alive and event=='idle');return true
          end
          Unit.has_animation_event=has_animation_event
          function mod:hook(object,name,handler)
           assert(object==Unit and name=='animation_event')
           Unit.animation_event=function(...)
            return handler(function(u,event)
             assert(u==outfit and event=='idle');mode('unsupported')
             setup_idle_dispatches=(setup_idle_dispatches or 0)+1
            end,...)
           end
          end
        ''')
        lua.execute(source[dispatch_start:dispatch_end])
        lua.execute("function inventory_setup_initial_animation(unit,outfit_unit)\n" +
                    source[setup_start:setup_end] + "\nend")
        lua.execute('''
          inventory_setup_initial_animation(owner,outfit)
          assert(setup_idle_dispatches==1 and mod._warlock_outfit_owners[outfit]==owner)
          mode('unsupported');tick(.25);HEALTH_ALIVE[owner]=true
          local o=mode('legacy');assert(o.state=='base/idle' and o.clip=='original/idle')
        ''')

    def test_pending_outgoing_guard_does_not_consume_blend_time(self):
        lua = runtime()
        lua.execute('''
          HEALTH_ALIVE[owner]=nil;assert(start());note('custom');note('idle')
          for i=1,4 do tick(.25);mode('unsupported') end
          HEALTH_ALIVE[owner]=true
          local o=mode('authored');assert(o.state=='base/idle' and o.transitioning)
          tick(.249999);mode('authored');tick(.0000011);mode('legacy')
        ''')

    def test_missing_global_health_cache_is_an_initial_read_only_interval(self):
        lua = runtime()
        lua.execute('''
          HEALTH_ALIVE=nil;assert(start());note('custom');tick(.25)
          mode('unsupported');HEALTH_ALIVE={[owner]=true}
          assert(mode('authored').state=='base/custom')
        ''')

    def test_each_first_healthy_observer_permanently_closes_startup_permission(self):
        operations = ("query()", "note('idle')", "tick(.01)")
        for first_observation in operations:
            for loss_observation in operations:
                with self.subTest(first=first_observation, loss=loss_observation):
                    lua = runtime()
                    lua.execute("HEALTH_ALIVE[owner]=nil;assert(start());HEALTH_ALIVE[owner]=true;" +
                                first_observation + ";HEALTH_ALIVE[owner]=nil;" + loss_observation)
                    lua.execute('''
                      HEALTH_ALIVE[owner]=true;mode('unsupported')
                      note('custom');tick(.25);mode('unsupported')
                    ''')

    def test_explicit_false_during_pending_registration_invalidates_every_observer(self):
        for observation in ("query()", "note('custom')", "tick(.01)"):
            with self.subTest(observation=observation):
                lua = runtime()
                lua.execute("HEALTH_ALIVE[owner]=nil;assert(start());HEALTH_ALIVE[owner]=false;" + observation)
                lua.execute("HEALTH_ALIVE[owner]=true;mode('unsupported');note('custom');mode('unsupported')")

    def test_health_loss_after_activation_does_not_reopen_pending_events(self):
        for inactive in ("nil", "false"):
            lua = runtime()
            lua.execute("HEALTH_ALIVE[owner]=nil;assert(start());note('custom');HEALTH_ALIVE[owner]=true")
            lua.execute("mode('authored');HEALTH_ALIVE[owner]=" + inactive + ";note('idle')")
            lua.execute("HEALTH_ALIVE[owner]=true;mode('unsupported')")

    def test_invalid_bindings_are_permanently_removed_by_all_observers(self):
        mutations = (
            ("owner.alive=false", "owner.alive=true"),
            ("outfit.alive=false", "outfit.alive=true"),
            ("mod._warlock_outfits[owner]=nil", "mod._warlock_outfits[owner]=outfit"),
            ("mod._warlock_outfits[owner]=make_unit(unit_name)", "mod._warlock_outfits[owner]=outfit"),
            ("owner.world=other_world", "owner.world=world"),
            ("outfit.world=other_world", "outfit.world=world"),
        )
        for initial_health in ("nil", "true"):
            for mutation, restore in mutations:
                for observation in ("query()", "note('idle')", "tick(.01)"):
                    with self.subTest(initial_health=initial_health, mutation=mutation, observation=observation):
                        lua = runtime()
                        lua.execute("HEALTH_ALIVE[owner]=" + initial_health + ";assert(start());note('custom');" +
                                    mutation + ";" + observation + ";" + restore)
                        lua.execute("HEALTH_ALIVE[owner]=true;mode('unsupported');note('custom');mode('unsupported')")

    def test_wrong_optional_outfit_does_not_cancel_the_pending_registered_outfit(self):
        lua = runtime()
        lua.execute('''
          HEALTH_ALIVE[owner]=nil;assert(start());note('custom')
          local other=make_unit(unit_name)
          assert(mod._warlock_animation_ownership(owner,other).upper_body=='unsupported')
          HEALTH_ALIVE[owner]=true;assert(mode('authored').state=='base/custom')
        ''')

    def test_pending_lifetime_cleanup_prevents_later_activation(self):
        for cleanup in ("mod._stop_warlock_animation_ownership(owner)",
                        "mod._reset_warlock_animation_ownership()",
                        "mod._release_warlock_animation_ownership_world(world)"):
            with self.subTest(cleanup=cleanup):
                lua = runtime()
                lua.execute("HEALTH_ALIVE[owner]=nil;assert(start());note('custom');" + cleanup)
                lua.execute("HEALTH_ALIVE[owner]=true;mode('unsupported')")

    def test_pending_world_release_is_isolated_and_never_touches_released_handles(self):
        lua = runtime()
        lua.execute('''
          HEALTH_ALIVE[owner]=nil;assert(start());note('custom')
          mod._release_warlock_animation_ownership_world(other_world)
          HEALTH_ALIVE[owner]=true;mode('authored')
          mod._release_warlock_animation_ownership_world(world)
          world.alive=false;owner.alive=false;outfit.alive=false
          local native=calls.native;note('idle');tick(.25);mode('unsupported')
          assert(calls.native==native)
        ''')


class AnimationOwnershipConsumerTests(unittest.TestCase):
    def test_real_locomotion_initialization_waits_for_health_and_retains_early_authored_speed(self):
        lua = add_ownership(locomotion.runtime())
        lua.execute('''
          HEALTH_ALIVE[owner]=nil;assert(start())
          assert(mod._start_warlock_locomotion_animation(owner,outfit))
          assert(events.finds==1 and events.writes==0)
          mod._note_warlock_animation_ownership_event(owner,'custom',true)
          HEALTH_ALIVE[owner]=true;advance(owner,.4,0,0,world,.1)
          assert(events.writes==0)
          mod._note_warlock_animation_ownership_event(owner,'custom_gait',true)
          advance(owner,.19,0,0,world,.1)
          assert(events.writes==1 and math.abs(outfit.speed-1.9)<1e-9)
        ''')

    def test_real_visible_aim_keeps_early_authored_state_without_pre_health_outfit_writes(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = add_ownership(visible_aim.runtime(lane))
                lua.execute(CUT_PROFILE + '''
                  HEALTH_ALIVE[owner]=nil;assert(start())
                  mod._note_warlock_animation_ownership_event(owner,'custom',true)
                  tick();assert(owner.writes==1 and outfit.writes==0 and outfit.finds==0)
                  HEALTH_ALIVE[owner]=true;tick()
                  assert(owner.writes==2 and outfit.writes==0 and outfit.finds==0)
                  mod._note_warlock_animation_ownership_event(owner,'idle',true);tick()
                  assert(owner.writes==3 and outfit.writes==1 and outfit.finds==1)
                ''')

    def test_real_grip_preserves_custom_body_pose_on_first_active_frame_after_early_event(self):
        lua = add_ownership(authored_weapon.runtime())
        lua.execute('''
          profile.weapon_links=semantic_links
          HEALTH_ALIVE[owner]=nil;assert(start())
          mod._note_warlock_animation_ownership_event(owner,'custom',true)
          assert(mod._warlock_animation_ownership(owner,outfit).weapon=='unsupported')
          HEALTH_ALIVE[owner]=true;tick();assert(not mod.last_error,mod.last_error)
          assert(calls.writes==0 and mod._warlock_grip_alignment_status(owner)=='authored')
          assert(weapon_gap()<1e-8)
        ''')

    def test_authored_speed_prevents_real_locomotion_variable_writes(self):
        lua = add_ownership(locomotion.runtime())
        lua.execute('''
          profile.default_state='base/custom';assert(start())
          assert(mod._start_warlock_locomotion_animation(owner,outfit))
          assert(events.finds==1 and events.writes==0)
          advance(owner,.4,0,0,world,.1)
          advance(owner,.4,0,0,world,0)
          advance(owner,.4,0,0,world,.1)
          assert(events.writes==0)
        ''')

    def test_explicit_measured_authored_gait_allows_real_cadence_updates(self):
        lua = add_ownership(locomotion.runtime())
        lua.execute('''
          profile.default_state='base/custom_gait';assert(start())
          assert(mod._start_warlock_locomotion_animation(owner,outfit))
          advance(owner,.19,0,0,world,.1)
          assert(events.writes==2 and math.abs(outfit.speed-1.9)<1e-9)
          assert(mod._warlock_animation_ownership(owner,outfit).upper_body=='authored')
        ''')

    def test_real_locomotion_respects_entry_blend_and_retains_recent_motion_baseline(self):
        lua = add_ownership(locomotion.runtime())
        lua.execute('''
          assert(start());assert(mod._start_warlock_locomotion_animation(owner,outfit))
          advance(owner,.4,0,0,world,.1);assert(events.writes==2 and outfit.speed==4)
          mod._note_warlock_animation_ownership_event(owner,'custom',true)
          advance(owner,.4,0,0,world,.1);assert(events.writes==2)
          mod._note_warlock_animation_ownership_event(owner,'idle',true)
          mod._update_warlock_animation_ownership(world,.249999)
          advance(owner,.4,0,0,world,.1);assert(events.writes==2)
          mod._update_warlock_animation_ownership(world,.0000011)
          advance(owner,.005,0,0,world,.005)
          assert(events.writes==3 and math.abs(outfit.speed-1)<1e-9)
        ''')

    def test_invalid_marked_profile_disables_real_locomotion_writes(self):
        lua = add_ownership(locomotion.runtime())
        lua.execute('''
          mark();outfit.data.warlock_animation_manifest_id='mismatch'
          assert(not mod._start_warlock_animation_ownership(owner,outfit))
          assert(mod._start_warlock_locomotion_animation(owner,outfit))
          advance(owner,.4,0,0,world,.1);assert(events.writes==0)
        ''')

    def test_strict_authored_aim_preserves_carrier_and_network_target(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = add_ownership(visible_aim.runtime(lane))
                lua.execute('''
                  profile.default_state='base/custom';assert(start())
                  local publish=GameSession.set_game_object_field
                  published_count=0
                  GameSession.set_game_object_field=function(...)
                   published_count=published_count+1;return publish(...)
                  end
                  BLACKBOARDS[owner].attack_pattern_data={
                   ballistic_aim_direction_box={unbox=function() return vec(0,4,3) end}}
                  tick();tick()
                  assert(owner.writes==2 and outfit.writes==0 and outfit.finds==0)
                  assert(data.visible_aim_outfit==nil and data.visible_aim_constraint==nil)
                ''')
                if lane == "owner":
                    lua.execute('''
                      assert(published_count==2 and published==owner.target)
                      assert(owner.target.x==10 and owner.target.y==24 and owner.target.z==33)
                    ''')
                else:
                    lua.execute("assert(published_count==0 and owner.target==replicated)")

    def test_explicit_gameplay_aim_uses_the_outfit_own_constraint(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = add_ownership(visible_aim.runtime(lane))
                lua.execute('''
                  profile.default_state='base/custom'
                  profile.states['base/custom'].visible_aim=true
                  profile.states['base/custom'].aim_policy='gameplay'
                  assert(start());tick();tick()
                  assert(owner.writes==2 and outfit.writes==2 and outfit.finds==1)
                  assert(outfit.target==owner.target and data.visible_aim_constraint==outfit.index)
                ''')

    def test_real_aim_clears_cached_outfit_and_respects_full_outgoing_blend(self):
        lua = add_ownership(visible_aim.runtime())
        lua.execute('''
          assert(start());tick();assert(outfit.writes==1)
          mod._note_warlock_animation_ownership_event(owner,'custom',true)
          tick();assert(outfit.writes==1 and owner.writes==2)
          assert(data.visible_aim_outfit==nil and data.visible_aim_constraint==nil)
          mod._note_warlock_animation_ownership_event(owner,'idle',true)
          mod._update_warlock_animation_ownership(world,.249999)
          tick();assert(outfit.writes==1 and owner.writes==3)
          mod._update_warlock_animation_ownership(world,.0000011)
          tick();assert(outfit.writes==2 and owner.writes==4 and outfit.finds==2)
        ''')

    def test_invalid_marked_profile_blocks_real_visual_aim_without_losing_ballistics(self):
        lua = add_ownership(visible_aim.runtime())
        lua.execute('''
          mark();outfit.data.warlock_animation_manifest_id='mismatch'
          assert(not mod._start_warlock_animation_ownership(owner,outfit))
          tick();assert(owner.writes==1 and outfit.writes==0 and outfit.finds==0)
          assert(published==owner.target)
        ''')


class AnimationOwnershipCutTests(unittest.TestCase):
    def test_verified_cross_owner_cuts_transfer_all_channels_immediately(self):
        lua = runtime()
        lua.execute(CUT_PROFILE + '''
          assert(start())
          for i=1,3 do
           note('custom');local o=mode('authored')
           assert(not o.transitioning and o.accessories=='authored'
            and o.speed=='authored' and not o.visible_aim)
           note('idle');o=mode('legacy')
           assert(not o.transitioning and o.accessories=='legacy-pelvis'
            and o.speed=='measured' and o.visible_aim)
          end
        ''')

    def test_cut_policy_preserves_same_owner_transitions_and_their_blend_settings(self):
        lua = runtime()
        lua.execute(CUT_PROFILE + '''
          assert(start());note('fixed_speed');local o=mode('legacy')
          assert(o.state=='base/fixed_speed' and o.speed=='authored')
          assert(profile.states['base/idle'].transitions.fixed_speed.blend_time==.25)
          note('idle');note('custom');note('custom_gait');o=mode('authored')
          assert(o.state=='base/custom_gait' and o.speed=='measured')
          assert(profile.states['base/custom'].transitions.custom_gait.blend_time==.25)
          tick(.25);mode('authored')
        ''')

    def test_every_cross_owner_edge_requires_zero_blend_before_activation(self):
        for state, event in (("base/idle", "custom"), ("base/custom", "idle"),
                             ("base/custom", "death"), ("base/custom_gait", "idle")):
            with self.subTest(state=state, event=event):
                lua = runtime()
                lua.execute(CUT_PROFILE)
                lua.execute("profile.states['" + state + "'].transitions['" + event + "'].blend_time=.01")
                lua.execute("assert(not start());mode('unsupported')")

    def test_unknown_policy_is_rejected_without_legacy_fallback(self):
        for expression in ("'blend'", "''", "true", "false", "0", "{}"):
            with self.subTest(expression=expression):
                lua = runtime()
                lua.execute(CUT_PROFILE + "profile.cross_owner_transition_policy=" + expression)
                lua.execute("assert(not start());note('custom');mode('unsupported')")

    def test_auxiliary_unknown_and_unmirrored_events_keep_conservative_protection(self):
        for event, mirrored in (("sound", True), ("unknown", True), ("idle", False)):
            with self.subTest(event=event, mirrored=mirrored):
                lua = runtime()
                lua.execute(CUT_PROFILE + "assert(start());note('custom')")
                lua.globals().note(event, mirrored)
                lua.execute("for i=1,4 do tick(.25);assert(mode('authored').state=='base/custom') end")

    def test_unknown_authored_latch_releases_only_on_an_observed_known_cut(self):
        lua = runtime()
        lua.execute(CUT_PROFILE + '''
          assert(start());note('custom');note('unknown')
          tick(.25);mode('authored');note('idle',false);tick(.25);mode('authored')
          note('sound');mode('authored');note('idle',true)
          local o=mode('legacy');assert(not o.transitioning and o.visible_aim)
        ''')

    def test_zero_blend_without_verified_cut_policy_keeps_existing_maximum_guard(self):
        lua = runtime()
        lua.execute('''
          profile.states['base/idle'].transitions.custom.blend_time=0
          profile.states['base/custom'].transitions.idle.blend_time=0
          assert(start());note('custom');note('idle');tick(.249999);mode('authored')
          tick(.0000011);mode('legacy')
        ''')

    def test_paused_and_unrelated_world_updates_cannot_invent_an_ownership_cut(self):
        lua = runtime()
        lua.execute(CUT_PROFILE + '''
          assert(start());note('custom')
          tick(0);tick(.25,other_world);tick(0/0);tick(-1)
          local o=mode('authored');assert(o.state=='base/custom' and not o.visible_aim)
          note('idle');o=mode('legacy');assert(o.state=='base/idle' and o.visible_aim)
        ''')

    def test_verified_cut_resumes_actual_gait_without_an_extra_blend_delay(self):
        lua = add_ownership(locomotion.runtime())
        lua.execute(CUT_PROFILE + '''
          profile.default_state='base/custom';assert(start())
          assert(mod._start_warlock_locomotion_animation(owner,outfit))
          advance(owner,.4,0,0,world,.1);assert(events.writes==0)
          mod._note_warlock_animation_ownership_event(owner,'idle',true)
          advance(owner,.2,0,0,world,.1)
          assert(events.writes==1 and math.abs(outfit.speed-2)<1e-9)
          mod._note_warlock_animation_ownership_event(owner,'custom',true)
          advance(owner,.4,0,0,world,.1);assert(events.writes==1)
        ''')

    def test_verified_cut_resumes_actual_visual_aim_on_the_next_evaluation(self):
        for lane in ("owner", "husk"):
            with self.subTest(lane=lane):
                lua = add_ownership(visible_aim.runtime(lane))
                lua.execute(CUT_PROFILE + '''
                  profile.default_state='base/custom';assert(start());tick()
                  assert(owner.writes==1 and outfit.writes==0)
                  mod._note_warlock_animation_ownership_event(owner,'idle',true)
                  tick();assert(owner.writes==2 and outfit.writes==1)
                  assert(outfit.target==owner.target)
                  mod._note_warlock_animation_ownership_event(owner,'custom',true)
                  tick();assert(owner.writes==3 and outfit.writes==1)
                ''')

    def test_verified_cut_restores_actual_grip_and_native_weapon_links_immediately(self):
        lua = add_ownership(authored_weapon.runtime())
        lua.execute(CUT_PROFILE + '''
          profile.weapon_links=semantic_links
          profile.default_state='base/custom';assert(start());tick()
          assert(not mod.last_error,mod.last_error)
          assert(calls.writes==0 and mod._warlock_grip_alignment_status(owner)=='authored')
          mod._note_warlock_animation_ownership_event(owner,'idle',true)
          tick();assert(not mod.last_error,mod.last_error)
          assert(calls.writes==24 and mod._warlock_grip_alignment_status(owner)=='active')
          for _,link in ipairs(semantic_links) do
           local node=type(link.target)=='string' and Unit.node(weapon,link.target) or link.target
           assert(weapon.external[node].unit==owner
            and weapon.external[node].node==Unit.node(owner,link.source))
          end
          mod._note_warlock_animation_ownership_event(owner,'custom',true)
          tick();assert(not mod.last_error,mod.last_error)
          assert(calls.writes==24 and mod._warlock_grip_alignment_status(owner)=='authored')
        ''')


class SnapshotBlendOwnershipTests(unittest.TestCase):
    def test_incomplete_or_alias_sampler_metadata_fails_before_native_start(self):
        invalid = (
            "profile.sampler_state_machine=nil",
            "profile.sampler_state_machine='carrier/foreign'",
            "profile.bone_names[138]=nil",
            "profile.bone_names[138]=profile.bone_names[1]",
            "profile.bone_names[138]=''",
            "profile.states['base/idle'].loop_animation=nil",
        )
        for mutation in invalid:
            with self.subTest(mutation=mutation):
                lua = runtime()
                lua.execute(SNAPSHOT_PROFILE + mutation + '''
                  assert(not start());mode('unsupported');assert(blend.starts==0)
                ''')

    def test_sampler_start_failure_blocks_legacy_pose_fallback(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          blend.start=false;assert(not start());mode('unsupported')
          assert(blend.starts==1);note('custom');mode('authored')
        ''')

    def test_sampler_acknowledges_before_state_advance_and_retains_failed_pose_guard(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          assert(start());note('custom');assert(mode('authored').state=='base/custom')
          blend.ack=false;note('idle');tick(.25)
          assert(mode('authored').state=='base/custom' and blend.notes==2)
        ''')

    def test_bridge_retains_pose_ownership_while_destination_gait_and_aim_continue(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          assert(start());note('custom');note('idle');blend.active=true
          for i=1,4 do tick(.25) end
          local o=mode('authored')
          assert(o.accessories=='authored' and o.transitioning)
          assert(o.speed=='measured' and o.visible_aim and o.state=='base/idle')
          blend.active=false;o=mode('legacy')
          assert(not o.transitioning and o.accessories=='legacy-pelvis')
        ''')

    def test_authored_destination_disables_gameplay_gait_and_aim_during_bridge(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          assert(start());note('custom');blend.active=true
          local o=mode('authored');assert(o.speed=='authored' and not o.visible_aim)
        ''')

    def test_short_bridge_releases_exactly_without_a_second_maximum_duration_timer(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          profile.states['base/custom'].transitions.idle.blend_time=.1
          assert(start());note('custom');note('idle');blend.active=true
          tick(.1);mode('authored');blend.active=false
          local o=mode('legacy');assert(not o.transitioning and o.visible_aim)
        ''')

    def test_pending_health_allows_sampler_event_registration_without_pose_ownership(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          HEALTH_ALIVE[owner]=nil;assert(start());note('custom')
          assert(query().upper_body=='unsupported' and blend.notes==1)
          HEALTH_ALIVE[owner]=true;assert(mode('authored').state=='base/custom')
        ''')

    def test_registration_restart_and_cleanup_delegate_helper_lifetime(self):
        lua = runtime()
        lua.execute(SNAPSHOT_PROFILE + '''
          assert(start());blend.active=true
          outfit.data.warlock_rig_profile=nil
          assert(not mod._start_warlock_animation_ownership(owner,outfit))
          assert(blend.stops==2 and not blend.active)
          assert(start());mod._stop_warlock_animation_ownership(owner)
          assert(blend.stops==4)
          mod._reset_warlock_animation_ownership();assert(blend.resets==1)
          mod._release_warlock_animation_ownership_world(world);assert(blend.releases==1)
        ''')


if __name__ == "__main__":
    unittest.main()
