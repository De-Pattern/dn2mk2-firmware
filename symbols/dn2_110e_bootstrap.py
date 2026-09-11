"""Curated names in the Digitone II 1.10E bootstrap (section 2).

The recovery receiver, read with a Gate-F-cleared disassembler at its run base
0x800003fc -- see `docs/bootstrap.md` for the full account and the evidence.
Addresses are 1.10E, build 40050; they do not carry to 1.11, which moved the
bootstrap (`docs/os-versions.md`).
"""

from dnfw.symbolmap.record import BOOTSTRAP_BASE, Symbol

_COMMON = dict(build="40050", version="1.10E", section=2, base=BOOTSTRAP_BASE, kind="function")

SYMBOLS = [
    Symbol(
        id="dn2-110e-bs-recv-loop",
        name="recovery_receive_loop",
        address=0x80003E5A,
        guard="9cfb6077a227d94a125a033b56997cea7ce04cd8b19a4d0075bdaaea7d657932",
        note="Top-level recovery UI: shows READY TO RECEIVE, then RECEIVING... with "
        "a bar = received_packets*128/total_packets, then calls the flasher. "
        "docs/bootstrap.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-bs-recv-handler",
        name="sysex_packet_handler",
        address=0x800036F6,
        guard="ed6c5a2124869ff7e202bb2cbf2823f3a05cdd607391f5402e22873a01c2d233",
        note="One call per SysEx message. Checks packet sequence against a running "
        "counter and the per-packet checksum; a mismatch on either sets the receive "
        "state to 0 and freezes reception -- no retransmit. The reason a bad DIN link "
        "stalls silently. docs/bootstrap.md.",
        **_COMMON,
    ),
    Symbol(
        id="dn2-110e-bs-flash-container",
        name="verify_and_flash_container",
        address=0x80003C9C,
        guard="dffc643f16c6daf596ea4e4479e44055d10498c24910d6f6612fbe5145678e2c",
        note="Post-receive: checksums the whole container in RAM at 0x40000000 (our "
        "[size][checksum][container] preamble), erases flash in 256 KB blocks, and "
        "copies the container to flash 0x80000 in 512-byte chunks -- verbatim, no "
        "decompression. Then resets. docs/bootstrap.md.",
        **_COMMON,
    ),
]
