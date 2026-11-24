# Add eight native Sidecar parts with manifest-driven machine pages

Contribution for `De-Pattern/dn2mk2-firmware:main`, requesting review for inclusion
in the normal build. This is a source contribution, not a firmware release.

## What changes

A Digitone II track can select an engine running on a Sidecar Pi from native
MACHINE SEL, edit its named controls on up to two SYN pages, and sequence those
controls with parameter locks. Eight mono returns enter the assigned native
voices before filter, AMP, pan and FX sends. The eight-part session uses tracks
1-8; tracks 9-16 remain available for native machines.

The DN2 stores the engine's full ID and up to sixteen fractional parameter
values. Compatible engines supply their names, defaults, ranges and enums from
Pi metadata. Adding one does not require a DN2 machine definition or reflash.
The public SC Snare plugin demonstrates this without any external drum library.

This targets current `main` (v0.72 plus the OS-version documentation update),
using **Elektron OS 1.11**. It does not add OS 1.12 support. All v0.72 native
synth DSP objects and guard weights are retained; only the shared return tail
and native control/UI patch data are regenerated.

## Companion and compatibility

The required Pi endpoint is available on the [experimental Sidecar branch](https://github.com/Ericxgao/sidecar-firmware/tree/propose/dn2-native),
based on Sidecar `dev`. Upstream Sidecar releases without that endpoint do not
provide DN2 native parts. Users currently need both modified codebases; public
built-ins and SC Snare suffice, with no private plugin library required.
Neither endpoint requires the other's product version number to
match: the event, session and metadata formats are the compatibility boundary.

Without a matching ACK/RESET session the Pi cannot take native return ownership.
The existing legacy sound identity remains readable. Generic sounds retain full
IDs rather than catalog positions or cache slots; unavailable engines are not
silently replaced. No plugin DSP, sample bank, firmware image or device settings
are included in this contribution.

## Review order

1. Portable event encoding and saved identity (`csrc/sidecar/wire.c`, `sound.c`).
2. Native capture, bounded USB/session handling and catalog/page integration.
3. Eight-lane ownership and the generated DSP return tail.
4. Compiled tests, public fixtures and generated patch data.

The firmware-specific bindings remain in the DN2 adapter. Moving those behind a
single host interface and adding capability negotiation are separate follow-ups;
neither is necessary for compatible plugins within today's sixteen-control ABI.

## Validation

Exact commands, evidence and limitations are in [the review guide](https://github.com/Ericxgao/dn2mk2-firmware/blob/propose/sidecar-native/docs/sidecar-review.md)
and [validation receipt](https://github.com/Ericxgao/dn2mk2-firmware/blob/propose/sidecar-native/docs/sidecar-validation.json).
All 125 focused DN2 tests passed without skips. Fourteen frozen wire events and
saved eight-part packets also passed their Pi receiver checks.
The source-integrated image passed integrity preflight and all five packaged
DSP-tail routing/register-preservation cases. Compiled native UI/capture/storage
tests, frozen wire events and saved eight-part packets are covered by focused
checks. The SC Snare package's actual metadata is exchanged with the Pi server
by the compiled DN2 client; this is not an audio-rendering test.

**Not a flash release:** this newly integrated image has not been booted or
qualified on hardware. Full project filesystem save/reopen, worst-case playback,
physical latency/alignment and the maintainer's complete shipping gate remain
release acceptance work. No change to release policy or bypass is proposed.

## Requested review

Please review the native binding locations and return ownership/storage contract
for inclusion in the normal DN2MK2 build. This would let users install ordinary
DN2MK2 updates without maintaining a separate per-release Sidecar patch. The
Pi companion can be reviewed separately; it need not be released simultaneously.

This is AI-assisted work developed primarily for personal use. I'm offering the
generic integration for adoption, but cannot commit to maintaining either fork
independently across future releases or providing ongoing public support. The
Pi side is being shared for adoption discussion, not presented as an officially
supported Sidecar DN2 edition. I would appreciate a decision on whether this
endpoint and its native bindings are a fit for DN2MK2 to own upstream.
