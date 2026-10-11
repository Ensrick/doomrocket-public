# Project status

Updated 2026-10-11 UTC. GitHub Issues is the live backlog.

| Question | Answer |
| --- | --- |
| Live public alpha | [v0.1.59-alpha](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344), published and verified October 1 at 06:28 UTC |
| Current public scope | Accepted crash, reload/shove/retreat, smoke, hose physics and functional audio fixes; [source, acceptance and publication evidence](docs/releases/v0.1.59-alpha.md). 96,315,457 bytes; content handle `5109085740045324862`. |
| Published development TEST | [v0.1.85-dev](https://steamcommunity.com/sharedfiles/filedetails/?id=3794172730), verified 2026-10-11 01:13 UTC. 96,226,816 bytes; content handle `2896541613366277250`. [Release record](https://github.com/Ensrick/doomrocket-private/releases/tag/v0.1.85-dev); [reviewed source](https://github.com/Ensrick/doomrocket-private/commit/95388a6a05298ebf2ef08caae7b181a01aab7ca4). |
| Ready TEST checks | Hose rest shape [#3](https://github.com/Ensrick/doomrocket-private/issues/3), near-range rocket clearance [#6](https://github.com/Ensrick/doomrocket-private/issues/6), crystal flame resizing [#15](https://github.com/Ensrick/doomrocket-private/issues/15), launcher/hand alignment [#28](https://github.com/Ensrick/doomrocket-private/issues/28), Dutch Spice arena waves [#35](https://github.com/Ensrick/doomrocket-private/issues/35), and lingering audio [#44](https://github.com/Ensrick/doomrocket-private/issues/44) are ready for solo verdicts on v0.1.85-dev. Publication does not establish their in-game acceptance. |
| Accepted recent TEST work | Longer aim [#16](https://github.com/Ensrick/doomrocket-private/issues/16), portrait frame [#30](https://github.com/Ensrick/doomrocket-private/issues/30), and the five-change balance plan [#33](https://github.com/Ensrick/doomrocket-private/issues/33) are closed from Crunch's written results. Closure does not promote them to alpha. |
| Remaining alpha evidence | [Crash #34](https://github.com/Ensrick/doomrocket-private/issues/34) still needs a crash-bearing log or GUID; [public #2](https://github.com/Ensrick/doomrocket-public/issues/2) is ready for a solo post-monitor corpse wake/cleanup check on v0.1.59-alpha. |
| Blocked prerequisites | Full sound cues [#5](https://github.com/Ensrick/doomrocket-private/issues/5) need Arnaud's new masters. Public-alpha crash [#34](https://github.com/Ensrick/doomrocket-private/issues/34) needs a crash-bearing log or GUID and remains `needs-info`. |

The v0.1.59 promotion retains the public Ratling health/armor, projectile
trajectory and aiming timing. The firmer TEST hose spring, ballistic aiming,
visible spine aim constraint and grip diagnostics remain excluded from alpha.
Known fence/vault motion and hose collision limits remain documented in the
release record. No later TEST candidate is an implicit alpha promotion.

Crunch accepted the v0.1.84 balance plan, including prompt rocket impacts and
the flailing airborne throw with movable camera. His latest wider playtest
report says players are satisfied with the knockback. Occasional terrain
bouncing remains recorded; report a reproducible recurrence normally rather
than keeping the completed balance plan open indefinitely.

The v0.1.84 crystal fire is visible, but Crunch reports that changing its size
command produces no visible difference. He suggested trying a torch flame.
The published v0.1.85 TEST build changes the scaling path; it still needs a
written visual verdict. His new #44 report describes living-enemy sounds
occasionally continuing after death; that observation is accepted and the
published TEST cleanup requires a fresh result. No fixed claim follows from offline
tests alone.

TEST v0.1.80-dev stopped re-running vanilla breed/pickup settings, which had
overwritten Dutch Spice's Into the Nest arena-wave hook. That change is
retained in v0.1.85-dev, but the arena-wave verdict remains outstanding under
#35 and the fix has not been promoted to public alpha. The separate Legend
loading crash names Dutch Spice's misspelled `skaven_storm_vzermin` breed;
it requires a Dutch Spice correction and does not establish failure of the
Warlock compatibility candidate.

#34's original attachment loads v0.1.56-alpha, has no `<<Script Error>>` block,
and ends normally. Neither the old accepted crash closures nor a successful
upload resolve that unlocated `entity_damage` crash report.

`ready-for-testing` and `testing` identify a verified build and its pending
in-game verdict. `blocked` names an engineering, publication, source-asset or
diagnostic-evidence prerequisite. Missing source assets and crash evidence are
real blockers; they are not invitations to repeat unrelated tests.

The v0.1.85 TEST tag stays bound to reviewed source `95388a6a05298ebf2ef08caae7b181a01aab7ca4`. Public
alpha remains v0.1.59-alpha with its original source tag and publication receipt.
No TEST change is claimed as an alpha promotion.

Use the [canonical VMB/Tweaker method](docs/RELEASE_CHANNELS.md). The game is
not installed: publication only, with no deployment claim. Keep exactly one
channel enabled. A solo written observation and matching log suffice; no video,
second player, or arranged multiplayer session is a standing test requirement.
