local mod = get_mod("doomrocket")

local math_abs = math.abs
local math_log = math.log
local math_ex = math.exp
local math_pow = math.pow

local function radians_to_quaternion(theta, ro, phi)
    local c1 =  math.cos(theta/2)
    local c2 = math.cos(ro/2)
    local c3 = math.cos(phi/2)
    local s1 = math.sin(theta/2)
    local s2 = math.sin(ro/2)
    local s3 = math.sin(phi/2)
    local x = (s1*s2*c3) + (c1*c2*s3)
    local y = (s1*c2*c3) + (c1*s2*s3)
    local z = (c1*s2*c3) - (s1*c2*s3)
    local w = (c1*c2*c3) - (s1*s2*s3)
    local rot = Quaternion.from_elements(x, y, z, w)
    return rot
end

local function sign(x)
    return x>0 and 1 or x<0 and -1 or 0
end

local magnitude = Vector3.length
local dot_product = Vector3.dot
local normalize = Vector3.normal
local vec_dsit = Vector3.distance

local velocity = Actor.velocity
local pos_actor = Actor.position
local rot_actor = Actor.rotation
local rotate_actor = Actor.teleport_rotation
local actor_add_vel = Actor.add_velocity

local move_particles = World.move_particles
local vector4_multi = Quaternion.multiply
local quat_look = Quaternion.look

local rotate_unit = Unit.set_local_rotation
local unit_delta_rotation = Unit.delta_rotation

local linear_sphere_sweep = stingray.PhysicsWorld.linear_sphere_sweep

ProjectileRocket = class(ProjectileRocket)

ProjectileRocket.init = function (self, unit, attacker_unit, target_pos, launch_sound_unit, combat_voice_variant)
    Managers.package:load("resource_packages/breeds/skaven_warpfire_thrower", "global")
    self.unit_string = tostring(unit)
    self.unit = unit
    local actor = Unit.actor(unit, "throw")
    self.actor = actor
    self.target_z = target_pos.z
    self.target_y = target_pos.y
    self.target_x = target_pos.x
    self.attacker_unit = attacker_unit
    self.launch_z = Unit.local_position(self.attacker_unit, 0).z
    self.launch_y = Unit.local_position(self.attacker_unit, 0).y
    self.launch_x = Unit.local_position(self.attacker_unit, 0).x

    self.reached_apogee = false

    self.world = Unit.world(unit)
	-- Constructor execution is the per-peer projectile-spawn boundary: the host creates
	-- one instance in _shoot and every other peer creates one from rpc_launch_rocket.
	-- The authority includes a zero-or-variant index in that same RPC, so the first rocket
	-- in a volley produces one matching positional bark on every peer.
	mod._play_warlock_combat_voice(attacker_unit, combat_voice_variant)

	-- Prefer the launcher's p_fx node; fall back to the projectile if the weapon vanished.
	mod._play_doomrocket_launch_sound(
		launch_sound_unit and Unit.alive(launch_sound_unit) and launch_sound_unit or unit)

    local position = Actor.position(actor)
    local rotation = Actor.rotation(actor)
    self.exhaust_id = World.create_particles(self.world, "fx/chr_warp_fire_flamethrower_01", position, rotation, Vector3(0,0,1))

    self.physics_world = World.physics_world(self.world)

    self.time_pass = 0

    self.attacker_goid = Managers.state.unit_storage:go_id(self.attacker_unit)

    self.exploded = false

end

ProjectileRocket.update = function (self, dt)
    -- `rocket_explode` is a terminal transition.  A synchronous engine callback
    -- can re-enter this extension, and deletion is deferred until the spawner's
    -- cleanup pass, so never touch physics or particles after it has been claimed.
    if self.exploded then
        return
    end

    if not Unit.alive(self.unit) then
        self:rocket_explode()

        return
    end

    if self.actor then
        local vel = velocity(self.actor)
        local speed = magnitude(vel)

        local new_direction = vel.x*vel.y*vel.z
        new_direction = new_direction/math.abs(new_direction)

        if not self.current_direction then
            self.current_direction = new_direction
        end

        self:straighten_rocket(vel)
        self:move_particles(self.actor)

        -- The rocket is ballistic now (see ROCKET in bt_doomrocket_launch_action), so a
        -- slow high lob is nearly stationary in Z at the top of its arc. The old
        -- `speed < 4` test would detonate it in mid-air there. Detonate only on a real
        -- stop (impact), and only after it has cleared the muzzle.
        if self.time_pass > 0.35 and speed < 1.5 then
            self:rocket_explode()

            return
        end

        self.time_pass = self.time_pass + dt
        self.current_direction = new_direction
        self.previous_speed = speed
    end
