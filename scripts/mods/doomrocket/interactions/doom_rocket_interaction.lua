local mod = get_mod("doomrocket")

local num_interacts = #NetworkLookup.interactions


NetworkLookup.interactions["doom_rocket"] = num_interacts+1
NetworkLookup.interactions[num_interacts + 1] = "doom_rocket"

InteractionHelper = InteractionHelper or {}
InteractionHelper.interactions.doom_rocket = {}
for _, config_table in pairs(InteractionHelper.interactions) do
	config_table.request_rpc = config_table.request_rpc or "rpc_generic_interaction_request"
end


InteractionDefinitions["doom_rocket"] = InteractionDefinitions.doom_rocket or table.clone(InteractionDefinitions.smartobject)
InteractionDefinitions.doom_rocket.config.swap_to_3p = false

InteractionDefinitions.doom_rocket.config.request_rpc = "rpc_generic_interaction_request"

InteractionDefinitions.doom_rocket.server.stop = function (world, interactor_unit, interactable_unit, data, config, t, result)
    if result == InteractionResult.SUCCESS then
        local interactable_system = ScriptUnit.extension(interactable_unit, "interactable_system")
        interactable_system.num_times_successfully_completed = interactable_system.num_times_successfully_completed + 1

    end
end

InteractionDefinitions.doom_rocket.client.can_interact = function (interactor_unit, interactable_unit, data, config)

    return false
end

InteractionDefinitions.doom_rocket.server.can_interact = function (interactor_unit, interactable_unit)

    return false
end

InteractionDefinitions.doom_rocket.client.stop = function (world, interactor_unit, interactable_unit, data, config, t, result)
	data.start_time = nil

	if result == InteractionResult.SUCCESS and not data.is_husk then
	    if interactable_unit then
            print("boom")
        end

	end
end


InteractionDefinitions.doom_rocket.replacement_rpc = function(interactable_unit)
    if interactable_unit then
        mod.interactable_unit = interactable_unit
        mod:handle_transition("open_quest_board_letter_view")
        return true
    end
end

InteractionDefinitions.doom_rocket.client.hud_description = function (interactable_unit, data, config, fail_reason, interactor_unit)
    return Unit.get_data(interactable_unit, "interaction_data", "hud_interaction_action"), Unit.get_data(interactable_unit, "interaction_data", "hud_description")
end