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

-- #33: detonate on contact instead of after the physics body slides to a stop.
-- Casts use vanilla's static-geometry projectile filter (player projectiles'
-- static impacts) and the enemy projectile filter (the Globadier globe's
-- impact raycast); near-miss c_afro volumes are ignored as vanilla does.
local IMPACT_COLLISION_FILTERS = {
    "filter_player_ray_projectile_static_only",
    "filter_enemy_ray_projectile",
}
-- Seconds after launch before contacts count, so the muzzle is cleared.
local IMPACT_ARM_TIME = 0.1
-- Metres cast beyond one frame of travel: the rocket's half-length plus
-- physics contact offset, so contact is seen before the body bounces.
local IMPACT_MARGIN = 0.3
local IMPACT_MIN_SPEED = 0.5
-- Any physical contact changes the body's velocity far more in one frame than
-- gravity does, so a velocity that leaves its ballistic prediction by more than
-- this (m/s, plus a per-second allowance for damping on long frames) is a hit,
-- whatever the collision filters can see. v0.1.81 logs showed most rockets
-- still detonating 0.25-0.5 s late through the stop fallback.
local IMPACT_DEVIATION = 1.5
local IMPACT_DEVIATION_PER_S = 5
local GRAVITY = 9.82

ProjectileRocket = class(ProjectileRocket)

ProjectileRocket.init = function (self, unit, attacker_unit, target_pos, launch_sound_unit, combat_voice_variant)
    Managers.package:load("resource_packages/breeds/skaven_warpfire_thrower", "global")
    self.unit_string = tostring(unit)
    self.unit = unit
    local actor = Unit.actor(unit, "throw")
    self.actor = actor
	-- The native locomotion extension has already decoded the launch velocity.
	-- Align and seed its path now, before the first physics step/update can use
	-- an inherited carrier yaw or lose the initial contact segment.
	local launch_velocity = Actor.velocity(actor)
	self:straighten_rocket(launch_velocity)
	Actor.set_angular_velocity(actor, Vector3.zero())
	self:_remember_path(Actor.position(actor), launch_velocity)
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
		launch_sound_unit and Unit.alive(launch_sound_unit) and launch_sound_unit or unit, attacker_unit)

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

        local position = pos_actor(self.actor)

        if self.time_pass > IMPACT_ARM_TIME and Managers.player.is_server then
            local impact_position = self:_find_impact(position, vel, dt)

            if impact_position then
                self:_log_impact("contact", speed)
                self:rocket_explode(impact_position)

                return
            end

            if self:_left_ballistic_path(vel, dt) then
                self:_log_impact("deviation", speed)
                self:rocket_explode(position)

                return
            end
        end

        -- The rocket is ballistic now (see ROCKET in bt_doomrocket_launch_action), so a
        -- slow high lob is nearly stationary in Z at the top of its arc. The old
        -- `speed < 4` test would detonate it in mid-air there. Detonate only on a real
        -- stop (impact), and only after it has cleared the muzzle.
        -- #33: this now only backs up the contact casts above, for example when a
        -- rocket settles too slowly for either cast to see the surface.
        if self.time_pass > 0.35 and speed < 1.5 then
            self:_log_impact("stopped", speed)
            self:rocket_explode()

            return
        end

        self.time_pass = self.time_pass + dt
        self.current_direction = new_direction
        self.previous_speed = speed
        self:_remember_path(position, vel)
    end
end

ProjectileRocket.straighten_rocket = function(self, direction)
    local new_rotation = quat_look(direction)
    rotate_unit(self.unit, 0 , new_rotation)
    rotate_actor(self.actor, new_rotation)
end

-- Closest valid contact along one cast, ignoring the rocket and its shooter.
ProjectileRocket._cast_for_impact = function(self, from, vel, dt)
    local direction, speed = Vector3.direction_length(vel)

    if speed < IMPACT_MIN_SPEED then
        return nil
    end

    local physics_world = self.physics_world
    local distance = speed * dt + IMPACT_MARGIN

    PhysicsWorld.prepare_actors_for_raycast(physics_world, from, direction, 0, 1, distance * distance)

    local impact_position, impact_distance

    for f = 1, #IMPACT_COLLISION_FILTERS do
        local hits = PhysicsWorld.immediate_raycast(physics_world, from, direction, distance, "all", "collision_filter", IMPACT_COLLISION_FILTERS[f])

        for i = 1, hits and #hits or 0 do
            local hit = hits[i]
            local hit_actor = hit[4]
            local hit_unit = hit_actor and Actor.unit(hit_actor)

            if hit_unit and hit_unit ~= self.unit and hit_unit ~= self.attacker_unit
                and Unit.actor(hit_unit, "c_afro") ~= hit_actor
                and (not impact_distance or hit[2] < impact_distance) then
                impact_position = hit[1]
                impact_distance = hit[2]
            end
        end
    end

    return impact_position
end

-- Look ahead along this frame's velocity, so contact is caught before the
-- physics step can bounce the body; then re-cast the path the rocket was on
-- during the step that just elapsed (dt), which catches a contact that step
-- already resolved into a bounce or slide.
ProjectileRocket._find_impact = function(self, position, vel, dt)
    local impact_position = self:_cast_for_impact(position, vel, dt)

    if impact_position or not self.last_position_box then
        return impact_position
    end

    return self:_cast_for_impact(self.last_position_box:unbox(), self.last_velocity_box:unbox(), dt)
end

-- True when this frame's velocity is not last frame's velocity plus gravity:
-- the physics step resolved a contact (bounce, slide or graze) since then.
ProjectileRocket._left_ballistic_path = function(self, vel, dt)
    if not self.last_velocity_box or dt <= 0 then
        return false
    end

    local last = self.last_velocity_box:unbox()

    if magnitude(last) < IMPACT_MIN_SPEED then
        return false
    end

    local expected = last + Vector3(0, 0, -GRAVITY * dt)

    return magnitude(vel - expected) > IMPACT_DEVIATION + IMPACT_DEVIATION_PER_S * dt
end

ProjectileRocket._log_impact = function(self, reason, speed)
    local position = self.actor and Actor.position(self.actor) or Vector3.zero()
    printf("[doomrocket:IMPACT] reason=%s flight_s=%.2f speed=%.2f attacker_go_id=%s position=%.3f,%.3f,%.3f target=%.3f,%.3f,%.3f",
        reason, self.time_pass or 0, speed or 0, tostring(self.attacker_goid),
        position.x, position.y, position.z, self.target_x or 0, self.target_y or 0, self.target_z or 0)
end

ProjectileRocket._remember_path = function(self, position, vel)
    if self.last_position_box then
        self.last_position_box:store(position)
        self.last_velocity_box:store(vel)
    else
        self.last_position_box = Vector3Box(position)
        self.last_velocity_box = Vector3Box(vel)
    end
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
ProjectileRocket.rocket_explode = function(self, impact_position)
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

    -- #33: a detected contact detonates where the cast met the surface, not
    -- up to one frame of travel short of it where the body is now.
    if position and impact_position then
        position = impact_position
    end
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
