# The display path, found by watching the screen instead of naming a function

**Measured 2026-09-13 on Digitone II 1.11**, against digikit `ec32de1`, resumed
from the 400M boot rung with the UI drawing (409 frames composed).

This project named the display path twice by reading code and was wrong twice —
`Sound::updateMirror` was a vtable-only lambda nothing calls, and forcing
`parameter_value_getter`'s return changed nothing on screen. The rule that came
out of it is that **an instruction pattern confirms an address, never a role**.

So nothing here is named by eye. `scripts/paint_map.py` watches the bytes that
*are* the screen and records the `pc` of every instruction that writes one; a pc
that wrote a pixel is on the display path by definition.

## 1. The write hook fires — and that settles a second question

1,637,709 framebuffer writes from 29 distinct pcs across 209M instructions.

That matters beyond this page. `scripts/write_map.py` used the same
`install_mmio_trace` mechanism over candidate cave RAM and printed `events: 0`
twice, and both runs were too short to reach the code that writes — so *"the
hook does not fire"* and *"nothing wrote"* were never separated, and the write
map has never produced a number anyone could read. **The mechanism works.** Its
zeros were run length, not blindness.

### The buffers are behind pointers, and the first run of this got it wrong

`profile.fb_front` and `fb_back` are the addresses of the **pointers**, not of
the buffers — they sit four bytes apart, and `emu.panel.read()` dereferences
before reading 1024 bytes. Watching them directly watches the pointer variables
and the RAM after them.

The first run did exactly that and produced a confident, plausible table: 1,521
writes, 6 pcs, neat 32-bit widths. Nothing in the output looked wrong. It was a
map of a data structure that paints nothing.

> **A watch aimed at the wrong address does not report an error. It reports a
> table.** The tell was arithmetic and available before the run: two
> "framebuffer addresses" four bytes apart cannot both be 1024-byte buffers.

## 2. The drawing primitives

Every pc that wrote a screen byte, grouped by the function containing it
(`dnfw fn entry --at`):

| entry | direct callers | writes | shape |
|---|---|---|---|
| `0x40113b90` | 18 | 1,302,866 | read-modify-write — reads == writes |
| `0x40114d94` | 34 | 104,448 | **writes only, no reads** — a fill or clear |
| `0x40114842` | 90 | 75,656 | read-modify-write |
| `0x401157fc` | 108 | 45,598 | read-modify-write |
| `0x40115118` | 5 | 49,434 | read-modify-write |
| `0x40113cf4` | 21 | 28,511 | |
| `0x40113edc` | 18 | 1,124 | |
| `0x40131d8e` | 2 | 1,024 | writes only — in the `panel_diff` neighbourhood |

The two with 90 and 108 direct callers are the general-purpose primitives the
whole UI draws through. `0x40114d94` writing without ever reading is the
signature of a fill: it does not need the old pixels.

**These are leaves, not the page renderer.** They say where the ink goes.

## 3. Walking back: only 2 of 34 callers actually fire

`scripts/caller_map.py` hooks a function entry and reads the return address off
the stack, which on ColdFire is `(sp)` at the first instruction of a callee.

`param_index_in_page` (`0x400dbcc4`) — **2,798 entries, 2 distinct callers**:

| returns to | count | enclosing function |
|---|---|---|
| `0x40037166` | 2,797 | `0x40036bac` |
| `0x400371cc` | 1 | `0x40036bac` |

So the static list of 34 is right and almost all of it is cold. One function
does essentially all the parameter-table indexing this instrument does while
drawing.

### The control: two unrelated instruments agree to the byte

The runtime return addresses are `0x40037166` and `0x400371cc`. The static
caller scan reports call sites at `0x40037160` and `0x400371c6` — **exactly six
bytes earlier in both cases**, which is the length of `jsr <32-bit absolute>`.

A linear disassembly scan in this repository and a stack read inside someone
else's emulator, sharing no code, land on the same two instructions. Neither was
adjusted to fit the other.

### And the chain above it

| watched | live caller | count |
|---|---|---|
| `param_index_in_page` `0x400dbcc4` | `0x40036bac` | 2,798 |
| `0x40036bac` | `0x4003951e` — **the destination-list builder** | 2,097 |
| `parameter_value_getter` `0x4006408a` | `0x4006538e` | 2,796 |
| | `0x40063af0` | 233 |

`0x4003951e` is already named in `docs/version-anchors.md` as the
destination-list builder — found independently, months of reasoning earlier, by
following the four filter sites. It turning up here as the live caller is
corroboration from a direction that was not looking for it.

**`parameter_value_getter` runs constantly** (3,031 calls) even though forcing
its return changes nothing on screen. Both facts are now measured, and together
they say it computes a parameter value for something that is not the pixels —
which is a live lead rather than the dead end it looked like.

