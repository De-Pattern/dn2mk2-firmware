
# Adding a feature to the DN2 — the playbook

**STATUS: accumulating, not finished.** The owner asked for this on 2026-09-16:
collate the streamlined process so the next feature *"doesn't hit the same
issues and stoppers and goes directly to the working solution as quick as
possible."* It is to be finalised **once LFO4 is built and verified on
hardware**, because a step that has not survived a flash is a guess.

It is started now rather than then, because the material is evidence from this
week and writing it later would be reconstruction from memory. Every claim here
is dated and sourced. **Where a step has not yet been proven end to end, it says
so.**

---

## 1. The eight layers, and why they are the whole map

The single most useful thing learned so far: **a parameter-visible feature on
this instrument crosses the same eight layers every time, in the same order.**
LFO4 hit all eight. A new machine, a new effect, a new modulation source will
hit the same eight, with different addresses.

| # | layer | what it is | LFO4's instance (1.11) |
|---|---|---|---|
| 1 | **Parameter records** | 321 × 60-byte records: page id, index, range, default, CC, name pointers, formatter | table `0x401f7f94`; repurpose dead `ERR` slots |
| 2 | **Enumeration** | boot-time tables that say which records a page walks | `param_set_tables_build` `0x400dc4d0` |
| 3 | **Classifier** | *which parameter set owns this record* — a **virtual predicate**, vtable slot `+0x54` | `0x400dbe8a`/`0x400dbf4e`/`0x400dbf82`/`0x400dbfbc`, and `0x400dbee6` |
| 4 | **Slot space** | runtime index → value, inside the sound object | accessor `0x400dc02a`, bound `moveq #100`; values at `sound+0x14+slot*2` |
| 5 | **Engine** | whatever generates or consumes the value per frame | LFO tick `0x40137726` |
| 6 | **Serialization** | live ⇄ stored, through the forward/inverse maps | `0x400dd24a` / `0x400dd6f0`, maps `0x401fcf20` / `0x401fd0b0` |
| 7 | **Page view** | the class that draws the page and maps columns to records | `LfoPageView`, vtable `0x40205614`, columns at `+0xBC` |
| 8 | **Navigation** | how a key reaches the page — `register(ctx, *ids, count)` over a **packed pool of view ids** | pool `0x401e0000` (32 longwords, **no gaps**); LFO's slice `(0x48, 3)` at `0x40061558`. The count cannot be bumped — the list relocates |

**Use this as a checklist before estimating anything.** LFO4 was priced three
times and wrong twice, both times because a layer had not been looked at yet —
layer 3 in particular, which is invisible to every kind of scan that looks for a
switch on a page id.

---

## 2. The stoppers, and how to not hit them again

Each of these cost real time in September 2026. They are listed by what they
cost, not by how interesting they are.

### 2.1 Use the reference repos' tooling. Do not write scans.

**Owner's standing rule, 2026-09-16:** *"Always use the tooling at hand in other
reference repos, don't build your own tooling if it is not needed."* /
*"Don't reinvent the wheel unless it is not invented."*

Three hand-rolled scans in this project produced wrong answers:

| scan | wrong answer | cost |
|---|---|---|
| bare constant `addil #-26` | four unrelated hits taken as meaningful | a wrong cost model |
| `jsr (xxx).L` only | "the ISR's 15 callees are enumerated" — it has 73 | a retracted conclusion |
| regex for value-array accesses | 144 hits, most false | abandoned mid-task |

`m-dwyer/digikit` (MIT) already ships better, and `capstone` is installed, so
every static one runs today:

```
tools/rttiscan.py    typeinfo, vtables, vtable LOAD SITES, Class::method strings
tools/refscan.py     exhaustive absolute-reference scan into an address range
tools/vtcheck.py     vtable validation
tools/decompile.py   decompiled C (needs PyGhidra)
tools/addrtrace.py   hit counts and registers at first hit -- BY RUNNING
emu/                 boots the firmware under Unicorn, screen + front panel
```

`rttiscan.py` on our DN2 1.11 MAIN OS: **1,047 typeinfo objects, 1,911 vtables,
4,845 vtable load sites, in five seconds.** It found in one query the page-view
registry that half a day of hand-scanning had missed.

**And use the decompiler.** `00_Resources/03_Ghidra/emac/mainos_111_emac.gpr` is
already imported with the ColdfireEMAC language:

```
set PROCESSOR=68000:BE:32:ColdfireEMAC
ghidra\analyze.bat 00_Resources\03_Ghidra\emac mainos_111_emac ^
    out\ext111\section_3_MAIN_OS.aplib.bin 0x40000400 ^
    -postScript DecompileFunction.java 0x40061550
```

Reading 900 bytes of assembly by eye, when that exists, is a choice.

### 2.2 Anchor a scan on structure, never on a constant

When the question is *"what else names X?"*, scanning for X's encoding finds
noise. **Anchor on something structural instead.**

Finding every consumer of page id `0x1d`: scanning for `moveq #29` returns
hundreds. Scanning for comparisons against 29 **within 60 bytes of one of the 49
sites that load the parameter table** returns **three**, and all three are real.
That difference is the whole difference between v2 failing and v3 being worth
flashing.

