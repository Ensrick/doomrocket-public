# Offline two-ended hose solver

This is an **offline laboratory**, not a runtime mod extension. Nothing here is
loaded by `doomrocket.lua`. The solver calls no engine, physics, networking, or
file APIs. It changes neither the character nor the carried/dropped weapon.
No successful test or generated animation establishes in-game acceptance.

## Run

Python needs `lupa` with its Lua 5.1 runtime. Run from the repository root:

```powershell
py -3 -m unittest discover -s tools/hose_lab/solver -p 'test_*.py' -v
py -3 tools/hose_lab/solver/benchmark_hose_xpbd.py
py -3 tools/hose_lab/solver/export_trajectory.py --output .build/hose_lab/solver_trajectory.json
```

The committed default input is
[`../rig/runtime_contract.json`](../rig/runtime_contract.json).
Each directly executable Python tool accepts `--contract PATH`; the test runner
also accepts normal unittest arguments. No Blender, SDK, extracted game payload,
game installation, or Workshop access is needed for these numerical tests.
Output paths are resolved and rejected unless they are files below this
checkout's ignored `.build` directory. Tests and the benchmark write no artifacts.

The contract has 29 controls and 28 **unequal** measured link lengths, totaling
2.3238061919335924 m. The older approximate 2.265 m extent is not their length.
The solver copies the measured array; it never replaces collar intervals with
uniform spacing. The previous slow sequential-projection experiment remains
ignored and is not the tracked implementation.

## Method and interface

`hose_xpbd.lua` returns a class-like table:

```lua
local hose = Solver.new(authored_rest_lengths)
local visible, reason = hose:reset(ax, ay, az, bx, by, bz)
visible, reason = hose:frame(dt, ax, ay, az, bx, by, bz)
-- When visible: hose.rx[i], hose.ry[i], hose.rz[i] are render positions in metres.
```

The physical state is `x/y/z` plus previous positions `px/py/pz`. Render positions
are separate; extrapolation and endpoint correction do not inject render-only
motion back into the physical state. Both render endpoints are pinned exactly
to the latest supplied endpoint coordinates.

