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
- Prepare on a feature branch and merge through a reviewed PR to remote `main`.
- Final publication uses the clean exact live `main` commit, including a detached
  checkout of that commit when another worktree owns the local branch.
- Steam Workshop item: `3771657344`.
- Required title shape: `Warlock Engineer v<version>-alpha`.
- Development repository/worktree: `Ensrick/doomrocket-private` at
  `C:\Users\danjo\source\repos\doomrocket`.
- Development Workshop item: `3794172730`, visibly labeled `TEST`.

Never add experimental gameplay, aiming, sound, effects, animation, balance, or
asset work directly to this release line. Implement and validate it in the
development repository, then port it deliberately after in-game acceptance.

The `origin` remote is dalo_kraff's historical upstream and is read-only for
this maintenance line. Push preparation branches only to `public`, open a PR
against `main`, and pass hosted QA before merging. Preserve unrelated edits in
other worktrees; the clean public release checkout is separate from the older
dirty `doomrocket-public` checkout.

## Current deliberate promotion, November 7, 2026

The maintainer explicitly authorized promoting the improved tested default
Warlock to the official item. Broker-allocated **v0.1.60-alpha is in preparation**;
v0.1.59-alpha remains the last verified public publication. The selected source
is TEST v0.1.98-dev, commit `e865b41768348e980e0b1cb80f0e5c68b0c397c6`.
[The promotion record](docs/releases/v0.1.60-alpha.md) owns scope, acceptance,
known limits and subsequent publication evidence.

Carry the tested default runtime and its required resources without new tuning.
Crunch accepts the improved traversal and hose sway, while asking for a stronger
W shape as a remaining refinement. Keep the current accepted stiffness/damping,
existing animation tracks and authored/custom ownership. The default authored
manifest remains empty, the shipping body is unmarked, and rehearsal remains
disabled until explicitly selected; no generated artist profile or localized
body overlay is activated by this promotion.

The thirteen calibrated original animation FBXs differ from alpha59 in the
constant `aim_target` helper translation. Verify the non-helper tracks and helper
rotations rather than claiming whole-file identity against alpha59. Require
parity with the tested TEST98 sources apart from channel/version metadata.

The existing game-absent publication-only exception applies. A build or upload
does not add local native game evidence. Keep TEST item 3794172730 unchanged,
and record fresh source/receipt, QA and native Workshop proof before calling
alpha60 published or ready.

## Asset authorship boundary

New art, 3D models, animation clips, audio masters, and other new source assets
belong to Arnaud. Do not invent or author replacement assets to unblock an issue.

Engineering may fix code, adjust packaging of already-approved assets, and
reuse or modify effects already present in the game. Preserve the approved
artist masters when adjusting their packaging. When a fix needs a new source
asset, name that missing asset in the issue and keep it blocked until Arnaud
supplies it.

## Start every session

1. Read `PROJECT_STATUS.md` and the relevant GitHub issue.
2. Run `git status --short --branch` and preserve unrelated local edits. Work
   on a feature branch for preparation; final publication uses clean live HEAD.
3. Verify `itemV2.cfg` still targets `3771657344`, is public, and has no `TEST`,
   `Currently Unstable`, or `-dev` title text.
4. Treat GitHub Issues as the live backlog. Do not create a competing TODO list.

## Build environment hygiene

Keep temporary settings in copied child environments. If a PowerShell caller
changes process environment values, save and restore them in `try/finally`.
Never persist build settings, alter the user's PATH, dot-source a build launcher
or install build-only tools globally. Every isolated `DOTNET_CLI_HOME` child must
explicitly receive `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false` and
`DOTNET_GENERATE_ASPNET_CERTIFICATE=false`. Preserve user/machine values and
types, and do not restore a stale whole PATH over concurrent legitimate changes.

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
