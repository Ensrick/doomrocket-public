local unit_go_sync_functions = require("scripts/network/game_object_initializers_extractors")

local function enemy_unit_common_extractor(unit, game_session, game_object_id)
	local breed_name_id = GameSession.game_object_field(game_session, game_object_id, "breed_name")
	local breed_name = NetworkLookup.breeds[breed_name_id]
	local breed = Breeds[breed_name]

	Unit.set_data(unit, "breed", breed)

	local level_settings = LevelSettings[Managers.state.game_mode:level_key()]
	local climate_type = level_settings.climate_type or "default"

	Unit.set_flow_variable(unit, "climate_type", climate_type)
	Unit.flow_event(unit, "climate_type_set")

	local side_id = GameSession.game_object_field(game_session, game_object_id, "side_id")

	return breed, breed_name, side_id
end

unit_go_sync_functions.initializers.ai_unit_doomrocket = function(unit, unit_name, unit_template, gameobject_functor_context)
    local mover = Unit.mover(unit)
    local breed = Unit.get_data(unit, "breed")
    local ai_extension = ScriptUnit.extension(unit, "ai_system")
    local size_variation, size_variation_normalized = ai_extension:size_variation()
    local inventory_configuration_name = ScriptUnit.extension(unit, "ai_inventory_system").inventory_configuration_name
    local side = Managers.state.side.side_by_unit[unit]
    local side_id = side.side_id
    local data_table = {
        has_teleported = 1,
        go_type = NetworkLookup.go_types.ai_unit_doomrocket,
        husk_unit = NetworkLookup.husks[unit_name],
        health = ScriptUnit.extension(unit, "health_system"):get_max_health(),
        position = mover and Mover.position(mover) or Unit.local_position(unit, 0),
        yaw_rot = Quaternion.yaw(Unit.local_rotation(unit, 0)),
        velocity = Vector3(0, 0, 0),
        breed_name = NetworkLookup.breeds[breed.name],
        uniform_scale = size_variation,
        inventory_configuration = NetworkLookup.ai_inventory[inventory_configuration_name],
        aim_target = Vector3.zero(),
        bt_action_name = NetworkLookup.bt_action_names["n/a"],
        side_id = side_id,
    }

    return data_table
end

unit_go_sync_functions.initializers.doomrocket_projectile = function (unit, unit_name, unit_template, gameobject_functor_context)
    local health_extension = ScriptUnit.has_extension(unit, "health_system")
    local data_table = {
        go_type = NetworkLookup.go_types.doomrocket_projectile,
        husk_unit = NetworkLookup.husks[unit_name],
        position = Unit.local_position(unit, 0),
        rotation = Unit.local_rotation(unit, 0),
        health = health_extension:get_max_health(),
    }

    return data_table
end

unit_go_sync_functions.extractors.ai_unit_doomrocket = function(game_session, game_object_id, owner_id, unit, gameobject_functor_context)
    local breed, breed_name, side_id = enemy_unit_common_extractor(unit, game_session, game_object_id)
    local inventory_configuration_name = NetworkLookup.ai_inventory[GameSession.game_object_field(game_session, game_object_id, "inventory_configuration")]
    local health = GameSession.game_object_field(game_session, game_object_id, "health")
    local extension_init_data = {
        ai_system = {
            go_id = game_object_id,
            game = game_session,
            side_id = side_id,
        },
        locomotion_system = {
            go_id = game_object_id,
            breed = breed,
            game = game_session,
        },
        health_system = {
            health = health,
        },
        death_system = {
            is_husk = true,
            death_reaction_template = breed.death_reaction,
            disable_second_hit_ragdoll = breed.disable_second_hit_ragdoll,
        },
        hit_reaction_system = {
            is_husk = true,
            hit_reaction_template = breed.hit_reaction,
            hit_effect_template = breed.hit_effect_template,
        },
        ai_inventory_system = {
            inventory_configuration_name = inventory_configuration_name,
        },
        dialogue_system = {
            faction = "enemy",
            breed_name = breed_name,
        },
        aim_system = {
            is_husk = true,
            template = "doomrocket",
        },
        proximity_system = {
            breed = breed,
        },
        buff_system = {
            breed = breed,
        },
    }
    local unit_template_name = breed.unit_template

    return unit_template_name, extension_init_data
end

unit_go_sync_functions.extractors.doomrocket_projectile = function (game_session, go_id, owner_id, unit, gameobject_functor_context)
    local health = GameSession.game_object_field(game_session, go_id, "health")
    local unit_template_name = "doomrocket_projectile"
    local extension_init_data = {
        health_system = {
            health = health,
        },
        death_system = {
            death_reaction_template = "level_object",
            is_husk = true,
        },
        hit_reaction_system = {
            hit_reaction_template = "level_object",
            is_husk = true,
        },
    }

    return unit_template_name, extension_init_data
end


return unit_go_sync_functions