"""v0.40: the +Drive library's folders inside folders over the sample link, on the ColdFire
emulator (scripts/emu_waverider_menu.py's link16 `nest` scenario; the gate's `link16` step).

csrc/sampler/lib.c keeps a folder's parent in its 32-byte record's last byte (0 before v0.40,
so every older library is all top-level folders), link 17's name is a path ("A/B/C"), 30 makes
a folder inside one, 31 reads the tree. Checked here, against a Python +Drive that logs every
write:

- an old (v0.39) library, its import's flat "TRANCE STARTER PACK/KICKS" folders included, reads
  as it did: every folder at the top, every sample where it was, nothing written by reading;
- link 17's path makes each level once (again: the same folder, nothing written); 30 inside a
  folder; look-alike names at different levels are different folders, and a top-level name
  finds the top-level folder; past six levels nothing deeper is made (17: the sixth level is
  the answer; 30: the parent, flagged); a sample sent into the third level is listed there;
- DROP refuses a folder with a folder inside it; each folder change writes one sector, the
  record's; the tree read back from the +Drive as at power-on is the same;
- a power cut after every sector written (making the tree, then a DELETE of the pack's folder
  with all inside it, through the browser's own smp_fb_delete) leaves a library that reads as a
  tree: every folder's parent named, no loop, six deep at most, the old library's samples in
  their folders, every sample listed in a folder that is there;
- a v0.39 reading the result sees each folder by its own name (the tag never in a name);
- at every one of those points the firmware's tree is dnfw.sampler.libtree's of the records.
"""

from __future__ import annotations

import struct

from dnfw.sampler import libtree

LIB = 0x700000
LIB_INDEX = LIB + 1
LIB_FOLD = LIB + 1 + 256
LIB_DATA = LIB_FOLD + 4
DEPTH = 6
# v0.43: folders 64..127 (csrc/sampler/lib.c LIB_HI_AT): a header, then four sectors of records,
# which count only when the header checks (as the firmware's hi_read takes them)
LIB_HI_AT = 0x6FF800
LIB_HI_MAGIC = 0x444E3246


def folder_table(state):
    """-> the 128 folder records as the firmware reads them at power-on from `state`."""
    lo = b"".join(state.get(LIB_FOLD + k, bytes(512)) for k in range(4))
    h = state.get(LIB_HI_AT, bytes(512))
    w = struct.unpack(">4I", h[:16])
    ok = (w[0] == LIB_HI_MAGIC and w[1] == 1 and w[2] == libtree.FOLDERS
          and w[3] == (~w[0] ^ w[1] ^ w[2] ^ 0x3CC35AA5) & 0xFFFFFFFF)
    hi = b"".join(state.get(LIB_HI_AT + 1 + k, bytes(512)) for k in range(4)) if ok else bytes(2048)
    return lo + hi


def adler(b, s=1):
    a_, b_ = s & 0xFFFF, s >> 16
    for x in b:
        a_ = (a_ + x) % 65521
        b_ = (b_ + a_) % 65521
    return b_ << 16 | a_


