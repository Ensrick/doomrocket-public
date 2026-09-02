# Release channels

Warprocket Bombardier has two public release channels. They intentionally use
separate repositories, worktrees, Workshop items, titles, preview images, and
published-ID guards.

| Channel | GitHub | Branch | Steam Workshop | Version/title | Purpose |
| --- | --- | --- | --- | --- | --- |
| Public alpha | `Ensrick/doomrocket-public` | `main` | `3771657344` | `Warprocket Bombardier v0.1.55-alpha` | Last in-game accepted model, textures, weapon placement, death drop, and host ragdoll |
| Development TEST | `Ensrick/doomrocket-private` | `private-copy` | `3794172730` | `Warprocket Bombardier TEST v0.1.60-dev` | Experimental combat, shove, ballistic aiming, and custom audio |

Both GitHub repositories and both Workshop items are public. The TEST listing
must begin with a prominent development/instability warning and use the black
thumbnail with white `TEST` text. The public-alpha title must never contain
`TEST`, `Currently Unstable`, or `-dev`.

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

The pipeline fails when a channel points at the other channel's Workshop item,
which prevents an experimental build from overwriting the public alpha.
