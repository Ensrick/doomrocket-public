local mod = get_mod("doomrocket")

local menu = {
	name = "doomrocket",
	description = mod:localize("mod_description"),
	is_togglable = false,
}

menu.custom_gui_texture = {}
menu.custom_gui_textures = {
	atlases = {
		{
			"materials/doomrocket/doomrocket_atlas",
			"doomrocket_atlas",
			"doomrocket_atlas_masked",
			nil,
			nil,
			"doomrocket_atlas",
		},
	},

	-- Injections
	ui_renderer_injections = {
		{
			"ingame_ui",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"hero_view",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"loading_view",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"rcon_manager",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"chat_manager",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"popup_manager",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"splash_view",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"twitch_icon_view",
			"materials/doomrocket/doomrocket_atlas",
		},
		{
			"disconnect_indicator_view",
			"materials/doomrocket/doomrocket_atlas",
		},
	},
}

return menu
