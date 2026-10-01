-- Numeric-only frame/shape adapter. No temporary native vector survives a call.
local Frames = {}
Frames.__index = Frames
local sqrt, abs = math.sqrt, math.abs
local function dot(a,b) return a[1]*b[1]+a[2]*b[2]+a[3]*b[3] end
local function cross(a,b,out)
    out[1],out[2],out[3]=a[2]*b[3]-a[3]*b[2],a[3]*b[1]-a[1]*b[3],a[1]*b[2]-a[2]*b[1]
    return out
end
local function normalize(v)
    local length=sqrt(dot(v,v))
    if length~=length or length<1e-8 or length>1e6 then return false end
    for i=1,3 do v[i]=v[i]/length end
    return true
end
local function new_pose() return {x_axis={1,0,0},y_axis={0,1,0},z_axis={0,0,1},position={0,0,0}} end
local function copy(a,b) for i=1,3 do b[i]=a[i] end end
local function world_direction(pose,local_direction,out)
    for i=1,3 do out[i]=pose.x_axis[i]*local_direction[1]+pose.y_axis[i]*local_direction[2]+pose.z_axis[i]*local_direction[3] end
end
local function local_direction(pose,v)
    return {dot(v,pose.x_axis),dot(v,pose.y_axis),dot(v,pose.z_axis)}
end
-- Minimal rotation with a deterministic antiparallel axis. Caller supplies a
-- radial direction perpendicular to from; no Quaternion.look pole singularity.
local function rotate(v,from,to,radial,out,k,work)
    local cosine=math.max(-1,math.min(1,dot(from,to)))
    if cosine<-.999999 then
        local projection=dot(v,radial)
        for j=1,3 do out[j]=2*projection*radial[j]-v[j] end
    else
        cross(from,to,k)
        cross(k,v,work)
        local vx,vy,vz=work[1],work[2],work[3]
        cross(k,work,out)
        out[1]=v[1]+vx+out[1]/(1+cosine)
        out[2]=v[2]+vy+out[2]/(1+cosine)
        out[3]=v[3]+vz+out[3]/(1+cosine)
    end
end

function Frames.new(profile)
    local n=#profile.controls
    local self=setmetatable({n=n,poses={},offsets={},fractions={},radials={},tangents={},coarse_tangents={},previous_tangents={},
        chord={},current_chord={},radial={},offset={},rotated={},rotated_y={},k={},work={},scratch={},
        previous_pack=new_pose(),initialized=false},Frames)
    local first,last=profile.controls[1].rest,profile.controls[n].rest
    local chord={last.position[1]-first.position[1],last.position[2]-first.position[2],last.position[3]-first.position[3]}
    self.rest_chord=local_direction(first,chord)
    local total,travelled=0,0
    for i=1,#profile.lengths do total=total+profile.lengths[i] end
    self.length=total
    self.rest_span=sqrt(dot(chord,chord))
    for i=1,n do
        local rest=profile.controls[i].rest
        local fraction=travelled/total
        local offset={}
        for j=1,3 do offset[j]=rest.position[j]-first.position[j]-fraction*chord[j] end
        self.offsets[i]=local_direction(first,offset)
        self.radials[i]=local_direction(first,rest.x_axis)
        self.tangents[i]=local_direction(first,rest.y_axis)
        -- Preserve the authored dense-curve tangent instead of silently
        -- replacing it by the more coarsely sampled simulation tangent.
        local before=profile.controls[math.max(1,i-1)].rest.position
        local after=profile.controls[math.min(n,i+1)].rest.position
        local tangent={after[1]-before[1],after[2]-before[2],after[3]-before[3]}
        normalize(tangent)
        self.coarse_tangents[i]=local_direction(first,tangent)
        self.previous_tangents[i]={0,1,0}
        self.fractions[i]=fraction
        self.poses[i]=new_pose()
        if i<n then travelled=travelled+profile.lengths[i] end
    end
    return self
end

