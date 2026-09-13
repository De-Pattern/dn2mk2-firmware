# Ideas parked for later

Deliberately kept rather than discarded — a path that is closed *today* is still
a signal, and several of these become the obvious move once the fourth LFO is
done or once we start on the DN1. Each entry says what it is, what it would buy,
and what would have to be true for it to work.

Nothing here is scheduled. The active work is `docs/lfo4-feasibility.md`.

---

## 1. Reclaiming space by removing a feature

**The idea.** 1.11 added a whole container section (id 8, ~160 KB) for the
Outbox. If Elektron can add a section, could we delete one we do not use — the
Outbox — and spend the space on a fourth LFO? And more generally: is "sacrifice a
feature for room" a strategy?

**Why deleting section 8 does not buy what we need.** The ELE3 container's
sections are not all mapped into the CPU's address space. MAIN OS (id 3) loads
at `0x40000400` and executes there; section 8's `dest` is `0x00000000`, like
`blob` and `meta` — flash-resident **data** the OS reads, not code at a virtual
address. A fourth LFO's parameter records, page-view and hook stubs must live
**inside section 3's virtual address range**. Removing section 8 frees flash and
file size and adds **nothing** to that range. It also risks a boot fault: 1.11's
MAIN OS contains the Outbox code, and if anything loads that section at startup
(not only when hardware is attached), deleting it breaks the boot for no gain.

**The variant that does pay off: repurpose dead code inside section 3.** Pick a
feature whose *code* we are willing to sacrifice, prove nothing reaches it, and
its bytes become one large contiguous cave at a usable address — exactly "remove
a feature for room", aimed where room actually exists. What must be true:

- the region is genuinely dead (established by cross-reference analysis, not
  assumption), or its call sites are neutered / its entry made to return;
- we accept that every future diff against stock is harder to read.

**When to spend it.** Not yet. ~29 KB of padding in ~1 KB runs (1.11) is
probably enough for hook stubs plus a page-view. **Size the requirement first**
and only sacrifice a feature if the measurement says we must. This becomes much
more likely on the **DN1**, whose image is smaller and whose padding is
scarcer — which is where this strategy earns its keep.

> ### ⚠️ "~29 KB of padding in ~1 KB runs" is wrong. Corrected 2026-09-13.
>
> Those runs are **not padding**. Sixteen of them sit at a regular 0x40C stride
> from `0x40287ef6`, each 1,035 zero bytes followed by one `0xff` — a
> **16-element array of 1,036-byte records**, shipped zeroed and **written at
> runtime**. Sixteen is this machine's track and voice count.
>
> `dnfw cave scan` offered them because the bytes are zero, exactly as
> `docs/memory-map.md` warns it will: *a zero run is a candidate, not a
> blessing.* Caves were placed there anyway, the firmware overwrote them while
> the keyboard was played, and the device took an **address error with
> PC `0x40000042`** — a jump into what had been code and was now data
> (`docs/flashing.md`).
>
> So the free-space budget for hooks is **unmeasured**, not 29 KB, and a regular
> stride is positive evidence *against* a run being padding. The boot proof's
> cave at `0x4028ea02` is outside this array and has run without incident.

**Related, and also unresolved:** growing section 3 itself. Freed flash could in
principle let MAIN OS extend past its end (`0x4030b980` on 1.11), but that needs
the device's flash layout confirmed and the boundary above the loaded image
pinned, so new bytes cannot collide with anything. See `docs/memory-map.md`.

### 1a. The better half of the idea: **add** a section, do not delete one

*Raised by the owner 2026-09-13, from the Outbox observation above.*

This entry asked *"if Elektron can add a section, could we delete one?"* and
answered no. It never asked the other question, and that one is much better:

> **If Elektron can add a section, can we?**

Section 8 is the existence proof, and it is a strong one. In a single release
Elektron added a **new section id**, carrying a payload the ColdFire never
executes, at a `dest` of its own choosing, and the device accepts it. Nothing
about that mechanism is Outbox-specific.

**Why this is the right shape for LFO4.** Every cave problem this project has
had comes from *squatting*: finding bytes that look unused inside a section
built for something else, and being wrong about them — the `0x40287ef6` array
above being the expensive case. A section of our own has none of that. We choose
the `dest`, we know the length, and nothing else in the image claims it. No zero-
run hunting, no stride heuristics, no guessing whether a gap is real.

It also composes with the 25 MB above the BSS end (`docs/lfo4-slot-plan.md`):
that region is unclaimed but full of power-on garbage, so anything living there
must be initialised by our own code. A section with a `dest` **is** the
initialiser — the loader writes it before the OS runs, which is precisely the
service the extension array needs.

**What must be true, in order of how likely it is to kill the idea:**

1. **The updater accepts an unknown section id** rather than rejecting the
   image or faulting. This is the gate. Section 8 shows *Elektron's* new ids are
   accepted by the 1.11 updater — it does not show an id nobody has shipped is.
2. **The loader honours an arbitrary `dest`**, and writes it where we ask.
3. **Integrity survives.** The content checksum and the HMAC-SHA256 trailer are
   both ours to recompute (`docs/ele3-format.md`), so this is expected to be
   routine — but it is expected, not shown. **The "Multiplier" key material is
   not to be touched**, and adding a section does not require touching it.
4. **The `dest` does not collide** with anything the loader or BSS clear uses.

