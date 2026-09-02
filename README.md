# Warprocket Bombardier — public alpha

[![Repository quality](https://github.com/Ensrick/doomrocket-public/actions/workflows/repository-quality.yml/badge.svg)](https://github.com/Ensrick/doomrocket-public/actions/workflows/repository-quality.yml)

Public release source for the Warprocket Bombardier enemy mod for Vermintide 2.

- [Public-alpha Workshop build](https://steamcommunity.com/sharedfiles/filedetails/?id=3771657344)
- [Report a public-build bug](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
- [Experimental development repository](https://github.com/Ensrick/doomrocket-private)
- [Clearly marked TEST Workshop build](https://steamcommunity.com/sharedfiles/filedetails/?id=3794172730)
- [Current project status](PROJECT_STATUS.md)

The public alpha is deliberately based on the runtime-accepted `v0.1.55`
baseline. Experimental survivability, shove, ballistic-aim, and custom-audio
work remains isolated on the development line until it passes in-game testing.

Do not enable the public and TEST Workshop builds simultaneously. Every player
in a lobby must install and enable the same version.

## Reporting bugs and feedback

Use the [public issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
and select the form that matches what happened:

- **Gameplay or presentation bug** for spawning, combat, rockets, models,
  textures, animation, sound, or multiplayer behavior.
- **Crash report** when Vermintide closes or displays a crash/assertion dialog.
- **Balance or design feedback** for difficulty, damage, health, behavior, or
  feature suggestions.

Before filing, restart the game after the Workshop update, verify the log says
`[doomrocket:LOAD] v0.1.55-alpha`, and make sure the TEST build is disabled.
Attach the complete console log from
`%APPDATA%\Fatshark\Vermintide 2\console_logs\`; do not paste the entire file
into the issue body. See [Bug-reporting instructions](docs/BUG_REPORTING.md) for
the short checklist.

## Contributing

Player reports should use the issue chooser above. Code and documentation
contributions are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) before opening
a pull request. Experimental gameplay changes belong in the development
repository until they pass in-game acceptance.
