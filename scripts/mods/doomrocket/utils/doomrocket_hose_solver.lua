-- Cosmetic runtime solver. Authored rest-shape springs preserve the semi-rigid hose.
-- Metres, two pinned ends, inertial Verlet + XPBD distance constraints.
-- Reference: Macklin et al. (2016), https://mmacklin.com/xpbd.pdf
local Solver = {}
Solver.__index = Solver
local sqrt, sin, cos, exp, abs, min, floor = math.sqrt, math.sin, math.cos, math.exp, math.abs, math.min, math.floor
local EPS = 1e-10
local DOUBLE_EPSILON = 2^-52

local function finite(v)
    return type(v) == "number" and v == v and abs(v) < 1e100
end

local function distance(ax, ay, az, bx, by, bz)
    local x, y, z = bx-ax, by-ay, bz-az
    return sqrt(x*x+y*y+z*z)
end

local function endpoints_valid(ax, ay, az, bx, by, bz)
    return finite(ax) and finite(ay) and finite(az) and finite(bx) and finite(by) and finite(bz)
        and math.max(abs(ax),abs(ay),abs(az),abs(bx),abs(by),abs(bz)) <= 1e6
end

local function span_fits(length, ax, ay, az, bx, by, bz)
    local span=distance(ax,ay,az,bx,by,bz)
    -- Subtraction/norm arithmetic on rotating or translated exact-length ends
    -- can exceed length by a few ULPs. Admit only scale-aware double roundoff;
    -- never change rest lengths or use the solver's much larger error budget.
    local scale=math.max(1,length,abs(ax),abs(ay),abs(az),abs(bx),abs(by),abs(bz))
    local tolerance=8*DOUBLE_EPSILON*scale
    return span<=length+tolerance,span
end

function Solver.new(length, segments, damping, gravity)
    local authored_lengths=type(length)=="table" and length or nil
    if authored_lengths then
        segments=#authored_lengths
        length=0
        for i=1,segments do
            assert(finite(authored_lengths[i]) and authored_lengths[i]>1e-6)
            length=length+authored_lengths[i]
        end
    end
    assert(finite(length) and length > 0 and length < 100)
    assert(type(segments) == "number" and segments == floor(segments) and segments >= 4 and segments <= 64)
    assert(length/segments > 1e-6, "Links must be longer than numerical degeneracy tolerance")
    assert(damping == nil or finite(damping) and damping >= 0)
    assert(gravity == nil or finite(gravity))
    local self = setmetatable({length=length, segments=segments, n=segments+1,
        rest=length/segments, rest_lengths={}, h=1/120, max_steps=8, iterations=4,
        compliance=1e-7, damping=damping or 1.5, gravity=gravity or -9.81,
        max_error=.02, teleport_distance=length*.5, accumulator=0,
        visible=false, resets=0, steps=0, render_resets=0,
        x={},y={},z={}, px={},py={},pz={}, before_x={},before_y={},before_z={},
        rx={},ry={},rz={}, lambdas={}, nx={},ny={},nz={},
        diagonal={}, upper={}, rhs={}, delta_lambda={},
        shape_x={},shape_y={},shape_z={}, shape_previous_x={},shape_previous_y={},shape_previous_z={},
        shape_stiffness=100, shape_acceleration_limit=40, shape_points={},shape_count=0}, Solver)
    -- All persistent numeric storage is allocated once, never per frame/substep.
    for i=1,self.n do
        self.x[i],self.y[i],self.z[i]=0,0,0
        self.px[i],self.py[i],self.pz[i]=0,0,0
        self.before_x[i],self.before_y[i],self.before_z[i]=0,0,0
        self.rx[i],self.ry[i],self.rz[i]=0,0,0
        self.shape_x[i],self.shape_y[i],self.shape_z[i]=0,0,0
        self.shape_previous_x[i],self.shape_previous_y[i],self.shape_previous_z[i]=0,0,0
        if i<self.n then
            self.lambdas[i]=0
            self.rest_lengths[i]=authored_lengths and authored_lengths[i] or self.rest
            self.nx[i],self.ny[i],self.nz[i]=0,0,0
            self.diagonal[i],self.upper[i],self.rhs[i],self.delta_lambda[i]=0,0,0,0
        end
    end
    return self
end

