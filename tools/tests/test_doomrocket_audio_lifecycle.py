#!/usr/bin/env python3
"""Execute #44 audio ownership against delayed/rejected stops and retained corpses.

The native playing-ID API is independently present in VT2's dialogue_system
and corruptor_beam_extension. Doubles prove our ownership and retry ordering;
the tester's audible verdict still decides actual in-game cleanup and loudness.
"""
from pathlib import Path
import hashlib
import struct
import sys
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build_doomrocket_wwise_bank as bank

MODULE = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_audio.lua"

HARNESS = r'''
world={alive=true}; ww={world=world}; now=0
logs={}; calls={}; playing={}; sources={}; next_id=100; next_source=1
stop_ignored=0; stop_delayed=false
function printf(fmt,...) logs[#logs+1]=string.format(fmt,...) end
function new_owner()
 local u={alive=true,health={dead=false}}
 function u.health:is_alive() return not self.dead end
 return u
end
owner=new_owner(); outfit={alive=true}; launcher={alive=true}
Unit={alive=function(u) return u and u.alive end,
 has_node=function(u,n) assert(u.alive); return true end,
 node=function(u,n) assert(u.alive); return 1 end}
ScriptUnit={has_extension=function(u,n)
 assert(u.alive,'deleted unit extension queried')
 if n=='health_system' then return u.health end
 if n=='hit_reaction_system' then return nil end
 error('unexpected extension')
end}
wm={_worlds={level_world=world},_disabled_worlds={}}
function wm:has_world(n) return self._worlds[n]~=nil end
function wm:world(n) assert(self._worlds[n]); return self._worlds[n] end
function wm:wwise_world(w) assert(w.alive,'released audio world queried'); return ww end
Managers={world=wm,player={is_server=true},state={unit_storage={go_id=function() return 2 end}}}
Application={can_get=function() return true end,time_since_launch=function() return now end}
Wwise={has_event=function() return false end,load_bank=function() end,unload_bank=function() end}
WwiseUtils={make_unit_auto_source=function(w,u,n)
 assert(w.alive and u.alive); local id=next_source; next_source=next_source+1; sources[id]=u
 return id,ww
end}
local function valid(w) assert(w==ww and w.world.alive,'stale Wwise world used') end
WwiseWorld={trigger_event=function(w,event,tracking,source)
 valid(w); assert(tracking==true); assert(sources[source])
 if event:sub(1,4)=='Stop' then calls[#calls+1]={kind='authored_stop',event=event}; return 0 end
 local id=next_id; next_id=next_id+1; playing[id]={event=event,source=source}
 calls[#calls+1]={kind='play',id=id,event=event}; return id
end,is_playing=function(w,id) valid(w); return playing[id]~=nil end,
stop_event=function(w,id)
 valid(w); assert(playing[id],'completed playing ID stopped')
 calls[#calls+1]={kind='stop',id=id}
 if stop_ignored>0 then stop_ignored=stop_ignored-1
 elseif stop_delayed then playing[id].stop_pending=true
 else playing[id]=nil end
end}
mod={}; function get_mod() return mod end
function advance(dt) now=now+(dt or 0.3); mod._update_warlock_backpack_sounds() end
function count_playing() local n=0; for _ in pairs(playing) do n=n+1 end; return n end
function start_all(o,b,l)
 o=o or owner; b=b or outfit; l=l or launcher
 assert(mod._start_warlock_backpack_sound(o,b))
 assert(mod._play_warlock_combat_voice(o,1))
 assert(mod._play_doomrocket_launch_sound(l,o))
end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(MODULE.read_text(encoding="utf-8"))
    return lua


class AudioLifecycleTests(unittest.TestCase):
    def test_death_stops_exact_ids_even_if_authored_stop_event_is_rejected(self):
        runtime().execute('''
        start_all(); assert(count_playing()==3)
        mod._stop_warlock_living_sounds(owner,'death_unit')
        assert(count_playing()==0)
        for _,call in ipairs(calls) do assert(call.kind~='authored_stop') end
        local n=#calls; mod._stop_warlock_living_sounds(owner,'death_husk'); assert(#calls==n)
        advance()
        local verified=0; for _,line in ipairs(logs) do
          if line:find('status=stopped',1,true) then verified=verified+1 end
        end; assert(verified==3)
        ''')

    def test_stop_is_retained_and_retried_until_wwise_observes_silence(self):
        runtime().execute('''
        assert(mod._start_warlock_backpack_sound(owner,outfit))
        stop_ignored=1; mod._stop_warlock_living_sounds(owner,'death')
        assert(count_playing()==1)
        for _,line in ipairs(logs) do assert(not line:find('status=stopped',1,true)) end
        advance(); assert(count_playing()==0); advance()
        assert(logs[#logs]:find('status=stopped',1,true))
        assert(logs[#logs]:find('attempts=2',1,true))
        ''')

    def test_asynchronous_stop_is_not_reported_as_complete_early(self):
        runtime().execute('''
        start_all(); stop_delayed=true
        mod._stop_warlock_living_sounds(owner,'death'); advance(0.1)
        assert(count_playing()==3)
        for _,line in ipairs(logs) do assert(not line:find('status=stopped',1,true)) end
        for id in pairs(playing) do playing[id]=nil end
        advance(); local count=0
        for _,line in ipairs(logs) do if line:find('status=stopped',1,true) then count=count+1 end end
        assert(count==3)
        ''')

    def test_dead_health_on_retained_unit_stops_audio_without_death_callback(self):
        runtime().execute('''
        start_all(); owner.health.dead=true; assert(Unit.alive(owner))
        advance(); assert(count_playing()==0)
        assert(not mod._start_warlock_backpack_sound(owner,outfit))
        assert(not mod._play_warlock_combat_voice(owner,1))
        assert(not mod._play_doomrocket_launch_sound(launcher,owner))
        ''')

    def test_late_spawn_or_launch_callback_cannot_restart_retired_owner(self):
        runtime().execute('''
        start_all(); mod._stop_warlock_living_sounds(owner,'inventory_freeze')
        assert(owner.health:is_alive())
        assert(not mod._start_warlock_backpack_sound(owner,outfit))
        assert(not mod._play_warlock_combat_voice(owner,1))
        assert(not mod._play_doomrocket_launch_sound(launcher,owner))
        assert(mod._choose_warlock_combat_voice(owner)==0)
        ''')

    def test_destroyed_handle_is_forgotten_after_its_audio_stops(self):
        runtime().execute('''
        start_all(); assert(mod._play_warlock_death_voice(owner))
        mod._stop_warlock_living_sounds(owner,'inventory_destroy')
        mod._forget_warlock_audio_owner(owner); advance(5)
        assert(count_playing()==1, 'only the death voice may remain')
        -- The engine reuses the same handle for a new, living Engineer.
        assert(mod._start_warlock_backpack_sound(owner,outfit))
        assert(mod._play_warlock_combat_voice(owner,1))
        assert(mod._play_doomrocket_launch_sound(launcher,owner))
        assert(mod._play_warlock_death_voice(owner))
        mod._forget_warlock_audio_owner(nil)
        ''')

    def test_death_voice_survives_living_audio_cleanup(self):
        runtime().execute('''
        start_all(); assert(mod._play_warlock_death_voice(owner))
        assert(count_playing()==1)
        for _,event in pairs(playing) do assert(event.event:find('voice_death',1,true)) end
        mod._stop_warlock_living_sounds(owner,'inventory_freeze'); advance()
        assert(count_playing()==1)
        assert(not mod._play_warlock_death_voice(owner))
        ''')

    def test_multiple_enemies_and_overlap_keep_independent_audio(self):
        runtime().execute('''
        local o2=new_owner(); start_all(); start_all(o2,{alive=true},{alive=true})
        assert(mod._play_doomrocket_launch_sound(launcher,owner))
        assert(count_playing()==7)
        mod._stop_warlock_living_sounds(owner,'death'); assert(count_playing()==3)
        advance(); mod._stop_warlock_living_sounds(o2,'death'); assert(count_playing()==0)
        ''')

    def test_completed_oneshots_are_forgotten_without_invalid_stop_calls(self):
        runtime().execute('''
        start_all()
        for id,event in pairs(playing) do if not event.event:find('backpack',1,true) then playing[id]=nil end end
        advance(); local n=#calls
        mod._stop_warlock_living_sounds(owner,'death'); assert(#calls==n+1)
        ''')

    def test_world_release_stops_before_native_release_and_forgets_pending_ids(self):
        runtime().execute('''
        start_all(); stop_ignored=20
        mod._release_warlock_audio_world(world)
        world.alive=false; wm._worlds.level_world=nil
        advance(); mod._shutdown_doomrocket_audio('late_unload',true)
        ''')

    def test_lost_world_and_deleted_owner_never_touch_released_native_handle(self):
        runtime().execute('''
        start_all(); world.alive=false; wm._worlds.level_world=nil; owner.alive=false
        advance(); mod._shutdown_doomrocket_audio('state_exit',true)
        ''')

    def test_one_owner_stop_does_not_depend_on_live_outfit_source(self):
        runtime().execute('''
        start_all(); outfit.alive=false; advance(); assert(count_playing()==0)
        ''')

    def test_disabled_world_retains_valid_cleanup_ownership(self):
        runtime().execute('''
        start_all(); wm._worlds.level_world=nil; wm._disabled_worlds.level_world=world
        mod._stop_warlock_living_sounds(owner,'paused_death'); assert(count_playing()==0)
        advance()
        ''')

    def test_inventory_and_world_hooks_run_audio_cleanup_before_native_teardown(self):
        source = (ROOT / "scripts/mods/doomrocket/utils/hooks.lua").read_text(encoding="utf-8")
        for phase in ("destroy", "freeze"):
            block = source.split(f'mod:hook(AIInventoryExtension, "{phase}"', 1)[1].split("end)", 1)[0]
            self.assertLess(block.index("mod._stop_warlock_living_sounds"), block.index("return func"))
            if phase == "destroy":
                self.assertLess(block.index("mod._stop_warlock_living_sounds"),
                                block.index("mod._forget_warlock_audio_owner"))
                self.assertLess(block.index("mod._forget_warlock_audio_owner"), block.index("return func"))
            else:
                self.assertNotIn("mod._forget_warlock_audio_owner", block)
        block = source.split('mod:hook(Application, "release_world"', 1)[1].split("end)", 1)[0]
        self.assertLess(block.index("mod._release_warlock_audio_world"), block.index("func(world"))


class ApprovedAudioGainTests(unittest.TestCase):
    def test_gain_is_symmetric_preserves_silence_and_cannot_clip(self):
        values = [-32768, -32767, -1000, -1, 0, 1, 1000, 32767]
        converted = struct.unpack("<8h", bank.playback_pcm(struct.pack("<8h", *values)))
        self.assertEqual(converted, (-16217, -16216, -495, 0, 0, 0, 495, 16216))
        with self.assertRaises(ValueError):
            bank.playback_pcm(b"x")

    def test_all_pcm_levels_are_thirty_percent_quieter_than_shipped_test(self):
        values = range(-32768, 32768)
        pcm = struct.pack("<65536h", *values)
        rendered = struct.unpack("<65536h", bank.playback_pcm(pcm))
        self.assertEqual(rendered[32768], 0)
        for before, after in zip(values, rendered):
            # Independent comparison to the previous bank's rounded 707/1000
            # PCM, then the requested 0.70 multiplier. Composing on the master
            # avoids intermediate rounding; the two paths differ by at most
            # one 16-bit quantisation level.
            previous = (abs(before) * 707 + 500) // 1000
            reduced_previous = (previous * 7 + 5) // 10
            self.assertLessEqual(abs(abs(after) - reduced_previous), 1)
            self.assertLessEqual(abs(after), previous)
            self.assertLessEqual(abs(after), 16217)
            if after:
                self.assertEqual(after < 0, before < 0)

    def test_reduced_gain_preserves_every_approved_source_and_sample_count(self):
        import json
        manifest = json.loads((ROOT / "wwise/doomrocket.bank_manifest.json").read_text())
        self.assertEqual(manifest["authoring"]["playback_gain"],
                         {"numerator": 4949, "denominator": 10000, "approximate_db": -6.11})
        self.assertEqual(manifest["authoring"]["playback_gain_adjustment"], {
            "relative_to": "TEST v0.1.88-dev",
            "previous_numerator": 707, "previous_denominator": 1000,
            "numerator": 7, "denominator": 10, "additional_db": -3.10,
        })
        for key, name in bank.CANONICAL_SOURCE_NAMES.items():
            source = ROOT / "audio_src/doomrocket" / name
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), bank.EXPECTED_SOURCE_HASHES[key])
            pcm, _ = bank.read_pcm_wave(source)
            rendered = bank.playback_pcm(pcm)
            self.assertEqual(len(rendered), len(pcm))
            self.assertEqual(hashlib.sha256(rendered).hexdigest(), manifest["media"][key]["playback_pcm_sha256"])

    def test_embedded_bank_media_has_reviewed_gain_without_timing_or_channel_changes(self):
        import json
        manifest = json.loads((ROOT / "wwise/doomrocket.bank_manifest.json").read_text())
        raw = (ROOT / "wwise/doomrocket.wwise_bank").read_bytes()[44:]
        chunks = {}
        offset = 0
        while offset < len(raw):
            tag, size = struct.unpack_from("<4sI", raw, offset)
            chunks[tag] = raw[offset + 8:offset + 8 + size]
            offset += 8 + size
        media = {mid: chunks[b"DATA"][start:start + size]
                 for mid, start, size in struct.iter_unpack("<III", chunks[b"DIDX"])}
        for key, metadata in manifest["media"].items():
            source_pcm, _ = bank.read_pcm_wave(ROOT / metadata["canonical_source"])
            wem = media[metadata["media_id"]]
            data_at = wem.index(b"data")
            size = struct.unpack_from("<I", wem, data_at + 4)[0]
            pcm = wem[data_at + 8:data_at + 8 + size]
            self.assertEqual(len(pcm), len(source_pcm))
            # Check actual packaged media with an independent rational-gain
            # calculation rather than trusting the manifest or renderer.
            for (before,), (after,) in zip(struct.iter_unpack("<h", source_pcm), struct.iter_unpack("<h", pcm)):
                expected = (abs(before) * 4949 + 5000) // 10000
                self.assertEqual(after, -expected if before < 0 else expected, key)


if __name__ == "__main__":
    unittest.main()
