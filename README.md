# Warlock Engineer — public alpha

[![Repository quality](https://github.com/Ensrick/doomrocket-public/actions/workflows/repository-quality.yml/badge.svg)](https://github.com/Ensrick/doomrocket-public/actions/workflows/repository-quality.yml)

Public release source for Warlock Engineer, the mod that adds the Warprocket Bombardier enemy to Vermintide 2.

- [Public-alpha Workshop build](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344)
- [Report a public-build bug](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
- [Experimental development repository](https://github.com/Ensrick/doomrocket-private)
- [Clearly marked TEST Workshop build](https://steamcommunity.com/sharedfiles/filedetails/?id=3794172730)
- [Current project status](PROJECT_STATUS.md)

The public alpha retains the accepted body/weapon artwork and portrait.
[v0.1.59-alpha](docs/releases/v0.1.59-alpha.md) is published and verified.

**v0.1.60-alpha is in preparation and has not been published.** The maintainer
authorized promoting the improved tested default Warlock from TEST v0.1.98-dev.
The selected scope includes the hose W-shape correction with the accepted sway
settings, more convincing blended vault/fall/landing motion, accepted flame and
balance changes, and the associated aiming, sound and compatibility fixes.
Existing animation tracks and custom-pose ownership remain preserved. A stronger
hose W shape remains a refinement; the separate custom-animation export and
other open reports are not declared complete.

See [project status](PROJECT_STATUS.md) and the
[alpha60 promotion record](docs/releases/v0.1.60-alpha.md) for preparation and
publication evidence. The original [alpha59 record](docs/releases/v0.1.59-alpha.md)
retains its historical source and acceptance scope.

Do not enable the public and TEST Workshop builds simultaneously. Every player
in a lobby must install and enable the same version.

## Installation

1. Subscribe to [Vermintide Mod Framework](https://steamcommunity.com/sharedfiles/filedetails/?id=1369573612).
2. Subscribe to the [Warlock Engineer public alpha](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344).
3. In the Vermintide mod launcher, enable both and place Vermintide Mod
   Framework above Warlock Engineer in the load order.
4. Launch the **Modded Realm**. This mod is not sanctioned for the Official
   Realm.

## Reporting bugs and feedback

Use the [public issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
and select the form that matches what happened:

- **Gameplay or presentation bug** for spawning, combat, rockets, models,
  textures, animation, sound, or multiplayer behavior.
- **Crash report** when Vermintide closes or displays a crash/assertion dialog.
- **Balance or design feedback** for difficulty, damage, health, behavior, or
  feature suggestions.

Before filing, restart the game after the Workshop update, copy the actual
`[doomrocket:LOAD]` banner, and make sure the TEST build is disabled. The
currently verified banner is `[doomrocket:LOAD] v0.1.59-alpha`. Once the alpha60
publication record is verified, its banner will be `[doomrocket:LOAD] v0.1.60-alpha`.
Use the version actually loaded when reporting a result.
Attach the complete console log from
`%APPDATA%\Fatshark\Vermintide 2\console_logs\`; do not paste the entire file
into the issue body. See [Bug-reporting instructions](docs/BUG_REPORTING.md) for
the short checklist.

## Contributing

Player reports should use the issue chooser above. Code and documentation
contributions are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) before opening
a pull request. Experimental gameplay changes belong in the development
repository until they pass in-game acceptance.

For routine playtests, use the copyable [public-alpha tester checklist](docs/TESTER_CHECKLIST.md).
