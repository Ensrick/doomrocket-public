# Repository instructions

This checkout is the accepted **public-alpha** release line. These instructions
apply to human maintainers and AI coding agents.

## Build, deploy and upload authority

Use the working Vermintide 2 Tweaker method required by the maintainer on
September 13, 2026. Read `docs/RELEASE_CHANNELS.md` and the byte-for-byte
upstream copy in `docs/upstream/vermintide-2-tweaker/PROJECT_STANDARDS.md`,
section 6.6. These instructions supersede historical release wrappers.

`tools/ship/ship.ps1` uses the working standalone Warlock adapter with explicit
public-alpha identity. The launcher is the approved standalone VMB 0.6.4 build.
Acquire the broker claim before choosing a version; BuildOnly records the
spliced, validated package in `.build-receipt.json`. Commit source and receipt,
pass hosted `qa-gate`, merge, then ship from clean live `main` HEAD.
Do not use direct launcher upload, GUI publication, or the retired v0.5.6 path.
The game is not installed, so use `-AllowPublic -PublicationOnly`; no deployment
is claimed. Steam restart is exceptional recovery, not a routine ship step.

## Identity and boundaries

- Canonical GitHub repository: `Ensrick/doomrocket-public`, remote `public`.
- Local branch: `public-alpha`; it publishes to remote branch `main`.
- Steam Workshop item: `3771657344`.
- Required title shape: `Warlock Engineer v<version>-alpha`.
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
2. Run `git status --short --branch` and preserve unrelated local edits. Work
   on a feature branch for preparation; final publication uses clean live HEAD.
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

`tools/Invoke-DoomrocketRelease.ps1` delegates to the canonical standalone
adapter. Publication requires the exact source/output receipt and hosted QA.

See `docs/RELEASE_CHANNELS.md`, `CONTRIBUTING.md`, and
`docs/TESTER_CHECKLIST.md` for the human workflows.