**Why it is testable now, which it was not last week.** Point 1 used to be
flash-and-find-out on the owner's hardware. **Section 4 is the updater**, and
`m-dwyer/digikit` runs section 4's code under emulation already — that is how it
depacks (`docs/emulator.md`). So the updater's section dispatch can be read
statically out of 32 KB of ColdFire, and exercised, without touching the device.

**Do this before building anything.** It is cheap, it is offline, and it decides
between "a section of our own" and "keep hunting for safe caves" — which is the
difference between a solved placement problem and the one that has bitten us
twice.

### 1b. Answered the same day: the updater looks sections up **by id**

Read out of the 1.11 updater (section 4, 32 KB, `0x80000400`), statically —
no device, no emulator run needed in the end.

`'ELE3'` occurs exactly once in the image, as an immediate:

```
80003cf8:  read 32 bytes of the container header
80003d1a:  movel #'ELE3',%d0
80003d20:  cmpl  0x8000b3d4,%d0        ; magic
80003d28:  moveq #52,%d0
80003d2a:  cmpl  0x8000b3d8,%d0        ; and a second field == 52
```

and the lookup at `0x80003d6e` is:

```
d3 = 0x80020                    ; the section table, container offset 0x20
loop: read 16 bytes at d3       ; one entry, matching docs/ele3-format.md
      d3 += 16
      if (wanted_id == entry[0]) goto found      ; 0x80003dbe
      if (++d2 < *0x8000b3f0) goto loop          ; bounded by the section count
      return 0                                    ; NOT FOUND
found: copy the entry out, return 1               ; 0x80003dce
```

**A `find_section_by_id`, not a dispatcher.** Two consequences, and they pull
against each other:

* **Good: an unknown section id is harmless.** The loop only ever *searches*.
  An id nothing asks for is never found, never examined, and produces no error
  and no fault. Gate 1 above is passed — adding a section will not break the
  update.
* **Bad: it is therefore inert.** Nothing installs a section the updater does
  not look up by name. Our bytes would ride along in the file, be covered by the
  content checksum and the HMAC, and then be **ignored**.

**The corroboration is in our own notes.** `docs/os-versions.md` records that in
1.11 the **updater changed for the first time in three releases**, 14,231 bytes
differing — and 1.11 is exactly the release that added section 8. That is what
this code predicts: *the updater must be taught each new id*. A fact recorded
weeks ago as a curiosity turns out to be the mechanism.

**So 1a is elegant and blocked**, by the same property that makes it safe. Using
it would mean patching the updater — the one section this project and
`m-dwyer/digikit` both refuse to touch, because a broken updater takes the
recovery path with it.

### 1c. What survives: grow section 3

The need was never "a new id". It was **bytes at an address we choose, installed
by something that already works.** Section 3 is already looked up, already
installed, already loaded at `0x40000400`, and its length comes from the section
table.

So the viable form of this idea is the one already parked under *"Related, and
also unresolved"* above: **extend MAIN OS past its end** (`0x4030b980` on 1.11)
rather than add a section beside it. Same benefit — a region that is ours, at a
known address, with no zero-run guessing and no stride heuristics — and it needs
no updater change at all.

What must still be established, and is now the actual blocker:

1. **What the updater does with a found section** — whether it honours the
   table's length and dest generically, or carries per-id expectations. Read the
   code at `0x80003dce`'s callers next.
2. **What lies above `0x4030b980`** in the loaded image, and where the `.data`
   copy and BSS clear land — `docs/memory-map.md` puts BSS at `0x402fc000` and
   the initializer at `0x402e2000..0x40300000`, which need reconciling with an
   image that ends at `0x4030b980`.
3. **Flash room**, which is where deleting section 8 finally becomes relevant —
   not for address space, but to pay for a longer section 3.

Note the shape of that last point: the owner's original instinct was right, just
one step removed. Section 8's space does not house our code — it **funds** it.

---

## 2. An emulator as a test harness

**The idea.** <https://github.com/joelanders/gearmulator-md-mm> — a fork of
TUS's Gearmulator adding **Machinedrum and Monomachine** emulations. It boots
the real firmware and its panel menu even offers *Send SysEx File*, following
the machine's normal receive procedure. An emulator that accepts an OS update is
exactly the test harness this project lacks: flash a patched OS in software,
observe, iterate — with no brick risk and no MIDI transfer.

**Why it is not a drop-in.** The Machinedrum and Monomachine are 2000s-era boxes
built around a **DSP56300**, which is what Gearmulator emulates (it began as an
Access Virus emulator). The Digitone II is a 2024 **ColdFire V4e + SHARC**
design — different host CPU, different DSP, different peripherals. Running DN2
firmware would mean writing a new machine from scratch, not configuring an
existing one. The fork also ships **no LICENSE file**, so as with ems-octakit,
nothing gets ported from it until that is resolved.

**The more realistic route.** We do not need audio to test most of what we are
changing. The parameter table, the page-view wiring, the MOD navigation and our
cave hooks are all **control-path** code on the ColdFire. **QEMU has m68k /
ColdFire support**, so the promising experiment is: load MAIN OS at
`0x40000400` under a ColdFire QEMU, stub the peripherals the startup touches
(`0xfc080000` and friends), and see how far it gets — ideally far enough to
exercise a patched parameter table without a SHARC at all. Even reaching `main`
would be a large win for iteration speed.

