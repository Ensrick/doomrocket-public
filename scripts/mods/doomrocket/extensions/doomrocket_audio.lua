local mod = get_mod("doomrocket")

local BANK_RESOURCE = "wwise/doomrocket"
local BACKPACK_PLAY_EVENT = "Play_enemy_doomrocket_backpack_loop"
local BACKPACK_STOP_EVENT = "Stop_enemy_doomrocket_backpack_loop"
local LAUNCH_EVENT = "Play_enemy_doomrocket_launch"
local IMPACT_EVENT = "Play_enemy_doomrocket_impact"
local IMPACT_FALLBACK_EVENT = "Play_enemy_combat_warpfire_backpack_explode"
local COMBAT_VOICE_EVENTS = {
	"Play_enemy_doomrocket_voice_01",
	"Play_enemy_doomrocket_voice_02",
	"Play_enemy_doomrocket_voice_03",
	"Play_enemy_doomrocket_voice_04",
	"Play_enemy_doomrocket_voice_05",
	"Play_enemy_doomrocket_voice_laugh_01",
}
local DEATH_VOICE_EVENTS = {
	"Play_enemy_doomrocket_voice_death_01",
	"Play_enemy_doomrocket_voice_death_02",
}
local COMBAT_VOICE_COOLDOWN_SECONDS = 5

-- There is intentionally no flight-loop event yet. The current source set has a launch
-- one-shot, but no dedicated in-flight loop; treating the one-shot as a loop makes every
-- rocket restart the muzzle transient until impact.
mod.doomrocket_sound_bank = BANK_RESOURCE
mod.doomrocket_sound_events = {
	backpack_play = BACKPACK_PLAY_EVENT,
	backpack_stop = BACKPACK_STOP_EVENT,
	launch = LAUNCH_EVENT,
	impact = IMPACT_EVENT,
	combat_voices = COMBAT_VOICE_EVENTS,
	death_voices = DEATH_VOICE_EVENTS,
}

local audio_state = {
	bank_loaded_by_mod = false,
	bank_unavailable_logged = false,
	unverified_events_logged = {},
	impact_event_name = IMPACT_FALLBACK_EVENT,
	backpack_loops = {},
	combat_voice_next_time = setmetatable({}, { __mode = "k" }),
	combat_voice_last_index = setmetatable({}, { __mode = "k" }),
	active_combat_voices = setmetatable({}, { __mode = "k" }),
	death_voice_played = setmetatable({}, { __mode = "k" }),
}

local function peer_role()
	return Managers.player and Managers.player.is_server and "server" or "client"
end

local function audio_runtime_available()
	return not DEDICATED_SERVER and Wwise and WwiseWorld and WwiseUtils
end

local function event_exists(event_name)
	return Wwise.has_event and Wwise.has_event(event_name) or false
end

local function ensure_bank_for_event(event_name)
	if not audio_runtime_available() then
		return false, DEDICATED_SERVER and "dedicated_server" or "runtime_unavailable"
	end

	if event_exists(event_name) then
		return true, "registered"
	end

	if not audio_state.bank_loaded_by_mod then
		if not Application.can_get("wwise_bank", BANK_RESOURCE) then
			if not audio_state.bank_unavailable_logged then
				audio_state.bank_unavailable_logged = true
				printf("[doomrocket:SOUND] phase=bank status=unavailable resource=%s action=silent",
					BANK_RESOURCE)
			end

			return false, "bank_unavailable"
		end

		Wwise.load_bank("wwise/doomrocket")
		audio_state.bank_loaded_by_mod = true
		printf("[doomrocket:SOUND] phase=bank status=loaded resource=%s", BANK_RESOURCE)
	end

	if event_exists(event_name) then
		return true, "registered"
	end

	-- Working VT2 custom-audio mods dispatch bank events directly. Wwise.has_event
	-- depends on project metadata registration and can remain false when the bank
	-- itself loaded successfully, so treat it as diagnostic rather than a mute gate.
	if not audio_state.unverified_events_logged[event_name] then
		audio_state.unverified_events_logged[event_name] = true
		printf("[doomrocket:SOUND] phase=bank status=metadata_unverified resource=%s event=%s action=attempt_playback",
			BANK_RESOURCE, event_name)
	end

	return true, "metadata_unverified"
