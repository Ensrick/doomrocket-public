local mod = get_mod("doomrocket")

local DoomrocketBallistics = {
	GRAVITY = 9.82,
	SECONDS_PER_METRE = 0.13,
	-- Keep close shots beyond ProjectileRocket's 0.35 s muzzle-clear/impact-arm
	-- delay, but do not force every target inside 13 m through the same tall lob.
	MIN_FLIGHT_TIME = 0.4,
	MAX_FLIGHT_TIME = 3.4,
	MUZZLE_BACKSTEP = 0.25,
	MIN_LAUNCH_SPEED_SQUARED = 0.01,
	-- Measured mesh-local bounds of the shipped SM_Rocket's convex pRocket:
	-- Y -0.739722..0.540586 m, radial support 0.126553 m. Round outward, never
	-- substitute the old Globadier's point-sized target clearance.
	ROCKET_FORWARD_EXTENT = 0.541,
	ROCKET_REAR_EXTENT = 0.740,
	ROCKET_RADIUS = 0.127,
	TARGET_GROUND_CLEARANCE = 0.025,
}

local function flight_time_for(displacement)
	return math.clamp(
		Vector3.length(Vector3.flat(displacement)) * DoomrocketBallistics.SECONDS_PER_METRE,
		DoomrocketBallistics.MIN_FLIGHT_TIME,
		DoomrocketBallistics.MAX_FLIGHT_TIME
	)
end

-- Conservative vertical support of the convex hull in its velocity-aligned
-- frame. On descent the nose is lowest; on ascent the longer tail is lowest.
DoomrocketBallistics.lower_hull_extent = function (velocity)
	local speed = Vector3.length(velocity)

	if speed <= 0 then
		return math.sqrt(DoomrocketBallistics.ROCKET_REAR_EXTENT * DoomrocketBallistics.ROCKET_REAR_EXTENT
			+ DoomrocketBallistics.ROCKET_RADIUS * DoomrocketBallistics.ROCKET_RADIUS)
	end

	local vertical = math.clamp(velocity.z / speed, -1, 1)
	local longitudinal = vertical >= 0 and DoomrocketBallistics.ROCKET_REAR_EXTENT
		or DoomrocketBallistics.ROCKET_FORWARD_EXTENT

	return longitudinal * math.abs(vertical)
		+ DoomrocketBallistics.ROCKET_RADIUS * math.sqrt(math.max(0, 1 - vertical * vertical))
end

-- Aim the actor origin high enough that the whole rocket clears the target's
-- floor. Raising an endpoint also changes the incoming tangent, so re-evaluate
-- its support with the same deterministic flight time. Only raise the height;
-- this bounded monotone calculation retains clearance even if a later tangent
-- needs less. It changes neither the horizontal endpoint nor the time curve.
DoomrocketBallistics.clear_target_position = function (start_position, ground_position, minimum_height)
	if not Vector3.is_valid(start_position) or not Vector3.is_valid(ground_position) then
		return ground_position
	end

	local displacement = ground_position - start_position
	local flight_time = flight_time_for(displacement)
	local height = minimum_height

	for i = 1, 12 do
		local ideal_velocity = Vector3(
			displacement.x / flight_time,
			displacement.y / flight_time,
			(displacement.z + height) / flight_time + 0.5 * DoomrocketBallistics.GRAVITY * flight_time
		)
		local encoded_velocity = AiAnimUtils.velocity_network_scale(ideal_velocity, true)
		local decoded_velocity = AiAnimUtils.velocity_network_scale(encoded_velocity)
		local incoming_velocity = decoded_velocity - Vector3(0, 0, DoomrocketBallistics.GRAVITY * flight_time)
		local quantized_height_error = (decoded_velocity.z - ideal_velocity.z) * flight_time
		local required_height = DoomrocketBallistics.lower_hull_extent(incoming_velocity)
			+ DoomrocketBallistics.TARGET_GROUND_CLEARANCE - quantized_height_error

		if required_height <= height then
			break
		end

		-- Moving an ideal endpoint within one velocity bin does not move the
		-- physical endpoint at all. Cross at least one Z bin when clearance is
		-- insufficient, instead of exhausting the loop on a quantizer plateau.
		encoded_velocity[3] = encoded_velocity[3] + 1
		local next_velocity = AiAnimUtils.velocity_network_scale(encoded_velocity)
		height = math.max(required_height, height + (next_velocity.z - ideal_velocity.z) * flight_time)
	end

	return ground_position + Vector3(0, 0, height)
end

-- Return the initial velocity that reaches target_position after a deterministic,
-- range-clamped flight time under Stingray's -Z gravity. Keeping this calculation
-- here gives the animation pose and the spawned projectile one source of truth.
DoomrocketBallistics.solve_launch_velocity = function (start_position, target_position)
	if not Vector3.is_valid(start_position) or not Vector3.is_valid(target_position) then
		return nil, nil
	end

	local displacement = target_position - start_position
	local flight_time = flight_time_for(displacement)
	local launch_velocity = Vector3(
		displacement.x / flight_time,
		displacement.y / flight_time,
		displacement.z / flight_time + 0.5 * DoomrocketBallistics.GRAVITY * flight_time
	)

	-- A zero (or quantizer-sized near-zero) vector is finite, but consumers must
	-- normalize it for both the animation constraint and projectile rotation.
	if not Vector3.is_valid(launch_velocity)
		or Vector3.length_squared(launch_velocity) <= DoomrocketBallistics.MIN_LAUNCH_SPEED_SQUARED then
		return nil, nil
	end

	return launch_velocity, flight_time
end

mod.doomrocket_ballistics = DoomrocketBallistics