**What it would buy.** Today every hardware test costs a full SysEx flash and a
recovery path. A software loop would make the fourth LFO — and everything after
it — dramatically cheaper to try.

---

## 3. Expanding the PCM catalogue for the FM drum machine

**The idea.** The DN2's FM drum machine uses PCM content alongside its synthesis.
Expanding that catalogue would be a **data-side** mod rather than a code one,
and so is a genuinely different (and possibly easier) class of change than the
fourth LFO: no cave, no engine tick, no bound immediates.

**Where to look.** `blob` (id 7, 602,076 → **836,956 B**). **Section 8 is
ruled out** — `docs/data-sections.md` identifies it as a complete ARM Cortex-M
firmware image, not DN2 data.

**Updated 2026-09-12.** `blob` is now known to be **mixed data, a large part of
it float32** (`docs/data-sections.md`). If the FM drum machine's PCM lives here
it is float32, not the 16-bit PCM this idea assumed, and it shares the section
with other content — so the first job is to map `blob`'s internal layout and
find its index, not to look for a WAV-like header.

**What would have to be true.** We would need to (a) locate the PCM data,
(b) decode its format — sample rate, bit depth, any header or index table, and
(c) find the index the engine uses to address it, since adding samples almost
certainly means growing a table the code bounds-checks, which puts us back in
code-patching territory for the index even if the audio itself is pure data.

**Verification.** DNX is the instrument here too — if patched firmware exposes
new samples, a project saved from the device should show them in the sound
objects it already decodes.

---

## 4. Open the FX and Master parameters to LFO modulation and p-locks

**The idea (2026-09-12).** The DN2's FX **settings** — the parameters that
control reverb, delay and chorus themselves — accept MIDI CC from outside, but
you cannot route an LFO to them or p-lock them in a pattern. Make them
modulatable like any other parameter.

**Not the sends.** Clarified by the owner: the per-track Chorus/Delay/Reverb
*sends* are already modulatable, and that is not what this is about. The
firmware agrees — ids 67/68/69 (`FX` page, `CHR`/`DEL`/`REV` Send) all carry the
full `0x1e00` mask.

**What the mask actually says.** `docs/modulation-mask.md` found the field that
decides destination-list membership, at `record+0x24`. Read across the FX and
Master pages it does **not** split the way the idea assumed:

| Page | ids | Mask |
|---|---|---|
| **Delay** settings | 113-122 | **`0x1e00` on 9 of 10** — Delay Time, Pingpong, Stereo Width, Feedback Gain/HPF/LPF, Reverb Send, Mix Volume, FX Routing. Only `Delay Mix Vol.` is `0x0` |
| **Reverb** settings | 123-131 | **`0x1e00` on 7 of 9** — Pre-delay, Decay Time, FB Shelving Freq/Gain, Input HPF/LPF, Mix Volume, FX Routing. Only `Reverb Mix Vol.` is `0x0` |
| **Chorus** settings | 105-112 | **`0x0` on all 8** |
| **Master** (compressor) | 149-159 | **`0x0` on all 11** |

So **Delay and Reverb settings are already marked modulatable** — yet the owner
reports they cannot be reached. That is the interesting part: **the mask is
necessary but not sufficient.**

**Where the real gate probably is.** The destination-list builder
`FUN_4003951e` does not walk the parameter table. It walks **101 slots of a
`ParameterSet`**, through a virtual call:

```c
slot = (**(code **)(*param_1 + 0x50))(param_1, i);   /* i = 0 .. 0x64 */
```

and only then tests the mask. The RTTI names four such classes —
**`SoundParameterSet`, `FxParameterSet`, `TrigParameterSet`, `MidiParameterSet`**
(typeinfo strings at `0x402147ef`ff). A synth track's LFO almost certainly walks
a `SoundParameterSet`, which would never enumerate an FX setting no matter what
its mask says.

If that is right, the work splits cleanly:

- **Delay and Reverb**: the mask is already correct; the job is **enumeration** —
  get those ids into the set the LFO's destination list walks. No record edits.
- **Chorus and Master**: need **both** — the mask set to `0x1e00` *and* the
  enumeration. Chorus is eight one-word record edits, Master eleven.

**Retracted: the FX-track hypothesis.** The guess above was that the DN2 has an
FX track with its own LFOs and those masks exist for it. The owner settled it:
*"nope, that's Octatrak exclusive"*. There is no FX track on the DN2. The Delay
and Reverb masks are latent capability that nothing on this device asks for.

> **What this retraction does NOT say, flagged 2026-09-14 because it was
> misread — by me, in a summary to the owner.** It retracts an *explanation of
> the masks*, not a feature. "The DN2 has no FX track" is a fact about the stock
> device, and the stock device has no fourth LFO either; that is the premise of
> this whole repository, not an objection to it. **Adding FX tracks remains a
> live idea and is §8.** The only thing established here is that the existing
> `0x1e00` masks are not evidence of hidden FX-track machinery, so they cannot
> be cited as a head start.

**Settled (2026-09-12): it is an enumeration problem, and the enumeration is a
data edit.** `docs/parameter-set-tables.md` reads the boot-time builder
`param_set_tables_build` (1.11 `0x400dc4d0`). It walks the parameter table and
files each id into a set chosen by the record's **page id** at `record+0x00`, at
the slot given by **`record+0x04`**:

