# Changelog

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
