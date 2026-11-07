local mod = get_mod("doomrocket")

-- The launcher is linked to the native Ratling, but the visible arms used an
-- independently advancing animation machine. Match the twelve upper-body
-- deform joints to the carrier's evaluated rigid world pose. Keep the custom
-- hierarchy, scales, lower-body gait and own ASM intact. Explicit authored
-- ownership bypasses this transfer and follows all three authored weapon
-- frames through the weapon's approved internal graph. Only its root is linked
-- to the uniform carrier root; animated outfit shear never becomes link scale.
-- Never copy a native local pose into the custom rig's 100x parent space.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local WEAPON = "units/rocket/pRocketLauncher"
local NAMES = {
	"j_spine", "j_spine1", "j_leftshoulder", "j_rightshoulder",
	"j_leftarm", "j_rightarm", "j_leftforearm", "j_rightforearm",
	"j_lefthand", "j_righthand", "j_leftforearmroll", "j_rightforearmroll",
}
local WEAPON_LINKS = {
	{ target = 0, source = "j_leftweaponattach" },
	{ target = "a_barrel", source = "j_leftweaponcomponent1" },
	{ target = "handle", source = "j_lefthand" },
}

if mod._reset_warlock_grip_alignment then
	mod._reset_warlock_grip_alignment()
end

local entries, pending, epoch = {}, {}, 0

local function finite(n)
	return type(n) == "number" and n == n and math.abs(n) < math.huge
end

local function live(unit, world)
	return unit and Unit.alive(unit) and Unit.world(unit) == world
end

local function valid(owner, entry)
	return live(owner, entry.world) and live(entry.outfit, entry.world)
		and HEALTH_ALIVE and HEALTH_ALIVE[owner]
		and mod._warlock_outfits and mod._warlock_outfits[owner] == entry.outfit
end

local function orthogonal(pose)
	if not Matrix4x4.is_valid(pose) then return false end
	local x, y, z = Matrix4x4.x(pose), Matrix4x4.y(pose), Matrix4x4.z(pose)
	local a, b, c = Vector3.length(x), Vector3.length(y), Vector3.length(z)
	return a > 0.000001 and b > 0.000001 and c > 0.000001
		and math.abs(Vector3.dot(x, y)) < a * b * 0.0001
		and math.abs(Vector3.dot(x, z)) < a * c * 0.0001
		and math.abs(Vector3.dot(y, z)) < b * c * 0.0001, a, b, c
end

local function times(v, scale)
	return Vector3(v.x * scale, v.y * scale, v.z * scale)
end

local function ownership(owner, entry)
	if mod._warlock_animation_ownership then
		return mod._warlock_animation_ownership(owner, entry.outfit)
	end
	return { upper_body = "legacy", weapon = "legacy" }
end

local function scene_graph(weapon)
	local graph = Unit.get_data(weapon, "scene_graph_data")
	if type(graph) ~= "table" or #graph ~= 2 then return end
	local expected, found = {}, {}
	for i = 2, #WEAPON_LINKS do
		local name = WEAPON_LINKS[i].target
		if not Unit.has_node(weapon, name) then return end
		expected[Unit.node(weapon, name)] = true
	end
	for _, link in ipairs(graph) do
		if type(link) ~= "table" or not expected[link.i] or found[link.i]
			or not finite(link.parent) or link.parent ~= math.floor(link.parent)
			or link.parent < 0 or link.parent >= link.i
			or not link.local_pose then return end
		local ok, pose = pcall(function() return link.local_pose:unbox() end)
		if not ok or not Matrix4x4.is_valid(pose) then return end
		found[link.i] = true
	end
	for i = 2, #WEAPON_LINKS do
		local name = WEAPON_LINKS[i].target
		if not Unit.has_node(weapon, name) or not found[Unit.node(weapon, name)] then return end
	end
	return graph
end

local function unlink_weapon(entry)
	if not entry.authored_weapon then return true end
	if not live(entry.weapon, entry.world) then entry.authored_weapon = nil; return true end
	local graph = scene_graph(entry.weapon)
	if not graph then return false end
	-- This is the same convention as AIInventoryExtension.unlink_unit. Never
	-- replace its pre-link metadata with an externally linked animated pose.
	-- Unlink preserves the current root world placement for native drop actors.
	World.update_unit(entry.world, entry.weapon)
	World.unlink_unit(entry.world, entry.weapon)
	for _, link in ipairs(graph) do
		Unit.scene_graph_link(entry.weapon, link.i, link.parent)
		Unit.set_local_pose(entry.weapon, link.i, link.local_pose:unbox())
	end
	entry.authored_weapon = nil
	World.update_unit(entry.world, entry.weapon)
	return true