| Page id | Set |
|---|---|
| `11..15` and `26..28` | **sound** — the table the LFO destination list walks |
| `16..21` | **FX/global** — Chorus 16, Reverb 17, Delay 18, Master 19–20, Ext-in 21 |
| `22..25` and `26..28` | **MIDI** |
| `29, 30, 0xffffffff` | not enumerated at all |

So Delay and Reverb are unreachable because they are filed into the FX/global
table while the LFO walks the sound table — and **both deciding fields are
editable records**, not code. Moving Delay Time into the sound set is a two-field
write to one record.

**The cheap half is finished: every parameter a mask edit can open, is open.**
Measured 2026-09-12. Of the 173 parameters an LFO destination list can reach —
the union of the sound, machine and filter tables, which is what
`param_set_slot_to_id` can return — exactly **13** still carried mask `0x0`, and
those 13 are precisely Group A of `scripts/build_moddest_expand.py`, flashed and
confirmed working:

| | |
|---|---|
| Portamento | `PTIM` `PORT` |
| Amp | `DEL` `MODE` `RSET` |
| SYN | `ATRG` `ARST` `BTRG` `BRST` `PHRT` `KSA` `KSB1` `KSB2` |

**There is nothing left that a mask edit alone can open.** Any further
destination requires moving a parameter between sets, which is a different and
much larger job.

**And that job is bigger than "two record fields", for three reasons — the third
is the real one.**

1. **The page id *is* the UI page.** A moved parameter leaves the Delay page.
2. **There is no free sound slot.** `docs/engine-index-map.md` §6b: slots 0, 65
   and 100 all resolve to engine index 0. Slot 65 is repairable with a 4-byte
   forward-map write; slot 100 is a trap. So the ceiling is **one** moved
   parameter, not two.
3. **The FX objects are on the other side of a different mirror.** The LFO's
   output reaches the engine through `Sound::updateMirror` into the sound
   mirror, indexed by the sound engine space (0..106, fully accounted for by
   sound parameters). Delay, Reverb, Chorus and Master are mirrored separately
   by `FxSetup::updateMirror` into `fxSetupStorage_v0_t`, a different structure
   with a different index space. Enumerating an FX parameter into the sound set
   would give it a sound-mirror slot that the FX object never reads. It would be
   offered, and it would not move.

So **Delay and Reverb already carrying `0x1e00` is a red herring** — the mask
costs nothing and buys nothing while the enumeration and the mirror are both
wrong. And Chorus and Master are not "eight and eleven record edits"; they are
the same cross-mirror problem plus a mask.

**What would actually have to be true**, and none of it is established: either
the engine's destination space covers FX parameters (unknowable from this image
— the engine's code is not in it), or the modulation is applied control-side
before the mirror split, in which case the place to hook is `FxSetup::updateMirror`
rather than the parameter table.

**The more promising half of this idea is the p-locks**, which were always the
second part of it and are a different mechanism: pattern storage, decoded by DNX
(`DNX/docs/dn2-pattern-format.md`), not the LFO destination path at all. That
has not been costed and is where to look next if this idea is picked up.

**Then the engine unknown, now narrowed.** On 2026-09-12 a mask flip made
Portamento Time both appear as a destination **and actually modulate**, proving
the apply path is generic over the parameter index
(`docs/modulation-mask.md`). But Portamento Time is a **per-voice sound
parameter** the engine already computes for every voice. Chorus, Master, Delay
and Reverb settings are **global** — a different object, not per-voice — so that
result is encouraging and is **not** evidence these will work. Failure stays
visible and harmless: the parameter appears in the `DEST` list and does not
move.

**P-locks are a separate question.** Whether a parameter can be p-locked is not
obviously this field. DNX's decoded pattern format
(`DNX/docs/dn2-pattern-format.md`) is where to check what the p-lock table can
address.

---

## 5. Bake an LFO's output into parameter locks

**The idea (2026-09-12, from the owner).** Internal LFO modulation is invisible
on screen, and deliberately so — if the display followed the LFO, arming live
record during playback would capture that movement as p-locks and record the
modulation on top of itself (`docs/lfo4-feasibility.md`, the retraction).

But doing it *on purpose* is a feature: run an LFO, then **bake** its output
into parameter locks across the sequence and free the LFO for something else.
The owner's own caveat is the cost: "it would take precious sequencer space for
other modulations/parameter locks."

**Why it is interesting here.** It needs no new engine capability — it is a
sequencer-data transform, writing values the p-lock table can already hold. That
makes it a very different risk class from a fourth LFO, and it is the kind of
thing DNX can verify offline by reading the resulting pattern.

