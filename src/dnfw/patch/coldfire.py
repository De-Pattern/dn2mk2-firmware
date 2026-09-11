"""A tiny ColdFire V4e instruction encoder.

Ported from `tools/ot3_asm.py` in bkkbrls-del/midisc (MIT, Sam Banks), which
patches the same ColdFire core the Digitones run. Every encoding there is
checked against an instruction that already exists in a stock Elektron image,
and `link()` resolves `.w` branch displacements so they are never typed by
hand -- the class of bug that shipped a wrong shift and a `jsr` where a `jmp`
was meant in earlier hand-written patches.

What transfers is purely the ColdFire ISA. Nothing about the Octatrack's
memory map, engine or safe-cave addresses is carried here; that is
`patch/cave.py`'s and `docs/memory-map.md`'s business, keyed to the DN2.

Divergences from the source, so the next reader does not assume a verbatim copy:

- `nop()` is added (`0x4e71`) -- the cave applier pads a hook site out to an
  instruction boundary with it.
- Encodings are unchanged. Where a method's docstring cites a "stock" pattern,
  that is the Octatrack instruction midisc verified against; the encoding is a
  property of the ISA, so it holds on the DN2 image identically, and
  `test/test_coldfire.py` re-checks each against `m68k-linux-gnu-as`.

This encoder is the no-toolchain path and the way to build one-line hook
branches. For anything larger than a few instructions, `patch/assemble.py`
runs the real assembler instead; see `docs/references.md` (ems-octakit).
"""

from __future__ import annotations

D_PUSH = {n: f"2f{n:02x}" for n in range(8)}
A_PUSH = {0: "2f08", 1: "2f09"}
D_POP = {0: "201f", 1: "221f", 2: "241f", 3: "261f", 4: "281f", 5: "2a1f", 6: "2c1f", 7: "2e1f"}
A_POP = {0: "205f", 1: "225f"}


def jmp_abs(target: int) -> bytes:
    """jmp (target).l -- 6 bytes, the detour a cave hook writes at its site."""
    return b"\x4e\xf9" + target.to_bytes(4, "big")


def jsr_abs(target: int) -> bytes:
    """jsr (target).l -- 6 bytes, a call-out that returns with rts."""
    return b"\x4e\xb9" + target.to_bytes(4, "big")


