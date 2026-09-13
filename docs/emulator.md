# The emulator, and how this repository refers to one it does not own

`m-dwyer/digikit` emulates the Digitone II's control processor well enough to
boot the OS, render the panel and take encoder input (`docs/references.md`).
This records how it is wired in, and why that way.

## Where it lives

```
C:\ZZ_Code\ZZ_Personal\digikit\        a plain git clone, tracking origin/main
```

**A sibling of this repository and of DNX, not inside either.** Nothing of
digikit's enters this repository at all.

It was first cloned into `00_Resources/01_Reference/` beside the other seven
references, and promoted within the hour on the owner's instruction: *"clone it
in personal so DNX can use it too."* That is the right call, and it is worth
saying why rather than just recording the path.

The other seven are **source to read**. digikit is **a tool to run** — it has a
virtualenv, a compiled native dependency, and a command line. A tool used by two
projects should not live inside one of them, because the moment DNX depends on
it, DNX depends on a path inside `dn2_firmware`'s gitignored scratch space.

And DNX's claim on it is real rather than hypothetical. DNX's object model was
derived from **hardware captures**; an emulator that runs the same firmware lets
those decoders be checked against the code that produces the bytes. The ~90
`MidiRpc` request/response pairs in `docs/midi-rpc.md`, parked for want of a way
to exercise them, are the obvious first use.

One caveat before DNX leans on it: **storage is not served**. digikit's eSDHC
and eMMC models handle card identification only, and `CMD18` reads return zeros,
so `+Drive` traffic has nothing behind it yet. The protocol path can be traced;
the data cannot be read.

## Why a plain clone and not a submodule

Three ways to depend on someone else's repository, and only one suits this:

| | what it does | why not / why yes |
|---|---|---|
| **submodule** | records URL + **a pinned commit** inside our tree | it writes a **GPL-2.0 dependency into a public AGPL repository's history** — legal, but a statement about this project that is not true: we *run* digikit, we do not build on it. It also pins rather than tracks, so "tied to main" needs `git submodule update --remote` and a commit every time; and it leaves contributors on a detached HEAD, which is how stale pointers get committed |
| **subtree / vendoring** | copies their source into our tree | licence mixing and bloat, and this repository holds only its own code and docs |
| **plain clone, gitignored** ✅ | an ordinary working copy beside the others | simplest; `git pull` tracks their `main` with no ceremony; **zero entanglement** — nothing about digikit appears in our history, which keeps the AGPL/GPL question academic for as long as we only run it |

**It is not in `ZZ_Personal/` root** because that level is for the owner's own
projects — `DNX` is a sibling because the owner wrote it. digikit is
third-party tooling used by *this* project. If DNX ever needs it too, promote it
then; premature promotion just puts a shared dependency somewhere nobody owns.

## Tracking their main — and the discipline that makes it safe

```sh
cd 00_Resources/01_Reference/digikit
git pull                 # follows origin/main
git log --oneline -1     # <- record this
```

A plain clone follows `main` for free. The hazard is the opposite one: **their
main moves, and our findings drift without anyone noticing.** A result produced
against one revision of an emulator is not automatically true against the next,
and this project has already spent a week on results that were not what they
appeared to be.

> **Rule: every finding produced in the emulator records the digikit commit it
> was produced against**, in the same line as the finding. Not in a setup
> section, not once at the top of a file — beside the claim, like a date.

Because it is emphatically a *moving* dependency: the licence itself landed in
`c282f0c`, days after the repository became useful, and the README already
disagrees with the handover notes about what works.

### Working revision

| | |
|---|---|
| clone date | 2026-09-13 |
| commit | **`c282f0c`** — "Licence this GPL-2.0-or-later, because it cannot be MIT" |
| licence at that commit | GPL-2.0-or-later (`LICENSE` = GPL v2 text) |

## Running it on this machine

digikit needs **Python 3.12** and `uv`, and its Unicorn patch installs through a
shell script. This machine:

| | |
|---|---|
| Windows Python | 3.14.7 — **too new**, digikit pins 3.12 |
| WSL Python | **3.12.3** — correct |
| `uv` | not installed on either side |
| `tools/install-patched-unicorn.sh` | a shell script — wants a POSIX shell |

So **WSL is the natural home**, which is also where this project already reaches
for `m68k-linux-gnu-as` and `objdump` (`patch/assemble.py`, `image/objdump.py`).
The clone stays on the Windows side and is reached from WSL as
`/mnt/c/ZZ_Code/zz_personal/dn2_firmware/00_Resources/01_Reference/digikit`.