Interior points retain velocity, respond to gravity, and lose energy through
exponential damping. This is secondary **inertial motion**, not a spline that
merely follows two endpoints. Distance constraints use the compliant formulation
from [Macklin et al., XPBD (2016)](https://mmacklin.com/xpbd.pdf). For a chain, the
coupled matrix `J W Jᵀ + alpha I` is tridiagonal. A guarded Thomas solve applies
each nonlinear correction in O(number of links), with a four-iteration cap and
residual-based early exit. Endpoint inverse weights are zero; interior weights
are one. This is a mathematical solver convention, **not** a recipe to set a
native engine chain's mass to zero.

Defaults and failure policy:

- Fixed step: 1/120 s; maximum eight substeps per supplied frame.
- Endpoint positions are linearly sampled at fixed-step times between animation
  samples. Rendering extrapolates over the fractional remainder.
- A frame longer than eight steps or an endpoint jump greater than half the
  authored total length explicitly resets position history and velocity; no
  unbounded catch-up loop occurs.
- Unchanged zero-dt input pauses. Changed endpoints at zero dt cause an explicit
  `paused_endpoint_change` reset, preserving exact pins without simulating time.
- Reset constructs a constant-curvature polyline with the actual individual
  chord lengths. This is only initialization, not the moving simulation.
- Impossible endpoint span greater than total authored length is **hidden**,
  never accommodated by lengthening the rest-length array. Invalid inputs also
  hide; valid later input can initialize again. Hiding is a failure presentation
  policy, not a successful physics result. The comparison allows only
  `8 * 2^-52 * max(1, total_length, absolute_endpoint_coordinates)` metres of
  double-precision roundoff. Without this tolerance, rotating an exactly taut
  hose produced false hides from sub-femtometre excess at the origin. This is
  not the 2% constraint error budget and does not change authored rest lengths.
- Finite compliance permits small individual link errors. The safety limit is
  2% absolute relative error, not a claim of perfectly inextensible geometry.
  Degenerate directions, invalid pivots, nonfinite state, excessive corrections,
  or excess length error explicitly reset valid configurations.
- Physical and render projections use the same finite compliance. An earlier
  zero-compliance render projection caused repeated near-taut resets; explicit
  regressions now forbid masking those failures with reset/hide.
- Numeric arrays are preallocated. The supported lab topology is 4–64 segments,
  each longer than one micrometre; current art uses 28. A severely uneven rest
  distribution outside the circular initializer's supported range is rejected
  as `unsupported_rest_distribution`, not presented as a solved pose.

## Evidence and limitations

The September 10, 2026 run passed **21 tests**, including:

- Actual nonuniform 29-control lengths, endpoint equality, inertia after endpoint
  motion stops, gravity sag, damping, instance isolation and bounded storage.
- Ten-second moving runs at 30/60/144 FPS: 0.150295 mm maximum final-pose
  difference, 0.0268273% maximum relative link error, **zero safety resets**.
- Eighteen five-second near-straight cases: spans 99%, 99.99%, and 100% of rest
  length; 30/60/144 FPS; horizontal and vertical. Maximum link error 0.409340%,
  **zero resets or hides**. The original failing cases remain regression tests.
- Exactly taut rotating endpoints over 600 frames at both the origin and
  100,000 m translation: maximum relative link error 0.399353%, exact render
  pins, **zero hides/resets**, and unchanged rest lengths. Actual overspan of
  0.1 micrometres, 10 micrometres, and 1 mm remains rejected at the origin,
  100,000 m, and near the supported 1,000,000 m coordinate bound.
- Teleport/long-frame behavior, paused endpoint change, impossible-span hiding,
  nonfinite data, deliberate internal corruption, and tiny-link rejection.
- After warming the Lua VM stack with collection stopped: 0 KiB continuing heap
  growth over 2,000 additional frames. This is not a native memory-leak test.

The trajectory exporter uses actual Lua 5.1 and the committed endpoint frames.
It settles for two seconds, then captures 60 frames at 30 FPS: the weapon moves
for one second and holds for one second. The latest export had exact endpoints,
zero resets, 0.0264833% maximum link error, and 0.268315 m of subsequent interior
motion during the fixed-endpoint hold. JSON contains source/solver hashes and
explicit `prototype_only` / `engine_acceptance` fields.

### CPU cost is material

Local plain Lua 5.1 measurements for **20 active hoses × 29 controls** follow.
Each row contains 240 measured frames after 30 warm-up frames. Timings include
the numerical frame call, **not engine pose writes, skinning, materials,
collisions, rendering, or production callback overhead**. They vary with host
load and hardware; they are not a shipping frame-time guarantee.

| Recorded run / per-frame simulated work | Mean | p95 | p99 | Maximum | Safety resets |
| --- | ---: | ---: | ---: | ---: | ---: |
| Boundary-audit run: normal two substeps, 60 FPS input | 2.621 ms | 3.469 ms | 3.789 ms | 3.950 ms | 0 |
| Boundary-audit run: maximum eight substeps | 9.115 ms | 11.931 ms | 12.440 ms | 12.950 ms | 0 |
| Roundoff-fix retest: normal two substeps, 60 FPS input | 1.703 ms | 2.262 ms | 2.734 ms | 2.910 ms | 0 |
| Roundoff-fix retest: maximum eight substeps | 5.891 ms | 7.065 ms | 10.016 ms | 10.274 ms | 0 |

Both runs use the same coupled projection workload; the roundoff comparison
change is not a claimed performance optimization. Retaining both measurements
shows local timing variability rather than selecting only the fastest run.
The eight-step case is a substantial cost spike. In-game profiling, a bounded
cosmetic population/LOD policy, and total bone/render cost must be reviewed
before integration. Reducing iteration count is not accepted on speed alone;
it must retain zero-reset normal-motion and length/error tests.

## Native integration is separate work

Native Lua provides a relevant **bone-writing** precedent, not proof that this
lab is integrated. The game's
[TentacleSplineExtension](https://github.com/Aussiemon/Vermintide-2-Source-Code/blob/c5e4968b1fbb00c49884e56d640ef990a9c04dd0/scripts/unit_extensions/generic/tentacle_spline_extension.lua#L1049)
forms a desired world pose, multiplies by the inverse parent pose, then calls
`Unit.set_local_pose`. Its spline movement is kinematic; the inertial portion
here comes from this lab solver. Native
[ScriptWorld update ordering](https://github.com/Aussiemon/Vermintide-2-Source-Code/blob/c5e4968b1fbb00c49884e56d640ef990a9c04dd0/foundation/scripts/util/script_world.lua#L316)
separates animation, safe animation callbacks and scene update. Native
[inventory teardown](https://github.com/Aussiemon/Vermintide-2-Source-Code/blob/c5e4968b1fbb00c49884e56d640ef990a9c04dd0/scripts/entity_system/systems/ai/ai_inventory_extension.lua#L204)
and [world release](https://github.com/Aussiemon/Vermintide-2-Source-Code/blob/c5e4968b1fbb00c49884e56d640ef990a9c04dd0/foundation/scripts/managers/world/world_manager.lua#L64)
are lifecycle boundaries a future adapter must respect.

A future adapter must use a separate zero-actor visual unit, read both live
endpoint frames, and write only that unit's verified deform nodes. It must
preserve actual compiled inverse binds and the exported scale conventions;
normalizing a scale-100 bone basis or applying its scale twice is not valid.
The rig's flat sibling hierarchy is independent of this solver's chain topology.
Persistent native vectors/matrices require proper boxed storage.

This directory does **not** implement collision/self-collision, torsional or
endpoint-orientation constraints, stable bone-frame/twist transport, engine
spawn/deletion hooks, death/drop behavior, networking, or host/client acceptance.
It must not be connected to character actors, body bones, or dropped-weapon
physics as an implicit next step. An offline render is a demonstration, not
proof of any of those unimplemented contracts.
