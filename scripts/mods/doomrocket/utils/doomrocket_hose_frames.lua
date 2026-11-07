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

-- The circular reference accommodates the carried hose's short endpoint span.
-- Retain the complete artist-curve residual: a circle by itself erases the two
-- changes of bend direction which give the hose its W-shaped silhouette (#3).
local ARC_STEPS=128
local ARC_HALF_ANGLE={}
for step=0,ARC_STEPS do
    local ratio,low,high=step/ARC_STEPS,0,math.pi
    for _=1,48 do
        local angle=(low+high)/2
        if angle>0 and math.sin(angle)/angle>ratio then low=angle else high=angle end
    end
    ARC_HALF_ANGLE[step]=(low+high)/2
end
local function half_angle(span,length)
    local position=math.min(span/length,1)*ARC_STEPS
    local step=math.min(math.floor(position),ARC_STEPS-1)
    return ARC_HALF_ANGLE[step]+(ARC_HALF_ANGLE[step+1]-ARC_HALF_ANGLE[step])*(position-step)
end
-- Fit the already-resampled curve, not just its dense reference. Cutting across
-- a curved segment during resampling shortens it; ignoring this makes the
-- distance solver fold the short target to absorb the missing hose length.
-- Reuse all numeric buffers; trial fitting never mutates the physical solver.
local function resampled_length(self,scale)
    local n=self.n
    local x,y,z=self.raw_x,self.raw_y,self.raw_z
    local distance=self.target_distance
    local total=0
    for i=1,n do
        local along=self.along[i]
        x[i]=along*self.current_chord[1]+scale*self.target_x[i]
        y[i]=along*self.current_chord[2]+scale*self.target_y[i]
        z[i]=along*self.current_chord[3]+scale*self.target_z[i]
        if i>1 then
            local dx,dy,dz=x[i]-x[i-1],y[i]-y[i-1],z[i]-z[i-1]
            total=total+sqrt(dx*dx+dy*dy+dz*dz)
        end
        distance[i]=total
    end
    local segment,length=1,0
    local sx,sy,sz=self.sample_x,self.sample_y,self.sample_z
    for i=1,n do
        local wanted=self.fractions[i]*total
        while segment<n-1 and distance[segment+1]<wanted do segment=segment+1 end
        local edge=distance[segment+1]-distance[segment]
        local t=edge>1e-10 and (wanted-distance[segment])/edge or 0
        sx[i]=x[segment]+t*(x[segment+1]-x[segment])
        sy[i]=y[segment]+t*(y[segment+1]-y[segment])
        sz[i]=z[segment]+t*(z[segment+1]-z[segment])
        if i>1 then
            local dx,dy,dz=sx[i]-sx[i-1],sy[i]-sy[i-1],sz[i]-sz[i-1]
            length=length+sqrt(dx*dx+dy*dy+dz*dz)
        end
    end
    return length
end

function Frames.new(profile)
    local n=#profile.controls
    local self=setmetatable({n=n,poses={},offsets={},fractions={},radials={},tangents={},coarse_tangents={},
        chord={},current_chord={},radial={},offset={},rotated={},k={},work={},scratch={},
        bow={0,0,0},sag={0,0,0},residuals={},along={},target_x={},target_y={},target_z={},
        raw_x={},raw_y={},raw_z={},sample_x={},sample_y={},sample_z={},target_distance={},
        frame_x={},frame_y={},frame_z={},roll_x={},roll_y={},twist=0},Frames)
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
        self.fractions[i]=fraction
        self.poses[i]=new_pose()
        self.residuals[i]={0,0,0}
        self.along[i],self.target_x[i],self.target_y[i],self.target_z[i]=0,0,0,0
        self.raw_x[i],self.raw_y[i],self.raw_z[i],self.target_distance[i]=0,0,0,0
        self.sample_x[i],self.sample_y[i],self.sample_z[i]=0,0,0
        for j=1,3 do self.bow[j]=self.bow[j]+self.offsets[i][j]/n end
        if i<n then travelled=travelled+profile.lengths[i] end
    end
    local direction=local_direction(first,chord)
    normalize(direction)
    local projection=dot(self.bow,direction)
    for j=1,3 do self.sag[j]=self.bow[j]-projection*direction[j] end
    assert(normalize(self.sag),'authored hose has no reference bow')
    local half=half_angle(self.rest_span,self.length)
    local radius=self.length/(2*half)
    for i=2,n-1 do
        local t=self.fractions[i]
        local along=math.sin(half*(2*t-1))*radius
        local bulge=(math.cos(half*(2*t-1))-math.cos(half))*radius
        for j=1,3 do
            self.residuals[i][j]=self.offsets[i][j]+(t-.5)*self.rest_chord[j]-along*direction[j]-bulge*self.sag[j]
        end
    end
    -- Record each authored bone against the rotation-minimizing frame of the rest
    -- curve, so the live frame reproduces the rest pose and its authored roll.
    local x,y,z={1,0,0},{0,1,0},{0,0,1}
    local moved,k,work={},{},{}
    for i=1,n do
        local to=(i==1 or i==n) and self.tangents[i] or self.coarse_tangents[i]
        self.frame_x[i],self.frame_y[i],self.frame_z[i]={1,0,0},{0,1,0},{0,0,1}
        if i>1 then
            rotate(x,y,to,x,moved,k,work)
            copy(moved,x); copy(to,y)
            local projection=dot(x,y)
            for j=1,3 do x[j]=x[j]-projection*y[j] end
            normalize(x); normalize(y); cross(x,y,z)
        end
        self.roll_x[i]={dot(self.radials[i],x),dot(self.radials[i],y),dot(self.radials[i],z)}
        self.roll_y[i]={dot(self.tangents[i],x),dot(self.tangents[i],y),dot(self.tangents[i],z)}
    end
    return self
end

function Frames:shape(solver,pack,weapon)
    world_direction(pack,self.rest_chord,self.chord)
    if not normalize(self.chord) then return false end
    for j=1,3 do self.current_chord[j]=weapon.position[j]-pack.position[j] end
    local span=sqrt(dot(self.current_chord,self.current_chord))
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
    -- Keep the previously accepted stretched/rest target unchanged. Only the
    -- short-span path, which discarded the artist's W bends, needs correction.
    if span>=self.rest_span then
        local rest_slack=self.length*self.length-self.rest_span*self.rest_span
        local scale=rest_slack>1e-10 and sqrt(math.max(0,(self.length*self.length-span*span)/rest_slack)) or 1
        for i=1,self.n do
            world_direction(pack,self.offsets[i],self.offset)
            rotate(self.offset,self.chord,self.current_chord,self.radial,self.rotated,self.k,self.work)
            local t=self.fractions[i]
            if not solver:set_shape_point(i,pack.position[1]+t*span*self.current_chord[1]+scale*self.rotated[1],
                pack.position[2]+t*span*self.current_chord[2]+scale*self.rotated[2],
                pack.position[3]+t*span*self.current_chord[3]+scale*self.rotated[3]) then return false end
        end
        return solver:enable_shape()
    end
    world_direction(pack,self.sag,self.offset)
    rotate(self.offset,self.chord,self.current_chord,self.radial,self.rotated,self.k,self.work)
    copy(self.rotated,self.scratch)
    local half=half_angle(span,self.length)
    local radius=self.length/(2*half)
    local n=self.n
    for i=1,n do
        local t=self.fractions[i]
        world_direction(pack,self.residuals[i],self.offset)
        rotate(self.offset,self.chord,self.current_chord,self.radial,self.rotated,self.k,self.work)
        local along=math.sin(half*(2*t-1))*radius
        local bulge=(math.cos(half*(2*t-1))-math.cos(half))*radius
        for j=1,3 do self.rotated[j]=(.5*span+along)*self.current_chord[j]+bulge*self.scratch[j]+self.rotated[j] end
        along=dot(self.rotated,self.current_chord)
        self.along[i]=along
        self.target_x[i]=self.rotated[1]-along*self.current_chord[1]
        self.target_y[i]=self.rotated[2]-along*self.current_chord[2]
        self.target_z[i]=self.rotated[3]-along*self.current_chord[3]
    end
    -- LUT interpolation and decoded float bases must never move either fitting.
    self.along[1],self.along[n]=0,span
    self.target_x[1],self.target_y[1],self.target_z[1]=0,0,0
    self.target_x[n],self.target_y[n],self.target_z[n]=0,0,0
    local scale=self.fit_scale or 1
    local error=resampled_length(self,scale)-self.length
    if abs(error)>1e-6 then
        -- Warm-start in the previous solution's neighbourhood. The fit depends
        -- on endpoint span, not world translation or roll; ordinary walking
        -- normally converges in a few evaluations instead of a per-frame sweep.
        local low,high=math.max(0,scale*.97),scale*1.03
        local below,above=resampled_length(self,low)-self.length,resampled_length(self,high)-self.length
        if below>0 then low=0;below=resampled_length(self,low)-self.length end
        while above<0 and high<64 do high=high*2;above=resampled_length(self,high)-self.length end
        if above<0 then return false end
        local replaced=0
        for iteration=1,30 do
            -- Illinois regula falsi avoids a stalled endpoint on a curved
            -- length function. A final bounded bisection phase is fail-safe.
            if iteration>12 or above-below<1e-12 then scale=(low+high)/2
            else scale=(low*above-high*below)/(above-below) end
            error=resampled_length(self,scale)-self.length
            if abs(error)<=1e-6 then break end
            if error<0 then
                low,below=scale,error
                if replaced==-1 then above=above*.5 end
                replaced=-1
            else
                high,above=scale,error
                if replaced==1 then below=below*.5 end
                replaced=1
            end
        end
    end
    if abs(error)>2e-5 then return false end
    self.fit_scale=scale
    for i=1,n do
        if not solver:set_shape_point(i,pack.position[1]+self.sample_x[i],pack.position[2]+self.sample_y[i],pack.position[3]+self.sample_z[i]) then return false end
    end
    return solver:enable_shape()
end

-- Carry the outlet's frame along the live hose with no spin of its own, so
-- neighbouring bones cannot twist against each other and pinch the skinned tube
-- (#3). The difference from the launcher's roll is spread over the whole length.
function Frames:update(solver,pack,weapon,reinitialize)
    if reinitialize then self.twist=0 end
    local n,x,y,z=self.n,self.frame_x,self.frame_y,self.frame_z
    copy(pack.x_axis,x[1]); copy(pack.y_axis,y[1]); copy(pack.z_axis,z[1])
    for i=2,n do
        local to=y[i]
        if i==n then copy(weapon.y_axis,to)
        else
            to[1]=solver.rx[i+1]-solver.rx[i-1]
            to[2]=solver.ry[i+1]-solver.ry[i-1]
            to[3]=solver.rz[i+1]-solver.rz[i-1]
        end
        if not normalize(to) then return false end
        rotate(x[i-1],y[i-1],to,x[i-1],x[i],self.k,self.work)
        local projection=dot(x[i],to)
        for j=1,3 do x[i][j]=x[i][j]-projection*to[j] end
        if not normalize(x[i]) then return false end
        cross(x[i],to,z[i])
    end
    -- Keep the roll difference continuous from frame to frame instead of wrapping
    -- at half a turn, which would spin every bone at once.
    local roll=self.roll_x[n]
    for j=1,3 do self.scratch[j]=x[n][j]*roll[1]+y[n][j]*roll[2]+z[n][j]*roll[3] end
    cross(self.scratch,weapon.x_axis,self.work)
    local difference=math.atan2(dot(self.work,y[n]),dot(self.scratch,weapon.x_axis))-self.twist
    difference=(difference+math.pi)%(2*math.pi)-math.pi
    self.twist=self.twist+difference
    for i=1,n do
        local pose=self.poses[i]
        if i==1 or i==n then
            local endpoint=i==1 and pack or weapon
            copy(endpoint.x_axis,pose.x_axis); copy(endpoint.y_axis,pose.y_axis); copy(endpoint.z_axis,pose.z_axis)
        else
            local angle=self.twist*(i-1)/(n-1)
            local c,s=math.cos(angle),math.sin(angle)
            local rx,ry=self.roll_x[i],self.roll_y[i]
            for j=1,3 do
                local spun_x,spun_z=x[i][j]*c-z[i][j]*s,z[i][j]*c+x[i][j]*s
                pose.x_axis[j]=spun_x*rx[1]+y[i][j]*rx[2]+spun_z*rx[3]
                pose.y_axis[j]=spun_x*ry[1]+y[i][j]*ry[2]+spun_z*ry[3]
            end
            if not normalize(pose.x_axis) or not normalize(pose.y_axis) then return false end
            cross(pose.x_axis,pose.y_axis,pose.z_axis)
            if not normalize(pose.z_axis) then return false end
        end
        pose.position[1],pose.position[2],pose.position[3]=solver.rx[i],solver.ry[i],solver.rz[i]
    end
    return true
end
return Frames
