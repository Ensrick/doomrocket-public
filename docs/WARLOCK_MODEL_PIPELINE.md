# Warlock Bombardier model pipeline

How Crunch's Warlock Engineer model ships as the doomrocket enemy, what broke
along the way, and the invariants that keep it working. Companion tooling:
`tools/splice_warlock_materials.ps1`, `tools/Test-WarlockPipeline.ps1`.
The reusable authoring procedure is in `docs/HOW_TO_CREATE_A_VT2_RAGDOLL.md`.
Detailed forensic research remains in
`docs/research/RAGDOLL_VISUAL_HANDOFF.md`. The authoritative texture/channel,
UV, native-donor, and conversion contract is in
`docs/research/WARLOCK_TEXTURE_PIPELINE.md`. The rigid launcher attachment,
root-space export, projectile, and death-drop contract is in
`docs/research/WARLOCK_WEAPON_PIPELINE.md`.

## The proven living-visual contract (v0.1.22 baseline, user-confirmed in-game)

1. **Mesh**: 4 meshes joined (`g_body_lod0`, `g_fur_lod0`,
   `SM_Skaven_WarlockBombardier_Armor`, `_Backpack`; 29,123 verts), 5 material
   slots, on the 138-bone `armature object.008` rig. The rig was authored to
   fit the gun rat's existing animation set.
   `g_stormvermin_armor_lod0` is donor-scene scaffolding - never export it.
   The current `warlock_bombardier_3p.bones` contains exactly 138 names. The
   old `units/bombadier/bombadier.bones` contains 139; its only additional name
   is `camera_attach`. This is not evidence of Blender inventing bones.
2. **FBX for the DCC importer** must:
   - come from the `prepare_pusfume_fbx.py` round-trip (weights pruned to 4
     deform influences, renormalized to 1.0);
   - have the mesh object transform APPLIED (donor meshes are cm-space data
     with 0.01 object scale; the armature is meters - Stingray bind matrices
     cannot straddle the two spaces);
   - carry a BAKED animation take (`bake_anim=True`, all bones) - a bind-pose
     FBX compiles without the animated character activation group and renders
     rigid forever.
3. **Unit sources**: same-name `.unit` (own `animation_state_machine` path) +
   `.bones` + `.dcc_asset` + `.state_machine` (bones = own unit path) +
   `anims/*.fbx` clips with `.animation` sidecars (bones = own unit path).
4. **Materials**: the five boot-package `materials/warlock_bombardier/wb_*`
   are SDK compiles and render RIGID and dark - they are placeholders. The
   real bindings are game child-material payloads spliced over
   `child_materials/warlock_bombardier/wb_*_child` in
   `resource_packages/doomrocket/warlock_child.package`, which is absent from
   `doomrocket.mod`'s packages list and loaded at runtime via
   `mod:load_package` after the Ratling armor and Stormvermin body donor
   packages are resident.
   `hooks.lua` swaps each slot via `Unit.set_material` per spawn.
5. **Living driving**: root-only link (`AttachmentNodeLinking.doomrocket_warlock_root`)
   + `Unit.set_animation_bone_mode("transform")` + `Unit.set_bones_lod(0)` +
   own state machine enabled + explicit `idle` event. The rat's
   name-based `Unit.animation_event` calls are mirrored onto the outfit
   (`mod._warlock_outfits`); events the outfit's state machine lacks are
   skipped. Raw variable and constraint indices are deliberately **not**
   mirrored because indices are state-machine-local and forwarding them caused
   native animation assertions in earlier builds.
6. **Carrier identity**: the gameplay unit is a native **ratling gunner** clone
   (`Breeds.skaven_doomrocket = table.clone(Breeds.skaven_ratling_gunner)`).
   Its render meshes are hidden while alive, but its native unit, actors,
   animation controller, and ragdoll remain the authoritative gameplay and
   physics carrier. The separate 138-bone Warlock unit is the visible overlay.
   References to a "stormvermin donor" elsewhere in the history describe rig
   ancestry or an abandoned v0.1.31-35 experiment, not the current carrier.

