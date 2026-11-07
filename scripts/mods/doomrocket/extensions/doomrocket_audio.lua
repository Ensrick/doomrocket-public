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
	active_combat_voices = {},
	active_launch_sounds = {},
	pending_stops = {},
	retired_owners = setmetatable({}, { __mode = "k" }),
	owner_ids = setmetatable({}, { __mode = "k" }),
	next_owner_id = 0,
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

local function owner_id(owner)
	local id = audio_state.owner_ids[owner]
	if not id then
		audio_state.next_owner_id = audio_state.next_owner_id + 1
		id = audio_state.next_owner_id
		audio_state.owner_ids[owner] = id
	end
	return id
end

local function living_owner(owner)
	if not owner or not Unit.alive(owner) or audio_state.retired_owners[owner] then
		return false
	end
	-- Unit.alive remains true while the corpse is retained. The native health
	-- extension, unlike an engine-unit existence check, records the killing blow.
	local health = ScriptUnit.has_extension(owner, "health_system")
	return not health or not health.is_alive or health:is_alive()
end

local function known_audio_world(entry)
	local manager = Managers.world
	return entry.world and manager and
		(manager:has_world("level_world") and manager:world("level_world") == entry.world
		or manager._disabled_worlds and manager._disabled_worlds.level_world == entry.world)
end

local function stop_playing_id(entry, phase, reason)
	if not known_audio_world(entry) then
		printf("[doomrocket:SOUND] phase=%s status=world_gone owner_id=%s playing_id=%s reason=%s peer=%s",
			phase, tostring(entry.owner_id), tostring(entry.playing_id), tostring(reason), peer_role())
		return false
	end
	if not WwiseWorld.is_playing(entry.wwise_world, entry.playing_id) then
		return false
	end
	-- Native VT2 dialogue/corruptor cleanup uses this exact playing-ID API. Keep
	-- the ID until a later update observes silence: posting an event is not proof
	-- that the loop stopped, and Wwise may process stop requests asynchronously.
	entry.stop_phase = phase
	entry.stop_reason = reason
	entry.next_stop_at = Application.time_since_launch() + 0.25
	entry.stop_attempts = 1
	audio_state.pending_stops[entry.playing_id] = entry
	WwiseWorld.stop_event(entry.wwise_world, entry.playing_id)
	printf("[doomrocket:SOUND] phase=%s status=stop_requested owner_id=%s playing_id=%s reason=%s method=playing_id peer=%s",
		phase, tostring(entry.owner_id), tostring(entry.playing_id), tostring(reason), peer_role())
	return true
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

	return played, playing_id, wwise_world, world
end

-- The authority chooses one variant and sends that index through the existing rocket
-- launch RPC. A per-owner cooldown makes a three-rocket volley produce one bark rather
-- than three overlapping lines, while every peer still hears the same variant.
mod._choose_warlock_combat_voice = function(owner_unit)
	if not living_owner(owner_unit) then
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
	stop_playing_id(entry, "combat_voice_stop", reason)

	return true
end

mod._play_warlock_combat_voice = function(owner_unit, variant)
	if not living_owner(owner_unit) then
		return false
	end
	local event_name = COMBAT_VOICE_EVENTS[variant]

	if not event_name then
		if variant and variant ~= 0 then
			printf("[doomrocket:SOUND] phase=combat_voice status=skipped variant=%s reason=invalid_variant peer=%s",
				tostring(variant), peer_role())
		end
		return false
	end

	stop_combat_voice_entry(owner_unit, "replacement")

	local played, playing_id, wwise_world, world = play_voice_event(owner_unit, event_name, "combat_voice", variant)

	if played then
		audio_state.active_combat_voices[owner_unit] = {
			wwise_world = wwise_world,
			world = world,
			playing_id = playing_id,
			event_name = event_name,
			owner_id = owner_id(owner_unit),
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
	mod._stop_warlock_living_sounds(owner_unit, "death")

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

	-- Stop the exact instance even while its outfit is alive. An authored stop
	-- event/source can be rejected or rebound; it must not be our sole cleanup.
	stop_playing_id(entry, "backpack_stop", reason)

	return true
end

mod._start_warlock_backpack_sound = function(owner_unit, outfit_unit)
	if not living_owner(owner_unit) or not outfit_unit or not Unit.alive(outfit_unit) then
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
		world = world,
		source_id = source_id,
		playing_id = playing_id,
		owner_id = owner_id(owner_unit),
	}

	printf("[doomrocket:SOUND] phase=backpack_start status=played event=%s owner=%s outfit=%s node=%d playing_id=%s peer=%s owner_id=%s",
		BACKPACK_PLAY_EVENT, tostring(owner_unit), tostring(outfit_unit), node_id,
		tostring(playing_id), peer_role(), tostring(owner_id(owner_unit)))

	return true
end

mod._stop_warlock_backpack_sound = function(owner_unit, reason)
	return stop_backpack_entry(owner_unit, reason or "unspecified")
end

local function stop_launch_sounds(owner, reason)
	local entries = audio_state.active_launch_sounds[owner]
	audio_state.active_launch_sounds[owner] = nil
	for _, entry in ipairs(entries or {}) do
		stop_playing_id(entry, "launch_stop", reason)
	end
end

mod._stop_warlock_living_sounds = function(owner, reason)
	if not owner then
		return
	end
	-- Late launch/configuration callbacks must never restart machinery or speech
	-- on a retained corpse after the death/inventory lifetime has ended.
	audio_state.retired_owners[owner] = true
	stop_backpack_entry(owner, reason)
	stop_combat_voice_entry(owner, reason)
	stop_launch_sounds(owner, reason)
end

