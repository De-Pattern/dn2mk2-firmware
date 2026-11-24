# Sidecar bridge review candidate

This source candidate lets a native Digitone II track select a Pi engine by its
manifest name, edit up to sixteen controls over two SYN pages, retain the full
engine identity in saved sounds, and send events to Sidecar. Eight independent
mono returns enter the assigned voices before native filter/AMP/pan/FX sends.
New compatible engines require a Pi package, not a new per-engine DN2 patch.

The merge proposal is on `propose/sidecar-native`, based on current upstream
`main`: **v0.72** plus its OS-version documentation update. Executable sources
and generated payloads are identical to the verified v0.72 candidate. The
underlying Elektron OS remains **1.11**; documenting 1.12 does not port the bridge.
The earlier `review/dn2-bridge` and `review/dn2-bridge-v072` branches are retained.
This is a review candidate, not a new firmware release.

Maintainer-facing description: [proposed contribution](sidecar-proposal.md).
Release ownership and version boundaries: [maintenance](sidecar-maintenance.md).

## Included and excluded

- Portable event encoder and ID validation; stable generic ID/control storage.
- Bounded capture/USB/session handling and reconnect/ownership behavior.
- Manifest-driven catalog, selection, native pages and parameter formatting.
- Native-return generator and guarded integration with existing firmware hooks.
- Original fixtures and focused compiled tests, including saved-sound conversion.
- Regenerated ColdFire patch data and only the shared DSP return-routing tail;
  every other v0.72 DSP object and the v0.72 native guard weights are retained.
- No private Pi drum DSP, plugin manifests/resources, device credentials,
  recordings, prototype history or full firmware images.

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

For the optional playable public demo, first build SC Snare using the paired
Sidecar checkout's `tools/dn2/build_public_demo.py --a64-bin PATH`. Set
`SIDECAR_DEMO_PACKAGE` to its `build/dn2/public-demo/sc_snare.a64.rmp`, then run
`test/test_sidecar_ui.py::test_compiled_metadata_transactions`. This exercises
the real package's metadata through the compiled native client and Pi server;
it does not render the plugin's DSP or install anything.

## Generated files and release boundary

Merge-proposal follow-up (2026-11-24): **125 passed, no skips, in 1 minute
43 seconds** on Windows/Python 3.14 with the ColdFire compiler and Unicorn.
This is a fresh complete focused run against the updated Sidecar `dev` companion,
including public SC Snare. Session-scoped cached compilation avoids rebuilding
the native client separately for each test module. The fourteen frozen wire
events and the paired saved eight-part receiver check also pass after the rebase.
The current test log is `out/sidecar-v072/merge-target-tests.log`.
The shareable [validation receipt](sidecar-validation.json) records code revisions,
commands, results and limits without local resource paths or raw device data.

Recorded v0.72 integration checks (2026-11-24):

- The focused suite completed in 4 minutes 36 seconds: 124 passed and one
  public-demo assertion failed. SC Snare has ten controls; its six unused cells
  were correctly hidden, while the test expected sixteen populated cells.
  After correcting that expectation, the affected metadata test and saved-part
  recovery test both passed in 29 seconds. No runtime change was needed.
  All 125 cases therefore have passing evidence; the entire suite was not rerun
  after the assertion-only correction.
- The compiled metadata client accepted all three synthetic manifests and the
  unmodified public `sc.snare` package, including page formatting and unused cells.
- Saved eight-part packets passed the paired Pi session/receiver check.
- Fourteen frozen events matched host C/C++ and compiled ColdFire encoding.
- All five packaged DSP-tail ownership/routing cases passed, including register
  preservation, empty/disabled ownership and duplicate/invalid assignments.
- The combined verification image passed byte-integrity preflight. The freshly
  compiled native chunks match the regenerated patch data.

Receipts are in ignored `out/sidecar-v072/`, `out/sidecar-ui-client.json`,
`out/sidecar-pages-compile-report.json` and `out/sidecar-recovery/`; paired host
receipts are under Sidecar's `build/dn2/`. These are one-time integration checks,
not a new mandatory full-build gate for individual plugin or bridge edits.

The v0.72 candidate includes regenerated ColdFire patch JSON and native-return
tail objects. The generator verifies stock instructions, allocation bounds and
exact replay of generated edits. The DSP audit confirms all v0.72 objects except
the shared return tail are unchanged, including the optimized native engines.

For later source edits, regenerate the return tail with
`scripts/gen_sidecar_tail.py --selas PATH` when its generator changes, and
`scripts/gen_waverider_code.py` when native UI/capture bindings change. The latter
accepts `DNFW_STOCK_111` as well as the usual resource directory. Reuse unchanged
engine objects; do not regenerate every native synth for a bridge-only edit.

A local combined image has been built and passed preflight integrity checks.
That is not full boot, real-time or hardware qualification and does not clear
the image for flashing. Follow the maintainer's release process when preparing
an actual release; no release is being offered here.

Offline capture/converter/UI checks are not a project filesystem save/reopen,
full boot, physical latency or worst-case eight-part playback qualification.
The companion Sidecar repository's `docs/dn2/PROTOCOL.md` defines the current
event/session boundary and its limits. Its `propose/dn2-native` branch targets
Sidecar `dev`; include that source/patch series when submitting this proposal.
