"""Export an offline physics demo from the actual Lua solver and measured rig."""
from pathlib import Path
import copy
import hashlib
import json
import math
import argparse
from lupa.lua51 import LuaRuntime
from lab_paths import DEFAULT_CONTRACT, DEFAULT_TRAJECTORY, generated_output

HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--contract",type=Path,default=DEFAULT_CONTRACT)
parser.add_argument("--output",type=Path,default=DEFAULT_TRAJECTORY)
options=parser.parse_args()
contract_path=options.contract.resolve()
output_path=generated_output(options.output)
contract=json.loads(contract_path.read_text(encoding="utf-8"))
lua=LuaRuntime(unpack_returned_tuples=True)
solver_type=lua.execute((HERE/"hose_xpbd.lua").read_text(encoding="utf-8"))
solver=solver_type.new(lua.table_from(contract["control_rest_lengths_m"]))

def multiply(a,b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def xyz(m): return [m[i][3] for i in range(3)]

pack=contract["controls"][0]["frame"]
base=multiply(contract["preview_weapon_world"],contract["endpoints"]["weapon"]["target_canonical_frame_m"])
a,b=xyz(pack),xyz(base)
assert solver.reset(solver,*a,*b)[0]
for _ in range(240): assert solver.frame(solver,1/120,*a,*b)[0]
initial_resets=solver.resets
frames=[]
worst=0
for frame in range(60):
    t=frame/30
    weapon=copy.deepcopy(base)
    phase=math.sin(math.pi*t) if t<1 else 0
    for i,amplitude in enumerate((.2,.12,.15)): weapon[i][3]+=amplitude*phase
    a,b=xyz(pack),xyz(weapon)
    ok,reason=solver.frame(solver,1/30,*a,*b)
    assert ok and reason=="simulated",reason
    points=[[solver.rx[i],solver.ry[i],solver.rz[i]] for i in range(1,30)]
    assert points[0]==a and points[-1]==b
    worst=max(worst,solver.length_error(solver,solver.rx,solver.ry,solver.rz))
    frames.append({"t":t,"points":points,"endpoints":[a,b],"endpoint_frames":[pack,weapon]})
assert solver.resets==initial_resets and solver.render_resets==0
hold_displacement=max(math.dist(frames[30]["points"][i],f["points"][i]) for f in frames[31:] for i in range(1,28))
assert hold_displacement>.005,"The hold phase must visibly retain inertia, not endpoint interpolation."
report={
    "schema":1,"prototype_only":True,"engine_acceptance":False,
    "source_contract_sha256":hashlib.sha256(contract_path.read_bytes()).hexdigest(),
    "solver_sha256":hashlib.sha256((HERE/"hose_xpbd.lua").read_bytes()).hexdigest(),
    "description":"Offline two-ended physical hose. Pack fixed; weapon moves for1s then remains fixed for1s; interior keeps moving. No game launch or engine integration.",
    "fps":30,"solver_hz":120,"warmup_seconds":2,"frame_count":len(frames),
    "control_count":29,"authored_rest_lengths_m":contract["control_rest_lengths_m"],
    "authored_total_length_m":sum(contract["control_rest_lengths_m"]),
    "checks":{"safety_resets_during_capture":solver.resets-initial_resets,
              "render_resets":solver.render_resets,"max_relative_link_length_error":worst,
              "max_interior_displacement_during_fixed_endpoint_hold_m":hold_displacement,
              "both_endpoints_exact":True},
    "frames":frames,
}
output_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
print(json.dumps(report["checks"],indent=2))
print(output_path)
