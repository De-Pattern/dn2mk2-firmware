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
| commit | **`ec32de1`** — "Merge pull request #1 from angellinares/depacker-address-per-build" |
| licence at that commit | GPL-2.0-or-later (`LICENSE` = GPL v2 text) |

Earlier findings on this page were produced against **`c282f0c`**, one commit
before ours landed; they are marked where it matters.

### Our contribution, merged upstream

`m-dwyer/digikit#1` — *"Resolve the depacker's address per build, so Digitone II
1.11 extracts"* — merged 2026-09-13 as `ec32de1`. digikit hard-coded the
address of the updater's aPLib depacker, a constant derived on Digitakt II
1.15C. It holds on DN2 1.10E and fails on 1.11 with `implausible output length
0`. The fix tries the constant and falls back to locating the routine in the
image: 1.10E resolves to `0x80005710`, reproducing their constant exactly, and
1.11 to `0x80005720`.

**digikit now extracts 1.11 by itself**, which retires
`scripts/export_sections_for_digikit.py` as a *requirement* — the write-map runs
below pass no `--sections-dir` and digikit does its own extraction. The script
stays, because `--verify-against` is still how the two extractions are compared.

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

---

# The write map: the run designed to tell two outcomes apart

`scripts/write_map.py`, against digikit **`ec32de1`**.

A value watch cannot answer the question this project keeps asking of it. The
array is cleared with `clrl` — it is *written with zeros* — so "cleared to zero"
and "never touched" both read `0x00000000`. `Machine.install_mmio_trace` gives
range-scoped **write hooks** instead: a zero store is an event like any other,
and it carries the `pc` that made it, which a value watch could never produce.

Since 1.11 now extracts in digikit itself, these runs pass no `--sections-dir`.

## Run 1 — the control caught the run, exactly as intended

120M instructions, 16 regions (12 candidates that pass both static checks, plus
4 known-live array records as positive controls):

```
events: 0        controls_written: 0/4        candidates_written: 0/12
*** CONTROL BLIND ***
```

**And that is a successful run of the instrument, not a failed experiment.** The
harness refused to print a table of zeros as a result, which is precisely what
`docs/trace-harness.md` and the first watch run above did not do.

### The control had its own blind spot, and this is how it showed

A blind control still does not say *why*. "The write hooks are not firing" and
"the run never reached the code that writes" produce the same zero. The earlier
400M run on this page records the main application task starting at
**n ≈ 315.7M** — so at a 120M limit the clearing loop at `0x4002a4d2` had not
executed, and the control could not have been written no matter how well the
hooks worked.

So the clearing loop's own address is now hooked as well, and the two failures
report differently:

| loop hits | writes to controls | verdict |
|---|---|---|
| 0 | 0 | **RUN TOO SHORT** — raise `--limit`; says nothing about anything |
| >0 | 0 | **CONTROL BLIND** — the hooks are not firing; ignore the table |
| >0 | >0 | the instrument works; the candidate rows mean something |

That is the same lesson for the fourth time, one level up: **it is not enough for
the experiment to discriminate — the control has to discriminate too.**

## What a clean result will and will not mean

A cold boot plays no notes, turns no encoder and loads no project. The device
faulted *while the keyboard was played*. So a candidate region with no writes has
earned exactly one sentence — **"not written during cold boot"** — and the
harness prints that caveat next to its own table rather than leaving it here.

---

# The call map: the run that settled what four flashes could not

`scripts/call_map.py`, against digikit **`ec32de1`**, on Digitone II 1.11.

`docs/trace-harness.md` spent a flash asking eleven functions "did you run?" and
got back two marks, nine blanks, and **no way to tell two opposite readings
apart** — because a stamp written once at boot and a stamp rewritten constantly
look identical. The emulator does not have that problem: a call **count** never
travels through the display.

Resumed from the 400M rung, 209M instructions, UI alive:
`param_index_in_page` **2,798 calls** across ten separate slices,
`parameter_value_getter` **3,031**, pip consumer B **2,097**. The nine blank
columns did not mean those functions never run. Full table and what stays open:
`docs/trace-harness.md`.

**It cost a script and 33 seconds.** The same question had already cost four
flashed images and a week, and the emulator had been sitting in this repository
for a day. The instrument to reach for first is the one whose negative result
means something.

## The rung is a phase — and the tool already knew which one

digikit's boot ladder snapshots at 60/120/200/280/400M instructions, and
`emu.run.usable_rung()` picks between them **by inspecting each snapshot's
state**, because two firmwares do not reach the same place at the same count.

On 1.11, rendering each rung with digikit's own `emu.panel` for 60M
instructions:

