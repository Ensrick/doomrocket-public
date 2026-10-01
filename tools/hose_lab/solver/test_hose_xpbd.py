"""Executes the non-shipping pure-Lua solver in Lua 5.1, not an engine mock."""
from pathlib import Path
import json
import argparse
import sys
import unittest
from lupa.lua51 import LuaRuntime
from lab_paths import DEFAULT_CONTRACT, generated_output, ROOT

MODULE = Path(__file__).with_name("hose_xpbd.lua")
CONTRACT = DEFAULT_CONTRACT


class LuaHoseTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().Solver=self.lua.execute(MODULE.read_text(encoding="utf-8"))
        contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.lua.globals().authored=self.lua.table_from(contract["control_rest_lengths_m"])
        self.lua.execute("""
            function new(damping,gravity)
                local s=Solver.new(2.265,12,damping,gravity)
                assert(s:reset(0,0,1.5,1.2,0,1.5))
                return s
            end
            function pinned(s,ax,ay,az,bx,by,bz)
                assert(s.visible)
                assert(s.rx[1]==ax and s.ry[1]==ay and s.rz[1]==az)
                assert(s.rx[s.n]==bx and s.ry[s.n]==by and s.rz[s.n]==bz)
            end
            function energy(s)
                local e=0
                for i=2,s.n-1 do
                    e=e+((s.x[i]-s.px[i])^2+(s.y[i]-s.py[i])^2+(s.z[i]-s.pz[i])^2)/s.h^2
                end
                return e
            end
        """)

    def test_equal_link_reset_handles_horizontal_vertical_and_coincident_ends(self):
        self.lua.execute("""
            for _,b in ipairs({{1.2,0,0},{0,0,1.2},{0,0,0}}) do
                local s=new(); assert(s:reset(0,0,0,unpack(b)))
                pinned(s,0,0,0,unpack(b))
                assert(s:length_error(s.x,s.y,s.z)<1e-9)
            end
        """)

    def test_real_inertia_and_sag_with_unchanged_endpoints(self):
        self.lua.execute("""
            local s=new()
            for i=1,240 do assert(s:frame(s.h,0,0,1.5,1.2,0,1.5)) end
            assert(s.rz[7]<1.3)
            s.py[7]=s.y[7]-.5*s.h
            local y=s.y[7]
            s:frame(s.h,0,0,1.5,1.2,0,1.5)
            local displaced=s.y[7]
            assert(displaced>y+.001)
            s:frame(s.h,0,0,1.5,1.2,0,1.5)
            assert(s.y[7]>displaced)
            pinned(s,0,0,1.5,1.2,0,1.5)
        """)

    def test_damping_dissipates_interior_motion(self):
        self.lua.execute("""
            local low,high=new(0,0),new(4,0)
            for _,s in ipairs({low,high}) do
                for i=2,s.n-1 do s.py[i]=s.y[i]-.5*s.h*math.sin((i-1)*math.pi/s.segments) end
                for i=1,240 do assert(s:frame(s.h,0,0,1.5,1.2,0,1.5)) end
                assert(s.resets==1,'impulse test must not reset away energy')
            end
            assert(energy(high)<energy(low)*.1)
        """)

    def test_frame_rates_keep_exact_render_pins_and_bounded_length(self):
        self.lua.execute("""
            poses={}; worst=0
            for _,rate in ipairs({30,60,144}) do
                local s=new()
                for frame=1,rate*3 do
                    local t=frame/rate
                    local ax,ay,az=.25*math.sin(t),.1*math.cos(t)-.1,1.5
                    local bx,by,bz=1.2+ax,ay+.1*math.sin(3*t),1.5+.1*math.sin(t)
                    assert(s:frame(1/rate,ax,ay,az,bx,by,bz))
                    pinned(s,ax,ay,az,bx,by,bz)
                    worst=math.max(worst,s:length_error(s.rx,s.ry,s.rz))
                end
                assert(s.steps==360 and s.resets==1 and s.render_resets==0)
                poses[#poses+1]=s
            end
            parity_error=0
            for p=2,#poses do
                for i=1,poses[p].n do
                    local a,b=poses[1],poses[p]
                    parity_error=math.max(parity_error,math.sqrt((a.rx[i]-b.rx[i])^2+(a.ry[i]-b.ry[i])^2+(a.rz[i]-b.rz[i])^2))
                end
            end
            assert(parity_error<.005 and worst<.02)
        """)
        print(f"Lua moving-frame parity={self.lua.globals().parity_error:.9f} m; max length error={self.lua.globals().worst:.9%}")

    def test_static_frame_partition_is_identical(self):
        self.lua.execute("""
            local baseline
            for _,rate in ipairs({30,60,144}) do
                local s=new()
                for i=1,rate do s:frame(1/rate,0,0,1.5,1.2,0,1.5) end
                assert(s.steps==120)
                if baseline then
                    for j=1,s.n do assert(s.x[j]==baseline.x[j] and s.y[j]==baseline.y[j] and s.z[j]==baseline.z[j]) end
                end
                baseline=s
            end
        """)

    def test_teleport_long_frame_and_pause_cannot_accumulate_unbounded_work(self):
        self.lua.execute("""
            local s=new(); local steps=s.steps
            local ok,reason=s:frame(1/60,100,100,3,101.2,100,3)
            assert(ok and reason=='teleport' and s.steps==steps)
            pinned(s,100,100,3,101.2,100,3)
            for i=1,s.n do assert(s.x[i]==s.px[i] and s.y[i]==s.py[i] and s.z[i]==s.pz[i]) end
            ok,reason=s:frame(5,100,100,3,101.2,100,3)
            assert(ok and reason=='long_frame' and s.steps==steps and s.accumulator==0)
            ok,reason=s:frame(0,100,100,3,101.2,100,3)
            assert(ok and reason=='paused' and s.steps==steps)
            s:frame(8*s.h,100,100,3,101.2,100,3)
            assert(s.steps-steps<=8)
        """)

    def test_impossible_span_is_hidden_not_stretched_and_can_recover(self):
        self.lua.execute("""
            local s=new(); local rest=s.rest
            local ok,reason=s:frame(s.h,0,0,0,2.266,0,0)
            assert(not ok and not s.visible and reason=='span_exceeds_length')
            assert(s.rest==rest and s.steps==0)
            assert(s:frame(s.h,0,0,0,1.2,0,0))
            pinned(s,0,0,0,1.2,0,0)
        """)

    def test_nonfinite_input_and_internal_corruption_do_not_escape(self):
        self.lua.execute("""
            for _,v in ipairs({0/0,math.huge,-math.huge,'bad'}) do
                local s=new(); local ok,reason=s:frame(s.h,v,0,0,1.2,0,0)
                assert(not ok and reason=='invalid_endpoint')
            end
            local s=new(); assert(not s:frame(0/0,0,0,1.5,1.2,0,1.5))
            s=new(); s.x[6]=0/0
            local ok,reason=s:frame(s.h,0,0,1.5,1.2,0,1.5)
            assert(ok and reason=='solver_error' and s.accumulator==0)
            assert(s:length_error(s.x,s.y,s.z)<1e-9)
        """)

    def test_working_tables_are_reused_and_instances_are_independent(self):
        self.lua.execute("""
            local s,t=new(),new()
            local x,y,z,rx,ry,rz,lambdas=s.x,s.y,s.z,s.rx,s.ry,s.rz,s.lambdas
            for i=1,600 do assert(s:frame(s.h,0,0,1.5,1.2,0,1.5)) end
            assert(s.x==x and s.y==y and s.z==z and s.rx==rx and s.ry==ry and s.rz==rz and s.lambdas==lambdas)
            assert(#x==13 and #lambdas==12 and t.steps==0 and t.resets==1)
        """)

    def test_solver_contains_no_engine_or_network_or_file_api(self):
        source=MODULE.read_text(encoding="utf-8")
        for api in ("Unit.","World.","Actor.","PhysicsWorld.","Managers.","io.","os.","require(","get_mod(","send_rpc"):
            self.assertNotIn(api,source)

    def test_authored_29_point_nonuniform_rest_lengths_are_exact(self):
        self.lua.execute("""
            assert(#authored==28)
            local s=Solver.new(authored)
            assert(math.abs(s.length-2.3238061919335924)<1e-12)
            for _,b in ipairs({{1.2,0,0},{0,0,1.2},{0,0,0}}) do
                assert(s:reset(0,0,0,unpack(b)))
                pinned(s,0,0,0,unpack(b))
                assert(s:length_error(s.x,s.y,s.z)<1e-9)
                for i=1,28 do assert(s.rest_lengths[i]==authored[i]) end
            end
        """)

    def test_authored_29_point_chain_moving_30_60_144_fps_without_resets(self):
        self.lua.execute("""
            local poses={}; authored_worst=0
            for _,rate in ipairs({30,60,144}) do
                local s=Solver.new(authored)
                assert(s:reset(0,0,1.5,1.2,0,1.5))
                for frame=1,rate*10 do
                    local t=frame/rate
                    local ax,ay,az=.4*math.sin(t),.2*math.cos(t)-.2,1.5
                    local bx,by,bz=1.2+ax,ay+.15*math.sin(3*t),1.5+.2*math.sin(t)
                    assert(s:frame(1/rate,ax,ay,az,bx,by,bz))
                    pinned(s,ax,ay,az,bx,by,bz)
                    authored_worst=math.max(authored_worst,s:length_error(s.rx,s.ry,s.rz))
                end
                assert(s.steps==1200 and s.resets==1 and s.render_resets==0)
                poses[#poses+1]=s
            end
            authored_parity=0
            for p=2,#poses do
                for i=1,poses[p].n do
                    local a,b=poses[1],poses[p]
                    authored_parity=math.max(authored_parity,math.sqrt((a.rx[i]-b.rx[i])^2+(a.ry[i]-b.ry[i])^2+(a.rz[i]-b.rz[i])^2))
                end
            end
            assert(authored_parity<.005 and authored_worst<.02)
        """)
        print(f"Authored29 parity={self.lua.globals().authored_parity:.9f} m; max link error={self.lua.globals().authored_worst:.9%}")

    def test_authored_29_point_near_taut_and_large_interior_impulse_fail_bounded(self):
        self.lua.execute("""
            local s=Solver.new(authored)
            assert(s:reset(0,0,1.5,s.length*.9999,0,1.5))
            for i=1,120 do
                assert(s:frame(s.h,0,0,1.5,s.length*.9999,0,1.5))
                pinned(s,0,0,1.5,s.length*.9999,0,1.5)
                assert(s:length_error(s.rx,s.ry,s.rz)<=s.max_error)
            end
            assert(s.resets==1 and s.render_resets==0,'near-taut success cannot be manufactured by resetting')
            s.px[14]=s.x[14]-100
            local ok,reason=s:frame(s.h,0,0,1.5,s.length*.9999,0,1.5)
            assert(ok and reason=='solver_error')
            assert(s.accumulator==0 and s:length_error(s.x,s.y,s.z)<1e-9)
        """)

    def test_frame_numeric_storage_has_no_unbounded_heap_growth(self):
        self.lua.execute("""
            local s=Solver.new(authored)
            assert(s:reset(0,0,1.5,1.2,0,1.5))
            collectgarbage('collect'); collectgarbage('stop')
            -- Collection may shrink the interpreter stack. Warm it only AFTER
            -- collection, then measure continuing growth with GC still stopped.
            for i=1,20 do s:frame(s.h,0,0,1.5,1.2,0,1.5) end
            local before=collectgarbage('count')
            for i=1,2000 do s:frame(s.h,0,0,1.5,1.2,0,1.5) end
            heap_growth_kb=collectgarbage('count')-before
            collectgarbage('restart')
            assert(heap_growth_kb<1,'frame path unexpectedly allocates: '..tostring(heap_growth_kb))
        """)
        print(f"Heap growth with GC stopped across2,000frames={self.lua.globals().heap_growth_kb:.6f} KiB")


    def test_exact_taut_boundary_is_finite_without_repeated_resets(self):
        self.lua.execute("""
            local s=Solver.new(authored)
            assert(s:reset(0,0,0,s.length,0,0))
            for i=1,120 do
                assert(s:frame(s.h,0,0,0,s.length,0,0))
                pinned(s,0,0,0,s.length,0,0)
                assert(s:length_error(s.rx,s.ry,s.rz)<=s.max_error)
            end
            assert(s.resets==1 and s.render_resets==0,'taut test cannot hide/reset its way to success')
        """)

    def test_paused_endpoint_change_is_explicit_zero_velocity_reset(self):
        self.lua.execute("""
            local s=new(); local steps=s.steps
            local ok,reason=s:frame(0,.1,0,1.5,1.3,0,1.5)
            assert(ok and reason=='paused_endpoint_change' and s.steps==steps)
            pinned(s,.1,0,1.5,1.3,0,1.5)
            for i=1,s.n do assert(s.x[i]==s.px[i] and s.y[i]==s.py[i] and s.z[i]==s.pz[i]) end
        """)

    def test_tiny_rest_lengths_are_rejected_not_reset_forever(self):
        self.lua.execute("""
            assert(not pcall(function() Solver.new(1e-9,28) end))
            assert(not pcall(function() Solver.new({1e-9,.1,.1,.1}) end))
        """)

    def test_generated_output_cannot_escape_ignored_build_directory(self):
        for path in (ROOT / "tools/unwanted.json", ROOT / ".build", ROOT / ".build/../unwanted.json"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    generated_output(path)

    def test_near_straight_five_second_matrix_cannot_mask_failure_with_resets(self):
        self.lua.execute("""
            straight_worst=0
            for _,ratio in ipairs({.99,.9999,1}) do
                for _,rate in ipairs({30,60,144}) do
                    for _,vertical in ipairs({false,true}) do
                        local s=Solver.new(authored)
                        local bx=vertical and 0 or s.length*ratio
                        local bz=vertical and s.length*ratio or 0
                        assert(s:reset(0,0,0,bx,0,bz))
                        for frame=1,rate*5 do
                            assert(s:frame(1/rate,0,0,0,bx,0,bz))
                            pinned(s,0,0,0,bx,0,bz)
                            straight_worst=math.max(straight_worst,s:length_error(s.rx,s.ry,s.rz))
                        end
                        assert(s.resets==1 and s.render_resets==0,
                            'near-straight numerical failure cannot be concealed by reset/hide')
                    end
                end
            end
            assert(straight_worst<.02)
        """)
        print(f"Near-straight matrix maximum relative link error={self.lua.globals().straight_worst:.6%}; zero resets")

    def test_rotating_exact_taut_endpoints_do_not_hide_on_roundoff(self):
        self.lua.execute("""
            rotating_taut_worst=0
            for _,offset in ipairs({0,100000}) do
                local s=Solver.new(authored)
                assert(s:reset(offset,offset,offset,offset+s.length,offset,offset))
                for frame=1,600 do
                    local angle=.15*math.sin(frame/60)
                    local bx=offset+s.length*math.cos(angle)
                    local by=offset+s.length*math.sin(angle)
                    local ok,reason=s:frame(1/60,offset,offset,offset,bx,by,offset)
                    assert(ok and reason=='simulated','roundoff must not hide/reinitialize an exactly taut hose')
                    pinned(s,offset,offset,offset,bx,by,offset)
                    rotating_taut_worst=math.max(rotating_taut_worst,s:length_error(s.rx,s.ry,s.rz))
                end
                assert(s.resets==1 and s.render_resets==0 and s.steps==1200)
                for i=1,28 do assert(s.rest_lengths[i]==authored[i]) end
            end
            assert(rotating_taut_worst<.02)
        """)
        print(f"Rotating exact-taut maximum relative link error={self.lua.globals().rotating_taut_worst:.6%}; zero hides/resets")

    def test_span_roundoff_tolerance_does_not_accept_real_overstretch(self):
        self.lua.execute("""
            for _,offset in ipairs({0,100000,999990}) do
                for _,excess in ipairs({1e-7,1e-5,.001}) do
                    local s=Solver.new(authored)
                    local total=s.length
                    local ok,reason=s:reset(offset,offset,offset,offset+total+excess,offset,offset)
                    assert(not ok and reason=='span_exceeds_length')
                    assert(s:reset(offset,offset,offset,offset+total*.9,offset,offset))
                    ok,reason=s:frame(s.h,offset,offset,offset,offset+total+excess,offset,offset)
                    assert(not ok and reason=='span_exceeds_length' and s.length==total)
                    for i=1,28 do assert(s.rest_lengths[i]==authored[i]) end
                end
            end
        """)


if __name__=="__main__":
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument("--contract",type=Path,default=DEFAULT_CONTRACT)
    options,remaining=parser.parse_known_args()
    CONTRACT=options.contract.resolve()
    unittest.main(argv=[sys.argv[0]]+remaining,verbosity=2)
