# Isolated hose asset compiler check

This imports the new rig without enabling it in the mod. It uses a plain
diagnostic material, no animation controller, and no physics actors. Source
templates have a `.template` suffix so normal mod builds cannot accidentally
compile them as a new runtime unit.

After generating the rig (see `../rig/README.md`), coordinate SDK compiler use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/hose_lab/compiled/Invoke-HoseAssetProbe.ps1
```

The runner stages only its own files under `.build`, invokes the SDK hidden,
checks its success message, then decodes the compiled unit. It never deletes
a directory, modifies the shipping model, deploys, or uploads. The generated
report includes the asset hash and all 29 control-to-compiled-bone transforms.

The shared path preflight runs before staging and again before compilation.
It rejects reparse points, junctions, symlinks and hard-linked files anywhere in
the existing probe tree, including nested source/data/bundle paths and individual
output files. An already-running SDK compiler is refused. The compiled unit's
index entry must be unique and resolve to an ordinary file inside the data root.
These checks are not an atomic lock against concurrent filesystem changes;
compiler use still needs coordination. Both runners accept `-PythonExecutable`;
relative probe paths are repository-relative. Run the SDK-free regressions with
`py -3 tools/hose_lab/test_compile_paths.py`.

The audit requires zero actors, a single mesh/skin, all 29 named deform
controls under one parent, and the exporter-retained unused root skin entry.
It checks all four weight slots for finite, nonnegative values, including
unused slots, and compares positive influences to the source FBX. A 1 µm seam
weld maps 1,608 source vertices to 1,536 canonical positions. All positions
must be covered. Each of the 3,024 compiled triangles must belong to exactly
one source polygon, with exact triangle multiplicity and directed boundary
cancellation. Either valid quad diagonal is accepted; reversed winding,
missing/extra triangles and unused compiled vertices are rejected.

The verifier compares actual weighted source and compiled vertices at three
pose sets with different transforms for each bone—not merely an algebraic
matrix cancellation. The reviewed maximum differences are 0.599, 0.619 and
0.616 mm, within a 2 mm gate accommodating position/weight quantization.
Acceptance checks remain active under Python `-O`. Standard-library-only
synthetic mutation tests run with `py -3 tools/hose_lab/compiled/test_verifier.py`.
Standalone `--report` output must be a file inside a dedicated `.build` child;
the shared path preflight rejects redirected ancestors, nested reparse points
and hard-linked output files before writing.
Runtime collision, culling, frame/twist continuity,
and hook behavior are not established by these offline checks.

## Coordinate convention that must not be skipped

This new FBX has **metre-valued mesh vertices under a scale-100 mesh node**.
The SDK geometry stream is therefore 0.01 times the authored coordinates;
its skin inverse binds differ from the existing body's chimney case.
For column-vector matrices:

```text
W_bone = W_control * inverse(rest_control) * mesh_bind_world * inverse(compiled_inverse_bind)
```

`mesh_bind_world` is the compiled mesh node's bind transform (`diag(100,100,100,1)` in the
current fixture). Omitting it causes a 100-fold size error. Do not substitute
the chimney's local 0.01 scale or normalize these matrices. The verifier
checks that native bone-world × inverse-bind equals mesh-bind-world in the
rest pose, then proves the above equation for independent target poses.

To turn a desired world bone pose into a local pose, the actual game uses
`Matrix4x4.multiply(world_pose, Matrix4x4.inverse(parent_pose))` before
`Unit.set_local_pose` in its row-vector API convention. See
[`TentacleSplineExtension`](https://github.com/Aussiemon/Vermintide-2-Source-Code/blob/c5e4968b1fbb00c49884e56d640ef990a9c04dd0/scripts/unit_extensions/generic/tentacle_spline_extension.lua#L1049).
That is a supported bone-driving precedent, not proof that this hose has run
in the game. Any future driver must write only the separate hose unit.