**What would have to be true.** We would need the LFO's output at each step
(which needs the tick, or a good enough reimplementation of the LFO's maths),
somewhere to put the values (DNX has the p-lock layout and the free `4*slot + 0`
band), and a UI affordance to trigger it. The first is the same blocker as
everything else on this list.

---

## 6. A new ELE3 section as real address space, instead of caves

**The idea (2026-09-12, raised by the owner).** Asked why new code cannot simply
be appended at the end of MAIN OS and referred to by its address, the honest
answer turned out to be narrower than `docs/code-caves.md` had been saying.
Appending shifts nothing — the "every address moves" objection is about
*inserting*, not appending, and absolute addressing does not care where the
bytes sit. What kills it is that the space past the section end **is already
reserved**: BSS runs `0x402fc000`–`0x466b74d0` on 1.11, the section ends at
`0x4030b980`, and the clear loop at `0x400004b2` zeroes ~104.5 MB of it before
`main` runs. An appended table is erased at boot.

**But that argument does not apply to a different address.** The ELE3 container
is a table of `{id, offset, comp_len, dest}`, and 1.11 already ships six
sections at four distinct `dest` values (`0x02010000`, `0x40000400`,
`0x80000400`, and two at `0`). Nothing about the format restricts us to the
six that Elektron chose. A **seventh section with `dest` above the BSS end**
would be written straight to an address the startup code never touches — real,
unclaimed, arbitrarily large address space, with no cave chaining, no BSS
surgery, and no shifting.

That would change the ceiling on this whole project. Caves cap a payload at
~1 KB per run, ~26 KB total, which is why the LFO4 work keeps running into
"needs a cave" on things as small as a 430-byte table.

**Both gating questions are answered, and both answers are yes** (2026-09-12,
`docs/memory-map.md`).

1. **Does SDRAM extend above `0x466b74d0`? Yes — to `0x48000000`.** The C
   runtime's first instruction is `moveal #0x48000000,%sp` at `0x400004f2`, and
   stacks descend, so the top of usable RAM is `0x48000000` and SDRAM is
   **128 MB**. The window above BSS is **26,512,176 bytes (25.3 MB)**. (The
   memory-controller setup at `0x4000043e` was the suggested route; the stack
   init turned out to be a shorter and less ambiguous one.)
2. **Does the heap live up there? No.** Scanning every 32-bit immediate that
   names an address in `[BSS start, top of RAM)` returns **7,043 hits inside
   BSS and none above it**. The highest reach `0x466b748c` — within **68 bytes**
   of the BSS end — and then stop dead, which is what a linker-computed `_end`
   looks like. So the heap is a static arena *inside* BSS, which is also why BSS
   is 100 MB: globals plus the pool.

**The only occupant of the window is the stack**, descending from `0x48000000`,
and its depth is unmeasured. So **place a new section at the bottom of the
window, not the top** — just above `0x466b74d0`, where the stack would have to
descend 25 MB to reach it.

**Then the loader question.** Whether the bootloader validates `dest` at all, or
writes wherever the section table says. `docs/bootstrap.md` records that
reception validates very little — "nothing reception validates can tell our
`gate-d` image apart from stock" — which is encouraging but is about the
*container*, not about `dest` handling specifically. Read
`verify_and_flash_container` before trusting it.

**Risk, stated plainly.** This writes to an address no stock firmware writes to,
which is a different class of experiment from everything done so far: every
patch to date has been same-length edits inside a region the device already
uses. A bad `dest` could fail at flash time rather than at boot. The recovery
path (`docs/flashing.md`) is proven, so the downside is a reflash, not a brick —
but this should not be the first thing tried after a long gap, and it should be
tried with a payload whose absence is harmless (a table nothing reads yet),
never with a payload the firmware depends on to boot.

---

## 7. The DSP hunt, parked with an explicit warning

> **[UNPARKED 2026-09-14]** This section was parked because nothing could read
> SHARC+ VISA. That is no longer true: digikit ships both a Ghidra processor
> module and a stdlib-only Python disassembler for our exact chip family, built
> from ADI's *public* programming reference — **no CrossCore licence is
> involved** — and run against our image it decodes **~81% of the L2 code region
> confidently** (`docs/sharc-disassembly.md`). The binding constraint named here
> and in `docs/ROADMAP.md` is lifted. What remains unbuilt is p-code semantics,
> so the tooling **disassembles but does not decompile**.


> **[LARGELY ANSWERED 2026-09-13 — `docs/sharc-image.md`, `docs/sharc-code-map.md`.]**
> The hunt succeeded, and this section's premises are the interesting part of the
> record, so they are kept rather than rewritten.
>
> | this section says | actually |
> |---|---|
> | *"no boot stream has been found in any ELE3 section"* | **Section 7 is an ADI boot stream.** 95 blocks, consuming all 836,956 bytes exactly, entry point `0x001c12e2`. |
> | *"the ColdFire probably boots it from the 16 MB Winbond NOR — a region the update file need not touch"* | It ships **in the update**, in every release. |
> | *"the DSP image could be in the firmware in a packed form, and every test would miss it"* | The warning was right that the tests were the problem and **wrong about which problem**. `blob` is aPLib-packed in the container and we already decompress it. The searches failed on the *decompressed* bytes because they looked for a **raw** instruction stream; a boot stream is headers-plus-payloads and has no global period. |
> | *"we have no SHARC disassembler … reading it needs a tool we do not have"* | **Still true of this repository**, and it is now the binding constraint rather than a hypothetical. digikit has one (`sharc_disasm.py`, SHARC+ VISA). |
>
> The contributor's Machinedrum advice — *get an established memory map from
> MAME to identify the DSP code setup* — was sound and is now moot in the
> better direction: the boot stream **states its own memory map**, which is
> stronger than borrowing one. See `docs/sharc-code-map.md` for which regions
> are code and the `exec = (load − 0x28000000) / 2` mapping.
>
> **Still open:** whether the synthesis engine is in that image at all, and the
> `0xb8` execution address space (1,025 of 1,616 call targets).

**Parked 2026-09-12** at the owner's direction: finish LFO4 first, resume this
once there is a flashable firmware.

`docs/engine-index-map.md` §§9–13 and `docs/hardware.md` carry the state. The
short version: the DSP is an **ADSP-21569 (SHARC+)** with its own DDR3; the
ColdFire (an **MCF5441x**) does no audio DSP; no boot stream has been found in
any ELE3 section; and there is no serial flash beside the SHARC, so the ColdFire
probably boots it from the 16 MB Winbond NOR — a region the update file need not
touch.

**The warning, raised by the owner and worth stating loudly because every test
so far shares this blind spot: the DSP image could be in the firmware in a
packed form, and every test run to date would miss it.**

All three searches looked for *structure* — 24-bit periodicity, 48-bit
periodicity, ADI LDR block headers. **Compression destroys all three.** And
`docs/engine-index-map.md` §10 already measured that **~350 KB of `blob`
(windows `0x20000`–`0x78000`) is structureless**, with per-byte entropy 7.3–7.6
and near-zero column spread at every stride. That is exactly what packed content
looks like, and exactly where a packed DSP image would hide.

So the accumulated "no DSP code in the file" readings are **conditional on the
data being stored raw**, and that condition has never been tested. Say it that
way, not as a conclusion.

**When this resumes, do these in order:**

1. **Try to unpack the structureless region.** The container's own aPLib variant
   is already implemented (`src/dnfw/codec/aplib.py`) — try it at a range of
   offsets inside `blob` first, since Elektron demonstrably has that codec to
   hand. Then the common alternatives. Any successful unpack gets the
   periodicity tests re-run on its *output*, which is where they should have
   been aimed all along.
2. **Follow the reader, not the bytes.** `blob` ships with `dest 0`, so it is
   flash-resident and MAIN OS must address it explicitly. Find that code: it
   reveals `blob`'s internal layout, its index, and whether anything decompresses
   it — which answers the packing question directly rather than by statistics.
3. **Map the 16 MB SPI NOR.** Where the ELE3 payload lands and what else occupies
   it. If a DSP image sits outside the updated region, that closes the question
   and also scopes what writing flash directly would involve.

**Tooling gap to record now:** we have no SHARC disassembler. `objdump` does not
target SHARC, Ghidra has no ADSP-2156x processor module, and ADI's CrossCore
toolchain is the reference. **Even if a boot image is found, reading it needs a
tool we do not have** — worth knowing before the search succeeds rather than
after.

### Advice from another Elektron RE contributor (2026-09-12), and what it changes

Passed on by the owner, from someone who reverse-engineered the **Machinedrum**:

> When I was doing Machinedrum RE it helped a lot to have an established memory
> map from Mame to identify the DSP code setup. In Machinedrum the DSP memory is
> not reachable from the Coldfire CPU, the CPU has to upload the DSP memory word
> by word using a port in the DSPs. Use the Elektron Firmware Tool to extract the
> blobs.

This is worth more than a tip, because it **shifts the leading hypothesis and
exposes a flaw in the search that produced the current one.**

**It establishes the Elektron house pattern, across two devices.** On the
Machinedrum the ColdFire uploads DSP memory **word by word through a port on the
DSP**, because the DSP's memory is not in the CPU's address space at all. That is
exactly what octabam measured independently on the **Octatrack** — `FUN_40001b18`
pushing 79,563- and 77,061-byte payloads through the HI08 host-port window
(`docs/engine-index-map.md` §7). Two Elektron devices, two DSP families, the same
arrangement.

**So the prior should be that the DN2 does it too** — and therefore that a DSP
image *is* in this firmware, rather than that it is not. Combined with the
owner's packing warning above, the honest reading becomes: the image is probably
present, probably packed, and has not been found because neither the packing nor
the upload path was searched correctly.

**The flaw it exposes.** `docs/engine-index-map.md` §7 reported "no upload loop
found". That search looked for **absolute-addressed stores** — `move.x dN,(xxx).L`
inside a short backward branch. A word-by-word upload almost certainly does **not**
look like that: the port address would be held in an **address register**, loaded
once before the loop, and the loop body would be `move.w (aSrc)+,(aPort)` with no
absolute operand anywhere. **My scan could not have found it.** That is a
measurement gap, not evidence of absence, and §7's negative result must be read
that way.

### Revised plan for when this resumes

Ahead of the three steps above, because it is cheaper and now better aimed:

0. **Re-run the uploader search with the right shape.** Look for a tight loop
   containing a **post-increment read** (`(aN)+`) and a **non-incrementing write
   through an address register**, where that register was loaded with a constant
   in a FlexBus or peripheral window. The windows already mapped are
   `0xec09xxxx` (270 absolute accesses), `0xec07xxxx`, `0xec03xxxx`,
   `0x8c00xxxx` — but the port may be none of these, since a register-held
   address would not have appeared in that census either. Search by **loop
   shape**, then read what address the register was given.

Then, on the MAME suggestion: **MAME has no Digitone driver**, so there is no map
to lift directly. The transferable part is the method — *get the peripheral map
from an independent source rather than inferring it* — and for the DN2 that
source is **Analog Devices' ADSP-21569 documentation** (host port, link port and
SPI slave boot, and their register maps) plus **NXP's MCF5441x reference manual**
for the FlexBus chip-select configuration that decides which external window
lands where. Reading the ColdFire's chip-select setup at boot would name every
external window on the board, which is the same win MAME gave on the Machinedrum.