end

local function wielded_weapon(entry)
	local inventory = entry.inventory
	if not inventory or inventory.wielded ~= true or inventory.dropped or not inventory.inventory_item_units
		or not inventory.inventory_item_definitions then return end
	-- Native inventory has sets only for multiple_configurations. The ordinary
	-- doomrocket_inventory uses all of its items, as AIInventorySystem.update does.
	local first, last = 1, inventory.inventory_items_n
	if inventory.item_sets then
		local set = inventory.item_sets[inventory.current_item_set_index]
		if not set then return end
		first, last = set.start_index, set.end_index
	end
	if not finite(first) or not finite(last) or first ~= math.floor(first) or last ~= math.floor(last)
		or first < 1 or last < first or last - first > 256 then return end
	for index = first, last do
		local item = inventory.inventory_item_units[index]
		local definition = inventory.inventory_item_definitions[index]
		-- Definitions are shared configuration tables; native drops mutate them.
		-- Only the inventory and item extension describe this instance's state.
		if live(item, entry.world) and definition
			and not (entry.stopped_items and entry.stopped_items[item])
			and Unit.get_data(item, "unit_name") == WEAPON then
			local extension = ScriptUnit and ScriptUnit.has_extension(item, "ai_inventory_item_system")
			if extension and not extension.dropped and extension.wielding_unit == inventory.unit then
				return item
			end
		end
	end
end

local function weapon_links(profile)
	local links = profile and profile.weapon_links
	if type(links) ~= "table" or #links ~= #WEAPON_LINKS then return false end
	for i, expected in ipairs(WEAPON_LINKS) do
		local link = links[i]
		local scale = type(link) == "table" and link.world_scale
		if type(link) ~= "table" or link.target ~= expected.target or link.source ~= expected.source
			or type(scale) ~= "table" or #scale ~= 3
			or scale[1] ~= 1 or scale[2] ~= 1 or scale[3] ~= 1
			or link.offset ~= nil then return false end
	end
	return true
end

-- Quaternion.normalize is not used by any VT2 script, so it may be absent
-- from this engine build; fall back to the element form VT2 does use.
local function normalized(q)
	if not Quaternion then return end
	if Quaternion.normalize then return Quaternion.normalize(q) end
	if not Quaternion.to_elements or not Quaternion.from_elements then return end
	local x, y, z, w = Quaternion.to_elements(q)
	local length = math.sqrt(x * x + y * y + z * z + w * w)
	if not finite(length) or length < 0.000001 then return end
	return Quaternion.from_elements(x / length, y / length, z / length, w / length)
end

local function positive_frame(pose)
	if not Matrix4x4.is_valid(pose) then return false end
	local x, y, z = Matrix4x4.x(pose), Matrix4x4.y(pose), Matrix4x4.z(pose)
	local determinant = x.x * (y.y * z.z - y.z * z.y)
		- x.y * (y.x * z.z - y.z * z.x) + x.z * (y.x * z.y - y.y * z.x)
	return finite(determinant) and determinant > 0.000000000001
end

