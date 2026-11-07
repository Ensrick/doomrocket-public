local mod = get_mod("doomrocket")

-- The opt-in skin uses seven existing channels that legacy clips did not skin.
-- Derive their poses from the evaluated outfit pelvis after grip/death writes.
-- Never rewrite a clip, capture an animated spawn pose as bind, or touch the
-- other 131 channels. Authored living states own their accessory animation.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local PROFILE = "localized-v1-runtime"
local SHIPPING_BODY = "cb2eba0224d1eff044a30b1bf0269d1a10395e8db9244af5c011e5c0ba0bd0bc"
local SHIPPING_BONES = "6e4eb323ba5a21db1e2f09f91d73cfa1e3234a03d7b183223f48ccd96c51a197"
local CHANNELS = {
	{ "j_whip_parent", "j_hips" },
	{ "j_whip_dynamic", "j_whip_parent" },
	{ "j_loot_sack_component1", "j_loot_sack" },
	{ "j_loot_sack_component2", "j_loot_sack" },
	{ "j_loot_sack_component3", "j_loot_sack" },
	{ "j_loot_sack_component4", "j_loot_sack" },
	{ "j_loot_sack_component5", "j_loot_sack" },
}
local GRIP_CHANNELS = {
	"j_spine", "j_spine1", "j_leftshoulder", "j_rightshoulder",
	"j_leftarm", "j_rightarm", "j_leftforearm", "j_rightforearm",
	"j_lefthand", "j_righthand", "j_leftforearmroll", "j_rightforearmroll",
}

if mod._reset_warlock_outfit_correction then mod._reset_warlock_outfit_correction() end
local entries = {}

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function hash(value)
	return type(value) == "string" and #value == 64 and not value:find("[^a-f0-9]")
end

local function live(unit, world)
	return unit and Unit.alive(unit) and Unit.world(unit) == world
end

local function times(vector, amount)
	return Vector3(vector.x * amount, vector.y * amount, vector.z * amount)
end

local function orthogonal(pose)
	if not Matrix4x4.is_valid(pose) then return false end
	local x, y, z = Matrix4x4.x(pose), Matrix4x4.y(pose), Matrix4x4.z(pose)
	local a, b, c = Vector3.length(x), Vector3.length(y), Vector3.length(z)
	if not finite(a) or not finite(b) or not finite(c)
		or a <= 0.000001 or b <= 0.000001 or c <= 0.000001 then return false end
	return math.abs(Vector3.dot(x, y)) <= a * b * 0.0001
		and math.abs(Vector3.dot(x, z)) <= a * c * 0.0001
		and math.abs(Vector3.dot(y, z)) <= b * c * 0.0001
		and Vector3.dot(x, Vector3.cross(y, z)) > a * b * c * 0.9999, a, b, c
end

local function native_offset(rows)
	if type(rows) ~= "table" or #rows ~= 4 then return end
	for row = 1, 4 do
		if type(rows[row]) ~= "table" or #rows[row] ~= 4 then return end
		for column = 1, 4 do if not finite(rows[row][column]) then return end end
	end
	if rows[4][1] ~= 0 or rows[4][2] ~= 0 or rows[4][3] ~= 0 or rows[4][4] ~= 1 then return end
	local pose = Matrix4x4.identity()
	Matrix4x4.set_x(pose, Vector3(rows[1][1], rows[2][1], rows[3][1]))
	Matrix4x4.set_y(pose, Vector3(rows[1][2], rows[2][2], rows[3][2]))
	Matrix4x4.set_z(pose, Vector3(rows[1][3], rows[2][3], rows[3][3]))
	Matrix4x4.set_translation(pose, Vector3(rows[1][4], rows[2][4], rows[3][4]))
	local ok, a, b, c = orthogonal(pose)
	if not ok or math.abs(a - 1) > 0.0001 or math.abs(b - 1) > 0.0001
		or math.abs(c - 1) > 0.0001 or Vector3.length(Matrix4x4.translation(pose)) > 2 then return end
	return pose
