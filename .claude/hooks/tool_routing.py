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
| SHARC / DSP side | selache in WSL: `/root/selmap-target/release/selmap`, `/root/selache-target/release/{selas,seld,seldump,selsyms}`; regions in `out/sharc/*.bin`; `scripts/sharc_*.py`; `docs/sharc-*.md` |
| project / preset / pattern data on a device | ask the DNX session -- never hand-roll SysEx capture here |
| live hardware state | `scripts/service_console.py` (maintenance mode, read-only allow list); `docs/service-commands.md` |
| has someone already read this? | `digikit-up/docs/FINDINGS.md`, `docs/for-digikit-*.md`, `docs/STATUS.md`, the lalzart notes (cite in our own words), Synthdawg (consult, never quote) |

The same table with its reasoning: `docs/instruments.md`.

Two ways this project has been fooled by a static read, both on 2026-09-20:
`movea.l` does not prove a pointer -- it is also how GCC parks a value it wants
to index with `lea`; and an unsigned range test does not prove memory -- a
window check on a wrapping counter has the same shape.
</tool-routing>"""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0                      # never block a prompt over a parse error
    prompt = payload.get("prompt") or ""
    if CHATTER.match(prompt) or not TRIGGERS.search(prompt):
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": ROUTING}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
