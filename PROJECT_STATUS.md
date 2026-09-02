# Project status

Snapshot updated 2026-09-01. GitHub Issues is the live work queue; this page is
the short re-entry map, not a second backlog.

## One-minute re-entry

| Question | Answer |
| --- | --- |
| What can ordinary players use? | [Public alpha v0.1.55-alpha](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344) |
| What is being tested? | [Development TEST v0.1.60-dev](https://steamcommunity.com/sharedfiles/filedetails/?id=3794172730) |
| Where are public reports filed? | [Public issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose) |
| Where is experimental work tracked? | [Development issues](https://github.com/Ensrick/doomrocket-private/issues) |
| Can both Workshop items be enabled? | No. They share an internal mod identity; use exactly one. |

## Current state

The public alpha is intentionally pinned to the last in-game accepted baseline:
the current body and weapon models, textures, launcher hand/back placement,
loaded-warhead death drop, and host ragdoll behavior.

The development line contains newer combat, shove, ballistic-aim, and custom
audio work. It is not ready for promotion. Its current release blocker is
[repeated rocket detonation after impact](https://github.com/Ensrick/doomrocket-private/issues/8);
the earlier explosion-crash containment candidate remains tracked in
[issue #7](https://github.com/Ensrick/doomrocket-private/issues/7).

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
5. Never infer acceptance from static tests alone. A player-visible or runtime
   change remains development-only until the required in-game test passes.

See [Release channels](docs/RELEASE_CHANNELS.md) for the publication sequence
and [Bug reporting](docs/BUG_REPORTING.md) for tester instructions.