-- Distributed rest-shape springs add semi-rigidity without changing segment
-- lengths or connecting the character/weapon physics actors. Targets are supplied
-- in world metres by the measured authored-curve adapter, once per animation pass.
-- Stiffness 100 means acceleration 100 * displacement (s^-2), clamped to
-- 40 m/s^2. Damping is exponential velocity decay in s^-1; the game controller
-- supplies 5, while the standalone solver retains its legacy default of 1.5.
function Solver:set_shape_point(i,x,y,z)
    if not finite(i) or i~=floor(i) or i<1 or i>self.n
        or not finite(x) or not finite(y) or not finite(z)
        or math.max(abs(x),abs(y),abs(z))>1e6 then return false end
    if not self.shape_points[i] then self.shape_points[i]=true; self.shape_count=self.shape_count+1 end
    self.shape_previous_x[i]=self.shape_ready and self.shape_x[i] or x
    self.shape_previous_y[i]=self.shape_ready and self.shape_y[i] or y
    self.shape_previous_z[i]=self.shape_ready and self.shape_z[i] or z
    self.shape_x[i],self.shape_y[i],self.shape_z[i]=x,y,z
    return true
end

function Solver:enable_shape()
    if self.shape_count~=self.n then return false end
    self.shape_ready=true
    return true
end

function Solver:hide(reason)
    self.visible=false
    self.accumulator=0
    self.reason=reason
    return false,reason
end

function Solver:finish_reset(ax,ay,az,bx,by,bz,reason)
    for i=1,self.n do
        local x,y,z=self.x[i],self.y[i],self.z[i]
        self.px[i],self.py[i],self.pz[i]=x,y,z
        self.rx[i],self.ry[i],self.rz[i]=x,y,z
        if self.shape_ready then
            self.shape_previous_x[i],self.shape_previous_y[i],self.shape_previous_z[i]=self.shape_x[i],self.shape_y[i],self.shape_z[i]
        end
    end
    self.ax,self.ay,self.az,self.bx,self.by,self.bz=ax,ay,az,bx,by,bz
    self.visible=true; self.reason=reason or "reset"
    return true,self.reason
end

function Solver:reset(ax,ay,az,bx,by,bz,reason)
    self.resets=self.resets+1
    self.accumulator=0
    if not endpoints_valid(ax,ay,az,bx,by,bz) then return self:hide("invalid_endpoint") end
    local fits,span=span_fits(self.length,ax,ay,az,bx,by,bz)
    -- Impossible configurations are hidden, never solved by extending rest length.
    if not fits then return self:hide("span_exceeds_length") end
    -- Initialize from the actual semi-rigid authored target, not a generic
    -- gravity-aligned circle. This is a zero-velocity reset only: subsequent
    -- frames integrate inertia and springs, never overwrite simulated points.
    if self.shape_ready then
        for i=1,self.n do self.x[i],self.y[i],self.z[i]=self.shape_x[i],self.shape_y[i],self.shape_z[i] end
        self.x[1],self.y[1],self.z[1]=ax,ay,az
        self.x[self.n],self.y[self.n],self.z[self.n]=bx,by,bz
        if self:length_error(self.x,self.y,self.z)<1e-5 or self:project(self.x,self.y,self.z,self.compliance) then
            return self:finish_reset(ax,ay,az,bx,by,bz,reason)
        end
        -- Extreme endpoint spans can make the rest-shape target infeasible.
        -- The length-valid circle is a bounded fallback, still spring-driven.
    end
    local ux,uy,uz=1,0,0
    if span>EPS then ux,uy,uz=(bx-ax)/span,(by-ay)/span,(bz-az)/span end
    local dx,dy,dz=ux*uz,uy*uz,-1+uz*uz
    local d=sqrt(dx*dx+dy*dy+dz*dz)
    if d<EPS then dx,dy,dz=1-ux*ux,-ux*uy,-ux*uz; d=sqrt(dx*dx+dy*dy+dz*dz) end
    dx,dy,dz=dx/d,dy/d,dz/d
    local curvature,half
    if span < self.length-1e-9 then
        -- Constant-curvature circle with EACH authored chord length retained.
        -- Find curvature at a complete circle, then solve the requested chord.
        local longest=0
        for i=1,self.segments do longest=math.max(longest,self.rest_lengths[i]) end
        local lo,hi=0,2/longest
        for _=1,64 do
            local k=(lo+hi)/2
            local angle=0
            for i=1,self.segments do angle=angle+2*math.asin(min(1,self.rest_lengths[i]*k/2)) end
            if angle<2*math.pi then lo=k else hi=k end
        end
        local angle=0
        for i=1,self.segments do angle=angle+2*math.asin(min(1,self.rest_lengths[i]*hi/2)) end
        if angle<2*math.pi-1e-8 then return self:hide("unsupported_rest_distribution") end
        lo=0
        for _=1,64 do
            local k=(lo+hi)/2
            local total=0
            for i=1,self.segments do total=total+2*math.asin(min(1,self.rest_lengths[i]*k/2)) end
            local chord=2*sin(total/2)/k
            if chord>span then lo=k else hi=k end
        end
        curvature=(lo+hi)/2
        half=0
        for i=1,self.segments do half=half+math.asin(min(1,self.rest_lengths[i]*curvature/2)) end
    end
    local arc_angle=half and -half or 0
    local travelled=0
    for i=1,self.n do
        local x,y,z
        if curvature then
            if i>1 then arc_angle=arc_angle+2*math.asin(min(1,self.rest_lengths[i-1]*curvature/2)) end
            local along=sin(arc_angle)/curvature
            local sag=(cos(arc_angle)-cos(half))/curvature
            x,y,z=(ax+bx)/2+ux*along+dx*sag,(ay+by)/2+uy*along+dy*sag,(az+bz)/2+uz*along+dz*sag
        else
            if i>1 then travelled=travelled+self.rest_lengths[i-1] end
            local t=travelled/self.length
            x,y,z=ax+(bx-ax)*t,ay+(by-ay)*t,az+(bz-az)*t
        end
        self.x[i],self.y[i],self.z[i]=x,y,z
    end
    self.x[1],self.y[1],self.z[1]=ax,ay,az
    self.x[self.n],self.y[self.n],self.z[self.n]=bx,by,bz
    return self:finish_reset(ax,ay,az,bx,by,bz,reason)
