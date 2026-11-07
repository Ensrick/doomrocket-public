# Project status

Updated 2026-11-07 (America/Chicago). [GitHub Issues](https://github.com/Ensrick/doomrocket-public/issues)
is the live backlog.

| Question | Answer |
| --- | --- |
| Live public alpha | [v0.1.59-alpha](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344), last verified `2026-10-01T06:28:11.2425809Z`: 96,315,457 bytes; content handle `5109085740045324862`. [Original record](docs/releases/v0.1.59-alpha.md). |
| Current preparation | Broker-allocated **v0.1.60-alpha is in preparation and is not yet published**. The maintainer authorized promotion of the improved tested default runtime on November 7. [Selected scope and evidence](docs/releases/v0.1.60-alpha.md). |
| Selected development source | [TEST v0.1.98-dev](https://github.com/Ensrick/doomrocket-private/releases/tag/v0.1.98-dev), reviewed source [`e865b41`](https://github.com/Ensrick/doomrocket-private/commit/e865b41768348e980e0b1cb80f0e5c68b0c397c6). Verified `2026-11-06T04:43:23.0702456Z`: TEST item 3794172730, 96,189,752 bytes; content handle `4811280844651333429`. |
| Latest written feedback | Crunch says [vaulting looks much more convincing](https://github.com/Ensrick/doomrocket-private/issues/53#issuecomment-6703671499). His matching log loads v0.1.98-dev. He would like [a stronger hose W shape](https://github.com/Ensrick/doomrocket-private/issues/3#issuecomment-6704081003); the accepted sway settings are retained. |
| Acceptance already recorded | Flame colour/size [#15](https://github.com/Ensrick/doomrocket-private/issues/15#issuecomment-6624849555), ordinary-spawn crash fix [#65](https://github.com/Ensrick/doomrocket-private/issues/65), longer aim [#16](https://github.com/Ensrick/doomrocket-private/issues/16), portrait frame [#30](https://github.com/Ensrick/doomrocket-private/issues/30), and balance plan [#33](https://github.com/Ensrick/doomrocket-private/issues/33). Accepted checks need no repeated demonstration. |
| Separate unresolved work | W-strength preference [#3](https://github.com/Ensrick/doomrocket-private/issues/3), first-spawn hitch verdict [#69](https://github.com/Ensrick/doomrocket-private/issues/69), clearance [#6](https://github.com/Ensrick/doomrocket-private/issues/6), grip [#28](https://github.com/Ensrick/doomrocket-private/issues/28), arena compatibility [#35](https://github.com/Ensrick/doomrocket-private/issues/35), rare lingering audio [#44](https://github.com/Ensrick/doomrocket-private/issues/44), and facing [#55](https://github.com/Ensrick/doomrocket-private/issues/55) retain their recorded scope. Promotion does not close them. |
| Asset and evidence prerequisites | Full sound pass [#5](https://github.com/Ensrick/doomrocket-private/issues/5) needs Arnaud's source takes/trigger choices; head art [#56](https://github.com/Ensrick/doomrocket-private/issues/56) remains an artist decision. Alpha crash [#34](https://github.com/Ensrick/doomrocket-private/issues/34) still lacks a crash-bearing alpha log/GUID. Broader custom-export, localized-outfit and native-oracle acceptance in [#53](https://github.com/Ensrick/doomrocket-private/issues/53) remains separate. |

## Promotion scope and verification

The alpha60 candidate deliberately ports the tested default runtime and required
resources from TEST98: hose shape/physics, legacy traversal and presentation,
guarded aiming and rocket behavior, approved balance and portrait work,
flame/smoke/material loading, compatibility and audio lifecycle fixes. It adds
no new tuning, production models, animation clips or audio masters. The public
item, thumbnail, title shape, channel guards and canonical VMB adapter remain
on the public line. TEST publication is unchanged.

The default authored manifest stays empty, the shipping body has no custom
profile marker, and rehearsal is disabled until explicitly selected. Supporting
inert resources do not activate artist profiles, localized skins or a custom
animation export. Existing tracks and custom-pose ownership remain protected.

The thirteen original animation source FBXs include the already-tested constant
`aim_target` helper translation relative to alpha59. Non-helper tracks and helper
rotations must remain preserved; whole-file identity against alpha59 is not
claimed. The final candidate must match tested TEST98 source/resource bytes
apart from channel/version metadata and retain the public publication boundary.

Clean SDK compilation, the material/FX splice, full pipeline, committed schema-3
receipt, hosted PR/exact-default QA and canonical VMB publication are pending.
Only fresh item-specific native start/outcome/finish-OK evidence plus matching
Steam metadata can advance the live public row. Historical tags and receipts
retain their original source commits.

The game is absent on the publishing machine. The maintainer's publication-only
exception applies; no local/remote deployment or new local game launch is
claimed. Crunch's TEST98 report and the maintainer's promotion approval are the
runtime acceptance evidence for this port. Visual refinements and separate open
issues remain recorded rather than being inferred from offline tests.

## Reporting and channel boundaries

Use the [public issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
for the installed alpha and the [development tracker](https://github.com/Ensrick/doomrocket-private/issues)
for TEST work. Enable exactly one Workshop channel and report the actual loaded
banner. Written observations and a matching log suffice; no video, second
player or arranged lobby is a standing requirement. Follow each issue's current
instructions and preserve accepted observations after later releases.

See the [promotion record](docs/releases/v0.1.60-alpha.md) and
[canonical release method](docs/RELEASE_CHANNELS.md).
