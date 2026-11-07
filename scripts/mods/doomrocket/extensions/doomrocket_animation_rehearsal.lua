local mod = get_mod("doomrocket")

-- Explicitly opt in NEW outfits only. Existing stock clips exercise controller
-- ownership/clocks; this is not an artist-export or localized-garment verdict.
-- The inventory hook grants freshness before registering this exact outfit.
-- There is no native current-ASM getter here: never sweep or rebind live units.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local VISIBLE = OUTFIT .. "/native_controller_rehearsal"
local SAMPLER = OUTFIT .. "/presentation_sampler"
local PROFILE = "native-controller-rehearsal-v1"
local enabled = false
local seen = setmetatable({}, { __mode = "k" })
local selected, failed = 0, 0

local function hash(value)
	return type(value) == "string" and #value == 64 and not value:find("[^a-f0-9]")
end

local function live(unit, world)
	return unit and Unit.alive(unit) and (world == nil or Unit.world(unit) == world)
end

local function fresh(owner, outfit, world)
	return live(owner, world) and live(outfit, world)
		and (not mod._warlock_outfits or mod._warlock_outfits[owner] == nil)
		and (not mod._warlock_outfit_owners or mod._warlock_outfit_owners[outfit] == nil)
end

local function contract()
	local manifest = mod._warlock_animation_manifest
	local profile = type(manifest) == "table" and manifest.schema == 1
		and type(manifest.profiles) == "table" and manifest.profiles[PROFILE]
	local validation = type(profile) == "table" and profile.validation
	if type(profile) ~= "table" or profile.unit ~= OUTFIT or not hash(profile.manifest_id)
		or profile.native_rehearsal_only ~= true or profile.visible_state_machine ~= VISIBLE
		or profile.sampler_state_machine ~= SAMPLER or profile.cross_owner_transition_policy ~= "snapshot-blend-v1"
		or profile.accessory_skin ~= nil or type(profile.bone_names) ~= "table" or #profile.bone_names ~= 138
		or type(validation) ~= "table" or validation.scope ~= "existing-stock-clip-native-controller-rehearsal"
		or validation.artist_export_acceptance ~= false or validation.localized_garment_acceptance ~= false
		or not hash(validation.visible_state_machine_sha256) or not hash(validation.sampler_state_machine_sha256)
		or type(profile.states) ~= "table" or profile.default_state ~= "base/idle" then return end
	local idle = profile.states["base/idle"]
	if type(idle) ~= "table" or idle.owner ~= "authored" or idle.visible_aim ~= false
		or idle.aim_policy ~= "authored" or idle.clip ~= "units/warlock_bombardier/anims/combat_idle"
		or idle.speed ~= "authored" or idle.speed_expression ~= "1" then return end
	return profile
end

local function output(reason)
	local echo = mod.echo or mod.warning
	if type(echo) == "function" then
		pcall(echo, mod, "Warlock native controller rehearsal: %s (new outfits only; existing stock clip, not artist-export/garment acceptance).", reason)
	end
end

