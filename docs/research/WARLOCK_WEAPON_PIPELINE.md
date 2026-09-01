# Warlock launcher integration, placement, and physics pipeline

This is the authoritative procedure for replacing the Doomrocket launcher and
rocket art without breaking Vermintide 2's established attachment, muzzle,
projectile, or death-drop contracts. Texture conversion is documented
separately in `docs/research/WARLOCK_TEXTURE_PIPELINE.md`; character animation
and the native-carrier corpse handoff are documented in
`docs/WARLOCK_MODEL_PIPELINE.md` and
`docs/testing/WARLOCK_RAGDOLL_TEST_PROTOCOL.md`.

## Current status

The result must be evaluated as three independent lanes:

| Lane | Observed result | Remaining limitation |
|---|---|---|
| Warlock body/corpse | Passed the latest three-corpse host analyzer run | This is host `source=unit` evidence only; remote-client `source=husk`, post-monitor wake, and long-lived corpse behavior still need their own captures |
| Loaded launcher death drop | Visually reported working after making `pRocket` a child of actor-owned `pRocketLauncher` | Do not regress the hierarchy or add a second dynamic actor |
| Launcher hand/back placement | v0.1.54 failed visually: Crunch's launcher was displaced from the enemy while both wielded and unwielded | The v0.1.55 presentation-space bake, semantic-grip calibration, and rigid-MVP tether exclusion are implemented; source and fresh compiled-bundle gates pass, while a uniquely versioned in-game visual test remains required |

The accepted v0.1.54 host log is
`C:\Users\danjo\Downloads\console-2026-08-13-01.15.59-7009c335-e195-4768-8c49-a99e37659f53.log`.
It contains `[doomrocket:LOAD] v0.1.54-dev`, three complete five-second corpse
traces, and three material summaries of `slots=5/5 custom_textures=6/6
resident`. The exact analyzer command reports:

```text
[ragdoll-log] OK - 3 corpse trace(s), >=5.001 s, hips drift <= 0.25 m
```

Every trace stopped with `callbacks=602 pose_writes=602 sleep_skips=0`; final
hips drift was 0.046, 0.040, and 0.007 m. Parent, named-root, scale, and
non-hips-translation mutation counts were all zero. This proves the monitored
host body handoff. It does not prove weapon placement because no console datum
measures where the rigid launcher appears relative to a hand or back mount.

The tested Workshop artifact was friends-only item `3771657344`, v0.1.54
ManifestID `3649786646933166566`.

The v0.1.55 candidate was clean-built, spliced, tested, deployed, and uploaded
to the same friends-only item as ManifestID `6225347386542634141`. Its 39
weapon/source/compiled regressions, 17 texture regressions, and complete
ragdoll/pipeline suite pass. This proves the artifact matches the reviewed
source contracts; hand/back placement still needs in-game visual acceptance.

## Authoritative inputs and provenance

Never rebuild from a visually similar download or a shipping FBX used as its
own donor. The exporter hash-pins the following inputs:

| Input | Path or Git object | SHA-256 |
|---|---|---|
| Crunch Blender scene | `C:\Users\danjo\Downloads\xud4soo5fg7g8qd4.blend` | `AB6EBC9EF45CEA6E402BBD0415C2D40716824552C2AB514947902D1EAC06C1B2` |
| Crunch texture archive | `C:\Users\danjo\Downloads\zxnu2hjyuovl4rhx.zip` | `551852EE9A9FA99995921E4B6B5CF898D4C17B51486E22FE7772D980F92C2187` |
| Isolated Crunch launcher export | `C:\Users\danjo\source\repos\_warlock_bombardier_art\warlock_rocketlauncher.fbx` | `1682ECD2979ED988C2254DBABFD20E1D2E5C7D4869AD39B3727872F914F9DF69` |
| Isolated Crunch rocket export | `C:\Users\danjo\source\repos\_warlock_bombardier_art\warlock_rocket.fbx` | `968539ECA60F065B90ED5899195F1EB2DFD6ED2B77ED87A8958CA976DCC0E0EA` |
| Isolated Crunch short-conduit export | `C:\Users\danjo\source\repos\_warlock_bombardier_art\warlock_tube.fbx` | `EEFA15569E53784077973801F3E02FC1145AF1E5014E3D275D4F74A14F2DCDC9` |
| Known-good Dalo launcher frame | Git blob `4afd3ff155889b44760ff41500bca7e1bf6ccafa` | `80CAF376BA9210B83DED30587F9D2A3663F6614D4B624513307D06DEC0E64D5F` |
| Known-good Dalo projectile frame | Git blob `445636e36fc62a8aef8883d2f59ed85eaa6707a0` | `AFF853DC8C420B7FD94F7273166025E1BAF49C9828274B05CCD5647AB43294C7` |

