-- PackageManager.load(name, reference, callback, asynchronous, prioritize), from
-- VT2 foundation/scripts/managers/package/package_manager.lua. Never flush a
-- cosmetic package in the inventory/spawn path. Poll emitter residency from
-- mod.update; VMF completion callbacks only finish owned package disposal.
local package_api = {}
local mod = get_mod("doomrocket")
local state = mod._doomrocket_effect_package_operations or {
	active = setmetatable({}, { __mode = "k" }),
	releasing = setmetatable({}, { __mode = "k" }),
	unloading = setmetatable({}, { __mode = "k" }),
}
state.unloading = state.unloading or setmetatable({}, { __mode = "k" })
mod._doomrocket_effect_package_operations = state

package_api.ensure = function (packages, name, reference)
	if state.unloading[packages] then return false, "package_releasing" end
	if state.active[packages] then return false, "package_pending" end
	state.releasing[packages] = nil -- a new live lease supersedes deferred retirement
	local manager = Managers.package
	if not manager or not Application.can_get("package", name) then
		return false, "package_unavailable"
	end

	if packages[name] and packages[name] ~= manager then
		-- The retired manager owns its own teardown. Do not query or decrement it.
		packages[name] = nil
	end

	if not packages[name] then
		-- Publish ownership before calling load: a wrapper may reset/release while
		-- the request is being enqueued. reference_count also sees pending loads.
		packages[name] = manager
		state.active[packages] = (state.active[packages] or 0) + 1
		local loaded = pcall(manager.load, manager, name, reference, nil, true)
		local remaining = state.active[packages] - 1
		state.active[packages] = remaining > 0 and remaining or nil
		local deferred_release = state.releasing[packages]
		if deferred_release and not state.active[packages] then
			state.releasing[packages] = nil
			package_api.release(packages, deferred_release.reference, deferred_release.order)
			return false, "package_cancelled"
		end
		if manager ~= Managers.package then
			if packages[name] == manager then packages[name] = nil end
			return false, "package_manager_changed"
		end
		if not loaded then
			if not manager:reference_count(name, reference)
				or manager:reference_count(name, reference) == 0 then
				packages[name] = nil
			end
			return false, "resource_error"
		end
	end

	if manager:has_loaded(name, reference) then
		return true
	elseif manager:is_loading(name, reference) then
		return false, "package_pending"
	end

	-- A request rejected without taking a reference must not become a permanent
	-- ready flag. A later update can retry, still using the asynchronous path.
	if not manager:reference_count(name, reference)
		or manager:reference_count(name, reference) == 0 then
		packages[name] = nil
	end
	return false, "package_not_loaded"
end

-- Delayed .mod_bundle packages belong to VMF/Mod.resource_package, not the
-- game's global PackageManager namespace. Native donors must be resident first.
package_api.ensure_mod = function (packages, name, reference)
	if state.unloading[packages] then return false, "package_releasing" end
	if state.active[packages] then return false, "package_pending" end
	state.releasing[packages] = nil
	local token = packages[name]
	local status = mod:package_status(name)
	if token and token.kind == "mod_package" then
		if status == "loaded" then token.ready = true; return true end
		if status == "loading" then return false, "package_pending" end
		-- A previously completed package can have been released by VMF teardown.
		if token.ready then packages[name] = nil; token = nil
		else
			if token.recovery_failed then return false, "resource_error" end
			-- A live world can also observe VMF's hidden loading_cancelled state.
			-- Revive its same request/callback now rather than wait for a reset.
			state.active[packages] = 1
			pcall(token.owner.load_package, token.owner, name, token.completed, false)
			state.active[packages] = nil
			status = token.owner:package_status(name)
			local deferred = state.releasing[packages]
			if deferred then
				state.releasing[packages] = nil
				package_api.release(packages, deferred.reference, deferred.order)
				return false, "package_cancelled"
			elseif not status then
				token.recovery_failed = true
				return false, "resource_error"
			elseif status == "loaded" then
				token.ready = true
				return true
			end
			return false, "package_pending"
		end
	elseif status then
		-- No per-consumer refs exist in VMF: never claim a package we did not load.
		return false, "package_already_owned"
	end

	token = { kind = "mod_package", owner = mod, ready = false }
	packages[name] = token
	state.active[packages] = 1
	local function completed()
		if packages[name] ~= token then return end
		token.ready = true
		-- No emitter, unit or world APIs run here. A cancelled cosmetic request
		-- can finish safe ordered package disposal even while mod.update is off.
		local deferred = state.releasing[packages]
		if deferred and not state.active[packages] then
			state.releasing[packages] = nil
			package_api.release(packages, deferred.reference, deferred.order)
		end
	end
	token.completed = completed
	local requested = pcall(mod.load_package, mod, name, completed, false)
	state.active[packages] = nil
	status = mod:package_status(name)
	if not status and not token.ready then
		-- Public nil can also mean loading_cancelled; never infer native teardown
		-- from it. Recovery below restores a completion callback before disposal.
		token.failed = true
	end
	local deferred = state.releasing[packages]
	if deferred then
		state.releasing[packages] = nil
		package_api.release(packages, deferred.reference, deferred.order)
		return false, "package_cancelled"
	elseif not requested or not status then
		return false, "resource_error"
	elseif status == "loaded" then
		token.ready = true
		return true
	end
	return false, "package_pending"