end

local function valid_playing_id(playing_id)
	return playing_id ~= nil and playing_id ~= 0
end

local function unit_node_or_root(unit, node_name)
	if Unit.has_node(unit, node_name) then
		return Unit.node(unit, node_name)
	end

	return 0
end

-- WwiseUtils requires a world registered with WorldManager. Unit.world(unit) is not a
-- safe substitute: projectile and attachment units can expose a Stingray world handle
-- for which Managers.world:wwise_world returns nil. Validate the managed level world
-- before any call that crosses into the native Wwise plugin.
local function managed_audio_world()
	local world_manager = Managers.world

	if not world_manager or not world_manager:has_world("level_world") then
		return nil, "level_world_unavailable"
	end

	local world = world_manager:world("level_world")
	local wwise_world = world and world_manager:wwise_world(world)

	if not wwise_world then
		return nil, "wwise_world_unavailable"
	end

	return world
end

local function play_voice_event(emitter_unit, event_name, phase, variant)
	if not emitter_unit or not Unit.alive(emitter_unit) then
		printf("[doomrocket:SOUND] phase=%s status=skipped event=%s variant=%s reason=no_live_emitter peer=%s",
			phase, event_name, tostring(variant), peer_role())
		return false
	end

	local available, unavailable_reason = ensure_bank_for_event(event_name)

	if not available then
		printf("[doomrocket:SOUND] phase=%s status=skipped event=%s variant=%s emitter=%s reason=%s peer=%s",
			phase, event_name, tostring(variant), tostring(emitter_unit),
			tostring(unavailable_reason), peer_role())
		return false
	end

	local world, world_reason = managed_audio_world()

	if not world then
		printf("[doomrocket:SOUND] phase=%s status=skipped event=%s variant=%s emitter=%s reason=%s peer=%s",
			phase, event_name, tostring(variant), tostring(emitter_unit), world_reason,
			peer_role())
		return false
	end

	local node_id = unit_node_or_root(emitter_unit, "c_head")
	local source_id, wwise_world = WwiseUtils.make_unit_auto_source(world, emitter_unit, node_id)
	local playing_id = WwiseWorld.trigger_event(wwise_world, event_name, true, source_id)
	local played = valid_playing_id(playing_id)

	printf("[doomrocket:SOUND] phase=%s status=%s event=%s variant=%s emitter=%s node=%d playing_id=%s peer=%s",
		phase, played and "played" or "trigger_rejected", event_name, tostring(variant), tostring(emitter_unit), node_id,
		tostring(playing_id), peer_role())

	return played, playing_id, wwise_world
end

-- The authority chooses one variant and sends that index through the existing rocket
-- launch RPC. A per-owner cooldown makes a three-rocket volley produce one bark rather
-- than three overlapping lines, while every peer still hears the same variant.
mod._choose_warlock_combat_voice = function(owner_unit)
	if not owner_unit or not Unit.alive(owner_unit) then
		return 0
	end

	local now = Application.time_since_launch()
	local next_time = audio_state.combat_voice_next_time[owner_unit] or 0

	if now < next_time then
		return 0
	end

	local count = #COMBAT_VOICE_EVENTS
	local previous = audio_state.combat_voice_last_index[owner_unit]
	local index

	if previous and count > 1 then
		index = math.random(1, count - 1)
		if index >= previous then
			index = index + 1
		end
	else
		index = math.random(1, count)
	end

	audio_state.combat_voice_last_index[owner_unit] = index
	audio_state.combat_voice_next_time[owner_unit] = now + COMBAT_VOICE_COOLDOWN_SECONDS

	return index
end

