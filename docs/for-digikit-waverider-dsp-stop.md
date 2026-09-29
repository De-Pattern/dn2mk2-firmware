# For digikit: our own SHARC code stops the DN2's DSP on silicon, not in the runner (2026-09-29)

This asks for your read on a behaviour we can measure on the instrument but cannot reproduce in digikit's runner. There is no change of ours to land. Everything below is our own code, addresses on DN2 1.11, and measurements; no firmware bytes are quoted.

## Short version

We add a small wavetable reader (about 150 SHARC instructions) to DN2 1.11's DSP image, called in place of WaveTone's render call at sw `0x1c9611`. The ColdFire, UI and loader are untouched apart from our DSP payload.

On the instrument, the DSP stops the first time our reader runs.
- The output DMA then loops its last two pages (a 750 Hz tone), and nothing recovers but a power cycle.
- The ColdFire keeps running normally.

Your runner, at `6f812e9` and again at `2a54bdc`, runs the same image through the whole reader with no fault, and renders the expected output bit for bit.

We have narrowed the stop to a few instructions, and we would like to know whether this pattern means something to you.

## Setup

- **Image:** DN2 1.11 section 7, with three extra blocks in L1 block 2: our code at byte `0x300000` (reader) and `0x300400` (adapter), plus a small save area and parameter block.
- **The call:** the stock `CALL 0x1c6d4a (DB)` at sw `0x1c9611` is retargeted to our adapter.
  - The adapter saves R0-R15 and I0-I5 to absolute addresses and fills a six-word parameter block.
  - It then `CJUMP`s our reader and restores everything before returning in the firmware's own shape: `I12 = DM(M7, I6)`, one instruction, `JUMP (M14, I12) (DB)`, NOP, RFRAME.
- **Placement:** our code is in block 2; other builds put it in blocks 0 and 1. All of them stopped the same way.
- **Gates we run** before anything reaches the instrument:
  - your runner (4 blocks, trig on block 1), strict memory map: no access by our code outside real memory, into the caches, or unaligned;
  - sharcdb decode of our spans: all confident, every branch on an instruction boundary;
  - an encoding audit: every opcode of ours (form + mnemonic, data registers masked) also occurs in stock;
  - selache's `selas` / `selmap` agreeing with your decoder.

## How we see where it stops

At each step, our code stores a marker word `0x5752_00nn` to word 1 of both DSP->ColdFire reply pages (the DSPI2 link; the ColdFire receives the reply at `0x800053a4`, and no ColdFire code reads bytes 4-0x15 of it). It uses two absolute stores (`DM(0x2c49d4)`, `DM(0x2c59d4)`).

When the core stops, nothing overwrites the pages, and the link DMA keeps replaying them. So a read-only USB read of `0x800053a4` shows the heartbeat in word 0 frozen at two alternating values, and word 1 shows the last marker reached.

Confirmed on hardware:
- the heartbeat freezes exactly as the descriptor ring predicts;
- the marker survives the stop;
- the link delivers the DSP word with its 16-bit halves swapped.

## What five hardware runs show

Each run is a separate build. It dies on the **first call** every time: a call counter in word 2 reads 1.

The reader's first instructions (the per-build additions are the markers and the stores listed below):

```
I4 = R4;               // parameter block, byte address 0x301100
R8 = DM(0, I4);        // six loads
R9 = DM(1, I4);
R10 = DM(2, I4);
R11 = DM(3, I4);
R12 = DM(4, I4);
R0 = DM(5, I4);        // output pointer
I2 = R0;
...                    // row arithmetic, DM(6, I4) = R0, ...
```

| build | markers / extra stores | last thing that landed | never landed |
|---|---|---|---|
| stages | after entry (3), after `I2 = R0` (4) | marker 3 | marker 4 |
| stages-loads | + after each load (20-26) | marker 26 (after load 6) | marker 4 |
| stages-i2 | + R0 to word 3; `I2 = R0`; NOP; NOP; I2 to word 4 | the I2 stores | marker 4 |
| stages-i2l1 | as i2, but `I2 = 0x301060` (L1 scratch) instead of `I2 = R0` | the I2 stores | marker 4 |
| stages-r13 | as i2l1, marker 4 via R13 instead of I1 | the I2 stores | marker 4 |