## 4. A candidate for the page renderer, explicitly not confirmed

`0x400167a4` (7 direct callers) calls the text primitive `0x401157fc` 466 times,
and it sits where 1.10E's `FUN_40016f38` — identified in
`docs/parameter-table-consumer.md` as the `[MOD]`/parameter page renderer — would
land after the relink. Its body repeats one block (`0x40046bfe`, `0x40030e66`,
two vtable calls, then `0x4003e426`, the engine thunk site named in
`docs/version-anchors.md`) several times over, which is the shape of a loop over
parameter cells.

**This is a candidate and nothing more.** No reference to the 1.11 record base
`0x401f7f94` was found in its first 1,600 bytes, and "it is near where the old
one was" is precisely the reasoning that produced two wrong identifications
already. It gets confirmed by a role test or not at all.

## What this does not establish

**No input is modelled** (`docs/emulator.md`), so every count here is from an
undriven boot sitting on whatever page it starts on. Nothing reached only by
pressing `[MOD]` or turning an encoder appears, and that includes the whole
mirror path — which is why `updateMirror` and its enclosing function stay silent
in every run so far. Those zeros still mean "not entered during an undriven
boot".

## Reproducing

```
python scripts/paint_map.py  --digikit ~/digikit --snapshot ~/snaps/boot400M.snap
python scripts/caller_map.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
    --at 0x400dbcc4 --at 0x4006408a
dnfw fn <image> entry   --at <pc>        # what function is this
dnfw fn <image> callers --at <entry>     # and the static list to check against
```

Ask `emu.run.usable_rung()` which snapshot to resume; do not copy a rung number
out of a docstring (`docs/emulator.md`).

---

# The emulated instrument, and what it is actually showing

Every count on this page was taken while the firmware was drawing **a real
parameter page**. That is not an assumption — here is the frame, captured at
`panel_diff` entry and written out by `scripts/drive.py`:

