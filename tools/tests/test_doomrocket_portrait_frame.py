#!/usr/bin/env python3
"""Issue #30: the Engineer's kill-feed portrait gets the vanilla 6 px frame.

The production frame module runs in Lua 5.1. The always-run lane drives it with
widgets shaped like vanilla's kill-feed widgets. When the local game-source
checkout is present, a native lane builds the widgets with vanilla's own
create_reinforcement_widget and positions portraits with vanilla's own
_assign_portrait_texture. Neither lane renders pixels; the visible result still
needs an in-game check.
"""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
FRAME = ROOT / "scripts/mods/doomrocket/extensions/doomrocket_portrait_frame.lua"
BOOTSTRAP = ROOT / "scripts/mods/doomrocket/doomrocket.lua"
NATIVE = ROOT.parent / "Vermintide-2-Source-Code/scripts/ui/views"
NATIVE_DEFINITIONS = NATIVE / "positive_reinforcement_ui_definitions.lua"
NATIVE_UI = NATIVE / "positive_reinforcement_ui.lua"

HARNESS = r"""
    function table.clone(t)
        local copy = {}
        for key, value in pairs(t) do
            copy[key] = type(value) == 'table' and table.clone(value) or value
        end
        return copy
    end
    mod = { hooks = {} }
    function get_mod() return mod end
    function mod:hook(object, method, handler)
        assert(object == 'PositiveReinforcementUI', 'hook by name: the class loads later')
        self.hooks[method] = { kind = 'hook', handler = handler }
    end
    function mod:hook_safe(object, method, handler)
        assert(object == 'PositiveReinforcementUI', 'hook by name: the class loads later')
        self.hooks[method] = { kind = 'hook_safe', handler = handler }
    end
    package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'] = nil
    function init_widget(definition)
        -- UIWidget.init: deep-cloned content and style, shared pass list.
        return { content = table.clone(definition.content), style = table.clone(definition.style),
            element = { passes = definition.element.passes }, offset = { 0, 0, 0 } }
    end
    function strips(widget, slot)
        local names = {}
        for _, side in ipairs({ 'top', 'bottom', 'left', 'right' }) do
            names[side] = 'doomrocket_frame_portrait_' .. slot .. '_' .. side
        end
        return names
    end
"""

MODEL_DEFINITIONS = r"""
    local function model_widget()
        local color = { 255, 255, 255, 255 }
        local definition = { element = { passes = {
            { pass_type = 'texture', texture_id = 'icon', style_id = 'icon' },
            { pass_type = 'texture_uv', content_id = 'portrait_1', style_id = 'portrait_1' },
            { pass_type = 'texture_uv', content_id = 'portrait_2', style_id = 'portrait_2' },
        } }, content = { texte_style_ids = { 'icon', 'portrait_1', 'portrait_2' } }, style = { icon = { color = { 255, 255, 255, 255 } } } }
        for i = 1, 2 do
            local name = 'portrait_' .. i
            definition.content[name] = { texture_id = 'icons_placeholder',
                uvs = i == 1 and { { 0, 0 }, { 1, 1 } } or { { 1, 0 }, { 0, 1 } } }
            definition.style[name] = { color = color, offset = { 0, 0, 3 }, size = { 86, 108 },
                portrait_offset = { (i - 1) * 150, 0, 3 } }
        end
        return definition
    end
    package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'] = {
        message_widgets = { model_widget(), model_widget() },
    }
    -- Same arithmetic as vanilla _assign_portrait_texture for a 60x70 atlas entry.
    function assign(widget, slot, texture)
        local name = 'portrait_' .. slot
        local style = widget.style[name]
        if not texture then
            style.size = { 0, 0 }
        else
            widget.content[name].texture_id = texture
            style.size = { 60, 70 }
            style.offset[1] = style.portrait_offset[1] - 30
            style.offset[2] = style.portrait_offset[2] - 35
        end
        mod.hooks._assign_portrait_texture.handler(nil, widget, name, texture)
    end
"""


def model_runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    lua.execute(FRAME.read_text(encoding="utf-8"))
    lua.execute(MODEL_DEFINITIONS)
    return lua


