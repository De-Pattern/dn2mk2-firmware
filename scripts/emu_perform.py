"""v0.69, PERFORM's macros (csrc/sampler/perf.c, docs/perform.md) in the ColdFire emulator: the
`perform` scenario of `emu_waverider_menu.py`'s link16 step, with the +Drive played by Python (as
emu_tune.py: the OS's own LOAD and NEW run, pf_poll is called as the UI loop calls it, the UI's
clock moved on by hand).

What it checks (each a key of the result's "facts"):

1. power-on with no record: eight empty macros, PERF MUTE off, not one sector written;
2. the offset: a macro on track 1's parameter moves the modulated mirror cell by depth x value /
   127 (bipolar: / 64) on top of what was there, frame after frame without piling up; back to 0
   and PERF MUTE: the cell as it was; two macros on one cell add; the sound itself never written;
3. a change in project 7: nothing for two seconds, then one record in 7's own sectors;
4. LOAD 9 (no record): empty macros; LOAD 7: its macros as they were (targets, depth, value,
   BIPOLAR, name, mute);
5. a corrupted newer copy: the older one; both: empty; another project's record: refused;
6. NEW in 9: empty, and 9's record replaced;
7. a power cycle: the active project's macros read back;
8. ERASE MOD DATA's lock: nothing written;
9. every sector written lies in 0x6E0500..0x6E05FF;
10. (v0.70) the mirror's blocks are VOICES: with track 3 on voice 6 and track 8 on voice 3, a macro
    on track 3 moves voice 6's cell and leaves voice 3's (track 8's) alone; voice 6 gone to another
    track, its cell put back; voice 4 taking track 3, its cell moved. (v0.69 moved block t for track
    t: the wrong track, or nothing, Dubmaster's report.)
"""

from __future__ import annotations

import sys as _osport_sys, pathlib as _osport_pl  # noqa: E401
_osport_sys.path.insert(0, str(_osport_pl.Path(__file__).resolve().parents[1] / 'src'))
from dnfw.osport.os import A  # noqa: E402  (docs/os112-port.md)

import struct

