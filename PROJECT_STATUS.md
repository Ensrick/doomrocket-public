# Project status

Snapshot updated 2026-09-10. GitHub Issues is the live work queue; this page is
the short re-entry map, not a second backlog.

## One-minute re-entry

| Question | Answer |
| --- | --- |
| What can ordinary players use? | [Public alpha v0.1.56-alpha](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344), published and verified |
| Where is the promotion evidence? | [v0.1.56-alpha release record](docs/releases/v0.1.56-alpha.md) |
| What is the TEST status? | v0.1.65-dev has the [confirmed relocation crash #14](https://github.com/Ensrick/doomrocket-private/issues/14); do not promote it |
| Where are public reports filed? | [Public issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose) |
| Where is experimental work tracked? | [Development issues](https://github.com/Ensrick/doomrocket-private/issues) |
| Can both Workshop items be enabled? | No. They share an internal mod identity; use exactly one. |

## Current state

**v0.1.56-alpha is published and verified**, September 10 at 05:05:35 UTC.
Steam confirms public item `3771657344`, title `Warprocket Bombardier
v0.1.56-alpha`, content handle `1428725673095257484`, and exactly 92,596,852
bytes. The description matches the source configuration. The release preserves
the accepted body/weapon assets, launcher
hand/back placement, loaded-warhead death drop, host ragdoll, and existing
public combat/audio behavior.

Built source `3c08e46` passed the clean build, verified material splice, full
public package pipeline, and [source CI](https://github.com/Ensrick/doomrocket-public/actions/runs/34439363632).
The same validated package uploaded successfully after a graceful Steam
restart. TEST v0.1.65 and its content handle `8123257090222204359` are unchanged.

The deliberate promotion contains only Crunch's requested 60x70 kill-feed
portrait and nil/deleted-target guards in launch/reload. The target-safety
approach has [development host evidence under #9](https://github.com/Ensrick/doomrocket-private/issues/9#issuecomment-5554028509),
but this narrower public port still requires a matching runtime regression.
Portrait color, size and orientation likewise remain visually unconfirmed.
See the [promotion and release record](docs/releases/v0.1.56-alpha.md).

No reposition, shove, reload-preservation, Stormvermin durability, ballistic-aim,
custom-audio, or projectile/explosion changes are promoted. TEST v0.1.65's
missing `reposition` network action ID crashes after a kick ([#14](https://github.com/Ensrick/doomrocket-private/issues/14));
that action is absent from this public release. The development explosion
matrix remains open under [#7](https://github.com/Ensrick/doomrocket-private/issues/7)
and [#8](https://github.com/Ensrick/doomrocket-private/issues/8).

Public acceptance gaps remain tracked by [remote-client ragdoll #1](https://github.com/Ensrick/doomrocket-public/issues/1)
and [post-monitor cleanup #2](https://github.com/Ensrick/doomrocket-public/issues/2).

## Where a change belongs

| Change | Repository |
| --- | --- |
| Documentation, packaging, or a proven fix for the shipped alpha | `doomrocket-public` |
| New mechanics, balance, aiming, sound, effects, animation, or asset experiments | `doomrocket-private` |
| Promotion of accepted development work | Implement/test in development first, then deliberately port to public |

## Resume checklist

1. Choose the public or development channel before editing anything.
2. Confirm the current worktree is clean with `git status --short`.
3. Read the relevant GitHub issue and its newest attached log.
4. Run `py -3 tools/check_repository.py --channel public` for a fast public
   metadata check; use the full pipeline before any Workshop upload.
5. Never infer acceptance from static tests alone. Record the explicit promotion
   scope and any outstanding runtime evidence; do not expand a narrow promotion
   into a merge of the TEST branch.

See [Release channels](docs/RELEASE_CHANNELS.md) for the publication sequence
and [Bug reporting](docs/BUG_REPORTING.md) for tester instructions.
