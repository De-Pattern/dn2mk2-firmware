"""Stereo study, stage 3's question (docs/stereo-assessment.md, "The build, in order" 3): what of
each chain stage's state does the chain's body set each block, and what does the stage itself
keep (its history)? A second pass for R then copies the first and keeps its own of the second.

    python scripts/sharc_stereo_state.py [--blocks N] [--window BYTES]

On M4's voice run (type 5, one note), on the traced block: at 0x1c8ef1's entry, at each call out of
its body to a stage, and at that call's return, the words of the stage's state window [R4, R4 + W)
are snapshotted. Per stage: the words the body wrote before the call (set each block), the words
the call wrote (history, or outputs), both, and the window's words it never changed. Reads only.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import sharc_waverider_m4 as m4          # noqa: E402

CHAIN = 0x1C8EF1
BODY = (0x1C8EF1, 0x1C9C5D)
STAGES = {0xB8251B, 0x1CDB56, 0xB80C39, 0xB8265B, 0xB81368, 0xB82342, 0xB80345}
T0 = {0x250020, 0x24FA20, 0x24F320, 0x250160, 0x2533E0, 0x2505A0, 0x2547A0}   # track 0's (the first probe)


LOG = {"ctx": None, "w": {}, "r": {}}      # address -> [contexts in order]


def wrap_memory():
    """every DM read and write the runner makes, tagged with the context of the moment"""
    import sharc_core.memory as mem
    ow, orr = mem._dm_write, mem._dm_read

    def w(state, address, width, value, *a, **k):
        if LOG["ctx"] is not None:
            ad = getattr(address, "value", address)
            if isinstance(ad, int):
                LOG["w"].setdefault(ad & ~3, []).append(LOG["ctx"])
                LOG.setdefault("wpc", {}).setdefault(ad & ~3, []).append(LOG.get("pc"))
        return ow(state, address, width, value, *a, **k)

    def r(state, address, width, *a, **k):
        if LOG["ctx"] is not None:
            ad = getattr(address, "value", address)
            if isinstance(ad, int):
                LOG["r"].setdefault(ad & ~3, []).append(LOG["ctx"])
        return orr(state, address, width, *a, **k)
    for m in list(sys.modules.values()):
        if getattr(m, "_dm_write", None) is ow:
            m._dm_write = w
        if getattr(m, "_dm_read", None) is orr:
            m._dm_read = r


def spans(addrs):
    out, a0, prev = [], None, None
    for a in sorted(addrs):
        if prev is not None and a == prev + 4:
            prev = a
            continue
        if a0 is not None:
            out.append(f"{a0:#x}" + (f"..{prev:#x}" if prev != a0 else ""))
        a0 = prev = a
    if a0 is not None:
        out.append(f"{a0:#x}" + (f"..{prev:#x}" if prev != a0 else ""))
    return out


def render(pc, insn):
    """the digikit dossier's mnemonic for INSN (tools/sharcfn.py), else its fields"""
    try:
        import collections as _c
        import sharcfn
        return sharcfn.render_instruction(pc, insn, None, set(), _c.Counter(), [])[0]
    except Exception as e:                         # noqa: BLE001
        return f"{insn.type_name} {insn.fields} ({type(e).__name__}: {e})"