def entry(start, frames, folder, name, frames_sum):
    e = bytearray(64)
    struct.pack_into("<III", e, 0, start, frames, 0x3F800000)
    e[12], e[13] = 1, folder
    struct.pack_into("<I", e, 16, frames_sum)
    struct.pack_into("<I", e, 20, (frames * 2 + 511) // 512)
    e[24:24 + len(name)] = name.encode()
    struct.pack_into("<I", e, 60, adler(bytes(e[:60])) ^ 0x4C494245)
    return bytes(e)


def old_library(disk):
    """a library as v0.31..v0.39 wrote it, v0.39's import's flat path folders in it"""
    sb = struct.pack(">4I", 0x444E324C, 1, 2048, (~0x444E324C ^ 1 ^ 2048 ^ 0x5AA5C33C) & 0xFFFFFFFF)
    disk[LIB] = sb.ljust(512, b"\0")
    folders = ["INCOMING", "RECORDED", "TRANCE STARTER PACK/KICKS", "TRANCE STARTER PACK/LEADS", "DRUMS"]
    ft = bytearray(4 * 512)
    for f, nm in enumerate(folders):
        ft[32 * f:32 * f + len(nm)] = nm.encode()
    for k in range(4):
        disk[LIB_FOLD + k] = bytes(ft[512 * k:512 * k + 512])
    idx = bytearray(256 * 512)
    samples = [("OLD KICK", 2, 700), ("OLD LEAD", 3, 900), ("SNARE", 4, 500)]
    at = LIB_DATA
    for k, (nm, f, fr) in enumerate(samples):
        data = bytes((k * 31 + j * 7) & 0xFF for j in range(2 * fr))
        for s in range((len(data) + 511) // 512):
            disk[at + s] = data[512 * s:512 * s + 512].ljust(512, b"\0")
        idx[64 * k:64 * k + 64] = entry(at, fr, f, nm, adler(data))
        at += (len(data) + 511) // 512
    for k in range(256):
        if any(idx[512 * k:512 * k + 512]):
            disk[LIB_INDEX + k] = bytes(idx[512 * k:512 * k + 512])
    return folders, samples


def run(cx):
    m, call, long, period = cx["machine"], cx["call"], cx["long"], cx["period"]
    disk, io, syms, uc, K = cx["disk"], cx["io"], cx["syms"], cx["uc"], cx["K"]
    pack7, unpack7, hook_code = cx["pack7"], cx["unpack7"], cx["UC_HOOK_CODE"]
    buf = cx["scratch"]
    facts, notes = {}, {}
    replies = []

    def at_sender(uc_, address, size, user):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        b, n, _ab, _port = struct.unpack(">4I", bytes(uc.mem_read(sp + 4, 16)))
        replies.append(bytes(uc.mem_read(b, n)))
    hs = uc.hook_add(hook_code, at_sender, begin=cx["sender"], end=cx["sender"])

    def sx(cmd, payload=b""):
        msg = bytes([0xF0, 0, 0x20, 0x3C, 0x7D, 1]) + pack7(struct.pack(">HB", 7, cmd) + payload) + b"\xF7"
        m.write(buf, msg)
        replies.clear()
        call("smp_rx", buf, len(msg), 2)
        if not replies:
            return None, b""
        r = unpack7(replies[-1][6:-1])
        return r[3], bytes(r[4:])

    def boot():
        """as at power-on: the library read again from the +Drive"""
        m.write(syms["smp_lib_state"], bytes(4))
        st, info = sx(16)
        return st == 0 and info and struct.unpack_from("<I", info)[0] == 2

    def tree():
        # v0.43: 128 folders, TREE a page of 64 at a time (rq[3] the first folder)
        st, r = sx(31, bytes([0]))
        st2, r2 = sx(31, bytes([64]))
        if st or st2 or len(r) < 65 or len(r2) < 65:
            return None, None
        return r[0], list(r[1:65]) + list(r2[1:65])

    def names(n=128):
        out = []
        for f0 in range(0, n, 4):
            _, p = sx(23, bytes([f0]))
            out += [p[24 * j:24 * j + 24].split(b"\0")[0].decode("ascii", "replace") for j in range(4)]
        return out

    def listing(upto=16):
        rows = []
        for k0 in range(0, upto, 4):
            _, p = sx(21, struct.pack("<H", k0))
            for j in range(4):
                o = 4 + 31 * j
                k, fr, fo = struct.unpack_from("<HIB", p, o)
                if fo != 0xFF:
                    rows.append((k, p[o + 7:o + 31].split(b"\0")[0].decode(), fo, fr))
        return rows

    def folder_in(parent, name):
        st, r = sx(30, bytes([0xFF if parent is None else parent]) + name.encode())
        return (r[0], r[1]) if st == 0 and len(r) >= 2 else (None, None)

    def path_of(f, par, nm):
        p, seen = [], 0
        while f is not None and f != 0xFF and seen < 10:
            p.append(nm[f])
            f, seen = par[f], seen + 1
        return "/".join(reversed(p))

    def sound(par, nm):
        """the tree reads as a tree: parents named, no loop, six deep at most"""
        for f in range(len(par)):
            if par[f] == 0xFF:
                continue
            if par[f] >= len(par) or not nm[par[f]] or not nm[f]:
                return False
            g, d = f, 1
            while par[g] != 0xFF and d <= DEPTH:
                g, d = par[g], d + 1
            if par[g] != 0xFF or d > DEPTH:
                return False
        return True

    def send(name, folder, data):
        frames = len(data) // 2
        st, r = sx(18, struct.pack("<IBBI", frames, 1, folder, 0x3F800000) + name.encode())
        if st != 0:
            return None
        k, _at = struct.unpack_from("<II", r)
        for o in range(0, len(data), 300):
            st, _ = sx(19, struct.pack("<I", o) + data[o:o + 300])
            if st != 0:
                return None
        st, _ = sx(20, struct.pack("<I", adler(data)))
        return k if st == 0 else None

    disk.clear()
    io.pop("errors", None)
    old_f, old_s = old_library(disk)
    disk0 = dict(disk)
    wlog = []
    io["log"] = wlog
    # -- 1. an old library reads as it did ----------------------------------------------------
    ok_boot = boot()
    dep, par = tree()
    nm = names()
    rows = listing()
    facts["an old (v0.39) library: every folder at the top, named as it was"] = (
        ok_boot and dep == DEPTH and par is not None and all(p == 0xFF for p in par)
        and nm[:5] == [n[:24] for n in old_f])
    facts["its samples where they were"] = sorted((n, f) for _, n, f, _ in rows) == sorted((n, f) for n, f, _ in old_s)
    facts["nothing written by reading it"] = not wlog and disk == disk0
    # -- 2. a path through link 17, folders inside folders through 30 -------------------------
    T = "TRANCE STARTER PACK"
    n0 = len(wlog)
    st, r = sx(17, f"{T}/KICKS".encode())
    kicks = r[0] if st == 0 and r else None
    w17 = wlog[n0:]
    dep, par = tree()
    nm = names()
    tsp = par[kicks] if kicks is not None else None
    facts["17 'TRANCE STARTER PACK/KICKS': KICKS inside a new top-level TRANCE STARTER PACK"] = (
        kicks is not None and tsp not in (None, 0xFF) and nm[kicks] == "KICKS" and nm[tsp] == T
        and par[tsp] == 0xFF and kicks not in (2, 3) and tsp not in (2, 3))
    facts["the old flat folders untouched, still at the top"] = nm[2:4] == [n[:24] for n in old_f[2:4]] and par[2] == par[3] == 0xFF
    facts["each level one sector written, its record's"] = (
        len(w17) == 2 and all(s == LIB_FOLD + f // 16 and len(d) == 512 for (s, d), f in zip(w17, (tsp, kicks))))
    n0 = len(wlog)
    st, r = sx(17, f"{T} / KICKS".encode())
    facts["the same path again: the same folder, nothing written"] = st == 0 and r[:1] == bytes([kicks]) and len(wlog) == n0
    leads, fl1 = folder_in(tsp, "LEADS")
    leads2, fl2 = folder_in(tsp, "LEADS")
    f808, _ = folder_in(kicks, "808")
    look, _ = folder_in(f808, T)
    st, r = sx(17, T.encode())
    top_t = r[0] if st == 0 and r else None
    st, r = sx(17, b"KICKS")
    top_k = r[0] if st == 0 and r else None
    dep, par = tree()
    nm = names()
    facts["30 inside a folder: made (flag 1), then found (flag 0)"] = (
        leads is not None and leads == leads2 and fl1 == 1 and fl2 == 0 and par[leads] == tsp)
    facts["look-alikes at other levels are other folders; a top-level name finds the top-level one"] = (
        None not in (f808, look, top_t, top_k) and par[f808] == kicks and par[look] == f808 and nm[look] == T
        and look != tsp and top_t == tsp and top_k not in (kicks, leads, f808, look) and par[top_k] == 0xFF)
    # depth: 808 is level 3, its look-alike 4; 5 and 6 made, 7 is not (30: the parent, flag 2)
    d5, _ = folder_in(look, "D5")
    d6, _ = folder_in(d5, "D6")
    d7, fl7 = folder_in(d6, "D7")
    nmade = len(wlog)
    st, r = sx(17, b"A/B/C/D/E/F/G/H")
    deep = r[0] if st == 0 and r else None
    dep, par = tree()
    nm = names()
    facts["six levels deep at most: 30 past it gives the parent back (flag 2)"] = (
        None not in (d5, d6) and par[d6] == d5 and d7 == d6 and fl7 == 2 and "D7" not in nm)
    facts["17 past six levels: the sixth is the answer, nothing deeper made"] = (
        deep is not None and nm[deep] == "F" and path_of(deep, par, nm) == "A/B/C/D/E/F"
        and "G" not in nm and "H" not in nm and len(wlog) - nmade == 6)
    facts["the tree as read is sound"] = sound(par, nm)
    # a sample into the third level
    data = bytes((j * 13 + 5) & 0xFF for j in range(1600))
    k808 = send("808 A", f808, data)
    rows = listing()
    facts["a sample sent into the third level is listed there"] = (
        k808 is not None and any(k == k808 and n == "808 A" and f == f808 for k, n, f, _ in rows))
    # DROP: refused with a folder inside; an empty leaf goes
    st_t, _ = sx(26, bytes([tsp]))
    st_l, _ = sx(26, bytes([leads]))
    dep, par = tree()
    nm = names()
    facts["DROP refuses a folder with a folder inside it; an empty leaf goes"] = (
        st_t != 0 and nm[tsp] == T and st_l == 0 and nm[leads] == "")
    # read back as at power-on
    before = (par, nm, sorted(listing()))
    facts["read back from the +Drive as at power-on: the same tree, names, samples"] = (
        boot() and (tree()[1], names(), sorted(listing())) == before)
    made_log = list(wlog)
    final = dict(disk)
    # -- 3. a power cut after every sector written ------------------------------------------
    def cut_ok(state, want_samples):
        disk.clear()
        disk.update(state)
        if not boot():
            return False, "no boot"
        d_, p_ = tree()
        n_ = names()
        rs = listing()
        if p_ is None or not sound(p_, n_):
            return False, "tree"
        ft = folder_table(state)                       # v0.43: and folders 64..127
        if [-1 if x == 0xFF else x for x in p_] != libtree.tree(ft):
            return False, "not the model's tree (dnfw.sampler.libtree)"
        if not all(any(n == sn and f == sf for _, n, f, _ in rs) and p_[sf] == 0xFF and n_[sf]
                   for sn, sf, _ in old_s):
            return False, "old samples"
        if not all(n_[f] or f in (0, 1) for _, _, f, _ in rs):
            return False, "a sample in a folder not there"
        if not want_samples(rs):
            return False, "samples"
        return True, ""
    bad = []
    state = dict(disk0)
    for i in range(len(made_log) + 1):
        if i:
            s, d = made_log[i - 1]
            for j in range(len(d) // 512):
                state[s + j] = d[512 * j:512 * j + 512]
        good, why = cut_ok(state, lambda rs: len(rs) in (3, 4))
        if not good:
            bad.append((i, why))
    facts[f"a power cut after each of the {len(made_log)} sectors making it: a sound tree, nothing lost"] = not bad
    notes["cuts_making"] = bad[:5]
    # -- 4. DELETE on the pack's folder (the browser's own: smp_fb_delete), cut after each ----
    disk.clear()
    disk.update(final)
    boot()
    n0 = len(wlog)
    m.write(syms["smp_fb_store"], struct.pack(">i", 1))
    m.write(syms["smp_fb_folder"], struct.pack(">i", -1))
    call("smp_fb_delete", 0xFFFFFFFF, tsp)
    m.write(syms["smp_fb_store"], struct.pack(">i", -1))
    del_log = wlog[n0:]
    after = dict(disk)
    dep, par = tree()
    nm = names()
    rows = listing()
    under = [f for f in (tsp, kicks, f808, look, d5, d6)]
    facts["DELETE on the pack: it and every folder inside gone, its sample too"] = (
        all(nm[f] == "" for f in under) and not any(n == "808 A" for _, n, _, _ in rows))
    facts["the rest untouched: the old flat folders, A/../F, their samples"] = (
        nm[2:5] == [n[:24] for n in old_f[2:5]] and nm[deep] == "F"
        and sorted((n, f) for _, n, f, _ in rows) == sorted((n, f) for n, f, _ in old_s))
    facts["samples first, then folders deepest first (each one sector)"] = (
        bool(del_log) and all(s < LIB_FOLD for s, _ in del_log[:1])
        and all(s >= LIB_FOLD for s, _ in del_log[1:]) and len(del_log) == 1 + 6)
    bad = []
    state = dict(final)
    for i in range(len(del_log) + 1):
        if i:
            s, d = del_log[i - 1]
            for j in range(len(d) // 512):
                state[s + j] = d[512 * j:512 * j + 512]
        good, why = cut_ok(state, lambda rs: len(rs) in (3, 4))
        if not good:
            bad.append((i, why))
    facts[f"a power cut after each of the DELETE's {len(del_log)} sectors: a sound tree, nothing else lost"] = not bad
    notes["cuts_delete"] = bad[:5]
    # -- 5. what a v0.39 reads of it: each folder by its own name --------------------------
    disk.clear()
    disk.update(final)
    ft = b"".join(disk.get(LIB_FOLD + k, bytes(512)) for k in range(4))
    old_names = [ft[32 * f:32 * f + 32].split(b"\0")[0].decode("ascii", "replace") for f in range(64)]
    boot()
    dep, par = tree()
    nm = names()
    facts["a v0.39 reading it sees each folder by its own name (the tag never in a name)"] = (
        all(old_names[f][:24] == nm[f] for f in range(64)) and old_names[kicks] == "KICKS" and old_names[look] == T)
    # -- 6. v0.43 (Wolljamin: "command 30: refused", the 64 folders full): 128 folders, 64..127
    # in their own sectors below the library (a header, then four sectors), written only once
    # a folder past 63 is made; their parents kept; the 129th refused; all read back at boot
    disk.clear()
    disk.update(final)
    boot()
    st, info = sx(16)
    facts["v0.43: INFO says 128 folders"] = st == 0 and len(info) >= 24 and struct.unpack_from("<I", info, 20)[0] == 128
    HI = 0x6FF800
    io["log"] = []
    made = []
    for k in range(140):
        f, fl = folder_in(None, f"TOP{k:03d}")
        if f is None:
            break
        made.append(f)
    hi_writes = [s_ for s_, _d in io["log"] if HI <= s_ < HI + 5]
    facts["v0.43: folders made up to 128, the next refused"] = len(made) >= 64 and max(made) == 127 and len(set(made)) == len(made)
    facts["v0.43: folders past 63 written to their own sectors (and nowhere in the stock's or the frames' area)"] = (
        bool(hi_writes) and all(s_ >= HI and (s_ < HI + 5 or s_ >= LIB) for s_, _d in io["log"]))
    # a folder inside one past 63, and one past 63 inside one under 64: drop two first to make room
    drop_a, drop_b = made[-1], made[-2]
    sx(26, bytes([drop_a]))
    sx(26, bytes([drop_b]))
    inner, _fl = folder_in(100, "IN100")
    deeper, _fl = folder_in(inner, "DEEPER") if inner is not None else (None, None)
    want_names = names(128)
    boot()                                       # as at power-on: everything read again
    nm128 = names(128)
    pars = []
    for f0 in (0, 64):
        st, r = sx(31, bytes([f0]))
        pars += list(r[1:65]) if st == 0 and len(r) >= 65 else [None] * 64
    facts["v0.43: after a reboot every folder's name the same, 128 of them"] = (
        nm128 == want_names and sum(1 for n in nm128 if n) >= 126 and nm128[127 if 127 not in (drop_a, drop_b) else 100] != "")
    facts["v0.43: parents past 63 kept (IN100 inside 100, DEEPER inside it)"] = (
        inner is not None and deeper is not None and pars[inner] == 100 and pars[deeper] == inner)
    notes["v043"] = {"made": len(made), "hi_writes": len(hi_writes), "inner": inner, "deeper": deeper,
                     "pars": [pars[x] for x in (inner, deeper) if x is not None]}
    disk.clear()
    disk.update(after)
    io.pop("log", None)
    uc.hook_del(hs)
    notes.update(writes_making=len(made_log), writes_delete=len(del_log), errors=io.get("errors"))
    return {"ok": all(facts.values()), "facts": facts, "notes": notes}