| rung | frames flushed | distinct |
|---|---|---|
| 120M | 0 | 0 |
| 200M | 0 | 0 |
| 280M | 0 | 0 |
| **400M** | **173** | **109** |

120M–280M never compose a frame and leave `timers_held` true: the intro never
hands over. Only 400M draws.

**`usable_rung()` returns 400M for this build.** It was right; the error was
mine. Its docstring illustrates the idea with *"on Digitone only 400M is
disqualified, and it gets 280M"* — a **1.10E** observation — and I read that
example as a rule for Digitones, hand-picked 280M, and spent two full runs
watching a dead machine report "nine silent functions".

> **An example in a docstring is not a specification.** The check cost one line
> (`usable_rung(prefix, default)`) and would have replaced both runs.

This was nearly written up as a digikit bug and a PR sent for it. It is not a
bug. Verifying the claim before filing it is what stopped a wrong report going
upstream — and the same claim had already been written into this file, a commit
message and a pull request body before the check was run.

## Two traps inside digikit that a harness must not step in

**`setPixel` is not the screen.** `longrun.build(bitmap=True, on_pixel=...)`
intercepts `Bitmap::setPixel`, which is the **intro's** drawing primitive. The
main OS composes text and widgets straight into a framebuffer and never calls
it, so `setPixel` counts near zero while a complete UI renders. digikit's
`emu/panel.py` says this cost its author a session. The real signal is
`panel_diff`, the routine that diffs the two 1024-byte buffers and flushes the
changed runs — entering it means a frame was composed. `call_map.py` counts
frames there, after first being written the wrong way.

**The timers are not optional.** PIT2 spawns the OS tasks and DMA timer 3 is the
30 Hz tick whose ISR is the only thing at boot that posts to the queue the main
application task blocks on. Without them that task makes one pass through its
message loop and waits forever — a machine that is running and doing nothing,
whose every zero belongs to the harness rather than the firmware.

## A control has to be asked for in the phase it lives in

The first version of `call_map.py` required both hardware-marked probes, `R` and
`E`, in every run. A post-boot window then printed **"control silent"** while
three probes were firing thousands of times, because `R` is boot-phase: from the
280M rung it fires 697 times between 5M and 21M and never again.

Demanding a boot probe in a post-boot window is demanding a negative. That is
the same defect as a watch that cannot produce a different answer per outcome —
this time wearing a control's clothes. The controls now carry their phase, and
silence in the wrong window is reported as expected rather than as blindness.

## The patched Unicorn is built and verified — 2026-09-16

**Read this section's predecessors first.** "Running it on this machine" and
"Digitone II **1.11 cold-boots**" above already recorded the WSL decision, the
venv-placement caveat, the CRLF trap and the fact that 1.11 boots. On
2026-09-16 the assistant re-derived all four from scratch before reading them.
That is the same mistake the owner had just corrected one layer up — *"don't
reinvent the wheel"* — and it applies to **this repository's own documentation**,
not only to the reference repos. It is recorded in
`docs/FEATURE-PLAYBOOK.md` §2.0.

What is genuinely new, and was not here before:

**The patched library exists and passes digikit's own check.** Built under WSL
Ubuntu 24.04 (cmake 3.28.3, gcc 13.3, Python 3.12.3), venv in WSL's own
filesystem at `~/dn2-emu-venv` exactly as the caveat above says:

```sh
python3 -m venv ~/dn2-emu-venv
~/dn2-emu-venv/bin/python -m pip install unicorn==2.1.4 capstone==5.0.7
cd /mnt/c/ZZ_Code/ZZ_Personal/digikit
PYTHON=~/dn2-emu-venv/bin/python bash tools/install-patched-unicorn.sh
```

Tag `2.1.4` resolved to `8028ec436f2d9376525352dd38ed9ed6b9f6be10`, the commit
digikit pins, and both patches applied at their pinned SHA-256. `emu.unicorn_compat`
then reported `"compatible": true` with **all four cases passing**, including
`emac_mac_with_load` — the EMAC fix that matters for the modulation kernel at
`0x400db1dc`.

**Their extractor agrees with ours, byte for byte.** `python -m emu.extract` on
DN2 1.11 produced six sections whose lengths match `dnfw extract` exactly —
MAIN OS 3,192,192, bootstrap 30,302, updater 32,768, blob 836,956, section 8
159,948, meta 15. Two implementations sharing no lineage agreeing on a depacker
is worth more than either one's tests.

(One naming difference to expect: digikit labels section 2 `section_2_DSP.bin`.
On the DN2 that section is the **bootstrap**, `dest 0x02010000`. The label is
theirs and is wrong for this device; the `dest` is right and nothing reads the
label.)

