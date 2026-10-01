# Offline hose rig lab

This creates a **separate, actor-free skinned hose prototype**, not a shipping
weapon replacement or an automatically loaded mod feature. Original artist art,
body skeleton, weapon geometry, physics and Workshop files are untouched.
Only scripts and a compact measured contract belong in Git; generated Blender,
FBX, images, decoded geometry and per-vertex diagnostics stay in `.build`.

## Rig and attachment decisions

The reviewed 1,608-vertex hose tail contains seven flexible sections (each 15
rings of 12 vertices), four 26-vertex collars and two 122-vertex collars. It is
not 13 equivalent chain links. Six coincident section joins define one ordered
99-ring centreline, measured length **2.32813285 m**. The earlier approximately
2.265 m dimension was not the centreline rest length.

Each tube uses controls at rings 0, 4, 7, 10 and 14. Shared joins give **29
controls**, 28 unequal intervals totaling **2.32380619 m**. The intervals range
from 0.0642063 to 0.1043191 m. `j_hose_00` through `j_hose_28` are flat sibling
bones under the non-deforming `hose_root`, independent of the character rig.
Their ordered positions/lengths define the custom solver chain, not a native
constraint hierarchy. Bone +Y is tangent, +X is radial; matrices use column
vectors. A future native-chain experiment would need a separate hierarchy.

Flexible ring weights interpolate between surrounding controls by measured
centreline arc length. Each collar follows its shared join rigidly. Duplicate
ring seams receive identical weights. The original vertex positions, polygons,
UVs and `DoomRocket_Weapon` material are preserved in the bind shape.

The backpack endpoint matches cap vertex **5426**, rigidly weighted to
`j_backpack`, within 0.23 micrometres. The shipping body contains the same cap
at index 18272. Its target frame uses the compiled body's inverse skin bind,
not an inverse of a currently posed bone.

The weapon end does **not** meet the detached presentation launcher in Crunch's
scene. The prototype inlet is the lower cylindrical grip-base cap: the 12
vertices surrounding cap centre vertex 1809. This is **inferred from visible
fit and orientation, not artist-confirmed**. The hose radius is 34.302 mm;
the cap skirt radius averages approximately 37.603 mm, and the opposing axes
agree within 1.623 degrees. The endpoint is inserted **1 mm** inside the skirt
plane. No cap or weapon geometry is removed. The separate 198-vertex short
conduit has a much smaller diameter and is not used as this hose's mate.

The inlet is translated by the accepted launcher grip calibration, then mapped
into the compiled `pRocketLauncher` node frame. Both attachment profiles include
scale-100 compensation. These target profiles must not be mistaken for the
new hose's own compiled skin binds: inspect the new compiled unit separately.
Do not copy the chimney's inverse-bind scale into this different FBX rig.

The isolated [compiled-asset probe](../compiled/README.md) subsequently verified
the candidate as actor-free, with 29 weighted controls, an empty root skin
cluster and 1,893 seam-split render vertices. All positive compiled weights
match the FBX within 0.000242; the maximum quantized world-position difference
is 0.442 mm. Its mesh bind-world matrix is scale 100, while its inverse-bind
axes are approximately unit scale. Use the compiled probe's full skinning
equation, not a guessed scale on each bone. Compilation is not game acceptance.

## Reproduce

The committed metadata also has a standard-library-only CI check, requiring
neither downloaded artist assets nor `.build`:

```powershell
py -3 tools/hose_lab/rig/test_contract.py
```

It validates the measured frames, unequal lengths, source identity, attachment
ownership and scale compensation, and rejects eight representative mutations.

Requirements: Blender 5.2; Python 3 with NumPy, Pillow and Lupa (the existing
source test helpers load these); the SHA-pinned artist scene, isolated original
launcher FBX, shipping body/weapon FBXs, and an existing compiled development
bundle. `read_weapon_contract.py` only reads that bundle. This lab does not run
the SDK compiler.

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\hose_lab\rig\Invoke-RigProbe.ps1 -ArtistScene 'D:\Game Mods\Vermintide 2 modding\Projects\3D\xud4soo5fg7g8qd4.blend'
```

The wrapper checks the artist SHA, disables embedded script execution, stops
on every failed command, and defaults to `.build/hose_rig_probe`. Pass
`-OutputPath` for another directory inside `.build`. The builder saves only
new compressed output scenes, never the artist input. It does not run Rigify.

Both the wrapper and every script's path resolver apply the shared probe-tree
guard before creating output directories or writing files. The `.build` root
itself is not a valid output target. Existing nested reparse points, junctions,
symlinks and hard-linked files are rejected, including individual output files.
Relative output paths are repository-relative. The SDK-free guard regressions
are `py -3 tools/hose_lab/test_compile_paths.py`.
The resolver also refuses Python `-O` / `PYTHONOPTIMIZE`, because the Blender
lab's validation assertions must remain enabled.

Outputs include `warlock_hose_rig.blend`, `warlock_hose.fbx`, an illustrative
`warlock_hose_pose_preview.blend`, `rig_contract.json` (full local audit), and
`runtime_contract.json` (compact measurements). FBX timestamps can change
between exports; verification checks geometry, weights and transforms, not
cross-run whole-file byte equality. The tracked compact contract records the
reviewed candidate, rather than silently updating after every local run.

`verify_hose_fbx.py` checks ten source/FBX contracts. The Blender round-trip
check imports the FBX into a fresh scene and compares all 1,608 deformed
vertices in three different poses with the explicit skinning equation.
The static preview uses a labelled illustrative weapon placement, not a game
animation or the rejected inverse-hand placement transform.

## Actual solver-to-rig demonstration

After the adjacent solver lab exports `.build/hose_solver_probe/trajectory.json`:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --disable-autoexec --python-exit-code 1 --python tools\hose_lab\rig\render_solver_demo.py
py -3 tools/hose_lab/rig/encode_demo.py
```

This reads the actual Lua solver trajectory, drives the real rig and skin,
tests endpoints/seams/collars on all 60 frames, and creates
`.build/hose_rig_probe/offline_hose_physics_demo.gif`. The first second moves
the weapon; the second holds it still while the hose retains inertia.

The reviewed run stayed below 0.50 micrometres for evaluated skin error,
0.38 micrometres for endpoint error, 0.30 micrometres for seams, and
0.17 micrometres for rigid-collar distance error. This is an **offline Blender
and Lua demonstration**: native game integration, collisions, wield/stow,
death/drop, multiplayer and lifecycle acceptance remain separate work.