local function stop_combat_voice_entry(owner_unit, reason)
	local entry = audio_state.active_combat_voices[owner_unit]

	if not entry then
		return false
	end

	-- Clear first so death, despawn and lifecycle cleanup can safely converge.
	audio_state.active_combat_voices[owner_unit] = nil
	local was_playing = entry.playing_id and WwiseWorld.is_playing(entry.wwise_world, entry.playing_id)

	if was_playing then
		WwiseWorld.stop_event(entry.wwise_world, entry.playing_id)
	end

	printf("[doomrocket:SOUND] phase=combat_voice_stop status=%s event=%s owner=%s reason=%s peer=%s",
		was_playing and "stopped" or "already_complete", tostring(entry.event_name),
		tostring(owner_unit), tostring(reason), peer_role())

	return true
end

mod._play_warlock_combat_voice = function(owner_unit, variant)
	local event_name = COMBAT_VOICE_EVENTS[variant]

	if not event_name then
		if variant and variant ~= 0 then
			printf("[doomrocket:SOUND] phase=combat_voice status=skipped variant=%s reason=invalid_variant peer=%s",
				tostring(variant), peer_role())
		end
		return false
	end

	stop_combat_voice_entry(owner_unit, "replacement")

	local played, playing_id, wwise_world = play_voice_event(owner_unit, event_name, "combat_voice", variant)

	if played then
		audio_state.active_combat_voices[owner_unit] = {
			wwise_world = wwise_world,
			playing_id = playing_id,
			event_name = event_name,
		}
	end

	return played
end