**`emu.run --check` passes on 1.11**, resolving firmware, sections and the
snapshot path, with their standing warning that only Digitakt II 1.15C is
tested.

### What is running, and what it is for

A snapshot ladder cold boot at 60M / 150M / 280M / 400M instructions, because
`tools/bootcheck.py` and the `--resume` half of `tools/addrtrace.py` both need
a snapshot, and only a resume reaches the display module.

The target is the question §"What it is for" lists and `docs/lfo4-build-plan.md`
§3 cannot answer statically: **which value-array sites can ever see a slot
≥ 101.** That is reachability, and reachability is what static scanning has got
wrong three times here.

**Carry the positive controls** listed above under "The first watch run was not
a result" — `0x401f7f94` static, `0x42c64b3c` built at boot, a live TCB. A zero
without them means nothing.

## What actually stops the emulator answering UI questions — 2026-09-16

The owner asked, fairly: *"can you not check these questions in the emulator? Is
there anything stopping that?"* The answer is **nothing fundamental, and one
concrete prerequisite**.

**What already works on Digitone II 1.11 here:**

| | |
|---|---|
| boot to `MAIN_OS_RUNNING` | yes, from `boot400M.snap` |
| `tools/bootwatch.py` write watches | yes — it settled the descriptor-id writer |
| `tools/addrtrace.py` code hooks | yes |
| `tools/panelsweep.py` — map panel button codes | running; it reads the firmware's own `queue_send` record, and its record layout was *"verified across dozens of samples on Digitone"* |
| `tools/guirun.py` — **headless** panel input + screenshots | the right tool: `--input 150M:press:17`, `--png-at 170M:out/x.png` |

**The prerequisite.** Starting a run on 1.11 prints:

```
unresolved OPTIONAL symbols: ['call_sites', 'ctx_switch_load',
  'display_frame_post', 'display_sem', 'transport', 'ui_key_dispatch',
  'ui_tick_counter', 'ui_tick_inc', 'view_activate', 'view_close',
  'view_closed_mark', 'view_offer', 'view_request_pop', 'view_sweep']
```

**Six of those are exactly the UI ones** a widget-selection question needs —
`ui_key_dispatch`, `view_activate`, `view_close`, `view_offer`,
`view_request_pop`, `view_sweep`. They are derived by byte signature from
Digitakt II 1.15C and do not match this build.

That is the **same class of problem as `mainloop`**, which was one byte (a
`moveq #40` against `moveq #41`) and is now fixed and sent as digikit PR #16.
Thirteen more of the same kind is real work, but it is tractable, mechanical,
and it benefits digikit as much as us.

**So the honest statement is:** the emulator can already answer *memory*
questions on our build and has done. It cannot yet answer *UI* questions,
because the UI hook points are unresolved — and that is a signature-porting job,
not a limitation of the emulator.

### Driving the UI: what works now, and the three ports still needed

Attempted 2026-09-16, because the owner asked for screenshots of any page being
worked on. **No screenshot yet.** What was established:

**Working on DN2 1.11:**

- **`tools/panelsweep.py` — the whole panel is mapped.** 192 s, all 56
  `(channel, bit)` groups in channels 0–6 report `code = channel*8 + bit + 1`,
  and the nine encoders `code = channel + 1` — identical to 1.10E. One anomaly,
  code `0x00` shared by `(6,2)` and `(6,3)`, matching the non-linear channel 6
  the device file already documents.
- **The device file.** `tools/guirun.py` refused the firmware with *"No device
  file matches"* until `devices/digitone-ii.toml` gained a 1.11 entry. That
  refusal is correct behaviour — it would otherwise run this image under another
  product's panel. Added and sent to digikit as branch `devices/dn2-1.11`.

**Still to port from Digitakt II 1.15C, and each is the same shape as the
`mainloop` byte:**

| what | symptom on 1.11 |
|---|---|
| six UI symbols — `ui_key_dispatch`, `view_activate`, `view_close`, `view_offer`, `view_request_pop`, `view_sweep` | reported unresolved at startup; no UI tracing |
| the `--weakptr` patch | `RuntimeError: weakptr: 0x40188b40 holds 4878, expected 6714` — a hardcoded address and value |
| whatever else the terminal loop needs | without `--weakptr`, a resumed run reaches `TERMINAL LOOP` at ~63 M with `tasks=0` |

**So the position is:** the emulator answers **memory** questions on our build
today, and has — `bootwatch` settled the descriptor-id writer, and `bootcheck`
reports `MAIN_OS_RUNNING`. It cannot yet **drive the panel and draw a page**,
and that is three small ports away, not a limitation of the tool.

Worth doing: it is the difference between guessing at widget selection and
watching it.
