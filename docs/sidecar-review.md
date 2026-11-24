# Sidecar bridge review candidate

This source candidate lets a native Digitone II track select a Pi engine by its
manifest name, edit up to sixteen controls over two SYN pages, retain the full
engine identity in saved sounds, and send events to Sidecar. Eight independent
mono returns enter the assigned voices before native filter/AMP/pan/FX sends.
New compatible engines require a Pi package, not a new per-engine DN2 patch.

The baseline is dn2mk2 v0.70 on Elektron OS 1.11, matching the development source
this work was extracted from. Newer upstream changes are not silently mixed in.
This is a source-review branch, not a new flashable release.

## Included and excluded

- Portable event encoder and ID validation; stable generic ID/control storage.
- Bounded capture/USB/session handling and reconnect/ownership behavior.
- Manifest-driven catalog, selection, native pages and parameter formatting.
- Native-return generator and guarded integration with existing firmware hooks.
- Original fixtures and focused compiled tests, including saved-sound conversion.
- No Pi drum DSP, plugin manifests/resources, device credentials, recordings,
  prototype history, or new generated firmware payloads.

The legacy eleven-control layout and `mega.perkons` ID are frozen compatibility
data for existing sounds. They contain no engine implementation and no import of
a private Pi manifest. New machines use the dynamic catalog and sixteen-control
layout. These compatibility records must not be repurposed during cleanup.

The existing version-specific addresses/layouts remain in the adapter and
generator. A fully abstracted host binding is future work, not part of this
extraction. Unknown Elektron versions remain unsupported.

## Focused validation

Use the repository's existing Python/ColdFire/Unicorn environment. Set
`SIDECAR_BRIDGE_ROOT` to the paired Sidecar checkout; the default expects
`../sidecar-bridge-public`. `DNFW_STOCK_111` may point to the owner's stock 1.11
archive; the default remains `00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip`.
The upstream composer also requires its existing owner-supplied MD/MNM firmware
resources (`MD_OS_BIN`, `MNM_OS`). Those inputs are not distributed here.

```
python -m pytest -q test/test_sidecar_pages.py test/test_sidecar_capture.py test/test_sidecar_usb.py test/test_sidecar_ui.py test/test_sidecar_machlist.py test/test_sidecar_native_return.py test/test_sidecar_recovery.py
```

On Windows, add `-p no:faulthandler` for the known Unicorn mapping diagnostic.
Metadata tests generate original, non-executable RMP fixtures in the paired
Sidecar checkout; no private package or DSP compilation is needed. Saved-sound
tests write packets under ignored `out/sidecar-recovery/`; consume those with:

```
python tools/dn2/check_dn2.py --recovery-only ../dn2mk2-bridge-public/out/sidecar-recovery/saved-parts.bin
```

Run that last command from the paired Sidecar checkout. Pure wire checks there
do not require stock ROMs. Test receipts distinguish skips from passes. No check
flashes or sends MIDI, and this adds no new mandatory full-build gate.

## Generated files and release boundary

Recorded extraction check (2026-11-24): all 125 focused tests above passed
(no skips; 8 minutes 13 seconds). The saved eight-part packets also passed the
paired Pi session/receiver check. This was a one-time source-extraction check;
the whole set is not a new mandatory gate for individual plugin/bridge edits.
The standalone shared wire check passed fourteen frozen events through both
host C/C++ and compiled ColdFire execution.

Generated ColdFire patch JSON and DSP objects are deliberately left at their
upstream baseline in this source candidate. **Do not build a flash image from
those stale generated files.** Before preparing a firmware candidate, regenerate
the native-return tail with `scripts/gen_sidecar_tail.py --selas PATH`, then
`scripts/gen_waverider_code.py` using the supported stock input and existing
toolchains. Review the generated changes and run the applicable integrity,
compiled routing and hardware checks. Follow the maintainer's release process
when preparing an actual release; no release is being offered here.

Offline capture/converter/UI checks are not a project filesystem save/reopen,
full boot, physical latency or worst-case eight-part playback qualification.
The paired [Sidecar protocol](../../sidecar-bridge-public/docs/dn2/PROTOCOL.md)
defines the current event/session boundary and its limits.
