-- Native NetworkLookup is built before mod breeds are added. AISystem sends
-- blackboard.action.name for every living AI, including a failed relocation;
-- its missing-key metatable throws before the network field can be written.
-- Register on every peer at mod load, never on a host-only action transition.
local lookup = NetworkLookup.bt_action_names
local custom_actions = { "fire_rocket", "reposition" }

for _, action_name in ipairs(custom_actions) do
	-- Ordinary lookup[action_name] is not a membership test: absent keys throw.
	local action_id = rawget(lookup, action_name)

	if action_id == nil then
		action_id = #lookup + 1
		lookup[action_id] = action_name
		lookup[action_name] = action_id
	else
		assert(rawget(lookup, action_id) == action_name,
			"Doomrocket: inconsistent bt_action_names entry for " .. action_name)
	end
end

printf("[doomrocket:COMBAT] phase=network_actions_registered fire_rocket=%d reposition=%d",
	lookup.fire_rocket, lookup.reposition)
