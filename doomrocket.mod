return {
	run = function()
		fassert(rawget(_G, "new_mod"), "`doomrocket` mod must be lower than Vermintide Mod Framework in your launcher's load order.")

		new_mod("doomrocket", {
			mod_script       = "scripts/mods/doomrocket/doomrocket",
			mod_data         = "scripts/mods/doomrocket/doomrocket_data",
			mod_localization = "scripts/mods/doomrocket/doomrocket_localization",
		})
	end,
	packages = {
		"resource_packages/doomrocket/doomrocket",
	},
}