-- Unit-keyed records outlive the unit: weak keys do not release engine unit
-- handles, and a destroyed handle may later name a new Engineer. Once its
-- playing IDs are stopped at inventory destruction, forget the lifetime so a
-- reused handle is not treated as a retired corpse or an already-dead voice.
mod._forget_warlock_audio_owner = function(owner)
	if not owner then
		return
	end
	audio_state.retired_owners[owner] = nil
	audio_state.owner_ids[owner] = nil
	audio_state.death_voice_played[owner] = nil
	audio_state.combat_voice_next_time[owner] = nil
	audio_state.combat_voice_last_index[owner] = nil
end

local function update_pending_stops()
	local now = Application.time_since_launch()
	for id, entry in pairs(audio_state.pending_stops) do
		if not known_audio_world(entry) then
			audio_state.pending_stops[id] = nil
		elseif not WwiseWorld.is_playing(entry.wwise_world, id) then
			audio_state.pending_stops[id] = nil
			printf("[doomrocket:SOUND] phase=%s status=stopped owner_id=%s playing_id=%s reason=%s attempts=%d peer=%s",
				entry.stop_phase, tostring(entry.owner_id), tostring(id), tostring(entry.stop_reason),
				entry.stop_attempts, peer_role())
		elseif now >= entry.next_stop_at then
			-- Retain ownership until Wwise confirms silence. Retry quietly; report
			-- once if the first second did not stop it, instead of logging success.
			entry.stop_attempts = entry.stop_attempts + 1
			entry.next_stop_at = now + (entry.stop_attempts < 5 and 0.25 or 1)
			WwiseWorld.stop_event(entry.wwise_world, id)
			if entry.stop_attempts == 5 then
				printf("[doomrocket:SOUND] phase=%s status=still_playing owner_id=%s playing_id=%s reason=%s peer=%s",
					entry.stop_phase, tostring(entry.owner_id), tostring(id), tostring(entry.stop_reason), peer_role())
			end
		end
	end
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
	update_pending_stops()
	local stopped_owners = {}
	local stopped_reasons = {}
	local owners = {}
	for owner in pairs(audio_state.backpack_loops) do owners[owner] = true end
	for owner in pairs(audio_state.active_combat_voices) do owners[owner] = true end
	for owner in pairs(audio_state.active_launch_sounds) do owners[owner] = true end

	for owner_unit in pairs(owners) do
		local entry = audio_state.backpack_loops[owner_unit]
		if not living_owner(owner_unit) then
			stopped_owners[#stopped_owners + 1] = owner_unit
			stopped_reasons[#stopped_reasons + 1] = "owner_not_living"
		elseif entry and (not entry.outfit_unit or not Unit.alive(entry.outfit_unit)) then
			stopped_owners[#stopped_owners + 1] = owner_unit
			stopped_reasons[#stopped_reasons + 1] = "outfit_not_alive"
		else
			local voice = audio_state.active_combat_voices[owner_unit]
			if voice and (not known_audio_world(voice) or not WwiseWorld.is_playing(voice.wwise_world, voice.playing_id)) then
				audio_state.active_combat_voices[owner_unit] = nil
			end
			local launches = audio_state.active_launch_sounds[owner_unit]
			for i = #(launches or {}), 1, -1 do
				local shot = launches[i]
				if not known_audio_world(shot) or not WwiseWorld.is_playing(shot.wwise_world, shot.playing_id) then
					table.remove(launches, i)
				end
			end
			if launches and #launches == 0 then audio_state.active_launch_sounds[owner_unit] = nil end
		end
	end

	for i = 1, #stopped_owners do
		mod._stop_warlock_living_sounds(stopped_owners[i], stopped_reasons[i])
	end
end

mod._play_doomrocket_launch_sound = function(emitter_unit, owner_unit)
	if not living_owner(owner_unit) then
		return false
	end
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
	if played then
		local entries = audio_state.active_launch_sounds[owner_unit] or {}
		entries[#entries + 1] = {
			wwise_world = wwise_world, world = world, playing_id = playing_id,
			owner_id = owner_id(owner_unit),
		}
		audio_state.active_launch_sounds[owner_unit] = entries
	end

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
	local launch_owners = {}
	for owner in pairs(audio_state.active_launch_sounds) do launch_owners[#launch_owners + 1] = owner end
	for _, owner in ipairs(launch_owners) do stop_launch_sounds(owner, reason or "shutdown") end
	audio_state.combat_voice_next_time = setmetatable({}, { __mode = "k" })
	audio_state.combat_voice_last_index = setmetatable({}, { __mode = "k" })
	audio_state.active_combat_voices = {}
	audio_state.death_voice_played = setmetatable({}, { __mode = "k" })

	if unload_bank and audio_state.bank_loaded_by_mod then
		Wwise.unload_bank("wwise/doomrocket")
		audio_state.bank_loaded_by_mod = false
		printf("[doomrocket:SOUND] phase=bank status=unloaded resource=%s reason=%s",
			BANK_RESOURCE, tostring(reason))
	end
end

mod._release_warlock_audio_world = function(world)
	-- Called before the native world release. Stop remaining owned IDs while
	-- the Wwise handle is valid, then forget them so no later update touches it.
	local owners = {}
	for owner, entry in pairs(audio_state.backpack_loops) do
		if entry.world == world then owners[owner] = true end
	end
	for owner, entry in pairs(audio_state.active_combat_voices) do
		if entry.world == world then owners[owner] = true end
	end
	for owner, entries in pairs(audio_state.active_launch_sounds) do
		for _, entry in ipairs(entries) do if entry.world == world then owners[owner] = true end end
	end
	for owner in pairs(owners) do mod._stop_warlock_living_sounds(owner, "world_release") end
	for id, entry in pairs(audio_state.pending_stops) do
		if entry.world == world then audio_state.pending_stops[id] = nil end
	end
end