mod._play_warlock_death_voice = function(owner_unit)
	if not owner_unit or not Unit.alive(owner_unit) or audio_state.death_voice_played[owner_unit] then
		return false
	end

	-- The death take replaces speech; never allow an earlier attack bark to talk
	-- over the corpse or over the custom death voice.
	stop_combat_voice_entry(owner_unit, "death")

	-- Network game-object IDs are stable on every peer, so the same corpse selects the
	-- same take without adding a second death-only RPC. Fall back to random only for an
	-- unexpected local/non-network unit.
	local unit_storage = Managers.state and Managers.state.unit_storage
	local go_id = unit_storage and unit_storage:go_id(owner_unit)
	local variant = go_id and go_id % #DEATH_VOICE_EVENTS + 1
		or math.random(1, #DEATH_VOICE_EVENTS)
	local event_name = DEATH_VOICE_EVENTS[variant]

	-- Claim the death before touching Wwise. Both pre-start and later cleanup paths can
	-- be reached during unusual death ordering, and a missing bank must stay silent rather
	-- than retrying the second take on the same corpse.
	audio_state.death_voice_played[owner_unit] = true
	local played, playing_id = play_voice_event(owner_unit, event_name, "death_voice", variant)

	if played then
		local hit_reaction_extension = ScriptUnit.has_extension(owner_unit, "hit_reaction_system")
		if hit_reaction_extension then
			hit_reaction_extension:set_death_sound_event_id(playing_id)
		end
	end

	return played
end

local function stop_backpack_entry(owner_unit, reason)
	local entry = audio_state.backpack_loops[owner_unit]

	if not entry then
		return false
	end

	-- Clear first so repeated death/despawn/state-exit paths are idempotent even if an
	-- authored stop event itself causes another lifecycle callback.
	audio_state.backpack_loops[owner_unit] = nil

	local stop_method = "auto_source_gone"
	local source_is_live = entry.outfit_unit and Unit.alive(entry.outfit_unit)

	if source_is_live then
		local stop_event_available = ensure_bank_for_event(BACKPACK_STOP_EVENT)

		if stop_event_available then
			WwiseWorld.trigger_event(entry.wwise_world, BACKPACK_STOP_EVENT, true, entry.source_id)
			stop_method = "stop_event"
		elseif entry.playing_id and WwiseWorld.is_playing(entry.wwise_world, entry.playing_id) then
			-- A malformed/incomplete bank must not leave a loop running forever. This is a
			-- silent hard-stop fallback, never a mismatched vanilla audible stop-tail.
			WwiseWorld.stop_event(entry.wwise_world, entry.playing_id)
			stop_method = "hard_stop_missing_contract"
		end
	elseif entry.playing_id and WwiseWorld.is_playing(entry.wwise_world, entry.playing_id) then
		-- Unit auto-sources normally disappear with their unit. Cover an engine ordering
		-- edge where the unit is already dead but its playing ID still survives this frame.
		WwiseWorld.stop_event(entry.wwise_world, entry.playing_id)
		stop_method = "hard_stop_dead_source"
	end

	printf("[doomrocket:SOUND] phase=backpack_stop status=complete event=%s owner=%s outfit=%s reason=%s method=%s peer=%s",
		BACKPACK_STOP_EVENT, tostring(owner_unit), tostring(entry.outfit_unit), tostring(reason),
		stop_method, peer_role())

	return true
end

mod._start_warlock_backpack_sound = function(owner_unit, outfit_unit)
	if not owner_unit or not Unit.alive(owner_unit) or not outfit_unit or not Unit.alive(outfit_unit) then
		return false
	end

	local existing = audio_state.backpack_loops[owner_unit]

	if existing and existing.outfit_unit == outfit_unit then
		return true
	elseif existing then
		stop_backpack_entry(owner_unit, "outfit_replaced")
	end

	local available, unavailable_reason = ensure_bank_for_event(BACKPACK_PLAY_EVENT)

	if not available then
		printf("[doomrocket:SOUND] phase=backpack_start status=skipped event=%s owner=%s reason=%s peer=%s",
			BACKPACK_PLAY_EVENT, tostring(owner_unit), tostring(unavailable_reason), peer_role())
		return false
	end

	local world, world_reason = managed_audio_world()

	if not world then
		printf("[doomrocket:SOUND] phase=backpack_start status=skipped event=%s owner=%s reason=%s peer=%s",
			BACKPACK_PLAY_EVENT, tostring(owner_unit), world_reason, peer_role())
		return false
	end

	local node_id = unit_node_or_root(outfit_unit, "j_backpack")
	local source_id, wwise_world = WwiseUtils.make_unit_auto_source(world, outfit_unit, node_id)
	local playing_id = WwiseWorld.trigger_event(wwise_world, BACKPACK_PLAY_EVENT, true, source_id)

	if not valid_playing_id(playing_id) then
		printf("[doomrocket:SOUND] phase=backpack_start status=trigger_rejected event=%s owner=%s outfit=%s node=%d playing_id=%s peer=%s",
			BACKPACK_PLAY_EVENT, tostring(owner_unit), tostring(outfit_unit), node_id,
			tostring(playing_id), peer_role())

		return false
	end

	audio_state.backpack_loops[owner_unit] = {
		outfit_unit = outfit_unit,
		wwise_world = wwise_world,
		source_id = source_id,
		playing_id = playing_id,
	}

	printf("[doomrocket:SOUND] phase=backpack_start status=played event=%s owner=%s outfit=%s node=%d playing_id=%s peer=%s",
		BACKPACK_PLAY_EVENT, tostring(owner_unit), tostring(outfit_unit), node_id,
		tostring(playing_id), peer_role())

	return true
end

mod._stop_warlock_backpack_sound = function(owner_unit, reason)
	return stop_backpack_entry(owner_unit, reason or "unspecified")
end

mod._stop_all_warlock_backpack_sounds = function(reason)
	local owners = {}

	for owner_unit, _ in pairs(audio_state.backpack_loops) do
		owners[#owners + 1] = owner_unit
	end

	for i = 1, #owners do
		stop_backpack_entry(owners[i], reason or "stop_all")
	end
end

mod._stop_all_warlock_combat_voices = function(reason)
	local owners = {}

	for owner_unit, _ in pairs(audio_state.active_combat_voices) do
		owners[#owners + 1] = owner_unit
	end

	for i = 1, #owners do
		stop_combat_voice_entry(owners[i], reason or "stop_all")
	end
end

mod._update_warlock_backpack_sounds = function()
	local stopped_owners = {}
	local stopped_reasons = {}

	for owner_unit, entry in pairs(audio_state.backpack_loops) do
		if not Unit.alive(owner_unit) then
			stopped_owners[#stopped_owners + 1] = owner_unit
			stopped_reasons[#stopped_reasons + 1] = "owner_not_alive"
		elseif not entry.outfit_unit or not Unit.alive(entry.outfit_unit) then
			stopped_owners[#stopped_owners + 1] = owner_unit
			stopped_reasons[#stopped_reasons + 1] = "outfit_not_alive"
		end
	end

	for i = 1, #stopped_owners do
		stop_backpack_entry(stopped_owners[i], stopped_reasons[i])
	end
end

mod._play_doomrocket_launch_sound = function(emitter_unit)
	if not emitter_unit or not Unit.alive(emitter_unit) then
		printf("[doomrocket:SOUND] phase=launch status=skipped event=%s reason=no_live_emitter peer=%s",
			LAUNCH_EVENT, peer_role())
		return false
	end

	local available, unavailable_reason = ensure_bank_for_event(LAUNCH_EVENT)

	if not available then
		printf("[doomrocket:SOUND] phase=launch status=skipped event=%s emitter=%s reason=%s peer=%s",
			LAUNCH_EVENT, tostring(emitter_unit), tostring(unavailable_reason), peer_role())
		return false
	end

	local world, world_reason = managed_audio_world()

	if not world then
		printf("[doomrocket:SOUND] phase=launch status=skipped event=%s emitter=%s reason=%s peer=%s",
			LAUNCH_EVENT, tostring(emitter_unit), world_reason, peer_role())
		return false
	end

	local node_id = unit_node_or_root(emitter_unit, "p_fx")
	local source_id, wwise_world = WwiseUtils.make_unit_auto_source(world, emitter_unit, node_id)
	local playing_id = WwiseWorld.trigger_event(wwise_world, LAUNCH_EVENT, true, source_id)
	local played = valid_playing_id(playing_id)

	printf("[doomrocket:SOUND] phase=launch status=%s event=%s emitter=%s node=%d playing_id=%s peer=%s",
		played and "played" or "trigger_rejected", LAUNCH_EVENT, tostring(emitter_unit), node_id,
		tostring(playing_id), peer_role())

	return played
end

-- Configure the replicated explosion template once per peer. The unique metadata
-- resource avoids the base game's generic project path, while bank-loaded events
-- remain playable even if Wwise.has_event has not refreshed its registry yet.
mod._doomrocket_select_impact_event = function()
	local available, unavailable_reason = ensure_bank_for_event(IMPACT_EVENT)
	local selected_event = available and IMPACT_EVENT or IMPACT_FALLBACK_EVENT
	audio_state.impact_event_name = selected_event

	printf("[doomrocket:SOUND] phase=impact_config status=%s custom_event=%s selected_event=%s reason=%s peer=%s",
		available and "custom" or "fallback", IMPACT_EVENT, selected_event,
		tostring(unavailable_reason or "none"), peer_role())

	return selected_event
end

-- Playback belongs exclusively to AreaDamageSystem/DamageUtils via the explosion
-- template. This authority-side message records the dispatch without playing twice.
mod._doomrocket_sound_impact_requested = function(position)
	printf("[doomrocket:SOUND] phase=impact status=template_dispatch selected_event=%s position=%s peer=%s",
		audio_state.impact_event_name, tostring(position), peer_role())
end

mod._shutdown_doomrocket_audio = function(reason, unload_bank)
	mod._stop_all_warlock_backpack_sounds(reason or "shutdown")
	mod._stop_all_warlock_combat_voices(reason or "shutdown")
	audio_state.combat_voice_next_time = setmetatable({}, { __mode = "k" })
	audio_state.combat_voice_last_index = setmetatable({}, { __mode = "k" })
	audio_state.active_combat_voices = setmetatable({}, { __mode = "k" })
	audio_state.death_voice_played = setmetatable({}, { __mode = "k" })

	if unload_bank and audio_state.bank_loaded_by_mod then
		Wwise.unload_bank("wwise/doomrocket")
		audio_state.bank_loaded_by_mod = false
		printf("[doomrocket:SOUND] phase=bank status=unloaded resource=%s reason=%s",
			BANK_RESOURCE, tostring(reason))
	end
end
