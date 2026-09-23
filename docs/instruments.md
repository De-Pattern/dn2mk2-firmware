# Which instrument answers which question

**Written 2026-09-20, after a failure worth naming.** One 32-bit field
(`0x80005398`) was read three times from the instruction stream in a single
afternoon and labelled three different ways — a pointer, the base of a
900,000-byte region, a timestamp — while the emulator that could have watched it
move and the SHARC toolchain that could have checked the other end of the link
both sat unused. Two of the three labels were wrong.

The owner's question was the right one: *"why are we guessing when we have
tools?"*

## The table

| the question is about | reach for |
|---|---|
| **ColdFire firmware, statically** | `dnfw disasm`, `dnfw fn callers` / `fn entry`, `dnfw symbols` / `symbolmap`, `dnfw params`, `dnfw cave`; `scripts/sram_field_map.py` (per-address width and read/write); `scripts/find_constant.py`; `scripts/call_map.py`; `ghidra/` |
| **what the firmware actually does at run time** | digikit's emulator — `scripts/emu_*.py`, `scripts/lfo4_harness.py` for snapshot + direct call, `UC_HOOK_MEM_WRITE` to watch a field move, and a cold boot beside a **stock control**. `docs/emulator.md` |
| **driving the panel in the emulator** | **hold the encoder push and turn** — a plain turn does nothing in a menu. Push codes 41–48 (A–H) are channel 5, bits 0–7 (`code_for` is `channel * 8 + bit + 1`); `--panel-dwell 2` makes a tap a tap, since the default pacing turns every tap into a hold. The sequencer and the pattern load do **not** run — call those routines directly, as `scripts/emu_arp_plocks.py` does. **The pages are `MOD (n/3)` and they wrap**, and the screen says which one is open — read it rather than inferring the page from the slot a turn wrote. **A key that only works the first time means its release never registered:** the wire carries a whole-channel state mask and the firmware XORs it, so a repeat of the same byte is correctly no edge at all. And prove any dwell actually changes something before believing a sweep over it |
| **the SHARC / DSP side** | selache in WSL: `/root/selmap-target/release/selmap` for a linear walk, `/root/selache-target/release/{selas,seld,seldump,selsyms}`; the regions in `out/sharc/*.bin`; `scripts/sharc_*.py`; `docs/sharc-*.md` |
| **project, preset or pattern data on a device** | ask the DNX session. Never hand-roll SysEx capture here |
| **live hardware state** | `scripts/service_console.py` — maintenance mode, read-only allow list. `docs/service-commands.md` |
| **has someone already read this?** | `digikit-up/docs/FINDINGS.md` — **or `docs/findings/01..09` once `machine-ideas-menu` merges** (see below); our own `docs/for-digikit-*.md` and `docs/STATUS.md`, the lalzart notes (cite in our own words), the Synthdawg guide (consult, never quote) |

### digikit's findings are being split, and the file we point at will go

`machine-ideas-menu` (42 commits, unmerged as of 2026-09-22) takes 5,904 lines
out of `docs/FINDINGS.md` and splits them. Ours is not the only project
pointing at that one path, so the mapping is worth keeping here rather than
rediscovering:

| file | what moved into it |
|---|---|
| `01-container-and-patching.md` | the ELE3 container, checksums, the recovery path |
| `02-machines-and-parameters.md` | machine types, the parameter descriptor tables |
| `03-ui-and-panel.md` | the panel, the control table, `MACHINE SEL` |
| `04-coldfire-dsp-link.md` | `FUN_400cf9c4`, the 2,748-byte frame, the payload sizes |
| `05-sharc-isa-and-decoding.md` | the SHARC+ language and decode table |
| `06-sharc-engine-and-startup.md` | the DSP engine, its boot and its ring writers |
| `07-emulator.md` | the emulator: harness quirks, `unblock`, timers |
| `08-hardware-and-ghidra.md` | boards, and getting the image into Ghidra |
| `09-runtime-state.md` | state forwarding, the writer chains |

The one most often wanted from here is **`04-coldfire-dsp-link.md`**: it holds
the frame this project measured from the ColdFire side.

## A null needs the input proved first

"Nothing wrote" is only evidence once the input is known to have arrived.
`scripts/drive.py` exists for exactly that: it separates *input never reached
the firmware* from *navigation works but deltas do not* from *the path works end
to end*. The first probe written for the parameter setter reported zero writes
after an encoder turn — and the turn had not been held, so the null said nothing
at all.

## The rule

**Before extended inference, name the instrument that would settle it.** If one
exists, use it. If none does, say so and mark the conclusion unverified rather
than letting a plausible reading harden into a label.

A static read is evidence about *encoding*. It is rarely evidence about
*meaning*, and this project has been fooled this way more than once:

- **`movea.l` does not prove a pointer.** It is also how GCC parks a 32-bit
  value it wants to index with `lea`.
- **An unsigned range test does not prove memory.** A window check on a wrapping
  counter has exactly the same shape.
- **An offset is meaningless without the frame it is in.** A `+Drive` file is a
  31-byte container header, the image, then a 12-byte trailer; every offset in a
  device write-up is an *image* offset. Applied to the file they land 31 bytes
  early — inside the previous record's trailing `0xFF` fill, which reads as the
  format's "unused" marker no matter what is really there. On 2026-09-23 that
  produced **three** confirmations in a row that all looked right and all were
  wrong, including two that agreed with the conclusion being checked. **Ask for
  the raw image, or convert the frame explicitly and say which one you are in.**

What settled that field in the end was neither: it was the *callee*, a list
insert ordered by `subl` + `bpl` — a **signed** difference, which is how
quantities that wrap are compared and not how addresses are.

## And the first thing it produced was a negative

`scripts/emu_timebase.py` was written to settle the unit of that 900,000 span by
watching the marks move: hook **writes** to the transport's four longwords and
the two block fields, and count three references with known meaning beside them
— the audio ISR, the transport stop, the due-time queue insert.

60 M instructions from reset, stock MAIN OS. The result:

```
  reference points: none fired
  6 write(s) to the watched words
    n=     33,457  block 5394  <- 0  from 0x4000046e   (the .data initialiser)
    n= 10,930,880  cursor +0   <- 0  from 0x400004d2   (the BSS clear)
```

**Not one of the four reference points ran**, and the only writes are the
startup code zeroing the words. The emulator does not reach this path from a
cold boot — which matches `docs/emulator.md`: the sequencer does not play there,
because the audio-frame chain needs the DSP side that is not modelled.

So the instrument answered, and its answer was *"I cannot reach that"*. That
bounds the question rather than leaving it open: the unit of the span will be
settled by digikit's SSI0 pacing work when it matures, or on the instrument —
not by more reading. **A tool that reports it cannot see something is still a
result, and a better one than a third inference.**

## The hook

`.claude/hooks/tool_routing.py`, wired to `UserPromptSubmit` in
`.claude/settings.json`, injects this table when a prompt asks for something to
be found out (what/why/which/find/confirm/verify/infer …) and stays silent
otherwise. It is a prompt, not a gate: it cannot force a tool to be used, only
put the list in front of the assistant before it starts reasoning.

It needs nothing but Python — this machine has no `jq`.