ACTIVE = A(0x405CD899)
NOW = A(0x4058E8D4)
PJ_LOAD, PJ_GET_PROJECT = 0x40042E6E, A(0x4018A97A)
STUB_OPEN, STUB_TEMP = 0x40042B92, 0x40040190
NEW_SITE, NEW_AFTER = 0x40042AF0, 0x40042AFA
PF_AT, PF_END = 0x6E0500, 0x6E0600
MIRROR = 0x800068E4
VOICE_SOUND = 0x800052A8
VOICE_TRACK = 0x80005308
MACRO = 26                                      # sizeof(struct pf_macro): name 9, bip, val, 5 x (trk, slot, depth)


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

    def macros():
        raw = m.read(syms["pf"], 8 * MACRO)
        out = []
        for k in range(8):
            q = raw[MACRO * k:MACRO * (k + 1)]
            out.append((q[:9].split(b"\0")[0], q[9], struct.unpack(">b", q[10:11])[0],
                        tuple((q[11 + 3 * j], q[12 + 3 * j], struct.unpack(">b", q[13 + 3 * j:14 + 3 * j])[0])
                              for j in range(5))))
        return out, i32("pf_mute")

    empty = ([(b"", 0, 0, tuple((0xFF, 0, 0) for _ in range(5)))] * 8, 0)

    def set_macro(k, name, bip, val, targets):
        q = bytearray(MACRO)
        q[:len(name)] = name
        q[9] = bip
        q[10] = val & 0xFF
        for j in range(5):
            t = targets[j] if j < len(targets) else (0xFF, 0, 0)
            q[11 + 3 * j], q[12 + 3 * j], q[13 + 3 * j] = t[0], t[1], t[2] & 0xFF
        m.write(syms["pf"] + MACRO * k, bytes(q))

    def clock(dt):
        now = struct.unpack(">I", m.read(NOW, 4))[0]
        m.write(NOW, struct.pack(">I", (now + dt) & 0xFFFFFFFF))

    def poll(n=1):
        for _ in range(n):
            call("pf_poll")

    def changed():
        call("pf_publish")
        # as perf.c's changed(): dirty, its time now
        call("pf_mark")

    def settle():
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

    def boot():
        put("pf_owner", -2)
        poll(2)

    def cell(t, s):
        return struct.unpack(">H", m.read(MIRROR + 34 + 202 * t + 2 * s, 2))[0]

    def set_cell(t, s, v):
        m.write(MIRROR + 34 + 202 * t + 2 * s, struct.pack(">H", v))

    disk.clear()
    # 1. power-on, no record
    boot()
    facts["1 power-on, no record: eight empty macros, PERF MUTE off, nothing written"] = macros() == empty and not wlog

    # 2. the offset, on track 1's slot 20 (an LFO destination on every machine: the mirror's own cell)
    sound_ok = struct.unpack(">I", m.read(VOICE_SOUND, 4))[0] != 0
    T, S = 0, 20
    sound_before = m.read(struct.unpack(">I", m.read(VOICE_SOUND, 4))[0], 256) if sound_ok else b""
    set_cell(T, S, 0x2300)
    set_macro(0, b"", 0, 127, [(T, S, 30)])
    call("pf_publish")
    call("pf_apply")
    a1 = cell(T, S)
    call("pf_apply")
    a2 = cell(T, S)                            # stock did not rewrite: still +30, not +60
    set_cell(T, S, 0x1000)                     # stock rewrote it (an LFO moved): +30 on the new value
    call("pf_apply")
    a3 = cell(T, S)
    set_macro(1, b"", 1, -32, [(T, S, 20)])    # a second macro on the same cell, bipolar, half down
    call("pf_publish")
    call("pf_apply")
    a4 = cell(T, S)                            # 0x10 + 30 - 10
    put("pf_mute", 1)
    call("pf_publish")
    call("pf_apply")
    a5 = cell(T, S)                            # PERF MUTE: as it was
    put("pf_mute", 0)
    set_macro(0, b"", 0, 0, [(T, S, 30)])
    set_macro(1, b"", 1, 0, [(T, S, 20)])
    call("pf_publish")
    call("pf_apply")
    a6 = cell(T, S)                            # both at 0: as it was
    set_cell(T, S, 0x7000)
    set_macro(0, b"", 0, 127, [(T, S, 63)])
    call("pf_publish")
    call("pf_apply")
    a7 = cell(T, S)                            # clamped at the top
    set_macro(0, b"", 0, 0, [(0xFF, 0, 0)])
    set_macro(1, b"", 0, 0, [(0xFF, 0, 0)])
    call("pf_publish")
    call("pf_apply")
    a8 = cell(T, S)                            # the target gone: put back
    sound_after = m.read(struct.unpack(">I", m.read(VOICE_SOUND, 4))[0], 256) if sound_ok else b""
    facts["2 the offset: +depth x value / 127 on what was there, no piling up, two macros add, "
          "bipolar / 64, PERF MUTE and 0 put it back, clamped, the sound untouched"] = (
        sound_ok and a1 == 0x2300 + 30 * 256 and a2 == a1 and a3 == 0x1000 + 30 * 256
        and a4 == 0x1000 + (30 - 10) * 256 and a5 == 0x1000 and a6 == 0x1000 and a7 == 0x7FFF
        and a8 == 0x7000 and sound_before == sound_after)
    offsets = [hex(x) for x in (a1, a2, a3, a4, a5, a6, a7, a8)]

    # 10. voices, not tracks (v0.70): the voice -> track table set, every voice given a sound
    vt_saved, vs_saved = m.read(VOICE_TRACK, 64), m.read(VOICE_SOUND, 64)
    snd = struct.unpack(">I", m.read(VOICE_SOUND, 4))[0]
    m.write(VOICE_SOUND, struct.pack(">16I", *([snd] * 16)))

    def route(table):
        m.write(VOICE_TRACK, struct.pack(">16I", *[table.get(v, 15) for v in range(16)]))
    route({6: 2, 3: 7, 4: 9})
    for v in range(16):
        set_cell(v, S, 0x2000)
    set_macro(0, b"", 0, 127, [(2, S, 30)])
    set_macro(1, b"", 0, 0, [(0xFF, 0, 0)])
    call("pf_publish")
    call("pf_apply")
    r1 = [cell(v, S) for v in range(16)]
    route({4: 2, 6: 9, 3: 7})                 # voice 6 gone to track 10, voice 4 now plays track 3
    call("pf_apply")
    r2 = [cell(v, S) for v in range(16)]
    set_macro(0, b"", 0, 0, [(0xFF, 0, 0)])
    call("pf_publish")
    call("pf_apply")
    r3 = [cell(v, S) for v in range(16)]
    m.write(VOICE_TRACK, vt_saved)
    m.write(VOICE_SOUND, vs_saved)
    moved = 0x2000 + 30 * 256
    facts["10 voices, not tracks: track 3's macro moves the voice playing track 3 (voice 6), not voice 3 "
          "(track 8); voice 6 put back when it goes to another track, voice 4 moved when it takes "
          "track 3; the macro removed: every cell as it was"] = (
        r1[6] == moved and all(r1[v] == 0x2000 for v in range(16) if v != 6)
        and r2[4] == moved and r2[6] == 0x2000 and all(r2[v] == 0x2000 for v in range(16) if v != 4)
        and all(x == 0x2000 for x in r3))
    voices = {"r1": [hex(x) for x in r1], "r2": [hex(x) for x in r2], "r3": [hex(x) for x in r3]}
    boot()                                     # (back to the project's own, empty)

    # 3. a change in project 7
    a7p = os_load(7)
    n0 = len(wlog)
    want = (b"BIG DROP", 1, -12, ((2, 20, -40), (5, 24, 17), (0xFF, 0, 0), (0xFF, 0, 0), (0xFF, 0, 0)))
    set_macro(3, want[0], want[1], want[2], list(want[3]))
    changed()
    poll(3)
    early = len(wlog) - n0
    settle()
    w7 = [s for s, _ in wlog[n0:]]
    facts["3 a change in 7: nothing for two seconds, then one record in 7's sectors"] = (
        a7p == 7 and early == 0 and len(w7) == 1 and w7[0] in (PF_AT + 14, PF_AT + 15))

    # 4. LOAD 9: empty; LOAD 7: as it was
    a9 = os_load(9)
    e9 = macros()
    put("pf_mute", 1)
    changed()
    n1 = len(wlog)
    settle()
    w9 = [s for s, _ in wlog[n1:]]
    os_load(7)
    got = macros()
    facts["4 LOAD 9: empty (its change in 9's sectors); LOAD 7: its macros as they were"] = (
        a9 == 9 and e9 == empty and len(w9) == 1 and w9[0] in (PF_AT + 18, PF_AT + 19)
        and got[0][3] == want and got[1] == 0 and all(got[0][k] == empty[0][k] for k in (0, 1, 2, 4, 5, 6, 7)))

    # 5. corruption
    first7 = w7[0]
    set_macro(3, b"BIGGER", 0, 5, [(2, 20, -40)])
    changed()
    n2 = len(wlog)
    settle()
    w7b = [s for s, _ in wlog[n2:]]
    other = w7b[0] if w7b else None
    alt = other is not None and other != first7 and other in (PF_AT + 14, PF_AT + 15)
    os_load(9)
    bad0 = i32("pf_bad")
    rec = bytearray(disk[other]) if other in disk else bytearray(512)
    rec[30] ^= 0x40
    disk[other] = bytes(rec)
    os_load(7)
    back = macros()
    os_load(9)
    rec = bytearray(disk[first7])
    rec[25] ^= 0x01
    disk[first7] = bytes(rec)
    os_load(7)
    none = macros()
    bad1 = i32("pf_bad")
    os_load(9)
    good9 = disk.get(w9[0])
    disk[first7] = good9
    disk[other] = good9
    os_load(7)
    wrongp = macros()
    facts["5 a corrupted newer copy: the older; both: empty; another project's: refused"] = (
        alt and back[0][3] == want and none == empty and bad1 >= bad0 + 2 and wrongp == empty)

    # 6. NEW in 9
    os_load(9)
    had9 = macros()[1] == 1
    n3 = len(wlog)
    a = os_new(9)
    after_new = macros()
    settle()
    w_new = [s for s, _ in wlog[n3:]]
    os_load(7)
    os_load(9)
    facts["6 NEW in 9: empty, its record replaced, LOAD 9 then empty"] = (
        had9 and a == 9 and after_new == empty and len(w_new) == 1
        and w_new[0] in (PF_AT + 18, PF_AT + 19) and macros() == empty)

    # 7. a power cycle
    set_macro(0, b"PWR", 0, 99, [(1, 22, 9)])
    changed()
    settle()
    m.write(syms["pf"], bytes(8 * MACRO))
    boot()
    pw = macros()
    facts["7 a power cycle: 9's macros read back"] = pw[0][0][0] == b"PWR" and pw[0][0][2] == 99 and pw[0][0][3][0] == (1, 22, 9)

    # 8. ERASE MOD DATA's lock
    lock = syms.get("smp_er_lock")
    n4 = len(wlog)
    if lock:
        m.write(lock, struct.pack(">i", 1))
    set_macro(2, b"", 0, 1, [(0, 20, 1)])
    changed()
    settle()
    locked = len(wlog) == n4
    if lock:
        m.write(lock, struct.pack(">i", 0))
    facts["8 ERASE MOD DATA's lock: nothing written"] = bool(lock) and locked

    # 9. every write in the region
    outside = [hex(s) for s, _ in wlog if not PF_AT <= s < PF_END]
    facts["9 every sector written lies in 0x6E0500..0x6E05FF"] = not outside and len(wlog) >= 5

    io.pop("log", None)
    return {"facts": facts, "ok": all(facts.values()), "voices": voices, "writes": [hex(s) for s, _ in wlog],
            "outside": outside[:20], "offsets": offsets, "pf_reads": i32("pf_reads"), "pf_writes": i32("pf_writes")}
