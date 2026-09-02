# Contributing

Thanks for helping improve Warprocket Bombardier. Keep contributions focused so
they are easy to test and safe to promote.

## Players and testers

Use the [issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
instead of a blank issue. Select the gameplay/presentation, crash, or feedback
form and follow [the short reporting guide](docs/BUG_REPORTING.md). Public-alpha
reports belong here; TEST-build reports belong in the
[development tracker](https://github.com/Ensrick/doomrocket-private/issues/new/choose).

## Code and documentation

1. Start from an existing issue when possible and keep one change per pull
   request.
2. Put new mechanics and unverified behavior in the development repository.
   The public repository is the accepted release line.
3. Preserve Lua 5.1 compatibility and the host/client ownership model.
4. Add or update a regression test for a bug fix.
5. Do not commit `bundleV2`, `.build`, compiled `.mod_bundle` files, downloaded
   tester logs, or game-derived donor payloads.
6. Run the fast repository check and relevant tests. The GitHub workflow repeats
   source-safe checks; the complete VMB build and in-game acceptance remain
   local/manual steps.

```powershell
py -3 tools/check_repository.py --channel public
py -3 tools/tests/test_warlock_retarget_math.py
py -3 tools/tests/test_warlock_texture_pipeline.py
py -3 tools/tests/test_warlock_weapon_pipeline.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/tests/Test-WarlockRagdollRegressions.ps1
```

Before a Workshop upload, also complete the clean build, verified material
splice, and full `tools/Test-WarlockPipeline.ps1` gate documented in
[Release channels](docs/RELEASE_CHANNELS.md).