GEOMETRY_ASSERTIONS = r"""
    local function near(a, b) return math.abs(a - b) < 1e-9 end
    local function check(widget, slot, mirrored)
        local names = strips(widget, slot)
        local portrait = widget.style['portrait_' .. slot]
        local x, y = portrait.offset[1], portrait.offset[2]
        local expected = {
            top = { x, y + 64, 60, 6, 0, 0, 1, 6 / 70 },
            bottom = { x, y, 60, 6, 0, 64 / 70, 1, 1 },
            left = { x, y + 6, 6, 58, 0, 6 / 70, 6 / 60, 64 / 70 },
            right = { x + 54, y + 6, 6, 58, 54 / 60, 6 / 70, 1, 64 / 70 },
        }
        for side, e in pairs(expected) do
            local content, style = widget.content[names[side]], widget.style[names[side]]
            assert(content.visible == true and content.texture_id == 'unit_frame_portrait_enemy_ratling_gunner', side)
            assert(near(style.offset[1], e[1]) and near(style.offset[2], e[2]), side)
            assert(style.offset[3] == portrait.offset[3] + 1, side)
            assert(style.size[1] == e[3] and style.size[2] == e[4], side)
            local u0, u1 = e[5], e[7]
            if mirrored then u0, u1 = 1 - u0, 1 - u1 end
            local uvs = content.uvs
            assert(near(uvs[1][1], u0) and near(uvs[1][2], e[6]) and near(uvs[2][1], u1) and near(uvs[2][2], e[8]), side)
        end
    end
"""


class PortraitFrameModelTests(unittest.TestCase):
    def test_bootstrap_loads_the_frame_module(self):
        self.assertIn('mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_portrait_frame")',
                      BOOTSTRAP.read_text(encoding="utf-8"))

    def test_patch_is_idempotent_and_strips_fade_with_the_widget(self):
        lua = model_runtime()
        lua.execute("""
            local definitions = package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions']
            assert(mod._add_doomrocket_portrait_frame_passes())
            assert(mod._add_doomrocket_portrait_frame_passes())
            for _, definition in ipairs(definitions.message_widgets) do
                assert(#definition.element.passes == 3 + 8)
                assert(#definition.content.texte_style_ids == 3 + 8)
                for slot = 1, 2 do
                    for side, name in pairs(strips(definition, slot)) do
                        assert(definition.content[name].visible == false, name)
                        assert(definition.style[name].color ~= definition.style['portrait_' .. slot].color)
                    end
                end
            end
        """)

    def test_create_ui_elements_hook_patches_before_building(self):
        lua = model_runtime()
        lua.execute("""
            local definitions = package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions']
            local seen
            mod.hooks.create_ui_elements.handler(function(self)
                seen = #definitions.message_widgets[1].element.passes
                return 'built'
            end, {})
            assert(seen == 11 and mod.hooks.create_ui_elements.kind == 'hook')
            assert(mod.hooks._assign_portrait_texture.kind == 'hook_safe')
        """)

    def test_frame_covers_the_engineer_in_either_slot(self):
        lua = model_runtime()
        lua.execute(GEOMETRY_ASSERTIONS + """
            mod._add_doomrocket_portrait_frame_passes()
            local definition = package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'].message_widgets[1]
            local widget = init_widget(definition)
            assign(widget, 1, 'small_unit_frame_portrait_kruber_mercenary')
            assign(widget, 2, 'unit_frame_portrait_enemy_doomrocket')
            check(widget, 2, true)
            for _, name in pairs(strips(widget, 1)) do assert(widget.content[name].visible == false) end
            assign(widget, 1, 'unit_frame_portrait_enemy_doomrocket')
            check(widget, 1, false)
        """)

    def test_recycled_widget_hides_the_frame_for_other_portraits(self):
        lua = model_runtime()
        lua.execute("""
            mod._add_doomrocket_portrait_frame_passes()
            local definition = package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'].message_widgets[1]
            local widget = init_widget(definition)
            assign(widget, 2, 'unit_frame_portrait_enemy_doomrocket')
            assign(widget, 2, 'unit_frame_portrait_enemy_rat_ogre')
            for _, name in pairs(strips(widget, 2)) do assert(widget.content[name].visible == false) end
            assign(widget, 2, 'unit_frame_portrait_enemy_doomrocket')
            assign(widget, 2, nil)
            for _, name in pairs(strips(widget, 2)) do assert(widget.content[name].visible == false) end
        """)

    def test_widgets_built_without_the_patch_are_left_alone(self):
        lua = model_runtime()
        lua.execute("""
            local definition = package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'].message_widgets[1]
            local widget = init_widget(definition)
            assert(mod._update_doomrocket_portrait_frame(widget, 'portrait_2', 'unit_frame_portrait_enemy_doomrocket') == false)
            package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'] = nil
            assert(mod._add_doomrocket_portrait_frame_passes() == false)
        """)


