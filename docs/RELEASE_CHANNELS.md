# Release channels

Warlock Engineer has two public release channels. They intentionally use
separate repositories, worktrees, Workshop items, titles, preview images, and
published-ID guards.

| Channel | GitHub | Branch | Steam Workshop | Version/title | Purpose |
| --- | --- | --- | --- | --- | --- |
| Public alpha | `Ensrick/doomrocket-public` | `main` | `3771657344` | `Warlock Engineer v<version>-alpha` | Accepted baseline plus deliberate, documented promotions |
| Development TEST | `Ensrick/doomrocket-private` | `private-copy` | `3794172730` | `Warlock Engineer TEST v<version>-dev` | Experimental combat, movement, ballistic aiming, and custom audio |

Both GitHub repositories and both Workshop items are public. The TEST listing
must begin with a prominent development/instability warning and use the black
thumbnail with white `TEST` text. The public-alpha title must never contain
`TEST`, `Currently Unstable`, or `-dev`.

See [project status](../PROJECT_STATUS.md) for live versus candidate versions;
a source commit or release candidate is not proof that Steam distributed it.

## Deliberate promotion

Do not merge the development branch into public wholesale. List the selected
files, source provenance, runtime evidence and remaining limitations in a
release record, then port only that scope. Keep public metadata, Workshop ID,
preview, existing assets and unmodified gameplay intact.