![The DN2's SYN1 page under emulation](img/syn1-page.png)

`TUN1 WAV1 PD1 LEV1` over `TUN2 WAV2 PD2 LEV2`, with knob widgets, the `SYN 1`
track badge and a level meter — the Digitone II's SYN1 page, rendered by the
firmware into its own framebuffer. The `Loading...` banner is the modal digikit's
`weakptr` diagnostic exists to clear; the page is drawn underneath it regardless.

**Screens are archived as PNGs in `docs/img/` rather than described.** A byte
count says a screen changed; a picture says what it changed to.

## Two configuration facts, both measured, both costing a run

**DMA timer channel 1 makes this build worse.** digikit's `build()` docstring
says `channels=(3, 1)` stops a fault, so it was added. Measured on 1.11:

| timer channels | richest frame | what it shows |
|---|---|---|
| `(3,)` | **2,183 lit** | the SYN1 parameter page above |
| `(3, 1)` | 411 lit | the boot animation; the page is never reached |

It did not stop the fault either. **Digitakt's fix is not Digitone's** — the
same lesson as the boot rung, learnt twice from the same docstring.

**`weakptr` is unavailable on 1.11.** Its patch site is build-specific and
digikit's guard refuses:

```
RuntimeError: weakptr: 0x40188b40 holds 4878, expected 6714
```

That is the guard working exactly as it should.

# Input is modelled, it works, and the halt was my own bug

`emu/panelin.py` implements the front panel properly — buttons and encoders over
UART8, addresses resolved per build. digikit's README saying "No input" is
stale. The firmware's own control table reads out of the running image:
**55 buttons** (`TRIG SRC FLTR AMP FX MOD PRESET SETTINGS …`) and 10 encoders,
so `MOD` is button code 6, channel 0 bit 5 — found by name, not guessed.

`scripts/drive.py` drives it, and **the input path works end to end**:

| step | new frames | bytes changed | executed | stop |
|---|---|---|---|---|
| idle (no input) | 69 | 168 | 43,013,859 | limit |
| press+release `MOD` | 64 | **616** | 20,030,401 | limit |
| `ENCODER A +10` | 117 | **120** | 40,060,798 | limit |

Both move the screen by far more than it moves on its own, which is what the
idle control exists to establish. And the screen goes somewhere real — the
`Loading...` banner is replaced by the project name and a live tempo:

![The main screen after driving the panel](img/encoder-a--10.png)

## The retraction, and it is the most useful thing on this page

**This first reported `unhandled vector 257 at 0x4011eb0e` — a `halt`
instruction — as a digikit bug, and filed it upstream. It was my own defect.**

`panelin.feed()` returns the new pc, and the script threw it away:

```python
panelin.press(m, p, 0, 5)                  # returns the ISR pc -- discarded
pc, ran, stop = longrun.spin(m, pc, ...)   # resumed at the PRE-injection pc
```

`raise_vector` pushes an exception frame and sets the pc to the handler.
Resuming at the pc from *before* the injection runs the firmware on with a
stray exception frame on its stack, and it asserts. The `halt` was the firmware
correctly detecting the corruption I had introduced.

Three things went wrong in order, and only the third was expensive:

1. The docstring says `-> new PC`. I read past it.
2. The failure looked like a firmware panic, because it *was* one — just one I
   caused. A correct-looking assert is a persuasive wrong answer.
3. **I wrote it up and filed it upstream before finding my own bug.** The
   measurement was real and the interpretation was not, and the direction of
   the error — blaming someone else's code — is the one that costs other people
   time rather than only mine.

The rule this earns, which is the same one this project already applies to
addresses, now pointed at ourselves: **before reporting a fault in someone
else''s tool, eliminate your own use of it.** The issue is closed with the
retraction (`m-dwyer/digikit#5`).

## But the encoder does not edit a parameter, and that is the result

Input being *delivered* is not input being *useful*. The second half of the
control asks whether a turn changes a **value**, and it does not.

Six `ENCODER A` turns of +10 detents, with the page drawn and the header showing
the loaded project: **the parameter row is byte-identical before and after.**
`TUN1`'s widget does not move. The screen churns, execution changes — driving
the run raises `param_index_in_page` from 2,798 calls to **4,106** and
`parameter_value_getter` from 3,031 to **4,448** — but nothing is edited.

This is exactly the case `docs/emulator.md` recorded the author warning about:
*"the author flags encoder deltas as buggy, so verify the input path delivers a
value change and not merely an event before believing any trace — a broken delta
lights the wrong half of the path and looks like a result."*

It looked like a result. The control caught it.

### So the mirror probes are still unanswered

With input driven, `M`, `S`, `F`, `B`, `C` and `A` — the `updateMirror` lambda,
its enclosing function, the fill loop, both bulk copies and one pip consumer —
**all still report zero**.

That is **not** evidence that they are off the parameter-edit path. No parameter
was edited. A probe cannot be absent from an event that never happened, and
reading those zeros as a finding would be the same error as reading the trace
harness's blank columns as one.

**The engine-feed path is therefore still not reachable by driving the UI**, and
it stays on the static route: `0x4003951e` (the destination-list builder, and
the live caller found above) and `0x4003e426` (the engine thunk site).

Not reported upstream: the author already flags encoder deltas as buggy, so this
corroborates a known issue rather than finding a new one — and this page has
already spent one upstream report on a defect that turned out to be mine.

## What does not change

The `channels=(3,)` vs `(3, 1)` measurement above stands — it was a separate
observation with its own evidence, and had nothing to do with the halt.

---

# The encoder delta, traced to where it actually stops

digikit's author flags encoder deltas as buggy, and `docs/emulator.md` carries
the warning. This is how far the delta gets on Digitone II 1.11, measured
against `ec32de1`. It gets **much** further than "buggy" suggests, and the
failure is in one identifiable place.

## It is delivered, and the firmware decodes it correctly

Hooking `queue_send` (`0x40001896` — 37 direct callers on 1.11, the same
address digikit uses on Digitakt) reads the firmware's **own decoded record**
for the event, which is ground truth: it is immune to render timing, modal UI
and frame tearing, because no pixel has to move for it to exist.

Sending `panelin.encoder(m, profile, 0, 5)` — ENCODER A, +5 detents — produces:

```
ret=0x4011f780  type=1  code=1  delta=+5
raw=01000000 00000001 05000000 00000000
```

`type=1` is an encoder record, `code=1` is channel 0 + 1 = **ENCODER A**, and
the delta byte at `+0x08` is **exactly the 5 that was sent**. The ring drains
completely: `produced: 2, consumed: 2`.

So the wire format, the DMA ring, the RX vector, the driver and the firmware's
own decoder are all correct. **Nothing on the input side is broken.**

| stage | works? | evidence |
|---|---|---|
| bytes into the DMA ring | yes | `produced` advances |
| RX vector, driver drains it | yes | `consumed` catches up |
| firmware decodes the event | **yes** | its own record, right code and delta |
| queued to the application | yes | `queue_send` at `0x4011f780`, in `0x4011f5d0` |
| consumed by the app | yes | `queue_receive` `0x40001928`, 622 of 625 returns to `0x4002f184`, in **`0x4002e91c`** — the main task's message loop |
| UI reacts | **yes** | the label under encoder A switches from `TUN1` to a live value readout |
| **the value changes** | **no** | `0.00` after 45 detents |

## Timing matters, which is the owner's insight showing up in the data

The Digitone scales an encoder's sensitivity by how fast it is turned. That is
visible here, and it is why the first attempts looked like nothing happening at
all:

| input | result |
|---|---|
| 6 × `+10` in a burst | **nothing** — parameter row byte-identical |
| 15 × `+1`, ~10M instructions apart | **the label switches to the value readout** |
| 5 × `+1`, ~50M apart | nothing — too slow, the overlay never engages |
| 30 in one message | nothing |

So the firmware is applying its acceleration logic, and it takes a *plausibly
timed turn* to engage at all. A burst is not a fast turn; it is one message.

## Where it stops

The UI engages — the encoder is recognised, the parameter is focused, the value
overlay replaces the label — and then the value stays at `0.00` through 45
detents in either direction. The `panelin` docstring says the firmware
"accumulates deltas per encoder and clamps what it flushes to ±30", so the
shape of the remaining bug is an **accumulate-and-flush that engages but never
flushes**, which would look exactly like this.

That is a hypothesis and is recorded as one. What is measured is the table
above.

## Why this is worth having anyway

**The consumer is the parameter-edit path.** `0x4002e91c` takes the encoder
record and is supposed to turn it into a parameter change — which is the
**engine-feed path** this project has been hunting by other means all along.
Finding it by following an encoder event is a better provenance than any
pattern match: it is the code the firmware itself routes the input to.

So even unfixed, this hands LFO4 the function it needs to read, with a role
established by observation rather than by name.

## Root cause candidate: the encoder timestamps itself from a timer nothing drives

Found by pointing `scripts/diff_trace.py` at the problem rather than reading the
2 KB message loop by eye.

**The instrument, and the correction it needed.** Record every basic block the
CPU enters during an idle window, a driven window and a second idle window, and
report what ran only while turning. The first version used *sets* and reported
the UART driver and the RTOS queue and **no application code at all**, at 6
detents and again at 20. That was the instrument, not the firmware: the code
handling an encoder record also runs when idle, so subtracting "blocks that also
ran when idle" deletes exactly what is being looked for. Counting blocks instead
of listing them fixes it — 29 blocks run **exactly once per detent**, all in the
driver at `0x4011fc2c..0x4011fde0` and the queue at `0x40001f1a..0x40001f74`.

That bounded the search to ~440 bytes, and those bytes say this:

```
0x4011fc54  movel 0xfc07000c,%d6        ; <-- DTIM0's counter (DTCN0)
...
0x4011fc90  movel %d3,%a3@(0,%d2:l:4)   ; accumulate the scaled delta
0x4011fcc4  movel %d6,%a2@(4)           ; store that timestamp per encoder
```

`d6` is read from `0xfc07000c` and **only ever stored**, never compared or used
arithmetically here. `BASES[0] = 0xFC070000` in digikit's `emu/dtim.py`, and
offset `0x0C` is `DTCN` — so the driver stamps every encoder event with **DMA
timer 0's free-running counter**, for something downstream to measure speed
with. That is the device behaviour the owner described: the Digitone scales an
encoder's sensitivity by how fast it is turned.

**And that counter never moves.** Measured in the emulator:

| address | what | value |
|---|---|---|
| `0xfc07000c` | DTIM0 `DTCN` | **0, 0, 0** — never advances |
| `0xfc070000` | DTIM0 `DTMR` | `0x0000` — not enabled |
| `0x466758b0` | the millisecond tick global | 1095 → 1426 over 30M instructions ✓ |

digikit models DMA timer channels by request and defaults to `(3,)`; **channel
0 is never among them**. So every encoder event is stamped `0`, every interval
between detents computes as zero, and a delta scaled by a zero interval
plausibly scales to nothing — which is precisely the observed behaviour: the
parameter focuses, the value overlay appears, and the number never moves.

**Stated as a candidate, not a conclusion.** What is measured is that the driver
reads DTCN0, stores it per encoder, and that DTCN0 is stuck at zero. That the
downstream consumer divides by or compares against it is inference, and the
arithmetic has not been read. It is written here as the next thing to check, not
as the answer.

Two things this did *not* turn out to be, both of which were checked:

- **The branch at `0x4011fc70` is not a rejection.** It looked like "too fast →
  clear the accumulator", and instrumenting it shows the **process** path taken
  on every detent at every spacing tried (6 of 6, at 10M, 40M and 80M apart) and
  the clear path never. Reading a branch direction off a disassembly and
  believing it is how this project has been wrong before; the hook settled it in
  one run.
- **`0x4017cea4` is not the acceleration helper.** It was hooked on that
  assumption and fires 60,000–480,000 times in a window with six detents — it
  scales with run length, not with input. A count is what exposed that; the
  name would not have.