function mod._prepare_warlock_animation_rehearsal(owner, outfit, fresh_spawn)
	if fresh_spawn ~= true or not outfit or seen[outfit] then return false, "not_fresh" end
	seen[outfit] = true
	if not enabled then return false, "off" end
	local profile, world, switched, marked = nil, nil, false, false
	local ok, reason = pcall(function()
		if type(Unit) ~= "table" or type(Unit.set_data) ~= "function"
			or type(Unit.set_animation_state_machine) ~= "function"
			or not live(owner) or not live(outfit) then return "unavailable_unit" end
		world = Unit.world(owner)
		if not world or not fresh(owner, outfit, world)
			or Unit.get_data(outfit, "unit_name") ~= OUTFIT then return "wrong_or_registered_outfit" end
		if Unit.get_data(outfit, "warlock_rig_profile") ~= nil
			or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= nil then return "existing_profile" end
		for _, name in ipairs({ "_warlock_grip_alignment_status", "_warlock_outfit_correction_status", "_warlock_animation_blend_status" }) do
			if type(mod[name]) == "function" and mod[name](owner) ~= "off" then return "existing_controller" end
		end
		profile = contract()
		if not profile then return "invalid_contract" end
		if not Application or type(Application.can_get) ~= "function"
			or not Application.can_get("unit", OUTFIT)
			or not Application.can_get("state_machine", OUTFIT)
			or not Application.can_get("state_machine", VISIBLE)
			or not Application.can_get("state_machine", SAMPLER) then return "unloaded_controller" end
		if not Application.can_get("animation", profile.states["base/idle"].clip) then return "unloaded_idle" end
		if not Unit.has_animation_state_machine(outfit) then return "missing_default_controller" end
		local used = {}
		for _, name in ipairs(profile.bone_names) do
			if type(name) ~= "string" or used[name] or not Unit.has_node(outfit, name) then return "missing_or_aliased_bone" end
			used[name] = true
		end
		if not fresh(owner, outfit, world) or Unit.get_data(outfit, "warlock_rig_profile") ~= nil
			or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= nil then return "changed_binding" end
		-- Mark before switching: any interrupted initialization remains protected
		-- from legacy writers until this transaction restores the original state.
		marked = true
		Unit.set_data(outfit, "warlock_rig_profile", PROFILE)
		if not fresh(owner, outfit, world) or Unit.get_data(outfit, "warlock_rig_profile") ~= PROFILE
			or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= nil then error("binding changed during marker") end
		Unit.set_data(outfit, "warlock_animation_manifest_id", profile.manifest_id)
		if not fresh(owner, outfit, world) or Unit.get_data(outfit, "warlock_rig_profile") ~= PROFILE
			or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= profile.manifest_id then error("binding changed during identity") end
		switched = true
		Unit.set_animation_state_machine(outfit, VISIBLE)
		if not fresh(owner, outfit, world) or Unit.get_data(outfit, "warlock_rig_profile") ~= PROFILE
			or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= profile.manifest_id then error("binding changed during controller") end
		return "selected"
	end)
	if ok and reason == "selected" then
		selected = selected + 1
		output("selected")
		return true, reason
	end
	if marked then
		local restored = pcall(function()
			local function still_ours()
				if not fresh(owner, outfit, world) then error("rollback binding unavailable") end
				local marker = Unit.get_data(outfit, "warlock_rig_profile")
				local identity = Unit.get_data(outfit, "warlock_animation_manifest_id")
				if marker ~= nil and marker ~= PROFILE or identity ~= nil and identity ~= profile.manifest_id then
					error("another profile replaced rehearsal")
				end
			end
			still_ours()
			if switched then Unit.set_animation_state_machine(outfit, OUTFIT) end
			still_ours()
			Unit.set_data(outfit, "warlock_animation_manifest_id", nil)
			still_ours()
			Unit.set_data(outfit, "warlock_rig_profile", nil)
			still_ours()
			if Unit.get_data(outfit, "warlock_rig_profile") ~= nil
				or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= nil then error("rollback marker failed") end
		end)
		if not restored then reason = "rollback_incomplete_protected" end
	end
	failed = failed + 1
	reason = ok and reason or (reason == "rollback_incomplete_protected" and reason or "initializer_api_error")
	output(reason)
	return false, reason
end

function mod._reset_warlock_animation_rehearsal()
	-- Never reset a live outfit's ASM/pose; only future fresh-spawn selection.
	enabled = false
end

function mod._warlock_animation_rehearsal_status()
	return { enabled = enabled, selected = selected, failed = failed,
		scope = "existing-stock-clip-native-controller-rehearsal" }
end

mod:command("warlock_animation_rehearsal", "Native controller rehearsal for NEW outfits: on, off, status", function(action)
	if action == "on" then enabled = true; output("on for subsequent fresh spawns")
	elseif action == "off" then enabled = false; output("off for subsequent fresh spawns; existing outfits finish their own profile")
	else output(string.format("%s; selected=%d failed=%d", enabled and "on" or "off", selected, failed)) end
end)
