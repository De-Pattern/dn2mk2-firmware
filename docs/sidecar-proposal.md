# Proposed contribution: native Sidecar parts on DN2MK2 0.72

Local maintainer handoff draft. Not sent, published or accepted upstream.

## Problem and resulting behavior

External Pi synths currently require a separate custom DN2 firmware branch.
This contribution adds a generic Sidecar endpoint to dn2mk2 so compatible Pi
packages can appear by name in native MACHINE SEL, supply their parameter labels
over up to two SYN pages, receive knobs/locks and saved sound identity, and use
the assigned track's native filter, AMP, pan and FX sends.

For example, install the existing public SC Snare RMP on a compatible Sidecar
Pi and select SNARE on the DN2. The DN2 stores `sc.snare` and its controls; there
is no SC Snare entry or DSP implementation compiled into DN2 firmware. Up to
eight parts have independent saved identities and native processing lanes.

## Scope and review order

Based on the exact v0.72 release, using Elektron OS 1.11:

1. Portable event encoding and persistent identity/control representation.
2. Native capture/session/USB, catalog/selection/pages and native audio returns.
3. Synthetic cross-repository fixtures, public-plugin interoperability and docs.
4. Generated ColdFire patch data and shared DSP-tail objects for this base.

The current integration uses existing native record space and preserves the
legacy eleven-control identity. No private engine implementation, source/resource
snapshot, private library inventory, firmware image or device configuration is
part of the contribution. Native v0.72 synth objects and guard weights are kept.

The Pi-side companion is a separate clean Sidecar branch; it is required for
the feature but does not need a release number matching dn2mk2. The shared wire
fixtures and [maintenance contract](sidecar-maintenance.md) describe the boundary.
The companion and this branch have disabled push destinations until publication
is explicitly authorized. Replace local checkout references with the final
companion contribution link when actually submitting.

## What reviewers can reproduce

See [review/build instructions](sidecar-review.md). The focused checks compile
the actual native client/capture code, run the saved-sound converters, exchange
metadata with the real Pi server using synthetic fixtures and public SC Snare,
and execute the packaged return tail against ownership/isolation cases.
The source generator checks its stock instructions and exact patch replay.

An offline combined image is built only as a verification artifact. Preflight
integrity success is not a release clearance. No v0.72 image from this branch
has been flashed or booted on hardware, and no physical test result is claimed.
Full project filesystem recall, worst-case playback and latency remain release
acceptance items. The complete native binding extraction and capability exchange
are follow-up work, not features silently promised by this patch.

## Maintainer decisions

- Whether to merge the full feature together or review the wire/storage,
  native UI/control and native-return layers in separate dependent changes.
- The preferred location/ownership of the OS 1.11 binding and future ports.
- Whether normal releases include the endpoint directly or select it through an
  existing build option; avoid a second post-release binary patch for users.
- The agreed protocol compatibility policy and scope of a later capability query.

These are proposal points, not demands to change the maintainer's release gates
or accept new private plugin dependencies.
