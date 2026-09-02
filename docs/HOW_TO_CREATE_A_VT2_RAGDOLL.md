# How to create a Vermintide 2 ragdoll for a custom enemy

This is the practical procedure derived from the Warlock Bombardier work. It
covers both a conventional Stingray ragdoll and the carrier/visual architecture
used by Doomrocket v0.1.50. Read the failure table before choosing a design;
the two architectures solve different problems and must not be mixed.

## 1. Choose the physics owner first

There are two valid architectures.

### A. One unit owns both skin and ragdoll

Use a conventional authored ragdoll when the visible mesh is skinned to the
**exact scene graph, rest transforms, scale basis, and inverse binds** used by
its physics unit. The same unit owns:

- the skinned mesh;
- the animation state machine;
- actors and collision shapes;
- constraints and ragdoll state.

This is the normal Autodesk Stingray workflow. It is the simplest result when
the asset really uses one canonical rig.

### B. A native unit owns physics; a custom unit owns pixels

Use a carrier/visual handoff when the custom skin and a stable native VT2
ragdoll share bone names but not the exact compiled hierarchy or transform
basis. The native unit keeps all actors, constraints, impacts, arrows, cleanup,
and networking. Its meshes stay hidden. A physics-free custom unit follows its
ragdoll pose and remains visible.

This is the Doomrocket v0.1.50 architecture; the persistent driver and stricter
guards described below are post-v0.1.50 hardening. It is not an actor
transplant.
The Actor API exposes each actor's owning unit, and no supported runtime API
for moving a complete ragdoll between units was found; the unit-ownership
conclusion is therefore a source/API inference, not an explicit Autodesk
guarantee.

Do **not** give both units dynamic actors. Do **not** reveal the carrier as a
fallback corpse. Do **not** copy transforms between the rigs in local space.

## 2. Audit the rigs before authoring anything

For both architectures, record these facts from the compiled resources—not
only from Blender or Maya:

1. Full scene-node count and names.
2. State-machine `.bones` count and names. This is a selected animation subset,
   not necessarily the full scene graph.
3. Parent index and local rest matrix for every deform bone.
4. World rest matrix for every common bone.
5. Wrapper nodes and accumulated scale above `root_point` and `j_hips`.
6. Skin count, actor count, mesh count, and physics-scene presence.
7. Which unit actually owns hit actors, embedded projectiles, and cleanup.

Name equality is necessary but insufficient. Doomrocket's 138 custom bone
names all exist in the native ratling scene graph, yet 83 of 106 common
state-machine bones have different local rest matrices and all 106 have
different world rest matrices. The custom armature also sits under a 100×
wrapper while the native ratling root is scale 1.

If the rig audit cannot prove exact rest-space identity, do not use raw local
pose copying and do not assume a same-named bone is interchangeable.

## 3. Conventional authored ragdoll procedure

Use this only for architecture A.

### DCC preparation

1. Start from the exact skeleton used by the final compiled character. Do not
   rebuild, rename, reparent, or add wrapper transforms after physics authoring.
2. Use the exporter version specified by the **VT2 SDK**, not whichever
   version appears in documentation for a different Stingray release. The
   installed SDK's `tools/physx_exporters/Readme.txt` says PhysX export from
   Maya/Max is the only supported way to create constrained setups such as
   ragdolls, directs users to PhysX `3-4-2`, and lists Maya 2015–2018,
   Maya LT 2018–2019, and 3ds Max 2015–2019.
3. Work at the documented physical scale. Autodesk's Maya workflow starts in
   meters and applies the required export conversion for the PhysX/APX file.
   Verify the imported actor dimensions against the character; do not infer
   correctness from the DCC viewport alone.
4. Apply/freeze mesh transforms and keep the skeleton, skin, animation, and
   physics exports on one coordinate convention.

### Bodies and constraints

1. Create the pelvis/hips rigid body first. Prefer a simple box, capsule, or
   sphere close to the body volume; avoid dynamic triangle meshes.
2. Add torso, head, upper/lower arms, thighs, and shins in hierarchy order.
   Use the minimum number of actors that produces the desired motion.
3. Connect parent and child actors with constraints. Selection order matters:
   parent first, child second.
4. Place each constraint at the anatomical joint. Begin with conservative
   swing limits and locked or narrow twist, then widen only after stable tests.