end

local function profile_for(outfit)
	local manifest = mod._warlock_animation_manifest
	if type(manifest) ~= "table" or manifest.schema ~= 1 or type(manifest.profiles) ~= "table"
		or Unit.get_data(outfit, "warlock_rig_profile") ~= PROFILE then return end
	local profile = manifest.profiles[PROFILE]
	if type(profile) ~= "table" or profile.unit ~= OUTFIT or profile.accessory_skin ~= "localized-v1"
		or not hash(profile.manifest_id) or not hash(profile.body_fbx_sha256)
		or not hash(profile.rest_contract_sha256) or profile.shipping_body_sha256 ~= SHIPPING_BODY
		or profile.shipping_bones_sha256 ~= SHIPPING_BONES
		or Unit.get_data(outfit, "warlock_animation_manifest_id") ~= profile.manifest_id
		or Unit.get_data(outfit, "unit_name") ~= OUTFIT then return end
	if profile.reference_bone ~= "j_hips" or profile.native_bind_scale ~= 100
		or type(profile.channels) ~= "table" or #profile.channels ~= #CHANNELS then return end
	return profile
end

local function valid(owner, outfit, entry, corpse, handoff)
	if not entry or entry.outfit ~= outfit or not live(owner, entry.world) or not live(outfit, entry.world)
		or profile_for(outfit) ~= entry.profile or entry.profile.manifest_id ~= entry.manifest_id then return false end
	local registered = mod._warlock_outfits and mod._warlock_outfits[owner]
	if corpse then return entry.corpse == true and (registered == nil or registered == outfit) end
	return not entry.corpse and registered == outfit
		and (handoff == true or HEALTH_ALIVE and HEALTH_ALIVE[owner] == true)
end

local function target_entry(outfit, world, profile)
	if not Unit.has_node(outfit, "j_hips") then return end
	local node_pairs, parents, owned = {}, {}, {}
	for index = 1, #CHANNELS do
		local expected, channel = CHANNELS[index], profile.channels[index]
		if type(channel) ~= "table" or channel.bone ~= expected[1] or channel.parent ~= expected[2]
			or not Unit.has_node(outfit, channel.bone) or not Unit.has_node(outfit, channel.parent) then return end
		local offset = native_offset(channel.bind_offset)
		local node, parent = Unit.node(outfit, channel.bone), Unit.node(outfit, channel.parent)
		if not offset or node == 0 or owned[node] or Unit.scene_graph_parent(outfit, node) ~= parent then return end
		owned[node] = true
		node_pairs[index] = { node = node, parent = parent, bind_offset = Matrix4x4Box(offset) }
		local current, visited, count = node, {}, 0
		while current ~= 0 do
			if visited[current] or count >= 256 then return end
			visited[current], count = true, count + 1
			local ancestor = Unit.scene_graph_parent(outfit, current)
			if not finite(ancestor) or ancestor ~= math.floor(ancestor) or ancestor < 0 or ancestor == current then return end
			parents[current] = ancestor
			current = ancestor
		end
	end
	return { outfit = outfit, world = world, profile = profile, manifest_id = profile.manifest_id,
		pairs = node_pairs, parents = parents, owned = owned, hips = Unit.node(outfit, "j_hips"), status = "armed" }
end

function mod._start_warlock_outfit_correction(owner, outfit)
	if not owner then return false end
	entries[owner] = nil
	if not owner or not Unit.alive(owner) or not outfit or not Unit.alive(outfit)
		or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= outfit then return false end
	local profile = profile_for(outfit)
	local world = Unit.world(owner)
	if not profile or not world or Unit.world(outfit) ~= world then return false end
	entries[owner] = target_entry(outfit, world, profile)
	if not entries[owner] then return false end
	return true
end

