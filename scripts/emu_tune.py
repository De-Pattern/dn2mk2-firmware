"""v0.61, microtuning's record per project in the ColdFire emulator (csrc/sampler/tune.c,
docs/microtuning.md): the `tune` scenario of `emu_waverider_menu.py`'s link16 step, with the
+Drive played by Python. The OS's own LOAD and NEW run as in emu_pools.py (the same stubs), so
the build's hooks count them as on the unit; tn_poll is called as the UI loop calls it, and the
UI's clock (0x4058E8D4) is moved on by hand.

What it checks (each a key of the result's "facts"):

1. power-on with no record: 12-TET, no track tuned, and not one sector written;
2. a change in project 7 (a tuning, ROOT, two tracks, a USER slot's offsets): nothing written
   for two seconds, then one record in 7's own sectors;
3. LOAD 9 (no record): 12-TET, nothing tuned; a change there: 9's record;
4. LOAD 7: 7's tuning, ROOT, tracks and USER slot as they were; the interrupt's snapshot too;
5. a second change in 7 goes into the other copy; that copy corrupted: the earlier copy is used;
   both corrupted: 12-TET (and the refusals counted); a record naming another project: refused;
6. NEW in slot 9: 12-TET, and 9's record replaced, so LOAD 9 gives 12-TET too;
7. a power cycle: the active project's tuning read back;
8. ERASE MOD DATA's lock: nothing written;
9. every sector written lies in the tunings' region (0x6E0400..0x6E04FF).
"""

from __future__ import annotations

import struct

ACTIVE = 0x405CD899
NOW = 0x4058E8D4
PJ_LOAD, PJ_GET_PROJECT = 0x40042E6E, 0x4018A97A
STUB_OPEN, STUB_TEMP = 0x40042B92, 0x40040190
NEW_SITE, NEW_AFTER = 0x40042AF0, 0x40042AFA
TN_AT, TN_END = 0x6E0400, 0x6E0500


