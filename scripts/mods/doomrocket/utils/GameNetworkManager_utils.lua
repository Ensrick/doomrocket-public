local mod = get_mod("doomrocket")
local game_object_templates = dofile("scripts/mods/doomrocket/utils/game_object_templates")


NetworkLookup.go_types = NetworkLookup.go_types or {}

local go_types_to_add = {
    "doomrocket_projectile",
    "ai_unit_doomrocket",
}
local num_go_types = #NetworkLookup.go_types
for i, go_type in ipairs(go_types_to_add) do
    NetworkLookup.go_types[num_go_types + i] = go_type
    NetworkLookup.go_types[go_type] = num_go_types + i
end

-- local modded_go_types = {
-- 	doomrocket_projectile = "destructible_objective_unit",
-- }

-- mod:hook(GameSession, 'create_game_object', function(func, game_session, go_type, go_init_data)
-- 	if modded_go_types[go_type] then
-- 		go_type = modded_go_types[go_type]
-- 	end
-- 	return func(game_session, go_type, go_init_data)
-- end)

-- mod:hook(Network, 'config_hash', function(func, config_name)
--     return func("scripts/mods/doomrocket/utils/doomrocket")
-- end)

-- Only our own go_types resolve against the mod's table; everything else falls through
-- to vanilla. The mod's copy of game_object_templates is from 2024 and no longer has
-- explosive_barrel_socket, dark_pact_horde_ability, or the current merged `objective`
-- entry, so answering for every go_type nil-deref'd those objects for the whole lobby.
local DOOMROCKET_GO_TYPES = {
	ai_unit_doomrocket = true,
	doomrocket_projectile = true,
}

mod:hook(GameNetworkManager, 'game_object_template',  function (old_func, self, go_type)
    if DOOMROCKET_GO_TYPES[go_type] then
        return game_object_templates[go_type]
    end

    return old_func(self, go_type)
end)

-- Network.config_hash("scripts/mods/doomrocket/utils/doomrocket")
-- local game_session = Network.game_session()
-- GameSession.create_game_object(game_session, "doomrocket_projectile", {})

mod:hook(GameNetworkManager, 'game_object_created',  function (old_func, self, go_id, owner_id)
    local go_type_id = GameSession.game_object_field(self.game_session, go_id, "go_type")
	local go_type = NetworkLookup.go_types[go_type_id]

	if not DOOMROCKET_GO_TYPES[go_type] then
		return old_func(self, go_id, owner_id)
	end

	local go_template = game_object_templates[go_type]
	local go_created_func_name = go_template.game_object_created_func_name
	local session_disconnect_func_name = go_template.game_session_disconnect_func_name

	if session_disconnect_func_name then
		local function cb(game_object_id)
			self[session_disconnect_func_name](self, game_object_id)
		end

		self._game_object_disconnect_callbacks[go_id] = cb
	end

	local go_created_func = self[go_created_func_name]

	assert(go_created_func)
	go_created_func(self, go_id, owner_id, go_template)
end)

mod:hook(GameNetworkManager, 'game_object_destroyed',  function (old_func, self, go_id, owner_id)
    local go_type_id = GameSession.game_object_field(self.game_session, go_id, "go_type")
	local go_type = NetworkLookup.go_types[go_type_id]

	if not DOOMROCKET_GO_TYPES[go_type] then
		return old_func(self, go_id, owner_id)
	end

	local go_template = game_object_templates[go_type]
	local go_destroyed_func_name = go_template.game_object_destroyed_func_name
	local go_destroyed_func = self[go_destroyed_func_name]

	go_destroyed_func(self, go_id, owner_id, go_template)

	self._game_object_disconnect_callbacks[go_id] = nil

end)


-- mod:hook(EntitySystem, '_init_systems', function(func, self, entity_system_creation_context)
--     mod:echo('pioopsarjtgffhosartpenmbghijahoen')mod:echo('pioopsarjtgffhosartpenmbghijahoen')
--     mod:echo('pioopsarjtgffhosartpenmbghijahoen')
--     mod:echo('pioopsarjtgffhosartpenmbghijahoen')
--     mod:echo('pioopsarjtgffhosartpenmbghijahoen')
--     mod:echo('pioopsarjtgffhosartpenmbghijahoen')
--     mod:echo('pioopsarjtgffhosartpenmbghijahoen')
--     return func(self, entity_system_creation_context)
-- end)

-- mod:hook(GameNetworkManager, 'game_object_template',  function (old_func, self, go_type)
--     mod:echo(go_type)
--     return old_func(self, go_type)
-- end)
