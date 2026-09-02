# Warlock ragdoll runtime test protocol

This protocol is the acceptance gate for the native-ratling-physics/custom-
Warlock-visual handoff. A stable ratling corpse is a failure, not a fallback.
Static tests prove only that known-dangerous mechanisms are absent; video is
required to prove the visible model identity.

Recorded status: uploaded v0.1.50 passed an 11-corpse, five-second host
telemetry baseline on 2026-08-12. Uploaded v0.1.51 failed its first host death:
hips drift reached 2.505 m at 5 s despite 602 callbacks, while deformation and
performance metrics remained normal. The v0.1.51 sleep gate cached/consulted
actors during the monitor and suppressed pose transfer. v0.1.52 introduced the
fix that forbids sleep optimization until `monitor_complete`, but received no
runtime capture. v0.1.53 carried that fix forward, added mandatory
`pose_writes`/`sleep_skips` evidence, and passed four host deaths on 2026-08-12:
every callback wrote a pose, no sleep callback was skipped, and all four
five-second traces passed the drift gate. v0.1.54 kept that proven body path
unchanged and passed three more host traces while correcting the loaded-warhead
drop hierarchy; its launcher art was nevertheless misplaced. v0.1.55 corrected
the rigid launcher's internal mesh placement and excluded the unrigged long
tether. The user confirmed the visible Warlock corpse, weapon appearance,
hand/back placement, firing/reload behavior, and loaded death drop in game.
The latest capture contains 20 complete host traces; the first six ordinary
traces pass every strict threshold, while a separate fourteen-corpse overlap
stress batch has transient extremity-anchor excursions and settles by one
second. Remote-client `source=husk`, explicit post-monitor wake, pause, and
long-lived cleanup coverage remain required.

## Before launching

1. Run from the repository root:

       powershell -NoProfile -File tools/tests/Test-WarlockRagdollRegressions.ps1
       powershell -NoProfile -File tools/Test-WarlockPipeline.ps1

2. Build, splice, validate, deploy, and upload in that order. Never use
   `vmblauncher all`; it can publish the unspliced material bundle.
3. Restart Steam and Vermintide 2 after the Workshop item finishes syncing.
4. Disable **Less Corpses** and any other corpse/physics replacement mod. Use a
   corpse limit of at least 70 for the test.
5. Confirm the console contains the exact tested-build banner and record
   its Workshop manifest ID:

       [doomrocket:LOAD] v0.1.55-alpha

   `[doomrocket:LOAD] v0.1.50-dev` identifies the original baseline.
   `[doomrocket:LOAD] v0.1.51-dev` identifies the known pre-monitor
   sleep-suppression regression. `[doomrocket:LOAD] v0.1.52-dev` is the
   uploaded but uncaptured predecessor and lacks the final counter gate.
   `[doomrocket:LOAD] v0.1.53-dev` identifies the four-corpse host pass with
   the floating-warhead defect. `[doomrocket:LOAD] v0.1.54-dev` identifies the
   three-corpse host pass with corrected warhead-drop physics but displaced
   launcher art. None is a valid v0.1.55 test run.
6. For a public multiplayer test, every participant must subscribe to and
   enable the same Workshop item/version. The host controls spawning. Preserve
   the host log and at least one remote-client log so `source=unit` and
   `source=husk` can be verified independently.

## Capture matrix

Use non-gibbing attacks. Do not use the Doomrocket backpack/`aux` explosion as
the killing blow. Record the corpse continuously for at least 10 seconds, with
the full body in frame.

| Lane | Scenario | Minimum observations |
|---|---|---|
| Host | Low-impulse melee torso kill | One corpse on level ground |
| Host | Ranged headshot | One corpse; embedded projectile may remain |
| Host | Terrain | One torso kill on stairs or a slope |
| Host | Concurrency | Five Doomrockets killed rapidly in the same view |
| Host | Pause | Pause before 2 s, wait at least 5 wall-clock seconds, resume; game-time checkpoints must continue rather than jump to completion |
| Host | Post-monitor wake | Let one non-gibbed corpse settle past 5 s, then wake/move it with an ordinary physics interaction; the Warlock visual must resume with the carrier |
| Host | Cleanup/reload | Observe normal corpse deletion, then leave and re-enter `StateIngame`; no stale callback or reload error |
| Remote client | Repeat melee and ranged cases | Client log must report `source=husk` |
| Remote client | Post-monitor wake and cleanup | Visual stays attached after wake; no stale husk driver after deletion or level exit |

For each single-corpse case, retain fixed-camera frames at approximately
0.5 s, 2 s, 5 s, and after the post-monitor wake. Do not count an accidental
spawn or a unit killed before it finishes spawning.

Run the pause lane in a separate console capture. Its intentional wall-clock
gap is expected to exceed the 250 ms performance limit even though game-time
checkpoints correctly do not advance; do not include that trace in the main
analyzer acceptance log. The non-paused host/client captures must independently
pass the wall-gap threshold.

