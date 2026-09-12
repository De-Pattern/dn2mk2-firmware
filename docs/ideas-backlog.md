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

**Related, and also unresolved:** growing section 3 itself. Freed flash could in
principle let MAIN OS extend past its end (`0x4030b980` on 1.11), but that needs
the device's flash layout confirmed and the boundary above the loaded image
pinned, so new bytes cannot collide with anything. See `docs/memory-map.md`.

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

**The price, which is why this is still a backlog item and not a build.** The
page id *is* the UI page, so a moved parameter leaves the Delay page. Only sound
slots **65 and 100** are free, so at most two FX parameters can move. And the
apply path writes `sound + 0x14 + idx*2`, a **per-voice** location, while the
Delay is one global instance — an enumerated global would most likely be offered
as a destination and then not move. That last point is the experiment worth
running, and it is cheap: two records, four fields, the same build-and-flash
loop as the mask tests.

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

**Two things to check before this is worth any effort, in this order:**

1. **Does SDRAM extend above `0x466b74d0`?** That is ~103 MB into the bank. If
   the part is 128 MB (`0x40000000`–`0x48000000`) there is ~25 MB of genuinely
   unclaimed RAM above BSS; if the bank ends at BSS end, there is none. The
   memory-controller setup at `0x4000043e` (`andl` against `0xfc050014`, then
   `movew #1343,0xfc080000`) is where the bank size is configured and is the
   place to read it. **This is the gating question** — if the answer is no, the
   idea is dead and costs nothing more.
2. **Does the heap live up there?** If `malloc` carves from above the BSS end,
   the space is claimed after all and a new section would be overwritten by the
   first allocation. Find the allocator's arena bounds — `0x40120264` is called
   for allocations in `Sound::updateMirror`'s neighbourhood and is a way in.

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