5. Use plausible nonzero masses and inertias. Avoid tiny collision shapes,
   intersecting shapes, and extreme mass ratios across adjacent limbs.
6. Simulate in the DCC on flat ground, stairs, and slopes. Correct persistent
   twitching before export; a ragdoll that never sleeps remains expensive.

### Export, import, and controller

1. Return every intended ragdoll body to `Dynamic` for the exported physics
   scene.
2. Export APEX/PhysX as APX/XML with the filename and location expected beside
   the character unit. Autodesk's generic tutorial describes a same-name XML
   beside the `.unit`; Doomrocket's historical VT2 compile accepted a
   same-path `.physx` resource. The VT2 SDK readme does not document that
   filename conversion, so verify the actual compiler input and compiled
   `physics_scene` payload instead of treating an extension as proof.
3. Re-import the character unit and inspect every actor in the Unit Editor.
   Disable any exported ground plane.
4. Disable the ragdoll bodies at ordinary spawn so animation owns the living
   character.
5. In the animation controller, define the ragdoll actors as Dynamic,
   Kinematic, or Ignored, add a ragdoll state, and transition on the death
   event.
6. Compile and inspect the resulting unit: actor count, constraints, physics
   payload, node bindings, and scale must match the audit.

A minimal state-machine shape is a dedicated empty-to-ragdoll layer plus a
ragdoll definition. Names below are illustrative; every actor must match the
exported physics scene exactly:

```sjson
events = { ragdoll = {} }
layers = [
    {
        default_state = "ragdolls/empty"
        states = [
            {
                name = "ragdolls/empty"
                state_type = "empty"
                transitions = [
                    { event = "ragdoll" to = "ragdolls/ragdoll" mode = "direct" }
                ]
            }
            {
                name = "ragdolls/ragdoll"
                state_type = "ragdoll"
                ragdoll = "ragdoll"
            }
        ]
    }
]
ragdolls = {
    ragdoll = {
        actors = [ "j_hips" "j_spine" "j_head" ]
        keyframed = []
    }
}
```

