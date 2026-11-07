"""Execute the standalone oracle against bounded Lua 5.1 native API doubles."""
import json
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / "tools/animation_rig/native_pose_oracle.lua"
HARNESS = r'''
config = {
    compiled_provenance_file = "provenance.json", output_file = "poses.json",
    provenance = {}, unit_resource = "oracle/checked_unit",
    animation_resource = "oracle/first_clip", bone_names = {"root", "hand"},
    fps = 60, samples_per_update = 2,
    samples = {
        {frame = 0, time_seconds = 0.125, clip = "first"},
        {frame = 1, time_seconds = 0.25, clip = "second",
            animation_resource = "oracle/second_clip", sample_fps = 240},
    },
}
package.preload.native_pose_oracle_input = function() return config end
subject = {alive = true, has_asm = true, layers = 1}
world = {}
calls = {unsafe = 0, crossfades = {}, speeds = {}, seeks = {}, updates = {},
    scenes = {}, poses = 0, releases = 0, quits = {}, restores = 0, writes = 0}
messages = {}
output_text = ""
function print(message) messages[#messages + 1] = message end
local function live(u)
    if u ~= subject or not u.alive or world.released then
        calls.unsafe = calls.unsafe + 1
        error("unsafe native unit access")
    end
end
local function single(u)
    live(u)
    if not u.has_asm or u.layers ~= 1 then
        calls.unsafe = calls.unsafe + 1
        error("unsafe native animation layer access")
    end
end
Application = {
    DISABLE_PHYSICS = 1, DISABLE_RENDERING = 2, DISABLE_SOUND = 3, DISABLE_APEX_CLOTH = 4,
    new_world = function(name, ...)
        assert(name == "animation_native_pose_oracle")
        assert(select("#", ...) == 4)
        return world
    end,
    release_world = function(w)
        assert(w == world and not w.released)
        w.released = true; calls.releases = calls.releases + 1
    end,
    quit = function(code) calls.quits[#calls.quits + 1] = code end,
}
World = {
    spawn_unit = function(w, resource)
        assert(w == world and resource == config.unit_resource); return subject
    end,
    update_animations = function(w, dt)
        assert(w == world and not w.released); calls.updates[#calls.updates + 1] = dt
    end,
    update_scene = function(w, dt)
        assert(w == world and not w.released); calls.scenes[#calls.scenes + 1] = dt
    end,
}
local pose = {x = {1, 2, 3}, y = {4, 5, 6}, z = {7, 8, 9}, translation = {10, 11, 12}}
Unit = {
    alive = function(u) return u and u.alive end,
    has_animation_state_machine = function(u) live(u); return u.has_asm end,
    animation_get_state = function(u)
        live(u); assert(u.has_asm)
        if u.layers == 0 then return end
        if u.layers == 2 then return nil, 42 end
        if u.empty_state then return nil end
        return 31
    end,
    disable_animation_state_machine = function(u) single(u); calls.writes = calls.writes + 1 end,
    set_animation_bone_mode = function(u, mode) single(u); assert(mode == "transform") end,
    set_animation_root_mode = function(u, mode) single(u); assert(mode == "ignore") end,
    crossfade_animation = function(u, resource, layer, blend, loop, mode)
        single(u)
        if layer ~= 0 then calls.unsafe = calls.unsafe + 1; error("layer out of bounds") end
        assert(blend == 0 and loop == false and mode == "normal")
        calls.crossfades[#calls.crossfades + 1] = {resource = resource, layer = layer}
        return #calls.crossfades
    end,
    crossfade_animation_set_speed = function(u, id, speed)
        single(u); calls.speeds[#calls.speeds + 1] = {id = id, speed = speed}
    end,
    crossfade_animation_set_time = function(u, id, time, frozen)
        single(u); assert(frozen == true)
        calls.seeks[#calls.seeks + 1] = {id = id, time = time}
    end,
    node = function(u, name) live(u); return name == "root" and 0 or 1 end,
    local_pose = function(u, node) live(u); calls.poses = calls.poses + 1; return pose end,
    world_pose = function(u, node) live(u); calls.poses = calls.poses + 1; return pose end,
    animation_wanted_root_pose = function(u) live(u); return pose end,
}
Matrix4x4 = {
    x = function(p) return p.x end, y = function(p) return p.y end,
    z = function(p) return p.z end, translation = function(p) return p.translation end,
}
Vector3 = {x = function(v) return v[1] end, y = function(v) return v[2] end,
    z = function(v) return v[3] end}
Script = {
    temp_count = function() return 1, 2, 3 end,
    set_temp_count = function(a, b, c)
        assert(a == 1 and b == 2 and c == 3); calls.restores = calls.restores + 1
    end,
}
io = {open = function(path, mode)
    if path == config.compiled_provenance_file then
        assert(mode == "r")
        return {close = function() end, read = function(self, all)
            assert(all == "*a")
            local hash = string.rep("a", 64)
            return '{"compiled_unit_sha256":"' .. hash .. '","compiled_animation_sha256":"' ..
                hash .. '","sdk_executable_sha256":"' .. hash .. '"}'
        end}
    end
    assert(path == config.output_file and mode == "w")
    return {flush = function() end, close = function() end, write = function(self, ...)
        for i = 1, select("#", ...) do output_text = output_text .. tostring(select(i, ...)) end
    end}
end}
'''