def native_function(path, name):
    source = path.read_text(encoding="utf-8-sig")
    match = re.search(r"(?ms)^" + re.escape(name) + r" = function\b.*?^end$", source)
    if not match:
        raise AssertionError(f"missing native {name}")
    return match.group()


def native_local_function(path, name):
    source = path.read_text(encoding="utf-8-sig")
    match = re.search(r"(?ms)^local function " + re.escape(name) + r"\(.*?^end$", source)
    if not match:
        raise AssertionError(f"missing native local {name}")
    return match.group()


@unittest.skipUnless(NATIVE_DEFINITIONS.exists() and NATIVE_UI.exists(), "local game-source checkout not present")
class PortraitFrameNativeTests(unittest.TestCase):
    def test_vanilla_widget_and_assignment_carry_the_frame(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(HARNESS)
        lua.execute(FRAME.read_text(encoding="utf-8"))
        lua.execute("""
            UIPlayerPortraitFrameSettings = {}
            Colors = { get_table = function() return { 255, 255, 255, 255 } end }
            UIAtlasHelper = {
                has_atlas_settings_by_texture_name = function(texture) return texture ~= 'icons_placeholder' end,
                get_atlas_settings_by_texture_name = function() return { size = { 60, 70 } } end,
            }
            PositiveReinforcementUI = {}
        """)
        lua.execute(native_local_function(NATIVE_DEFINITIONS, "create_reinforcement_widget")
                    + "\nnative_create = create_reinforcement_widget")
        native_ui = NATIVE_UI.read_text(encoding="utf-8-sig")
        temp_size = re.search(r"(?ms)^local temp_portrait_size = \{.*?^\}$", native_ui)
        self.assertIsNotNone(temp_size, "vanilla fallback portrait size moved")
        lua.execute(temp_size.group() + "\n"
                    + native_function(NATIVE_UI, "PositiveReinforcementUI._assign_portrait_texture"))
        lua.execute(GEOMETRY_ASSERTIONS + """
            package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'] = {
                message_widgets = { native_create('message_animated', 'positive_reinforcement', 1) },
            }
            mod._add_doomrocket_portrait_frame_passes()
            local definition = package.loaded['scripts/ui/views/positive_reinforcement_ui_definitions'].message_widgets[1]
            local widget = init_widget(definition)
            local function assign(slot, texture)
                PositiveReinforcementUI._assign_portrait_texture(nil, widget, 'portrait_' .. slot, texture)
                mod.hooks._assign_portrait_texture.handler(nil, widget, 'portrait_' .. slot, texture)
            end
            assign(1, 'small_unit_frame_portrait_kruber_mercenary')
            assign(2, 'unit_frame_portrait_enemy_doomrocket')
            check(widget, 2, true)
            assign(1, 'unit_frame_portrait_enemy_doomrocket')
            check(widget, 1, false)
            -- Vanilla fades by texte_style_ids; the strips are listed.
            local listed = {}
            for _, id in ipairs(widget.content.texte_style_ids) do listed[id] = true end
            for slot = 1, 2 do
                for _, name in pairs(strips(widget, slot)) do assert(listed[name], name) end
            end
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
