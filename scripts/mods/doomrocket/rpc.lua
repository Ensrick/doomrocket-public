local mod = get_mod("doomrocket")

mod:network_register("rpc_launch_rocket", function(sender, go_id, network_velocity, network_target_vector, attacker_unit_id, combat_voice_variant)
	print(sender)

    local attacker_unit = Managers.state.unit_storage:unit(attacker_unit_id)
	local velocity = AiAnimUtils.velocity_network_scale(network_velocity)
    local target_vector = AiAnimUtils.velocity_network_scale(network_target_vector)

	local breed = Breeds['skaven_doomrocket']
	local inventory_template = breed.default_inventory_template
	local inventory_extension = ScriptUnit.extension(attacker_unit, "ai_inventory_system")
	local ratling_gun_unit = inventory_extension:get_unit(inventory_template)

	local projectile_unit = Managers.state.unit_storage:unit(go_id)

	mod.projectiles[projectile_unit] = ProjectileRocket:new(
		projectile_unit, attacker_unit, target_vector, ratling_gun_unit, combat_voice_variant)

	Unit.set_mesh_visibility(ratling_gun_unit, "pRocket", false, "default")
end)

-- The UnitSpawner.spawn_unit_from_game_object hook that used to live here rewrote
-- go_template.go_type from 'ai_unit_ratling_gunner' to 'ai_unit_doomrocket' in place.
-- That template table is shared vanilla state, so the write was permanent and converted
-- every REAL ratling gunner in the session too (/doom adds bombardiers alongside ratling
-- gunners, it does not replace them).
--
-- Breeds.skaven_doomrocket now carries unit_template = "ai_unit_doomrocket", so
-- UnitSpawner.spawn_network_unit resolves the right go_type at creation time and no
-- rewrite is needed. See breeds/skaven_doomrocket.lua.

mod:network_register("rpc_reload_rocket", function(sender, rat_go_id)
	print(sender)

    local attacker_unit = Managers.state.unit_storage:unit(rat_go_id)

	local breed = Breeds['skaven_doomrocket']
	local inventory_template = breed.default_inventory_template
	local inventory_extension = ScriptUnit.extension(attacker_unit, "ai_inventory_system")
	local ratling_gun_unit = inventory_extension:get_unit(inventory_template)

	Unit.set_mesh_visibility(ratling_gun_unit, "pRocket", true, "default")
end)