The Blender source names are deliberately pinned, including Crunch's typo:

- full presentation launcher: `SM_Skaven_WarlockBombardier_RcoketLauncher`,
  4,916 vertices, of which the reviewed rigid MVP retains the first 3,308;
- loaded/fired rocket source: `SM_Skaven_WarlockBombardier_Rocket`, 622
  vertices;
- distinct deferred short conduit: `SM_Skaven_WarlockBombardier_Tube`, 198
  vertices and material `DoomRocket_Pipe`;
- character armature retained for projectile normalization:
  `armature object.008`.

Shipping resource paths remain stable even though their render geometry is
replaced:

- `units/rocket/pRocketLauncher.fbx`, `.unit`, and `.physics`;
- `units/rocket/SM_Rocket.fbx`, `.unit`, and `.physics`;
- `materials/rocket/rocket_neutral.material` and `rocket_red.material`;
- `textures/rocket/wb_weapon_*` and `wb_rocket_*`.

The old Dalo FBXs are not the desired art. They are immutable donors for the
engine-facing node frames and are also known-good placement references. The
final FBXs must contain Crunch geometry and must not equal the old whole-file
hashes.

## Rigid MVP scope: the backpack tether is deliberately excluded

The complete 4,916-vertex presentation launcher is not one rigid weapon. Its
last 1,608 vertices are a segmented, roughly 2.265 m backpack tether made of
13 disconnected sections. One tether end matches the backpack outlet cap to
within `1.34e-7` m in Crunch's presentation scene. It has no bone chain,
weights, constraints, or physics rig. If those vertices are baked into
`pRocketLauncher`, the entire tether follows the hand/back weapon actor as a
rigid shape; it cannot keep its other end on the backpack and visibly floats
above the character.

The pinned source has an exact closed boundary at vertex 3,308: no polygon
crosses it. The Blender mesh contains 3,365 retained rigid-weapon polygons and
1,608 deferred tether polygons. The isolated triangulated FBX contains 6,094
retained and 3,024 deferred triangles. The exporter verifies those counts
before deleting the tail block, and the Python suite pins the topology and 13
deferred component sizes. A reordered or revised source fails closed instead
of deleting an arbitrary range.

`SM_Skaven_WarlockBombardier_Tube` is a separate 198-vertex short
weapon-local conduit, not a duplicate of the long backpack tether. It is also
unparented, unweighted, and modifier-free in the current source, so the rigid
MVP explicitly verifies and defers it rather than guessing a runtime rig.
Neither deferred object appears in the shipping FBX. Adding the flexible
weapon-to-pack connection later requires reviewed endpoint locators and a
real deformation/physics contract; it must not be re-appended to the one rigid
launcher actor.

## Runtime node and attachment contract

The carried launcher FBX keeps one legacy weapon rig and these exact names:

| Node | Required role | Reviewed local translation |
|---|---|---:|
| `root_point` | Weapon-unit root and legacy frame | `(0.00, 0.00, 0.00)` |
| `handle` | Left-hand secondary attachment | `(0.00, -0.42, 0.05)` |
| `p_fx` | Rocket spawn/muzzle lookup | `(0.00, 0.85, 0.06)` |
| `a_barrel` | Weapon-component secondary attachment | `(0.17, 0.40, 0.06)` |
| `pRocketLauncher` | Main visible mesh and only carried-weapon physics node | geometry is calibrated into the legacy weapon-root space |
| `pRocket` | Loaded visible warhead | direct rigid child of `pRocketLauncher` |

