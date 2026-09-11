"""Curated names in the Digitone II 1.10E MAIN OS (section 3).

Anchors established elsewhere in the docs, named here so a Ghidra project opens
with them in place. MAIN OS also carries 454 RTTI type names, which `symbolmap`
adds automatically -- these are the few things RTTI does not give you: a data
table and the service-protocol code. Addresses are 1.10E, build 40050.
"""

from dnfw.symbolmap.record import MAIN_OS_BASE, Symbol

_COMMON = dict(build="40050", version="1.10E", section=3, base=MAIN_OS_BASE)

SYMBOLS = [
    Symbol(
        id="dn2-110e-param-table",
        name="parameter_table",
        kind="data",
        address=0x401E29D4,
        guard="0eb3f8520a4075fc95adf59c159f77326638d2310c5fdc74011a14b3e3fb6a2c",
        note="320 records of 60 bytes, the whole instrument's parameters: handler, "
        "group, id, range, default, CC, NRPN, then long/page/short name pointers. "
        "The Phase 2 target for a fourth LFO. docs/lfo-parameters.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-service-dispatcher",
        name="service_command_dispatcher",
        kind="function",
        address=0x400CF906,
        guard="1f56f0afbb351f19090bc2f0b3271b36d6e177df9be1d98e265d4aba4a98a3ad",
        note="Reads a line from the service queue and walks a strcmp chain of "
        "#-commands (#READ_SERIAL, #WRITE_SERIAL, ...). docs/service-commands.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-line-assembler",
        name="service_line_assembler",
        kind="function",
        address=0x40110FF8,
        guard="09aff0f8699eee5e19619e63503128a07c3815df4a4e4b9a6486e074763b736e",
        note="Assembles a service command line byte by byte ('#'/'!'/backtick "
        "prefixes, skips \\r, terminates on \\n) and posts it to the RTOS queue the "
        "dispatcher reads. docs/service-commands.md.",
        **_COMMON,
    ),
]
