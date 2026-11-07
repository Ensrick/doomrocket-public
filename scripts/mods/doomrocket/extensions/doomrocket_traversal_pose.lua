local mod = get_mod("doomrocket")

-- The carrier owns native traversal clips that the visible controller lacks.
-- Present their checked rigid world pose on the unmarked shipping outfit only.
-- Its own ASM keeps evaluating, and its original tracks, scale channels and
-- attachment hierarchy remain untouched. A marked artist/rehearsal profile is
-- never a target, even if it currently declares a legacy state.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local FADE_SECONDS, MAX_SECONDS, MAX_RADIUS = 0.12, 8, 8
-- Ratling's inherited SmartObjectSettings.templates.special plus BTFallAction.
-- Keep intermediate falls and fence/gap variants in the same pose owner; they
-- must not briefly restore the outfit's old walk clip between jump and land.
local TRAVERSAL_EVENTS = {
	jump_up_1m = true, jump_up_3m = true, jump_up_5m = true,
	jump_up_fence_1m = true, jump_up_fence_3m = true, jump_up_fence_5m = true,
	jump_down = true, jump_down_1m = true, jump_down_land = true,
	jump_down_fence_1m = true, jump_down_fence_3m = true, jump_down_fence_5m = true,
	jump_over_gap_4m = true, falling_fwd = true, falling_bwd = true,
}
local REQUIRED = { "j_hips", "j_spine", "j_spine1", "j_head",
	"j_leftupleg", "j_leftleg", "j_leftfoot", "j_rightupleg", "j_rightleg", "j_rightfoot",
	"j_leftshoulder", "j_rightshoulder", "j_leftarm", "j_rightarm", "j_leftforearm", "j_rightforearm",
	"j_lefthand", "j_righthand", "j_leftweaponattach" }
if mod._reset_warlock_traversal_pose then mod._reset_warlock_traversal_pose() end
local entries, pending, epoch = {}, {}, 0

local function finite(n)
	return type(n) == "number" and n == n and math.abs(n) < math.huge
end

local function live(unit, world)
	return unit and Unit.alive(unit) and Unit.world(unit) == world
end

local function binding(owner, entry)
	return live(owner, entry.world) and live(entry.outfit, entry.world)
		and mod._warlock_outfits and mod._warlock_outfits[owner] == entry.outfit
end

local function healthy(owner, entry)
	local value = HEALTH_ALIVE and HEALTH_ALIVE[owner]
	if value == true then entry.health_seen = true; return true end
	return false
end

local function permitted(owner, entry)
	if Unit.get_data(entry.outfit, "warlock_rig_profile") ~= nil then return false end
	local query = mod._warlock_animation_ownership
	if not query then return false end
	local channels = query(owner, entry.outfit)
	return channels and channels.upper_body == "legacy" and channels.weapon == "legacy"
		and not channels.transitioning
end

