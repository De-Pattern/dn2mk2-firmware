"""v0.38, per-project sample pools in the ColdFire emulator (csrc/sampler/pools.c,
docs/project-pools.md): the `pools` scenario of `emu_waverider_menu.py`'s link16 step, with
the +Drive and the DSP played by Python (as link16's other scenarios).

The OS's own project code runs where the emulator can: a LOAD through ProjectManager's load
`0x40042E6E` (its +Drive read `0x40042B92` and temp-slot write `0x40040190` stubbed to
succeed, as docs/project-pools-research.md's probe did), so the build's three detours there
and the stock slot setter run; a NEW through its slot-setting site `0x40042AF0` (entered
from a stub frame, the rest of NEW skipped: the emulator cannot run it to the end), so its
detour and the stock setter run. Then, every audio period, the DSP's directory is checked:
an entry the DSP holds is the switched-to project's, over frames that are whole -- never a
sample of another project, never one half sent.

What it checks, in order (each a key of the result's "facts"):

1. migration: an image as v0.37 left it (three samples), no lists: the first power-on writes
   the legacy list (the image's directory, byte for byte) and the superblock, and not one
   sector of the pool image;
2. LOAD of a project without a list (7): the legacy pool, nothing sent but entries;
3. a pool change in 7 (LOAD TO PROJECT of a library sample): 7's own list, at once;
4. LOAD 9 (no list): the legacy pool (7's new sample silent), then a change in 9: one
   slot emptied, a second library sample loaded -- placed clear of 7's sample (another
   project's extent is never reused);
5. LOAD 7, LOAD 9, LOAD 7 ...: each its own slots; shared and resident samples cost nothing;
6. NEW (-1) and NEW in slot 12: an empty pool; 12's list written empty; LOAD 5 (made before
   the feature): today's pool; LOAD 12: empty;
7. a power cycle: the lists and the owner read back; the kit's sample first; each list's
   pool as it was;
8. a corrupted list: its previous copy; both copies corrupted: the legacy pool;
9. frames changed behind our back (an older build): that slot silent, never the wrong one;
10. the image changed behind our back: kept, into the owner's list;
11. a power cut after each sector of a pool change's writes, and of a switch's: every
    power-on after it finds a whole pool, the right owner's, and no list lost;
12. every sector written lies in the pool image or the lists' region, none past the device;
    and the image, at the end, is one v0.37 reads as it reads its own (downgrade).
"""

from __future__ import annotations

import struct

ACTIVE = 0x405CD899
PJ_LOAD, PJ_GET_PROJECT = 0x40042E6E, 0x4018A97A
SAVE_AS = 0x400402D8                    # interactiveSave's (project, slot, cb)
STUB_OPEN, STUB_TEMP = 0x40042B92, 0x40040190      # the load's +Drive read, its temp-slot write
NEW_SITE, NEW_AFTER = 0x40042AF0, 0x40042AFA
STORE_SECTOR = 0x600000
PL_SB, PL_LISTS, PL_SPAN, PL_END = 0x6D0000, 0x6D0100, 256, 0x6D0100 + 2 * 129 * 256
LIB, LIB_DATA = 0x700000, 0x700000 + 1 + 256 + 4


def csum(b):
    a, c = 1, 0
    for x in b:
        a = (a + x) & 0xFFFFFFFF
        c = (c + a) & 0xFFFFFFFF
    return (c << 16 ^ a) & 0xFFFFFFFF


def adler(b, s=1):
    a_, b_ = s & 0xFFFF, s >> 16
    for x in b:
        a_ = (a_ + x) % 65521
        b_ = (b_ + a_) % 65521
    return b_ << 16 | a_


