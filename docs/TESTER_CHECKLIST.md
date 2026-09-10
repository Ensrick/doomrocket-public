# Public-alpha tester checklist

This is the short checklist for Workshop item `3771657344`. It is suitable for
copying into Discord. **Wait for verified v0.1.56-alpha publication before
testing this update.** An older loaded banner does not test the candidate.

```text
WARPROCKET BOMBARDIER v0.1.56-alpha — QUICK TEST

Setup
[ ] Let Steam finish the Workshop update, then restart Vermintide.
[ ] Launch the Modded Realm.
[ ] Load Vermintide Mod Framework above Warprocket Bombardier.
[ ] Enable the public alpha only; disable the TEST build.
[ ] Confirm the log contains: [doomrocket:LOAD] v0.1.56-alpha
[ ] Record whether you are host, remote client, or solo.

New portrait
[ ] Kill a Bombardier and check the new small Warlock Engineer kill-feed icon.
[ ] Verify the red warhead, green highlights, native size and normal orientation.
[ ] Compare the host and remote-client kill feeds; attach a screenshot of each.

Career-change safety (controlled Keep test)
[ ] With one living Bombardier, switch careers repeatedly during aim/fire/reload.
[ ] Repeat with one dead and one living Bombardier; no crash or stuck attack.
[ ] After the switch, the living enemy acquires a valid target and fires normally.

Enemy and weapon
[ ] Living model and textures look correct; no hidden ratling model is visible.
[ ] Launcher sits correctly in the hands while firing and on the back when stowed.
[ ] A fired rocket can hit normally and can be shot down by a player.
[ ] Each rocket detonates once and disappears; no repeated explosions remain.

Death and ragdoll
[ ] Kill one Bombardier normally and watch the full corpse transition.
[ ] Corpse remains the Warlock model and ragdolls without stretching or floating.
[ ] Launcher and loaded warhead fall with the corpse; neither floats in place.
[ ] Repeat with several ordinary deaths, keeping dense corpse-pile stress separate.

Evidence
[ ] Note exact reproduction steps and whether the problem happens every time.
[ ] For a crash, copy the crash GUID/Crashify link.
[ ] Attach the complete matching console log from:
    %APPDATA%\Fatshark\Vermintide 2\console_logs\
[ ] Submit through: https://github.com/Ensrick/doomrocket-public/issues/new/choose
```

Do not treat a static test or a clean log as proof of correct visuals. Report
what was visibly observed and attach the matching log. This public build does
not contain the TEST kick/reposition, armor/health, ballistic-aim, custom-audio,
or explosion changes; do not expect those features in this checklist.