## Ship procedure

Clean `VMBLauncher build` -> `tools/splice_warlock_materials.ps1` ->
`tools/Test-WarlockPipeline.ps1` -> local `deploy --no-remote` -> `upload` ->
verify the fresh Workshop log and deployed hashes -> git commit+push. NEVER
`vmblauncher all` (it would upload the unspliced bundle). Use the known
headless v0.5.6 launcher and Doomrocket-specific configuration; the exact
commands and publication checks are authoritative in
`docs/research/WARLOCK_WEAPON_PIPELINE.md`.

## Failure ledger

| Build | Symptom | Root cause | Rule derived |
|---|---|---|---|
| v0.1.9-13 | Floating armor, no wearer | Name-filtered export dropped 3 of 5 rig meshes; model is self-contained | Export the full rig mesh set |
| v0.1.15 | Vanilla stormvermin armor clipping Crunch's armor | `g_stormvermin_armor_lod0` is donor-scene scenery, wrongly joined in | 4 meshes, never the scaffold |
| <=v0.1.15 | Rigid mesh + uniform darkness | Mod SDK cannot compile the character-skinning shader permutation; static FBX lacked the animated activation group | Splice game child materials; bake a take into the FBX |
| v0.1.16 | CRASH at boot, `PatchedResourcePackage::flush`, first spliced material | Spliced children rode the boot-flushed main package | Spliced children live ONLY in the runtime-loaded child package |
| v0.1.18 | Animated stick figure | (compound; see .19/.20 - and ultimately .21) | - |
| v0.1.19 | Stick figure persists | Weight theory (normalize across non-deform groups) fixed a real defect but was not the operative cause | Animated export starts from the cleaned round-trip FBX regardless |
| v0.1.20 | Stick figure persists | Scale theory (cm mesh / m armature) fixed a real defect but was not the operative cause | transform_apply the mesh before export regardless |
| v0.1.21/22 | CORRECT deformation | Own-ASM driving works | Self-animation is a valid mode |
| v0.1.23 | Stick figure again (bridge retry with bone-mode calls) | ~~"link driving never reaches the skin"~~ STRUCK - disproven by v0.1.28. Retro-diagnosis: unlinked scale bones + possible weight/scale defects of that era's compile | Link driving works; see the v0.1.36 scale-bone finding (docs/research/SCALE_BONES_FINDING.md) |
| v0.1.24 | CRASH ~0.2s after spawn, `AnimationBlender Layer 0 / LayerState 1`, no Lua stack | Vanilla state machine on a mod-compiled skeleton: `Unit.set_animation_state_machine` SUCCEEDS, then the blender asserts on evaluation - pcall cannot catch it | NEVER point a mod skeleton at a vanilla state machine |
| v0.1.25 | CRASH in aim_system update, Lua stack ends in our `animation_set_constraint_target` mirror (index 0, aim-target Vector3) | Raw variable/constraint indices are only meaningful within ONE compiled state machine; forwarding them to a unit on a different SM is an engine assert - the pcall wrapper caught nothing | Mirror animation state by NAME only (events gated on `has_animation_event`); never by raw index |
| v0.1.27 | CRASH at spawn, stack in the event mirror: vanilla `_setup_configuration` fires `anim_state_event "idle"` on the rat, mirror forwards to the outfit | Firing an animation event into a DISABLED state machine is an engine assert; bridge mode disables the outfit ASM but left the mirror registered | Event mirroring exists only for the enabled-own-SM mode; bridge mode never registers the outfit |
| v0.1.28 | Bridge DRIVES the model but limbs stretch compounding with chain depth | Donor was the RATLING body; Crunch's rig is stormvermin-family - differently-proportioned skeleton driving a mismatched bind | The donor's skeleton family must match the rig (stormvermin) |
| v0.1.29 | Same compile invisible under its own idle | Blender re-export of Dalo's armature scale conventions double-converts for self-evaluation (renders ~1/100) | Bridge-driven use only for the Dalo-convention compile |
| v0.1.31 | CRASH: `generic_hit_reaction_extension.lua:218`, nil health_extension on the donor | Breed `hit_zones` name UNIT ACTORS; the ratling clone's zones didn't match the new stormvermin body, health-extension init failed | Body-coupled breed tables (hit_zones, hitbox_ragdoll_translation, ragdoll_actor_thickness) must come from the donor body's breed |
| v0.1.32 | CRASH at spawn in GenericUnitAimExtension init | `Unit.animation_find_constraint_target(unit, "aim_target")` asserts on the stormvermin machine (no aim constraint - stormvermin never aim) | Aim template must not touch constraints unless the machine has them |
| v0.1.33 | Pile of bare idle-posed stormvermin ("million copies") | `hooks.lua:164` called a file-local declared BELOW the hook -> nil global -> every spawn attempt errored, et quarantined the tick, director retried forever | Fully qualify engine calls or declare locals above every use (late-local lint class) |
| v0.1.34 | Raw NATIVE crash (no Error Context, no Lua stack) moments after spawn | Ratling state machine bound to the stormvermin skeleton - clips animate gun bones the skeleton lacks | Cross-skeleton SM binding is fatal in EVERY direction (v0.1.24 mod->vanilla, v0.1.34 vanilla->vanilla). Machines only ever run on the skeleton they were compiled against |
| v0.1.35 | Deformed abomination (stormvermin donor, own SM) | cm-convention compile under bridge driving | (see v0.1.36 close-out) |
| v0.1.36 | STILL deformed with all six scale bones linked + ratling donor | Ran on the cm compile (v0.1.29-proven internally inconsistent); but this completes the matrix: 2 compiles x 2 donors x scale-links on/off - every cell deformed | **BRIDGE LANE CLOSED.** The engine's linked-skinning bind space is not producible from Blender FBX export. Self-anim (v0.1.22, the only user-confirmed-correct config) is the architecture; gun-rat clips arrive via the Bitsquid compiled-animation importer onto OUR skeleton |
| v0.1.40 | Ragdoll deformed terribly, stretched wildly, FPS < 1 | Physics solver explosion. Suspects, in order: scene actors dynamic AT SPAWN fighting the animation (serialized eKINEMATIC possibly not honored on instantiation); near-zero inertia tensors on small bones (tails ~8e-5) destabilizing the joint chain; no joint projection so error compounds unboundedly (giant polygons = fill-rate death) | v0.1.41 counters all three: spawn audit force-kinematics all 29 actors (+ prints [doomrocket:RAGDOLL] found/created), inertia floor 0.01 + heavier extremity masses, D6 ePROJECTION 0.05m/0.5rad, solver 16/4. Await the audit line from the next run |
| v0.1.43 | Kinematic-at-spawn held while alive, but death still corrupted the skeleton with a 1-1.6 s physics stall | The owner's death event was mirrored into the outfit BEFORE the delayed handoff; the outfit's SM ragdoll state flipped its actors dynamic internally, so the custom scene still fought the engine at death | v0.1.44 removes the custom PhysX scene and the SM ragdoll layer entirely - the authored-scene lane is closed for ragdoll |
| v0.1.44 | Native-carrier attempt: linking the 97 target bones independently with World.link_unit recreated the "stick figure" | Per-bone World.link_unit destroys this Blender-built mesh's local scene-graph hierarchy (same class as the closed bridge lane) | Keep the root-only attachment and intact custom hierarchy; never independently re-link its bones. Later builds also proved raw local-pose copying invalid |
| v0.1.45/46 | (design, [untested]) | Death handoff = vanilla-carrier pose copy: `_prepare_warlock_death` runs BEFORE ai_extension:die, removes the mirror entry, disables the outfit ASM, builds owner->outfit node pairs from `AttachmentNodeLinking.doomrocket_warlock_bridge` (skipping root); the death reaction copies each carrier LOCAL pose per frame (`_update_warlock_death_pose`) while the OWNER'S native ratling ragdoll does the physics. Diagnostics: `[doomrocket:RAGDOLL] <src> pre-event local-pose carrier active: nodes=N custom_physics=absent` | This is the runtime analogue of the parent-relative retarget that made v0.1.39's living animations work |
| v0.1.47 (tested) | Ragdoll = giant stretched mess flying skyward, but NO framerate loss (2026-08-04, host + client logs agree; carrier armed cleanly, nodes=96, both peers) | The v0.1.45 raw `Unit.local_pose` copy is the closed v0.1.28 bridge failure resurrected at death: the ratling carrier's local matrices carry ITS bone translations and its animated proportion SCALE (the bridge maps the `*_scale` bones), compounding multiplicatively down every chain on Crunch's hierarchy. No fps loss because no physics is involved - pure render deformation | v0.1.48: ROTATION-ONLY retarget (`Unit.set_local_rotation` per mapped bone - bone lengths/proportions stay at Crunch's bind, stretch impossible by construction), j_hips alone also copies local translation (root-relative, no chain) so the corpse falls; `*_scale` + `aim_target` excluded. Diagnostic line now `rotation carrier active: nodes=N scale/aim_excluded=K` |
| v0.1.48 (tested) | Six clean deaths with Less Corpses absent and corpse limit 70: the visible Warlock outfit vanished, while embedded longbow arrows remained suspended on the native carrier corpse; no FPS or solver failure | Raw native hips local position was copied under the custom scale-100 parent. Compiled-rest composition places the custom hips about 86.899 m from its valid rest position, fully explaining an out-of-view/bounds skin without deletion. ASM disable may also affect the experimental render path, but is not needed for this displacement | Never copy source-local translations across these rigs. Convert calibrated world motion back through the target parent's inverse; test culling separately only if bounded pose telemetry passes |
| v0.1.49 (tested, 2026-08-11) | The corpse looked like a ratling gunner because the build deliberately revealed all 24 native carrier meshes on all 11 deaths. Physics stayed stable, but the Warlock overlay did not follow: `root_delta` stayed 0 while mean/max `hips_delta` grew from 0.04/0.07 m at frame 1 to 1.32/1.683 m at frame 64 | The visible corpse was a fallback underlay, not the Warlock model. The pose driver wrote during entity update, before the same frame's world animation evaluation; the still-enabled outfit ASM in `transform` mode could write the bones afterward. Direct carrier/outfit local transforms are also not interchangeable because the compiled custom rig has a scale-100 wrapper and different rest matrices | Never expose the carrier as a substitute corpse. Drive the custom visual after animation evaluation, block animation bone writes, and convert through calibrated world/rest space. This replacement is a candidate until runtime video **and** post-animation logs pass. Tested ManifestID: `8847975153665526573` |
| v0.1.50 (host baseline passed 2026-08-12) | Hidden native ratling remains the sole physics owner; custom outfit captures its final living world/rest calibration in death `pre_start`, switches to bone mode `ignore`, and receives a topology-ordered world-delta/local-parent conversion once per carrier-world animation frame. Five-second per-corpse telemetry has unique unit/husk IDs | 11/11 host corpses completed seven checkpoints through 5 s with both units alive. Maximum hips drift 0.133 m, bone-radius ratio 1.469×, and largest checkpoint-adjacent callback gap 19.6 ms; zero carrier reveals, custom actors, parent changes, scale changes, non-hips translations, assertions, or solver anomalies | Passed the original five-second host transform/lifetime lane. That build stopped pose driving at monitor completion and did not accumulate the interval's worst gap, so it did not validate persistent corpse lifetime or hitch detection. Visual identity and remote-client `source=husk` also remain untested. Workshop item `3771657344`, ManifestID `2137195637454965122` |
| v0.1.51-dev hardening (runtime failed 2026-08-12) | The first host death began normally with 90 mapped nodes, then the custom visual stopped following the native carrier. At 5 s, `hips_drift=2.505` m and `anchor_max_drift=3.567` m despite 602 callbacks. `root_delta=0`, bone-radius ratio stayed about 0.998, mutations/reveals/custom actors stayed zero, and the largest wall gap was only 11.1 ms: this was pose suppression, not deformation, solver instability, or a performance stall | The new sleep optimization ran before `monitor_complete`, cached/interpreted transition-time dynamic actors as sleeping, and suppressed the 90-bone transfer while the native ragdoll continued moving | Sleep detection, actor caching, and pose-write suppression are forbidden during the complete 0–5000 ms monitor. Log: `console-2026-08-12-22.42.49-d1eaa659-0dcc-4c1d-bebd-1789887d36d9.log`; Workshop ManifestID `813553378698087677` |
| v0.1.52-dev fix candidate (uploaded; runtime pending) | Preserve the v0.1.51 preflight, lifecycle, visibility, and telemetry hardening, but force pose transfer on every owner-world callback until `monitor_complete`. Discover and consult native dynamic actors only after the monitor has closed | This restores the proven v0.1.50 behavior during the acceptance window while retaining post-monitor sleep/wake optimization. Clean build, exact material splice, full pipeline, ragdoll regressions, and 17 texture tests passed | Friends-only Workshop item `3771657344`, ManifestID `2963729984774018388`. Static and mutation tests are necessary but insufficient. Do not claim runtime success until a uniquely versioned v0.1.52 host log and visual test pass; remote-client `source=husk` and post-monitor wake remain required |
| v0.1.53-dev (host body passed; weapon drop failed) | Carries the v0.1.52 sleep-order fix forward and logs `pose_writes` plus `sleep_skips` at every checkpoint/stop. Replaces the Dalo placeholder launcher and projectile geometry with Crunch's final set-03/set-04 meshes and texture inputs | Four host corpses passed the complete body gate: `callbacks=pose_writes`, zero sleep skips, and hips drift below 0.25 m. The loaded `pRocket` nevertheless floated after death because it was a sibling of the physics-owned `pRocketLauncher`; `rp_dropped` moved only the launcher subtree | Body result is accepted for the host lane. Weapon-drop hierarchy failed visually even though the engine emitted no actor error. Log: `console-2026-08-13-00.17.18-321ad4fb-ba9c-4073-b9df-bd5394b1b3d1.log`; ManifestID `7981237903583458691` |
| v0.1.54-dev (host body/drop passed; launcher placement failed) | Kept the v0.1.53 body implementation unchanged and parented loaded `pRocket` beneath actor-owned `pRocketLauncher` without adding a second body | Three host deaths passed with `callbacks=pose_writes=602`, zero sleep skips, and at most 0.058 m hips drift; the tester confirmed launcher and warhead fell together. The replacement launcher nevertheless floated away from both hand and back because the exporter baked an inverse character-hand transform into unrigged prop geometry | Ragdoll/drop result accepted for the host lane. Placement rejected. Log: `console-2026-08-13-01.15.59-7009c335-e195-4768-8c49-a99e37659f53.log`; ManifestID `3649786646933166566` |
| v0.1.55-dev (host MVP accepted) | Preserves the accepted body and drop hierarchy. Removes the inverse-hand bake, retains the verified object rotation, translates the final launcher's semantic pistol-grip cap into the SHA-pinned legacy weapon frame, and excludes the exact 1,608-vertex unrigged backpack tether from the rigid gun | Source and compiled gates cover the reviewed 3,308/1,608 split, canonical and signed direction, origin/surface proximity, the unique 217-vertex grip landmark, exact runtime nodes, and loaded-warhead actor closure. The complete pipeline passed after a clean build and native-material splice. The user then confirmed the final weapon placement/appearance, loaded death drop, and visible corpse in game | Public Workshop item `3771657344`, ManifestID `6225347386542634141`, Git commit `90f2c53`. The latest log has 20 complete host traces with `callbacks=pose_writes`, zero sleep skips, and 20 resident-material summaries. Its first six ordinary traces meet every analyzer threshold; a separate fourteen-corpse overlap stress batch has transient early anchor excursions but settles by one second. Remote `source=husk` and explicit post-monitor wake/cleanup remain uncaptured; the flexible tether, separate short conduit, and chimney particles remain deferred |
| v0.1.47 | User report "No ragdoll" (2026-08-03) was a STALE BUILD: the 22:21 session log shows `[doomrocket:LOAD] v0.1.41-dev` + the v0.1.41 spawn-audit line | v0.1.42-46 were deployed locally but NEVER uploaded; the user's Steam restart (pulling an unrelated gt update) re-synced item 3771657344 back to the 07-27 v0.1.41 manifest - the exact clobber class in `feedback_local_deploy_clobbered_must_upload` | v0.1.47-dev republishes the current tree (identical code to v0.1.46 + version/title bump), upload log-confirmed ManifestID 3747860009260434476. NOTE: launcher v0.5.7+ refuses direct `upload` (publication receipt required); the out-of-monorepo doomrocket flow uses the v0.5.6 baseline binary `vmb-launcher-baseline-056-20260726` |

## Uncatchable crash classes (pcall is useless)

- Boot-flushing a spliced child material (`PatchedResourcePackage::flush`).
- Vanilla state machine / clips evaluated against a mod-compiled skeleton
  (`AnimationBlender` assert, delayed ~1 frame after a successful-looking call).
- `Unit.animation_set_variable` / `animation_set_constraint_target` with an
  index from a DIFFERENT state machine (indices are per-compiled-SM; the
  pcall wrapper around the call catches nothing).
- `Unit.node()` on a missing node (why the old bridge pruned via
  `Unit.has_node`).

## Current native-carrier visual handoff (v0.1.55 host MVP accepted; client pending)

The hidden native ratling unit owns the ragdoll, and the custom Warlock unit
owns no physics. The core carrier-to-visual transfer has a v0.1.50 host
baseline. v0.1.51 then proved that lifecycle hardening can regress that transfer
if sleep state is consulted during the transition: its visual accumulated
2.505 m of hips drift while the callback continued normally. v0.1.52 introduced
the ordering fix but received no runtime capture. v0.1.53 carried it forward
with counter-complete telemetry and passed four host deaths; v0.1.54 passed
three more and corrected the loaded-warhead drop. v0.1.55 preserves that body
path and is user-confirmed visually with the corrected final launcher. Its
latest log contains 20 complete host traces: every callback wrote a pose, no
sleep callback was skipped, and both units remained alive through every
five-second monitor. The first six ordinary traces meet all strict analyzer
thresholds. The following fourteen-corpses-at-once overlap stress batch has
transient anchor excursions at 250/500 ms, so the combined log is stress
evidence rather than a clean whole-file analyzer pass; every trace is back
within the anchor gate by one second. Remote-client and explicit post-monitor
wake/cleanup coverage remain pending. Offline parsing of the compiled resources
found:

- custom: 142 scene nodes, 138 state-machine bones, 1 skin, 0 actors and no
  physics scene;
- native ratling: 235 scene nodes, 106 state-machine bones, 17 skins, 32
  actors and a 125,620-byte native physics scene;
- all 138 custom bone names already exist in the ratling scene graph, so name
  absence and importer-created bones are not the issue;
- the custom unit has three wrapper nodes, then an armature node at index 3
  with world scale `(100, 100, 100)`, then `root_point` at index 4. Native
  `root_point` is top-level index 0 at scale 1. Of 106 common state-machine
  bones, 83 local rest matrices differ and all 106 world rest matrices differ.

The implementation therefore does **not** copy raw source-local matrices. It
preflights every named node before `Unit.node`, enforces one unique hips pair
and exactly 90 mapped nodes, validates finite/invertible calibration and parent
matrices before inversion or state changes, and rejects near-collinear bases
with a scale-normalized triple-product test. It keeps the carrier hidden,
leaves the outfit ASM enabled but changes its animation bone mode to `ignore`,
schedules the copy with
`AnimationSystem.add_safe_animation_callback()` (after world animation and
before scene update), applies calibrated world-space rotation deltas, and
derives the desired hips local pose through the inverse desired target-parent
world pose.

The strong driver persists after the five-second monitor closes. Before
`monitor_complete`, every owner-world callback must transfer the pose: actor
discovery, sleep-state caching, and sleep-based suppression are forbidden.
Only after monitor completion may the driver skip pose writes while all cached
native dynamic actors sleep and queue again when any actor wakes. It is removed
only when either unit dies or on explicit state/mod teardown. Checkpoints use
game time, while wall-clock callback gaps are accumulated as the worst gap
between samples. Mesh reveal attempts are changed to `false`; whole-unit reveal
attempts are followed by a complete carrier-mesh re-hide. v0.1.55 has passed the
observed host visual/MVP lane; explicit post-monitor wake/cleanup, pause, and
remote-client `source=husk` coverage remain required before claiming those
broader lanes. See `docs/HOW_TO_CREATE_A_VT2_RAGDOLL.md` for the practical
procedure and `docs/research/RAGDOLL_VISUAL_HANDOFF.md` for the forensic
derivation.

AnimationSystem's safe-callback queue is global, while ScriptWorld drains it
for every active world. The callback is therefore one-shot and never queues
itself. Hooks on both `World.update_animations` variants enqueue it only after
the carrier's own `Unit.world` animation pass, producing one transfer/sample
per carrier-world frame before that world's scene update.

## MILESTONE - v0.1.39 USER-CONFIRMED IN-GAME (2026-07-27)

"This seems to work... it works." Crunch's model, gun-rat animation set,
self-animated on its own skeleton, driven by mirrored AI events. The full
recipe: extract compiled clips -> Bitsquid PARSER only -> custom
parent-relative applier (basis = rest_local^-1 @ engine_local) -> strip
scale/helper/weapon-bone curves, keep root_point -> bake to Crunch's rig ->
render-verify -> export via the proven FBX pipeline -> state machine over the
ratling event vocabulary -> event mirror at runtime.

Remaining at that milestone: no ragdoll on death (the later v0.1.40 authored
physics lane failed and was removed), and the texture pass (Crunch's full material masters - 4 sets of
BC/NR/MASE/E incl. warpstone emissive - arrived 2026-07-26; current spliced
setup predates them).

## Historical ragdoll experiment (v0.1.40-dev) - authored PhysX scene, no Maya

Vanilla character ragdolls are NOT unit-editor actors: the ratling's 32
ActorResource entries are c_* hit capsules (template keyframed_no_collision);
the ragdoll bodies are j_*-named rigid dynamics inside the unit's
`physics_scene_data` (cooked PhysX 4.1.1 SEBD binary, 125 KB), which the SDK
docs say comes from a Maya-exported PhysX XML renamed `<unit>.physx` next to
the .unit. The SM references those actors by bone name in a `ragdolls` block;
ragdoll states live on their own layer.

What shipped (all offline-verified against the compiled bundle):

1. `warlock_bombardier_3p.physx` - GENERATED RepX XML
   (scratchpad gen_physx.py): 29 kinematic PxRigidDynamic named j_hips ...
   j_backpack (capsules along +X = the Stingray bone axis, radii transferred
   from the ratling's same-suffix hit capsules, lengths from OUR bind pose,
   bind poses in world METERS from the compiled unit's scene graph -
   decompose rotation+translation ONLY, the cm-convention compile bakes
   scale=100 into every node matrix) + 28 PxD6Joints (linear locked,
   twist/swing eLIMITED per joint category, joint X = child bone axis).
   The mod SDK compiler cooks it automatically when the file sits next to
   the .unit (RepXCompiler + core/physx_metadata, PhysX 4.1.1): compiled
   unit gained a 57 KB SEBD physics_scene_data.
2. `.state_machine` additions - SOURCE SYNTAX (discovered empirically, the
   compiler silently ignores wrong keys):
   `ragdolls = { ragdoll = { actors = [ "j_hips" ... ] keyframed = [] } }`
   ("actors" is the dynamic list key - "dynamic" is silently dropped), plus
   a second layer: default `ragdolls/empty` (state_type "empty", transition
   on event "ragdoll") -> `ragdolls/ragdoll` (state_type "ragdoll",
   `ragdoll = "ragdoll"` config ref, no animations). Compiled verification:
   ragdoll config [0] dynamic_actors == the 29 bone hashes; layer 1 has
   EMPTY_STATE + RAGDOLL_STATE(ragdoll=0). Mirrors the vanilla ratling
   layout exactly (its ragdoll layer: reset_scale / ragdoll(cfg 0) /
   ragdoll_torso(cfg 7) / empty).
3. Runtime: no new code - the existing name-gated event mirror already
   forwards the AI's "ragdoll" event; the base layer still plays death_shot
   while the ragdoll layer flips the 29 actors dynamic.

Verification tooling: scratchpad extract_bundle_payload.py (pull any
resource out of a built bundle) + verify_ragdoll_build.py (parse compiled
unit/SM via the Bitsquid tools). Test gate now cross-checks .physx actor
names == SM ragdolls block == .bones entries and joints == actors-1.

## Open work

- **Animation set: complete for the current enemy loop.** Since v0.1.39 the
  custom unit has compiled locomotion, shoot, wind-up/reload, stagger, and
  death clips plus state-machine events using the ratling vocabulary. Treat
  the older passive-idle-only notes above as pipeline history, not a present
  blocker. Add new clips only when a new gameplay state actually needs one.
- **Texture conversion: implemented and body appearance user-approved.** Armor
  and backpack now use source BC RGBA, NR RGBA, and
  `MASE_Fix.rgb + MASE.a` through the exact Ratling 0488 three-map child.
  Skin/fur/whiskers use the exact source-native Stormvermin children. UV
  comparison proves no flip or resampling is required. The 17-test texture
  regression suite and deterministic donor-payload validation pass; the
  verified build/splice was uploaded and its body appearance passed the user's
  in-game check. Launcher/rocket set-03/set-04 adapters ship in the accepted
  v0.1.55 host MVP and their appearance also passed the user's in-game check.
  See
  `docs/research/WARLOCK_TEXTURE_PIPELINE.md`.
- **Native-carrier visual handoff**: v0.1.50 passed the original five-second
  host baseline. v0.1.51 is a known pre-monitor sleep-suppression failure; the
  ordering fix is runtime-proven in v0.1.53, v0.1.54, and the accepted v0.1.55
  host MVP. The latest capture and user observation establish visible identity
  and ordinary host stability, while its deliberately dense overlap batch is
  stress evidence rather than a clean whole-file analyzer pass. An explicit
  post-five-second sleep/wake interaction, ordinary cleanup, pause behavior,
  and a remote-client `source=husk` run remain open. Never reveal the native
  ratling meshes as a fallback.
- **Launcher/projectile:** v0.1.55 ships Crunch's final launcher plus loaded
  rocket and standalone rocket with authored set 03/04 textures. The corrected
  semantic-grip placement, hand/back appearance, firing/reload behavior, and
  one-actor loaded death drop passed the user's in-game test. Preserve the
  existing rigid attachment, muzzle, projectile nodes, and actor closure, and
  rerun the complete source/compiled/runtime gates after any change.
- **Flexible tube and chimney particles:** deferred from the MVP so neither can
  confound the weapon/ragdoll test. Author and validate them as separate changes.

The public Workshop listing makes the remaining multiplayer lane available to
Crunch and other testers. Every player must subscribe to and enable the same
Doomrocket version; the host controls spawning. Collect both logs so the host
records `source=unit` and the remote client records `source=husk`. Public
visibility does not itself prove client behavior.