local function follow_authored_weapon(owner, entry, channels)
	local weapon = wielded_weapon(entry)
	if not weapon then
		unlink_weapon(entry)
		entry.status = "authored_no_wielded_weapon"
		return
	end
	if entry.weapon ~= weapon then
		if not unlink_weapon(entry) then entry.status = "invalid_weapon_graph"; return end
		entry.weapon = weapon
	end
	if not weapon_links(channels.profile) then entry.status = "invalid_weapon_manifest"; return end
	local graph = scene_graph(weapon)
	if not graph then entry.status = "invalid_weapon_graph"; return end
	local prepared, desired, parents, original = {}, {}, {}, {}
	for _, link in ipairs(graph) do
		parents[link.i] = link.parent
		original[link.i] = link.local_pose:unbox()
	end
	local root_parent = Unit.world_pose(owner, 0)
	local root_ok, a, b, c = orthogonal(root_parent)
	if not root_ok or not positive_frame(root_parent) or math.abs(a - b) > a * 0.0001
		or math.abs(a - c) > a * 0.0001 then entry.status = "invalid_weapon_parent"; return end
	for i, link in ipairs(WEAPON_LINKS) do
		if not Unit.has_node(entry.outfit, link.source)
			or (type(link.target) == "string" and not Unit.has_node(weapon, link.target)) then
			entry.status = "missing_weapon_node"; return
		end
		local source = Unit.node(entry.outfit, link.source)
		local target = type(link.target) == "string" and Unit.node(weapon, link.target) or link.target
		local parent = Unit.world_pose(entry.outfit, source)
		if not positive_frame(parent) then entry.status = "invalid_weapon_frame"; return end
		local rotation = Unit.world_rotation(entry.outfit, source)
		rotation = normalized(rotation)
		if not rotation then entry.status = "invalid_weapon_rotation"; return end
		local rigid = Matrix4x4.from_quaternion_position(rotation,
			Unit.world_position(entry.outfit, source))
		if not orthogonal(rigid) or not positive_frame(rigid) then
			entry.status = "invalid_weapon_frame"; return
		end
		desired[target] = rigid
		prepared[i] = { target = target }
		local node, guard = target, 0
		while node ~= 0 do
			local ancestor = parents[node]
			if ancestor == nil then ancestor = Unit.scene_graph_parent(weapon, node); parents[node] = ancestor end
			if type(ancestor) ~= "number" or ancestor < 0 or ancestor >= node or guard >= 256 then
				entry.status = "invalid_weapon_graph"; return
			end
			node, guard = ancestor, guard + 1
		end
	end
	local cache = {}
	local function parent_world(node)
		if desired[node] then return desired[node] end
		if cache[node] then return cache[node] end
		local pose = Matrix4x4.multiply(original[node] or Unit.local_pose(weapon, node), parent_world(parents[node]))
		cache[node] = pose
		return pose
	end
	for _, link in ipairs(prepared) do
		local parent = link.target == 0 and root_parent or parent_world(parents[link.target])
		if not positive_frame(parent) then entry.status = "invalid_weapon_parent"; return end
		local pose = Matrix4x4.multiply(desired[link.target], Matrix4x4.inverse(parent))
		-- The uniform-root route needs no local shear. Keep this bound explicit
		-- rather than silently changing the weapon's approved internal geometry.
		if not orthogonal(pose) or not positive_frame(pose) then
			entry.status = "invalid_weapon_local"; return
		end
		link.pose = pose
	end
	-- Validate every graph/pose first. Native wield may reparent this unit even
	-- without an animation event, so reconcile its internal graph every frame.
	World.unlink_unit(entry.world, weapon)
	for _, link in ipairs(graph) do
		Unit.scene_graph_link(weapon, link.i, link.parent)
		Unit.set_local_pose(weapon, link.i, link.local_pose:unbox())
	end
	entry.authored_weapon = true
	World.link_unit(entry.world, weapon, 0, owner, 0)
	for _, link in ipairs(prepared) do
		Unit.set_local_pose(weapon, link.target, link.pose)
	end
	World.update_unit(entry.world, weapon)
	entry.status = "authored"
end

local function restore_native_weapon(owner, entry)
	if not entry.authored_weapon then return true end
	local wielded = wielded_weapon(entry) == entry.weapon
	if not wielded then return unlink_weapon(entry) end
	for _, link in ipairs(WEAPON_LINKS) do
		if not Unit.has_node(owner, link.source) then return false end
	end
	if not unlink_weapon(entry) then return false end
	for _, link in ipairs(WEAPON_LINKS) do
		local target = type(link.target) == "string" and Unit.node(entry.weapon, link.target) or link.target
		World.link_unit(entry.world, entry.weapon, target, owner, Unit.node(owner, link.source))
	end
	World.update_unit(entry.world, entry.weapon)
	return true
end

-- Leaving authored ownership while the living carrier still wields the
-- launcher must return it to the native carrier links. A bare unlink after
-- a reset, an apply error or an invalid binding would leave it floating.
-- Death keeps the plain unlink, which preserves placement for native drops.
local function release_weapon(owner, entry)
	if live(owner, entry.world) and HEALTH_ALIVE and HEALTH_ALIVE[owner] then
		return restore_native_weapon(owner, entry)
	end
	return unlink_weapon(entry)
end