Names are engine string contracts. `root_point.001`, `pRocket.001`, or any
other Blender collision suffix is a hard failure even if Blender displays the
scene correctly.

`AttachmentNodeLinking.ai_doomrocket` in
`scripts/mods/doomrocket/breeds/skaven_doomrocket_inventory.lua` defines the
links. In a wielded state, weapon target `0` follows carrier
`j_leftweaponattach`, weapon `a_barrel` follows
`j_leftweaponcomponent1`, and weapon `handle` follows `j_lefthand`. In the
unwielded state, weapon target `0` follows carrier `a_spear`. The launch action
looks up `p_fx` on the weapon unit before creating `units/rocket/SM_Rocket`.

This means the engine already applies the hand/back attachment transform to the
weapon root. Geometry exported with an additional inverse character-hand
transform receives a transform that does not belong in the weapon unit. The
source object's presentation-space origin is not automatically a valid grip
locator either; orientation and semantic position are separate questions.

## Maya/Blender axes versus the effective mesh transform

Raw FBX Euler angles are not comparable across DCC conventions. The immutable
Dalo launcher declares Maya-style Y-up/+Z-front metadata and its top-level
`root_point` reports about -90 degrees around X. The Blender export declares
Z-up/-Y-front metadata and reports an almost-zero root rotation. After each
file's `GlobalSettings` axis conversion is applied, the normalized root axes
match. Manually adding the apparent -90-degree difference would double-apply a
coordinate conversion.

The placement value that matters is the complete effective transform:

```text
canonical_vertex = global_axis_conversion
                 * model_parent_chain
                 * geometry_vertex
```

The v0.1.54 Blender round-trip test reconstructed the exported candidate under
the same Blender character bone used to generate it. That operation applied
the inverse transform and then its opposite, so it could report sub-millimetre
agreement while the engine-facing weapon root was wrong. A self-inverting test
is not an attachment-space test.

### Presentation-space calibration (implemented; v0.1.55 runtime pending)

Crunch's final launcher and loaded rocket are unrigged, unparented presentation
props. They were not deliberately authored in the legacy weapon-root frame and
contain no grip locator. Their object-world rotation/axes nevertheless agree
with the pinned Dalo frame after FBX axis normalization. The correct
operation therefore preserves that object transform and adds a measured,
translation-only semantic grip calibration:

```text
v_weapon = Translation(delta_grip) * source_object_world * v_source
```

Do not apply this rejected v0.1.54 transform to the carried meshes:

```text
v_wrong = inverse(source_armature_world * j_leftweaponattach_rest)
        * source_object_world * v_source
```

That inverse injected the character bone's roughly one-metre rest translation
and its arbitrary rest rotation into an unrigged presentation prop. It explains
v0.1.54 being displaced in both attachment modes: the same bad
geometry-to-root transform was present when the engine linked the root to the
hand and when it linked it to `a_spear`.

Removing the inverse was necessary but did not identify the grip. A broad AABB
can contain node 0 while the hand is still inside empty space, and the closest
surface on the uncalibrated Crunch mesh is the rear stock. A generic
nearest-surface snap would therefore put the stock—not the handle—in the hand.

Forensics welds coincident positions for component identity and finds exactly
one disconnected 217-vertex pistol-grip component. Its upper 10 mm cap has this
centroid in the uncalibrated Blender/source world frame:

```text
g_src = (0.000021006, 0.910976648, -0.050454207) m
```

The SHA-pinned Dalo launcher supplies the reviewed canonical attachment
landmark:

```text
q_old = (0.000002565, 1.108044386, 0) cm  # canonical right, up, front
```

After converting that target into Blender/source axes and metres, the exporter
applies the following translation:

```text
delta_grip = (-0.00002098033, -0.91097664833, +0.06153465062) m
```

The exporter applies exactly the same translation to the launcher and loaded
rocket. This preserves their authored relative placement. It does not rotate,
scale, or independently offset either mesh, and it does not alter the legacy
`root_point`, `handle`, `p_fx`, or `a_barrel` nodes.

`tools/prepare_warlock_weapon_fbx.py` bakes
`Translation(delta_grip) * source_object.matrix_world` into each copied carried
mesh, parents the launcher under the preserved legacy rig at identity, and
parents the loaded rocket beneath the launcher at identity. Its reimport gate
compares the translated source points with the exported points at the weapon
root; it must not move the imported rig onto the source character's hand for
that comparison.

