# The Machinedrum's machines on the DN2 (v0.17)

PERC's drum machines become the Elektron Machinedrum's own (SPS-1 UW, OS 1.63): the TRX,
EFM and GND machines as DSP2 computes them, read from the owner's copy of the firmware.
v0.11..v0.16 had the owner's Ravel designs *after* the Machinedrum; these are the
Machinedrum.

## Where the algorithms come from

`../md163/research/md-research.md` (outside the repository: it holds Elektron's code)
records the firmware's layout: an MCF5206e host, two DSP56303s, the OS and both DSP
programs as NRV2B blocks. DSP2 synthesises: per track and per 32-sample block it calls
the machine's init, trig and render through three tables, with the words the host's
scale function made from the eight parameters. Its research tools there (a DSP56300
emulator, `emu56k/`) ran each machine's own code and recorded its output for 19..38
cases a machine (`emu56k/golden/`), and wrote an integer model of each machine that
matches that output bit for bit (`emu56k/md_models.py`, `host_scale.py`).

The firmware is Elektron's, so none of it, nor anything copied out of it (tables, golden
output), is in this repository. The build reads the tables it needs from the owner's
file at build time (`dnfw.md.rom`, `MD_OS_BIN`, default `../md163/md_uw_os1.63.bin`), as
it reads the DN2's own firmware; the tests read the golden vectors (`MD_GOLDEN`, default
`../md163/research/emu56k/golden`).

## How a machine is written (`src/dnfw/md/`)

Each machine is a class with `NAME`, `ID` (the Machinedrum's machine id), `PNAMES` and
four DSL steps (`dnfw.perc.dsl`, the same two-backend DSL as PERC: emit mode writes the
SHARC code, run mode is its model):

| step | when | does |
|---|---|---|
| `host(p, L)` | a block with a parameter change or a note | the eight 14-bit inputs (`core.inp`, `INP0..`) -> the host's words W (`core.ws`); `VW['trg']` says whether it is a note (some scale functions send fewer words without one) |
| `init(p, L)` | the machine was just chosen | DSP2's init |
| `trig(p, L)` | a note | DSP2's trig |
| `render(p, L)` | every 44.1 kHz block | 32 samples into the stream at `OUT0` |

Conventions (`core.py`): a Q23 word is a float (w / 2^23); `mpy` is `*`; the limiter is
`sat` (a clamp); 48-bit envelopes and phases are one float, or a 32-bit phase whose top
15 bits index the sine (`SINE_SHIFT`); I3 is the slot's words, I5 is free inside
`render` (`gnd.out_loop` walks the output). Where a product feeds back on itself block
after block and the 56300's truncation sets the rate (an envelope multiplied once a
block), `core.mpy_floor` reproduces the truncation exactly: GND-SN's pitch ramp was
-6 dB without it, 77 dB with it.

## How each is checked

`test/test_md.py` runs every machine in run mode on every golden case (`dnfw.md.bench`)
and holds it to the Machinedrum's output: signal-to-error ratio of at least 60 dB over
the case, or an error under 2^-20 RMS. The SHARC runner then holds the assembled code to
run mode, bit for bit, as for PERC.