class Asm:
    """Emit ColdFire bytes, with symbolic `.w` branches resolved by link()."""

    def __init__(self) -> None:
        self.b = bytearray()
        self._fix: list[tuple[int, str]] = []
        self._lab: dict[str, int] = {}

    # --- raw ---
    def hex(self, h: str) -> "Asm":
        self.b += bytes.fromhex(h.replace(" ", ""))
        return self

    def bytes(self, data: bytes) -> "Asm":
        self.b += data
        return self

    def label(self, name: str) -> "Asm":
        if name in self._lab:
            raise ValueError(f"duplicate label {name}")
        self._lab[name] = len(self.b)
        return self

    def link(self) -> bytes:
        for at, name in self._fix:
            if name not in self._lab:
                raise ValueError(f"unresolved label {name}")
            rel = self._lab[name] - (at + 2)
            if not -0x8000 <= rel <= 0x7FFF:
                raise ValueError(f"branch to {name} out of range ({rel})")
            self.b[at + 2] = (rel >> 8) & 0xFF
            self.b[at + 3] = rel & 0xFF
        return bytes(self.b)

    # --- branches (word form; displacement filled by link) ---
    def _br(self, op: str, name: str) -> "Asm":
        self._fix.append((len(self.b), name))
        return self.hex(op + "00" + "0000")

    def bra(self, name: str) -> "Asm":
        return self._br("60", name)

    def beq(self, name: str) -> "Asm":
        return self._br("67", name)

    def bne(self, name: str) -> "Asm":
        return self._br("66", name)

    def bcc(self, name: str) -> "Asm":
        return self._br("64", name)

    def bcs(self, name: str) -> "Asm":
        return self._br("65", name)

    def bhi(self, name: str) -> "Asm":
        """bhi.w -- unsigned greater than (HI)."""
        return self._br("62", name)

    def bpl(self, name: str) -> "Asm":
        return self._br("6a", name)

    def bmi(self, name: str) -> "Asm":
        return self._br("6b", name)

    # --- control ---
    def jsr(self, target: int) -> "Asm":
        return self.hex(f"4eb9{target:08x}")

    def jmp(self, target: int) -> "Asm":
        return self.hex(f"4ef9{target:08x}")

    def rts(self) -> "Asm":
        return self.hex("4e75")

    def nop(self) -> "Asm":
        return self.hex("4e71")

    # --- stack ---
    def push(self, *regs: str) -> "Asm":
        for r in regs:
            self.hex(D_PUSH[int(r[1])] if r[0] == "d" else A_PUSH[int(r[1])])
        return self

    def pop(self, *regs: str) -> "Asm":
        for r in regs:
            self.hex(D_POP[int(r[1])] if r[0] == "d" else A_POP[int(r[1])])
        return self

    # --- data moves (each encoding verified against a stock instruction) ---
    def move_l_sp(self, disp: int, dn: int) -> "Asm":
        """move.l disp(a7), dn   (stock: 202f0024)"""
        return self.hex(f"{0x202F + (dn << 9):04x}{disp:04x}")

    def move_l_dd(self, src: int, dst: int) -> "Asm":
        """move.l ds, dd   (stock: 2005 = move.l d5,d0)"""
        return self.hex(f"{0x2000 + (dst << 9) + src:04x}")

    def move_l_abs_d(self, addr: int, dn: int) -> "Asm":
        """move.l (addr).l, dn   (stock: 2239 = move.l abs,d1)"""
        return self.hex(f"{0x2039 + (dn << 9):04x}{addr:08x}")

    def move_l_imm(self, imm: int, dn: int) -> "Asm":
        """move.l #imm, dn   (stock: 203c000018b2)"""
        return self.hex(f"{0x203C + (dn << 9):04x}{imm:08x}")

    def mvz_b_abs(self, addr: int, dn: int) -> "Asm":
        """mvz.b (addr).l, dn   (stock: 71b9/77b9/7bb9)"""
        return self.hex(f"{0x71B9 + (dn << 9):04x}{addr:08x}")

    def mvz_b_ind(self, an: int, dn: int) -> "Asm":
        """mvz.b (an), dn   (stock: 7190 = mvz.b (a0),d0)"""
        return self.hex(f"{0x7190 + (dn << 9) + an:04x}")

    def mvz_b_disp(self, disp: int, an: int, dn: int) -> "Asm":
        """mvz.b disp(an), dn   (mode 5; stock mvs form: 71284900)"""
        return self.hex(f"{0x71A8 + (dn << 9) + an:04x}{disp:04x}")

    def move_b_d_ind(self, dn: int, an: int) -> "Asm":
        """move.b dn, (an)   (stock: 1085 = move.b d5,(a0))"""
        return self.hex(f"{0x1080 + (an << 9) + dn:04x}")

    def move_b_abs_d(self, addr: int, dn: int) -> "Asm":
        """move.b (addr).l, dn   (stock: 1039100b145e)"""
        return self.hex(f"{0x1039 + (dn << 9):04x}{addr:08x}")

    def move_b_d_abs(self, dn: int, addr: int) -> "Asm":
        """move.b dn, (addr).l   (stock: 13c0100b145e)"""
        return self.hex(f"{0x13C0 + dn:04x}{addr:08x}")

    def move_l_d_abs(self, dn: int, addr: int) -> "Asm":
        """move.l dn, (addr).l   (stock: 23c0460d169c)"""
        return self.hex(f"{0x23C0 + dn:04x}{addr:08x}")

    def move_b_ind_d(self, an: int, dn: int) -> "Asm":
        """move.b (an), dn   (stock: 1010 = move.b (a0),d0)"""
        return self.hex(f"{0x1010 + (dn << 9) + an:04x}")

    # --- address regs ---
    def movea_abs(self, addr: int, an: int) -> "Asm":
        """movea.l (addr).l, an   (stock: 207946c82456)"""
        return self.hex(f"{0x2079 + (an << 9):04x}{addr:08x}")

    def movea_imm(self, imm: int, an: int) -> "Asm":
        """movea.l #imm, an   (stock: 207c00095048)"""
        return self.hex(f"{0x207C + (an << 9):04x}{imm:08x}")

    def movea_d(self, dn: int, an: int) -> "Asm":
        """movea.l dn, an   (stock: 2040/2041)"""
        return self.hex(f"{0x2040 + (an << 9) + dn:04x}")

    def move_a_d(self, an: int, dn: int) -> "Asm":
        """move.l an, dn   (stock: 2608 = move.l a0,d3)"""
        return self.hex(f"{0x2008 + (dn << 9) + an:04x}")

    def adda_d(self, dn: int, an: int) -> "Asm":
        """adda.l dn, an   (stock: d1c7 = adda.l d7,a0)"""
        return self.hex(f"{0xD1C0 + (an << 9) + dn:04x}")

    def adda_imm(self, imm: int, an: int) -> "Asm":
        """adda.l #imm, an   (stock: d1fc0008f3e2)"""
        return self.hex(f"{0xD1FC + (an << 9):04x}{imm:08x}")

    # --- arithmetic ---
    def add_dd(self, src: int, dst: int) -> "Asm":
        """add.l ds, dd   (stock: d081 = add.l d1,d0)"""
        return self.hex(f"{0xD080 + (dst << 9) + src:04x}")

    def sub_dd(self, src: int, dst: int) -> "Asm":
        """sub.l ds, dd   (stock: 9280 = sub.l d0,d1)"""
        return self.hex(f"{0x9080 + (dst << 9) + src:04x}")

    def addi(self, imm: int, dn: int) -> "Asm":
        """addi.l #imm, dn   (stock: 068700000024)"""
        return self.hex(f"{0x0680 + dn:04x}{imm:08x}")

    def andi(self, imm: int, dn: int) -> "Asm":
        """andi.l #imm, dn   (stock: 0282... family)"""
        return self.hex(f"{0x0280 + dn:04x}{imm:08x}")

    def cmpi(self, imm: int, dn: int) -> "Asm":
        """cmpi.l #imm, dn   (stock: 0c8000000008)"""
        return self.hex(f"{0x0C80 + dn:04x}{imm:08x}")

    def addq(self, imm: int, dn: int) -> "Asm":
        """addq.l #imm, dn   (stock: 5284 = addq.l #1,d4)"""
        return self.hex(f"{0x5080 + ((imm & 7) << 9) + dn:04x}")

    def tst_abs(self, addr: int) -> "Asm":
        return self.hex(f"4ab9{addr:08x}")

    def tst_d(self, dn: int) -> "Asm":
        return self.hex(f"{0x4A80 + dn:04x}")

    def lsl(self, count: int, dn: int) -> "Asm":
        """lsl.l #count, dn   (stock: eb88 = lsl.l #5,d0, ed8d = lsl.l #6,d5)"""
        c = 0 if count == 8 else count
        return self.hex(f"{0xE188 + (c << 9) + dn:04x}")

    def asr(self, count: int, dn: int) -> "Asm":
        """asr.l #count, dn   (stock: e080 = asr.l #8,d0, e280 = asr.l #1,d0)"""
        c = 0 if count == 8 else count
        return self.hex(f"{0xE080 + (c << 9) + dn:04x}")

    def muls(self, src: int, dst: int) -> "Asm":
        """muls.l ds, dd   (stock: 4c051800 = muls.l d5,d1)"""
        return self.hex(f"{0x4C00 + src:04x}{0x0800 + (dst << 12):04x}")

    def lsl_reg(self, cnt: int, dn: int) -> "Asm":
        """lsl.l dcnt, dn   (stock: e7a8 = lsl.l d3,d0)"""
        return self.hex(f"{0xE1A8 + (cnt << 9) + dn:04x}")

    def or_dd(self, src: int, dst: int) -> "Asm":
        """or.l ds, dd   (stock: 8081 = or.l d1,d0)"""
        return self.hex(f"{0x8080 + (dst << 9) + src:04x}")

    def moveq(self, imm: int, dn: int) -> "Asm":
        """moveq #imm, dn   (stock: 7001 = moveq #1,d0)"""
        return self.hex(f"{0x7000 + (dn << 9) + (imm & 0xFF):04x}")
