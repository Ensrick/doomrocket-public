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
    local max_links,max_frames,held_speed=0,0,0
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
        links=max_links,frames=max_frames,resets=s.resets,render_resets=s.render_resets,shape_error=shape_error(s)}
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
        self.assertGreater(result.final, .005)
        self.assertLess(result.final, .15)
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
                self.assertGreater(result.held_displacement, .002)
                self.assertLess(result.end_speed, .002)
                self.assertLess(result.shape_error, .15)
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
        self.assertLess(allocated, .1)

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