Run a deliberately overlapping mass-kill stress lane in another separate
capture. Ordinary release acceptance remains strict and must print
`[ragdoll-log] OK` without stress exceptions. Dense collision stress may be
analyzed with the explicit `--dense-stress` option, which relaxes only transient
250/500 ms extremity-anchor excursions when at least ten complete traces overlap
and every trace returns below the ordinary anchor threshold at 1000, 2000, and
5000 ms. Hips, roots, deformation, mutation, visibility, lifetime, pose-write,
sleep-skip, and performance gates remain unchanged. A visual launch, stretch,
physics disturbance, or failure to settle rejects the stress run regardless of
the analyzer result.

## Visual pass criteria

- The corpse is recognizably the Warlock Engineer/Bombardier: body, armor, and
  backpack remain visible.
- No native ratling body or gunner outfit appears.
- No disappearance, stick figure, stretched limbs, roof launch, or exploding
  body parts.
- Nearby physics objects remain stable and there is no sustained frame-rate
  collapse or multi-frame kill freeze.
- A settled corpse still carries the Warlock visual when woken after five
  seconds; `monitor_complete` must not freeze it in the old pose.
- Ordinary corpse cleanup still occurs after the game's configured lifetime.

Any visual failure rejects the build even when the log analyzer passes.

## Log pass criteria

Each corpse produces `phase=begin`, game-time `phase=sample`, and
`phase=stop` records with one unique `id=unit-NNNN` or `id=husk-NNNN`.
There must be exactly one sample at 0, 100, 250, 500, 1000, 2000, and 5000 ms,
followed by `reason=monitor_complete`. That stop closes telemetry only; the
internal pose driver must remain registered until deletion/reset. Samples must
satisfy all of the following:

- `owner_alive=true`, `outfit_alive=true` through the observation window;
- `nodes=90` at every checkpoint;
- `custom_actors=0`, `carrier_reveals=0`, and `parent_mismatch=0`;
- `scale_mutations=0` and `nonhips_translation_mutations=0`;
- calibrated `hips_drift <= 0.25` m;
- absolute `hips_delta <= 0.25` m;
- `root_delta <= 0.25` m, `named_root_drift <= 0.25` m, and
  `anchor_max_drift <= 0.5` m;
- `bounds_ratio` and `max_bone_radius_ratio` each remain within 0.5–2.0×;
- `wall_gap_ms <= 250` ms. This is the maximum callback gap observed since
  the previous checkpoint, not merely the frame immediately before logging;
- `pose_writes` is a positive integer and strictly increases at every sample;
- `sleep_skips=0` at every sample and at the monitor-complete stop;
- the stop record has `callbacks=pose_writes`, proving no callback in the
  pre-monitor window returned without transferring the pose.

During those seven checkpoints, pose transfer is mandatory on every
owner-world callback. The implementation must not enumerate/cache actors or
suppress writes based on sleep state until after `monitor_complete`. A complete
callback count does not prove writes occurred: v0.1.51 logged 602 callbacks
while its visual drifted 2.505 m from the carrier.

`carrier_reveals=0` covers tracked Lua calls through both
`Unit.set_mesh_visibility` and `Unit.set_unit_visibility`. A mesh reveal attempt
is forced to `false`; a whole-unit reveal attempt is synchronously followed by
a complete carrier-mesh re-hide. Either incident still rejects the run. These
hooks cannot observe an engine-internal visibility or culling change, so the
recorded video remains the authoritative carrier-identity check.

Analyze a captured console log with:

    py -3 tools/analyze_warlock_ragdoll_log.py "C:\path\to\console.log" --expected-version 0.1.55-alpha

The analyzer must print `[ragdoll-log] OK`. `--expected-version` is mandatory
for acceptance; omitting it is supported only for historical-log triage.
Attach the original console log and the corresponding video to the issue; do
not paste only selected lines because concurrent corpse IDs and load/version
evidence must remain auditable.

For the separate dense-overlap stress capture only, use:

    py -3 tools/analyze_warlock_ragdoll_log.py "C:\path\to\stress-console.log" --expected-version 0.1.55-dev --dense-stress

This is additive stress evidence. It never replaces the ordinary strict host
capture, remote-client capture, or video.

## Failure triage

- `carrier_reveal` or a visible ratling: reject immediately; this is the
  v0.1.49 substitution failure.
- Large `hips_drift`, bounds ratio, or bone-radius ratio: reject as a retarget
  failure; do not compensate by revealing the carrier.
- Increasing hips/anchor drift with normal wall gaps, stable deformation ratios,
  zero mutations, and a normal callback count is the v0.1.51 pose-suppression
  signature. Verify that sleep discovery and suppression cannot execute before
  `monitor_complete`.
- Bounded telemetry but no visible Warlock: run a separate culling-only A/B
  build. Do not change physics, pose transfer, materials, and culling together.
- Host passes but client/husk fails: treat it as a lifecycle/network-lane bug;
  a host-only result is not acceptance.
- The Warlock detaches only after 5 s or after the wake interaction: reject the
  persistent-driver/sleep-wake lane even if the analyzer reports OK. The compact
  five-second schema cannot prove behavior after `monitor_complete`.
- Checkpoints complete while paused: reject the game-time monitor lane.
- An observed hitch is absent from `wall_gap_ms`: reject worst-gap
  accumulation; do not treat the adjacent-frame value as interval evidence.
- Reload/level exit emits a stale callback error: reject teardown cleanup.
