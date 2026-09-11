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
        address=0x401E29D0,
        guard="d8ca60524bbb0462957c79d82bb4ef76b4a52d23b7dc568abc43084d569613fe",
        note="Flat array indexed by global parameter id 1..320, 60-byte records, "
        "record[id] = 0x401e29d0 + id*60, offset 0 = short-name pointer. LFO1 ids "
        "75-84, LFO2 85-94, LFO3 95-104. The Phase 2 target. "
        "docs/parameter-table-consumer.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-param-page-renderer",
        name="parameter_page_renderer",
        kind="function",
        address=0x40016F38,
        guard="3c25b67666999d5abfa10330768b228796e7c5aa853db7911e65ddf20711c7ef",
        note="Draws a parameter page: a grid loop over 8 cells, each fetching its "
        "parameter id from the page-view vtable and reading parameter_table[id] to "
        "draw name and value. The clearest of the ~50 table accessors; the id<0x141 "
        "bound is the table length. docs/parameter-table-consumer.md.",
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
    Symbol(
        id="dn2-110e-is-lfo-modulatable",
        name="is_lfo_param_modulatable",
        kind="function",
        address=0x400DE34E,
        guard="503cd6f15e010e9764a4c178c5e167583bef4c2d94520d5e65b3b621bc60e8cc",
        note="Modulation subsystem: given a parameter id, reads the table's group "
        "field and returns whether it is an LFO parameter -- hardcoded as "
        "group - 0x1a < 3, i.e. group in {26,27,28} = LFO1/2/3. A 4th LFO (group "
        "29) needs < 4 here. A key Stage-3 site. docs/lfo4-feasibility.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-param-value-getter",
        name="parameter_value_getter",
        kind="function",
        address=0x40064786,
        guard="7851c2a94de3fa11a93d64c12e77c6042659b32e09187b68697821a84ada8db3",
        note="Read path: gets a parameter's current (modulated) value for a page "
        "cell, resolving p-locks/modulation via the resolver. docs/parameter-table-consumer.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-param-value-resolver",
        name="parameter_value_resolver",
        kind="function",
        address=0x400635D0,
        guard="8321a7dad8faf528aef86f31bfe47da6ce4223617cd7fa631254f14d9b1451e6",
        note="Read path (LfoPageView vtable +0x54): reads the already-modulated "
        "value out of the per-track sound engine state (page_view[0x1a] + 0x4f2e0). "
        "The real-time LFO generator writes that state; this only reads it. "
        "docs/lfo4-feasibility.md.",
        **_COMMON,
    ),
]
