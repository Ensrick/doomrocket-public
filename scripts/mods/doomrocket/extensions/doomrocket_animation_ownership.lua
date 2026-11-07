local mod = get_mod("doomrocket")

-- Only the generated, hash-bound companion can activate authored playback.
-- The supported graph has one layer and direct event transitions. Events are
-- observed on the visible outfit, never inferred from the carrier's clip IDs.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local entries = {}

local function finite(n)
	return type(n) == "number" and n == n and math.abs(n) < math.huge
end

local function data(unit, key)
	local ok, value = pcall(Unit.get_data, unit, key)
	if ok then return value, true end
	return nil, false
end

local function valid_binding(owner, entry)
	return owner and Unit.alive(owner) and Unit.alive(entry.outfit)
		and Unit.world(owner) == entry.world and Unit.world(entry.outfit) == entry.world
		and mod._warlock_outfits and mod._warlock_outfits[owner] == entry.outfit
end

local function health(owner)
	return HEALTH_ALIVE and HEALTH_ALIVE[owner]
end

local function health_ready(owner, entry)
	local alive = health(owner)
	if alive == true then
		if entry then entry.awaiting_health = false end
		return true
	end
	-- Inventory is constructed before HealthSystem publishes this cache. Keep
	-- only read-only registration/events during that first nil interval. Once
	-- health has been observed, its removal must never reopen startup tracking.
	if entry and (alive ~= nil or not entry.awaiting_health) then entries[owner] = nil end
	return false
end

local function accepted(profile)
	if type(profile) ~= "table" or profile.unit ~= OUTFIT
		or (profile.accessory_skin ~= nil and profile.accessory_skin ~= "localized-v1")
		or type(profile.manifest_id) ~= "string" or #profile.manifest_id ~= 64
		or not profile.manifest_id:match("^[0-9a-f]+$")
		or type(profile.states) ~= "table" or not profile.states[profile.default_state]
		or not finite(profile.max_blend_time) or profile.max_blend_time < 0
		or profile.max_blend_time > 1
		or (profile.auxiliary_events ~= nil and type(profile.auxiliary_events) ~= "table")
		or (profile.cross_owner_transition_policy ~= nil and profile.cross_owner_transition_policy ~= "cut"
			and profile.cross_owner_transition_policy ~= "snapshot-blend-v1") then
		return false
	end
	if profile.cross_owner_transition_policy == "snapshot-blend-v1" then
		if profile.sampler_state_machine ~= OUTFIT .. "/presentation_sampler"
			or type(profile.bone_names) ~= "table" or #profile.bone_names ~= 138 then return false end
		local names = {}
		for _, name in ipairs(profile.bone_names) do
			if type(name) ~= "string" or name == "" or names[name] then return false end
			names[name] = true
		end
	end
	for name, state in pairs(profile.states) do
		if type(name) ~= "string" or type(state) ~= "table" or type(state.clip) ~= "string"
			or (state.owner ~= "authored" and state.owner ~= "legacy")
			or (state.speed ~= "authored" and state.speed ~= "measured")
			or type(state.visible_aim) ~= "boolean" or type(state.transitions) ~= "table"
			or (state.owner == "authored" and state.visible_aim and state.aim_policy ~= "gameplay")
			or (name == "base/death" and state.owner ~= "legacy") then return false end
		if profile.cross_owner_transition_policy == "snapshot-blend-v1"
			and type(state.loop_animation) ~= "boolean" then return false end
		for event, transition in pairs(state.transitions) do
			if type(event) ~= "string" or type(transition) ~= "table"
				or type(profile.states[transition.to]) ~= "table" or not finite(transition.blend_time)
				or transition.blend_time < 0 or transition.blend_time > profile.max_blend_time then
				return false
			end
			if profile.cross_owner_transition_policy == "cut"
				and state.owner ~= profile.states[transition.to].owner and transition.blend_time ~= 0 then
				return false
			end
		end
	end
	return true
end

