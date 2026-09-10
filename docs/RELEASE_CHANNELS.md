# Release channels

Warprocket Bombardier has two public release channels. They intentionally use
separate repositories, worktrees, Workshop items, titles, preview images, and
published-ID guards.

| Channel | GitHub | Branch | Steam Workshop | Version/title | Purpose |
| --- | --- | --- | --- | --- | --- |
| Public alpha | `Ensrick/doomrocket-public` | `main` | `3771657344` | `Warprocket Bombardier v<version>-alpha` | Accepted baseline plus deliberate, documented promotions |
| Development TEST | `Ensrick/doomrocket-private` | `private-copy` | `3794172730` | `Warprocket Bombardier TEST v<version>-dev` | Experimental combat, movement, ballistic aiming, and custom audio |

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

## Publication procedure

From a clean, committed channel branch, prefer the guarded wrapper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\Invoke-DoomrocketRelease.ps1 -Upload
```

Omit `-Upload` to build/splice/test without publishing, or use
`-PreflightOnly` for a fast channel/metadata/clean-tree check.

1. Work only in that channel's dedicated worktree.
2. Confirm `itemV2.cfg` contains the channel's exact Workshop ID, public
   visibility, title, and preview image.
3. Run a clean VMB build.
4. Run the verified native-material splice.
5. Run the full `tools/Test-WarlockPipeline.ps1` gate.
6. Upload with the public-upload safeguard explicitly enabled.
7. Verify the Workshop title, visibility, description, ManifestID, and content
   size after Steam finishes processing the update.
8. Record the built source commit, validation results, exact content handle,
   byte size and package hashes. Only then mark publication verified and create
   a matching lightweight tag and GitHub prerelease at the publication-record
   commit. Do not move an existing released tag.

The pipeline fails when a channel points at the other channel's Workshop item,
which prevents an experimental build from overwriting the public alpha.