local function note(entry, status, reason)
	entry.status = status
	-- Bounded per outfit, with no clocks, matrices or recordings required.
	if (entry.messages or 0) < 16 then
		entry.messages = (entry.messages or 0) + 1
		printf("[doomrocket:TRAVERSAL] version=%s event=%s status=%s reason=%s bones=%d weight=%.3f",
			tostring(mod._doomrocket_version), tostring(entry.event), status, tostring(reason or "none"),
			#entry.pairs, entry.weight or 0)
	end
end

local function orthogonal(pose)
	if not Matrix4x4.is_valid(pose) then return false end
	local x, y, z = Matrix4x4.x(pose), Matrix4x4.y(pose), Matrix4x4.z(pose)
	local a, b, c = Vector3.length(x), Vector3.length(y), Vector3.length(z)
	if not finite(a) or not finite(b) or not finite(c) or a < 0.000001 or b < 0.000001 or c < 0.000001 then return false end
	return math.abs(Vector3.dot(x, y)) < a*b*0.0001 and math.abs(Vector3.dot(x, z)) < a*c*0.0001
		and math.abs(Vector3.dot(y, z)) < b*c*0.0001 and Vector3.dot(x, Vector3.cross(y, z)) > 0,
		a, b, c
end

local function times(v, n)
	return Vector3(v.x*n, v.y*n, v.z*n)
end

local function quaternion(q)
	local x, y, z, w = Quaternion.to_elements(q)
	if not finite(x) or not finite(y) or not finite(z) or not finite(w) then return end
	local n = math.sqrt(x*x + y*y + z*z + w*w)
	if not finite(n) or n < 0.000001 then return end
	return { x/n, y/n, z/n, w/n }
end

local function mix_rotation(a, b, amount)
	local dot = a[1]*b[1] + a[2]*b[2] + a[3]*b[3] + a[4]*b[4]
	local sign = dot < 0 and -1 or 1
	dot = math.min(1, math.abs(dot))
	local x, y = 1-amount, amount
	if dot < 0.9995 then
		local angle = math.acos(dot)
		local sine = math.sin(angle)
		x, y = math.sin((1-amount)*angle)/sine, math.sin(amount*angle)/sine
	end
	local q, n = {}, 0
	for i = 1, 4 do q[i] = a[i]*x + b[i]*y*sign; n = n + q[i]*q[i] end
	n = math.sqrt(n)
	return Quaternion.from_elements(q[1]/n, q[2]/n, q[3]/n, q[4]/n)
end

local function skeleton(owner, entry)
	for _, pair in ipairs(entry.pairs) do
		if not Unit.has_node(owner, pair.name) or not Unit.has_node(entry.outfit, pair.name)
			or Unit.node(owner, pair.name) ~= pair.source or Unit.node(entry.outfit, pair.name) ~= pair.target then return false end
	end
	for node, parent in pairs(entry.parents) do
		if Unit.scene_graph_parent(entry.outfit, node) ~= parent then return false end
	end
	return true
end

local function prepare(owner, entry)
	if not skeleton(owner, entry) then return nil, "changed_skeleton" end
	World.update_unit(entry.world, owner)
	World.update_unit(entry.world, entry.outfit)
	local root = Unit.world_position(owner, 0)
	if not Vector3.is_valid(root) then return nil, "invalid_root" end
	local desired, resolved, writes = {}, {}, {}
	for _, pair in ipairs(entry.pairs) do
		local target = Unit.world_pose(entry.outfit, pair.target)
		local ok, a, b, c = orthogonal(target)
		if not ok or math.abs(a-b) > a*0.0001 or math.abs(a-c) > a*0.0001 then return nil, "unsupported_scale" end
		local source = Unit.world_position(owner, pair.source)
		local native_q = quaternion(Unit.world_rotation(owner, pair.source))
		local target_q = quaternion(Unit.world_rotation(entry.outfit, pair.target))
		if not Vector3.is_valid(source) or Vector3.distance(source, root) > MAX_RADIUS or not native_q or not target_q then
			return nil, "invalid_source"
		end
		local position = Matrix4x4.translation(target)
		local weight = entry.weight
		position = Vector3(position.x*(1-weight)+source.x*weight, position.y*(1-weight)+source.y*weight,
			position.z*(1-weight)+source.z*weight)
		local pose = Matrix4x4.from_quaternion_position(mix_rotation(target_q, native_q, weight), position)
		-- Native animated scale/shear never enters the custom skin. Keep the
		-- existing uniform world scale and validate every resulting local scale.
		Matrix4x4.set_x(pose, times(Matrix4x4.x(pose), a))
		Matrix4x4.set_y(pose, times(Matrix4x4.y(pose), a))
		Matrix4x4.set_z(pose, times(Matrix4x4.z(pose), a))
		desired[pair.target] = pose
	end
	local function parent_world(node)
		if desired[node] then return desired[node] end
		if resolved[node] then return resolved[node] end
		if node == 0 then return Unit.world_pose(entry.outfit, 0) end
		local pose = Matrix4x4.multiply(Unit.local_pose(entry.outfit, node), parent_world(entry.parents[node]))
		resolved[node] = pose
		return pose
	end
	for _, pair in ipairs(entry.pairs) do
		local parent = parent_world(pair.parent)
		if not orthogonal(parent) then return nil, "invalid_parent" end
		local local_pose = Matrix4x4.multiply(desired[pair.target], Matrix4x4.inverse(parent))
		local ok, a, b, c = orthogonal(local_pose)
		local scale = Unit.local_scale(entry.outfit, pair.target)
		if not ok or not Vector3.is_valid(scale) or math.abs(a-scale.x) > 0.001
			or math.abs(b-scale.y) > 0.001 or math.abs(c-scale.z) > 0.001 then return nil, "unsupported_local_scale" end
		writes[#writes+1] = { node = pair.target, rotation = Matrix4x4.rotation(local_pose), position = Matrix4x4.translation(local_pose) }
	end
	return writes
end

local function recover(entry, reason)
	if entry.active and not entry.recovering then
		entry.recovering = true
		note(entry, "recovering", reason)
	end
end

local function apply(owner, entry, dt)
	if not permitted(owner, entry) then
		entry.active, entry.weight = false, 0
		note(entry, "protected", "pose_ownership")
		return
	end
	entry.elapsed = entry.elapsed + dt
	local board = BLACKBOARDS and BLACKBOARDS[owner]
	if board then
		if board.is_climbing or board.is_jumping or board.fall_state then entry.observed_action = true
		elseif entry.observed_action then recover(entry, "action_finished") end
	end
	if entry.elapsed >= MAX_SECONDS then recover(entry, "event_timeout") end
	entry.weight = math.max(0, math.min(1, entry.weight + (entry.recovering and -dt or dt)/FADE_SECONDS))
	if entry.weight <= 0 then
		entry.active = false
		note(entry, "native", "released")
		return
	end
	local writes, reason = prepare(owner, entry)
	if not writes then
		entry.active, entry.weight = false, 0
		note(entry, "rejected", reason)
		return
	end
	-- Recheck ownership and the complete graph at the commit boundary. Nothing
	-- may redirect a queued legacy operation onto a new authored outfit.
	if not binding(owner, entry) or not healthy(owner, entry) or not permitted(owner, entry) or not skeleton(owner, entry) then
		entry.active, entry.weight = false, 0
		note(entry, "rejected", "binding_changed")
		return
	end
	for _, write in ipairs(writes) do
		Unit.set_local_rotation(entry.outfit, write.node, write.rotation)
		Unit.set_local_position(entry.outfit, write.node, write.position)
	end
	World.update_unit(entry.world, entry.outfit)
	if mod._apply_warlock_outfit_correction then mod._apply_warlock_outfit_correction(owner, entry.outfit, false) end
	if entry.status == "armed" then note(entry, "active") end
end

function mod._start_warlock_traversal_pose(owner, outfit)
	if owner then entries[owner] = nil end
	if not owner or not outfit or not Unit.alive(owner) or not Unit.alive(outfit)
		or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= outfit
		or HEALTH_ALIVE and HEALTH_ALIVE[owner] ~= nil and HEALTH_ALIVE[owner] ~= true
		or Unit.get_data(outfit, "unit_name") ~= OUTFIT or Unit.get_data(outfit, "warlock_rig_profile") ~= nil then return false end
	local world = Unit.world(owner)
	if not world or Unit.world(outfit) ~= world then return false end
	local entry = { outfit = outfit, world = world, pairs = {}, parents = {}, weight = 0, status = "native",
		health_seen = HEALTH_ALIVE and HEALTH_ALIVE[owner] == true }
	local found, seen = {}, {}
	for _, link in ipairs(AttachmentNodeLinking.doomrocket_warlock_bridge or {}) do
		local name = link.target
		if type(name) == "string" and name == link.source and not name:match("_scale$")
			and name ~= "aim_target" and Unit.has_node(owner, name) and Unit.has_node(outfit, name) then
			local target = Unit.node(outfit, name)
			if target == 0 or seen[target] then return false end
			seen[target], found[name] = true, true
			local node, path, depth = target, {}, 0
			while node ~= 0 do
				if path[node] or depth >= 256 then return false end
				local parent = Unit.scene_graph_parent(outfit, node)
				if not finite(parent) or parent ~= math.floor(parent) or parent < 0 or parent == node then return false end
				path[node], entry.parents[node], node, depth = true, parent, parent, depth+1
			end
			entry.pairs[#entry.pairs+1] = { name = name, target = target, source = Unit.node(owner, name),
				parent = Unit.scene_graph_parent(outfit, target) }
		end
	end
	for _, name in ipairs(REQUIRED) do if not found[name] then return false end end
	entries[owner] = entry
	return true
end

function mod._note_warlock_traversal_event(owner, event, mirrored)
	local entry = entries[owner]
	if not entry then return end
	if not binding(owner, entry) then entries[owner] = nil; return end
	local ready = healthy(owner, entry)
	local health = HEALTH_ALIVE and HEALTH_ALIVE[owner]
	if not ready and (entry.health_seen or health ~= nil) then entries[owner] = nil; return end
	-- Inventory precedes the initial health-cache registration. Record its first
	-- traversal event, but defer all native pose writes until health is true.
	local allowed = ready and permitted(owner, entry) or not ready
		and Unit.get_data(entry.outfit, "warlock_rig_profile") == nil
	if mirrored ~= true and TRAVERSAL_EVENTS[event] and allowed then
		entry.event, entry.active, entry.recovering, entry.elapsed, entry.observed_action = event, true, false, 0, false
		note(entry, "armed")
	else recover(entry, mirrored == true and "compatible_event" or "unsupported_event") end
end

function mod._warlock_traversal_pose_status(owner)
	return entries[owner] and entries[owner].status or "off"
end

function mod._stop_warlock_traversal_pose(owner)
	if owner then entries[owner] = nil end
end

function mod._reset_warlock_traversal_pose()
	entries, pending, epoch = {}, {}, epoch+1
end

function mod._release_warlock_traversal_world(world)
	for owner, entry in pairs(entries) do if entry.world == world then entries[owner] = nil end end
	pending[world] = nil
end

function mod._queue_warlock_traversal_pose(world, dt)
	if pending[world] or not finite(dt) or dt <= 0 then return end
	local active = false
	for _, entry in pairs(entries) do if entry.world == world and entry.active then active = true; break end end
	if not active then return end
	local entity = Managers.state.entity
	local animation = entity and entity:system("animation_system")
	if not animation then return end
	local token = { epoch = epoch }
	pending[world] = token
	animation:add_safe_animation_callback(function()
		if pending[world] ~= token or token.epoch ~= epoch then return end
		pending[world] = nil
		for owner, entry in pairs(entries) do
			if entry.world == world and entry.active then
				if not binding(owner, entry) then entries[owner] = nil
				elseif not healthy(owner, entry) then
					if entry.health_seen or HEALTH_ALIVE and HEALTH_ALIVE[owner] ~= nil then entries[owner] = nil end
				elseif not mod:pcall(apply, owner, entry, dt) then
					entry.active, entry.weight = false, 0
					note(entry, "rejected", "native_api_error")
				end
			end
		end
	end)
end
