# Reporting public-alpha bugs

Use the [issue chooser](https://github.com/Ensrick/doomrocket-public/issues/new/choose)
and select the form that matches the report:

- **Gameplay or presentation bug** — spawning, combat, rockets, models,
  textures, animation, sound, or multiplayer behavior.
- **Crash report** — the game closed, froze, or displayed a crash/assertion
  dialog.
- **Balance or design feedback** — difficulty, damage, health, behavior, or a
  focused feature suggestion.

Do not use this repository for the experimental TEST Workshop item. Report TEST
build problems in the
[development issue tracker](https://github.com/Ensrick/doomrocket-private/issues/new/choose).

## Before filing

1. Let Steam finish updating the mod, then restart Vermintide 2.
2. Enable only the public Workshop item `3771657344`. Do not enable the TEST
   item at the same time.
3. In multiplayer, confirm every player has the same build installed and
   enabled.
4. Reproduce the problem once more if it is safe to do so.
5. Record whether you were the host, a remote client, or playing solo.

## Attach the correct console log

Press `Win+R`, paste the following path, and press Enter:

```text
%APPDATA%\Fatshark\Vermintide 2\console_logs\
```

Choose the newest `console-YYYY-MM-DD-HH.MM.SS-<guid>.log` file from the session
where the problem happened. Verify that it contains:

```text
[doomrocket:LOAD] v0.1.55-alpha
```

Attach the complete file to the form; do not paste the entire log into the
issue body. GitHub accepts `.log` directly up to 25 MB. If the browser still
rejects it, place the log in a `.zip` file and attach that instead.

For a crash, also copy the crash GUID or `crashify://` link from the crash
dialog. The console log and crash report must come from the same game session.

## Privacy

This is a public repository. Issue text and attachments can be viewed by
anyone. Review logs, screenshots, and videos before uploading them and remove
unrelated personal information when necessary. Do not remove game or mod log
lines needed to diagnose the problem.
