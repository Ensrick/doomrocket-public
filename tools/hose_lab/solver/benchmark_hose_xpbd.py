"""Numerical Lua 5.1 CPU probe, excludes engine bone writes/render cost."""
from pathlib import Path
import time
import json
import statistics
import argparse
from lupa.lua51 import LuaRuntime
from lab_paths import DEFAULT_CONTRACT

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--contract",type=Path,default=DEFAULT_CONTRACT)
options=parser.parse_args()

lua=LuaRuntime(unpack_returned_tuples=True)
lua.globals().Solver=lua.execute(Path(__file__).with_name("hose_xpbd.lua").read_text(encoding="utf-8"))
contract=json.loads(options.contract.read_text(encoding="utf-8"))
lua.globals().authored=lua.table_from(contract["control_rest_lengths_m"])
run=lua.eval("""function(count,frames,iterations)
    local hoses={}
    local worst=0
    for i=1,count do
        local s=Solver.new(authored)
        s.iterations=iterations
        local a=.25*math.sin(i*.02)
        local b=.1*math.cos(i*.02)-.1
        s:reset(a,b,1.5,1.2+a,b,1.5)
        hoses[i]=s
    end
    for f=1,frames do
        local t=f/60
        for i=1,count do
            local a=.25*math.sin(t+i*.02)
            local b=.1*math.cos(t+i*.02)-.1
            local s=hoses[i]
            assert(s:frame(1/60,a,b,1.5,1.2+a,b+.1*math.sin(3*t),1.5+.1*math.sin(t)))
            worst=math.max(worst,s:length_error(s.rx,s.ry,s.rz))
        end
    end
    local resets,steps=0,0
    for _,s in ipairs(hoses) do resets=resets+s.resets-1;steps=steps+s.steps end
    return worst,resets,steps
end""")
run(1,30,24)
for iterations in (4,3,2,1):
    t=time.perf_counter()
    worst,resets,steps=run(20,180,iterations)
    elapsed=time.perf_counter()-t
    print(f"20 hoses x29points, 60Hz, 120Hzsolver, iterations={iterations}: "
          f"{elapsed/180*1000:.3f} ms/frame average, max link error={worst*100:.4f}%, "
          f"safety resets={resets}, steps={steps}, samples=180frames")

make_frame_runner=lua.eval("""function(count)
    local hoses={}
    for i=1,count do
        local s=Solver.new(authored)
        local a=.25*math.sin(i*.02)
        local b=.1*math.cos(i*.02)-.1
        s:reset(a,b,1.5,1.2+a,b,1.5)
        hoses[i]=s
    end
    return function(dt,t)
        local resets=0
        for i=1,count do
            local a=.25*math.sin(t+i*.02)
            local b=.1*math.cos(t+i*.02)-.1
            local s=hoses[i]
            assert(s:frame(dt,a,b,1.5,1.2+a,b+.1*math.sin(3*t),1.5+.1*math.sin(t)))
            resets=resets+s.resets-1
        end
        return resets
    end
end""")
for dt,label in ((1/60,"normal2substeps"),(8/120,"maximum8substeps")):
    advance=make_frame_runner(20)
    t=0
    for _ in range(30):
        t+=dt
        advance(dt,t)
    samples=[]
    for _ in range(240):
        t+=dt
        begin=time.perf_counter()
        resets=advance(dt,t)
        samples.append((time.perf_counter()-begin)*1000)
    samples.sort()
    print(f"20 actual29point hoses, {label}: mean={statistics.mean(samples):.3f}ms, "
          f"p95={samples[int(len(samples)*.95)]:.3f}ms, p99={samples[int(len(samples)*.99)]:.3f}ms, "
          f"max={max(samples):.3f}ms, safety resets={resets}, 240 measuredframes after30warmup")
