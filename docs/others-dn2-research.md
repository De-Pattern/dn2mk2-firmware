# Other people's DN2 research, checked against ours (2026-10-29)

## complex-ping's digitone-2-modding-skill (MIT; github.com/complex-ping/digitone-2-modding-skill)

An agent skill and tools for DN2 OS 1.11 mods (the same OS as ours), from the author of the
Overtone firmware (OS 1.12). Read: `references/sharc.md`, `references/firmware.md`,
`scripts/hwrules.py`.

**Checked here:**

- **Hardware rules the emulators cannot see** (`hwrules.py`: hardware-loop ISA shape,
  loop ends, CALL near a loop end, branch spacing and the 12-instruction window, same-DAG
  loads and stores). Run on our v0.31 section 7 over our code (PERC 30,773 instructions,
  the sample machines 4,579, PING 863, the stubs): **no violations**. Our generated code
  uses no hardware loops at all (software loops), which avoids the loop rules entirely.
- **"Not above L2 0x200B0000; stock data words point to 0x200C0008 / 0x200C1F84"**: our
  PERC code loads at 0x200C0000. Searched the stock image: those two values occur only
  inside instruction encodings (`0128 0008 200c` is a compute) and a table of 16-bit words,
  not as pointers. PERC has run from there on units since v0.11. Not a concern, noted.
- **Our voices do not pay for a stock render**: stock renders every voice whose engine word
  (record +0x1b4) is FM TONE, WAVETONE or FM DRUM, sounding or not; our types map to 5
  (lookup16), which none of the render loops matches.
- **Power-on DDR holds garbage (NaN)**: every DDR range our code reads is loaded by the
  boot stream (zeros or tables; `ddr_spans`), the sample pool beyond its directory only
  after the link has filled it. v0.30.1's AMD bug was exactly this class (a table no
  longer loaded).

**New to us, and what it means for the DSP-time work:**

- **On the unit, cost is memory, not instructions**: L2 and DDR accesses cost several times
  their instruction count (the skill: +7 % instructions gave +21 % load once; a per-voice
  DDR path about 10x its count). Our Machinedrum voices keep their state in DDR
  (0x82100000) and read their tables there; the Monomachine voices' state and scratch are
  in DDR (0x81200000). The guard measures real cycles, so it stays right, but our cost
  figures (MNM_COST, MNM_BUDGET) are emulator instruction counts and understate the unit.
  **Moving the hot state into L1/L2 is likely the biggest single saving**, before any
  instruction-level tuning.
- The unit's budget: about 666k cycles a block, stock idle 63-65 % on the unit.
- A frame that lands after its block's render started is never rendered: its note-on masks
  are lost (a hook on the receive callback can merge them into the next block). A possible
  cause of a rare missed note.
- Hook sites they proved on units (main mix, FX-bus mixer, the voice chain pre-filter), and
  that the FX-bus mixer takes R4 and R8 as arguments.

## complex-ping's Overtone (OS 1.12)

Also ports the Machinedrum (TRX, EFM, P-I) and says the same about the DSP: these voices
cost more than stock, P-I is heavy, at 100 % the audio crackles and the answer is fewer
voices; it shows a DSP LOAD meter under SETTINGS. Its other features are on our roadmap
for later (`docs/ROADMAP.md`).