The standalone fired projectile is a separate contract. Its geometry is
normalized into the immutable Dalo `pRocket` mesh-local frame, its authored
nose is mapped to legacy local `+Y`, it is centered in the legacy bounds, and
the legacy `pRocket` node transform is retained. Do not copy the carried
launcher's object hierarchy into `SM_Rocket.fbx`.

### Offline placement gates

`tools/tests/test_warlock_weapon_pipeline.py` parses binary FBX directly and
compares the full geometry-to-model chain against the immutable known-good
launcher. It intentionally does not require Crunch's different shape to match
the Dalo placeholder vertex-for-vertex. The source-FBX gates are:

- canonical root axes differ from known-good by less than `2e-5` per
  component;
- the attachment origin is inside the effective launcher AABB, allowing at
  most `0.05` RMS-radius normalized margin;
- the closest effective mesh surface is no more than 5 cm from node 0 and its
  RMS-radius-normalized distance is at most `0.08`;
- after coincident-position welding, exactly one connected 217-vertex
  component exists, and the centroid of its upper 10 mm cap is within 0.1 cm
  per axis of `q_old`; this semantic gate prevents a rear-stock surface from
  impersonating the grip;
- the effective dominant length axis has `abs(dot) >= 0.85` with the known-good
  attachment axis;
- the full 4,916-vertex source has the exact reviewed 3,308/1,608 closed split,
  the 1,608-vertex block has the pinned 13-component tether topology, and the
  198-vertex conduit remains distinct, unrigged, and unexported;
- the retained rigid topology, rigid shape profile, per-vertex UV mapping,
  material names, and exact runtime node names remain unchanged.

The rejected v0.1.54 geometry measured normalized origin-envelope gap
`0.348408` and axis alignment `0.373250`. The calibrated, tether-free v0.1.55
source FBX measures gap `0.000000`, axis alignment `0.999179`, nearest-surface
distance `0.220337` cm (`0.006059` normalized), and semantic grip centroid
`(0.000002568, 1.108044572, 0.000003545)` cm. Its launcher and loaded-rocket
round trips are each below 0.5 micrometres. All source-FBX semantic,
orientation, shape, hierarchy, and material gates pass.

The suite also parses the compiled launcher unit after every VMB build. It
requires compiled bounds to match the final FBX within 0.005 m per endpoint,
compiled/source principal-axis alignment of at least `0.98`, surface distance
agreement within 0.005 m, compiled surface distance no greater than 0.05 m and
`0.08` normalized, and the same semantic grip cap within 0.1 cm per canonical
axis. It also rechecks that the compiled `pRocket` inherits the one
`rp_dropped` actor. This gate rejected the stale pre-calibration bundle, then
passed after the clean v0.1.55 build. The rebuilt compiled grip centroid was
`(-0.000074506, 1.108050346, 0.000148831)` cm. Source and compiled success are
still not runtime visual acceptance.

## Death-drop and projectile physics closure

The weapon is an inventory unit, not a body-ragdoll limb. The hidden native
Ratling remains the character physics carrier; none of this work adds weapon
bones or a custom launcher actor to the Warlock body's death retarget.

`rocket_glaive_1.drop_reasons.death = true` causes the inventory system to drop
the carried unit. `units/rocket/pRocketLauncher.physics` has one disabled
dynamic actor named `rp_dropped`, bound to node and shape
`pRocketLauncher`, plus the normal keyframed carried actor on the same node.
The runtime enables the drop actor for the launcher. It does not independently
create a dynamic actor for every visible child mesh.

Therefore every carried renderable must be within the one actor's transform
subtree:

```text
root_point (legacy weapon frame)
└── pRocketLauncher (mesh; rp_dropped actor owner)
    └── pRocket (loaded visible warhead; no independent actor)
```

