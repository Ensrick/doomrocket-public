# VT2 native-chain compiler lab

Research tooling, **not a playable mod or completed hose implementation**. It
proves a source-authorable native chain and records why that particular solver
does not provide two separately moving endpoint pins. No donor payload or
disassembly is included. Generated files stay under ignored `.build`.

## Reproduce

Coordinate use of the SDK compiler first. From the repository root:

```powershell
py -3 tools/hose_lab/native_chain/test_native_chain.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/hose_lab/native_chain/Invoke-NativeChainProbe.ps1
```

The runner accepts `-ProbeRoot`, `-SdkRoot`, and `-PythonExecutable`. ProbeRoot
must be a dedicated directory below this repository's `.build`; source, data,
bundle and logs are created there. It starts the compiler hidden, requires its
success result, then checks actual descriptor bytes. It never runs the game,
cleans a directory, deploys, or uploads. Stop if a compiler assertion appears.

Before writing fixtures and again before compilation, the shared path preflight
rejects reparse points, junctions, symlinks and hard-linked files throughout the
existing probe tree, including nested source/data/bundle destinations and logs.
It refuses an already-running SDK compiler. After compilation, each required
index entry must be unique and resolve to an ordinary file inside its data root.
These are workflow guards, not an atomic lock against concurrent path changes;
continue to coordinate compiler use. Run the SDK-free path regressions with
`py -3 tools/hose_lab/test_compile_paths.py`.

To verify existing compiler output without invoking the SDK:

```powershell
py -3 tools/hose_lab/native_chain/verify_compiled.py --data-root .build/hose_native_constraint_probe/data --quiet
```

`chain_base.json` is the one authored base. The generator renders it as SJSON
and creates nine cases: base plus eight mutations. Python tools require only
the standard library (Python 3.10+). Unit tests use synthetic bytes, not game
assets. The reader accepts only the validated uniquely named single-chain,
constant-expression envelope; it is not a general ASM parser or expression VM.

**DO NOT RUN THESE FIXTURES IN GAME.** Negative cases include zero mass and an
unsuitable root-bone assignment. Every fixture deliberately has `animations=[]`
to isolate compilation. A playable unit needs its own authored rest clip,
compatible skeleton/controller, and runtime validation. Compilation proves none
of those runtime requirements.

## Verified source contract

The ASM has `bones="probe"`, top-level
`constraints={hose={type="chain", ...}}`, and state `constraints=["hose"]`.
The descriptor's native type is 3. `debug_name` is 1..30 ASCII bytes; enabled and
debug_draw are booleans; link_count is an integer >=2. `link_0`, `link_1`, etc.
are objects. Bone strings resolve to ordered `.bones` indices, not unit scene
node indices. Nonfinal bones must exist; the final bone may be omitted.

| Scope | Fields | Source type |
|---|---|---|
| Chain | gravity, global_damping, vector_field_multiplier | Expression strings |
| Link | bone | String |
| Link | constraint_type, constraint_torsion_spring | Integers, **not booleans** |
| Link | constraint_rotation, length, mass, damping, constraint_damping, torsion_coef, constraint_angle | Expression strings |

`constraint_type` numeric-mode meanings are not fully decoded. Collision getters
also exist (type, transform, bone, position/rotation, radius/height), but their
conventions were not mutation-tested; these fixtures leave collision_type 0.

Compiler success alone is insufficient. The differential verifier proves:

- `mass="7.5"` encodes 7.5, whereas numeric `mass=7.5` silently encodes default 1.
- Integer torsion mode 1 encodes 1; an earlier boolean-true probe encoded default 0.
- Bone assignment changes the expected index; missing final bone encodes UINT32_MAX.
- Modified global and per-link constants alter the independently decoded values.
- Guessed `fixed`, `pin`, `inverse_mass`, `target`, and `tip_target` keys produce
  an entirely **byte-identical** descriptor. These exact spellings are ignored.

The base descriptor is 428 bytes, SHA256
`b32b7dc136f06d074552172eae0c22225eaf78eaa353d02579bd6c03cb58d15e`.
The same reader decoded native `emp_flail_chain` (11 links/1196 bytes) and
`bm_gor_flail_chain` (13 links/1388 bytes): both use gravity 9.82, damping 0.9,
no collision, and a missing final bone with final mass 10/length 1.

## Why this is not a two-pin hose solver

Evidence was checked on 2026-09-10 against the installed SDK executable
`bin/stingray_win64_dev_x64.exe`, SHA256
`721bc354a520510ea270147c57230c87cc7e07d93f78ca1a0763d5bdb74137de`.
Below are executable RVAs relative to image base 0x140000000, not game-memory
patch addresses. No binary modification or runtime execution was performed.

- Chain compiler field reads: roughly 0x772332..0x77413d.
- Missing final bone is explicitly permitted at 0x773714..0x773767.
- Final particle initializes from the **previous** bone plus its +X axis times
  length at 0x767f2d..0x767fe6, not a second endpoint's transform.
- Each update refreshes only particle 0 from the animated root at
  0x768070..0x7681af. Non-root particles proceed through integration.
- Non-root mass is multiplied into gravity at 0x7681b6..0x7681e7. A later path
  reads the next mass at 0x7685b0, multiplies it by scale at 0x7685e2, then divides
  by it at 0x7685ea **without a zero guard**. Zero mass is not a safe pin; it can
  introduce non-finite simulation values.
- Final-particle bone access is also skipped at 0x76853a..0x768578.

This establishes a fixed-root/free-tip native chain, not a verified connection
between a separately moving weapon and backpack. Keep two-pin solver work and
its lifecycle tests separate; do not change the accepted launcher/drop rig to
force this constraint to fit.

For the general pose/state relationship, see Autodesk's
[animation controller constraints](https://help.autodesk.com/cloudhelp/ENU/Stingray-Help/stingray_help/animation/animation_controllers/constraints.html).
That documentation covers position/aim constraints; the VT2 chain findings
above come from local source compilation, native descriptors and SDK inspection.