end

function Solver:project(x,y,z,compliance)
    local alpha=compliance/(self.h*self.h)
    local m,n=self.segments,self.n
    local lambdas,rest=self.lambdas,self.rest_lengths
    local nx,ny,nz=self.nx,self.ny,self.nz
    local diagonal,upper,rhs,dlambda=self.diagonal,self.upper,self.rhs,self.delta_lambda
    for i=1,m do lambdas[i]=0 end
    for iteration=1,self.iterations do
        -- Coupled chain solve: J W J^T is tridiagonal. A Thomas solve projects
        -- every link together, avoiding O(N^2) tension propagation from GS sweeps.
        local max_residual,max_geometric_error=0,0
        for i=1,m do
            local j=i+1
            local dx,dy,dz=x[i]-x[j],y[i]-y[j],z[i]-z[j]
            local dist=sqrt(dx*dx+dy*dy+dz*dz)
            if dist~=dist or dist>1e100 or dist<EPS then return false end
            nx[i],ny[i],nz[i]=dx/dist,dy/dist,dz/dist
            diagonal[i]=(i==1 and 0 or 1)+(j==n and 0 or 1)+alpha+1e-8
            rhs[i]=-(dist-rest[i])-alpha*lambdas[i]
            max_residual=math.max(max_residual,abs(rhs[i])/rest[i])
            max_geometric_error=math.max(max_geometric_error,abs(dist-rest[i])/rest[i])
        end
        if max_residual<1e-5 then return max_geometric_error<=self.max_error end
        for i=1,m-1 do
            upper[i]=-(nx[i]*nx[i+1]+ny[i]*ny[i+1]+nz[i]*nz[i+1])
        end
        for i=2,m do
            local pivot=diagonal[i-1]
            if pivot~=pivot or pivot>1e100 or pivot<EPS then return false end
            local factor=upper[i-1]/pivot
            diagonal[i]=diagonal[i]-factor*upper[i-1]
            rhs[i]=rhs[i]-factor*rhs[i-1]
        end
        for i=m,1,-1 do
            local pivot=diagonal[i]
            if pivot~=pivot or pivot>1e100 or pivot<EPS then return false end
            local value=rhs[i]
            if i<m then value=value-upper[i]*dlambda[i+1] end
            local dl=value/pivot
            if dl~=dl or abs(dl)>1e100 then return false end
            dlambda[i]=dl
            lambdas[i]=lambdas[i]+dl
        end
        for i=2,n-1 do
            local a,b=dlambda[i],dlambda[i-1]
            local dx=nx[i]*a-nx[i-1]*b
            local dy=ny[i]*a-ny[i-1]*b
            local dz=nz[i]*a-nz[i-1]*b
            if dx*dx+dy*dy+dz*dz>self.length*self.length then return false end
            x[i],y[i],z[i]=x[i]+dx,y[i]+dy,z[i]+dz
        end
    end
    return self:length_error(x,y,z)<=self.max_error
end

function Solver:length_error(x,y,z)
    local worst=0
    for i=1,self.segments do
        local ratio=distance(x[i],y[i],z[i],x[i+1],y[i+1],z[i+1])/self.rest_lengths[i]
        if not finite(ratio) then return math.huge end
        worst=math.max(worst,abs(ratio-1))
    end
    return worst
end

