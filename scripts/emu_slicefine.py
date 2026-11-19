"""v0.62, the slice editor's requests (impbox, Discord 2026-11-17): the `slicefine` scenario of
`emu_waverider_menu.py`'s link16 step, the +Drive and the DSP played by Python. The editor is
driven through slc_pop (the UI queue's items) and slc_poll (each UI pass), as slicebusy drives it.

The sample: 120,000 int16 frames of a tone 100 frames a period (its zero crossings known), in
slot 0 with four even slices; the active track a SLICE track on it, SLCE at NOTE.

What it checks (each a key of "facts"):

1. live: an edit (START turned) is not sent while the knobs move (the next pass, the clock
   unmoved), then, 0.2 s after, sent: the DSP's slice area and the +Drive's table are the editor's,
   and once only;
2. FUNC + END: the end lands on a zero crossing (its frame and the one before of opposite sign),
   the next slice's start with it (linked); END turned without FUNC: no snap (negative control);
3. deep zoom: ZOOM all the way: the view 128 frames at most a 2nd of that (zmax), the view's own
   frames read, each column's lowest and highest those of the sample there; back to zoom 0: no
   read (the fine waveform's view);
4. follow: a note on a voice of the editor's track picks slice (note - 24) mod 4; a note on a
   voice of another track, or with SLCE a fixed slice, picks nothing (negative controls);
5. NO closes the editor, the table on the +Drive the editor's last;
6. CREATE SLICE GRID (Wolljamin, Discord 2026-11-19): FUNC + E jumps SLICES through 2, 4, 8, 16,
   32, 64, a detent a jump, from between stops to the next; E alone moves one (negative control).
"""

from __future__ import annotations

import math
import struct

NOW = 0x4058E8D4
VOICE_TRACK, CTL_FRAME = 0x80005308, 0x80005E60
STORE_SECTOR = 0x600000