In v0.1.53 the two meshes were siblings under `root_point`. The launcher fell,
but the loaded rocket remained at the unlink pose and appeared to float. The
v0.1.54 hierarchy fixes that defect without introducing two unconstrained
rigid bodies or additional solver work. The source-FBX tests recreate the old
sibling mutation and require it to fail; compiled-bundle tests also verify that
`pRocket` is a direct child of `pRocketLauncher` and that `rp_dropped` targets
only the launcher node.

The fired unit has its own physics lifecycle. `SM_Rocket.physics` retains the
exact `pRocket` node, an enabled keyframed actor, and the disabled `throw`
projectile actor which gameplay activates. A working death drop does not prove
projectile orientation, collision, or explosion behavior.

## Deterministic export and verification

Run Blender 5.2 from the repository root with the exact source scene:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' `
  --background 'C:\Users\danjo\Downloads\xud4soo5fg7g8qd4.blend' `
  --python tools\prepare_warlock_weapon_fbx.py -- `
  --launcher-output .build\weapon_candidate\pRocketLauncher.fbx `
  --projectile-output .build\weapon_candidate\SM_Rocket.fbx
```

By default the exporter reads the two immutable legacy FBXs directly from the
pinned Git blobs and checks their hashes. Optional `--legacy-launcher` and
`--legacy-projectile` arguments are accepted only for files with those exact
hashes. Never make a shipping output its own `--legacy-*` input.

Review the exporter's source/reimport checks, then copy the reviewed candidates
to `units/rocket/`. Run the focused suite before invoking VMB:

```powershell
py -3 tools\tests\test_warlock_weapon_pipeline.py
```

The suite checks source provenance, geometry and UV identity, canonical frame,
surface proximity, semantic grip identity/calibration, node names and
transforms, loaded-warhead hierarchy, unit/material/physics contracts, and
mutation resistance. When `bundleV2` exists it also compares the compiled
launcher geometry, semantic grip, and actor closure with the final FBX. A stale
compiled bundle can only describe the previous build, so run the full pipeline
again after every asset replacement.

## Build, splice, test, deploy, and upload

Use the known headless v0.5.6 launcher binary and the Doomrocket-specific
configuration. Always supply a verb; invoking the executable with no arguments
opens the GUI.

```powershell
$vmb = 'C:\Users\danjo\source\repos\vmb-launcher-baseline-056-20260726\bin\Release\net9.0-windows\win-x64\publish\VMBLauncher.exe'
$cfg = 'C:\Users\danjo\source\repos\_doomrocket_vmb\vmblauncher.settings.json'

& $vmb build doomrocket --clean --config $cfg
powershell -NoProfile -ExecutionPolicy Bypass -File tools\splice_warlock_materials.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-WarlockPipeline.ps1
& $vmb deploy doomrocket --no-remote --config $cfg
& $vmb upload doomrocket --config $cfg
```

The order is mandatory. VMB's SDK build emits placeholder child-material
payloads; `splice_warlock_materials.ps1` replaces them with the reviewed native
children. `Test-WarlockPipeline.ps1` must inspect the already-spliced bundle
before deployment or publication. Never use the `all` verb for Doomrocket:
there is no splice point inside it, so it can publish an unspliced bundle.
`--no-remote` is explicit because this release lane targets the local Workshop
folder; an unavailable PC-B remote must not turn a valid local deployment into
a failed command.

After upload, verify a fresh `workshop_log.txt` success record/ManifestID for
published item `3771657344`, verify the deployed Workshop folder hashes match
`bundleV2`, and retain `public` visibility. A successful uploader exit
without a fresh log record and matching content is not publication evidence.

## Runtime acceptance

The tester should use the established spawn/kill method and a uniquely bumped
version. Confirm the exact `[doomrocket:LOAD]` banner before evaluating the
model. Disable Less Corpses and other corpse/physics replacement mods for the
acceptance capture.

At minimum, record and inspect:

1. Living/wielded: final Crunch launcher and loaded rocket are in the hands;
   the hands contact the `handle`/barrel instead of the weapon floating beside
   the model. The deferred two-metre backpack tether and short conduit must not
   appear as unrigged floating geometry in this MVP.
2. Firing: the rocket appears at `p_fx`, travels nose-forward, collides, and
   explodes through the existing behavior.
3. Reload: the loaded `pRocket` visibility transition still works.
4. Unwielded/back: the launcher is attached at `a_spear` and does not preserve
   an erroneous hand offset.
