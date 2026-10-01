# Changelog

## v0.1.58-alpha — 2026-09-30

- Publishes the supplied Warlock Engineer / Doom Rocket thumbnail using the
  byte-identical checkout policy accepted by the working VMB 0.6.4 process.
- Checks the copied checkout policy and receipt ignore contract before a build.
- Preserves the accepted public-alpha gameplay, models, animation and audio;
  no experimental TEST behavior is promoted.

## v0.1.57-alpha — 2026-09-30

GitHub candidate only: VMB refused an unsupported checkout attribute before
calling the Steam uploader. It never reached Workshop; superseded by v0.1.58-alpha.

- Uses the maintainer-supplied Warlock Engineer / Doom Rocket Workshop thumbnail,
  copied unchanged from Thumbnail_02.png (768×768 PNG).
- Publishes through the working standalone VMB 0.6.4 adaptation of the Tweaker
  claim, BuildOnly receipt, hosted QA, and verified Workshop transaction.
- Preserves the accepted public-alpha gameplay, models, animation and audio;
  no experimental TEST behavior is promoted.

## v0.1.56-alpha — 2026-09-10

- Promotes Crunch's requested 60x70 Warlock Engineer kill-feed portrait, with a
  deterministic atlas builder and asset verification.
- Guards launch/reload against nil or deleted targets during career changes,
  without changing public aiming, flight time, ammunition, range, or audio.
- Preserves the accepted v0.1.55 body/weapon assets and ragdoll baseline.
- Excludes the TEST relocation crash and all newer combat, balance, custom-audio,
  ballistic-aim, and explosion experiments.

Published and verified on public Workshop item `3771657344` at 05:05:35 UTC:
content handle `1428725673095257484`, exactly 92,596,852 bytes. Clean build,
material splice, full public package pipeline, and source CI pass.

Portrait visuals, the narrow public target-safety port, and remote-client
behavior still need matching runtime checks. See the
[promotion and publication record](docs/releases/v0.1.56-alpha.md).

## v0.1.55-alpha — 2026-09-01

First maintained public-alpha release after the handoff from dalo_kraff.

- Preserves the accepted Warlock body model, textures, and native-carrier
  ragdoll handoff.
- Uses Crunch's launcher and rocket assets with corrected hand/back placement.
- Keeps the loaded warhead attached to the physics-owned dropped launcher.
- Separates experimental combat, shove, ballistic-aim, and custom-audio work
  into the development TEST channel.
- Adds formal public bug/crash/feedback forms and console-log instructions.

Known validation gaps: remote-client ragdoll (`source=husk`), explicit
post-monitor sleep/wake cleanup, flexible tubing, backpack smoke, bespoke audio,
and final multiplayer acceptance.
