# Repository instructions

This checkout is the accepted **public-alpha** release line. These instructions
apply to human maintainers and AI coding agents.

## Identity and boundaries

- Canonical GitHub repository: `Ensrick/doomrocket-public`, remote `public`.
- Local branch: `public-alpha`; it publishes to remote branch `main`.
- Steam Workshop item: `3771657344`.
- Required title shape: `Warprocket Bombardier v<version>-alpha`.
- Development repository/worktree: `Ensrick/doomrocket-private` at
  `C:\Users\danjo\source\repos\doomrocket`.
- Development Workshop item: `3794172730`, visibly labeled `TEST`.

Never add experimental gameplay, aiming, sound, effects, animation, balance, or
asset work directly to this release line. Implement and validate it in the
development repository, then port it deliberately after in-game acceptance.

The `origin` remote is dalo_kraff's historical upstream and is read-only for
this maintenance line. Push public work only with:

```powershell
git push public public-alpha:main
```

## Start every session

1. Read `PROJECT_STATUS.md` and the relevant GitHub issue.
2. Run `git status --short` and confirm the branch is `public-alpha`.
3. Verify `itemV2.cfg` still targets `3771657344`, is public, and has no `TEST`,
   `Currently Unstable`, or `-dev` title text.
4. Treat GitHub Issues as the live backlog. Do not create a competing TODO list.

## Evidence and release rules

- Static tests cannot prove in-game visuals, physics, audio, or multiplayer
  behavior. Record those as pending until a matching runtime log and visual
  report pass.
- Never commit `bundleV2`, `.build`, `.mod_bundle`, downloaded logs, or
  game-derived donor payloads.
- Never use `vmblauncher all`; it has no material-splice checkpoint.
- Required publication order: clean build, verified material splice, full
  pipeline, optional deploy, upload, then verify Steam title/visibility,
  ManifestID, and content size.
- Both Workshop items are public but share the same internal mod identity.
  Never enable them together and never point this config at the TEST item.

Fast repository check:

```powershell
py -3 tools/check_repository.py --channel public
```

Full pre-upload gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-WarlockPipeline.ps1
```

See `docs/RELEASE_CHANNELS.md`, `CONTRIBUTING.md`, and
`docs/TESTER_CHECKLIST.md` for the human workflows.
