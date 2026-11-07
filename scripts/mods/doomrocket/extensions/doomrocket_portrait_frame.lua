local mod = get_mod("doomrocket")

-- #30: vanilla enemy kill-feed portraits carry their frame inside each 60x70
-- atlas image: a 6 px bronze border that is identical across the enemy set.
-- The kill-feed widget draws no separate frame, so the Engineer's full-bleed
-- portrait showed none. Draw the border over it at runtime from the edges of a
-- vanilla enemy portrait, so no game pixels are copied into this mod.
local DOOMROCKET_PORTRAIT = "unit_frame_portrait_enemy_doomrocket"
local FRAME_SOURCE = "unit_frame_portrait_enemy_ratling_gunner"
local FRAME_WIDTH = 6
local DEFINITIONS = "scripts/ui/views/positive_reinforcement_ui_definitions"
local PORTRAITS = { "portrait_1", "portrait_2" }
local SIDES = { "top", "bottom", "left", "right" }

local function strip_name(portrait_name, side)
	return "doomrocket_frame_" .. portrait_name .. "_" .. side
end

local function add_frame_passes(definition)
	local content = definition.content
	local style = definition.style
	local passes = definition.element and definition.element.passes

	if definition.doomrocket_portrait_frame or not passes or not content or not style
		or not content.texte_style_ids then
		return
	end

	definition.doomrocket_portrait_frame = true

	for _, portrait_name in ipairs(PORTRAITS) do
		local portrait_style = style[portrait_name]

		if portrait_style then
			for _, side in ipairs(SIDES) do
				local name = strip_name(portrait_name, side)

				passes[#passes + 1] = {
					pass_type = "texture_uv",
					content_id = name,
					style_id = name,
				}
				content[name] = {
					texture_id = FRAME_SOURCE,
					uvs = { { 0, 0 }, { 1, 1 } },
					visible = false,
				}
				style[name] = {
					color = table.clone(portrait_style.color),
					offset = { 0, 0, portrait_style.offset[3] + 1 },
					size = { 0, 0 },
				}
				-- The kill feed fades every listed style; the strips fade with it.
				content.texte_style_ids[#content.texte_style_ids + 1] = name
			end
		end
	end
end

mod._add_doomrocket_portrait_frame_passes = function ()
	local definitions = package.loaded[DEFINITIONS]
	local widgets = type(definitions) == "table" and definitions.message_widgets

	if type(widgets) ~= "table" then
		return false
	end

	for _, definition in pairs(widgets) do
		add_frame_passes(definition)
	end

	return true
end

local function set_strip(content, style, name, x, y, width, height, u0, v0, u1, v1, mirrored)
	local strip_content = content[name]
	local strip_style = style[name]

	if mirrored then
		u0, u1 = 1 - u0, 1 - u1
	end

	strip_content.uvs[1][1], strip_content.uvs[1][2] = u0, v0
	strip_content.uvs[2][1], strip_content.uvs[2][2] = u1, v1
	strip_style.offset[1], strip_style.offset[2] = x, y
	strip_style.size[1], strip_style.size[2] = width, height
end

-- UI positions are lower-left corners with y up; uv row 0 is the image top
-- (UIRenderer.draw_texture_frame draws its top corners with uv rows 0..c).
mod._update_doomrocket_portrait_frame = function (widget, portrait_name, texture)
	local content = widget and widget.content
	local style = widget and widget.style

	if not content or not style or not content[strip_name(portrait_name, "top")] then
		return false
	end

	local show = texture == DOOMROCKET_PORTRAIT
	local portrait_style = style[portrait_name]
	local portrait_content = content[portrait_name]

	for _, side in ipairs(SIDES) do
		content[strip_name(portrait_name, side)].visible = show
	end

	if not show then
		return false
	end

	local x, y = portrait_style.offset[1], portrait_style.offset[2]
	local width, height = portrait_style.size[1], portrait_style.size[2]
	local fu, fv = FRAME_WIDTH / width, FRAME_WIDTH / height
	local inner = height - 2 * FRAME_WIDTH
	-- The victim slot is drawn mirrored ({1, 0} to {0, 1}); mirror its frame too.
	local mirrored = portrait_content.uvs[1][1] > portrait_content.uvs[2][1]

	set_strip(content, style, strip_name(portrait_name, "top"),
		x, y + height - FRAME_WIDTH, width, FRAME_WIDTH, 0, 0, 1, fv, mirrored)
	set_strip(content, style, strip_name(portrait_name, "bottom"),
		x, y, width, FRAME_WIDTH, 0, 1 - fv, 1, 1, mirrored)
	set_strip(content, style, strip_name(portrait_name, "left"),
		x, y + FRAME_WIDTH, FRAME_WIDTH, inner, 0, fv, fu, 1 - fv, mirrored)
	set_strip(content, style, strip_name(portrait_name, "right"),
		x + width - FRAME_WIDTH, y + FRAME_WIDTH, FRAME_WIDTH, inner, 1 - fu, fv, 1, 1 - fv, mirrored)

	return true
end

-- Patch the shared definitions before each HUD builds its kill-feed widgets.
mod:hook("PositiveReinforcementUI", "create_ui_elements", function (func, self, ...)
	mod._add_doomrocket_portrait_frame_passes()

	return func(self, ...)
end)

mod:hook_safe("PositiveReinforcementUI", "_assign_portrait_texture", function (self, widget, pass_name, texture)
	mod._update_doomrocket_portrait_frame(widget, pass_name, texture)
end)

return