local function prepare_pose(entry, overrides)
	local outfit = entry.outfit
	-- Caller runs after its grip/death update. Flush here too so standalone calls
	-- cannot consume a previous scene-cache frame after changing an ancestor.
	World.update_unit(entry.world, outfit)
	local hip = Unit.world_pose(outfit, entry.hips)
	local ok, a, b, c = orthogonal(hip)
	if not ok or math.abs(a - b) > a * 0.0001 or math.abs(a - c) > a * 0.0001 then
		return nil, "unsupported_hips_scale"
	end
	local unit_scale = a / entry.profile.native_bind_scale
	local rigid_hip = Matrix4x4.multiply(hip, Matrix4x4.identity())
	Matrix4x4.set_x(rigid_hip, times(Matrix4x4.x(hip), 1 / a))
	Matrix4x4.set_y(rigid_hip, times(Matrix4x4.y(hip), 1 / b))
	Matrix4x4.set_z(rigid_hip, times(Matrix4x4.z(hip), 1 / c))
	local desired, graph, writes = {}, {}, {}
	for index = 1, #entry.pairs do
		local pair = entry.pairs[index]
		local target = Unit.world_pose(outfit, pair.node)
		local target_ok, x, y, z = orthogonal(target)
		if not target_ok then return nil, "invalid_target_scale" end
		local offset = pair.bind_offset:unbox()
		Matrix4x4.set_translation(offset, times(Matrix4x4.translation(offset), unit_scale))
		local pose = Matrix4x4.multiply(offset, rigid_hip)
		Matrix4x4.set_x(pose, times(Matrix4x4.x(pose), x))
		Matrix4x4.set_y(pose, times(Matrix4x4.y(pose), y))
		Matrix4x4.set_z(pose, times(Matrix4x4.z(pose), z))
		desired[pair.node] = pose
	end
	local function parent_world(node)
		if desired[node] then return desired[node] end
		if graph[node] then return graph[node] end
		if node == 0 then return Unit.world_pose(outfit, 0) end
		local pose = Matrix4x4.multiply(overrides and overrides[node] or Unit.local_pose(outfit, node),
			parent_world(entry.parents[node]))
		graph[node] = pose
		return pose
	end
	for index = 1, #entry.pairs do
		local pair = entry.pairs[index]
		local parent = parent_world(pair.parent)
		if not orthogonal(parent) then return nil, "invalid_parent" end
		local local_pose = Matrix4x4.multiply(desired[pair.node], Matrix4x4.inverse(parent))
		local local_ok, x, y, z = orthogonal(local_pose)
		local scale = Unit.local_scale(outfit, pair.node)
		if not local_ok or not Vector3.is_valid(scale) or scale.x <= 0 or scale.y <= 0 or scale.z <= 0
			or math.abs(x - scale.x) > math.max(0.00001, scale.x * 0.0001)
			or math.abs(y - scale.y) > math.max(0.00001, scale.y * 0.0001)
			or math.abs(z - scale.z) > math.max(0.00001, scale.z * 0.0001) then
			return nil, "unsupported_local_scale"
		end
		-- Quaternion extraction receives a rigid frame. Preserve the positive
		-- local scale through the setters rather than asking it to decompose scale.
		local rotation_pose = Matrix4x4.multiply(local_pose, Matrix4x4.identity())
		Matrix4x4.set_x(rotation_pose, times(Matrix4x4.x(local_pose), 1 / x))
		Matrix4x4.set_y(rotation_pose, times(Matrix4x4.y(local_pose), 1 / y))
		Matrix4x4.set_z(rotation_pose, times(Matrix4x4.z(local_pose), 1 / z))
		writes[index] = { node = pair.node, pose = local_pose, rotation = Matrix4x4.rotation(rotation_pose),
			position = Matrix4x4.translation(local_pose) }
	end
	return writes
end