function Solver:step(ax,ay,az,bx,by,bz,shape_fraction)
    local x,y,z=self.x,self.y,self.z
    local retention=exp(-self.damping*self.h)
    for i=1,self.n do
        self.before_x[i],self.before_y[i],self.before_z[i]=x[i],y[i],z[i]
        if i>1 and i<self.n then
            local sx,sy,sz=0,0,0
            if self.shape_ready then
                local f=shape_fraction or 1
                sx=(self.shape_previous_x[i]+(self.shape_x[i]-self.shape_previous_x[i])*f-x[i])*self.shape_stiffness
                sy=(self.shape_previous_y[i]+(self.shape_y[i]-self.shape_previous_y[i])*f-y[i])*self.shape_stiffness
                sz=(self.shape_previous_z[i]+(self.shape_z[i]-self.shape_previous_z[i])*f-z[i])*self.shape_stiffness
                local a=sqrt(sx*sx+sy*sy+sz*sz)
                if a>self.shape_acceleration_limit then
                    local scale=self.shape_acceleration_limit/a
                    sx,sy,sz=sx*scale,sy*scale,sz*scale
                end
            end
            x[i]=x[i]+(x[i]-self.px[i])*retention+sx*self.h*self.h
            y[i]=y[i]+(y[i]-self.py[i])*retention+sy*self.h*self.h
            z[i]=z[i]+(z[i]-self.pz[i])*retention+(self.gravity+sz)*self.h*self.h
        end
    end
    x[1],y[1],z[1]=ax,ay,az; x[self.n],y[self.n],z[self.n]=bx,by,bz
    self.steps=self.steps+1
    if not self:project(x,y,z,self.compliance) then return false end
    for i=1,self.n do
        self.px[i],self.py[i],self.pz[i]=self.before_x[i],self.before_y[i],self.before_z[i]
    end
    return true
end

function Solver:render_points(ax,ay,az,bx,by,bz)
    -- Extrapolate only the cosmetic output over the fractional remainder. Neither
    -- these projection corrections nor endpoint pinning feed energy into physics.
    local fraction=self.accumulator/self.h
    for i=1,self.n do
        self.rx[i]=self.x[i]+(self.x[i]-self.px[i])*fraction
        self.ry[i]=self.y[i]+(self.y[i]-self.py[i])*fraction
        self.rz[i]=self.z[i]+(self.z[i]-self.pz[i])*fraction
    end
    self.rx[1],self.ry[1],self.rz[1]=ax,ay,az
    self.rx[self.n],self.ry[self.n],self.rz[self.n]=bx,by,bz
    if fraction<EPS and self:length_error(self.rx,self.ry,self.rz)<=self.max_error then
        return true
    end
    -- Keep the same finite compliance as the physical solver. An unrelated
    -- zero-compliance render solve becomes nearly singular at full extension
    -- and can manufacture repeated resets from otherwise valid dynamics.
    return self:project(self.rx,self.ry,self.rz,self.compliance)
end

function Solver:frame(dt,ax,ay,az,bx,by,bz)
    if not endpoints_valid(ax,ay,az,bx,by,bz) then return self:hide("invalid_endpoint") end
    if not finite(dt) or dt<0 then return self:hide("invalid_dt") end
    if not span_fits(self.length,ax,ay,az,bx,by,bz) then return self:hide("span_exceeds_length") end
    if not self.visible then return self:reset(ax,ay,az,bx,by,bz,"initialize") end
    if dt==0 then
        if ax~=self.ax or ay~=self.ay or az~=self.az or bx~=self.bx or by~=self.by or bz~=self.bz then
            return self:reset(ax,ay,az,bx,by,bz,"paused_endpoint_change")
        end
        return true,"paused"
    end
    if dt>self.h*self.max_steps then return self:reset(ax,ay,az,bx,by,bz,"long_frame") end
    if distance(ax,ay,az,self.ax,self.ay,self.az)>self.teleport_distance
        or distance(bx,by,bz,self.bx,self.by,self.bz)>self.teleport_distance then
        return self:reset(ax,ay,az,bx,by,bz,"teleport")
    end
    local accumulated_before=self.accumulator
    self.accumulator=self.accumulator+dt
    local count=min(floor((self.accumulator+EPS)/self.h),self.max_steps)
    for i=1,count do
        local fraction=min(1,(i*self.h-accumulated_before)/dt)
        if not self:step(self.ax+(ax-self.ax)*fraction,self.ay+(ay-self.ay)*fraction,self.az+(az-self.az)*fraction,
            self.bx+(bx-self.bx)*fraction,self.by+(by-self.by)*fraction,self.bz+(bz-self.bz)*fraction,fraction) then
            return self:reset(ax,ay,az,bx,by,bz,"solver_error")
        end
    end
    self.accumulator=math.max(0,self.accumulator-count*self.h)
    self.ax,self.ay,self.az,self.bx,self.by,self.bz=ax,ay,az,bx,by,bz
    if not self:render_points(ax,ay,az,bx,by,bz) then
        self.render_resets=self.render_resets+1
        return self:reset(ax,ay,az,bx,by,bz,"render_error")
    end
    self.reason="simulated"
    return true,self.reason
end

return Solver