end

package_api.release = function (packages, reference, order)
	if state.active[packages] then
		-- A wrapper can reset before native load has acquired its reference. Keep
		-- the ownership claim until load unwinds, then cancel the actual request.
		state.releasing[packages] = { reference = reference, order = order }
		return
	end
	state.active[packages] = 1
	state.unloading[packages] = true
	local function release(name, manager)
		if manager.kind == "mod_package" then
			local status = manager.owner:package_status(name)
			if not status and not manager.ready and not manager.recovery_failed then
				-- VMF hides loading_cancelled immediately and suppresses its old
				-- callback. Its documented async reload revives that SAME handle and
				-- installs our original completion callback; keep donors until then.
				pcall(manager.owner.load_package, manager.owner, name, manager.completed, false)
				status = manager.owner:package_status(name)
				if not status and not manager.ready then manager.recovery_failed = true end
			end
			if not status and not manager.ready then return false, "pending_mod_package" end
			if status == "loading" or not manager.ready and status then
				-- VMF unload of a loading package exposes nil status BEFORE native
				-- release. Wait for its completion callback instead, retaining donor.
				return false, "pending_mod_package"
			end
			packages[name] = nil
			if status == "loaded" then
				local unloaded = pcall(manager.owner.unload_package, manager.owner, name)
				if not unloaded then
					if manager.owner:package_status(name) then packages[name] = manager end
					return false
				end
			end
			return true
		end
		-- Claim before native unload: reentrant cleanup cannot decrement it twice,
		-- and a newly acquired replacement reference must not be erased afterward.
		packages[name] = nil
		if manager == Managers.package then
			local count = manager:reference_count(name, reference)
			if count and count > 0 then
				-- Native unload handles both queued/asynchronous and resident refs.
				local unloaded = pcall(manager.unload, manager, name, reference)
				if not unloaded then
					if manager == Managers.package then
						local retained = manager:reference_count(name, reference)
						if retained and retained > 0 then packages[name] = manager end
					end
					return false
				end
			end
		end
		return true
	end
	local success, waiting = true, false
	-- An effect package must be retired before its native material/texture donor.
	for _, name in ipairs(order or {}) do
		if packages[name] then
			local released, reason = release(name, packages[name])
			if not released then success = false; waiting = reason == "pending_mod_package"; break end
		end
	end
	if success then
		for name, manager in pairs(packages) do
			local released, reason = release(name, manager)
			if not released then success = false; waiting = reason == "pending_mod_package"; break end
		end
	end
	state.active[packages] = nil
	state.unloading[packages] = nil
	local deferred = state.releasing[packages]
	state.releasing[packages] = nil
	if waiting then
		state.releasing[packages] = deferred or { reference = reference, order = order }
	end
	if success and deferred then
		return package_api.release(packages, deferred.reference, deferred.order)
	end
	return success
end

return package_api