The [v0.1.56-alpha record](releases/v0.1.56-alpha.md) selects the requested
portrait and narrow target guards. It excludes TEST repositioning (confirmed
crash #14), shove/reload changes, durability, aiming, audio, and explosions.

## Compatibility rule

Both packages retain the same internal mod identity for save and dependency
compatibility. Never enable both Workshop items simultaneously. Every player in
a lobby must use the same channel and exact version.

## Build, deploy and upload method

User ruling, September 13, 2026: use Vermintide 2 Tweaker's working method
without deviation. Its [exact documentation and implementation copy](upstream/vermintide-2-tweaker/README.md)
is the authority. The source commit and every copied SHA-256 are in
`upstream/vermintide-2-tweaker/COPY_MANIFEST.json`.

The owning procedure is [PROJECT_STANDARDS.md section 6.6](upstream/vermintide-2-tweaker/PROJECT_STANDARDS.md#66-ship-doctrine-keyed-off-the-mod_version-suffix-canonical-2026-07-01):

1. Acquire the machine-global mod/version claim; use the broker's version.
2. Update source, version and changelog together. Canonical `ship.ps1 -BuildOnly`
   builds and validates the artifact and its source/output proof.
3. Commit source and its selected artifact authority together, push the feature
   branch, pass hosted QA and merge through the protected default branch.
4. Run canonical `ship.ps1 -Mod <registered-mod>` from clean live default HEAD.
   It owns the machine transaction, exact-source validation, build parity,
   configured deployment, authorization-backed GitHub release, Workshop upload
   and verification. Public visibility uses its mechanical `-AllowPublic` flag.
5. Verify the fresh item-specific Workshop start/outcome/finish-OK transaction
   with the copied observer, and verify deployed file hashes. Uploader exit zero,
   printed success, metadata and byte count alone do not prove transfer.

Keep the source method's distinctions between tracked and receipt authority,
local/remote deployment and publication-only mode. Keep one private launcher
configuration bound to the invoking source tree and one approved launcher for
the transaction. Never hand-copy files into a real Workshop content directory.
Preserve the selected channel's existing item ID, required title shape,
thumbnail and visibility.

For Warlock's assets, clean compilation must still be followed by the verified
native-material splice and `tools/Test-WarlockPipeline.ps1` before recording the
final artifact proof or deploying/uploading. An unspliced build is not the
Warlock release artifact. Source/compiled checks do not establish game acceptance.

## Headless operation and test refresh

Follow the source workflow's noninteractive launcher path. The old v0.5.6
launcher wrapper and `.build/interactive-launcher` experiment are superseded;
do not revive them or replace the working method with another retry script.

The author tests the hash-verified local deploy without restarting Steam.
Volunteer testers refresh the Workshop subscription; restart Vermintide 2 and
confirm `[doomrocket:LOAD]` with the exact version in the newest console log.
A publication-only run has no local deployment to claim.

Steam restart is exceptional recovery, not a normal build/upload/test step.
Follow [Tweaker's recovery evidence](upstream/vermintide-2-tweaker/docs/PORTABLE_SETUP.md#sdk-prerequisites-and-exceptional-steam-recovery):
check recent successful uploads and actual process contexts before treating an
old failure as a current blocker. Do not infer a diagnosed cause from a stale
registry value or impose a new interactive workflow.

## Standalone repository entry point

Warlock keeps its own development and live repositories. The operational
`tools/ship/ship.ps1` adapts the copied helpers to root-level mod files and the
selected repository. VMBLauncher 0.6.4 adds explicit repository/channel
bindings while retaining the existing hosted receipt gate. The reference copy
under `docs/upstream` remains unchanged and must not be executed directly.

Generated game assets remain ignored. BuildOnly records the exact source bytes,
normalized package hashes and builder identity in `.build-receipt.json`, which
must be committed with the source. Git attributes preserve compiler input bytes.
The protected/default-branch QA and fresh hosted receipt steps are unchanged.

Use the same approved launcher executable and existing VMB project settings in
both phases. The adapter creates a private settings copy for launcher children.

```powershell
$env:VT2_SHIP_SESSION_ID = "warlock-<yyyymmdd>"   # same value for every step below
$env:VT2_SHIP_VMB_LAUNCHER = $launcher            # approved standalone 0.6.4 build
./tools/ship/claim.ps1 -Mod doomrocket -RepoRoot $PWD
./tools/ship/ship.ps1 -BuildOnly -LauncherPath $launcher -ConfigPath $config
# Commit source plus .build-receipt.json, push, pass hosted qa-gate, merge,
# and update this checkout to the clean live default HEAD.
./tools/ship/ship.ps1 -AllowPublic -PublicationOnly -LauncherPath $launcher -ConfigPath $config
```

The public adapter requires item `3771657344` and the `-alpha` suffix; it refuses
the TEST item. The game is not installed, so use publication-only mode. No local
or remote deployment is performed. The compatibility wrapper delegates to the
same transaction.
An upload is complete only after the fresh Steam transaction and metadata agree.

## Verified preflight (2026-09-14)

Recorded from the transaction that published TEST v0.1.70-dev after seven
failed attempts on v0.1.68-dev. Each item names the failure it prevents.

1. **Host.** Run `tools/ship/ship.ps1` from a native PowerShell host (pwsh 7 or
   Windows PowerShell), never from Git Bash. MSYS `tar` shadows Windows `tar`
   and the source-pin recovery step fails with
   `/usr/bin/tar: Cannot connect to C: resolve failed`.
2. **Launcher.** Pass the approved standalone VMB Launcher 0.6.4 build through
   both `VT2_SHIP_VMB_LAUNCHER` and `-LauncherPath` (same path). This
   repository has no `tools\vmb-launcher` checkout, so the environment override
   is the only approved candidate the resolver accepts.
3. **Claim identity.** `claim.ps1` binds a claim to `VT2_SHIP_SESSION_ID`,
   `CLAUDE_SESSION_ID`, `CODEX_THREAD_ID`, or the checkout path, in that order,
   but VMB Launcher derives its own owner from the VMB project root
   (`_doomrocket_vmb`), so in this standalone layout a path-derived identity
   never matches and the launcher refuses the upload (`[claim-gate] REFUSING
   publication: live claim belongs to ...`). Always set
   `$env:VT2_SHIP_SESSION_ID` to a fixed value before `claim.ps1`, BuildOnly and
   the ship; the adapter now fails closed without one. A claim left by another
   agent is released under that identity (`-Release`) and re-allocated; never
   edit the claim file. Claim BEFORE bumping: the broker reads the current
   `MOD_VERSION` and allocates the next patch.
4. **Steamworks registration.** VMB 0.6.3+ refuses to upload (exit 3) when
   `HKCU\Software\Valve\Steam\ActiveProcess\pid` is 0 or differs from the live
   `steam.exe`. On this machine the registration was zeroed every time another
   process launched `steam.exe` while Steam was already running (five times on
   2026-09-13). The recovery that restored it every time, with no game and no
   `ugc_tool` running: `steam.exe -shutdown`, wait for exit, `steam.exe -silent`,
   wait until the registered PID equals the live PID and `connection_log.txt`
   shows `processing complete`. Check the registration immediately before the
   ship; an earlier `doctor` report is not evidence.
5. **Lease contention.** Canonical Tweaker builds and ships hold the
   machine-global `Global\Ensrick.VMBLauncher.Transaction.v1` lease for 5 to 15
   minutes at a time. The adapter waits the upstream 300 seconds. If it still
   reports another owner, wait for that process to exit and rerun once; never
   run a parallel retry.
6. **SDK sidecar.** Clean Stingray builds emit `e7852992f40eb619.mod_bundle`
   (the `core/stingray_renderer/lookup_tables/generator/generate_luts` tool
   bundle) only sometimes. `tools/mod-inventory.psd1` strips it by exact name
   and SHA-256 `e1a04e500f8255ebedcaffb4e35e829adbd99ebf46c2b8b4cd89d26dca4735e2`
   before any receipt or parity comparison. A receipt that captured it can
   never be reproduced; that is what blocked v0.1.68-dev.
7. **Same version, new bytes.** An existing `v<version>` release tag bound to a
   different commit stops the ship. After any change to the receipt or source,
   reissue under the next broker version instead of reusing the number.
8. **Clean live HEAD.** `git status --short --branch` must be clean at the
   merged default-branch commit and the hosted `qa-gate` check on that exact
   commit must be green; the ship rechecks both.