function mod._start_warlock_animation_ownership(owner, outfit)
	if mod._stop_warlock_animation_blend then mod._stop_warlock_animation_blend(owner) end
	if owner then entries[owner] = nil end
	if not owner or not outfit or not Unit.alive(owner) or not Unit.alive(outfit)
		or (health(owner) ~= nil and health(owner) ~= true)
		or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= outfit
		or data(outfit, "unit_name") ~= OUTFIT then return false end
	local world = Unit.world(owner)
	if not world or Unit.world(outfit) ~= world then return false end
	local marker, readable = data(outfit, "warlock_rig_profile")
	local entry = { outfit = outfit, world = world, protected = 0, blocked = false,
		awaiting_health = health(owner) ~= true }
	entries[owner] = entry
	if not readable then entry.blocked = true; return false end
	if marker == nil then return false end
	-- A marked unit without its matching trusted companion fails closed. It must
	-- never silently fall back to overwriting a possibly authored upper body.
	entry.blocked = true
	local manifest = mod._warlock_animation_manifest
	local profile = type(manifest) == "table" and manifest.schema == 1 and type(manifest.profiles) == "table"
		and manifest.profiles[marker]
	if not accepted(profile) or data(outfit, "warlock_animation_manifest_id") ~= profile.manifest_id then
		return false
	end
	entry.profile, entry.profile_id, entry.state = profile, marker, profile.default_state
	entry.blocked = false
	if profile.cross_owner_transition_policy == "snapshot-blend-v1" then
		if not mod._start_warlock_animation_blend or not mod._start_warlock_animation_blend(owner, outfit, profile) then
			entry.blocked = true
			return false
		end
	end
	return true
end

function mod._note_warlock_animation_ownership_event(owner, event, mirrored)
	local entry = entries[owner]
	if not entry then return end
	if not valid_binding(owner, entry) then entries[owner] = nil; return end
	if not health_ready(owner, entry) and entries[owner] ~= entry then return end
	local profile = entry.profile
	if not profile then return end
	local state = profile.states[entry.state]
	local protected = state.owner == "authored" or entry.protected > 0 or entry.unknown_authored
	if mirrored ~= true then
		if not protected then entry.blocked = true end
		return
	end
	local transition = state.transitions[event]
	if not transition then
		-- Declared auxiliary events do not change state. Unknown events cannot
		-- relinquish existing authored ownership, including an outgoing blend.
		if not (profile.auxiliary_events and profile.auxiliary_events[event]) then
			if protected then entry.unknown_authored = true
			else entry.blocked = true end
		end
		return
	end
	local destination = profile.states[transition.to]
	if profile.cross_owner_transition_policy == "snapshot-blend-v1" then
		if not mod._note_warlock_animation_blend_event
			or not mod._note_warlock_animation_blend_event(owner, event, entry.state, transition.to, transition.blend_time) then
			entry.blocked, entry.unknown_authored = true, true
			return
		end
	end
	local ownership_cut = profile.cross_owner_transition_policy == "cut"
		and state.owner ~= destination.owner and transition.blend_time == 0
	if profile.cross_owner_transition_policy == "snapshot-blend-v1" then
		-- The presentation bridge owns its exact edge duration and native clock
		-- guard. A second maximum-duration timer would suppress legacy correction
		-- after a shorter bridge has already returned to its native endpoint.
		entry.protected, entry.protected_speed, entry.protected_aim = 0, nil, nil
	elseif ownership_cut then
		-- The generated controller and its compiled metadata guarantee this
		-- exact direct edge has no outgoing contribution. This avoids blending
		-- dormant legacy accessory poses into an authored localized skin.
		entry.protected, entry.protected_speed, entry.protected_aim = 0, nil, nil
	elseif protected and destination.owner ~= "authored" then
		entry.protected_speed = state.owner == "authored" and state.speed or entry.protected_speed
		if state.owner == "authored" then entry.protected_aim = state.visible_aim end
		entry.protected = math.max(entry.protected, profile.max_blend_time)
	elseif destination.owner == "authored" then
		entry.protected = 0
	end
	entry.state, entry.blocked, entry.unknown_authored = transition.to, false, false
end