-- Resolve accessory parents using the uncommitted grip candidates. Both
-- builders are read-only, so a bad final accessory cannot leave twelve helper
-- joints corrected while the other seven still contain the raw legacy pose.
function mod._prepare_warlock_legacy_outfit_pose(owner, helper, profile, grip_writes, token)
	local entry = entries[owner]
	local authorize = mod._warlock_transition_helper_valid
	if not entry or not valid(owner, entry.outfit, entry, false) or entry.profile ~= profile
		or not authorize or not authorize(owner, helper, profile, token) or not live(helper, entry.world)
		or helper == owner or helper == entry.outfit then return nil, "inactive_helper" end
	local target = target_entry(helper, entry.world, profile)
	if not target or type(grip_writes) ~= "table" or #grip_writes ~= #GRIP_CHANNELS then
		return nil, "invalid_helper_candidate"
	end
	local overrides, expected = {}, {}
	for i = 1, #GRIP_CHANNELS do
		if not Unit.has_node(helper, GRIP_CHANNELS[i]) then return nil, "missing_helper_node" end
		expected[Unit.node(helper, GRIP_CHANNELS[i])] = true
	end
	for i = 1, #grip_writes do
		local write = grip_writes[i]
		if type(write) ~= "table" or not expected[write.node] or overrides[write.node]
			or not write.pose then return nil, "invalid_helper_candidate" end
		local ok, x, y, z = orthogonal(write.pose)
		local scale = Unit.local_scale(helper, write.node)
		if not ok or not Vector3.is_valid(scale) or scale.x <= 0 or scale.y <= 0 or scale.z <= 0
			or math.abs(x - scale.x) > math.max(0.00001, scale.x * 0.0001)
			or math.abs(y - scale.y) > math.max(0.00001, scale.y * 0.0001)
			or math.abs(z - scale.z) > math.max(0.00001, scale.z * 0.0001) then
			return nil, "invalid_helper_candidate"
		end
		overrides[write.node] = write.pose
	end
	return prepare_pose(target, overrides)
end

function mod._apply_warlock_outfit_correction(owner, outfit, allow_corpse)
	local entry = entries[owner]
	local corpse = allow_corpse == true
	if entry then entry.status = "preflighting" end
	if not valid(owner, outfit, entry, corpse) then
		if entry then entry.status = "inactive_pair_or_profile" end
		return false
	end
	if not corpse then
		local getter = mod._warlock_animation_ownership
		local ownership = getter and getter(owner, outfit)
		if type(ownership) ~= "table" or ownership.accessories ~= "legacy-pelvis" then
			entry.status = type(ownership) == "table" and ownership.accessories == "authored" and "authored" or "unsupported_event"
			return false
		end
	end
	local writes, status = prepare_pose(entry)
	if not writes then entry.status = status; return false end
	-- Every parent, scale and transform is checked before the first native write.
	for index = 1, #writes do
		local write = writes[index]
		Unit.set_local_rotation(outfit, write.node, write.rotation)
		Unit.set_local_position(outfit, write.node, write.position)
	end
	World.update_unit(entry.world, outfit)
	entry.status = corpse and "active-corpse" or "active-legacy"
	return true
end

function mod._handoff_warlock_outfit_correction(owner, outfit)
	local entry = entries[owner]
	if not valid(owner, outfit, entry, false, true) then return false end
	entry.corpse, entry.status = true, "corpse-handoff"
	return true
end

function mod._warlock_outfit_correction_owns_node(owner, node)
	local entry = entries[owner]
	return entry and (entry.status == "active-legacy" or entry.status == "active-corpse")
		and entry.owned[node] == true or false
end

function mod._warlock_outfit_correction_status(owner)
	return entries[owner] and entries[owner].status or "off"
end

function mod._stop_warlock_outfit_correction(owner, preserve_corpse)
	if preserve_corpse and entries[owner] and entries[owner].corpse then return end
	if owner then entries[owner] = nil end
end

function mod._reset_warlock_outfit_correction()
	entries = {}
end

function mod._release_warlock_outfit_correction_world(world)
	for owner, entry in pairs(entries) do if entry.world == world then entries[owner] = nil end end
end
