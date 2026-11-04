"""v0.40 review: the slide copy/paste paths `emu_slides.py` did not drive, and a paste on a
nearly full lock table (docs/slides.md, "Copy and paste").

`dnfw.slides.PASTE_SITES` patches five stock sites that the slides step's earlier checks never
executed: page paste (0x40053246), its UNDO (0x40052634), track paste's UNDO (0x40052948), shift
(FUNC + LEFT/RIGHT, 0x40051158) and page autocopy (0x40050cce). Each is driven here through the
panel and stock's own code, its site counted (and the count asserted), and the whole lock table
read before and after:

- shift right, then left: every record of the track (stock's and ours) rotated by one step,
  every other record and the index untouched; then the table back byte for byte;
- track copy, change, paste, paste again (UNDO): the paste gives the copy, the UNDO the change;
- page copy, change, paste, paste again (UNDO): the page's steps from the copy, the rest of the
  track untouched; the UNDO gives the change;
- autocopy: the track cleared, the pattern 16 steps, lengthened to 17 in SEQUENCER PAGE SETUP
  (FUNC + PAGE, encoder E): page 1's locks, ours included, on page 2;
- slot 80: shift and autocopy treat our records (RAM header 0x50 / 0x51, "slot 80" and 81 to
  stock) as their own once the tag is cleared. The two stock routines are run again directly on
  the same pattern with and without our records: every write they make outside our records is
  the same (address, size, value, in order), the pattern bytes outside our records end the same,
  our headers are never written, and the sound's values (the voice mirror, the kit) are not
  touched by either;
- a paste on a nearly full table (review item 2): track and trig paste, our records ahead of the
  stock ones in the clipboard and exactly as many records free as the stock locks need. Every
  stock lock must come back; slides may be dropped. (939cbc42: our records took the free ones.)

Every comparison is of maps {(slot byte, track byte): 128 values}, a record whose values are all
0xffff left out (an empty record is stock's business, not a lock).

Run inside `emu_slides.py` (the gate) after its own panel checks, or alone for development:

    DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u scripts/emu_slides_paths.py \\
        --build out/bsl --snapshot ../digikit/out/snapshots/dn2-1.11/ui800M-v014.snap [--layout JSON]
"""

from __future__ import annotations

import struct

REC, RECS, INDEX, STEPBITS = 258, 80, 20640, 22256
PATTERN_PTR, PATTERN_BYTES, TABLE_AT = 0x42C5A9A0, 122478, 97872
SITES = {"page paste": 0x40053246, "page undo": 0x40052634, "track paste": 0x4005389C,
         "track undo": 0x40052948, "shift": 0x40051158, "autocopy": 0x40050CCE,
         "trig paste": 0x40055440}
SHIFT, AUTOCOPY = 0x40050DC2, 0x40050B4E
APP, TRACK_CTX = 0x4018A97A, 0x4003EFDE
CUR_A, CUR_B = 0x4003EFA8, 0x4003B394  # the app -> the pattern's settings (the autocopy wrapper's)
GET_LEN, SET_LEN = 0x4003A692, 0x4003A6C2                     # its length (pattern mode)
SAVE = 0x400DE718                       # the lock table, RAM -> stored (sl_save in the build)
SET_LOCK = 0x4003CEEE                   # (model, track, step, slot, value): a knob's p-lock
SRC, OUT, KIT, SOUND_STRIDE = 0x80003AF0, 0x800068E4, 0x800052A0, 1163
FUNC, RECORD, PLAY, STOP, PAGE, NO, LEFT, RIGHT = 17, 19, 20, 21, 22, 12, 13, 15
STEP_KEY = 25                           # [TRIG 1]