On the Elektron Firmware Tool: **already in hand.** It is cloned at
`00_Resources/01_Reference/elektron-firmware-tool/` (MIT), and `dnfw`'s container
and aPLib code is ported from it (`docs/references.md`). We extract blobs with
our own tooling today — but the C tool remains valuable exactly as the plan
intended, as an **independent cross-check** from code sharing no lineage with
our Python. Worth building and running `-i` over `blob` before trusting any
unpacking result we produce ourselves.

---

## 8. FX machines on tracks, and per-track assignable FX

**The idea (2026-09-13, issue #49, raised by the owner).** The DN2 assigns a
synthesis machine and a filter machine per track. Syntakt and Tonverk allow a
track to be an **FX machine** instead. Two pathways are proposed:

1. **Add FX machines as a track type** — potentially via a new ELE3 section
   (the issue says "section 9 or 10") to hold them, making FX parameters
   modulable rather than only the send value.
2. **The Octatrack model** — replace each audio track's *fixed* reverb, delay
   and chorus with **assignable FX slots**, moving FX configuration from
   global-per-pattern to per-track.

The issue notes this is adjacent to §4 (FX and Master parameters as LFO
destinations), which is correct and is where the two meet.

### What this depends on, and why it is different from LFO4

**This is DSP work, and LFO4 is not.** That is the single most important thing
to say about it, and it reorders the queue.

A fourth LFO may turn out to be entirely ColdFire-side: a parameter-table block,
a page view, a modulation destination mask, and reserved bytes that already
exist in the persisted format. An **FX machine processes audio**. It runs on the
SHARC. So §8 cannot be attempted on the strength of anything in `docs/lfo4-*`;
it sits on top of §7, which until 2026-09-13 was parked and believed
intractable.

**What changed on 2026-09-13 makes this askable rather than idle.** The DSP's
program ships in section 7, ~240 KB of it is identified as code, and its
execution addresses are mapped for one of two spaces
(`docs/sharc-code-map.md`). None of that existed when this idea would previously
have been filed under "requires a DSP image nobody has found".

**What has not changed:** we cannot read a SHARC instruction. §7's tooling-gap
note is now the binding constraint on §8, not a footnote to it.

### The two pathways are not equally expensive, and the issue's second is cheaper

Worth separating before any work starts, because the issue presents them as
alternatives of similar size and they are not.

**Writing a new FX machine** means authoring SHARC audio code, in an ISA we
cannot yet disassemble, for a processor we cannot emulate (no SHARC+ target
exists in Unicorn, QEMU or MAME — MAME's core is classic ADSP-2106x). That is
the expensive pathway by a wide margin.

**Re-routing existing FX per track** reuses DSP code that is already in the
image and already works. The reverb, delay and chorus algorithms exist; the
change is which track feeds which, and where the settings live — routing, state
and UI, much of which is ColdFire-side. It also has prior art we have already
read (`docs/octatrack-lfo-prior-art.md`).

**So the honest ordering is: pathway 2 first**, and only then pathway 1 if the
DSP side ever becomes writable. That is not a preference, it is the difference
between changing parameters to existing code and writing new code for a
processor we cannot yet read.

### On "a new section 9 or 10"

Do not design this fresh: §1b and §6 already did the work.

- **§1b** established that the updater looks sections up **by id**
  (`find_section_by_id`, `0x80003d6e`), not by position — which is what makes a
  new id conceivable at all.
- **§6** is the developed form of exactly this idea: a new ELE3 section whose
  `dest` lies **above the BSS end**, giving real unclaimed address space with no
  cave chaining. The container already ships six sections at four distinct
  `dest` values, and nothing in the format restricts us to those six.

§8 should treat §6 as its mechanism rather than restating it. The open question
§6 leaves — whether the *bootloader* accepts a section id it does not know, or
refuses the image — is the gate for both, and it is one experiment.

### Where the FX parameters actually are

§4 already measured the relevant field: `record+0x24` decides
destination-list membership (`docs/modulation-mask.md`), and the per-track
Chorus/Delay/Reverb **sends** (ids 67/68/69) already carry the full `0x1e00`
mask. Whatever §8 does to make FX settings modulable runs through that field, so
§4's measurements are §8's starting point and should not be re-derived.

### It splits three ways by cost, not two (2026-09-14)

The two pathways above are still right, but collapsing everything else into
"blocked behind the SHARC" is too coarse and hid the one tier that is open
today.

| Tier | What it is | Where it runs | Status |
|---|---|---|---|
| **A** | p-lock / modulate the **existing global FX settings** per pattern | nothing new on the DSP — the algorithms already run | **open, and adjacent to work already done** |
| **B** | let a track choose **which of the existing three** FX it feeds | reuses running DSP code; the change is routing | unknown whether the SHARC exposes configurable routing |
| **C** | **N FX instances per track**, Octatrack-style | multiplies DSP instances | genuinely behind the SHARC wall |

**Tier A is the one to start on, and it pays twice.** The thing standing between
an LFO and an FX parameter is §4's mirror split: `FxSetup::updateMirror` writing
into `fxSetupStorage_v0_t`, a separate structure with its own index space. That
is *also* exactly what per-pattern FX control has to go through. So Tier A's
mechanism is §4's named blocker, and understanding one resolves both.

Tier A also starts from storage that already exists: FX settings are already
pattern-scoped data, so per-step locks are an increment rather than a new
concept. **The first step costs nothing and touches no hardware** — ask DNX's
decoded pattern format (`DNX/docs/dn2-pattern-format.md`) whether a p-lock can
address an FX parameter id at all. If it can, Tier A is an enumeration problem.
If it structurally cannot, that is the real wall, found offline for free.

**Tier C's cost is not just "we can't read SHARC".** The Octatrack runs 8 tracks
× 2 FX slots; the DN2 runs **3 global** FX. Per-track means multiplying
instances, which is a DSP *headroom* question and additionally requires the
algorithms to be instantiable more than once — a property of code we cannot
inspect. Two unknowns, not one.

### What the Octatrack repositories do and do not give us

Worth stating plainly, because "we have the Octatrack code" is easy to
over-read:

| We have | What it actually is |
|---|---|
| `octabam` (MIT) | ColdFire code caves — the **delivery mechanism** |
| `midisc` (MIT) | MIDI scenes via cave splicing; we port its ColdFire assembler |
| `TABLE_ATLAS.md`, delay architecture | community docs describing **DSP56300** tables |
| `ems-octakit` | **unlicensed** — inspiration-only until a licence is granted |

**None of them contains an FX-track implementation.** The Octatrack's assignable
FX are stock Elektron firmware running on a **DSP56300**; ours is a **SHARC+
ADSP-21569**. No instruction, table layout or algorithm transfers. What we have
is the tooling that makes patching possible and the method — which is real, and
is why §"scenes" is tractable — but it is not the feature.

### The DN1 changes the answer for Tiers B and C

**`docs/dn1-dsp-comparison.md`: the Digitone 1 runs its audio DSP on the
ColdFire.** 613 multiply-accumulates against the DN2's 50, in four-accumulator
EMAC loops at `0x40096000`–`0x4009b000`, working on the `0x80000000` fast SRAM.
Elektron moved the engine off the main CPU between 2018 and 2024.

So on the DN1 the audio engine **is in the image, on a CPU we can already
disassemble** (Gate F cleared), and its firmware is **unsigned** — no HMAC to
reproduce, a shorter build loop. Everything this section calls "behind the SHARC
wall" is simply *readable* there.

That makes the DN1 the natural vehicle for Tiers B and C, and it suggests a use
that is better than either: **read the DN1's LFO generator as a template for
recognising the DN2's.** We would learn what an Elektron modulator looks like as
code — its phase accumulator, its waveform table shapes, its constants — and
then search the SHARC for that signature instead of reading 105 KB blind. That
partially routes around §7's decode problem rather than waiting on it.

**The caveat, so it is not overclaimed:** the DN1 is a different product with
fewer tracks and voices, and nothing found there transfers to the DN2 as fact.
It transfers as a *hypothesis to test*, which is still worth a great deal when
the alternative is an unnamed 105 KB.

## 9. A tool for a custom start-up animation

**Owner's idea, 2026-09-13.** Let people replace the Elektron boot animation
with their own — a small tool that takes frames in and produces a flashable
image, rather than a one-off patch.

This is parked like everything else here, but it is worth noting that it is
**the most tractable idea on this page**, for three reasons that are already
measured rather than hoped for.

**The intro is a separate drawing path, and we have seen it.** `emu/panel.py`
records that the main OS composes text and widgets straight into the
framebuffer and never calls `Bitmap::setPixel`, while **the intro draws through
that primitive**. So the boot animation is not entangled with the UI renderer:
it is its own code reaching its own entry point. `docs/display-path.md` captures
both — the intro animation and the SYN1 page — from the same run.

**The boot path is where cave code is already proven to run.** The project's
first and only confirmed code injection hooked the boot path and wrote
`CAVE RAN!!!` over a string in RAM (`docs/code-caves.md`). Whatever a custom
animation needs, it needs it *there*, which is the one region where execution is
not a hypothesis.

**It is visible without hardware.** `scripts/drive.py` archives the panel as a
PNG from the emulator, so an animation can be iterated offline and only flashed
once it looks right — instead of the flash-and-photograph loop that every
earlier experiment paid for.

### What is not known yet

- **Where the frames live, and in what form.** Nothing has looked. The
  `blob` section is the SHARC program (`docs/sharc-image.md`), so the animation
  is somewhere in MAIN OS — as bitmap data, as drawing code, or as both.
- **Whether it is data or procedure.** A stored frame sequence is a
  replace-the-bytes job with a size budget. A procedurally drawn animation —
  which the captured frames' symmetry rather suggests — means writing ColdFire
  drawing code in a cave, a different and larger task.
- **The size budget.** Same-length replacement is free; anything larger needs
  §1's space or §6's section.

The first question is the cheap one and answers the rest: hook `setPixel`
during the intro, record the pixels, and see whether the sequence matches
anything stored in the image. That is an afternoon with tools that already
exist, and it is the honest first step rather than a design.

### Why it is worth doing even though it is not LFO4

It is the first idea here with **a user other than us**. Everything else on this
page makes the instrument do more; this makes it *theirs*, which is a different
kind of value and a much easier thing to explain to someone who does not care
how an ELE3 container is laid out. It is also small enough to finish, which none
of §1, §4, §6, §7 or §8 currently are.