def run(cx):
    m, call, disk, io, syms, guest_call = cx["machine"], cx["call"], cx["disk"], cx["io"], cx["syms"], cx["guest_call"]
    scratch = cx["scratch"]
    facts = {}
    wlog = []
    io["log"] = wlog

    def i32(name):
        return struct.unpack(">i", m.read(syms[name], 4))[0]

    def put(name, v):
        m.write(syms[name], struct.pack(">i", v))

    def state():
        user = list(struct.unpack(">96h", m.read(syms["tn_user"], 192)))
        return (i32("tn_cur"), i32("tn_root"), i32("tn_mask"), tuple(user))

    def snapshot():
        sel = i32("tn_sel") & 1
        raw = m.read(syms["tn_snap"] + 28 * sel, 28)
        fine = list(struct.unpack(">12h", raw[:24]))
        root, mask = struct.unpack(">hH", raw[24:28])
        return fine, root, mask

    def clock(dt):
        now = struct.unpack(">I", m.read(NOW, 4))[0]
        m.write(NOW, struct.pack(">I", (now + dt) & 0xFFFFFFFF))

    def poll(n=1):
        for _ in range(n):
            call("tn_poll")

    def settle():
        """past the two seconds a change waits, polled as the UI loop polls"""
        poll(2)
        clock(3200)
        poll(3)

    def os_load(slot):
        old = (m.read(STUB_OPEN, 4), m.read(STUB_TEMP, 4))
        m.write(STUB_OPEN, bytes.fromhex("70014e75"))
        m.write(STUB_TEMP, bytes.fromhex("70014e75"))
        guest_call(PJ_GET_PROJECT)
        proj = guest_call.returned["d0"]
        m.write(scratch, bytes(32))
        guest_call(PJ_LOAD, proj, slot & 0xFFFFFFFF, scratch, limit=20_000_000)
        m.write(STUB_OPEN, old[0])
        m.write(STUB_TEMP, old[1])
        poll(2)
        return struct.unpack(">b", m.read(ACTIVE, 1))[0]

    def os_new(slot):
        stub = scratch + 0x100
        m.write(stub, bytes.fromhex("4e560000246e0008598f4ef9") + struct.pack(">I", NEW_SITE))
        old = m.read(NEW_AFTER, 4)
        m.write(NEW_AFTER, bytes.fromhex("4e5e4e75"))
        guest_call(PJ_GET_PROJECT)
        proj = guest_call.returned["d0"]
        guest_call(stub, proj, slot & 0xFFFFFFFF, limit=2_000_000)
        m.write(NEW_AFTER, old)
        poll(2)
        return struct.unpack(">b", m.read(ACTIVE, 1))[0]

    def fine_of(t):
        n = t * 256
        return (n + 500) // 1000 if n >= 0 else -((-n + 500) // 1000)

    def boot():
        put("tn_owner", -2)
        poll(2)

    disk.clear()
    # 1. power-on, no record (the project the snapshot booted with)
    boot()
    zero = (0, 0, 0, tuple([0] * 96))
    facts["1 power-on, no record: 12-TET, no track tuned, nothing written"] = state() == zero and not wlog

    # 2. a change in project 7
    a7 = os_load(7)
    n0 = len(wlog)
    call("tn_set", 2, 2, 0x0005)               # JUST MINOR, ROOT D, tracks 1 and 3
    user = [0] * 96
    user[12 * 3 + 4] = -137                    # USER 4, E: -13.7 cent
    m.write(syms["tn_user"], struct.pack(">96h", *user))
    call("tn_publish")
    poll(3)
    early = len(wlog) - n0
    settle()
    w7 = [s for s, _ in wlog[n0:]]
    want7 = (2, 2, 5, tuple(user))
    facts["2 a change in 7: nothing for two seconds, then one record in 7's sectors"] = (
        a7 == 7 and early == 0 and len(w7) == 1 and w7[0] in (TN_AT + 14, TN_AT + 15))

    # 3. LOAD 9: 12-TET; a change there: 9's record
    a9 = os_load(9)
    s9 = state()
    call("tn_set", 9, 0, 0x8000)               # POOLE ROD12, track 16
    n1 = len(wlog)
    settle()
    w9 = [s for s, _ in wlog[n1:]]
    facts["3 LOAD 9 (no record): 12-TET and nothing tuned; its change in 9's sectors"] = (
        a9 == 9 and s9[:3] == (0, 0, 0) and len(w9) == 1 and w9[0] in (TN_AT + 18, TN_AT + 19))

    # 4. LOAD 7: as it was, the interrupt's snapshot too
    os_load(7)
    fine, root, mask = snapshot()
    from dnfw.waverider import tunings as T     # noqa: PLC0415
    jm = [fine_of(t) for t in T.tenths(T.FACTORY[2][2])]
    facts["4 LOAD 7: its tuning, ROOT, tracks and USER slot; the interrupt's snapshot the same"] = (
        state() == want7 and fine == jm and root == 2 and mask == 5)

    # 5. a second change in 7: the other copy; corruption falls back
    first7 = w7[0]
    call("tn_set", 3, 2, 0x0005)               # PYTHAGOREAN
    n2 = len(wlog)
    settle()
    w7b = [s for s, _ in wlog[n2:]]
    other = w7b[0] if w7b else None
    alt = other is not None and other != first7 and other in (TN_AT + 14, TN_AT + 15)
    os_load(9)
    bad0 = i32("tn_bad")
    rec = bytearray(disk[other]) if other in disk else bytearray(512)
    rec[30] ^= 0x40
    disk[other] = bytes(rec)
    os_load(7)
    back = state()
    os_load(9)
    rec = bytearray(disk[first7])
    rec[25] ^= 0x01
    disk[first7] = bytes(rec)
    os_load(7)
    none = state()
    bad1 = i32("tn_bad")
    # a whole record, its check right, naming project 8, placed in 7's sectors: refused
    os_load(9)
    good9 = disk.get(w9[0])
    disk[first7] = good9                       # project 9's record (and sequence 1) in 7's place
    disk[other] = good9
    os_load(7)
    wrongp = state()
    facts["5 a second change: the other copy; it corrupted: the first; both: 12-TET; another project's: refused"] = (
        alt and back == want7 and none[:3] == (0, 0, 0) and bad1 >= bad0 + 2 and wrongp[:3] == (0, 0, 0))

    # 6. NEW in 9: 12-TET, 9's record replaced
    os_load(9)
    had9 = state()[:3] == (9, 0, 0x8000)
    n3 = len(wlog)
    a = os_new(9)
    after_new = state()
    settle()
    w_new = [s for s, _ in wlog[n3:]]
    os_load(7)
    os_load(9)
    facts["6 NEW in 9: 12-TET, its record replaced, LOAD 9 then 12-TET"] = (
        had9 and a == 9 and after_new[:3] == (0, 0, 0) and len(w_new) == 1
        and w_new[0] in (TN_AT + 18, TN_AT + 19) and state()[:3] == (0, 0, 0))

    # 7. a power cycle: the active project's tuning read back
    call("tn_set", 5, 7, 0x00F0)               # WERCKMEISTER3, ROOT G, tracks 5..8
    settle()
    m.write(syms["tn_user"], bytes(192))
    put("tn_cur", 0)
    put("tn_mask", 0)
    boot()
    facts["7 a power cycle: 9's tuning read back"] = state()[:3] == (5, 7, 0x00F0)

    # 8. ERASE MOD DATA's lock: nothing written
    lock = syms.get("smp_er_lock")
    n4 = len(wlog)
    if lock:
        m.write(lock, struct.pack(">i", 1))
    call("tn_set", 1, 0, 1)
    settle()
    locked = len(wlog) == n4
    if lock:
        m.write(lock, struct.pack(">i", 0))
    facts["8 ERASE MOD DATA's lock: nothing written"] = bool(lock) and locked

    # 9. every write in the region
    outside = [hex(s) for s, _ in wlog if not TN_AT <= s < TN_END]
    facts["9 every sector written lies in 0x6E0400..0x6E04FF"] = not outside and len(wlog) >= 5

    io.pop("log", None)
    return {"facts": facts, "ok": all(facts.values()), "writes": [hex(s) for s, _ in wlog],
            "outside": outside[:20], "tn_reads": i32("tn_reads"), "tn_writes": i32("tn_writes")}