function Frames:shape(solver,pack,weapon)
    world_direction(pack,self.rest_chord,self.chord)
    if not normalize(self.chord) then return false end
    for j=1,3 do self.current_chord[j]=weapon.position[j]-pack.position[j] end
    local span=sqrt(dot(self.current_chord,self.current_chord))
    -- A nearly straight hose cannot retain the full rest bend under tension.
    -- Relax its curvature target continuously using available chord slack;
    -- rest shape is unchanged at/rest-below its authored chord, and no segment
    -- rest length changes. Full extension has a straight, feasible target.
    local rest_slack=self.length*self.length-self.rest_span*self.rest_span
    local curvature_scale=1
    if span>self.rest_span and rest_slack>1e-10 then
        curvature_scale=math.sqrt(math.max(0,(self.length*self.length-span*span)/rest_slack))
    end
    if not normalize(self.current_chord) then copy(self.chord,self.current_chord) end
    copy(pack.x_axis,self.radial)
    local projection=dot(self.radial,self.chord)
    for j=1,3 do self.radial[j]=self.radial[j]-projection*self.chord[j] end
    if not normalize(self.radial) then
        copy(pack.z_axis,self.radial)
        projection=dot(self.radial,self.chord)
        for j=1,3 do self.radial[j]=self.radial[j]-projection*self.chord[j] end
        if not normalize(self.radial) then return false end
    end
    for i=1,self.n do
        world_direction(pack,self.offsets[i],self.offset)
        rotate(self.offset,self.chord,self.current_chord,self.radial,self.rotated,self.k,self.work)
        local t=self.fractions[i]
        if not solver:set_shape_point(i,
            pack.position[1]+t*(weapon.position[1]-pack.position[1])+curvature_scale*self.rotated[1],
            pack.position[2]+t*(weapon.position[2]-pack.position[2])+curvature_scale*self.rotated[2],
            pack.position[3]+t*(weapon.position[3]-pack.position[3])+curvature_scale*self.rotated[3]) then return false end
    end
    return solver:enable_shape()
end

local function pack_rotation(previous,current,v,out)
    local x,y,z=dot(v,previous.x_axis),dot(v,previous.y_axis),dot(v,previous.z_axis)
    for j=1,3 do out[j]=current.x_axis[j]*x+current.y_axis[j]*y+current.z_axis[j]*z end
end

function Frames:update(solver,pack,weapon,reinitialize)
    if reinitialize then self.initialized=false end
    for i=1,self.n do
        local pose=self.poses[i]
        if i==1 or i==self.n then
            local endpoint=i==1 and pack or weapon
            copy(endpoint.x_axis,pose.x_axis); copy(endpoint.y_axis,pose.y_axis); copy(endpoint.z_axis,pose.z_axis)
        else
            self.scratch[1]=solver.rx[i+1]-solver.rx[i-1]
            self.scratch[2]=solver.ry[i+1]-solver.ry[i-1]
            self.scratch[3]=solver.rz[i+1]-solver.rz[i-1]
            if not normalize(self.scratch) then return false end
            if not self.initialized then
                world_direction(pack,self.radials[i],pose.x_axis)
                world_direction(pack,self.tangents[i],pose.y_axis)
                world_direction(pack,self.coarse_tangents[i],self.previous_tangents[i])
                if not normalize(pose.x_axis) or not normalize(pose.y_axis)
                    or not normalize(self.previous_tangents[i]) then return false end
            else
                -- Carry rigid pack rotation before transporting along changing
                -- tangents; pure axial owner rotation must rotate hose roll too.
                pack_rotation(self.previous_pack,pack,pose.x_axis,self.rotated)
                copy(self.rotated,pose.x_axis)
                pack_rotation(self.previous_pack,pack,pose.y_axis,self.rotated)
                copy(self.rotated,pose.y_axis)
                pack_rotation(self.previous_pack,pack,self.previous_tangents[i],self.rotated)
                copy(self.rotated,self.previous_tangents[i])
                if not normalize(pose.x_axis) or not normalize(pose.y_axis)
                    or not normalize(self.previous_tangents[i]) then return false end
            end
            copy(pose.x_axis,self.radial)
            local radial_projection=dot(self.radial,self.previous_tangents[i])
            for j=1,3 do self.radial[j]=self.radial[j]-radial_projection*self.previous_tangents[i][j] end
            if not normalize(self.radial) then return false end
            rotate(pose.x_axis,self.previous_tangents[i],self.scratch,self.radial,self.rotated,self.k,self.work)
            rotate(pose.y_axis,self.previous_tangents[i],self.scratch,self.radial,self.rotated_y,self.k,self.work)
            copy(self.rotated_y,pose.y_axis)
            if not normalize(pose.y_axis) then return false end
            copy(self.scratch,self.previous_tangents[i])
            local projection=dot(self.rotated,pose.y_axis)
            for j=1,3 do pose.x_axis[j]=self.rotated[j]-projection*pose.y_axis[j] end
            if not normalize(pose.x_axis) then return false end
            cross(pose.x_axis,pose.y_axis,pose.z_axis)
            if not normalize(pose.z_axis) then return false end
        end
        pose.position[1],pose.position[2],pose.position[3]=solver.rx[i],solver.ry[i],solver.rz[i]
    end
    copy(pack.x_axis,self.previous_pack.x_axis); copy(pack.y_axis,self.previous_pack.y_axis); copy(pack.z_axis,self.previous_pack.z_axis)
    self.initialized=true
    return true
end
return Frames