def key(code):
    return ((code - 1) // 8, (code - 1) % 8)


class Paths:
    def __init__(self, machine, panel, lay, check, report):
        from unicorn import m68k_const as K
        self.m, self.uc, self.panel, self.lay = machine, machine.uc, panel, lay
        self.check, self.report, self.K = check, report, K
        self.hits = {n: 0 for n in SITES}
        from unicorn import UC_HOOK_CODE
        for n, va in SITES.items():
            def h(uc_, ad, sz, us, n=n):
                self.hits[n] += 1
            self.uc.hook_add(UC_HOOK_CODE, h, begin=va, end=va)
        self.saves = None                       # while logging: the stored tables SAVE wrote this one into

        def s(uc_, ad, sz, us):
            if self.saves is not None:
                sp = uc_.reg_read(self.K.UC_M68K_REG_A7)
                if self.m.long(sp + 8) == self.tbl:
                    self.saves.append(self.m.long(sp + 4))
        self.uc.hook_add(UC_HOOK_CODE, s, begin=SAVE, end=SAVE)
        machine.flush()                         # (a block translated before a hook runs without it)
        self.P = machine.long(PATTERN_PTR)
        self.tbl = self.P + TABLE_AT

    # ---- calls into the firmware from inside the UI's run (the UI's PC and SR put back) ----
    def call(self, fn, *args):
        K, uc, m = self.K, self.uc, self.m
        regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]
        saved = [uc.reg_read(r) for r in regs]
        pc0, sr0 = uc.reg_read(K.UC_M68K_REG_PC), uc.reg_read(K.UC_M68K_REG_SR)
        sp = 0x46A20000 - 0x200
        sentinel = 0x46A20400
        m.write(sp, struct.pack(">I", sentinel) + b"".join(struct.pack(">I", x & 0xFFFFFFFF) for x in args))
        m.write(sentinel, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        stepper = getattr(m.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        try:
            uc.emu_start(fn, sentinel, count=50_000_000)
        finally:
            if stepper is not None:
                stepper.left = 0
        d0, pc = uc.reg_read(K.UC_M68K_REG_D0), uc.reg_read(K.UC_M68K_REG_PC)
        for r, v in zip(regs, saved):
            uc.reg_write(r, v)
        uc.reg_write(K.UC_M68K_REG_PC, pc0)
        uc.reg_write(K.UC_M68K_REG_SR, sr0)
        self.m.pc = pc0
        if pc != sentinel:
            raise RuntimeError(f"call {fn:#x} stopped at {pc:#x}")
        return d0

    def ctx(self):
        return self.call(TRACK_CTX, self.call(APP))

    # ---- the panel ---------------------------------------------------------------------------
    def combo(self, mod, k):
        """MOD held, K pressed and released (a key of MOD's group keeps MOD in its mask)"""
        p, m = self.panel, self.m
        mc, mb = key(mod)
        kc, kb = key(k)
        held = (1 << mb) if mc == kc else 0
        p.hold((mc, mb), 5_000_000)
        m.pc = p.panelin.press(m.m, p.profile, kc, kb, held=held)
        p.settle(2_000_000)
        m.pc = p.panelin.release(m.m, p.profile, kc, kb, held=held)
        p.settle(10_000_000)
        p.let_go((mc, mb))
        p.settle(10_000_000)

    def tap(self, k):
        self.panel.tap(key(k))
        self.panel.settle(10_000_000)

    def turn(self, enc, delta):
        p = self.panel
        self.m.pc = p.panelin.encoder(self.m.m, p.profile, enc, delta)
        p.settle(10_000_000)

    # ---- the lock table ------------------------------------------------------------------------
    def table(self):
        return bytes(self.m.read(self.tbl, STEPBITS + 2048))

    @staticmethod
    def maps(raw):
        """{(slot byte, track byte): values} of every record with a lock"""
        out = {}
        for i in range(RECS):
            r = raw[REC * i:REC * (i + 1)]
            if r[0] == 0xFF:
                continue
            vals = struct.unpack(">128H", r[2:])
            if any(v != 0xFFFF for v in vals):
                out[(r[0], r[1])] = vals
        return out

    def now(self):
        return self.maps(self.table())

    @staticmethod
    def ours(h, t=0):
        return tuple(h) in ((0x50, 0x20 | t), (0x51, 0x20 | t))

    def clear_track(self):
        """FUNC + PLAY until the track has no lock record left: a second FUNC + PLAY right after a
        clear (or a paste) is its UNDO (0x40052824, measured), so one press may restore instead.
        Stock's clear (0x400e745c) frees a record by its header and leaves its values (its value
        loop strides 260 bytes over 258-byte records), and stock's setter 0x4003ceee takes a free
        record as it finds it, so a fresh lock could inherit a freed record's values; the freed
        records are reset to 0xffff here, so what a check reads is what the paste wrote"""
        for _ in range(3):
            self.combo(FUNC, PLAY)
            raw = self.table()
            if not any(raw[REC * i + 1] in (0, 0x20) and raw[REC * i] != 0xFF for i in range(RECS)):
                for i in range(RECS):
                    if raw[REC * i] == 0xFF:
                        self.m.write(self.tbl + REC * i + 2, b"\xff" * (REC - 2))
                return True
        return False

    def set_ours(self, step, sld, slen):
        sl_set = self.lay["sl_lock_set"]
        if sld is not None:
            self.call(sl_set, self.tbl, 0, step, 0, sld)
        if slen is not None:
            self.call(sl_set, self.tbl, 0, step, 1, slen)

    def set_stock(self, slot, step, value):
        """a stock p-lock as a knob turned on a held trig makes it (stock's own setter)"""
        model = self.m.long(self.ctx() + 44)
        return self.call(SET_LOCK, model, 0, step, slot, value) & 0xFF

    @staticmethod
    def describe(mp, t=0):
        rows = []
        for (s, tb), v in sorted(mp.items()):
            if tb & 0x0F == t:
                rows.append(f"{s:#x}/{tb:#x}:" + ",".join(f"{i}={x:#x}" for i, x in enumerate(v) if x != 0xFFFF))
        return "; ".join(rows)

    # ---- the checks ----------------------------------------------------------------------------
    def pattern(self):
        return self.call(CUR_B, self.call(CUR_A, self.call(APP)))

    def run(self, only=None):
        for name, f in (("shift", lambda: self.shift_checks(self.call(GET_LEN, self.pattern()) & 0xFFFF)), ("track", self.track_undo_checks),
                        ("page", self.page_checks), ("slot80", self.slot80_checks),
                        ("autocopy", self.autocopy_checks), ("full", self.full_table_checks)):
            if only is None or name in only:
                f()
        self.report["paths_hits"] = dict(self.hits)

    def shift_checks(self, length):
        t0 = self.table()
        before = self.maps(t0)
        h0 = self.hits["shift"]
        self.combo(FUNC, RIGHT)
        t1 = self.table()
        after = self.maps(t1)
        rot = {}
        for h, v in before.items():
            if h[1] & 0x0F == 0 and (h[1] == 0 or self.ours(h)):
                w = list(v)
                for s in range(length):
                    w[(s + 1) % length] = v[s]
                rot[h] = tuple(w)
            else:
                rot[h] = v
        heads = all(t1[REC * i:REC * i + 2] == t0[REC * i:REC * i + 2] for i in range(RECS))
        rest = t1[INDEX:STEPBITS] == t0[INDEX:STEPBITS]
        n = self.hits["shift"] - h0
        self.report["shift_length"] = length
        self.check("v0.40 shift (FUNC + RIGHT): every lock of the track, SLD/SLEN included, one step on; "
                   "other tracks, every record's header and the index untouched",
                   n > 0 and after == rot and heads and rest and any(self.ours(h) for h in before),
                   f"site hits {n}; expected {self.describe(rot)}; got {self.describe(after)}; heads {heads}, index {rest}")
        self.combo(FUNC, LEFT)
        t2 = self.table()
        self.check("v0.40 shift back (FUNC + LEFT): the lock table byte for byte as before",
                   t2[:STEPBITS] == t0[:STEPBITS] and self.hits["shift"] - h0 > n,
                   f"site hits {self.hits['shift'] - h0}, "
                   f"{sum(a != b for a, b in zip(t2[:STEPBITS], t0[:STEPBITS]))} bytes differ")

    def track_undo_checks(self):
        p0 = self.lay.get("sl_pasted")
        pasted = (lambda: self.m.long(p0)) if p0 else (lambda: 0)
        self.combo(FUNC, RECORD)                                # copy
        copied = self.now()
        self.set_ours(40, None, 3)                              # the track changed after the copy
        self.set_ours(50, 1, 5)
        self.set_stock(90, 50, 0x2222)
        self.set_stock(90, 5, 0x3333)
        changed = self.now()
        hp, hu, n0 = self.hits["track paste"], self.hits["track undo"], pasted()
        self.combo(FUNC, STOP)                                  # paste
        got_paste, n1 = self.now(), pasted()
        self.combo(FUNC, STOP)                                  # paste again: UNDO
        got_undo, n2 = self.now(), pasted()
        self.report["track_undo"] = {"copied": self.describe(copied), "changed": self.describe(changed),
                                     "pasted": self.describe(got_paste), "undone": self.describe(got_undo)}
        self.check("v0.40 track paste: the copy back, SLD/SLEN and the stock locks, exactly",
                   got_paste == copied and changed != copied and self.hits["track paste"] > hp and n1 > n0,
                   f"site hits {self.hits['track paste'] - hp}, ours written {n1 - n0}; "
                   f"copy {self.describe(copied)}; got {self.describe(got_paste)}")
        self.check("v0.40 track paste's UNDO (FUNC + STOP again): the track as it was before the paste, "
                   "SLD/SLEN and the stock locks, exactly",
                   got_undo == changed and self.hits["track undo"] > hu and n2 > n1,
                   f"site hits {self.hits['track undo'] - hu}, ours written {n2 - n1}; "
                   f"want {self.describe(changed)}; got {self.describe(got_undo)}")

    def page_checks(self):
        p0 = self.lay.get("sl_pasted")
        pasted = (lambda: self.m.long(p0)) if p0 else (lambda: 0)
        self.combo(PAGE, RECORD)                                # copy page 1
        copied = self.now()
        self.set_ours(5, None, 9)                               # page 1 changed after the copy ...
        self.set_ours(10, 1, 3)
        self.set_stock(90, 5, 0x1111)
        self.set_stock(90, 10, 0x4321)
        self.set_ours(60, 1, 11)                                # ... and a step past it
        self.set_stock(90, 60, 0x0606)
        changed = self.now()
        want = {}
        for h in set(copied) | set(changed):
            if h[1] & 0x0F == 0 and (h[1] == 0 or self.ours(h)):
                c = copied.get(h, (0xFFFF,) * 128)
                d = changed.get(h, (0xFFFF,) * 128)
                v = tuple(c[i] if i < 16 else d[i] for i in range(128))
            else:
                v = changed.get(h)
            if v is not None and any(x != 0xFFFF for x in v):
                want[h] = v
        hp, hu, n0 = self.hits["page paste"], self.hits["page undo"], pasted()
        self.combo(PAGE, STOP)                                  # paste
        got_paste, n1 = self.now(), pasted()
        self.combo(PAGE, STOP)                                  # paste again: UNDO
        got_undo, n2 = self.now(), pasted()
        self.report["page"] = {"copied": self.describe(copied), "changed": self.describe(changed),
                               "pasted": self.describe(got_paste), "undone": self.describe(got_undo)}
        self.check("v0.40 page paste (PAGE + STOP): page 1's steps from the copy, SLD/SLEN and the stock "
                   "locks, the rest of the track as it was",
                   got_paste == want and want != changed and self.hits["page paste"] > hp and n1 > n0,
                   f"site hits {self.hits['page paste'] - hp}, ours written {n1 - n0}; "
                   f"want {self.describe(want)}; got {self.describe(got_paste)}")
        self.check("v0.40 page paste's UNDO (PAGE + STOP again): the track as it was before the paste",
                   got_undo == changed and self.hits["page undo"] > hu and n2 > n1,
                   f"site hits {self.hits['page undo'] - hu}, ours written {n2 - n1}; "
                   f"want {self.describe(changed)}; got {self.describe(got_undo)}")

    # ---- slot 80: stock's shift and autocopy, with our records and without --------------------
    def logged(self, fn, *args):
        """-> (every write fn makes, with the bytes it overwrote; the stored tables its change notice
        SAVEd this table into)"""
        from unicorn import UC_HOOK_MEM_WRITE
        log, saves = [], []

        def w(uc_, access, address, size, value, user):         # (before the write: old is still there)
            if not 0x46A1F000 <= address < 0x46A20410:          # (the call's own stack)
                log.append((address, size, value & ((1 << (8 * size)) - 1), bytes(uc_.mem_read(address, size))))

        h = self.uc.hook_add(UC_HOOK_MEM_WRITE, w)
        self.m.flush()
        self.saves = saves
        try:
            self.call(fn, *args)
        finally:
            self.saves = None
            self.uc.hook_del(h)
        if not saves:
            raise RuntimeError("SAVE never seen: the stored copies could not be told apart")
        return log, saves

    def slot80_checks(self):
        m = self.m
        ctx = self.ctx()
        P, tbl = self.P, self.tbl
        # our records, and a stock record of track 0 beside them
        self.set_ours(3, 1, 4)
        self.set_ours(9, 0, 6)
        self.set_stock(90, 3, 0x0303)
        raw = self.table()
        ours_idx = [i for i in range(RECS) if self.ours(raw[REC * i:REC * i + 2])]
        spans = [(tbl + REC * i, tbl + REC * (i + 1)) for i in ours_idx]
        stored = []                     # their stored copies: SAVE (sl_save), checked by emu_slides.py

        def inside_ours(a, size=1):
            return any(lo <= a and a + size <= hi for lo, hi in spans) or \
                any(b + REC * i <= a and a + size <= b + REC * (i + 1) for b in stored for i in ours_idx)
        def undo(log):
            for a, _n, _v, old in reversed(log):
                m.write(a, old)
        sound = lambda: bytes(m.read(SRC, 2 * 1734)) + bytes(m.read(OUT, 2 * 1734)) + \
            bytes(m.read(m.long(KIT) + 52, 16 * SOUND_STRIDE))          # noqa: E731
        for name, fn, args in (("shift", SHIFT, (ctx, 1, -1)), ("autocopy", AUTOCOPY, (ctx, 0, 1))):
            saved = bytes(m.read(P, PATTERN_BYTES))
            s0 = sound()
            h0 = self.hits[name]
            log_a, sv_a = self.logged(fn, *args)
            after_a = bytes(m.read(P, PATTERN_BYTES))
            s1 = sound()
            undo(log_a)                                         # every byte it wrote put back
            hits_a = self.hits[name] - h0
            heads_a = [after_a[TABLE_AT + REC * i:TABLE_AT + REC * i + 2] for i in ours_idx]
            moved = [after_a[TABLE_AT + REC * i + 2:TABLE_AT + REC * (i + 1)] !=
                     saved[TABLE_AT + REC * i + 2:TABLE_AT + REC * (i + 1)] for i in ours_idx]
            # the control: the same pattern with our records freed
            base = bytearray(saved)
            for i in ours_idx:
                base[TABLE_AT + REC * i:TABLE_AT + REC * (i + 1)] = b"\xff" * REC
            m.write(P, bytes(base))
            log_b, sv_b = self.logged(fn, *args)
            stored[:] = sorted(set(sv_a) | set(sv_b))
            after_b = bytes(m.read(P, PATTERN_BYTES))
            s2 = sound()
            undo(log_b)
            m.write(P, saved)                                   # as it was
            out_a = [x[:3] for x in log_a if not inside_ours(*x[:2])]
            out_b = [x[:3] for x in log_b if not inside_ours(*x[:2])]
            hdr = [x for x in log_a if any(lo <= x[0] < lo + 2 for lo, _ in spans)]

            def masked(buf):
                b = bytearray(buf)
                for i in ours_idx:
                    b[TABLE_AT + REC * i:TABLE_AT + REC * (i + 1)] = b"\x00" * REC
                return bytes(b)
            same_mem = masked(after_a) == masked(after_b)
            first = next((k for k, (x, y) in enumerate(zip(out_a, out_b)) if x != y), min(len(out_a), len(out_b)))
            self.report[f"slot80_{name}"] = {"ours_idx": ours_idx, "stored": [hex(x) for x in stored],
                                              "writes": len(log_a), "writes_control": len(log_b),
                                              "into_ours": len(log_a) - len(out_a), "site_hits": hits_a,
                                              "first_difference": [[hex(v) for v in x] for x in out_a[first:first + 6]]
                                              + ["--"] + [[hex(v) for v in x] for x in out_b[first:first + 6]]
                                              if out_a != out_b else None}
            self.check(f"v0.40 slot 80 ({name}, 0x{fn:08x}): with our records it does exactly what it does "
                       "without them, outside their values (every write, in order, both runs from the same "
                       "memory; the pattern's bytes); "
                       "their headers never written; the voice mirror and the kit untouched",
                       hits_a > 0 and out_a == out_b and same_mem and not hdr and all(
                           hd in (bytes([0x50, 0x20]), bytes([0x51, 0x20])) for hd in heads_a)
                       and any(moved) and s0 == s1 == s2,
                       f"site hits {hits_a}; writes {len(log_a)} / control {len(log_b)}, outside ours "
                       f"(first difference at {first}: {self.report[f'slot80_{name}']['first_difference']}) "
                       f"{len(out_a)} / {len(out_b)} equal {out_a == out_b}; pattern equal {same_mem}; "
                       f"header writes {len(hdr)}; ours moved {moved}; sound untouched {s0 == s1 == s2}")

    def autocopy_checks(self):
        cleared = self.clear_track()                            # page 2 empty
        self.set_ours(3, 1, 4)
        self.set_ours(7, 0, 6)
        self.set_stock(90, 3, 0x1357)
        self.set_stock(90, 7, 0x2468)
        self.set_stock(67, 12, 0x5000)
        pat = self.pattern()
        self.call(SET_LEN, pat, 16)                             # stock's own setter (the menu's row 0)
        before = self.now()
        h0 = self.hits["autocopy"]
        self.combo(FUNC, PAGE)                                  # SEQUENCER PAGE SETUP
        self.panel.screen("paths_page_setup")
        length = []
        for _ in range(8):                                      # E: LENGTH up past 16 (a step is
            self.turn(4, 12)                                    # about a dozen detents, measured)
            length.append(self.call(GET_LEN, pat) & 0xFFFF)
            if length[-1] > 16:
                break
        self.panel.screen("paths_length_up")
        self.tap(NO)
        after = self.now()
        want = {}
        for h, v in before.items():
            if h[1] == 0 or self.ours(h):
                w = list(v)
                w[16:32] = v[0:16]
                want[h] = tuple(w)
            else:
                want[h] = v
        n = self.hits["autocopy"] - h0
        self.report["autocopy"] = {"before": self.describe(before), "after": self.describe(after), "hits": n,
                                   "lengths": length}
        self.check("v0.40 page autocopy (pattern lengthened past 16 steps in PAGE SETUP): page 1's locks on page 2, "
                   "SLD/SLEN as the stock locks, nothing else changed",
                   cleared and n > 0 and after == want and any(self.ours(h) for h in before),
                   f"site hits {n}; track cleared first {cleared}; length 16 -> {length}; want {self.describe(want)}; got {self.describe(after)}")

    def full_table_checks(self):
        """review item 2: a paste never costs a stock lock its record"""
        m = self.m
        tbl = self.tbl
        SLOTS = (60, 61, 62)

        def free():
            return [i for i in range(RECS) if m.read(tbl + REC * i, 1) == b"\xff"]

        def fill(keep):
            """junk stock records (track 9) in every free record but KEEP -> their indices"""
            got = []
            idx = free()
            for k, i in enumerate(idx[:len(idx) - keep]):
                slot = k % 100
                m.write(tbl + REC * i, bytes([slot, 9]) + b"\x01\x01" + b"\xff\xff" * 127)
                got.append(i)
            return got

        def unfill(got):
            for i in got:
                m.write(tbl + REC * i, b"\xff" * REC)

        for kind in ("track", "trig"):
            self.clear_track()                                  # no record of track 0
            self.tap(STEP_KEY + 2)                              # a trig on step 3 (placing it clears its locks)
            self.set_ours(2, 1, 5)                              # ours first (the lowest free records) ...
            for k, s in enumerate(SLOTS):                       # ... then the stock locks after them
                self.set_stock(s, 2, 0x4000 + s)
            src = self.now()
            stock_want = {h: v for h, v in src.items() if h[1] == 0}
            heads = [m.read(tbl + REC * i, 2) for i in range(RECS)]
            mine = [i for i, hd in enumerate(heads) if self.ours(hd)]
            theirs = [i for i, hd in enumerate(heads) if hd in tuple(bytes([s, 0]) for s in SLOTS)]
            first = bool(mine) and len(theirs) == len(SLOTS) and max(mine) < min(theirs)
            if kind == "track":
                self.combo(FUNC, RECORD)                        # copy the track
            else:
                self.panel.hold(key(STEP_KEY + 2), 5_000_000)   # step 3 held, RECORD: trig copy
                self.tap(RECORD)
                self.panel.let_go(key(STEP_KEY + 2))
                self.panel.settle(10_000_000)
            self.clear_track()                                  # cleared again
            junk = fill(len(SLOTS))
            nfree = len(free())
            h0 = self.hits[f"{kind} paste"]
            if kind == "track":
                self.combo(FUNC, STOP)                          # paste
            else:
                self.panel.hold(key(STEP_KEY + 2), 5_000_000)   # step 3 held (empty: a trig placed), STOP
                self.tap(STOP)                                  # trig paste on step 3
                self.panel.let_go(key(STEP_KEY + 2))
                self.panel.settle(10_000_000)
            want = stock_want
            got = self.now()
            unfill(junk)
            got_stock = {h: v for h, v in got.items() if h[1] == 0}
            slides = {h: v for h, v in got.items() if self.ours(h)}
            n = self.hits[f"{kind} paste"] - h0
            self.report[f"full_{kind}"] = {"ours_at": mine, "stock_at": theirs, "free": nfree,
                                           "stock": self.describe(got_stock), "slides": self.describe(slides), "hits": n}
            self.check(f"v0.40 {kind} paste on a nearly full lock table ({nfree} records free, our records "
                       f"first in the clipboard): every stock lock pasted (slides may be dropped)",
                       n > 0 and nfree == len(SLOTS) and first and got_stock == want,
                       f"site hits {n}; ours at {mine}, stock at {theirs}; want {self.describe(want)}; "
                       f"got {self.describe(got_stock)}; slides {self.describe(slides) or 'dropped'}")
        self.clear_track()


def main() -> int:
    import argparse
    import json
    import os
    import pathlib
    import sys
    here = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    sys.path.insert(0, str(here.parent / "src"))
    from emulib.image import differences
    from emulib.machine import Machine
    from emulib.panel import Panel
    from unicorn import UC_PROT_ALL, UcError

    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--layout", default=str(here.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--png-dir", default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--only", default=None, help="development: shift,track,page,slot80,autocopy,full")
    a = p.parse_args()
    machine = Machine(a.snapshot)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    si = pathlib.Path(a.snapshot + ".section_3_MAIN_OS.bin")
    if si.exists():
        machine.apply([(va, stock[va - 0x40000400:va - 0x40000400 + len(b)]) for va, b in
                       differences(stock, si.read_bytes()) if va + len(b) <= 0x40000400 + len(stock)])
    image = (pathlib.Path(a.build) / "section_3_MAIN_OS.bin").read_bytes()
    machine.apply(differences(stock, image))
    from dnfw.mods import platform
    for va, blob in platform.runtime(image):
        machine.write(va, blob)
    from dnfw.sampler import machines as SMx
    for page in range(SMx.MIRROR, SMx.MIRROR + 0x500000, 0x100000):
        try:
            machine.uc.mem_map(page, 0x100000, UC_PROT_ALL)
        except UcError:
            pass
    machine.flush()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    failures, report = [], {"checks": {}}

    def check(name, ok, detail=""):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
        if not ok:
            failures.append(name)
    panel = Panel(machine, png_dir=a.png_dir or "out/slides-paths-png")
    panel.settle(5_000_000)
    panel.tap(key(RECORD))                                      # grid recording
    panel.settle(10_000_000)
    panel.tap(key(STEP_KEY))                                    # a trig on step 1
    panel.settle(10_000_000)
    ps = Paths(machine, panel, lay, check, report)
    # the state emu_slides.py leaves: ours on steps 1, 6, 9, 41 and a stock lock beside them
    for st, sld, slen in ((0, 1, 7), (5, 1, 2), (8, 1, 2), (40, 1, 9)):
        ps.set_ours(st, sld, slen)
    for st in (5, 8, 40):
        ps.set_stock(90, st, 0x1234 + st)
    ps.run(only=a.only.split(",") if a.only else None)
    faults = getattr(machine.m, "faults", [])
    check("no fault", not faults, f"{len(faults)} fault(s)")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1) + "\n")
    print(f"slides paths: {'PASS' if not failures else 'FAIL ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