In every run, the instructions after the loads execute (two NOPs and two absolute stores of I2 to block 1 land), and **the next marker's first store never completes**, whichever register holds it (I1 or R13).
- Earlier markers of exactly the same form land every time.
- The stop point moves with our code, so it is tied to the instruction stream rather than to a fixed time after the call.
- The output pointer the dispatch hands us is DDR (`0x804ad010` in the runner; `0x804ad510` and `0x804ad590` on the unit in two runs). Aiming I2 at L1 instead changes nothing.

One earlier build, `rb-loads`, ran the same six loads and `I2 = R0`, then returned immediately through the firmware's return shape. It **survived**, track after track, block after block.

## What we have ruled out

- **Encodings.** Every instruction of ours has a stock twin in the same form (e.g. `I2 = R0` is `703e093f`, following stock's `I2 = R4` / `I4 = R0` pattern), and every width agrees across your decoder, `selmap` and the PRM figures.
- **I1 and I2 as registers an interrupt path relies on.** No function reachable from an interrupt vector reads I1 without setting it. Stock writes I2 in 671 places outside interrupt code, WaveTone's own render among them.
- **A DDR address in a DAG register.** Stock keeps DDR addresses in I5 and loads and stores through them (e.g. around sw `0x1c461e`), and our L1-scratch variant stops the same way.
- **The caches** (SHL1C_CFG read as 16 KB per cache; nothing of ours in the cache regions) and the PRM's "no code in blocks 1/2 with data caches on" (block-0 placement stops the same way).
- **The runner.** Your `2a54bdc` core, with the new `(lw)`, MODIFY and Type 4b fixes, still runs every build to the end with the expected markers (1..19 per block) and bit-exact output.

## The core state at the call, stock and ours

`scripts/sharc_entry_state_diff.py` snapshots every universal register except the data registers, plus the loop stack and the PC-stack depth. It takes the snapshot at the callee's first instruction of the render call at sw `0x1c9611` (stock's `0x1c6d4a`, our adapter) over 4 blocks.

- **The two agree completely** (0 differences in each of 4 calls): we inherit exactly what stock's render inherits.
- **No hardware loop is live** (`loops` empty, `CURLCNTR` = `0xffffffff`); all L registers are 0; the PC stack is 3 deep.
- **But the runner shows MODE1 = 0 and MODE2 = 0 at the call.** Stock's start-up routine at sw `0x1c0e6e` does `MODE1 = set(MODE1, 0x1011800)` (at `0x1c0ecc`) and `MODE2 = set(MODE2, 0x1)` (at `0x1c0eec`). The routine at `0x1c10e3` sets MODE1 bit 23 (at `0x1c10ef`), and stock toggles bit 21 (`0x200000`) 87 times and the secondary-register bits (`0x78`, `0x480`) in interrupt code.
- So either our snapshot's path never runs that start-up, or the runner does not carry MODE1/MODE2 into later execution. **Either way, the modes the silicon is in when our code runs are the one input we cannot see from the runner.**

## What we would value your view on

0. **MODE1/MODE2 at the WaveTone render call on silicon.** Does your cold boot carry `0x1c0e6e`'s MODE1 `0x1011800` and MODE2 bit 0, and does bit 23 (set at `0x1c10ef`) ever stay set into the audio path? If you know which bits are live at `0x1c9611`, we can check whether any of them changes what our loads, register moves or stores do (e.g. a broadcast-load or secondary-register bit).
1. Is there anything in the SHARC+ core, or in how the DN2 firmware configures it, that could stop the core on the first instruction or store after our parameter loads, and only in our code? For instance something about the DAG1 state, MODE1/MODE2 settings, or the loop and PC stacks at the point the WaveTone render is called.
2. Does the firmware enable anything at run time that the runner does not model and that would react to a store sequence like ours? For instance a watchpoint, a memory-protection or bus-error path via the SEC, or an address range guard.
3. Have you seen a SHARC stop look like this in your DT2 work, with the output DMA replaying and the link heartbeat frozen?
4. Would a trace from your `sharc_calltrace` / `sharc_memdiff`, of stock WaveTone's render entry against ours at this call site, be the comparison you would run? If you would do it differently, we would like to follow your method.

We can share the section-7 region blocks of any of these builds (our code only) and the runner harness we use. Thank you for digikit: it is what made this narrowing possible.
