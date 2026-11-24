# Owning the Sidecar bridge across releases

## One protocol, two independently maintained endpoints

The DN2 endpoint belongs in dn2mk2's regular source/build pipeline. The Pi
endpoint belongs in Sidecar. External engines remain separate RMP packages;
neither maintainer needs a private drum library to build or test the adapter.
If only dn2mk2 merges first, an existing compatible Pi build can continue serving
new DN2 releases. Pi upstream inclusion is useful but not a prerequisite for
removing the user's per-release DN2 patch/rebase step.

Release numbers are not wire versions. A dn2mk2 update on the same Elektron OS
does not inherently require a Pi update. A compatible new RMP package does not
require either firmware to change. Preserve full engine IDs and P positions;
never save catalog-row or Pi cache-slot numbers as identities.

## Current compatibility boundary

| Boundary | Current contract |
|---|---|
| Events | v1 eleven-control legacy; v2 full ID and sixteen fractional controls |
| Session | Token/lease, ACK then RESET, requested track(s) and return mode |
| Metadata | v2 catalog/load/pages; v3 contextual metadata for existing built-ins |
| Parts/returns | Eight independently owned mono lanes, before native processing |
| Panel/catalog | Sixteen controls, at most two SYN pages, 32 catalog entries |
| Saved sounds | Full canonical ID plus corruption detection; legacy records retained |

Frozen wire fixtures live in the paired Sidecar repository under
`docs/dn2/fixtures/events.json`; its contract checker compiles this repository's
actual portable encoder. The public SC Snare plugin provides an installable
demo. Generated metadata-only fixtures exercise enums and all sixteen controls
without proprietary DSP, samples or hardware.

This is NOT a general capability-negotiation implementation. There is no new
capability message in this contribution. Expanding capacities/widgets/formats
needs an agreed, backward-compatible feature exchange and rejection behavior.
Do not infer support from a product release number or silently change packet
sizes/parameter meanings. Existing endpoints reject unsupported versions/modes.

## Firmware bindings: explicit remaining work

The portable wire codec has no firmware addresses. The full native host binding
is not abstracted yet; these are the files the DN2 maintainer owns when the
underlying Elektron image or native layout changes:

| Responsibility | Binding and integration files |
|---|---|
| Hook sites, allocation reservations, native page dispatch | `src/dnfw/waverider/coldfire.py`, `pages.py`, `cpage.py` |
| Frame layout, task notification and session state | `csrc/sidecar/bridge.c`, `hooks.S` |
| Stored sound layout and native record domains | `csrc/sidecar/sound.c`, `src/dnfw/sidecar/machines.py`, sampler formatting hooks |
| Native UI objects, selection and track pointers | `csrc/sidecar/ui_page.c`, `select.c`, `machlist.c`, sampler integration |
| Bounded native USB admission | `csrc/sidecar/usb.c` |
| DSP ownership, frame publication and return insertion | `src/dnfw/sidecar/native_return.py`, `scripts/gen_ping_asm.py`, `src/dnfw/waverider/dsp.py` |

The recommended follow-up is one versioned native host interface following the
maintainer's conventions, not a second firmware patch generator. Retain existing
stock-byte guards and generation checks. OS 1.12 or any other base is not
qualified by this OS 1.11 contribution.

## Keeping checks proportionate

- Protocol edit: shared frozen fixtures plus affected session/receiver tests.
- UI/storage edit: compiled page/selection or converter cases for that path.
- Native-return edit: model checks and packaged DSP-tail execution.
- New compatible plugin: that plugin's package/DSP checks and metadata; no DN2 build.
- Release integration: generated payload freshness, byte integrity and relevant
  boot/hardware acceptance under the maintainer's normal release process.

The compiled DN2 runtime and Pi metadata test server are session-scoped pytest
fixtures, so a combined focused run does not rebuild them for each module.
Synthetic tests do not replace live project save/reopen, low-latency measurement
or worst-case eight-part playback. Those remain explicit release acceptance work.