5. Death with a loaded weapon: launcher and warhead fall together as one rigid
   prop. The warhead neither floats nor becomes an independently flailing
   body.
6. Body corpse: the Warlock remains recognizable and stable, with no native
   Ratling reveal, stick figure, roof launch, physics burst, or frame-rate
   collapse.
7. Materials: the console reports `slots=5/5 custom_textures=6/6 resident`, and
   the weapon/rocket show the set-03/set-04 textures without magenta fallback.

Analyze the new console log with its exact version:

```powershell
py -3 tools\analyze_warlock_ragdoll_log.py 'C:\path\to\console.log' --expected-version X.Y.Z-dev
```

`[ragdoll-log] OK` is necessary for the body lane. Video or direct visual
observation is mandatory for hand/back placement, loaded-warhead closure,
muzzle position, and projectile direction. Do not infer those from the absence
of engine errors.

## Failure signatures and first checks

| Symptom | Most likely contract violation | First check |
|---|---|---|
| Launcher displaced or rotated in both hand and back modes | Geometry received the rejected inverse-hand bake or lost its canonical axes | Canonical frame/dominant-axis tests; inspect for an inverse `j_leftweaponattach` bake |
| Launcher direction is plausible but the hand meets the rear stock or empty space | Presentation-space origin was mistaken for a grip, or `delta_grip` was omitted/changed | Unique 217-vertex pistol-grip cap must land on `q_old`; verify the exact translation-only constant |
| A generic origin/surface test passes but the grip is wrong | AABB containment or nearest-surface logic selected non-semantic geometry; the uncalibrated closest surface is the stock | Semantic component/cap test, not another arbitrary surface snap |
| A long segmented hose floats above or moves rigidly with the weapon | The deferred 1,608-vertex backpack tether was exported inside `pRocketLauncher` without a flexible rig | Shipping launcher must be the exact 3,308-vertex retained subset; verify the closed split and topology gates |
| Launcher correct in hand but wrong on back | Unwielded root link or authored root pivot | `unwielded target=0 -> source=a_spear`; do not alter wielded secondary links first |
| Semantic grip is calibrated but the hands pose incorrectly | `handle`/`a_barrel` node transform or secondary link changed | Exact legacy node translations and `AttachmentNodeLinking.ai_doomrocket` |
| Source FBX passes but the game shows the previous placement | VMB bundle is stale or compiled transform differs from the final FBX | Clean build, then compiled bounds/axis/surface/semantic-grip gate before deploy |
| Projectile emerges from the wrong place | `p_fx` missing, suffixed, or moved | Exact `p_fx` node and launch-action lookup |
| Fired rocket travels sideways/backward | Standalone `pRocket` legacy local `+Y` convention changed | `SM_Rocket.fbx` normalization and `throw` actor, not carried-weapon attachment rotation |
| Launcher falls but loaded warhead floats | `pRocket` became a sibling of `pRocketLauncher` | Source and compiled parent chain |
| Launcher and warhead collide/flail separately | A second dynamic loaded-warhead actor was added | `pRocketLauncher.physics` must keep one `rp_dropped` actor on the launcher |
| Missing mesh/actor despite correct-looking Blender scene | Blender added `.001` names or `.unit`/`.physics` points at another node | Raw FBX names plus exact renderable/node/shape strings |
| Correct body ragdoll but misplaced weapon | Independent rigid-prop placement failure | Keep body handoff unchanged; fix the weapon geometry-to-root chain |
| Texture fallback or old placeholder appearance | Material slot/sampler or compiled-splice failure | Weapon suite, texture suite, `5/5` and `6/6` runtime residency, then built-bundle splice evidence |
| Stick figure, body explosion, roof launch, or severe hitch | Body death-retarget/ragdoll regression, not a launcher-axis fix | Full ragdoll protocol and analyzer; do not add launcher physics to the character rig |

The governing rule is simple: preserve the old engine-facing frame and runtime
names, calibrate the new art by a real grip landmark without changing its
verified rotation, keep every carried renderable in the one drop actor's
subtree, and require source, compiled, and in-game acceptance gates.