local function prepare_legacy(owner, entry)
	local root = Unit.world_position(owner, 0)
	local desired, locals, graph = {}, {}, {}
	for i = 1, #entry.pairs do
		local pair = entry.pairs[i]
		local target_world = Unit.world_pose(entry.outfit, pair.target)
		local ok, a, b, c = orthogonal(target_world)
		if not ok or math.abs(a - b) > a * 0.0001 or math.abs(a - c) > a * 0.0001 then
			return nil, "unsupported_scale"
		end
		local source_position = Unit.world_position(owner, pair.source)
		if not Vector3.is_valid(source_position) or Vector3.distance(source_position, root) > 4 then
			return nil, "invalid_source"
		end
		-- Reject spawn transients or an unsupported torso displacement. No offset
		-- calibration may be captured from an unevaluated initial animation pose.
		if pair.name == "j_spine" and Vector3.distance(source_position,
			Unit.world_position(entry.outfit, pair.target)) > 0.5 then
			return nil, "unsettled_torso"
		end
		local pose = Matrix4x4.from_quaternion_position(
			Unit.world_rotation(owner, pair.source), source_position)
		if not orthogonal(pose) then return nil, "invalid_source" end
		-- Preserve the custom uniform world scale, not the native animated scale.
		Matrix4x4.set_x(pose, times(Matrix4x4.x(pose), a))
		Matrix4x4.set_y(pose, times(Matrix4x4.y(pose), a))
		Matrix4x4.set_z(pose, times(Matrix4x4.z(pose), a))
		desired[pair.target] = pose
	end

	local function parent_world(node)
		if desired[node] then return desired[node] end
		if graph[node] then return graph[node] end
		if node == 0 then return Unit.world_pose(entry.outfit, 0) end
		local parent = entry.parents[node]
		local pose = Matrix4x4.multiply(Unit.local_pose(entry.outfit, node), parent_world(parent))
		graph[node] = pose
		return pose
	end
	-- Resolve the entire candidate through the custom parent graph before any
	-- native write. Scale, shear, NaN and singular-parent failures leave it alone.
	for i = 1, #entry.pairs do
		local pair = entry.pairs[i]
		local parent = parent_world(pair.parent)
		if not orthogonal(parent) then return nil, "invalid_parent" end
		local pose = Matrix4x4.multiply(desired[pair.target], Matrix4x4.inverse(parent))
		local ok, a, b, c = orthogonal(pose)
		local scale = Unit.local_scale(entry.outfit, pair.target)
		if not ok or not Vector3.is_valid(scale)
			or math.abs(a - scale.x) > 0.001 or math.abs(b - scale.y) > 0.001
			or math.abs(c - scale.z) > 0.001 then
			return nil, "unsupported_local_scale"
		end
		locals[i] = { node = pair.target, pose = pose, rotation = Matrix4x4.rotation(pose),
			position = Matrix4x4.translation(pose) }
	end
	return locals
end

local function target_pairs(owner, outfit)
	local node_pairs, parents = {}, {}
	for i = 1, #NAMES do
		local name = NAMES[i]
		if not Unit.has_node(owner, name) or not Unit.has_node(outfit, name) then return end
		local target = Unit.node(outfit, name)
		local parent = Unit.scene_graph_parent(outfit, target)
		node_pairs[i] = { name = name, target = target, source = Unit.node(owner, name), parent = parent }
		local node, visited, guard = target, {}, 0
		while node ~= 0 do
			if visited[node] or guard >= 256 then return end
			local ancestor = Unit.scene_graph_parent(outfit, node)
			if not finite(ancestor) or ancestor ~= math.floor(ancestor) or ancestor < 0 or ancestor == node then return end
			visited[node], parents[node] = true, ancestor
			node, guard = ancestor, guard + 1
		end
	end
	return node_pairs, parents
end

-- The presentation compositor is the sole authority for this hidden target.
-- Return current-frame native temporaries; preflight every candidate without
-- changing either the displayed outfit or the helper's authored clip data.
function mod._prepare_warlock_legacy_grip_pose(owner, helper, token)
	local entry = entries[owner]
	local authorize = mod._warlock_transition_helper_valid
	if not entry or not valid(owner, entry) or not entry.mirrored or not authorize
		or not authorize(owner, helper, nil, token) or not live(helper, entry.world)
		or helper == owner or helper == entry.outfit then return nil, "inactive_helper" end
	local pairs, parents = target_pairs(owner, helper)
	if not pairs then return nil, "missing_helper_node" end
	World.update_unit(entry.world, owner)
	World.update_unit(entry.world, helper)
	return prepare_legacy(owner, { outfit = helper, pairs = pairs, parents = parents })
end