def run(cx):
    m, call, long, period = cx["machine"], cx["call"], cx["long"], cx["period"]
    disk, syms, SL, SM, base = cx["disk"], cx["syms"], cx["SL"], cx["SM"], cx["base"]
    pool, d0, item = cx["pool"], cx["returned_d0"], cx["item"]
    facts = {}

    def i32(name):
        return struct.unpack(">i", m.read(syms[name], 4))[0]

    def put(name, v):
        m.write(syms[name], struct.pack(">i", v))

    # -- the sample: a tone 100 frames a period, in slot 0 ----------------------------------
    n = 120000
    snd = [0.6 * math.sin(2 * math.pi * (k + 0.37) / 100) for k in range(n)]
    img = SL.pool_bytes([snd], base, [1.0], [SM.FMT_I16], ["TONE"])
    img = bytearray(img + bytes((-len(img)) % 512))
    hdr_dir = bytes(img[:SM.DATA_OFFSET])

    def adler(b):
        a_, b_ = 1, 0
        for x in b:
            a_ = (a_ + x) & 0xFFFFFFFF
            b_ = (b_ + a_) & 0xFFFFFFFF
        return (b_ << 16 ^ a_) & 0xFFFFFFFF
    magic, nbytes, ck = 0x444E3251, len(img), adler(hdr_dir)
    disk[STORE_SECTOR] = struct.pack(">5I", magic, 2, nbytes, ck, (~magic ^ nbytes ^ ck) & 0xFFFFFFFF).ljust(512, b"\0")
    for k in range(len(img) // 512):
        disk[STORE_SECTOR + 1 + k] = bytes(img[512 * k:512 * k + 512])
    for _ in range(3000):
        period()
        call("smp_boot")
        if long("smp_lstate") == 4:
            break
    loaded = long("smp_lstate") == 4

    def frames_on_disk():
        addr, fr = struct.unpack("<II", m.read(SM.MIRROR + 8, 8))
        lo = addr - base
        raw = b"".join(disk.get(STORE_SECTOR + 1 + (lo >> 9) + k, bytes(512))
                       for k in range((fr * 2 + (lo & 511) + 511) // 512))[lo & 511:(lo & 511) + 2 * fr]
        return list(struct.unpack(f"<{fr}h", raw))
    data = frames_on_disk()
    q = n // 4
    table = []
    for k in range(4):
        table += [k * q, (k + 1) * q, k * q]
    buf = cx["scratch"]
    m.write(buf, struct.pack(">12I", *table))
    call("smp_slices_set", 0, buf, 4)
    for _ in range(600):
        period()
        call("smp_boot")
        if long("smp_lstate") == 4 and all(pool.get(SM.SLICE_AREA // 4 + j) == table[j] for j in range(12)):
            break

    # -- the track: a SLICE track on SAMP 1 (slot 0), SLCE at NOTE ---------------------------
    kit = struct.unpack(">I", m.read(0x800052A0, 4))[0]
    trk = m.read(0x42431A6C, 1)[0] & 15
    snd_ = kit + 52 + 1163 * trk

    def set_rec(rid, value):
        r = struct.unpack(">3i", m.read(0x401F7F94 + 60 * rid, 12))
        m.write(snd_ + 20 + 2 * r[1], struct.pack(">H", (value + (r[2] >> 8)) << 8))
    m.write(snd_ + 0xDE, bytes([13]))
    set_rec(SM.SAMP_REC, 1)
    set_rec(SM.SLICE_REC, 0)

    def pop(kind, code, v):
        it = bytearray(12)
        it[0] = kind
        struct.pack_into(">I", it, 4, code)
        if kind == 1:
            it[8] = v & 0xFF
        else:
            struct.pack_into(">I", it, 8, v)
        m.write(item, bytes(it))
        call("slc_pop", item)

    def key(code):
        pop(0, code, 0x01)
        pop(0, code, 0x10)

    def knob(code, dd):
        pop(1, code, dd)

    def ui_pass():
        period()
        call("smp_boot")
        call("slc_poll")

    def clock(dt):
        now = struct.unpack(">I", m.read(NOW, 4))[0]
        m.write(NOW, struct.pack(">I", (now + dt) & 0xFFFFFFFF))

    def sl():
        return list(struct.unpack(">12I", m.read(syms["slc_sl"], 48)))

    m.write(syms["slc_page_seen"], struct.pack(">i", 1))
    m.write(syms["slc_seen_draw"], m.read(syms["wr_draws"], 4))
    m.write(syms["slc_open_track"], struct.pack(">I", trk))
    m.write(syms["slc_stock_asked"], bytes(4))
    put("smp_func_held", 0)
    dbg = {}
    call("smp_slot_frames", 0, 0)
    dbg["frames0"] = d0()
    dbg["page_seen"] = long("slc_page_seen")
    dbg["type"] = m.read(snd_ + 0xDE, 1)[0]
    key(10)                                     # the SLICE menu
    st_menu = long("slc_state")
    dbg["page_seen_after"] = long("slc_page_seen")
    key(10)                                     # EDIT SLICE POINTS
    st_after = long("slc_state")
    for _ in range(1500):
        if long("slc_state") != 3:
            break
        ui_pass()
    opened = long("slc_state") == 4 and long("slc_ns") == 4 and sl() == table
    facts["0 the editor open on the four slices"] = loaded and opened

    # 1. live
    sends0 = long("slc_live_sends")
    knob(5, 3)                                  # START of slice 1, three steps on
    after_turn = sl()
    ui_pass()
    early = long("slc_live_sends") - sends0
    clock(500)
    for _ in range(2):
        ui_pass()
    for _ in range(600):
        period()
        call("smp_boot")
        if long("smp_lstate") == 4 and all(pool.get(SM.SLICE_AREA // 4 + j) == after_turn[j] for j in range(12)):
            break
    m.write(buf, bytes(48))
    call("smp_slices_get", 0, buf)
    got = list(struct.unpack(">12I", m.read(buf, 48)))
    dsp_area = [pool.get(SM.SLICE_AREA // 4 + j) for j in range(12)]
    facts["1 live: not sent while turning; 0.2 s after, the DSP's and the +Drive's table the editor's, once"] = (
        after_turn[0] > table[0] and early == 0 and long("slc_live_sends") - sends0 == 1
        and got == after_turn and dsp_area == after_turn)

    # 2. FUNC + END: a zero crossing, the next start with it; without FUNC no snap
    snaps0 = long("slc_snaps")
    knob(8, 1)                                  # END without FUNC
    plain = sl()
    no_snap = long("slc_snaps") == snaps0
    put("smp_func_held", 1)
    knob(8, 1)
    put("smp_func_held", 0)
    snapped = sl()
    e = snapped[1]

    def crossing(f):
        return 0 < f < len(data) and (data[f - 1] < 0) != (data[f] < 0)
    facts["2 FUNC + END: on a zero crossing, the next start with it; END alone: no snap"] = (
        no_snap and not crossing(plain[1]) and long("slc_snaps") == snaps0 + 1 and crossing(e)
        and snapped[3] == e and abs(e - (plain[1] + n // 128)) <= 512)

    # 3. deep zoom: the view's own frames
    reads0 = long("slc_fine_views")
    for _ in range(4):
        knob(6, 8)
    for _ in range(300):                        # (a read waits for the link to be idle)
        ui_pass()
        if long("slc_fv_n") and long("slc_fine_views") > reads0:
            break
    v0 = long("slc_view0")
    fv = long("slc_fv_n")
    zmax = 0
    while (n >> (zmax + 1)) >= 128:
        zmax += 1
    want_n = n >> zmax
    lo = list(struct.unpack(">126i", m.read(syms["slc_fv_lo"], 504)))
    hi = list(struct.unpack(">126i", m.read(syms["slc_fv_hi"], 504)))
    wlo, whi = [], []
    for x in range(126):
        a, b = x * want_n // 126, max((x + 1) * want_n // 126, x * want_n // 126 + 1)
        seg = data[v0 + a:v0 + min(b, want_n)]
        wlo.append(min(seg) if seg else None)
        whi.append(max(seg) if seg else None)
    read_deep = long("slc_fine_views") - reads0
    for _ in range(4):
        knob(6, -8)
    ui_pass()
    ui_pass()
    facts["3 deep zoom: the view 128..255 frames, its own frames read, each column the sample's lowest and highest; zoom 0: no read"] = (
        fv == want_n and 128 <= fv < 256 and read_deep == 1 and lo == wlo and hi == whi
        and long("slc_fine_views") - reads0 == 1)

    # 4. follow: a played note picks its slice
    vt_stock = m.read(VOICE_TRACK, 64)           # put back after: stock's frame builder derives the
    vt = [0xFF] * 16                            # DSP's routing words from it (the runner checks those)
    vt[3], vt[4] = trk, (trk + 1) % 16

    def play(v, note):
        m.write(VOICE_TRACK, struct.pack(">16I", *vt))
        m.write(CTL_FRAME + 2 + 2 * v, struct.pack(">H", note << 8))
        call("slc_poll")
        return long("slc_cur")
    m.write(VOICE_TRACK, struct.pack(">16I", *vt))
    call("slc_poll")
    c1 = play(3, 24 + 2)
    c2 = play(3, 24 + 5)
    c3 = play(4, 24 + 3)                        # another track's voice
    set_rec(SM.SLICE_REC, 10)                   # SLCE a fixed slice
    c4 = play(3, 24 + 3)
    set_rec(SM.SLICE_REC, 0)
    m.write(VOICE_TRACK, vt_stock)
    facts["4 follow: a note on the track's voice picks (note - 24) mod 4; another track's or a fixed SLCE: nothing"] = (
        c1 == 2 and c2 == 1 and c3 == 1 and c4 == 1)

    # 5. NO closes, the table on the +Drive the editor's last
    last = sl()
    key(12)
    sec = SM.SLICE_AREA // 512
    for _ in range(1500):
        period()
        call("smp_boot")
        if long("smp_lstate") == 4 and list(struct.unpack(
                "<12I", disk.get(STORE_SECTOR + 1 + sec, bytes(512))[:48])) == last:
            break
    m.write(buf, bytes(48))
    call("smp_slices_get", 0, buf)
    got = list(struct.unpack(">12I", m.read(buf, 48)))
    on_disk = list(struct.unpack("<12I", disk.get(STORE_SECTOR + 1 + sec, bytes(512))[:48]))
    facts["5 NO closes; the table kept and on the +Drive the editor's last"] = (
        long("slc_state") == 0 and got == last and on_disk == last)
    # 6. CREATE SLICE GRID: FUNC + E jumps 2/4/8/16/32/64 (Wolljamin); E alone steps by one
    put("slc_state", 2)                         # S_GRID
    put("slc_grid_n", 13)
    put("smp_func_held", 1)
    gj = []
    for dd in (1, 1, -1, -1, -1, -1, -1, 5, 1):
        knob(5, dd)
        gj.append(long("slc_grid_n"))
    put("smp_func_held", 0)
    knob(5, -1)
    gj.append(long("slc_grid_n"))
    knob(5, 1)
    gj.append(long("slc_grid_n"))
    put("slc_state", 0)
    put("slc_grid_n", 16)
    facts["6 CREATE SLICE GRID: FUNC + E jumps 2/4/8/16/32/64; E alone one at a time"] = (
        gj == [16, 32, 16, 8, 4, 2, 2, 64, 64, 63, 64] and long("slc_grid_jumps") == 9)
    return {"facts": facts, "ok": all(facts.values()),
            "detail": {"grid_jumps": gj, "after_turn": after_turn, "snapped": snapped, "plain": plain, "fv": fv, "want_n": want_n,
                       "v0": v0, "last": last, "on_disk": on_disk, "got5": got, "follow": [c1, c2, c3, c4], "reads_deep": read_deep, "loaded": loaded,
                       "st_menu": st_menu, "st_after": st_after, "ns": long("slc_ns"), "fails": long("slc_fails"), "dbg": dbg}}