### 2.3 A string in a table is not a code path

Twice in one day. `Unsupported downgrade` sits at index 5 of the upgrade error
table, so the DN2 "has a downgrade gate" — it does not; nothing can produce that
code. `Incompatible OS` looked like the version check — it is a *product* check.

**Rule: read the comparison that produces the value. Presence of a message
proves only that a message exists.**

### 2.4 Behaviour is decided by virtual predicates, not switches

The single most expensive misconception. Ownership, grouping and dispatch on
this firmware are C++ virtual calls through vtable slots, so:

- there is no switch to grep for;
- `dnfw fn entry` attributes an address to the preceding *called* function,
  which for a vtable-reached method is **a guess, and it says so**;
- a cave in a function with **zero callers and zero data references** never runs
  — check before spending one (`0x4012a836` is a compiler artifact; every real
  use is inlined).

`rttiscan.py`'s vtable + load-site output is how you find these directly.

### 2.5 A decompiler argument can be a truncated pointer

Ghidra printed the navigation call as `register(ctx, 0x48, 3, ...)`, which
reads as two small constants. `0x48` was `0x401e0048` **truncated to its low
byte** — a pointer into a packed table, not a key code. Taking it at face
value produced "the edit is one byte", and the pool turned out to have no
free slot to bump into.

**Rule: check any small integer argument against the disassembly before
building on it.** The instruction was `movel #0x401e0048,%d0`, and one look
would have settled it.

### 2.6 objdump prints displacements in two radixes

`docs/mainos-image.md` has the full measurement. Indexed-mode (brief extension)
displacements print in **hex with no prefix**; `d16(An)` displacements print in
**decimal**. It has caused a wrong structure offset twice.

**The sharper form, learned 2026-09-16:** when a structure offset derived from
an indexed displacement produces fields that do not match how the *callee* uses
them, suspect the radix before suspecting the structure.

### 2.7 Stock Ghidra silently truncates this ISA

`68000:BE:32:Coldfire` has no constructor for `movclr`, so flow analysis stops
dead with no error. Use digikit's `68000:BE:32:ColdfireEMAC`
(`ghidra/install-coldfire-emac.bat`) and **re-import** — changing the language
on an analysed program does not re-disassemble what the old one got wrong.

### 2.8 Device data comes from DNX, never from hand-rolled MIDI

`scripts/sysex_capture.py` was written and deleted the same day. Two bugs, a
truncated dump, and the owner asking *"why don't you use DNX?"* twice. Ask the
DNX session.

**Port hazard:** both instruments are connected and the indices do not line up
between directions. Pair by **name** — `Elektron Digitone` / `Elektron Digitone II` —
never by index.

---

## 3. The build discipline that has worked

- **One question per flash.** v1 asked "is the page id enough?" (no). v2 asked
  "plus the routing byte?" (no). v3 asks "plus the classifier?" — and carries
  nothing else, so its answer is unambiguous.
- **Assert stock bytes before writing.** Every edit checks the encoding it
  expects and refuses otherwise.
- **Geometry guards.** Check that named records still resolve to their expected
  names before touching a table — a wrong anchor into a dense table still
  yields plausible strings.
- **Verify the rebuild.** `dnfw inspect` must reproduce every checksum *and* the
  HMAC trailer — which `docs/version-gate.md` §2 proves MAIN OS actually checks
  at flash time.
- **Builds are gitignored.** `00_Resources/02_Builds/<subject>_DN2_<version>.syx`.
  No firmware bytes in the repository, ever.

---

## 4. What is NOT yet proven, and must not be written up as fact

- Everything in §1 layers 3–8 is **read but not flashed**. The v3 build is the
  first test of layer 3.
- The `[MOD]` page count (`0x40061558`) has a second registration with count 2
  that is **not explained**.
- Whether the emulator (`emu/`) can boot a DN2 image at all is **untested** —
  Unicorn needs digikit's two m68k patches built from source, and their
  installer is POSIX-shaped.

## 5. The first thing to test this playbook on

**A third LFO for MIDI tracks.** The owner asked for it on 2026-09-16 as a
**separate feature** from LFO4, and it is the ideal validation: the same eight
layers of §1, different addresses, and the answer for every layer is already
known for its sibling.

What is already in hand for it, from the LFO4 work:

- MIDI tracks ship **2** LFOs (owner, confirmed against the factory firmware).
- The view-id pool registration for the MIDI group is **`(0x401e0000, 2)`**,
  ids `0x23 0x24`, at `0x40061868` — counts and pool packing in
  `docs/lfo4-build-plan.md` §5.
- `MidiParameterSet`'s ownership predicate is `0x400dbfbc`, pages `0x16`–`0x1c`.
- The same single `LfoPageView` serves both groups, so no new view class.

**If this playbook is any good, that build is much shorter than LFO4's.** If it
is not, the gap says which layer the playbook under-describes — which is the
only honest way to test a document like this.

**This file gets its final form when LFO4 works on hardware.** Until then it is
a record of what has cost time, which is useful on its own and honest about the
rest.
