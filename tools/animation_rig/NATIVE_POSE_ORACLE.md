# Native pose oracle status

The isolated harness compiles with the installed VT2 SDK. Native playback is
**unverified and blocked by the installed runtime entrypoint**. There are no
successful native pose receipts from this tool.

The v0.1.93-dev TEST candidate adds a separate passive in-game observation path:
`/warlock_animation_rehearsal on` selects a compiled stock-clip rehearsal only
for new outfits, and `/warlock_animation_probe on` observes clocks and a bounded
matrix subset after presentation. See [the authoring guide](../../docs/ANIMATION_AUTHORING.md#v0193-dev-runnable-native-controller-rehearsal).
This does not run this oracle, provide fixed-frame captures, or establish
Blender-export/garment acceptance. Do not paste the standalone oracle into the
game: it owns its own world and application shutdown.

On 2026-10-11 at 02:21:45 UTC, SDK executable SHA-256
`721bc354a520510ea270147c57230c87cc7e07d93f78ca1a0763d5bdb74137de`
was launched with `--no-rendering --disable-default-window
--suppress-messagebox --no-compile --data-dir <isolated data>
--ini native_pose_oracle --default-console-log-path <isolated file>`.
It entered the compiler and failed with:

> Error checking prerequisistes: Source directory '' for compile does not exist.

No boot callback, `ANIMATION_ORACLE_STARTED`, `ANIMATION_ORACLE_COMPLETE`, or
`Unit` pose output appeared. The installed SDK contains one engine executable;
its own `compile_streamable_resources.bat` also invokes that executable without
`--compile`. Generic Stingray runtime flags and Lua APIs present in the binary
do not establish an accessible playback entrypoint in this VT2 mod-tools build.
The runner refuses another native attempt with this known executable hash.

The October 20 read-only installation audit found one configured Steam library,
`C:\Program Files (x86)\Steam`, in both `steamapps/libraryfolders.vdf` and
`config/libraryfolders.vdf`. It has no `appmanifest_552500.acf`; the residual
`common/Warhammer Vermintide 2` directory contains only configuration, chroma,
and launcher-log files, without game executables or bundles. The installed SDK
still has the failed executable hash above. No new process was launched during
that audit. Under the launch-verification requirement, a new runtime handoff
remains pending before game startup; compilation and API-double tests do not
satisfy that stage.

The standalone oracle now starts both its initial and replacement crossfades
on zero-based layer `0`, after checking that its own spawned unit is alive,
has an animation state machine, and reports exactly one layer. The packed
`animation_get_state` return count distinguishes zero layers from one layer
whose current state is nil; the latter can start frozen playback. Every sample
also checks these prerequisites before seeking. Executable Lua-double tests
exercise both crossfades, absent/multiple layers and teardown while preserving
the frozen speed, seek times and matrix convention. These are engineering
checks, not evidence that the blocked native runtime has executed these APIs.

Ignored diagnostic evidence is under
`.build/animation_native_pose_oracle/clip_00/candidate/`:
`compiler.stdout.log`, `runtime.stdout.log`, `runtime.stderr.log`,
`runtime.console.log`, `runtime.process.json`, and `runtime_expected.json`.
The process receipt identifies the owned PID, executable hash, arguments,
start time, project directory, and timeout. No game was installed or deployed,
no Workshop operation occurred, and no viewport was created.

## Intended contract, pending an accessible runtime

`native_pose_oracle.lua` uses frozen direct animation seeking after disabling
the diagnostic animation state machine. It calls `World.update_animations` at
an explicit fixed timestep and `World.update_scene(0)`. Each local/world pose
is copied into numeric 4x4 rows immediately; native temporary math counters are
restored after every bone. Matrices preserve native units, scale wrappers, and
hierarchy. Native x/y/z/translation rows are transposed into conventional
column-vector affine matrices; no interpolation or metre rescaling occurs.
Root mode is `ignore`, with `animation_wanted_root_pose` recorded separately.

Diagnostic mode requests all 138 bone names at every authored frame: the
corrected 97-frame clip and continuous 589-frame clip use index/60 seconds.
Compatibility mode requests the seven reserved bones plus `j_hips`, across all
13 adapted clips at their manifest-declared rates. Staging accepts only bounded
1/2/4 refinements of the audited 60/240 fps bases: 60/120/240 fps for ordinary
clips and 240/480/960 fps for death/staggers. The final 4× calibration plans
12,045 authored samples at 240/960 fps. Candidate and reference sidecar hashes
are read separately from their staged bytes. This remains a capture plan, not
a native acceptance result.

Receipts must bind body FBX, animation FBX/sidecar, author manifest, staged
oracle script, compiled unit/animation resources, and SDK executable hashes.
The validator checks exact indices/times, complete bone names, finite matrices,
unique node indices, a completion marker, and unchanged compiled resources.
Those checks validate a capture, not visual or in-game acceptance.

The [Unit API](https://help.autodesk.com/cloudhelp/ENU/Stingray-Help/lua_ref/obj_stingray_Unit.html)
documents frozen seeking, disabled state-machine control, and final-pose
retention. The SDK's stock LUT generator supplies the boot-script/package
pattern. Neither source proves this particular executable can run the harness.

## Isolated compilation

`Invoke-AnimationRuntimeProbe.ps1 -CompileOnly` can stage and compile the
prototype with frozen FBX/body/manifest inputs. Use a dedicated `ProbeRoot`
below the repository `.build`. `-CompatibilityOnly -AdaptedClips <directory>`
stages the 13 existing clips; `-IncludeReference` also compiles the original
body/reference lane. This mode does not run native playback or produce a pass
receipt for poses. Compile/runtime attempts are bounded and only a verified
process created by this runner may be stopped.

Existing decoded animation checks must retain their stated evaluator evidence
and limitations; this failed bootstrap cannot strengthen them to actual
`Unit` playback or game acceptance.