class StateTracer(m4.ChainTracer):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.entry = {}          # stage state base -> words at the chain's entry (first run only)
        self.res = []
        self.pprev2 = None
        self.cur = None
        self.runs_seen = 0
        self.show, self.shown, self.lines = None, set(), []
        self.site = None
        self.notes, self.r4s = [], {}

    def win(self, st, base):
        return [m4.m2.word(st, base + 4 * k) for k in range(self.window // 4)]

    def pre(self, runner, insn):
        if self.active:
            pc = runner.state.pc_sw
            LOG["pc"] = pc
            st = runner.state
            if pc == 0x1C8FE8 and LOG["ctx"] is not None:
                self.notes.append(f"0x1c8fe8: R9 = DM(I2) with I2 = {m4.m2.word_reg(runner, 'I2'):#x}")
            if pc in STAGES and LOG["ctx"] is not None:
                self.r4s.setdefault(pc, []).append(m4.m2.word_reg(runner, "R4"))
            if self.show and self.show[0] <= pc < self.show[1] and LOG["ctx"] is not None and pc not in self.shown:
                self.shown.add(pc)
                self.lines.append(f"  {pc:#x}  {render(pc, insn)}")
            if pc == CHAIN and self.cur is None and self.runs_seen == 0:
                self.cur = {"bases": {}}
                self.runs_seen = 1
                self.site = self.pprev2
                LOG["ctx"] = "body"
            elif self.site is not None and 1 <= pc - self.site <= 3:
                LOG["ctx"] = None                  # the chain's run returned: the footprint is whole
                self.site = None
                self.cur = None
            if self.cur is not None and LOG["ctx"] is not None:
                inb = BODY[0] <= pc < BODY[1]
                pin = self.pprev2 is not None and BODY[0] <= self.pprev2 < BODY[1]
                if pin and not inb:
                    r4 = m4.m2.word_reg(runner, "R4")
                    if pc in STAGES and r4 in T0 and "open" not in self.cur:
                        self.cur["open"] = (pc, r4, self.win(st, r4))
                        LOG["ctx"] = pc
                    else:
                        LOG["ctx"] = ("call", pc)
                elif inb and not pin:
                    LOG["ctx"] = "body"
                    if "open" in self.cur:
                        tgt, r4, before = self.cur.pop("open")
                        self.res.append((tgt, r4, before, self.win(st, r4)))
                        pass
            self.pprev2 = pc
        return super().pre(runner, insn)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--window", type=lambda x: int(x, 0), default=0x200)
    p.add_argument("--show", help="LO,HI: print each instruction run in [LO, HI) once (the traced chain run)")
    a = p.parse_args()
    dk = m4.m1.Digikit(pathlib.Path(m4.os.environ.get("DNFW_DIGIKIT_SHARC",
                                                      m4.ROOT.parent / "digikit-wt-sharcemu")))
    m4.fx.bind(str(m4.ROOT.parent / "digikit-wt-sharcemu" / "tools"))
    stream = m4.m1.dn2_section7(m4.IMAGE)
    m4.SOUND, _machines = m4.init_sound(m4.IMAGE)
    m4.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=m4.OUT) as tmp:
        work = pathlib.Path(tmp)
        reader, _, _ = m4.m1.reader_code(False, work)
        m5, _, _ = m4.m3.load_json(m4.m3.MACHINE5, m4.m3.MACHINE5_SRC, False, work)
        m5d, _, _ = m4.load_code(m4.MACHINE5D, m4.MACHINE5D_SRC, False, work, m4.MACHINE5D_SW)
        mach = m4.M4Machine(dk, stream, reader, m5, m5d, work)
        init = m4.load_init(dk, mach, stream, reader)
        positions = m4.render.sweep(len(m4.testtable.table()), max(a.blocks, 2))
        prep = m4.voice_prep(375.0, positions)
        tr = StateTracer(a.window)
        if a.show:
            tr.show = tuple(int(x, 0) for x in a.show.split(","))
        wrap_memory()

        def frame(b):
            return m4.make_frame(m4.SOUND, 5, trig=(b == 1))
        on = m4.run_blocks(init, a.blocks, frame, type5=prep, tracer=tr, trace_block=a.blocks - 1)
        print("ok", on["ok"], on.get("halt"))
        print("\n".join(dict.fromkeys(tr.notes)))
        for tgt, r4 in tr.r4s.items():
            d = sorted({b - a for a, b in zip(r4, r4[1:])})
            print(f"stage {tgt:#x}: {len(r4)} calls, R4 from {min(r4):#x}, steps {[hex(x) for x in d][:6]}")
        allw = [ad for ad in LOG["w"] if not 0x2FF000 <= ad < 0x300000]
        print("everything the traced chain run wrote (stack 0x2ff000.. left out):", len(allw), "words")
        for sp in spans(allw):
            print("   ", sp)
        print("\n".join(sorted(tr.lines, key=lambda x: int(x.split()[0], 16))))
        for tgt, r4, before, after in tr.res:
            ch = [k for k, (x, y) in enumerate(zip(before, after)) if x != y]
            print(f"stage {tgt:#x} state {r4:#x}: the call changed {len(ch)} words of {a.window // 4}: "
                  f"{[hex(4 * k) for k in ch][:40]}")
        buf = range(0x804ACF90, 0x804AD010, 4)
        who = {}
        for ad in buf:
            for c in LOG["w"].get(ad, []):
                k = c if isinstance(c, str) else (hex(c[1]) if isinstance(c, tuple) else hex(c))
                who[k] = who.get(k, 0) + 1
        print("the block 0x804acf90 (32 words) written by:", who)
        nm = lambda c: c if isinstance(c, str) else (hex(c[1]) if isinstance(c, tuple) else hex(c))   # noqa: E731
        print("  word 5's writers in order:", [(nm(c), hex(q)) for c, q in zip(LOG["w"].get(0x804ACF90 + 20, []), LOG["wpc"].get(0x804ACF90 + 20, []))])
        print("  word 5's readers in order:", [nm(c) for c in LOG["r"].get(0x804ACF90 + 20, [])])
        # per stage: what it read and wrote, and who else wrote it this block (before it)
        order = {}
        for ad, cs in LOG["w"].items():
            order[ad] = cs
        for tgt, r4, _b, _a in tr.res:
            wr = {ad for ad, cs in LOG["w"].items() if tgt in cs}
            rd = {ad for ad, cs in LOG["r"].items() if tgt in cs}
            hist = rd & wr
            par = {ad for ad in rd - wr if any(c != tgt for c in LOG["w"].get(ad, []))}
            const = rd - wr - par
            print(f"\n== {tgt:#x} (state {r4:#x})")
            print("  writes:", spans(wr)[:30])
            print("  read and written (history, or in place):", spans(hist)[:30])
            print("  read, written by another this block (parameters):", spans(par)[:30])
            print("  read only (constants, or set before this block):", spans(const)[:30])
            for ad in sorted(par)[:12]:
                print(f"    {ad:#x} written by {[c if isinstance(c, str) else (c[0], hex(c[1])) if isinstance(c, tuple) else hex(c) for c in LOG['w'][ad]][:4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
