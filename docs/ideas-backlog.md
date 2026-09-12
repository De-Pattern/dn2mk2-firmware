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

**The idea (2026-09-12).** The DN2's FX settings — reverb, delay, chorus — accept
MIDI CC from outside, but you cannot route an LFO to them or p-lock them in a
pattern. Make them modulatable like any other parameter. Same for the other
pages the device holds closed.

**Why this one is unusually concrete.** `docs/modulation-mask.md` found the
mechanism that decides this, and it is a **single field per parameter record**.
A parameter appears in an LFO's destination list iff `(filter & ~mask) == 0`,
where `mask` is the word at `record+0x2c`. Measured across all 271 records, the
pages split cleanly:

| Page | Records at `0x1e00` (modulatable) | Records at `0x0` (closed) |
|---|---|---|
| Delay | 9 | 1 |
| Reverb | 8 | 1 |
| **Chorus** | **0** | **8** |
| **Master** | **0** | **11** |
| Portamento | 0 | 2 |
| Retrig | 0 | 4 |
| Euclidean | 0 | 8 |

So **Delay and Reverb are already open** — the closed ones are Chorus, Master,
Portamento, Retrig and Euclidean. Opening Chorus would be **eight one-word
edits**, `0x0` → `0x1e00`, with no relocation, no bound change and no new code.
That is the cheapest experiment in this whole backlog, and it doubles as the
cleanest possible test of the mask semantics.

**What would have to be true.** The mask governs *list membership* — whether the
parameter can be chosen as a destination. Whether the engine can then actually
apply a modulation to an FX parameter is the separate question, and it is the
same class of unknown as the fourth LFO's engine gate: the destination has to be
something the modulation path knows how to write. Two ways it could fail:

- the modulated value is applied through a per-track/per-voice path that FX
  parameters (which are global, not per-track) never pass through;
- the `0x0` is not a policy choice but a marker that no write path exists,
  in which case a chosen destination would simply do nothing.

Either failure is **visible and harmless**: the parameter appears in the `DEST`
list and does not move. Nothing is written to a place the firmware does not
already write.

**P-locks are a second, separate question.** Whether a parameter can be
p-locked is not obviously the same field — that needs finding before assuming
one edit buys both. DNX's decoded pattern format
(`DNX/docs/dn2-pattern-format.md`) is where to check what the p-lock table can
address.

**Sequence it after the tick.** The same unknown — what the write side can
reach — gates this and the fourth LFO, so finding the modulation tick answers
both at once. Do that first; this becomes cheap or impossible depending on what
it says.