def runtime(mutation=""):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(mutation)
    lua.execute(ORACLE.read_text(encoding="utf-8"))
    return lua


class NativePoseOracleLayers(unittest.TestCase):
    def test_init_and_resource_change_use_layer_zero_and_preserve_sampling(self):
        lua = runtime()
        lua.execute("init(); update(99)")
        self.assertEqual(lua.eval("calls.unsafe"), 0)
        self.assertEqual(lua.eval("#calls.crossfades"), 2)
        for index, resource in ((1, "oracle/first_clip"), (2, "oracle/second_clip")):
            self.assertEqual(lua.eval(f"calls.crossfades[{index}].resource"), resource)
            self.assertEqual(lua.eval(f"calls.crossfades[{index}].layer"), 0)
            self.assertEqual(lua.eval(f"calls.speeds[{index}].speed"), 0)
            self.assertEqual(lua.eval(f"calls.seeks[{index}].id"), index)
        self.assertEqual(lua.eval("calls.seeks[1].time"), 0.125)
        self.assertEqual(lua.eval("calls.seeks[2].time"), 0.25)
        self.assertAlmostEqual(lua.eval("calls.updates[1]"), 1 / 60)
        self.assertAlmostEqual(lua.eval("calls.updates[2]"), 1 / 240)
        self.assertEqual(lua.eval("calls.scenes[1] + calls.scenes[2]"), 0)
        self.assertEqual(lua.eval("calls.restores"), 6)
        self.assertEqual(lua.eval("calls.releases"), 1)
        self.assertEqual(lua.eval("calls.quits[1]"), 0)
        report = json.loads(lua.eval("output_text"))
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["bone_count"], 2)
        self.assertEqual(report["unit_node_indices"], {"root": 0, "hand": 1})
        self.assertEqual(report["samples"][0]["bones_local"]["hand"],
                         [[1, 4, 7, 10], [2, 5, 8, 11], [3, 6, 9, 12], [0, 0, 0, 1]])
        self.assertEqual(report["samples"][1]["clip"], "second")

    def test_single_nil_state_is_an_existing_layer_for_frozen_playback(self):
        lua = runtime("subject.empty_state = true")
        lua.execute("init(); update(0)")
        self.assertEqual(lua.eval("#calls.crossfades"), 2)
        self.assertEqual(lua.eval("calls.unsafe"), 0)
        self.assertEqual(lua.eval("calls.quits[1]"), 0)

    def test_invalid_init_has_no_native_animation_writes(self):
        for mutation in ("subject.alive = false", "subject.has_asm = false",
                         "subject.layers = 0", "subject.layers = 2"):
            with self.subTest(mutation=mutation):
                lua = runtime(mutation)
                lua.execute("init(); update(0)")
                self.assertEqual(lua.eval("calls.unsafe + calls.writes + #calls.crossfades + #calls.seeks"), 0)
                self.assertEqual(lua.eval("#calls.updates + calls.poses"), 0)
                self.assertEqual(lua.eval("calls.releases"), 1)
                self.assertEqual(lua.eval("#calls.quits"), 1)
                self.assertEqual(lua.eval("calls.quits[1]"), 1)
                self.assertTrue(lua.eval("messages[#messages]").startswith("ANIMATION_ORACLE_FAILURE "))

    def test_teardown_or_layer_loss_stops_before_replacement_crossfade_or_seek(self):
        for mutation in ("subject.alive = false", "subject.has_asm = false",
                         "subject.layers = 0", "subject.layers = 2"):
            for change_resource in (True, False):
                with self.subTest(mutation=mutation, change_resource=change_resource):
                    lua = runtime()
                    lua.execute("config.samples_per_update = 1; init(); update(0)")
                    if not change_resource:
                        lua.execute("config.samples[2].animation_resource = config.animation_resource")
                    lua.execute(mutation + "; update(0); update(0)")
                    self.assertEqual(lua.eval("calls.unsafe"), 0)
                    self.assertEqual(lua.eval("#calls.crossfades"), 1)
                    self.assertEqual(lua.eval("#calls.seeks"), 1)
                    self.assertEqual(lua.eval("#calls.updates"), 1)
                    self.assertEqual(lua.eval("calls.poses"), 4)
                    self.assertEqual(lua.eval("calls.releases"), 1)
                    self.assertEqual(lua.eval("#calls.quits"), 1)
                    self.assertEqual(lua.eval("calls.quits[1]"), 1)
                    self.assertNotIn("ANIMATION_ORACLE_COMPLETE", lua.eval("table.concat(messages, '\\n')"))


if __name__ == "__main__":
    unittest.main()