def run(cx):
    import os
    stop = int(os.environ.get("POOLS_STOP", "99"))     # (debugging: end after section N)
    m, call, long, period = cx["machine"], cx["call"], cx["long"], cx["period"]
    disk, io, pool, dsp, syms = cx["disk"], cx["io"], cx["pool"], cx["dsp"], cx["syms"]
    SL, SM, base, guest_call = cx["SL"], cx["SM"], cx["base"], cx["guest_call"]
    scratch = cx["scratch"]
    facts, notes = {}, {}
    wlog = []
    io["log"] = wlog
    io.pop("errors", None)                            # every write, in order: (sector, data)

    def i32(name):
        return struct.unpack(">i", m.read(syms[name], 4))[0]

    def put(name, v):
        m.write(syms[name], struct.pack(">i", v))

    def on_disk(sector, n):
        return b"".join(disk.get(sector + k, bytes(512)) for k in range(n))

    disk.clear()                                # (the snapshot's own boot ran on an empty +Drive)
    # -- the content: three samples in a v0.37 image, two in the library ------------------
    def tone(n, a, p):
        return [a * ((k * p % 200) / 100 - 1) for k in range(n)]
    snd = [tone(1200, 0.5, 7), tone(900, 0.4, 13), tone(700, 0.3, 29)]
    names = ["KICK", "SNARE", "HAT"]
    img = SL.pool_bytes(snd, base, [1.0] * 3, [SM.FMT_I16] * 3, names)
    img = bytearray(img + bytes((-len(img)) % 512))
    dir0 = bytes(img[:SM.DATA_OFFSET])
    magic, nbytes, ck = 0x444E3251, len(img), csum(dir0)
    disk[STORE_SECTOR] = struct.pack(">5I", magic, 2, nbytes, ck, (~magic ^ nbytes ^ ck) & 0xFFFFFFFF).ljust(512, b"\0")
    for k in range(len(img) // 512):
        disk[STORE_SECTOR + 1 + k] = bytes(img[512 * k:512 * k + 512])
    img_frames = {n: bytes(img[struct.unpack_from("<I", img, 8 + 16 * s)[0] - base:][:2 * len(snd[s])])
                  for s, n in enumerate(names)}

    import random
    rng = random.Random(38)
    libx = bytes(rng.randrange(256) for _ in range(2 * 1500))
    liby = bytes(rng.randrange(256) for _ in range(2 * 800))

    def lent(start, frames, folder, name, data):
        e = bytearray(64)
        struct.pack_into("<III", e, 0, start, frames, 0x3F800000)
        e[12], e[13] = 1, folder
        struct.pack_into("<I", e, 16, adler(data))
        struct.pack_into("<I", e, 20, (frames * 2 + 511) // 512)
        e[24:24 + len(name)] = name.encode()
        struct.pack_into("<I", e, 60, adler(bytes(e[:60])) ^ 0x4C494245)
        return bytes(e)
    xs, ys = LIB_DATA, LIB_DATA + (len(libx) + 511) // 512
    idx = lent(xs, 1500, 0, "LIBX ONE", libx) + lent(ys, 800, 0, "LIBY TWO", liby)
    sb = [0x444E324C, 1, 2048]
    sb.append((~sb[0] ^ sb[1] ^ sb[2] ^ 0x5AA5C33C) & 0xFFFFFFFF)
    disk[LIB] = struct.pack(">4I", *sb).ljust(512, b"\0")
    ix = idx.ljust(256 * 512, b"\0")
    for k in range(256):
        if any(ix[512 * k:512 * k + 512]):
            disk[LIB + 1 + k] = ix[512 * k:512 * k + 512]
    fold = (b"INCOMING".ljust(32, b"\0") + b"RECORDED".ljust(32, b"\0")).ljust(4 * 512, b"\0")
    for k in range(4):
        disk[LIB + 257 + k] = fold[512 * k:512 * k + 512]
    for start, data in ((xs, libx), (ys, liby)):
        pd = data + bytes((-len(data)) % 512)
        for k in range(len(pd) // 512):
            disk[start + k] = pd[512 * k:512 * k + 512]
    # what each frame address must hold (the image's samples now, the library's once loaded)
    known = {struct.unpack_from("<I", img, 8 + 16 * s_)[0]: img_frames[n_] for s_, n_ in enumerate(names)}

    # -- what the DSP holds ------------------------------------------------------------------
    def dsp_entry(k):
        return tuple(pool.get(2 + 4 * k + j, 0) for j in range(4))

    def dsp_bytes(addr, n):
        lo = (addr - base) // 4
        return b"".join(struct.pack("<I", pool.get(lo + j, 0)) for j in range((n + 3) // 4))[:n]

    def image_dir():
        return on_disk(STORE_SECTOR + 1, 8)

    def entries(d):
        return [struct.unpack_from("<4I", d, 8 + 16 * k) for k in range(SM.POOL_SLOTS)]

    def name_of(d, k):
        return d[SM.NAMES_OFFSET + SM.NAME_BYTES * k:SM.NAMES_OFFSET + SM.NAME_BYTES * (k + 1)].split(b"\0")[0].decode("latin-1")

    def pool_names(d):
        return {k: name_of(d, k) for k, e in enumerate(entries(d)) if e[0] >= base + SM.DATA_OFFSET and e[1]}

    watch = {"target": None, "grace": 0, "bad": [], "checked": 0}

    def check_dsp():
        """every entry the DSP holds: the target's, over its own whole frames"""
        t = watch["target"]
        if t == "follow":                       # (outside a switch: the pool as it is now)
            t = target_from(image_dir())
        if t is None or watch["grace"] > 0:
            watch["grace"] -= 1
            return
        want_e, want_n = t
        for k in range(SM.POOL_SLOTS):
            e = dsp_entry(k)
            if not e[0] and not e[1]:
                continue
            watch["checked"] += 1
            ok = e == want_e[k] and k in want_n
            if ok:
                data = known.get(e[0])
                ok = data is not None and e[1] * 2 <= len(data) and dsp_bytes(e[0], 2 * e[1]) == data[:2 * e[1]]
            if not ok and len(watch["bad"]) < 8:
                watch["bad"].append((k, [hex(x) for x in e], want_n.get(k)))

    def step(n=1):
        for _ in range(n):
            period()
            call("smp_boot")
            check_dsp()

    def settle(limit=6000):
        quiet = 0
        for i in range(limit):
            step()
            if (i32("smp_pl_state") == 0 and i32("smp_lstate") in (0, 4) and long("smp_booted") == 2):
                quiet += 1
                if quiet > 15:
                    return i
            else:
                quiet = 0
        return -1

    def target_from(d):
        es = entries(d)
        return ([e if (e[0] >= base + SM.DATA_OFFSET and e[1]) else (0, 0, 0, 0) for e in es], pool_names(d))

    def os_load(slot):
        old = (m.read(STUB_OPEN, 4), m.read(STUB_TEMP, 4))
        m.write(STUB_OPEN, bytes.fromhex("70014e75"))
        m.write(STUB_TEMP, bytes.fromhex("70014e75"))
        guest_call(PJ_GET_PROJECT)
        proj = guest_call.returned["d0"]
        fn = scratch
        m.write(fn, bytes(32))
        guest_call(PJ_LOAD, proj, slot & 0xFFFFFFFF, fn, limit=20_000_000)
        m.write(STUB_OPEN, old[0])
        m.write(STUB_TEMP, old[1])
        return struct.unpack(">b", m.read(ACTIVE, 1))[0]

    def os_new(slot):
        stub = scratch + 0x100
        # link.w %fp,#0 ; movea.l 8(%fp),%a2 ; subq.l #4,%sp ; jmp NEW_SITE -- NEW's frame, to
        # the site; at NEW_AFTER (for this call only) unlk %fp ; rts back
        m.write(stub, bytes.fromhex("4e560000246e0008598f4ef9") + struct.pack(">I", NEW_SITE))
        old = m.read(NEW_AFTER, 4)
        m.write(NEW_AFTER, bytes.fromhex("4e5e4e75"))
        guest_call(PJ_GET_PROJECT)
        proj = guest_call.returned["d0"]
        guest_call(stub, proj, slot & 0xFFFFFFFF, limit=2_000_000)
        m.write(NEW_AFTER, old)
        return struct.unpack(">b", m.read(ACTIVE, 1))[0]

    def switch(fn, slot, want_dir=None):
        """a LOAD or NEW, then the periods until the pool is whole; the DSP watched throughout"""
        skipped0, sw0 = long("smp_pl_skipped"), long("smp_pl_switches")
        fs0 = {k: v for k, v in pool.items() if 4 * k >= SM.DATA_OFFSET}
        act = fn(slot)
        # until the ISR's blank lands, the DSP still holds the old pool: a few periods
        watch["target"] = None
        blank_at = None
        for i in range(40):
            step()
            if all(not dsp_entry(k)[0] and not dsp_entry(k)[1] for k in range(SM.POOL_SLOTS)) and blank_at is None:
                blank_at = i + 1
                break
        # until the switch is applied: nothing at all may play
        watch["target"] = ([(0, 0, 0, 0)] * SM.POOL_SLOTS, {})
        watch["grace"] = 0
        for i in range(6000):
            if long("smp_pl_switches") != sw0 or (i32("smp_pl_state") == 0 and i > 10):
                break
            step()
        d = image_dir()
        watch["target"] = target_from(want_dir if want_dir is not None else d)
        n = settle()
        watch["target"] = "follow"
        d = image_dir()
        changed = sum(1 for k, v in pool.items() if 4 * k >= SM.DATA_OFFSET and fs0.get(k) != v)
        return {"active": act, "blank_periods": blank_at, "settle": n, "owner": i32("smp_pl_owner"),
                "src": i32("smp_pl_src"), "switches": long("smp_pl_switches") - sw0,
                "skipped": long("smp_pl_skipped") - skipped0, "frame_words_written": changed,
                "pool": pool_names(d)}

    def dsp_pool():
        out = {}
        d = image_dir()
        for k in range(SM.POOL_SLOTS):
            e = dsp_entry(k)
            if e[0] or e[1]:
                out[k] = name_of(d, k)
        return out

    def list_dir(p):
        """list P's newest whole copy on the +Drive, as pools.c's reader takes it -> (dir, sums, seq)"""
        best = None
        for c in (0, 1):
            s = PL_LISTS + PL_SPAN * (2 * p + c)
            h = struct.unpack(">12I", disk.get(s, bytes(512))[:48])
            if h[0] != 0x444E324B or h[2] != p or h[11] != (csum(struct.pack(">11I", *h[:11])) ^ 0x504C4B31):
                continue
            body = on_disk(s + 1, 9)
            if csum(body[:512]) != h[6] or csum(body[512:]) != h[7]:
                continue
            if best is None or h[3] > best[2]:
                best = (body[512:], struct.unpack(">128I", body[:512]), h[3], h[4], c)
        return best

    def sb_read():
        best = None
        for c in (0, 1):
            w = struct.unpack(">11I", disk.get(PL_SB + c, bytes(512))[:44])
            if w[0] != 0x444E324A or w[10] != (csum(struct.pack(">10I", *w[:10])) ^ 0x504C5342):
                continue
            if best is None or w[2] > best[2]:
                best = w
        return best

    def power_cycle(active, limit=8000):
        """off and on: the DSP's memory gone, our RAM garbage, the counters as the chunk loads them"""
        pool.clear()
        dsp.update(seq=None, state=0, vdone=0, vsum=0, vsum2=0, send=None, ram=0)
        m.write(ACTIVE, struct.pack(">b", active))
        for n in ("smp_booted", "smp_lib_state", "smp_pl_on", "smp_pl_state", "smp_lstate",
                  "smp_pj_begins", "smp_pj_ends", "smp_pj_loads", "smp_pj_news", "smp_pj_last", "smp_blank_req"):
            put(n, 0)
        mir = cx["mirror"]
        m.write(mir + 0x140000, b"\xA5" * 0xD4000)
        m.write(mir + 0x220000, b"\x5A" * 0xC000 + b"\x5A" * 2560)
        watch["target"] = None
        for i in range(limit):
            period()
            call("smp_boot")
            if long("smp_booted") == 2 and i32("smp_pl_state") == 0 and i32("smp_lstate") in (0, 4) and i > 20:
                break
        watch["target"] = target_from(image_dir())
        watch["grace"] = 0
        settle()
        watch["target"] = "follow"
        return i32("smp_pl_boot_case")

    # 1. migration -------------------------------------------------------------------------
    m.write(ACTIVE, struct.pack(">b", 4))
    wlog.clear()
    case = power_cycle(4)
    sbw = sb_read()
    leg = list_dir(128)
    img_writes = [s for s, _ in wlog if STORE_SECTOR <= s < PL_SB]
    facts["1 migration: legacy list == the image's directory, superblock owner 4, nothing written to the image"] = (
        case == 1 and leg is not None and leg[0] == dir0 and sbw is not None and sbw[4] == 4
        and not img_writes and i32("smp_pl_on") == 1 and dsp_pool() == {0: "KICK", 1: "SNARE", 2: "HAT"})
    notes["1"] = {"case": case, "writes": len(wlog), "image_writes": len(img_writes), "dsp": dsp_pool(),
                  "sb": list(sbw) if sbw else None}
    # the legacy list's sums, filled in once the load had read the frames
    leg = list_dir(128)
    facts["1b the legacy list's sums known after the power-on load"] = leg is not None and all(leg[1][k] for k in range(3))

    if stop < 2:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 2}
    # 2. LOAD 7 (no list): the legacy pool, nothing but entries sent ---------------------------
    r = switch(os_load, 7)
    notes["2"] = r
    facts["2 LOAD 7 (no list): the legacy pool, its samples resident (no frame sent)"] = (
        r["active"] == 7 and r["owner"] == 7 and r["src"] == 128 and r["pool"] == {0: "KICK", 1: "SNARE", 2: "HAT"}
        and r["frame_words_written"] == 0 and r["skipped"] == 3 and dsp_pool() == r["pool"]
        and (r["blank_periods"] or 99) <= 8)

    if stop < 3:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 3}
    # 3. a change in 7: LOAD TO PROJECT of LIBX -------------------------------------------------
    call("smp_lib_load", 0)
    for _ in range(3000):
        step()
        if long("smp_lp_done") >= 1 and i32("smp_lstate") in (0, 4) and i32("smp_pl_state") == 0:
            break
    step(200)
    l7 = list_dir(7)
    facts["3 a change in 7 (LOAD TO PROJECT): 7's own list at once, the DSP has it"] = (
        l7 is not None and pool_names(l7[0]) == {0: "KICK", 1: "SNARE", 2: "HAT", 3: "LIBX ON"}
        and dsp_pool().get(3) == "LIBX ON" and l7[1][3] != 0)
    x_ent = entries(image_dir())[3]
    known[x_ent[0]] = libx
    notes["3"] = {"list7": pool_names(l7[0]) if l7 else None, "x_entry": [hex(v) for v in x_ent],
                  "sum3": l7[1][3] if l7 else None}

    if stop < 4:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 4}
    # 4. LOAD 9 (no list), then changes in 9 ------------------------------------------------------
    r = switch(os_load, 9)
    notes["4"] = r
    facts["4 LOAD 9 (no list): the legacy pool; 7's sample silent, nothing sent"] = (
        r["owner"] == 9 and r["src"] == 128 and r["pool"] == {0: "KICK", 1: "SNARE", 2: "HAT"}
        and dsp_pool() == r["pool"] and r["frame_words_written"] == 0)
    call("smp_discard", 1)
    step(100)
    call("smp_lib_load", 1)
    for _ in range(3000):
        step()
        if long("smp_lp_done") >= 2 and i32("smp_lstate") in (0, 4) and i32("smp_pl_state") == 0:
            break
    step(200)
    l9 = list_dir(9)
    y_ent = entries(image_dir())[1]
    known[y_ent[0]] = liby
    xa, xb = x_ent[0] - base, x_ent[0] - base + 2 * 1500
    ya, yb = y_ent[0] - base, y_ent[0] - base + 2 * 800
    facts["4b changes in 9 (slot 2 emptied, LIBY loaded): 9's own list; LIBY clear of 7's LIBX"] = (
        l9 is not None and pool_names(l9[0]) == {0: "KICK", 1: "LIBY TW", 2: "HAT"}
        and (yb <= (xa & ~511) or ya >= ((xb + 511) & ~511)) and dsp_pool() == {0: "KICK", 1: "LIBY TW", 2: "HAT"}
        and list_dir(128)[0] == dir0)
    notes["4b"] = {"x": [hex(xa), hex(xb)], "y": [hex(ya), hex(yb)], "list9": pool_names(l9[0]) if l9 else None}

    if stop < 5:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 5}
    # 5. back and forth ---------------------------------------------------------------------------
    rs = [switch(os_load, 7), switch(os_load, 9), switch(os_load, 7)]
    notes["5"] = rs
    facts["5 LOAD 7, 9, 7: each its own slots, shared samples never sent again"] = (
        rs[0]["pool"] == rs[2]["pool"] == {0: "KICK", 1: "SNARE", 2: "HAT", 3: "LIBX ON"}
        and rs[1]["pool"] == {0: "KICK", 1: "LIBY TW", 2: "HAT"}
        and all(r_["frame_words_written"] == 0 for r_ in rs) and all(r_["src"] == r_["owner"] for r_ in rs))

    if stop < 6:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 6}
    # 6. NEW, NEW in a slot, a legacy project, the NEW one again ------------------------------------
    r_new = switch(os_new, -1)
    r_new12 = switch(os_new, 12)
    l12 = list_dir(12)
    r5 = switch(os_load, 5)
    r12 = switch(os_load, 12)
    notes["6"] = {"new": r_new, "new12": r_new12, "load5": r5, "load12": r12}
    facts["6 NEW: an empty pool; NEW in 12: its list empty; LOAD 5 (old): today's pool; LOAD 12: empty"] = (
        r_new["pool"] == {} and r_new["owner"] == -1 and r_new["active"] == -1
        and r_new12["pool"] == {} and r_new12["owner"] == 12 and l12 is not None and pool_names(l12[0]) == {}
        and r5["pool"] == {0: "KICK", 1: "SNARE", 2: "HAT"} and r5["src"] == 128
        and r12["pool"] == {} and r12["src"] == 12 and dsp_pool() == {})

    # 6b. SAVE AS (the OS's 0x400402D8, its +Drive writes stubbed; no detour: the poll sees the
    # slot byte move): 9's pool becomes 42's too, and stays 9's
    switch(os_load, 9)
    old = m.read(STUB_TEMP, 4)
    m.write(STUB_TEMP, bytes.fromhex("70014e75"))
    guest_call(PJ_GET_PROJECT)
    proj = guest_call.returned["d0"]
    m.write(scratch, bytes(32))
    guest_call(SAVE_AS, proj, 42, scratch, limit=20_000_000)
    m.write(STUB_TEMP, old)
    act42 = struct.unpack(">b", m.read(ACTIVE, 1))[0]
    step(300)
    l42, l9 = list_dir(42), list_dir(9)
    r42 = switch(os_load, 42)
    facts["6b SAVE AS 42 from 9: 42's list is 9's pool, 9's kept; LOAD 42 gives it"] = (
        act42 == 42 and i32("smp_pl_owner") == 42 and l42 is not None and l9 is not None
        and pool_names(l42[0]) == pool_names(l9[0]) == {0: "KICK", 1: "LIBY TW", 2: "HAT"}
        and r42["src"] == 42 and r42["pool"] == {0: "KICK", 1: "LIBY TW", 2: "HAT"} and r42["frame_words_written"] == 0)
    notes["6b"] = {"active": act42, "load42": r42}

    if stop < 7:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 7}
    # 7. a power cycle, with 7 active; its kit's sample first -----------------------------------
    switch(os_load, 7)
    kit = struct.unpack(">I", m.read(0x800052A0, 4))[0]
    if kit:
        m.write(kit + 52 + 0xDE, bytes([8]))                 # track 1 a ONESHOT on SAMP 4 (LIBX)
        m.write(kit + 52 + 20 + 2 * 43, bytes([4, 0]))
    first = {}
    case = power_cycle(7)
    notes["7"] = {"case": case, "dsp": dsp_pool()}
    order = list(m.read(syms["smp_l_order"], 4))
    r9 = switch(os_load, 9)
    facts["7 a power cycle: 7's pool loads (its kit's sample first); 9's change kept"] = (
        case == 9 and notes["7"]["dsp"] == {0: "KICK", 1: "SNARE", 2: "HAT", 3: "LIBX ON"}
        and (not kit or order[0] == 3) and r9["pool"] == {0: "KICK", 1: "LIBY TW", 2: "HAT"} and r9["src"] == 9)
    notes["7"]["order"] = order
    notes["7"]["load9"] = r9

    if stop < 8:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 8}
    # 8. a corrupted list: the previous copy; both: the legacy pool ---------------------------------
    nm = scratch + 0x200
    m.write(nm, b"HATTWO\0\0")
    call("smp_rename", 2, nm)
    step(200)
    l9 = list_dir(9)
    newest = l9[4]
    s_new = PL_LISTS + PL_SPAN * (2 * 9 + newest)
    disk[s_new + 3] = bytes(b ^ 0xFF for b in disk.get(s_new + 3, bytes(512)))
    r_c1 = switch(os_load, 9)
    s_old = PL_LISTS + PL_SPAN * (2 * 9 + (1 - newest))
    disk[s_old + 3] = bytes(b ^ 0xFF for b in disk.get(s_old + 3, bytes(512)))
    case8 = power_cycle(9)
    r_c2 = switch(os_load, 9)
    notes["8"] = {"one": r_c1, "case": case8, "both": r_c2}
    facts["8 a corrupted list: its previous copy (HAT, not HATTWO); both copies: the legacy pool"] = (
        r_c1["pool"] == {0: "KICK", 1: "LIBY TW", 2: "HAT"} and r_c1["src"] == 9
        and r_c2["pool"] == {0: "KICK", 1: "SNARE", 2: "HAT"} and r_c2["src"] == 128)

    if stop < 9:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 9}
    # 9. frames changed behind our back: silent, never wrong ----------------------------------------
    sec = STORE_SECTOR + 1 + (x_ent[0] - base) // 512 + 1
    disk[sec] = bytes(b ^ 0x55 for b in disk.get(sec, bytes(512)))
    mis0 = long("smp_pl_mismatch")
    r_x = switch(os_load, 7, want_dir=None)
    # LIBX's frames on the +Drive no longer match: the DSP must not get its entry
    facts["9 frames changed behind our back: that slot silent (its entry emptied), the rest play"] = (
        long("smp_pl_mismatch") - mis0 == 1 and 3 not in dsp_pool() and dsp_pool() == {0: "KICK", 1: "SNARE", 2: "HAT"}
        and 3 not in pool_names(image_dir()))
    notes["9"] = {"switch": r_x, "mismatch": long("smp_pl_mismatch") - mis0, "dsp": dsp_pool()}
    disk[sec] = bytes(b ^ 0x55 for b in disk[sec])         # (put back for what follows)

    if stop < 10:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 10}
    # 10. the image changed behind our back (an older build added a sample) ------------------------
    d = bytearray(image_dir())
    struct.pack_into("<4I", d, 8 + 16 * 5, *entries(d)[0])  # slot 6 = KICK's frames, as v0.37 might
    d[SM.NAMES_OFFSET + SM.NAME_BYTES * 5:SM.NAMES_OFFSET + SM.NAME_BYTES * 6] = b"OLDBLD\0\0"
    for k in range(8):
        disk[STORE_SECTOR + 1 + k] = bytes(d[512 * k:512 * k + 512])
    h = struct.unpack(">5I", disk[STORE_SECTOR][:20])
    ck = csum(bytes(d))
    disk[STORE_SECTOR] = struct.pack(">5I", h[0], 2, h[2], ck, (~h[0] ^ h[2] ^ ck) & 0xFFFFFFFF).ljust(512, b"\0")
    case10 = power_cycle(7)
    l7 = list_dir(7)
    facts["10 the image changed behind our back: kept, and into the owner's list"] = (
        case10 == 6 and l7 is not None and pool_names(l7[0]).get(5) == "OLDBLD" and dsp_pool().get(5) == "OLDBLD")
    notes["10"] = {"case": case10, "list7": pool_names(l7[0]) if l7 else None}

    if stop < 11:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 11}
    # 11. power cuts: after each sector of a pool change, and of a switch ---------------------------
    def snapshot():
        return dict(disk)

    def replay(before, log, n):
        disk.clear()
        disk.update(before)
        done = 0
        for s, data in log:
            for k in range(len(data) // 512):
                if done >= n:
                    return
                disk[s + k] = data[512 * k:512 * k + 512]
                done += 1

    def sectors(log):
        return sum(len(d_) // 512 for _, d_ in log)

    def cut_points(log):
        """0, each write's end, and a sector inside each write of several (a torn write): every
        state a power cut can leave, up to which sectors of one write landed"""
        pts, at = {0}, 0
        for _, d_ in log:
            n_ = len(d_) // 512
            if n_ > 1:
                pts.add(at + 1)
                pts.add(at + n_ // 2)
            at += n_
            pts.add(at)
        return sorted(pts)

    cuts = []
    # (a) a rename in 7: the image's directory, its header, 7's list, the superblock
    before = snapshot()
    wlog.clear()
    m.write(nm, b"NEWNAME\0")
    call("smp_rename", 0, nm)
    step(300)
    log_a = list(wlog)
    after_a = snapshot()
    na = sectors(log_a)
    for n in cut_points(log_a):
        replay(before, log_a, n)
        c = power_cycle(7)
        l7 = list_dir(7)
        d = image_dir()
        nm0 = name_of(d, 0)
        ok = (l7 is not None and l7[0] == d and nm0 in ("KICK", "NEWNAME") and i32("smp_pl_owner") == 7
              and dsp_pool() == pool_names(d))
        cuts.append(("rename", n, c, nm0, ok))
    disk.clear()
    disk.update(after_a)
    power_cycle(7)
    # (b) a switch 7 -> 9: every cut, the OS keeping 9 (ACTIVE 9) or not (7). 9 first gets a
    # list of its own again (section 8 destroyed both of its copies): LIBY into its slot 2
    switch(os_load, 9)
    call("smp_discard", 1)
    step(100)
    call("smp_lib_load", 1)
    for _ in range(3000):
        step()
        if i32("smp_lstate") in (0, 4) and i32("smp_pl_state") == 0 and 1 in pool_names(image_dir()) \
                and pool_names(image_dir())[1] == "LIBY TW":
            break
    step(200)
    known[entries(image_dir())[1][0]] = liby
    want9 = pool_names(list_dir(9)[0]) if list_dir(9) else None
    switch(os_load, 7)
    before = snapshot()
    wlog.clear()
    switch(os_load, 9)
    log_b = list(wlog)
    after_b = snapshot()
    nb = sectors(log_b)
    want7 = pool_names(list_dir(7)[0])
    for n in cut_points(log_b):
        for act, want in ((9, want9), (7, want7)):
            replay(before, log_b, n)
            c = power_cycle(act)
            got = pool_names(image_dir())
            l7, l9 = list_dir(7), list_dir(9)
            ok = (got == want and i32("smp_pl_owner") == act and dsp_pool() == want
                  and l7 is not None and pool_names(l7[0]) == want7 and l9 is not None and pool_names(l9[0]) == want9)
            cuts.append(("switch", n, act, c, ok))
    disk.clear()
    disk.update(after_b)
    power_cycle(9)
    notes["11"] = {"want9": want9}
    facts[f"11 power cut after each of {na} sectors of a change and {nb} of a switch: a whole pool, the owner's, no list lost"] = (
        bool(cuts) and all(c_[-1] for c_ in cuts))
    notes["11"].update(bad=[c_ for c_ in cuts if not c_[-1]][:10], n=len(cuts))

    if stop < 12:
        return {"facts": facts, "notes": notes, "ok": False, "stopped": 12}
    # 12. where everything was written, and the image as v0.37 reads it ------------------------------
    written = sorted(disk)
    outside = [hex(s) for s in written if not (STORE_SECTOR <= s < STORE_SECTOR + 1 + SM.POOL_BYTES // 512
                                               or PL_SB <= s < PL_END or LIB <= s < LIB_DATA + 64)]
    hdr = struct.unpack(">5I", disk[STORE_SECTOR][:20])
    d = image_dir()
    v037 = (hdr[0] == 0x444E3251 and hdr[4] == (~hdr[0] ^ hdr[2] ^ hdr[3]) & 0xFFFFFFFF
            and hdr[3] == csum(d) and struct.unpack_from("<I", d, 0)[0] == SM.POOL_MAGIC
            and SM.DATA_OFFSET <= hdr[2] <= SM.POOL_BYTES)
    frames_ok = True
    for k, e in enumerate(entries(d)):
        if e[0] >= base + SM.DATA_OFFSET and e[1]:
            data = known.get(e[0])
            got = on_disk(STORE_SECTOR + 1 + (e[0] - base) // 512, (2 * e[1] + 1023) // 512)
            off = (e[0] - base) % 512
            frames_ok = frames_ok and data is not None and got[off:off + len(data)] == data
    facts["12 every write inside the image or the lists' region; the image whole as v0.37 reads it"] = (
        not outside and v037 and frames_ok and not io.get("errors"))
    notes["12"] = {"outside": outside[:5], "io_errors": io.get("errors", [])[:3], "v037_header": v037, "frames": frames_ok,
                   "pl_sectors_written": long("smp_pl_writes"), "lists_written": long("smp_pl_lists_written"),
                   "switches": long("smp_pl_switches"), "events": long("smp_pl_events"),
                   "skipped": long("smp_pl_skipped"), "blank_packets": long("smp_blank_sent")}

    facts["the DSP never held another project's sample, nor one half sent"] = not watch["bad"] and watch["checked"] > 0
    notes["dsp_watch"] = {"checked": watch["checked"], "bad": watch["bad"]}
    io.pop("log", None)
    return {"facts": facts, "notes": notes, "ok": all(facts.values())}
