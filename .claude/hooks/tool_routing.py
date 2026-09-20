"""Before inferring, name the tool that could settle it.

A `UserPromptSubmit` hook. When a prompt asks the assistant to find out, work
out or confirm something, this injects the project's topic-to-tool routing
table, so the reflex is "which instrument answers this?" rather than "what does
the disassembly look like it says?".

It exists because of a real failure on 2026-09-20: one 32-bit field was read
three times from the instruction stream and labelled three different ways --
pointer, memory region, timestamp -- while the emulator that could have watched
it move and the SHARC toolchain that could have checked the other side of the
link both sat unused. Two of the three labels were wrong.

The same table, with the reasoning, is `docs/instruments.md`.

No dependencies beyond Python: the machine has no `jq`.
"""

import json
import re
import sys

# Between two injected blocks, when a prompt is both an investigation and a
# build. A named constant because writing it inline is how this line got
# broken once already.
SEPARATOR = chr(10) * 2

# Verbs and shapes that mean "go and find out", not "do this thing I described".
# `is it` / `does it` were here and matched "How is it going?"; a bare pronoun
# question is not an investigation, and a false positive costs context on every
# turn it fires.
TRIGGERS = re.compile(
    r"\b("
    r"what (is|are|does|do|was|were|happens)|why (is|are|does|do|did)|how (does|do|is|are|did)"
    r"|which\b|where (is|are|does|do)|when (does|do|is)"
    r"|find( out)?|locate|identif(y|ies)|determine|figure out|work out|track down"
    r"|infer|deduce|guess|assume|suspect|unknown|unclear|not sure|unsure"
    r"|confirm|verify|corroborate|settle|prove|disprove|check (if|whether|what|that)"
    r"|investigate|analys[ei]|analyz[ei]|understand|explain|read the|look (at|into)"
    r"|disassemb|trace|map out|reverse"
    r"|can we tell|any idea|hypothes"
    r")\b", re.IGNORECASE)

# Conversational forms the triggers above catch by accident: "How is it
# going?" matched `how is`. A pleasantry is not an investigation, and a false
# positive costs context on the turn it fires. Anchored to the whole prompt, so
# a real question that merely opens this way still fires.
CHATTER = re.compile(r"^\W*(how('s| is| are| did)?( it| things| we| that)?"
                     r"( going| go| doing)?|what('s| is) next|any news|all good"
                     r"|status)[\s?!.]*$", re.IGNORECASE)

ROUTING = """<tool-routing>
This prompt asks for something to be found out. Before any extended inference,
say which instrument would settle it, and use it. If none can, say so and mark
the conclusion unverified.

| topic | reach for |
|---|---|
| ColdFire firmware, static | `dnfw disasm / fn callers / fn entry / symbols / symbolmap / params / cave`, `scripts/sram_field_map.py` (field widths + read/write per address), `scripts/find_constant.py`, `scripts/call_map.py`, `ghidra/` |
| what the firmware actually DOES at run time | digikit's emulator: `scripts/emu_*.py`, `scripts/lfo4_harness.py` (snapshot + direct call), `UC_HOOK_MEM_WRITE` to watch a field move, cold-boot parity against a stock control. `docs/emulator.md` |
| **driving the panel** | **hold the encoder push and turn** -- a plain turn does nothing in a menu. Push codes 41..48 (A..H) = channel 5, bits 0..7; `code_for` is `channel * 8 + bit + 1`. `--panel-dwell 2` makes a tap a tap (the default pacing turns every tap into a hold). What does NOT run: the sequencer and the pattern load -- call those routines directly. Always run a control beside a positive result |
| SHARC / DSP side | selache in WSL: `/root/selmap-target/release/selmap`, `/root/selache-target/release/{selas,seld,seldump,selsyms}`; regions in `out/sharc/*.bin`; `scripts/sharc_*.py`; `docs/sharc-*.md` |
| project / preset / pattern data on a device | ask the DNX session -- never hand-roll SysEx capture here |
| live hardware state | `scripts/service_console.py` (maintenance mode, read-only allow list); `docs/service-commands.md` |
| **a build that will be flashed** | `scripts/emu_boot_check.py <build>/section_3_MAIN_OS.bin` -- boots it **from reset** against a cached stock control. A snapshot harness is not a boot test: `ui1200M` has already booted, so it never runs the loader, the init, or the first call into new code |
| has someone already read this? | `digikit-up/docs/FINDINGS.md`, `docs/for-digikit-*.md`, `docs/STATUS.md`, the lalzart notes (cite in our own words), Synthdawg (consult, never quote) |

The same table with its reasoning: `docs/instruments.md`.

A null from the emulator is only evidence once the input is known to arrive:
`scripts/drive.py` exists to tell "input never reached the firmware" from
"navigation works but deltas do not" from "the path works".

Two ways this project has been fooled by a static read, both on 2026-09-20:
`movea.l` does not prove a pointer -- it is also how GCC parks a value it wants
to index with `lea`; and an unsigned range test does not prove memory -- a
window check on a wrapping counter has the same shape.
</tool-routing>"""