Every golden case of every machine passes; the worst case per machine (signal-to-error
over the case, against the Machinedrum's own output; 200 = bit-exact):

| machine | worst (dB) | | machine | worst (dB) |
|---|---|---|---|---|
| TRX-BD | 100 | | EFM-BD | exact pairs (130) |
| TRX-B2 | 119 | | EFM-SD | 111 |
| TRX-SD | 106 | | EFM-XT | 120 |
| TRX-XT | 82 | | EFM-CP | 116 |
| TRX-XC | 75 | | EFM-RS | 106 |
| TRX-CL | 82 | | EFM-CB | 122 |
| TRX-RS | 91 | | EFM-HH | 108 |
| TRX-CP | exact | | EFM-CY | 122 |
| TRX-CB | exact | | GND-SN | 76 |
| TRX-CH, OH | 74 | | GND-NS | 46 (DEC 0: gone in a block; 2^-20 RMS) |
| TRX-CY | exact | | GND-IM | exact |
| TRX-MA | exact | | | |
| TRX-S2 | exact | | | |

What it took:

- **DSP2's own sine, word for word.** DSP2 makes its 32768-word sine at boot with a
  48-bit recursion whose limiter clamps at the trough; from there the table runs 1.5
  indices ahead, and one word (k = 16384) has the wrong sign. The FM machines feed their
  output back into their phase, so one LSB becomes another waveform within a few hundred
  samples. `core.md_sine_words` is that recursion in Python (equal to the emulator's
  table); the DSP fills its table with a float polynomial rounded to the word plus a
  packed correction (`sinecorr`, 5 bits a word, 22 KB), 1,024 words a block for the
  first 32 blocks after power-on. The runner checks the DSP's table against it.
- **The 56300's truncation where it feeds back**: envelopes multiplied once a block or
  once a sample (`mpy_floor`, `env_mul`), filter coefficients and recursions on
  integer words with 12-bit partial products a float holds exactly; the EFM pairs
  entirely in integer arithmetic.
- **The firmware's quirks kept**: TRX-S2's bump decays that only the first note after the
  machine is chosen gets; the XT/XC/CL oscillator's sample in its increment's fraction;
  TRX-MA's two stale words past its bead buffer (held at 0, as the golden runs start).

Cost: the exact machines are heavy (12,000 to 25,000 DSP instructions a 44.1 kHz block
for TRX-CP..S2 and the EFMs, about 1,000 for GND-SN). A machine rests when its sound has
died away (32 blocks under 2^-21) until its next note, so only sounding voices cost.

## The PERC page

TYPE (page 2) picks one of the 25 machines, in PERC's order until v0.16 with TRX-S2 added:
TRX (BD B2 SD XT CP RS CB CH OH CY MA CL XC S2), EFM (BD SD XT CP RS CB HH CY), GND (SN NS
IM); the note latches it, so
a p-locked TYPE changes the machine step by step, as before. Page 1 is the machine's
eight parameters under the Machinedrum's names; each knob is the nearest of the
Machinedrum's 128 positions. Page 2 keeps the track effects (AMD .. FLTQ). The note does
not tune a machine (as on the Machinedrum: PTCH does).

## Room

The DSP's program must fit its 1 MB upload buffer. v0.17 needed about 100 KB more
(the machines' code, 80 KB in L2, and the firmware's tables), so: the four test
sounds are no longer in the image (the +Drive holds the owner's samples since v0.16; the
runner puts them in itself), the sample machines' L2 span is 16 KB (their code is), PERC's
span is the code's size, EXP2's table covers -16..16 (what PERC's effects and the sample
machines use), TRX-OH shares TRX-CH's code, and the firmware's Q23 tables ship packed
24 bits a word (`tpack`, 47 KB instead of 63 KB): the DSP unpacks them into their floats
1,024 words a block for the first 16 blocks after power-on (`core.unpack_fill`; the
runner checks every word against the build's).

## Arithmetic shifts

selas encodes the immediate `Rd = ASHIFT Rx BY -n` with a shifter-op field the firmware's
own immediate ASHIFTs do not carry (digikit: "unsupported ShiftImm opcode 0x20";
`reader.asm` met it first). So `dsl.ash` puts the count in a register (`ASHIFT Rx BY Rt`,
the form the firmware and our other code use), saving and restoring Rt in a scratch word
(`ash`): every register is as before, at three more instructions a shift. v0.18: the
count goes in R12, the DSL's scratch, wherever the shift's own registers leave it free (run
mode sets R12 too, so a machine that kept something in R12 across a shift would fail its
golden cases: none does); TRX-CY's block went from 30.5k instructions to 28k.

## Rate

DSP2 runs at 44.1 kHz in 32-sample blocks (`md-research.md`: the OS's `muluw #44100`,
the DSP clock from an 11.2896 MHz crystal). The DN2 runs at 48 kHz. Each voice runs its
machine at 44.1 kHz, block by block, and the DN2's block reads that stream through a
4-point interpolator at 0.91875 Machinedrum samples a sample; the machine itself is
unchanged.
