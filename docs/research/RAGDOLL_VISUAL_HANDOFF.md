# Warlock visual handoff onto the native ratling ragdoll

Status: **the original offset-corrected v0.1.50 handoff passed a five-second
host baseline on 2026-08-12. v0.1.51 failed because its new sleep gate
suppressed pose transfer before the monitor completed. v0.1.52 introduced the
fix but received no runtime capture. v0.1.53 added explicit pose-write/
sleep-skip telemetry, and v0.1.53 through v0.1.55 runtime-prove the corrected
host ordering. The v0.1.55 host MVP is user-confirmed visually; remote-client
husk, explicit post-monitor wake, pause, and long-lived cleanup coverage remain
required**.

This note separates three things that previous builds conflated:

1. the native unit that owns gameplay and ragdoll physics;
2. the custom skinned unit that must remain visibly Warlock-shaped; and
3. the coordinate- and frame-order conversion that makes the visual follow the
   native corpse.

Passing physics while drawing a ratling corpse is not acceptance.

## Confirmed unit roles

The current carrier is a native **ratling gunner**, not a stormvermin:

- `scripts/mods/doomrocket/breeds/skaven_doomrocket.lua:36-65` clones
  `Breeds.skaven_ratling_gunner` and preserves its native unit template.
- The carrier's meshes are hidden while alive, but the unit keeps its native
  animation, hit actors, and ragdoll. The 138-bone Warlock unit is a separate
  `ai_outfit_unit` visual attached root-only.
- VT2 deliberately keeps `ai_outfit_unit`, `ai_skin_unit`, and helmet units
  attached instead of dropping them on death
  (`Vermintide-2-Source-Code/scripts/entity_system/systems/ai/ai_inventory_extension.lua:378-427`).
- Autodesk's Actor API exposes the scene-graph node in, and the `Unit` that
  owns, each actor. The recovered unit resource likewise stores actors and
  physics-scene data inside the unit. There is no documented runtime operation
  that transfers a ragdoll's actors to another unit. The supported design is a
  native physics owner plus a following visual, not an actor transplant.

Autodesk documents repeated `World.link_unit()` calls as the supported way to
attach clothing to multiple skin bones, but every call resets that child
node's local position, rotation, and scale to the parent node. `unlink_unit()`
does not restore the child's previous internal parent. VT2 therefore snapshots
each linked node's parent and local pose before linking and restores both on
unlink (`Vermintide-2-Source-Code/scripts/entity_system/systems/ai/ai_inventory_extension.lua:5-45`).
The complete internally parented Warlock armature is not a native link-authored
outfit; its v0.1.44 stick figure is consistent with replacing those internal
relationships one bone at a time. The current lane remains root-only.

Official references:

- [Actor Lua API](https://help.autodesk.com/cloudhelp/2021/CHS/Max-Interactive-Help/lua_ref/obj_stingray_Actor.html)
- [Create and control a ragdoll](https://help.autodesk.com/cloudhelp/2021/ENU/Max-Interactive-Help/interactive_help/creating_gameplay/physics/create_import_ragdoll.html)
- [`World.link_unit`, `unlink_unit`, and `update_unit`](https://help.autodesk.com/cloudhelp/2019/ENU/Max-Interactive-Help/lua_ref/obj_stingray_World.html)

## Compiled artifact comparison

The comparison used the current built custom resource
`.build/ragdoll-analysis/custom/C58A3743D12FF52F.unit`, the extracted native
ratling resource at
`../_warlock_bombardier_art/vt2_extract_tree/units/beings/enemies/skaven_ratlinggunner/chr_skaven_ratlinggunner.unit`,
and the Bitsquid parser loaded by
`../vt2-pusfume/.build/compare_compiled_hierarchy.py`.

| Property | Custom Warlock visual | Native ratling carrier |
|---|---:|---:|
| Scene nodes | 142 | 235 |
| State-machine `.bones` | 138 | 106 |
| Skins | 1 | 17 |
| Unit actors | 0 | 32 |
| Physics-scene payload | 0 | 125,620 bytes |
| `root_point` | index 4, below wrappers | index 0, top-level |

All 138 custom `.bones` names already exist somewhere in the native ratling
scene graph. The custom visual therefore does not have unexplained
Bitsquid-created bones. The apparent 32-name difference over the ratling's 106
state-machine bones consists of the six intentional `*_scale` bones plus
native accessory/helper nodes. A `.bones` resource is only the subset selected
for a state machine; it is not the full scene graph
(`../_bitsquid_blender_tools/bitsquid/bones/import_compiled.py:12-18`).

The important incompatibility is rest space:

- custom scene nodes 0-2 are wrappers;
- its armature node is index 3 with world scale `(100, 100, 100)`;
- the current custom FBX has a 138-bone `armature object.008` and mesh object
  scale `0.01`;
- native `root_point` has scale 1 and no parent;
- custom `j_hips` local position is about
  `(-0.001730, 0.007580, 0.000036)`, while native `j_hips` local position is
  about `(-0.851529, -0.176265, 0)`;
- of 106 common state-machine bones, 83 local rest matrices differ and all 106
  world rest matrices differ.

Name equality is therefore necessary but insufficient. Raw source-local pose,
position, or scale copying crosses incompatible spaces.

This is also a quantitative explanation for v0.1.48, not just a qualitative
warning. The compiled custom `j_hips` rest position is approximately
`(-0.001730, 0.007580, 0.000036)` beneath the scale-100 parent. Copying the
native local hips position `(-0.851529, -0.176265, 0)` into that slot composes
to approximately `(-85.1532, -17.6268, -0.0003)` in world space: about
86.899 m away from the valid custom rest hips. That is sufficient to move the
skin out of view/bounds while arrows remain on the native carrier; deletion or
Less Corpses is not needed to explain the observation.

## What v0.1.49 proved

The `console-2026-08-11-18.18.25-aaa52359-6b5c-47f3-92da-ecff08edc1d8.log`
session loaded `v0.1.49-dev` and recorded 11 deaths:

- the build deliberately emitted `donor fallback visibility=true
  meshes=24/24 reason=death-underlay` on all 11 deaths;
- the visible ratling corpse was therefore the revealed native carrier, not a
  successful custom-model ragdoll;
- no solver explosion, sustained FPS collapse, or pose-driver lifetime stop
  was reported;
- `root_delta` stayed exactly 0, confirming only the existing root link;
- hips divergence was systematic:

| Checkpoint | Mean `hips_delta` | Maximum `hips_delta` |
|---:|---:|---:|
| frame 1 | 0.04 m | 0.07 m |
| frame 16 | 0.12 m | 0.19 m |
| frame 32 | 0.52 m | 0.71 m |
| frame 64 | 1.32 m | 1.683 m |

The old 5 m escape alarm was too permissive to detect this repeatable failure.
This build is a **physics pass / visual identity and pose fail**.

## Why the old telemetry observed the wrong phase

The old driver ran from the death reaction's entity update
(`scripts/mods/doomrocket/extensions/death_reactions.lua:658-660` and
`:686-688`). VT2 then performs the following order:

1. `StateIngame` runs entity systems
   (`Vermintide-2-Source-Code/scripts/game_state/state_ingame.lua:974-978`).
2. Boot subsequently calls `Managers.world:update`
   (`Vermintide-2-Source-Code/scripts/boot.lua:786-789`).
3. `ScriptWorld.update` evaluates world animations, runs safe animation
   callbacks, and then updates the scene
   (`Vermintide-2-Source-Code/foundation/scripts/util/script_world.lua:316-334`).

The outfit ASM was still enabled in animation bone mode `transform`.
Autodesk defines that mode as applying animation position, rotation, and scale
to bone nodes. The manual writes and their samples therefore occurred before a
later same-frame animation writer could replace them. Autodesk also states
that skinning and animation have no direct connection and that a skinned object
can exist without animation. Keeping the ASM active is not, by itself, proof
that a skin or its bounds will update.

Relevant primary documentation:

- [`Unit.set_animation_bone_mode`, state-machine enable/disable, bone LOD, and local transforms](https://help.autodesk.com/cloudhelp/2019/ENU/Max-Interactive-Help/lua_ref/obj_stingray_Unit.html)
- [Basic animation concepts: animation and skinning are independent](https://help.autodesk.com/cloudhelp/2019/ENU/Max-Interactive-Help/interactive_help/animation/basic_anim_concepts.html)

The native extensible place for this experiment is
`AnimationSystem.add_safe_animation_callback()`
(`Vermintide-2-Source-Code/scripts/entity_system/systems/animation/animation_system.lua:487-503`),
which `ScriptWorld` runs after animation evaluation and before scene update.
The callback queue is global, however, while `WorldManager` updates every
active world. A callback must not enqueue its successor from inside itself: it
could be drained again by another world in the same rendered frame. The
implementation instead hooks both `World.update_animations` variants, checks that
the updated world is exactly `Unit.world(carrier)`, and then enqueues one
one-shot callback for that owner's immediately following safe-callback phase.

## Offset-corrected post-animation implementation

The implementation keeps these controls fixed:

- native ratling physics only; custom unit has no actors or physics scene;
- root-only inter-unit link; no per-bone `World.link_unit` calls;
- native carrier meshes remain hidden through death;
- outfit ASM remains enabled to hold that v0.1.49 variable constant, while
  `Unit.set_animation_bone_mode(outfit, "ignore")` prevents it from writing
  bone nodes. This is an experimental control, not a claim that the ASM is
  required for skin rendering;
- all pose application and diagnostic sampling occur in a safe animation
  callback, after the carrier's specific world animation evaluation; the
  callback never self-reschedules;
- no raw source `local_pose`, local scale, or local position is copied into the
  custom hierarchy.

The conversion calibrates each common source/target pair in world space. With
VT2's row-vector multiplication convention, let `S0` be the rigid source world
pose at calibration, `St` the current rigid source world pose, `T0` the target
world pose at calibration, and `PdesiredW` the target parent's desired world
pose:

    D = inverse(rigid(S0)) * rigid(St)
    TdesiredW = T0 * D
    Ldesired = TdesiredW * inverse(PdesiredW)

The row-vector convention is demonstrated by
`Vermintide-2-Source-Code/scripts/flow/flow_callbacks.lua:827-830`; VT2's own
world-to-local conversion is at
`scripts/unit_extensions/generic/tentacle_spline_extension.lua:1049-1053`.

`rigid()` removes source scale. The implementation stores `S0` and `T0` in
`Matrix4x4Box` values rather than retaining temporary engine matrices. For
child bones, it preserves the calibrated custom local translation and scale
and applies only the rotation derived from `Ldesired`. The hips position is
derived through the inverse desired target-parent world pose, so the inverse
parent cancels the custom scale-100 wrapper. No target scale is written;
ordinary child bones remain rotation-only.

The existing bridge array is not parent-first: for example, arm scale entries
precede their arm parents and tail scale precedes appended tail nodes
(`scripts/mods/doomrocket/breeds/skaven_doomrocket_inventory.lua:37-45` and
`:83-154`). An implementation must topologically order mapped nodes or compute
all desired parent world poses independently. Array order is not a hierarchy.

### Complete calibration preflight

Calibration is rejected before event mirroring, animation ownership,
visibility, or driver registries change unless all of these conditions hold:

- every named source and target passes `Unit.has_node` before `Unit.node`;
- targets are unique, the filtered map is exactly 90 nodes, and `j_hips`
  exists on both units and appears exactly once in the mapping;
- every rigid `S0` is finite and invertible before `Matrix4x4.inverse`, and its
  resulting inverse is finite;
- every `T0` is finite and invertible, and every retained target-local position
  and retained target-local scale is finite;
- every unmapped target-parent local pose needed by recursive world resolution
  is finite and invertible.

The invertibility predicate rejects both tiny axes and a scale-normalized
scalar triple product at or below the configured epsilon. This detects
collinear and near-collinear bases that three nonzero axis lengths alone do not.
Any rejection produces a keyed `phase=stop` with zero callbacks and leaves the
living visual path intact.

The same predicate guards each per-frame `desired_local` before
`Matrix4x4.rotation`. A merely finite but singular basis must not reach
quaternion extraction.

### Persistent sleep/wake lifecycle

The five-second constant is only the telemetry window. The hardened driver
stays in the strong active set until its owner or outfit is deleted, or until
`StateIngame` exit, mod disable, or mod unload invalidates every driver and
clears the weak registries. Already queued callbacks check the stopped flag and
do nothing after reset.

During the monitor window the owner-world hook must queue and execute pose
transfer on every callback, even when an actor reports sleeping, preserving all
seven checkpoints and the visible/native correlation. Actor enumeration,
sleep-state caching, and sleep-based suppression are forbidden until
`monitor_complete`. After that record, the implementation may enumerate the
carrier's actual physics scene with zero-based indices
`0..Unit.num_actors(carrier)-1`, cache actors for which `Actor.is_dynamic` is
true, and skip the 90-bone pose calculation and `World.update_unit` while all of
them sleep. It keeps testing the cached actors from the carrier-world animation
hook and resumes on the first wake. Physics actor names are not assumed to
match deform-bone names. Finding no dynamic actors after monitor completion is
treated as awake and retried.

v0.1.51 violated this ordering rule. It consulted and cached transition-time
actors before monitor completion, allowing an apparently sleeping actor set to
suppress the pose transfer while the actual native ragdoll advanced. The
v0.1.52 moved the entire sleep optimization behind `monitor_complete`.
v0.1.53 retains that ordering and additionally makes every skipped/write
callback observable; the change remains runtime-unvalidated.

The zero-based range follows VT2's complete-enumeration code in
`foundation/scripts/util/script_unit.lua:146-149`,
`scripts/managers/game_mode/game_mode_manager.lua:500-504`, and
`scripts/imgui/imgui_physgun.lua:220-221`. Starting at one would omit actor 0
and probe the invalid index `num_actors`.

Elapsed lifetime and checkpoints use `Managers.time:time("game")`; pausing the
game therefore does not finish the monitor. `Application.time_since_launch()`
is retained only for performance measurement. Each sample logs the maximum
wall-clock callback gap accumulated since the prior checkpoint, then resets
that accumulator. This catches an intervening one-frame stall that a final-gap
sample would miss.

### Fail-closed carrier visibility

The carrier is tracked only after all reported meshes have been hidden. A
later `Unit.set_mesh_visibility(..., true)` attempt increments keyed telemetry
and is passed to the engine as `false`. A whole-unit `true` write is also
logged, then all carrier meshes are synchronously re-hidden before the hook
returns. These hooks prevent known Lua-level ratling substitutions. They cannot
observe engine-internal render state, skin culling, or whether the Warlock
pixels are actually correct, so runtime video remains a hard gate.

## What v0.1.50 proved

The
`console-2026-08-12-02.22.45-73b986c9-2cbf-463e-8bdf-ba8f8ef99f3e.log`
session loaded v0.1.50-dev and produced a clean analyzer result:

- 11 unique `source=unit` corpses, 99 correlated records;
- seven samples per corpse through 5.001–5.015 s and normal
  `monitor_complete` stops;
- both owner and outfit alive at every sample;
- zero custom actors, carrier reveals, parent mismatches, scale mutations, and
  non-hips translation mutations;
- maximum hips drift 0.133 m, maximum bone-radius ratio 1.469×, and largest
  checkpoint-adjacent callback gap 19.6 ms;
- no assertion, invalid-matrix stop, or solver anomaly was observed.

This passes five seconds of host transform and unit-lifetime telemetry for the
tested code. It does not validate every hardening feature described above: in
the uploaded v0.1.50 build, `monitor_complete` also stopped the pose driver and
`wall_gap_ms` represented the immediately preceding sampled gap rather than an
interval maximum. The persistent post-monitor driver, sleep/wake resumption,
game-time pause behavior, worst-gap accumulation, complete calibration
preflight, and fail-closed visibility hooks need a new, uniquely versioned
runtime pass. The log also cannot prove rendered model identity or texture
appearance, and every trace is `source=unit`; remote-client `source=husk`
remains untested.

## What v0.1.51 disproved

The
`console-2026-08-12-22.42.49-d1eaa659-0dcc-4c1d-bebd-1789887d36d9.log`
session loaded v0.1.51-dev and produced one complete host `source=unit` trace.
It failed the analyzer with 15 threshold violations:

- at 250 ms, hips drift was 0.558 m and anchor drift was 1.200 m;
- at 1 s, hips drift was 2.428 m;
- at 5 s, hips drift was 2.505 m and anchor drift was 3.567 m;
- the normal `monitor_complete` record still reported 602 callbacks.

This was not the old physics explosion or deformation signature. The largest
recorded wall gap was only 11.1 ms; `root_delta` stayed zero; the bone-radius
ratio stayed approximately 0.998; and custom actors, carrier reveals, parent
mismatches, scale mutations, and non-hips translation mutations all stayed
zero. The visual skeleton was effectively frozen at handoff while the native
carrier pose moved away. Source review ties that signature to the pre-monitor
sleep cache/suppression added in v0.1.51.

v0.1.52 was only an uncaptured fix candidate. v0.1.53 retains its transfer
ordering and rejects a trace unless every pre-monitor callback wrote the pose
and no sleep skip occurred. That ordering subsequently passed host captures in
v0.1.53, v0.1.54, and v0.1.55; static coverage alone still cannot establish a
new build's runtime success.

Historical v0.1.50 evidence outside the ragdoll result included three material
lookup warnings before each later runtime material assignment; all 11
assignments nevertheless reported 5/5 slots and 8/8 textures resident. Those
specific Doomrocket material warnings were not reproduced in v0.1.55, whose 20
assignments reported 5/5 slots and 6/6 custom textures resident. Residency logs
still cannot prove UVs, channel packing, or final appearance; v0.1.55 has a
separate user visual approval for those pixels. Bestiary continues to emit a
missing `kills_per_breed_difficulty_skaven_doomrocket_normal` stat error on
initiating kills; telemetry continues normally, so that is a separate
integration bug.

## Runtime acceptance gates

Use a fresh game restart and require the exact uniquely bumped tested-build
`[doomrocket:LOAD]` banner. The accepted host MVP is `v0.1.55-dev`; v0.1.50 is
only the original baseline, v0.1.51 is the known pre-monitor sleep-suppression
failure, and v0.1.52 is the uncaptured predecessor without the final counter
gate.
Accept only when both runtime visuals and post-animation logs agree:

- at least 10 valid non-gibbing deaths, including single deaths, multiple rapid
  deaths, and sloped/stair geometry;
- every visible corpse retains the Warlock body, armor, and backpack; a ratling
  corpse is an automatic failure even if physics is stable;
- carrier mesh visibility remains false and the custom outfit remains alive
  and visible;
- telemetry includes a unique driver id and `unit`/`husk` source so concurrent
  corpses cannot be mixed;
- post-animation samples at 0, 100, 250, 500, 1000, 2000, and 5000 ms remain
  finite, appear exactly once, contain `nodes=90`, and remain monotonically
  attributable to the same corpse id;
- hips drift from its calibrated beginning remains at or below 0.25 m and does
  not trend upward across checkpoints;
- every `wall_gap_ms` is the accumulated interval maximum and stays at or below
  250 ms;
- `reason=monitor_complete` is the expected telemetry stop while both units are
  alive; no earlier error stop is allowed, and that record must not remove the
  internal pose driver;
- after five seconds, let the corpse settle, wake it with a normal physics
  interaction, and confirm the Warlock visual remains attached and updates;
- pausing does not consume the game-time observation window;
- no stick figure, extreme scale, roof launch, unrelated-physics corruption,
  or sustained FPS collapse;
- ordinary corpse cleanup still occurs, and leaving `StateIngame` produces no
  stale-driver callback or reload error.

Video confirms visual identity and pose. Logs confirm writer timing, unit
lifetime, visibility, and bounded error. Neither evidence class substitutes
for the other.

## Secondary culling experiment

The custom unit currently uses `culling = "bounding_volume"`
(`units/warlock_bombardier/warlock_bombardier_3p.unit:9-18`). Autodesk documents
mesh-bounds culling and a disabled mode in the
[Unit Editor](https://help.autodesk.com/cloudhelp/2021/ENU/Max-Interactive-Help/interactive_help/getting_started/common_windows/unit_editor.html).
The recovered compiled mesh resource contains an authored bounding volume.

No source proves that the outfit ASM updates that bound, or that culling caused
the v0.1.48 disappearance. If a future build produces bounded, correct pose
telemetry but remains visually absent, make a separate build that
changes only culling. Do not mix that A/B test with pose, physics, material, or
visibility changes.
