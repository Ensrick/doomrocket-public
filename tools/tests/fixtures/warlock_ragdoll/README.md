# Warlock ragdoll regression fixtures

These are mutation tests, not examples of supported implementation. Each bad
Lua fixture isolates one failure that previously shipped; the positive fixture
describes the current implementation contract. `fixtures.psd1` is the
executable manifest.

Engine-resource and Lua mutations must end in `.fixture.txt`, never their real
Stingray extension. VMB scans the entire mod root, including `tools/`; a
literal fixture such as `custom_physx.state_machine` is treated as a shipping
asset and can crash the compiler before package generation, while a `.lua`
fixture can silently enter the shipping scripts bundle.

| Historical failure | Static rule | Runtime evidence required |
|---|---|---|
| Custom PhysX solver explosion / FPS collapse | `WR-RAG-001`: no custom `.physx`, ragdoll state, or outfit actor release | `custom_actors=0`; `wall_gap_ms <= 250` |
| Per-bone scene-link stick figure | `WR-RAG-002`: root-only inventory link; no runtime `World.link_unit` / `unlink_unit` | `parent_mismatch=0`; bounded probe ratios |
| Full-pose/scale sky stretch | `WR-RAG-003`: no full-pose write, scale write, or raw carrier-local position copy | `hips_drift <= 0.25 m`; zero scale/non-hips translation mutations; ratios `<= 2x` |
| v0.1.48 custom corpse disappearance | `WR-RAG-004`: do not disable, hide, or destroy the death outfit | `outfit_alive=true` at every begin/sample checkpoint |
| v0.1.49 ratling corpse substitution | `WR-RAG-005`: never reveal the native carrier; positively hide it with the audited 24-mesh fallback, block mesh reveals, and re-hide after whole-unit reveals | `carrier_reveals=0`; `carrier_reveal` is an immediate failure |

The implementation-contract rules add:

- `WR-RAG-006`: the custom ASM stays enabled and death switches bone mode to
  `ignore`. An active-driver registry observes both `World.update_animations`
  paths, queues exactly once only when that world equals `Unit.world(owner)`,
  and applies once in `AnimationSystem.add_safe_animation_callback()`. A safe
  callback must never requeue itself because callbacks are globally drained.
- `WR-RAG-007`: rigid source handoff/current matrices compute
  `inverse(source0) * source`, apply that delta to `target0`, then convert the
  desired target world pose by `inverse(target_parent_world)`. Child writes are
  rotation-only; translation is limited to hips.
- `WR-RAG-008`: every ragdoll record has `phase`, unique `id`, and `source`;
  callbacks use game time for checkpoints, accumulate the worst wall-clock gap
  between checkpoints, and the source defines begin/sample/stop records.
  Samples and stops expose cumulative `pose_writes` and `sleep_skips`; stops
  also expose `callbacks`, so the analyzer can prove every callback in the
  acceptance window wrote the pose.
- `WR-RAG-009`: calibration checks named source/target nodes before lookup,
  requires unique targets, exactly 90 mapped nodes and one hips pair, and
  validates source inverses plus every required target-parent matrix before
  changing visual ownership.
- `WR-RAG-010`: five seconds closes telemetry but does not destroy the pose
  driver. Sleep detection enumerates the carrier's actual actors with
  zero-based indices `0..num_actors-1`; sleeping corpses skip pose writes,
  waking resumes them, and state/mod teardown invalidates queued work.

Run both source mutations and the production contract:

```powershell
./tools/tests/Test-WarlockRagdollRegressions.ps1
```

Analyze a runtime capture separately:

```powershell
py -3 ./tools/analyze_warlock_ragdoll_log.py C:\path\to\console.log --expected-version 0.1.55-alpha
```

The strict command above remains the release gate. A separate, deliberately
opt-in dense-corpse lane may use `--dense-stress`. That mode changes only the
interpretation of `anchor_max_drift`: an excursion is eligible only at the
250 or 500 ms checkpoints, cannot exceed the evidence-bounded 10 m stress
ceiling, must occur while at least 10 telemetry traces are active, and is
eligible only when that same trace is back at or below the ordinary limit at
every 1000, 2000, and 5000 ms checkpoint. All lifetime, visibility, hierarchy,
deformation, hips/root, callback-gap, pose-write, and version checks remain
strict. It is not a substitute for a separate ordinary-density capture that
passes without the option, or for video showing no corpse/prop launch.

`anchor_max_drift` is the maximum change from the calibrated owner-to-outfit
world-space offset among root, hips, head, hands, and feet. The owner and
outfit rigs have different proportions, so an extremity can transiently move
that aggregate heuristic during a dense collision even while root/hips and
the custom visual bounds remain stable. `dense_stress_transient_anchor.log`
captures that classification boundary. Manifest mutations prove that the
default still fails it, settlement is mandatory, the 100 ms checkpoint is not
waived, at least 10 active traces are required, the transient ceiling is
fail-closed, and hips drift stays strict.

`--expected-version` is mandatory for a release acceptance capture. It rejects
missing, stale, and mixed `[doomrocket:LOAD]` banners. It remains opt-in only so
the same analyzer can triage historical logs that predate versioned telemetry.

A default passing trace has exactly one sample at each required checkpoint
(`0`, `100`, `250`, `500`, `1000`, `2000`, and `5000` ms), then a stop record.
It also needs monotonic lifetime, matching `id=<source>-<digits>` /
`source=unit|husk`, no visibility or hierarchy incidents, root delta at most
0.25 m, hips separation and drift at most 0.25 m, maximum anchor drift at most
0.5 m, deformation ratios within 0.5–2× baseline, and no callback gap above
250 ms. Each sample must have a positive, strictly increasing `pose_writes`
counter and zero `sleep_skips`; the monitor-complete stop requires
`callbacks=pose_writes` and `sleep_skips=0`. Video is still required to prove
the visible corpse is the Warlock model.
