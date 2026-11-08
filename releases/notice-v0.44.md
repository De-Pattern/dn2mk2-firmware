# ⚠️ v0.44 withdrawn: BOUNCE can freeze your unit

loading a BOUNCE machine on v0.44 can crash the DN2, and it can stay frozen on the boot screen after you restart it. v0.44 is off the patcher

**if your unit is stuck**
1. power off, then hold **FUNC** while powering on: the STARTUP menu
2. **TRIG 2: EMPTY RESET.** it clears the working project only. everything on your +Drive (projects, samples, the library) is safe
3. if the startup menu doesn't come up: **TRIG 4: OS UPGRADE** from that menu takes v0.43 or stock 1.11 over DIN MIDI (Elektron Transfer)

**until the fix**
- flash v0.43 from the patcher (or stock 1.11)
- don't load a project that has a BOUNCE track in it

thanks depaffect for the report, and sorry. the fix is in progress, and it gets its own test against this freeze before anything ships

patcher: de-pattern.github.io/dn2mk2/patcher.html · not made or supported by Elektron