local function apply(owner, entry)
	-- Both units need their freshly evaluated local bones composed before reading
	-- world poses. pre_scene_update alone does not establish this cache boundary.
	World.update_unit(entry.world, owner)
	World.update_unit(entry.world, entry.outfit)
	if live(entry.weapon, entry.world) then
		World.update_unit(entry.world, entry.weapon)
	end
	if mod._apply_warlock_animation_blend then
		mod._apply_warlock_animation_blend(owner, entry.outfit)
	end
	local channels = ownership(owner, entry)
	if channels.upper_body == "authored" then
		follow_authored_weapon(owner, entry, channels)
		return
	elseif channels.upper_body ~= "legacy" then
		restore_native_weapon(owner, entry)
		entry.status = "unsupported_ownership"
		return
	end
	if not restore_native_weapon(owner, entry) then entry.status = "invalid_weapon_graph"; return end
	if not entry.mirrored then
		-- There are no authored jump clips on the custom rig. Pulling only the
		-- upper torso onto a jumping native pelvis would stretch the body.
		entry.status = "unsupported_event"
		return
	end
	local writes, status = prepare_legacy(owner, entry)
	if not writes then entry.status = status; return end
	for i = 1, #writes do
		local write = writes[i]
		Unit.set_local_rotation(entry.outfit, write.node, write.rotation)
		Unit.set_local_position(entry.outfit, write.node, write.position)
	end
	World.update_unit(entry.world, entry.outfit)
	entry.status = "active"
end

function mod._start_warlock_grip_alignment(owner, outfit, inventory)
	if owner then mod._stop_warlock_grip_alignment(owner) end
	if not owner or not Unit.alive(owner) or not outfit or not Unit.alive(outfit)
		or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= outfit
		or Unit.get_data(outfit, "unit_name") ~= OUTFIT then return false end
	local world = Unit.world(owner)
	if not world or Unit.world(outfit) ~= world then return false end
	local node_pairs, parents = target_pairs(owner, outfit)
	if not node_pairs then return false end
	local weapon
	for _, item in pairs(inventory and inventory.inventory_item_units or {}) do
		if live(item, world) and Unit.get_data(item, "unit_name") == WEAPON then weapon = item; break end
	end
	entries[owner] = { world = world, outfit = outfit, weapon = weapon, inventory = inventory, pairs = node_pairs,
		parents = parents, mirrored = true, status = "armed" }
	return true
end

function mod._note_warlock_grip_alignment_event(owner, event, mirrored)
	local entry = entries[owner]
	if entry then entry.mirrored = mirrored == true end
end

function mod._warlock_grip_alignment_status(owner)
	return entries[owner] and entries[owner].status or "off"
end

function mod._stop_warlock_grip_alignment(owner)
	if not owner then return end
	local entry = entries[owner]
	if entry then unlink_weapon(entry) end
	entries[owner] = nil
end

function mod._stop_warlock_grip_alignment_item(owner, item)
	local entry = entries[owner]
	if not entry or not live(item, entry.world) or Unit.get_data(item, "unit_name") ~= WEAPON then return end
	if item == entry.weapon then unlink_weapon(entry) end
	entry.stopped_items = entry.stopped_items or setmetatable({}, { __mode = "k" })
	entry.stopped_items[item] = true
end

function mod._resume_warlock_grip_alignment_item(owner, item)
	if not owner or not item then return end
	local entry = entries[owner]
	if entry and entry.stopped_items then entry.stopped_items[item] = nil end
end

function mod._reset_warlock_grip_alignment()
	for owner, entry in pairs(entries) do mod:pcall(release_weapon, owner, entry) end
	entries, pending, epoch = {}, {}, epoch + 1
end

function mod._release_warlock_grip_alignment_world(world)
	pending = {}
	epoch = epoch + 1
	for owner, entry in pairs(entries) do
		if entry.world == world then unlink_weapon(entry); entries[owner] = nil end
	end
end

function mod._queue_warlock_grip_alignment(world, dt)
	-- A finite hitch still evaluates both ASMs. Presentation must run after
	-- that evaluation so the compositor can release a completed bridge and
	-- correct the current legacy endpoint before the scene is displayed. Only
	-- locomotion derivatives use the short-frame bound; this callback uses no dt.
	if pending[world] or not next(entries) or not finite(dt) or dt <= 0 then return end
	local entity = Managers.state.entity
	local animation = entity and entity:system("animation_system")
	if not animation then return end
	local queued_epoch = epoch
	pending[world] = true
	animation:add_safe_animation_callback(function()
		if epoch ~= queued_epoch then return end
		pending[world] = nil
		for owner, entry in pairs(entries) do
			if entry.world == world then
				if valid(owner, entry) then
					if not mod:pcall(apply, owner, entry) then
						mod:pcall(release_weapon, owner, entry)
						entries[owner] = nil
					elseif mod._apply_warlock_outfit_correction then
						mod:pcall(mod._apply_warlock_outfit_correction, owner, entry.outfit, false)
					end
				else
					mod:pcall(release_weapon, owner, entry)
					entries[owner] = nil
				end
			end
		end
	end)
end
