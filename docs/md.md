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

| machine | worst case (dB) |
|---|---|
| GND-SN | 76 |
| GND-NS | 46 (DEC 0: the noise is gone in a block; error 2^-20 RMS) |
| GND-IM | exact |

## Rate

DSP2 runs at 44.1 kHz in 32-sample blocks (`md-research.md`: the OS's `muluw #44100`,
the DSP clock from an 11.2896 MHz crystal). The DN2 runs at 48 kHz. Each voice runs its
machine at 44.1 kHz, block by block, and the DN2's block reads that stream through a
4-point interpolator at 0.91875 Machinedrum samples a sample; the machine itself is
unchanged.