end

ProjectileRocket.straighten_rocket = function(self, direction)
    local new_rotation = quat_look(direction)
    rotate_unit(self.unit, 0 , new_rotation)
    rotate_actor(self.actor, new_rotation)
end

-- No longer called from update. Kept for reference only.
--
-- This applied a one-frame upward kick at launch: exp(-500 * t^2) decays to ~0.7% by
-- t = 0.1s, so it was a Dirac-style impulse rather than sustained thrust. It was also
-- unreliable: `math.random(0.75, 1)` hits Lua 5.1's integer path and evaluates as
-- math.random(0, 1), so the kick was multiplied by ZERO on roughly half of all shots,
-- producing a flat dart. The arc now comes from a solved ballistic launch velocity, so
-- every shot lobs identically and predictably, which is what makes it dodgeable.
ProjectileRocket.guide_force = function(self, dt)
    return
end

ProjectileRocket.move_particles = function(self, actor)
    local pos = pos_actor(actor)
    local rot = vector4_multi(rot_actor(actor), radians_to_quaternion(0,0, math.pi))
    move_particles(self.world, self.exhaust_id, pos, rot)
end

-- danger level similar to gas rat
-- damage of 1000 is too high
ProjectileRocket.rocket_explode = function(self)
    if self.exploded or not Managers.player.is_server then
        return false
    end

    -- Claim the terminal state before calling into audio, area damage, or the unit
    -- spawner.  Issue #8 proved that create_explosion can raise after partially
    -- dispatching: setting this at the end left the physics object active and made
    -- every subsequent frame explode it again.
    self.exploded = true

    local unit = self.unit
    local actor = self.actor
    if not unit or not Unit.alive(unit) then
        -- The spawner can win the race with mod.update during level teardown.  There
        -- is no live unit left to queue, so release our registry/particle state now.
        self:destroy()

        return false
    end

    -- Snapshot the physics transform while the unit is unquestionably live.  The
    -- actor guard handles teardown races while keeping deletion on one common path.
    -- The deletion mark below is deferred, but no later callback touches the actor.
    local position = actor and Actor.position(actor)
    local rotation = actor and Actor.rotation(actor)
	local explosion_template_name = "doomrocket_explosion"
	local explosion_template_id = NetworkLookup.explosion_templates[explosion_template_name]
	local damage_source = "skaven_doomrocket"
	local damage_source_id = NetworkLookup.damage_sources[damage_source]
	-- local power_level = 1000
	local power_level = 700
	local network_transmit = Managers.state.network.network_transmit
	local attacker_unit_id = self.attacker_goid

    -- Queue deletion before any fallible impact callback.  Keep the terminal object
    -- in mod.projectiles until GrowQueue.pop_first invokes destroy(); that registry is
    -- also the deletion hook's lookup table for particle and actor cleanup.  update()
    -- is harmless while we wait because the terminal guard above returns immediately.
    Managers.state.unit_spawner:mark_for_deletion(unit)

    if not actor then
        return false
    end

	-- The explosion template is the sole playback owner for impact audio. Record the
	-- dispatch without directly triggering a duplicate local event.
	mod._doomrocket_sound_impact_requested(position)

	-- This extension updates from VMF's mod.update callback, outside the engine's safe
	-- area-damage phase.  Issue #8 captured a stale POSITION_LOOKUP inside a direct
	-- AreaDamageSystem call.  Route exactly one request back through the native server
	-- RPC handler; it executes the authoritative explosion and owns client replication.
	network_transmit:send_rpc_server("rpc_create_explosion", attacker_unit_id, false,
		position, rotation, explosion_template_id, 1, damage_source_id, power_level,
		false, attacker_unit_id)

    return true
end

ProjectileRocket.destroy = function(self)
    -- Destruction is terminal even if a late death-reaction callback retained this
    -- Lua object.  Do not clear the guard and accidentally re-arm it.
    self.exploded = true

    local unit = self.unit

    if unit then
        mod.projectiles[unit] = nil
    end

    if self.exhaust_id then
        World.destroy_particles(self.world, self.exhaust_id)
        self.exhaust_id = nil
    end

    if unit and Unit.alive(unit) then
        Unit.destroy_actor(unit, 'pRocket')
    end
    self.unit = nil
    self.actor = nil
    self.unit_string = nil
end
