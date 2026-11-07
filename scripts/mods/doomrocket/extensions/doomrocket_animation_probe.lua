local mod = get_mod("doomrocket")

-- Opt-in, passive observations from the existing final presentation queue.
-- This never seeks/advances animation, spawns units, flushes a world, or writes
-- poses. Recorded matrices are native local units, not a fixed-frame oracle.
local INTERVAL, MAX_SECONDS, MAX_SAMPLES, MAX_ACTIVE = 0.25, 30, 120, 2
local BONES = { "root_point", "j_hips", "j_spine", "j_head", "j_lefthand", "j_righthand",
	"j_leftweaponattach", "j_whip_parent", "j_whip_dynamic", "j_loot_sack_component1" }
if mod._reset_warlock_animation_probe then mod._reset_warlock_animation_probe("reload") end
local state = { enabled = false, epoch = 0, pending = {}, entries = {}, samples = 0, elapsed = 0 }

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function json(value)
	local kind = type(value)
	if kind == "string" then
		return '"' .. value:gsub('[%z\1-\31\\"]', function(c)
			if c == '"' then return '\\"' end
			if c == '\\' then return '\\\\' end
			return string.format('\\u%04x', string.byte(c))
		end) .. '"'
	elseif kind == "number" then assert(finite(value), "nonfinite diagnostic"); return string.format("%.17g", value)
	elseif kind == "boolean" then return value and "true" or "false" end
	assert(kind == "table", "unsupported diagnostic value")
	local parts = {}
	if #value > 0 then
		for i = 1, #value do parts[i] = json(value[i]) end
		return "[" .. table.concat(parts, ",") .. "]"
	end
	local keys = {}
	for key in pairs(value) do keys[#keys + 1] = key end
	table.sort(keys)
	for i, key in ipairs(keys) do parts[i] = json(key) .. ":" .. json(value[key]) end
	return "{" .. table.concat(parts, ",") .. "}"
end

local function emit(record)
	record.schema, record.version, record.session = 1, mod._doomrocket_version, state.session or 0
	printf("[doomrocket:ANIMATION] %s", json(record))
end

local function stop(reason)
	if state.enabled then emit({ phase = "end", reason = reason, sample_count = state.samples }) end
	state.enabled, state.pending, state.entries = false, {}, {}
	state.epoch = state.epoch + 1
end

local function live(unit, world)
	return unit and Unit.alive(unit) and Unit.world(unit) == world
end

local function matrix(unit, name)
	assert(Unit.has_node(unit, name), "missing diagnostic bone " .. name)
	local node = Unit.node(unit, name)
	assert(finite(node) and node >= 0 and node == math.floor(node), "invalid diagnostic node")
	assert(Script and Script.temp_count and Script.set_temp_count, "temporary math API unavailable")
	local vectors, quaternions, matrices = Script.temp_count()
	local ok, result = pcall(function()
		local pose = Unit.local_pose(unit, node)
		local x, y, z, t = Matrix4x4.x(pose), Matrix4x4.y(pose), Matrix4x4.z(pose), Matrix4x4.translation(pose)
		return { {x.x, y.x, z.x, t.x}, {x.y, y.y, z.y, t.y}, {x.z, y.z, z.z, t.z}, {0, 0, 0, 1} }
	end)
	Script.set_temp_count(vectors, quaternions, matrices)
	assert(ok, "local matrix API unavailable")
	return result
end

local function sample(owner, outfit, world, entry, dt)
	assert(live(owner, world) and live(outfit, world), "unit lifetime changed")
	assert(entry.outfit == outfit, "selected outfit replaced")
	assert(mod._warlock_outfits and mod._warlock_outfits[owner] == outfit, "outfit replaced")
	local marker = Unit.get_data(outfit, "warlock_rig_profile")
	local snapshot = mod._warlock_animation_blend_snapshot and mod._warlock_animation_blend_snapshot(owner) or {status = "unavailable"}
	local record = { phase = "sample", sample_index = state.samples, unit_id = entry.id,
		time_seconds = state.elapsed, animation_dt = dt, stage = "post_presentation", profile_status = "no_custom_profile",
		sampler_status = snapshot.status, native_fixed_frame_oracle = false }
	if marker ~= nil then
		record.profile_status = "unregistered_custom_profile"
		if snapshot.manifest_id and snapshot.outfit == outfit then
			record.profile_status = "registered_custom_profile"
			record.profile_id = tostring(marker)
			record.sampler = {}
			for key, value in pairs(snapshot) do
				if key ~= "helper" and key ~= "outfit" then record.sampler[key] = value end
			end
			local helper = snapshot.helper
			assert(live(helper, world), "helper lifetime changed")
			assert(type(mod._warlock_animation_clock) == "function", "missing clock reader")
			local helper_time, helper_length, helper_reason = mod._warlock_animation_clock(helper, world)
			assert(helper_time ~= nil, helper_reason)
			local visible_time, visible_length, visible_reason = mod._warlock_animation_clock(outfit, world)
			assert(visible_time ~= nil, visible_reason)
			record.helper_clock, record.helper_length = helper_time, helper_length
			record.visible_clock, record.visible_length = visible_time, visible_length
			record.bones_local, record.helper_bones_local = {}, {}
			for _, name in ipairs(BONES) do
				record.bones_local[name] = matrix(outfit, name)
				record.helper_bones_local[name] = matrix(helper, name)
			end
		end
	end
	emit(record)
	state.samples = state.samples + 1
end

function mod._reset_warlock_animation_probe(reason)
	stop(reason or "reset")
end

function mod._release_warlock_animation_probe_world(world)
	-- Invalidate queued closures before the engine frees any native objects.
	if state.pending[world] then stop("world_release"); return end
	for _, entry in pairs(state.entries) do
		if entry.world == world then stop("world_release"); return end
	end
end

local function queue(world, dt)
	if not state.enabled or state.pending[world] or not finite(dt) or dt <= 0 then return end
	local found = false
	for owner, outfit in pairs(mod._warlock_outfits or {}) do
		if live(owner, world) and live(outfit, world) then found = true; break end
	end
	if not found then return end
	local entity = Managers.state.entity
	local animation = entity and entity:system("animation_system")
	if not animation then return end
	state.pending[world] = true
	local epoch = state.epoch
	animation:add_safe_animation_callback(function()
		local ok = pcall(function()
		if not state.enabled or state.epoch ~= epoch then return end
		state.pending[world] = nil
		state.elapsed = math.min(MAX_SECONDS, state.elapsed + dt)
		if state.elapsed >= MAX_SECONDS then stop("time_limit"); return end
		local used = 0
		for owner, outfit in pairs(mod._warlock_outfits or {}) do
			if used >= MAX_ACTIVE or state.samples >= MAX_SAMPLES then break end
			if live(owner, world) and live(outfit, world) and HEALTH_ALIVE and HEALTH_ALIVE[owner] == true then
				local entry = state.entries[owner]
				if not entry and (state.unit_sequence or 0) < MAX_ACTIVE then
					state.unit_sequence = (state.unit_sequence or 0) + 1
					entry = { id = state.unit_sequence, next_sample = 0, world = world, outfit = outfit }
					state.entries[owner] = entry
				end
				if entry and state.elapsed >= entry.next_sample then
					local ok = pcall(sample, owner, outfit, world, entry, dt)
					if not ok then
						emit({phase = "error", reason = "diagnostic_api_or_data_unavailable", sample_count = state.samples})
						stop("diagnostic_error"); return
					end
					entry.next_sample = state.elapsed + INTERVAL
					used = used + 1
				end
			end
		end
		if state.samples >= MAX_SAMPLES then stop("sample_limit") end
		end)
		if not ok and state.enabled and state.epoch == epoch then
			emit({phase = "error", reason = "diagnostic_api_or_data_unavailable", sample_count = state.samples})
			stop("diagnostic_error")
		end
	end)
end

function mod._queue_warlock_animation_probe(world, dt)
	local ok = pcall(queue, world, dt)
	if not ok and state.enabled then
		emit({phase = "error", reason = "diagnostic_api_or_data_unavailable", sample_count = state.samples})
		stop("diagnostic_error")
	end
end

mod:command("warlock_animation_probe", "Passive animation diagnostics: on, status, off", function(action)
	if action == "on" then
		stop("restarted")
		mod._warlock_animation_probe_sequence = (mod._warlock_animation_probe_sequence or 0) + 1
		state = { enabled = true, session = mod._warlock_animation_probe_sequence,
			epoch = state.epoch + 1, pending = {}, entries = {}, samples = 0, elapsed = 0 }
		emit({phase = "start", interval_seconds = INTERVAL, max_seconds = MAX_SECONDS,
			max_samples = MAX_SAMPLES, max_active_units = MAX_ACTIVE, bone_names = BONES,
			time_basis = "matching-outfit-world-animation-dt", wait_for_outfit = true})
	elseif action == "off" then stop("user_off")
	else
		emit({phase = "status", enabled = state.enabled, sample_count = state.samples})
		mod:echo("Animation probe %s; /warlock_animation_probe on or off. Default gameplay has no custom profile; a log is not animation acceptance.", state.enabled and "on" or "off")
	end
end)
