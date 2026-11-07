local mod = get_mod("doomrocket")

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

local velocity = Actor.velocity
local magnitude = Vector3.length

AnimEmitter = class(AnimEmitter)

AnimEmitter.init = function (self, unit, blackboard)
    self.unit = unit
    self.bb = blackboard
    -- if blackboard and is_server then
    --     self.current_health = blackboard.current_health_percent
    -- end
    self.current_animation = {}

    self.current_time = 0
    self.wait_time = 99999
    self.world = Unit.world(unit)
    self.wwise_world = Wwise.wwise_world(self.world)

end

AnimEmitter.update_animation = function (self, unit, animation_event)
    local animation_time = Unit.get_data(unit, animation_event, "timing")
    local emitted_event = Unit.get_data(unit, animation_event, "emitted_event")
    if animation_time and emitted_event then
        self.current_animation = {
            animation_event = animation_event,
            time = animation_time,
            emitted_event = emitted_event
        }
        self.wait_time = self.current_time + animation_time
    end
end

AnimEmitter.emit_event = function(self)
    local emitted_event = self.current_animation.emitted_event
    if self.bb then
        self.bb[emitted_event] = true
    end
    self.current_animation = nil
    self.wait_time = 99999
    return
end

AnimEmitter.update = function (self, unit, dt)
    self.current_time = self.current_time + dt

    if not Unit.alive(unit) then
        self:destroy(unit)
        return
    end

    if (self.current_time > self.wait_time) and self.current_animation then
       self:emit_event()
    end

    if BLACKBOARDS[unit] then
        if not self.bb then
            self.bb = BLACKBOARDS[unit]
        end
    end


end



AnimEmitter.destroy = function(self, unit)
    mod.anim_emitters[unit] = nil
    self.unit = nil
    self.bb = nil
    self.current_animation = nil
    self.current_time = nil
    self.wait_time = nil
    return
end