# Architecture review, 2026-09-14

Prompted by a standing instruction rather than by a bug: apply SRP and
modularity, and check that the patcher's translation to the web is tied up.

Both halves found something. The web-parity half found a **safety gap**, which
is recorded first because it is the one that could have reached a user.

## 1. The parity gap: the browser verified 9 things where the CLI verifies 21

`src/dnfw/firmware/verify.py` runs six kinds of check. `site/js/firmware.js` ran
four.

| check | Python | JS (before) |
|---|---|---|
| transport packet checksums | ✓ | ✓ |
| container content checksum | ✓ | ✓ |
| section byte-sum (×6) | ✓ | ✓ |
| **section padded to 4 bytes (×6)** | ✓ | **missing** |
| **section within Elektron's limits (×6)** | ✓ | **missing** |
| HMAC-SHA256 trailer | ✓ | ✓ |
| | **21 checks** | **9 checks** |

**Both missing checks guard the failure this project has actually hit.** From
the modules' own docstrings:

- padding — *"Images built without it boot through the normal update path and
  stall in recovery"* (`container/section.py`)
- limits — *"images of ours with no window boot through the normal update path
  and stall in the Early Start-up Menu's recovery flash"* (`codec/limits.py`)

The browser's own packer is bounded and its own section builder pads, so it
could not produce a violating image. **That is not a defence.** `verify` exists
to check the artifact, not to trust the producer — a verifier that passes only
because of what it knows about its own upstream is verifying its own
intentions, which is the exact phrase written into `transients-page.js` about
the download gate and then not applied one module over.

**Fixed.** `site/js/profile.js` ports `codec/profile.py`, and `verify()` now
emits 21 checks matching the Python name for name. Confirmed end to end in
headless Chrome: `original verifies — 21/21`, `repacked rebuild verifies —
21/21`.

### The rest of the translation is sound

Every module the browser needs has a twin, and the twins agree byte for byte
where that is testable (`test/test_js_codec.py`, `test_js_firmware.py`,
`test_js_mod.py`):

    codec/aplib · aplibpack · limits · profile
    syx/encode87 · frame · checksum · transport
    container/ele3 · section
    integrity/checksum · digest · keyderive
    image/bootstream
    mods/transients · moddest
    firmware/{load,build,verify}  ->  firmware.js

The 40 Python modules **without** a twin are correctly without one: `cli/*`
(argv and files), `image/{objdump,capstone_m68k,ghidra_listing,instruction,
functions,anchors,symbols}` (disassembly), `patch/*` (code injection),
`symbolmap/*`, `params/*`. None of that belongs in a browser tab.

## 2. SRP: one god file, and 127 lines of copy-paste

### `app/transients-page.js` — 565 lines, 20 functions, six subjects

Audio context and playback; waveform rendering; slot-card DOM; tuning controls;
firmware loading and facts; build and download; status. Its own docstring says
"wiring, and nothing else", which was true of its *role* and false of its size.

### And `destinations-page.js` was 73% copied from it

Measured: **127 of its 174 lines** were duplicates of six functions —
`wireDrop`, `addFact`, `showChecks`, `status`, `openFirmware`, `buildImage` —
already diverging in wording. Both files were written the same day, which is the
worst case: the duplication was not inherited, it was created.

**Fixed.** `app/shell.js` holds what every tool page does the same way.

| | before | after |
|---|---|---|
| `transients-page.js` | 565 | **446** |
| `destinations-page.js` | 174 | **75** |
| `shell.js` | — | 164 |
| total | 739 | 685 |

The saving is small; that is not the point. The point is that the two rules
about what reaches a user — *nothing is offered that has not verified*, and *a
file that does not verify stops there* — now live in one place instead of two
copies that had already started to drift.

Both pages were re-rendered end to end in headless Chrome afterwards: load,
verify 21/21, apply, rebuild, verify 21/21, download offered, **no page errors**.

## 3. Violations found and NOT fixed

Recorded rather than quietly carried. None is urgent; all are real.

### `cli/mods.py` holds a library model — **mine, today**

`_staged`, `_Restaged`, `_Firmware`, `_Container` (57 lines) implement "a
firmware whose sections are overridden by already-applied payloads". That is a
mods-system concept, and `docs/PRINCIPLES.md` is explicit: *"cli/ does argument
handling and I/O only — the work lives in the library module it calls."*

It belongs in `src/dnfw/mods/`. It went into the CLI because that is where I was
typing.

### `cli/mods.py` dispatches on a mod's identity

```python
if mod.ID == "transients":
    result = _apply_transients(mod, staged, args)
else:
    result = mod.apply(staged)
```

A generic path that special-cases one member is not generic. A mod should
declare what inputs it needs — `transients` wants a directory of samples,
`moddest` wants nothing — and the CLI should read that declaration. This will
get worse with mod three.

### `mods/transients.py` mixes the mod with audio I/O

319 lines, of which `read_wav`, `prepare` and `read_options` (~130) are WAV
decoding, resampling, onset detection and CSV parsing. Those are not "the FM
drum transient bank".

**The JavaScript is better factored than the Python here** — `audio.js` is
separate from `mods/transients.js`, and split deliberately so the untestable
half (Web Audio) is isolated from the half that makes judgement calls. The
Python should follow its own port.

### `patch/cave.py` — 435 lines, the largest module in the tree

Not examined in this review. Flagged because size is a symptom worth looking
at, not because anything is known to be wrong with it.

## 4. What is right, and worth not breaking

- **The two implementations mirror each other's module names.** `syx/`,
  `container/`, `integrity/`, `mods/` exist in both, so a reader comparing them
  can see drift. That was a deliberate choice and it paid off in this review:
  the missing `profile` twin was visible from a directory listing.
- **Every capability is reachable from `dnfw`.** No orphan scripts implementing
  things the CLI cannot do.
- **`firmware.js` merging load/build/verify** is a judgement call, not an
  oversight: the three Python modules share one subject in the browser — the
  order the layers run in — and it is 172 lines. Left alone.
- **No firmware bytes in the repository**, in either tree.

## 5. The pattern this review is an instance of

The parity gap and the duplication were both created **the same day** by the
same hand, and both were invisible from inside the work that created them. The
gap was found by listing two directories side by side; the duplication by
counting lines. Neither needed insight, only a different question than the one
being asked while building.

That is the same shape as every detector failure in `docs/pcm-hunt.md`: the
instrument was fine, the question was wrong. Worth scheduling this review again
rather than waiting for the next standing instruction.
