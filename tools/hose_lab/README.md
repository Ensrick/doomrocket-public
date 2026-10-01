# Hose research and prototype lab

These tools are **not loaded by the mod**. They do not change either Workshop
build. Start with the [research and acceptance record](../../docs/research/HOSE_RIG_AND_PHYSICS.md).

- [Native chain](native_chain/README.md): recovered compiler schema, controlled
  mutations, and why a free-tip flail chain is not a two-pin hose.
- [Rig](rig/README.md): source-preserving separate mesh, weights, endpoint
  measurements, compressed Blender handoff and offline demonstration.
- [Compiled asset](compiled/README.md): isolated SDK import and skin/bind/actor
  inspection; includes the mesh-bind scale in the bone-driving equation.
- [Solver](solver/README.md): two-ended inertial Lua simulation, tests,
  measured performance, limitations and trajectory generation.

Generated files stay under ignored `.build`; native binaries and artist
downloads are not committed. Do not use the native negative fixtures in game.
Do not treat a successful lab run as host/client acceptance or enable the
hose in the public build.

Run with normal Python settings, without `-O` or `PYTHONOPTIMIZE`. Rig and
trajectory tools reject optimized execution because their validation assertions
must run. The compiled-asset acceptance checks remain active even under `-O`.