One caveat worth knowing before it wastes an hour: building a native extension
against a `/mnt/c` path is slow and occasionally trips on permissions. Put the
**virtualenv inside WSL's own filesystem** even when the source is on `/mnt/c`.

### The CRLF trap — hit immediately, and it will recur

A repository cloned by Git for Windows with `core.autocrlf=true` — the default
here, and visible in this project's own commits as *"CRLF will be replaced by LF
the next time Git touches it"* — checks shell scripts out with **CRLF line
endings**. Run one under WSL's bash and you get:

```
tools/install-patched-unicorn.sh: line 3: set: pipefail: invalid option name
```

`set -euo pipefail\r` — bash is rejecting `pipefail\r`, not `pipefail`. The
message names a real bash option as invalid, which sends you looking at bash
versions instead of at the bytes. **Every `.sh` in a Windows clone run from WSL
has this**, and the failure wears a different mask in each script.

Fix it once, per clone:

```sh
cd /c/ZZ_Code/ZZ_Personal/digikit
git config core.autocrlf false
git config core.eol lf
git rm --cached -r -q .   &&  git reset --hard
```

Confirm with `head -3 tools/install-patched-unicorn.sh | cat -A` — lines must
end `$`, never `^M$`.

This is the same class of problem as everything else in this section: **the tool
was not lying, the input was malformed, and the error message pointed
elsewhere.**

## Stock Unicorn cannot run this firmware

digikit ships `tools/install-patched-unicorn.sh` for a **destructive SR read**
that corrupts the condition flags. Anyone standing one up from scratch would
debug the *firmware* for days instead of the emulator.

This is the third time this project has met the same trap — radare2's m68k
backend inventing instructions (`docs/mainos-image.md`), and our own trace
harness reporting blanks that meant nothing. **Validate the tool before trusting
its output** is the standing rule, and an emulator is a tool.

So the first thing to run is not our image. It is digikit's own
`tools/bootcheck.py` against a firmware its author has tested, to establish that
the emulator works *here* before anything it says about our image is believed.

## What it is for

Three questions this project has failed to answer by flashing, each of which is
a trace or a memory watch in an emulator:

1. **Is `0x40287ef6` live?** A write watch over that 16-record array either
   confirms the 2026-09-13 crash diagnosis (`docs/flashing.md`) or overturns it.
   The cheapest possible test of the most recent conclusion.
2. **What runs when an encoder turns?** The question behind four silent flashes.
   The author flags **encoder deltas as buggy**, so verify the input path
   delivers a value change and not merely an event before believing any trace —
   a broken delta lights the wrong half of the path and looks like a result.
3. **Where is the display path?** `set_pixel` (DN2 1.10E `0x40105964`) is a
   *named role*, not a pattern match. Everything on that screen goes through it,
   so hooking it and walking back is how the path gets identified — instead of
   the two functions this project named by eye and was wrong about both times.

## Version

digikit documents DN2 **1.10E**; its author says "latest"; ours is **1.11**.
Unresolved, and it decides whether the addresses above transfer directly or need
re-deriving. Ask, or measure — do not assume.

---

# The cross-check, and the bug it found

**2026-09-13, digikit `c282f0c`.** Setting the emulator up made an independent
extraction available for the first time, and it was worth more than the setup.

## Our depacker agrees with the device's own routine

digikit does not reimplement aPLib. Section 4 is the **updater**, stored raw, and
an updater must unpack the image it installs — so it carries the device's own
depacker, at `0x80000432`. digikit **runs that routine under Unicorn** and
decompresses every section with it.

So this is not one reimplementation agreeing with another. It is our Python
depacker agreeing with **the firmware's own code, executed**:

| section | ours vs digikit |
|---|---|
| 2 bootstrap / DSP | **identical** |
| 3 MAIN OS (3,085,696 B) | **identical** |
| 5 meta | **identical** |
| 7 blob | **identical** |
| 4 updater | **differed — 32,776 vs 32,768** |

`docs/references.md` records that `elektron-firmware-tool` should be kept
buildable as an independent cross-check and that it never was, for want of a C
compiler. **This is that cross-check**, from a stronger source than was planned.

## The bug: eight bytes of misalignment in `dnfw extract`

`ours[8:] == theirs`, exactly. We were writing a raw section's **8-byte header
as payload**, so anyone loading `section_4_updater.raw.bin` at `0x80000400` had
every address in it off by eight.

