"""Execute production semi-rigid solver/frame code on the actual 29-control rig.

No game, SDK or art checkout required. Tests reject hide/reset-masked failures.
The optional --benchmark reports Lua-only cost, excluding native bone writes.
"""
from pathlib import Path
import json
import math
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
UTILS = ROOT / "scripts/mods/doomrocket/utils"

HARNESS = r'''
local sqrt,sin,cos,abs=math.sqrt,math.sin,math.cos,math.abs
function vec(v) return {v[1],v[2],v[3]} end
function pose(v) return {x_axis=vec(v.x_axis),y_axis=vec(v.y_axis),z_axis=vec(v.z_axis),position=vec(v.position)} end
function rotate(v,y,z)
    local x,yy,zz=cos(y)*v[1]+sin(y)*v[3],v[2],-sin(y)*v[1]+cos(y)*v[3]
    return {cos(z)*x-sin(z)*yy,sin(z)*x+cos(z)*yy,zz}
end
function transformed(v,y,z,dx,dy,dz)
    local p=pose(v)
    p.x_axis=rotate(v.x_axis,y,z); p.y_axis=rotate(v.y_axis,y,z); p.z_axis=rotate(v.z_axis,y,z)
    p.position=rotate(v.position,y,z)
    p.position[1]=p.position[1]+dx; p.position[2]=p.position[2]+dy; p.position[3]=p.position[3]+dz
    return p
end
function new(gravity,damping)
    local s=Solver.new(Profile.lengths,nil,damping or 5,gravity)
    local f=Frames.new(Profile)
    local a,b=pose(Profile.controls[1].rest),pose(Profile.controls[29].rest)
    assert(f:shape(s,a,b))
    assert(s:frame(0,unpack({a.position[1],a.position[2],a.position[3],b.position[1],b.position[2],b.position[3]})))
    assert(f:update(s,a,b,true))
    return s,f,a,b
end
function tick(s,f,a,b,dt)
    assert(f:shape(s,a,b),'shape invalid')
    local visible,reason=s:frame(dt,a.position[1],a.position[2],a.position[3],b.position[1],b.position[2],b.position[3])
    assert(visible,reason)
    assert(f:update(s,a,b,false),'frame invalid')
end
function shape_error(s)
    local error=0
    for i=1,s.n do
        error=math.max(error,sqrt((s.rx[i]-s.shape_x[i])^2+(s.ry[i]-s.shape_y[i])^2+(s.rz[i]-s.shape_z[i])^2))
    end
    return error
end
function velocity(s)
    local v=0
    for i=2,s.n-1 do v=math.max(v,sqrt((s.x[i]-s.px[i])^2+(s.y[i]-s.py[i])^2+(s.z[i]-s.pz[i])^2)/s.h) end
    return v
end
function check_frames(f)
    local error=0
    for _,p in ipairs(f.poses) do
        for _,v in ipairs({p.x_axis,p.y_axis,p.z_axis,p.position}) do
            for j=1,3 do assert(v[j]==v[j] and abs(v[j])<1e6,'nonfinite frame') end
        end
        local x,y,z=p.x_axis,p.y_axis,p.z_axis
        local function dot(a,b) return a[1]*b[1]+a[2]*b[2]+a[3]*b[3] end
        error=math.max(error,abs(dot(x,x)-1),abs(dot(y,y)-1),abs(dot(z,z)-1),abs(dot(x,y)),abs(dot(y,z)),abs(dot(z,x)))
        local determinant=x[1]*(y[2]*z[3]-y[3]*z[2])-y[1]*(x[2]*z[3]-x[3]*z[2])+z[1]*(x[2]*y[3]-x[3]*y[2])
        assert(determinant>.9999,'reflected/singular frame')
    end
    return error
end
function static(gravity,seconds)
    local s,f,a,b=new(gravity)
    local first_error=shape_error(s)
    local first_pose_error=0
    for i=1,29 do for _,key in ipairs({'position','x_axis','y_axis','z_axis'}) do for j=1,3 do
        first_pose_error=math.max(first_pose_error,abs(f.poses[i][key][j]-Profile.controls[i].rest[key][j]))
    end end end
    for i=1,seconds*60 do tick(s,f,a,b,1/60) end
    return {initial=first_error,initial_pose=first_pose_error,final=shape_error(s),speed=velocity(s),
            resets=s.resets,render_resets=s.render_resets,links=s:length_error(s.rx,s.ry,s.rz),frames=check_frames(f)}
end
function moving(fps)
    local s,f,a,b=new(-9.81)
    local rest_a,rest_b=pose(a),pose(b)
    local max_links,max_frames,held_speed,held_peak_displacement=0,0,0,0
    local held_positions,checkpoints={},{}
    for frame=1,8*fps do
        local t=frame/fps
        local phase=math.min(t,2)*math.pi/2
        -- End at a fixed pose after two seconds; the velocity must continue
        -- briefly and then dissipate. This is not a prerecorded bend animation.
        a=transformed(rest_a,0,.12*sin(phase),.2*sin(phase),0,0)
        b=transformed(rest_b,0,.12*sin(phase),.2*sin(phase),0,0)
        b.position[1]=b.position[1]+.12*sin(phase)
        tick(s,f,a,b,1/fps)
        assert(s.resets==1,'unexpected reset during ordinary motion')
        max_links=math.max(max_links,s:length_error(s.rx,s.ry,s.rz))
        max_frames=math.max(max_frames,check_frames(f))
        if frame==2*fps then held_speed=velocity(s); for i=1,s.n do held_positions[i]={s.rx[i],s.ry[i],s.rz[i]} end end
        if frame>2*fps then
            for i=2,s.n-1 do
                held_peak_displacement=math.max(held_peak_displacement,sqrt((s.rx[i]-held_positions[i][1])^2+
                    (s.ry[i]-held_positions[i][2])^2+(s.rz[i]-held_positions[i][3])^2))
            end
        end
        if frame%(fps/6)==0 then
            local points={}; for i=1,s.n do points[i]={s.rx[i],s.ry[i],s.rz[i]} end
            checkpoints[#checkpoints+1]=points
        end
    end
    local displacement=0
    for i=2,s.n-1 do displacement=math.max(displacement,sqrt((s.rx[i]-held_positions[i][1])^2+(s.ry[i]-held_positions[i][2])^2+(s.rz[i]-held_positions[i][3])^2)) end
    local points={}
    for i=1,s.n do points[i]={s.rx[i],s.ry[i],s.rz[i]} end
    return {points=points,checkpoints=checkpoints,held_speed=held_speed,end_speed=velocity(s),held_displacement=displacement,
        links=max_links,frames=max_frames,resets=s.resets,render_resets=s.render_resets,shape_error=shape_error(s),
        held_peak_displacement=held_peak_displacement}
end
function frame_rigid_motion()
    local s,f,a,b=new(0)
    local expected={}
    for i=1,29 do expected[i]=pose(f.poses[i]) end
    local worst,orthogonal=0,0
    for step=1,720 do
        local y,z=step*math.pi/360,step*math.pi/250
        a=transformed(Profile.controls[1].rest,y,z,20,-30,40)
        b=transformed(Profile.controls[29].rest,y,z,20,-30,40)
        for i=1,29 do
            local p=transformed(Profile.controls[i].rest,y,z,20,-30,40)
            s.rx[i],s.ry[i],s.rz[i]=unpack(p.position)
        end
        assert(f:update(s,a,b,false))
        for i=1,29 do
            local target=transformed(expected[i],y,z,20,-30,40)
            for _,key in ipairs({'position','x_axis','y_axis','z_axis'}) do for j=1,3 do
                worst=math.max(worst,abs(f.poses[i][key][j]-target[key][j]))
            end end
        end
        orthogonal=math.max(orthogonal,check_frames(f))
    end
    return worst,orthogonal
end
function severe_rotation()
    local s,f,a,b=new(-9.81)
    local rest_a,rest_b=pose(a),pose(b)
    local max_error,max_frame=0,0
    for step=1,1200 do
        local phase=step/120*math.pi/2
        a=transformed(rest_a,.65*sin(phase),phase,0,0,1.4)
        b=transformed(rest_b,.65*sin(phase),phase,0,0,1.4)
        tick(s,f,a,b,1/120)
        max_error=math.max(max_error,s:length_error(s.rx,s.ry,s.rz))
        max_frame=math.max(max_frame,check_frames(f))
    end
    return s.resets,s.render_resets,max_error,max_frame
end
function relative_rotation(fps)
    local s,f,a,b=new(-9.81)
    local rest_b=pose(b)
    local chord={b.position[1]-a.position[1],b.position[2]-a.position[2],b.position[3]-a.position[3]}
    local maximum,frame_error,max_axis_step=0,0,0
    local axes={}
    for i=1,29 do axes[i]=vec(f.poses[i].x_axis) end
    for step=1,12*fps do
        local theta=step/fps*math.pi/3
        local current=rotate(chord,theta,0)
        b=transformed(rest_b,theta,0,0,0,0)
        for j=1,3 do b.position[j]=a.position[j]+current[j] end
        tick(s,f,a,b,1/fps)
        maximum=math.max(maximum,s:length_error(s.rx,s.ry,s.rz))
        frame_error=math.max(frame_error,check_frames(f))
        for i=2,28 do
            local v=f.poses[i].x_axis
            max_axis_step=math.max(max_axis_step,sqrt((v[1]-axes[i][1])^2+(v[2]-axes[i][2])^2+(v[3]-axes[i][3])^2))
            axes[i]=vec(v)
        end
    end
    return s.resets,s.render_resets,maximum,frame_error,max_axis_step
end
function walking(fps,cadence)
    local s,f,a,b=new(-9.81)
    local rest_a,rest_b=pose(a),pose(b)
    for step=1,2*fps do tick(s,f,a,b,1/fps) end
    local sums,squares,previous={}, {}, {}
    for i=2,s.n-1 do
        sums[i]={0,0,0}; squares[i]={0,0,0}
        previous[i]={s.rx[i]-s.shape_x[i],s.ry[i]-s.shape_y[i],s.rz[i]-s.shape_z[i]}
    end
    local count,velocity_squares,max_velocity,max_error,max_links,max_frames=0,0,0,0,0,0
    local checkpoints={}
    for step=1,8*fps do
        local t=step/fps
        local phase=2*math.pi*(cadence or 1.8)*t
        local envelope=1-math.exp(-3*t)
        -- Walking-scale carrier translation, bob and roll; the weapon has a
        -- separate 4 cm swing rather than both ends being a rigid copy.
        local dx=1.4*(t-envelope/3)
        local dy=.025*sin(phase)*envelope
        local dz=.02*(1-cos(phase))*envelope
        local roll=.025*sin(phase)*envelope
        a=transformed(rest_a,0,roll,dx,dy,dz)
        b=transformed(rest_b,0,roll,dx,dy,dz)
        b.position[2]=b.position[2]+.04*sin(phase+.5)*envelope
        tick(s,f,a,b,1/fps)
        assert(s.resets==1,'walking reset masks instability')
        max_links=math.max(max_links,s:length_error(s.rx,s.ry,s.rz))
        max_frames=math.max(max_frames,check_frames(f))
        if t>2 then
            count=count+1
            max_error=math.max(max_error,shape_error(s))
        end
        for i=2,s.n-1 do
            local offsets={s.rx[i]-s.shape_x[i],s.ry[i]-s.shape_y[i],s.rz[i]-s.shape_z[i]}
            local speed2=0
            for j=1,3 do
                if t>2 then
                    sums[i][j]=sums[i][j]+offsets[j]
                    squares[i][j]=squares[i][j]+offsets[j]^2
                    speed2=speed2+((offsets[j]-previous[i][j])*fps)^2
                end
                previous[i][j]=offsets[j]
            end
            if t>2 then
                velocity_squares=velocity_squares+speed2
                max_velocity=math.max(max_velocity,sqrt(speed2))
            end
        end
        if step%(fps/6)==0 then
            local points={}; for i=1,s.n do points[i]={s.rx[i],s.ry[i],s.rz[i]} end
            checkpoints[#checkpoints+1]=points
        end
    end
    local variance=0
    for i=2,s.n-1 do for j=1,3 do
        variance=variance+math.max(0,squares[i][j]/count-(sums[i][j]/count)^2)
    end end
    return {flap_rms=sqrt(variance/(s.n-2)),relative_speed_rms=sqrt(velocity_squares/(count*(s.n-2))),
        max_relative_speed=max_velocity,max_shape_error=max_error,links=max_links,frames=max_frames,
        resets=s.resets,render_resets=s.render_resets,checkpoints=checkpoints}
end
-- Carried pose from the v0.1.96 log: 0.347 m between the hose ends, 0.214 m
-- forward and 0.273 m up from the pack, against a 1.45 m bind chord.
function carried(fps,sway)
    local s=Solver.new(Profile.lengths,nil,5,-9.81)
    local f=Frames.new(Profile)
    local rest_a,rest_b=pose(Profile.controls[1].rest),pose(Profile.controls[29].rest)
    local a,b=pose(rest_a),pose(rest_b)
    local base={a.position[1],a.position[2]+.214,a.position[3]+.273}
    b.position=vec(base)
    assert(f:shape(s,a,b))
    assert(s:frame(0,a.position[1],a.position[2],a.position[3],b.position[1],b.position[2],b.position[3]))
    assert(f:update(s,a,b,true))
    local target=0
    for i=1,s.n-1 do
        target=target+sqrt((s.shape_x[i+1]-s.shape_x[i])^2+(s.shape_y[i+1]-s.shape_y[i])^2+(s.shape_z[i+1]-s.shape_z[i])^2)
    end
    local function dot3(u,v) return u[1]*v[1]+u[2]*v[2]+u[3]*v[3] end
    local function cross3(u,v) return {u[2]*v[3]-u[3]*v[2],u[3]*v[1]-u[1]*v[3],u[1]*v[2]-u[2]*v[1]} end
    local function unit(u) local l=sqrt(dot3(u,u)); return {u[1]/l,u[2]/l,u[3]/l} end
    -- Roll about q's long axis after removing the bend from p to q: the motion
    -- that collapses a skinned tube rather than curving it.
    local function roll(p,q)
        local from,to,x=unit(p.y_axis),unit(q.y_axis),unit(p.x_axis)
        local c=dot3(from,to)
        local k=cross3(from,to)
        local w=cross3(k,x)
        local w2=cross3(k,w)
        local moved=c>-.9999 and unit({x[1]+w[1]+w2[1]/(1+c),x[2]+w[2]+w2[2]/(1+c),x[3]+w[3]+w2[3]/(1+c)}) or x
        local target=unit(q.x_axis)
        return math.deg(math.atan2(dot3(cross3(moved,target),to),dot3(moved,target)))
    end
    local rest_roll={}
    for i=2,s.n do rest_roll[i]=roll(Profile.controls[i-1].rest,Profile.controls[i].rest) end
    local peak,twist=0,0
    for step=1,6*fps do
        local t=step/fps
        local phase=2*math.pi*1.8*t
        local envelope=1-math.exp(-2*t)
        local dx,dz=1.4*(t-envelope/2),.02*(1-cos(phase))*envelope
        a=pose(rest_a); b=pose(rest_b); b.position=vec(base)
        a.position[1]=a.position[1]+dx; a.position[3]=a.position[3]+dz
        b.position[1]=b.position[1]+dx+sway*sin(phase)*envelope
        b.position[2]=b.position[2]+sway*sin(phase+.6)*envelope
        b.position[3]=b.position[3]+dz+sway*sin(phase+1.2)*envelope
        tick(s,f,a,b,1/fps)
        if t>2 then
            peak=math.max(peak,(s:peak_bend()))
            for i=2,s.n do
                local difference=(roll(f.poses[i-1],f.poses[i])-rest_roll[i]+180)%360-180
                twist=math.max(twist,abs(difference))
            end
        end
    end
    return {target=target,length=s.length,peak=peak,twist=twist,resets=s.resets,render_resets=s.render_resets,
        links=s:length_error(s.rx,s.ry,s.rz),frames=check_frames(f)}
end
-- Only the longitudinal endpoint axes were logged. Reconstruct an orthonormal
-- frame around each measured axis and sweep the unknown roll independently;
-- these cases are not claimed to reproduce an unrecorded full native frame.
function orient_logged_y(p,y,roll)
    local function dot(a,b) return a[1]*b[1]+a[2]*b[2]+a[3]*b[3] end
    local length=sqrt(dot(y,y))
    p.y_axis={y[1]/length,y[2]/length,y[3]/length}
    local d=dot(p.x_axis,p.y_axis)
    local x={p.x_axis[1]-d*p.y_axis[1],p.x_axis[2]-d*p.y_axis[2],p.x_axis[3]-d*p.y_axis[3]}
    length=sqrt(dot(x,x))
    for j=1,3 do x[j]=x[j]/length end
    local z={x[2]*p.y_axis[3]-x[3]*p.y_axis[2],x[3]*p.y_axis[1]-x[1]*p.y_axis[3],x[1]*p.y_axis[2]-x[2]*p.y_axis[1]}
    p.x_axis={}; p.z_axis={}
    for j=1,3 do
        p.x_axis[j]=x[j]*cos(roll)-z[j]*sin(roll)
        p.z_axis[j]=z[j]*cos(roll)+x[j]*sin(roll)
    end
end
function logged_carried(case,fps,roll,pack_roll)
    local s=Solver.new(Profile.lengths,nil,5,-9.81)
    local f=Frames.new(Profile)
    local a,b=pose(Profile.controls[1].rest),pose(Profile.controls[29].rest)
    a.position=vec(case.pack); b.position=vec(case.weapon)
    orient_logged_y(a,case.pack_y,pack_roll or 0)
    orient_logged_y(b,case.weapon_y,roll)
    assert(f:shape(s,a,b))
    local target={}; for i=1,s.n do target[i]={s.shape_x[i],s.shape_y[i],s.shape_z[i]} end
    assert(s:frame(0,a.position[1],a.position[2],a.position[3],b.position[1],b.position[2],b.position[3]))
    assert(f:update(s,a,b,true))
    local peak,links,frames,axis_step,max_twist=0,0,0,0,0
    local axes={}; for i=1,s.n do axes[i]=vec(f.poses[i].x_axis) end
    for step=1,4*fps do
        local t=step/fps
        local phase=2*math.pi*1.8*t
        local envelope=1-math.exp(-2*t)
        a.position={case.pack[1]+1.4*t,case.pack[2],case.pack[3]+.02*(1-cos(phase))*envelope}
        b.position={case.weapon[1]+1.4*t+.05*sin(phase)*envelope,
            case.weapon[2]+.05*sin(phase+.6)*envelope,
            case.weapon[3]+.02*(1-cos(phase))*envelope+.05*sin(phase+1.2)*envelope}
        tick(s,f,a,b,1/fps)
        links=math.max(links,s:length_error(s.rx,s.ry,s.rz))
        frames=math.max(frames,check_frames(f))
        if t>1 then
            peak=math.max(peak,(s:peak_bend()))
            for i=2,s.n-1 do
                local x=f.poses[i].x_axis
                axis_step=math.max(axis_step,sqrt((x[1]-axes[i][1])^2+(x[2]-axes[i][2])^2+(x[3]-axes[i][3])^2))
            end
        end
        for i=1,s.n do axes[i]=vec(f.poses[i].x_axis) end
        max_twist=math.max(max_twist,abs(math.deg(f.twist)))
    end
    local points={}; for i=1,s.n do points[i]={s.rx[i],s.ry[i],s.rz[i]} end
    return {target=target,points=points,resets=s.resets,render_resets=s.render_resets,
        peak=peak,links=links,frames=frames,axis_step=axis_step,max_total_twist=max_twist}
end
function short_span_shape(span)
    local s=Solver.new(Profile.lengths,nil,5,0)
    local f=Frames.new(Profile)
    local a,b=pose(Profile.controls[1].rest),pose(Profile.controls[29].rest)
    local dx,dy,dz=b.position[1]-a.position[1],b.position[2]-a.position[2],b.position[3]-a.position[3]
    local length=sqrt(dx*dx+dy*dy+dz*dz)
    b.position={a.position[1]+span*dx/length,a.position[2]+span*dy/length,a.position[3]+span*dz/length}
    assert(f:shape(s,a,b))
    local points={};for i=1,s.n do points[i]={s.shape_x[i],s.shape_y[i],s.shape_z[i]} end
    return points,a.position,b.position
end
function compressed_benchmark(count,frames)
    local list={}
    for i=1,count do
        local s=Solver.new(Profile.lengths,nil,5,-9.81)
        local f=Frames.new(Profile)
        local a,b=pose(Profile.controls[1].rest),pose(Profile.controls[29].rest)
        b.position={a.position[1],a.position[2]+.214,a.position[3]+.273}
        list[i]={s=s,f=f,a=a,b=b}
    end
    local cold=os.clock()
    for _,v in ipairs(list) do tick(v.s,v.f,v.a,v.b,0) end
    cold=(os.clock()-cold)*1000
    local times,total,worst={},0,0
    for step=1,frames+30 do
        local start=os.clock()
        for _,v in ipairs(list) do
            v.b.position[1]=v.a.position[1]+.05*sin(step*.1)
            tick(v.s,v.f,v.a,v.b,1/60)
        end
        local elapsed=(os.clock()-start)*1000
        if step>30 then times[#times+1]=elapsed;total=total+elapsed;worst=math.max(worst,elapsed) end
    end
    table.sort(times)
    return cold,total/frames,times[math.ceil(.95*frames)],worst
end
function steady_translation(fps)
    local s,f,a,b=new(0)
    local rest_a,rest_b=pose(a),pose(b)
    for step=1,6*fps do
        local t=step/fps
        a=transformed(rest_a,0,0,1.4*t,0,0)
        b=transformed(rest_b,0,0,1.4*t,0,0)
        tick(s,f,a,b,1/fps)
        assert(s.resets==1,'translation reset masks drift')
    end
    return shape_error(s),s.resets,s.render_resets
end
function benchmark(count,frames)
    local list={}
    for i=1,count do local s,f,a,b=new(-9.81); list[i]={s=s,f=f,a=a,b=b} end
    local times={}
    local worst,total,resets=0,0,0
    for step=1,frames+30 do
        local dx=.001*sin(step*.02)
        local started=os.clock()
        for _,v in ipairs(list) do
            v.b.position[1]=Profile.controls[29].rest.position[1]+dx
            tick(v.s,v.f,v.a,v.b,1/60)
        end
        local elapsed=(os.clock()-started)*1000
        if step>30 then times[#times+1]=elapsed; total=total+elapsed; worst=math.max(worst,elapsed) end
    end
    for _,v in ipairs(list) do resets=resets+v.s.resets-1 end
    table.sort(times)
    return total/frames,times[math.ceil(.95*frames)],worst,resets
end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for name, filename in (("Profile", "doomrocket_hose_profile.lua"), ("Solver", "doomrocket_hose_solver.lua"), ("Frames", "doomrocket_hose_frames.lua")):
        lua.globals()[name] = lua.execute((UTILS / filename).read_text(encoding="utf-8"))
    lua.execute(HARNESS)
    return lua


def lua_points(points):
    return [[points[i][j] for j in range(1, 4)] for i in range(1, len(points) + 1)]


def polyline_length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def projected_turns(points):
    # Area-weighted polygon normal independently finds the hose's dominant
    # silhouette plane. It does not read the production curve/frame buffers.
    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    relative = [[p[j] - points[0][j] for j in range(3)] for p in points]
    normal = [0, 0, 0]
    for a, b in zip(relative, relative[1:]):
        area = cross(a, b)
        normal = [x + y for x, y in zip(normal, area)]
    norm = math.sqrt(dot(normal, normal))
    normal = [x / norm for x in normal]
    edges = [[b[j] - a[j] for j in range(3)] for a, b in zip(points, points[1:])]
    turns = [math.degrees(math.atan2(dot(cross(a, b), normal), dot(a, b) - dot(a, normal) * dot(b, normal)))
             for a, b in zip(edges, edges[1:])]
    # Select a stable sign convention: the large outer lobes bend negatively.
    return [-x for x in turns] if sum(turns) > 0 else turns


def turn_sign_runs(turns):
    signs = []
    for angle in turns:
        if abs(angle) < .3:
            continue
        sign = 1 if angle > 0 else -1
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return signs


class HoseDynamicsTests(unittest.TestCase):
    def test_zero_gravity_rest_shape_initializes_and_remains_authored(self):
        result = runtime().globals().static(0, 5)
        self.assertLess(result.initial, 1e-6)
        self.assertLess(result.initial_pose, 2e-6)
        self.assertLess(result.final, 1e-6)
        self.assertLess(result.speed, 1e-6)
        self.assertEqual(result.resets, 1)
        self.assertEqual(result.render_resets, 0)

    def test_gravity_deflects_but_springs_preserve_semi_rigid_rest_shape(self):
        result = runtime().globals().static(-9.81, 8)
        # A visible sag from the softer spring, without losing the rest shape.
        self.assertGreater(result.final, .055)
        self.assertLess(result.final, .070)
        self.assertLess(result.speed, .001)
        self.assertLess(result.links, .02)
        self.assertEqual(result.resets, 1)

    def test_motion_has_inertia_then_settles_at_all_frame_rates(self):
        runs = {}
        checkpoints = {}
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                result = runtime().globals().moving(fps)
                self.assertGreater(result.held_speed, .02)
                # The stopped pose can be close to eventual equilibrium. Check
                # its largest subsequent movement, rather than just the final
                # net offset, so returning to rest cannot hide real inertia.
                self.assertGreater(result.held_peak_displacement, .004)
                self.assertLess(result.end_speed, .002)
                self.assertLess(result.shape_error, .07)
                self.assertLess(result.links, .02)
                self.assertLess(result.frames, 2e-6)
                self.assertEqual(result.render_resets, 0)
                runs[fps] = [[result.points[i][j] for j in range(1, 4)] for i in range(1, 30)]
                checkpoints[fps] = [[[result.checkpoints[k][i][j] for j in range(1, 4)] for i in range(1, 30)] for k in range(1, 49)]
        maximum = max(math.dist(a, b) for fps in (30, 144) for a, b in zip(runs[60], runs[fps]))
        self.assertLess(maximum, .002)
        moving_maximum = max(math.dist(a, b) for fps in (30, 144)
                             for one, two in zip(checkpoints[60], checkpoints[fps]) for a, b in zip(one, two))
        self.assertLess(moving_maximum, .004)

    def test_walking_damps_relative_flapping_without_rigid_copy_or_reset_masking(self):
        checkpoints = {}
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                result = runtime().globals().walking(fps)
                # Production v0.1.94 measured 32.73–33.50 mm RMS flex and
                # .369–.382 m/s relative speed on this same walking input, and
                # Crunch reported it flapping. v0.1.96 measured about 12.4 mm and
                # .14 m/s and he reported it stiff (#3). Stay between the two.
                self.assertGreater(result.flap_rms, .017)
                self.assertLess(result.flap_rms, .028)
                self.assertLess(result.relative_speed_rms, .30)
                self.assertLess(result.max_relative_speed, .55)
                self.assertLess(result.max_shape_error, .085)
                self.assertLess(result.links, .002)
                self.assertLess(result.frames, 2e-6)
                self.assertEqual(result.resets, 1)
                self.assertEqual(result.render_resets, 0)
                checkpoints[fps] = [[[result.checkpoints[k][i][j] for j in range(1, 4)]
                                     for i in range(1, 30)] for k in range(1, 49)]
        maximum = max(math.dist(a, b) for fps in (30, 144)
                      for one, two in zip(checkpoints[60], checkpoints[fps]) for a, b in zip(one, two))
        self.assertLess(maximum, .002)

    def test_carried_short_chord_neither_folds_nor_twists_the_hose(self):
        # v0.1.96 on this input: target 0.52 m shorter than the hose, 138 degree
        # joints and 44 degrees of extra twist between neighbouring bones, the
        # section Crunch filmed deforming. The worst case stays free of folds too.
        for fps in (30, 60, 144):
            # A W has a reversing bend, unlike the retired uniform circle.
            # Preserve that feature with smooth joints, far below a folded link.
            for sway, bend in ((.05, 50), (.15, 75)):
                with self.subTest(fps=fps, sway=sway):
                    result = runtime().globals().carried(fps, sway)
                    self.assertLess(abs(result.target - result.length), .006)
                    self.assertLess(result.peak, bend)
                    self.assertLess(result.twist, 12)
                    self.assertLess(result.links, .02)
                    self.assertLess(result.frames, 2e-6)
                    self.assertEqual(result.resets, 1)
                    self.assertEqual(result.render_resets, 0)

    def test_compressed_target_preserves_the_authored_w_bend_directions_and_length(self):
        lua = runtime()
        rest_span = lua.globals().Frames.new(lua.globals().Profile).rest_span
        length = sum(lua.globals().Profile.lengths.values())
        for span in (1e-6, .05, .347, .894, .972, .75 * rest_span, rest_span):
            with self.subTest(span=span):
                raw, start, end = lua.globals().short_span_shape(span)
                points = lua_points(raw)
                self.assertLess(math.dist(points[0], list(start.values())), 1e-7)
                self.assertLess(math.dist(points[-1], list(end.values())), 1e-7)
                self.assertLess(abs(polyline_length(points) - length), 2e-5)
                turns = projected_turns(points)
                self.assertEqual(turn_sign_runs(turns), [-1, 1, -1])
                self.assertGreater(max(turns), 2)
                self.assertLess(max(map(abs, turns)), 55)

    def test_short_target_has_no_discontinuity_at_the_old_arc_boundary_or_rest_span(self):
        lua = runtime()
        rest_span = lua.globals().Frames.new(lua.globals().Profile).rest_span
        for boundary in (.75 * rest_span, rest_span):
            before = lua_points(lua.globals().short_span_shape(boundary - 1e-7)[0])
            after = lua_points(lua.globals().short_span_shape(boundary + 1e-7)[0])
            self.assertLess(max(map(math.dist, before, after)), 2e-5)

    def test_logged_endpoint_positions_and_axes_keep_w_shape_without_fold_or_reset(self):
        # Log v0.1.97-dev, 2026-11-03 19:11:18/46 and 19:12:09. It records
        # y axes only, so unknown roll is swept instead of being called native
        # full-pose evidence. These are ordinary 5 cm walking perturbations.
        cases = [
            {"pack": [-123.532585, -43.745716, -4.991587],
             "weapon": [-123.737129, -43.674507, -4.720704],
             "pack_y": [-.126, .207, -.970], "weapon_y": [-.047, -.229, .972]},
            {"pack": [-127.529732, -47.564442, -5.920027],
             "weapon": [-127.407257, -47.381378, -5.652126],
             "pack_y": [.224, .059, -.973], "weapon_y": [-.202, .113, .973]},
            {"pack": [-118.572098, -58.330685, -10.988973],
             "weapon": [-118.727859, -58.180218, -10.718066],
             "pack_y": [-.027, .241, -.970], "weapon_y": [-.138, -.188, .972]},
        ]
        for index, case in enumerate(cases):
            for fps in (30, 60, 144):
                rolls = [(0, -math.pi), (0, 0), (0, math.pi / 2)]
                if fps == 60:
                    rolls += [(-math.pi / 2, 0), (math.pi / 2, 0)]
                for pack_roll, roll in rolls:
                    with self.subTest(case=index, fps=fps, pack_roll=pack_roll, roll=roll):
                        lua = runtime()
                        native_case = lua.table_from({key: lua.table_from(value) for key, value in case.items()})
                        result = lua.globals().logged_carried(native_case, fps, roll, pack_roll)
                        self.assertEqual(turn_sign_runs(projected_turns(lua_points(result.target))), [-1, 1, -1])
                        self.assertEqual(turn_sign_runs(projected_turns(lua_points(result.points))), [-1, 1, -1])
                        self.assertLess(result.peak, 75)
                        self.assertLess(result.links, .002)
                        self.assertLess(result.frames, 2e-6)
                        self.assertLess(result.axis_step, .75)
                        self.assertEqual(result.resets, 1)
                        self.assertEqual(result.render_resets, 0)

    def test_short_span_fitting_reuses_all_buffers_without_per_frame_tables(self):
        lua = runtime()
        allocated = lua.execute('''
            local s,f,a,b=new(-9.81)
            b.position={a.position[1],a.position[2]+.214,a.position[3]+.273}
            assert(f:shape(s,a,b));assert(s:reset(a.position[1],a.position[2],a.position[3],unpack(b.position)))
            for i=1,100 do tick(s,f,a,b,1/60) end
            collectgarbage('collect'); collectgarbage('stop')
            local before=collectgarbage('count')
            for i=1,2000 do
                b.position[1]=a.position[1]+.05*math.sin(i*.1)
                tick(s,f,a,b,1/60)
            end
            local delta=collectgarbage('count')-before
            collectgarbage('restart')
            return delta
        ''')
        self.assertLess(allocated, 4)

    def test_walking_cadence_sweep_does_not_resonate_into_large_flaps(self):
        # The 140 s^-2 spring's undamped natural frequency is about 1.88 Hz.
        # Cover slow steps through that resonance and into a quick gait.
        for cadence in (.8, 1.2, 2.4, 3):
            with self.subTest(cadence=cadence):
                result = runtime().globals().walking(60, cadence)
                self.assertGreater(result.flap_rms, .001)
                self.assertLess(result.flap_rms, .045)
                self.assertLess(result.relative_speed_rms, .80)
                self.assertLess(result.max_shape_error, .100)
                self.assertLess(result.links, .002)
                self.assertLess(result.frames, 2e-6)
                self.assertEqual(result.resets, 1)
                self.assertEqual(result.render_resets, 0)

    def test_constant_carrier_velocity_does_not_create_world_drag(self):
        # Include FPS above the physical 120 Hz rate: previous target velocity
        # must span skipped solver frames, not just the last render interval.
        for fps in (30, 60, 144, 240):
            with self.subTest(fps=fps):
                error, resets, render_resets = runtime().globals().steady_translation(fps)
                self.assertLess(error, 1e-5)
                self.assertEqual(resets, 1)
                self.assertEqual(render_resets, 0)

    def test_frame_transport_is_rigid_rotation_translation_covariant(self):
        maximum, orthogonal = runtime().globals().frame_rigid_motion()
        self.assertLess(maximum, .0001)
        self.assertLess(orthogonal, 2e-6)

    def test_large_rotations_never_mask_failure_with_resets(self):
        resets, render_resets, links, frames = runtime().globals().severe_rotation()
        # First sample deliberately changes elevation by1.4m: explicit teleport.
        self.assertEqual(resets, 2)
        self.assertEqual(render_resets, 0)
        self.assertLess(links, .02)
        self.assertLess(frames, 2e-6)

    def test_independent_weapon_rotation_crosses_antiparallel_chord_without_snaps(self):
        for fps in (30, 60, 144):
            with self.subTest(fps=fps):
                resets, render_resets, links, frames, axis_step = runtime().globals().relative_rotation(fps)
                self.assertEqual(resets, 1)
                self.assertEqual(render_resets, 0)
                self.assertLess(links, .02)
                self.assertLess(frames, 2e-6)
                self.assertLess(axis_step, .5)

    def test_steady_state_production_math_allocates_no_per_frame_tables(self):
        lua = runtime()
        allocated = lua.execute('''
            local s,f,a,b=new(-9.81)
            for i=1,100 do tick(s,f,a,b,1/60) end
            collectgarbage('collect'); collectgarbage('stop')
            local before=collectgarbage('count')
            for i=1,2000 do tick(s,f,a,b,1/60) end
            local delta=collectgarbage('count')-before
            collectgarbage('restart')
            return delta
        ''')
        # The full collect shrinks the Lua stack, so its one regrowth (under 2 KB)
        # lands here. One small table per frame would be over 100 KB of this.
        self.assertLess(allocated, 4)

    def test_valid_fully_extended_and_nearly_extended_targets_do_not_reset_loop(self):
        lua = runtime()
        lua.execute('''
            for _,span_fraction in ipairs({.99,.9999,1}) do
                for _,fps in ipairs({30,60,144}) do
                    local s,f,a,b=new(-9.81)
                    b.position={a.position[1]+s.length*span_fraction,a.position[2],a.position[3]}
                    assert(f:shape(s,a,b))
                    assert(s:reset(a.position[1],a.position[2],a.position[3],unpack(b.position)))
                    for frame=1,fps*3 do
                        local theta=frame/fps*.2
                        b.position={a.position[1]+s.length*span_fraction*math.cos(theta),
                                    a.position[2]+s.length*span_fraction*math.sin(theta),a.position[3]}
                        tick(s,f,a,b,1/fps)
                        assert(s.resets==2,'near-taut reset loop '..span_fraction..'/'..fps..' frame '..frame..' '..tostring(s.reason))
                    end
                end
            end
        ''')

    def test_compressed_and_coincident_endpoints_remain_bounded(self):
        lua = runtime()
        lua.execute('''
            for _,fraction in ipairs({0,.05,.2}) do
                local s,f,a,b=new(-9.81)
                b.position={a.position[1]+s.length*fraction,a.position[2],a.position[3]}
                assert(f:shape(s,a,b))
                assert(s:reset(a.position[1],a.position[2],a.position[3],unpack(b.position)))
                for i=1,300 do
                    tick(s,f,a,b,1/60)
                    assert(s.resets==2,'compressed reset loop '..fraction..' frame '..i..' '..tostring(s.reason))
                end
            end
        ''')

    def test_invalid_shape_indices_partial_and_nonfinite_targets_are_rejected(self):
        lua = runtime()
        lua.execute('''
            local s=Solver.new(Profile.lengths,nil,5,0)
            assert(not s:enable_shape())
            for _,i in ipairs({0,30,1.5,-1,1/0}) do assert(not s:set_shape_point(i,0,0,0)) end
            assert(not s:set_shape_point(1,0/0,0,0))
            assert(not s:set_shape_point(1,1000001,0,0))
            assert(s:set_shape_point(1,0,0,0)); assert(not s:enable_shape())
        ''')

    def test_teleport_and_long_frame_reset_from_authored_shape_without_velocity(self):
        lua = runtime()
        lua.execute('''
            local s,f,a,b=new(0)
            a=transformed(a,0,0,100,-50,30); b=transformed(b,0,0,100,-50,30)
            tick(s,f,a,b,1/60)
            assert(s.reason=='teleport'); assert(s.resets==2); assert(velocity(s)==0)
            assert(shape_error(s)<1e-6)
            tick(s,f,a,b,.5)
            assert(s.reason=='long_frame'); assert(s.resets==3); assert(velocity(s)==0)
            assert(shape_error(s)<1e-6)
        ''')

    def test_impossible_span_hides_without_redefining_rest_lengths(self):
        lua = runtime()
        lua.execute('''
            local s,f,a,b=new(0)
            local lengths={}; for i=1,28 do lengths[i]=s.rest_lengths[i] end
            b.position={a.position[1]+s.length+.001,a.position[2],a.position[3]}
            assert(f:shape(s,a,b))
            local ok,why=s:frame(1/60,a.position[1],a.position[2],a.position[3],unpack(b.position))
            assert(not ok and why=='span_exceeds_length')
            for i=1,28 do assert(s.rest_lengths[i]==lengths[i]) end
        ''')


if __name__ == "__main__":
    if "--benchmark" in sys.argv:
        for count in (1, 20):
            mean, p95, maximum, resets = runtime().globals().benchmark(count, 240)
            print(json.dumps({"hoses": count, "fps": 60, "mean_ms": mean, "p95_ms": p95, "max_ms": maximum, "unexpected_resets": resets}))
    elif "--walking-metrics" in sys.argv:
        for fps in (30, 60, 144):
            lua = runtime()
            result = lua.globals().walking(fps)
            moving = lua.globals().moving(fps)
            print(json.dumps({"fps": fps,
                              **{key: value for key, value in result.items() if key != "checkpoints"},
                              "steady_translation_error": lua.globals().steady_translation(fps)[0],
                              "stop_peak_displacement": moving.held_peak_displacement}))
    elif "--metrics" in sys.argv:
        lua = runtime()
        for gravity in (0, -9.81):
            result = lua.globals().static(gravity, 8)
            print(json.dumps({"gravity": gravity, **dict(result.items())}))
        for fps in (30, 60, 144):
            result = lua.globals().moving(fps)
            print(json.dumps({"fps": fps, **{key: value for key, value in result.items() if key not in ("points", "checkpoints")}}))
    else:
        unittest.main(verbosity=2)