Autodesk's primary references are [Create and import a ragdoll](https://help.autodesk.com/cloudhelp/2021/ENU/Max-Interactive-Help/interactive_help/creating_gameplay/physics/create_import_ragdoll.html),
[Ragdolls](https://help.autodesk.com/cloudhelp/ENU/Stingray-Help/stingray_help/animation/ragdolls.html),
[Basic physics concepts](https://help.autodesk.com/cloudhelp/2020/ENU/Max-Interactive-Help/interactive_help/creating_gameplay/physics/basic_physics_concepts.html),
and [Ragdoll performance](https://help.autodesk.com/cloudhelp/2021/ENU/Max-Interactive-Help/interactive_help/animation/animation_perf.html).

### VT2 integration rule

Keep the breed's body-coupled data consistent with the chosen physics unit:
base unit, hit zones, hitbox-to-ragdoll translation, actor thickness, unit
template, and death reaction. A skin does not make an unrelated physics unit
compatible. Spawn and kill a single unit before testing concurrency.

The Warlock's custom-physics attempts are retained as negative evidence: its
actors fought animation at death and destabilized PhysX below one frame per
second. A green compile is not a runtime stability result.

## 4. Native-carrier/custom-visual procedure

Use this for architecture B. The production example is:

- carrier breed: `scripts/mods/doomrocket/breeds/skaven_doomrocket.lua`;
- visual item and bone map:
  `scripts/mods/doomrocket/breeds/skaven_doomrocket_inventory.lua`;
- living/death handoff: `scripts/mods/doomrocket/utils/hooks.lua`;
- earliest death capture:
  `scripts/mods/doomrocket/extensions/death_reactions.lua`.

### Asset contract

1. Clone a native breed whose gameplay, actors, animation, and ragdoll already
   work. Keep that native unit as the authoritative physics carrier.
2. Make the custom skinned unit an `ai_outfit_unit` with **zero actors and no
   custom physics scene**.
3. Attach it root-only. Preserve its internal skeleton hierarchy; never call
   `World.link_unit` independently for every deform bone.
4. Hide each carrier mesh with `Unit.set_mesh_visibility(..., false)`. Do not
   hide the carrier with whole-unit visibility because its scene graph must
   continue animating and simulating.
5. While alive, run the custom visual on its own compatible animation state
   machine. Mirror only name-based events that the visual supports. Never
   forward raw state-machine variable or constraint indices.

### Capture before competing death events

Capture the handoff in the custom death reaction's `pre_start`, before later
hit-reaction code can emit a death/ragdoll animation event.

For each mapped source/target bone, store:

- rigid source world pose at handoff, `S0`;
- its precomputed inverse;
- full target world pose at handoff, `T0`;
- target parent index and hierarchy depth;
- target local translation and scale at handoff.

Use `Matrix4x4Box` for matrices retained across frames. Autodesk documents raw
`Matrix4x4` userdata as frame-temporary.

Treat calibration as one atomic preflight. Before changing event mirroring,
bone mode, visibility, or driver registries:

1. Call `Unit.has_node` for every named source and target before the matching
   `Unit.node`; explicitly require one source and one target `j_hips`.
2. Reject duplicate target indices and any mapping count other than the
   compiled contract. Doomrocket's current filtered bridge is exactly 90
   mapped nodes; a different count is an asset change requiring a new audit.
3. Require every `S0` to be finite and invertible before calling
   `Matrix4x4.inverse`, and validate the resulting inverse.
4. Require every `T0` to be finite and invertible, and every retained local
   translation and scale to be finite. Walk every unmapped target-parent
   segment needed by the transfer and require each retained local matrix to be
   finite and invertible.
5. Test invertibility with both minimum axis lengths and a scale-normalized
   scalar triple product. Axis-length checks alone miss collinear or
   near-singular bases.

On any failure, emit a keyed zero-callback stop reason and leave the living
visual ownership unchanged. A Lua `pcall` cannot make an invalid `Unit.node`
or native matrix operation safe after the fact.

After capture:

1. Stop mirroring animation events to the visual.
2. Keep its state machine lifecycle unchanged, but call
   `Unit.set_animation_bone_mode(visual, "ignore")` so animation cannot
   overwrite bone nodes.
3. Register a strong death driver that survives the short vanilla death
   reaction update window.

Autodesk defines `ignore` as preventing animations from affecting bone nodes;
`transform`, by contrast, applies animation position, rotation, and scale.
See the [`Unit` Lua API](https://help.autodesk.com/cloudhelp/2019/ENU/Max-Interactive-Help/lua_ref/obj_stingray_Unit.html).

### Convert motion through calibrated world space

With Stingray/VT2 row-matrix multiplication, for each mapped bone:

```text
S0 = rigid source world pose at handoff
St = rigid source world pose this frame
T0 = full target world pose at handoff

D          = inverse(S0) * St
TdesiredW  = T0 * D
Ldesired   = TdesiredW * inverse(PdesiredW)
```

`PdesiredW` is the desired world pose of the target bone's parent. Resolve all
desired worlds from a frozen source snapshot, then apply target locals in
parent-first order. Do not trust a hand-written mapping table to be topological.

Important controls:

- Build `S0` and `St` from source world rotation and position so source scale
  or shear cannot enter `D`.
- Preserve target calibration, including its wrapper basis, in `T0` and the
  parent world.
- Apply `Ldesired` rotation to mapped child bones, but retain each child's
  calibrated target-local translation and scale. This preserves bone lengths.
- Apply corrected translation only to the deform root/hips. Never copy the
  source hips local position directly.
- Never write target scale.
- Validate source, target calibration, desired-world, parent, inverse-parent,
  and desired-local matrices before the first engine write. Reject singular or
  near-collinear target, parent, and desired-local bases before inversion or
  rotation extraction.

The inverse-parent conversion is load-bearing. Under Doomrocket's scale-100
wrapper, a 0.05 m source world movement becomes 0.0005 target-local units and
then evaluates back to 0.05 m in world space. The old direct local copy turned
the native hips rest position into an 86.899 m displacement.

### Apply after animation, before scene update

Writing from an entity-system update is too early: world animation can replace
the manual pose later in the same frame. Queue a one-shot
`AnimationSystem.add_safe_animation_callback()` only after the exact carrier
world finishes `World.update_animations` or
`World.update_animations_with_callback`. The callback applies and samples the
pose before that world's scene update.

The safe-callback queue is shared across active worlds. Never self-requeue from
inside the callback; another world could drain it again in the same rendered
frame. Use a pending flag and enqueue once from the carrier's world update.

### Keep the pose driver for the corpse lifetime

Five seconds is a diagnostics horizon, not a pose-driver lifetime. The current
hardened driver remains strongly registered until the carrier or visual is
deleted, or until `StateIngame` exit, mod disable, or mod unload resets all
drivers. A queued callback must observe the stopped flag and become a no-op
after reset.

Before the five-second monitor completes, run the callback and transfer the
pose on every owner-world animation pass even if a native actor reports
sleeping. Do not enumerate or cache the dynamic actor set and do not suppress
any pose write before `monitor_complete`; all checkpoints must remain both
observable and spatially correlated. After the monitor completes, enumerate
actor indices
`0..Unit.num_actors(carrier)-1`, retain the actual actors for which
`Actor.is_dynamic` is true, and:

- skip bone transfer and `World.update_unit` while all of them are sleeping;
- keep the driver registered and test their sleep state from the owner-world
  animation hook;
- resume the safe callback immediately when any actor wakes.

Do not infer actor names from deform-bone names; a unit's physics actor names
are a separate resource contract. If no dynamic actor is found on the
ragdoll-transition frame, treat the state as awake and retry instead of
permanently suspending the driver.

Use `Managers.time:time("game")` for monitor elapsed time and checkpoints so a
pause does not consume the observation window. Use
`Application.time_since_launch()` only for callback-gap performance telemetry.
Accumulate the worst wall-clock callback gap over the whole interval between
checkpoints; logging only the gap immediately before a checkpoint can hide a
one-frame stall.

### Make carrier visibility fail closed

Register the native carrier only after its complete mesh set has been hidden.
Intercept any later `set_mesh_visibility(..., true)` call, count and log it as
a failure, and pass `false` to the engine. Intercept a whole-unit visibility
enable, log it, and synchronously re-hide every carrier mesh before returning.
This blocks known Lua reveal paths; video remains necessary because an
engine-internal render-state or culling change is outside the hook's view.

## 5. Diagnostics are part of the implementation

Every death must receive a unique ID and lane:

```text
[doomrocket:RAGDOLL] phase=begin id=unit-0001 source=unit ...
[doomrocket:RAGDOLL] phase=sample id=unit-0001 source=unit ...
[doomrocket:RAGDOLL] phase=stop id=unit-0001 source=unit ...
```

Sample at the exact game-time checkpoints 0, 100, 250, 500, 1000, 2000, and
5000 ms. Record:

- owner and visual lifetime;
- mapped node count and custom actor count;
- carrier reveal incidents;
- scene-parent mismatches;
- named-root and hips drift from calibration;
- scale and non-hips translation mutations;
- bounds and maximum bone-radius ratios;
- worst elapsed wall gap between callbacks since the prior checkpoint.

The `phase=stop reason=monitor_complete` line closes the five-second telemetry
trace; it does **not** mean the persistent pose driver was removed. Early stop
reasons are failures. After monitor completion, lifetime/wake behavior and
ordinary cleanup are runtime visual gates because the compact telemetry schema
does not emit a second driver-destruction record.

Logs prove timing, transforms, lifetime, and measured performance. They cannot
prove that the correct pixels, UVs, or textures rendered. Video or direct
observation remains a separate visual gate.

Run the source and mutation suite:

```powershell
powershell -NoProfile -File tools/tests/Test-WarlockRagdollRegressions.ps1
powershell -NoProfile -File tools/Test-WarlockPipeline.ps1
```

Analyze a runtime log:

```powershell
py -3 tools/analyze_warlock_ragdoll_log.py "C:\path\to\console.log" --expected-version 0.1.55-alpha
```

Supply the exact tested version for every acceptance capture. The option is
deliberately not a default requirement so old logs remain analyzable, but a
release result without a matching `[doomrocket:LOAD]` banner is not valid.

The complete scenario matrix and thresholds are in
`docs/testing/WARLOCK_RAGDOLL_TEST_PROTOCOL.md`.

## 6. Acceptance checklist

A ragdoll is accepted only when all applicable lanes pass:

- correct build banner and Workshop manifest;
- recognizable custom corpse; no visible carrier;
- host `source=unit` and remote-client `source=husk` deaths;
- single deaths, five rapid deaths, and stairs/slopes;
- no disappearance, stick figure, stretch, roof launch, or unrelated physics
  corruption;
- custom visual remains alive for the observation window;
- no custom actors in the carrier/visual design;
- zero carrier reveals, parent mismatches, scale mutations, and non-hips
  translation mutations;
- exactly 90 mapped nodes and exactly one sample at each required checkpoint;
- hips drift at most 0.25 m;
- root delta and named-root drift at most 0.25 m; maximum anchor drift at most
  0.5 m;
- absolute hips separation at most 0.25 m;
- bounds and maximum bone-radius ratios within 0.5×–2× baseline;
- callback wall gap at most 250 ms;
- after five seconds, a sleeping corpse resumes correct pose transfer when a
  carrier actor is woken;
- normal corpse cleanup after the configured lifetime.

Use `physics debug on` when validating an authored ragdoll and confirm its
dynamic actors eventually sleep on flat ground, stairs, and ramps.

## 7. Doomrocket v0.1.50 host result

The 2026-08-12 log
`console-2026-08-12-02.22.45-73b986c9-2cbf-463e-8bdf-ba8f8ef99f3e.log`
is the first runtime telemetry pass for the original calibrated handoff:

- 11 independently correlated host corpses;
- 7 samples each at 0–5000 ms, then normal `monitor_complete`;
- owner and visual alive throughout;
- zero custom actors, carrier reveals, hierarchy changes, scale changes, or
  non-hips translation changes;
- maximum hips drift 0.133 m;
- maximum bone-radius ratio 1.469×;
- largest checkpoint-adjacent callback gap 19.6 ms;
- no assertion or solver anomaly was observed.

All 11 spawns also reported 5/5 material slots and 8/8 textures resident. This
log proves five seconds of host-side transform stability and unit lifetime for
that build. In the tested v0.1.50 code, `monitor_complete` also ended pose
driving and `wall_gap_ms` was the sampled preceding gap, not the hardened
interval maximum. The log therefore does **not** validate the later persistent
sleep/wake driver, pause-safe game-time monitor, worst-gap accumulator,
calibration preflight, or fail-closed visibility hooks. Those changes require
a uniquely versioned host/client runtime pass. The result also does not replace
visual inspection and contains no `source=husk` client coverage.

### v0.1.51 sleep-gate regression and the v0.1.52/v0.1.53 fix

The v0.1.51 log
`console-2026-08-12-22.42.49-d1eaa659-0dcc-4c1d-bebd-1789887d36d9.log`
showed why the ordering above is mandatory. One host corpse completed all seven
samples and logged 602 callbacks, but hips drift reached 2.505 m and anchor
drift reached 3.567 m at 5 s. The largest wall gap was only 11.1 ms, the
bone-radius ratio stayed approximately 0.998, and no custom actors, carrier
reveals, hierarchy changes, scale changes, or non-hips translation changes were
reported. The visual pose was being suppressed, not deformed or stalled.

v0.1.51 had discovered/consulted sleeping actors before the monitor completed
and skipped the transfer while the native ragdoll moved. v0.1.52 moved sleep
optimization behind the completed monitor. v0.1.53 carried that fix forward
and made the log prove `callbacks=pose_writes` and `sleep_skips=0` over the full
acceptance window. v0.1.53, v0.1.54, and v0.1.55 host captures runtime-prove
that ordering: every monitored callback wrote a pose and no pre-monitor sleep
skip occurred.

### v0.1.55 accepted host MVP and dense-stress distinction

The 2026-08-13 v0.1.55 log
`console-2026-08-13-02.50.55-72751c68-b9fa-4a86-91d7-55e6a520a98c.log`
contains 20 complete host `source=unit` traces and 20 material summaries. Across
all traces, the maximum hips drift was 0.185 m, callback gaps stayed below
23.6 ms, every stop had `callbacks=pose_writes`, and `sleep_skips=0`. The user
also confirmed the visible corpse and weapon behavior in game.

The capture combines two different tests. Its first six ordinary traces pass
the strict analyzer, with maximum anchor drift 0.363 m. The following fourteen
corpses were killed together in the same collision pile. Their differing
extremity poses briefly produced 15 anchor-offset excursions at 250/500 ms,
including one 8.404 m diagnostic value, while hips/root/deformation, pose-write,
and performance gates remained bounded. Every trace returned below the normal
anchor gate by one second and ended at or below 0.305 m.

Do not weaken ordinary acceptance to bless such a file. Capture normal deaths
separately and require the default analyzer to pass. Use `--dense-stress` only
for a separate ten-or-more-corpse overlap capture; it waives only transient
250/500 ms anchor-offset excess and requires ordinary anchor compliance at
1000, 2000, and 5000 ms. All other gates and the visual test remain strict.
This result establishes the observed host MVP, not remote-client `source=husk`,
pause, explicit post-monitor wake, or long-lived cleanup behavior.

## 8. Failure signatures and their causes

| Symptom | Likely cause | Correct response |
|---|---|---|
| Body explodes; unrelated physics destabilizes; FPS collapses | Two physics solvers/actor sets fighting, invalid shapes/inertia, or a ragdoll that never sleeps | Return to one physics owner; inspect actors, intersections, mass ratios, constraints, and sleep state |
| Stick figure | Per-bone scene links replaced the custom armature hierarchy | Restore root-only attachment and drive bone locals without relinking nodes |
| Giant stretched body or roof launch without a physics stall | Raw local pose/scale copied between incompatible rigs | Use calibrated rigid world deltas; preserve target child translations/scales |
| Custom corpse vanishes while arrows remain | Hips/root was moved outside the visual hierarchy or bounds; carrier still exists | Inspect named hips/root world drift; do not blame cleanup without lifetime evidence |
| Stable ratling corpse appears | Carrier meshes were revealed as a shortcut | Keep all carrier meshes hidden; visible model identity is an acceptance gate |
| Manual pose looks correct in logs but diverges after rendering | Animation writes later in the frame | Set bone mode `ignore` and apply from the post-animation safe callback |
| Several pose callbacks per rendered frame | Safe callback self-requeued and was drained by multiple worlds | Enqueue once after the exact owner-world animation pass |
| Hips and anchor drift grow while callbacks, frame gaps, deformation ratios, and mutation counters remain normal | Sleep detection suppressed pose writes during the monitor; v0.1.51 reached 2.505 m hips drift despite 602 callbacks | Forbid actor discovery, sleep caching, and sleep-based suppression until `monitor_complete`; require `callbacks=pose_writes` and `sleep_skips=0` in the tested build |
| Corpse detaches only after five seconds or after a later impact | Monitor completion removed the driver, or sleep/wake detection failed to resume it | Keep the driver registered for unit lifetime; reproduce with the post-monitor wake test |
| A paused test reaches checkpoints or a hitch disappears from telemetry | Monitor used wall time, or only the final pre-sample gap was logged | Use game time for checkpoint lifetime and accumulate the worst wall gap per interval |

## 9. Build and ship without invalidating the result

For Doomrocket, use the known headless v0.5.6 launcher and its project-specific
configuration:

```powershell
$vmb = 'C:\Users\danjo\source\repos\vmb-launcher-baseline-056-20260726\bin\Release\net9.0-windows\win-x64\publish\VMBLauncher.exe'
$cfg = 'C:\Users\danjo\source\repos\_doomrocket_public_vmb\vmblauncher.settings.json'

& $vmb info doomrocket --config $cfg
& $vmb build doomrocket --clean --config $cfg
powershell -NoProfile -ExecutionPolicy Bypass -File tools\splice_warlock_materials.ps1 -UseVerifiedCache
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-WarlockPipeline.ps1
& $vmb deploy doomrocket --no-remote --config $cfg
& $vmb upload doomrocket --allow-public --config $cfg
```

After upload, require a fresh successful ManifestID in `workshop_log.txt`, then
compare every deployed Workshop payload hash with local `bundleV2`. Verify the
intended `itemV2.cfg` visibility—`public` for the alpha release—so the next
upload cannot silently revert it. Only then commit and push the reviewed source
to `public/main`.

Never use `vmblauncher all`; it uploads before the required material splice.
Keep mutation fixtures on inert `.fixture.txt` extensions because VMB scans the
mod tree and will otherwise compile test resources into the shipping bundle.