function mod._update_warlock_animation_ownership(world, dt)
	for owner, entry in pairs(entries) do
		if not valid_binding(owner, entry) then entries[owner] = nil
		elseif health_ready(owner, entry) and entry.world == world and finite(dt) and dt > 0 and dt <= 0.25 then
			entry.protected = math.max(0, entry.protected - dt)
		end
	end
end

function mod._warlock_animation_ownership(owner, outfit)
	local entry = entries[owner]
	local invalid_binding = owner and not Unit.alive(owner) or entry and not valid_binding(owner, entry)
	if invalid_binding then entries[owner] = nil end
	if not owner or invalid_binding or not health_ready(owner, entry) then
		return { upper_body = "unsupported", weapon = "unsupported", accessories = "unsupported",
			speed = "unsupported", visible_aim = false }
	end
	if entry and outfit and outfit ~= entry.outfit then
		return { upper_body = "unsupported", weapon = "unsupported", accessories = "unsupported",
			speed = "unsupported", visible_aim = false }
	end
	if not entry then
		local candidate = outfit or (mod._warlock_outfits and mod._warlock_outfits[owner])
		local marker, readable
		if candidate and Unit.alive(candidate) then marker, readable = data(candidate, "warlock_rig_profile") end
		if candidate and (not Unit.alive(candidate) or Unit.world(candidate) ~= Unit.world(owner)
			or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= candidate
			or not readable or marker ~= nil) then
			return { upper_body = "unsupported", weapon = "unsupported", accessories = "unsupported",
				speed = "unsupported", visible_aim = false }
		end
		return { upper_body = "legacy", weapon = "legacy", accessories = "unsupported",
			speed = "measured", visible_aim = true }
	end
	local profile = entry.profile
	local state = profile and profile.states[entry.state]
	local bridge = profile and profile.cross_owner_transition_policy == "snapshot-blend-v1"
		and mod._warlock_animation_blend_active and mod._warlock_animation_blend_active(owner)
	local authored = state and (state.owner == "authored" or entry.protected > 0 or entry.unknown_authored or bridge)
	local mode = authored and "authored" or (entry.blocked and "unsupported" or "legacy")
	local visible_aim = false
	if mode == "legacy" then visible_aim = not state or state.visible_aim
	elseif authored then
		if state.owner == "authored" then visible_aim = state.visible_aim
		else visible_aim = entry.protected_aim == true end
	end
	-- The compositor owns the displayed pose, while both ASMs must evaluate
	-- the incoming state with identical variable/constraint policies. Keeping
	-- the outgoing authored speed here would desynchronize a legacy endpoint.
	local sampler_policy = state and profile.cross_owner_transition_policy == "snapshot-blend-v1"
	if sampler_policy then visible_aim = state.visible_aim end
	return { upper_body = mode, weapon = mode,
		accessories = authored and "authored" or (mode == "legacy" and profile
			and profile.accessory_skin == "localized-v1" and "legacy-pelvis" or "unsupported"),
		speed = sampler_policy and state.speed or authored and (state.owner == "authored" and state.speed or entry.protected_speed or "authored")
			or (mode == "legacy" and (state and state.speed or "measured") or "unsupported"),
		visible_aim = visible_aim,
		profile = profile, profile_id = entry.profile_id, state = entry.state,
		clip = state and state.clip, transitioning = entry.protected > 0 or bridge == true }
end

mod._warlock_animation_channel_ownership = mod._warlock_animation_ownership

function mod._stop_warlock_animation_ownership(owner)
	if mod._stop_warlock_animation_blend then mod._stop_warlock_animation_blend(owner) end
	if owner then entries[owner] = nil end
end

function mod._reset_warlock_animation_ownership()
	if mod._reset_warlock_animation_blend then mod._reset_warlock_animation_blend() end
	entries = {}
end

function mod._release_warlock_animation_ownership_world(world)
	if mod._release_warlock_animation_blend_world then mod._release_warlock_animation_blend_world(world) end
	for owner, entry in pairs(entries) do
		if entry.world == world then entries[owner] = nil end
	end
end