# Building and flashing is not an investigation, so the table above never fires
# for it -- and that is exactly the prompt where the boot gate matters. Added
# 2026-09-20, after `lfo4-bridge` passed every snapshot harness it had and then
# drew the instrument's EXCEPTION screen at boot.
SHIPPING_TRIGGERS = re.compile(
    r"\b(build|rebuild|compile|flash|burn|ship|upgrade|\.syx|syx|image|"
    r"firmware|install|deploy|test it on|on the (device|instrument|hardware)|"
    r"hardware test)\b", re.IGNORECASE)

SHIPPING = """<shipping-gate>
This prompt is about a build. Before any `.syx` is offered for flashing:

1. **Boot it from reset in the emulator.**
   `scripts/emu_boot_check.py out/<build>/section_3_MAIN_OS.bin`
   Three outcomes, and they are not the same: **fault** (the firmware's own
   reporter at `0x4011ea6a` ran -- it formats `V%02x M%x P%08x`, so vector,
   mode and faulting PC come from the machine, not from a photo of the screen),
   **no UI** (never faulted, never composed a frame -- a hang, which looks like
   a pass to anything watching only for a crash), and **booted**.
   A snapshot harness does NOT count: `ui1200M` has already booted, so it never
   runs the loader, the init, or the first call into new code from reset. That
   is precisely how `lfo4-bridge` reached the instrument and faulted -- and it
   faulted on a **scale factor of 8**, which GCC emits under `-mcpu=5475`, gas
   assembles, and Unicorn's generic m68k core runs. Only the ColdFire refuses.
   The build now rejects that encoding itself (`scripts/check_coldfire.py`).

   The gate also reports which of the build's routines **never ran**. A boot
   executes the loader, the init and the memcpy/memset stubs and nothing else:
   the audio engine does not run, and no kit loads, so the tick and the
   save/load converters are untouched. `scripts/emu_boot_engine.py` covers all
   three in one boot -- reset, then evaluator A, then a stored sound through
   LOAD and SAVE. A build touching those paths is not cleared by a boot alone.

2. **Make any demonstration unmissable.** A hard-coded proof -- a modulation, a
   sweep, a blink -- must be obvious within a bar. `lfo4-tick7` used the slowest
   multiplier there is and took ~14 bars to hear: *"I almost wrote that it
   didn't work."* A demo indistinguishable from a failure cannot tell the two
   apart, and the tester pays for it in flashes.

3. **Put it where builds live**: `00_Resources/02_Builds/name_DN2_version.syx`.

4. **Say what a pass looks like** before it is flashed, in the same terms the
   owner will use: which track, which knob, what should be heard or seen, and
   what a failure would look like instead. `00_Notes/.../Firmware test plan.md`
   is where that goes.

Flashing costs a ten-minute MIDI transfer and a recovery if it fails. The gate
costs wall-clock on a machine that is otherwise idle.
</shipping-gate>"""

def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0                      # never block a prompt over a parse error
    prompt = payload.get("prompt") or ""
    if CHATTER.match(prompt):
        return 0
    blocks = []
    if TRIGGERS.search(prompt):
        blocks.append(ROUTING)
    if SHIPPING_TRIGGERS.search(prompt):
        blocks.append(SHIPPING)
    if not blocks:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": SEPARATOR.join(blocks)}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