Not every raw section carries one, which is why a blanket rule fails:

```
id 4  updater   header present, declared sum 0, payload stored raw
id 5  meta      15 ASCII bytes of build stamp, no header at all
```

digikit's test, now ours (`Section.raw_payload`): **the declared sum.** A real
header over a stored stream has sum `0` — there is no stream to sum — while a
section that is only payload has arbitrary bytes there, which for `meta` are
ASCII and so never zero. Deciding from the section **id** would be a guess; the
sum is a check.

Their layout is the one confirmed by execution: the depacker at `0x80000432` is
a function entry from that base and reproduces every compressed section. Ours
was not confirmed by anything — it had simply never been compared.

After the fix, **all five sections are byte-identical.**

### Why this one is worth reading twice

It is the same failure as everything else this week, in the mildest possible
form: a plausible model — *"a raw section is stored raw, so write it out"* —
that nothing had ever tested, sitting in the repository looking settled. It cost
nothing here only because the payload bytes were right.

The rebuild path was never affected: `container/ele3.py` reassembles from
`section.stored`, so round-trips and every flashed image are unchanged. This was
an **export** bug, and the only consumer was a human reading the file.

---

# Running it

## Digitone II **1.11 cold-boots**

`tools/addrtrace.py` has a cold-boot mode that needs no snapshot, which is what
makes a first run possible at all. On 1.11, via `--sections-dir` pointed at our
own extraction (`scripts/export_sections_for_digikit.py`):

```
[n=26242562] TASK_CREATE entry=0x400cebb4 prio=0  tcb=0x424388ac
[n=26242651] TASK_CREATE entry=0x400cec98 prio=1  tcb=0x4243c900
[n=26910410] TASK_CREATE entry=0x40000ea0 prio=9  tcb=0x4058bee4
[n=26910480] TASK_CREATE entry=0x40002a46 prio=10 tcb=0x4058d604
[n=64757721] TASK_CREATE entry=0x400d3d86 prio=7  tcb=0x42c45624
```

**The RTOS comes up and spawns tasks.** digikit's README says plainly that
*"every address in this project is specific to"* Digitakt II 1.15C and that a
different firmware *"will very likely not boot"* — so this was not a given, and
1.11 is a build nobody had tried. It is the first time the firmware this project
patches has run anywhere but the instrument.

Two caveats that bound what the run means:

* **`unresolved symbols: transport, call_sites, mainloop, main_queue`.** digikit
  derives these by signature rather than freezing addresses per build, and the
  signatures do not all match on 1.11.
* **No prio-6 task appears.** On 1.10E that is the main application task
  (`0x4002e688`). Its absence at 120M instructions means the run had probably
  not reached the main OS, only the intro.

## The first watch run was not a result, and here is why

120M instructions, watching the flagged array at `0x40287ef6`:

```
0x40287ef8  0x00000000
0x40288000  0x00000000
0x40288b28  0x00000000
0x4028ea02  0x00000000
```

Read naively that says the array is never written, and the 2026-09-13 crash
diagnosis is wrong.

**It says nothing of the kind, because the run carried no positive control.**
Every watch returned zero, and "the region is untouched" and "the watch never
read anything" produce identical output. That is precisely the flaw that made
the trace harness's nine blank columns worthless (`docs/trace-harness.md`), and
it would have been repeated here.

### The controls to carry, and what each one separates

| watch | proves, if non-zero |
|---|---|
| `0x401f7f94` — the parameter records, **non-zero in the image itself** | the watch mechanism reads memory at all |
| `0x42c64b3c` — the sound `ParameterSet` slot table, **BSS, built at boot** by `param_set_tables_build` (`docs/parameter-set-tables.md`) | the boot progressed far enough to build parameter tables |
| `0x424388ac` — a TCB the trace itself reported being created | the run reached the RTOS |

A static control and a dynamic one. Without the first, zero is meaningless;
without the second, zero only means "not yet".

**And even a properly controlled zero would not refute the crash diagnosis.**
The device faulted *while the keyboard was played*. If those records are
per-voice, nothing writes them until a voice is allocated, and the emulator has
no notes and no input. The run that could refute the diagnosis is one that
reaches the main OS **and** makes sound — which is a longer run than this and
possibly one needing the input path digikit's author flags as buggy.

So the honest status is: **the diagnosis is neither confirmed nor refuted**, and
the next run is designed to tell those two apart rather than to produce a number.
