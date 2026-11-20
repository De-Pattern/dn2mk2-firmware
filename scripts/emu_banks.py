"""v0.65 PROJECT RAM banks in the ColdFire emulator (csrc/sampler/link.c, banks.h; docs/banks.md):
the `banks` scenario of `emu_waverider_menu.py`'s link16 step, with the +Drive and the DSP played
by Python as link16's other scenarios.

What it checks (each a key of the result's "facts"):

1. power-on: an image with two samples in bank A and one in bank B's page (slot 4), its header
   naming the page (words 5..9): bank A plays as before; B's slot 4 plays from B's page on the
   DSP's own rule (dnfw.sampler.live.slot_plays with the bank), its frames the image's; bank A's
   slot 4 does not; banks C and D are live and empty (their pages sent, count 0);
2. the ColdFire's view: smp_bank_live, smp_bank_count, smp_name of global slot 132 ("BSND");
3. the list's rows (smp_word_row / smp_row_word / smp_row_step, the code the knob and the list
   run): A127 + 1 is B001, B001 - 1 is A127, A001's row is 1, B005's word is 0x0540;
4. an edit in bank B (smp_discard of B005): the page's entry empty on the +Drive and in the DSP,
   the header's word for B the page's new checksum;
5. LOAD TO PROJECT with the list on bank B: the library sample goes into B001 (B's first empty
   slot), plays from B's page, B's count covers it, the +Drive's page and header follow;
6. a power cycle: B001 still plays (the page read back through the header's check);
Negative controls:
7. the header's word for B wrong: bank B comes up empty (nothing of it plays), A unchanged;
8. one of bank A's recordings lying where the pages go (an older firmware's): banks B..D off,
   no write and no DSP word in their area, the rows skip them (A127 + 1 is the first FLEX row).
"""
import struct

STORE_SECTOR = 0x600000
CHECK_SEED = 1


def csum(b: bytes) -> int:
    """link.c's checksum (the image header's)"""
    a, c = 1, 0
    for x in b:
        a = (a + x) & 0xFFFFFFFF
        c = (c + a) & 0xFFFFFFFF
    return (c << 16 ^ a) & 0xFFFFFFFF


def run(ctx):
    machine, call, long, period = ctx["machine"], ctx["call"], ctx["long"], ctx["period"]
    disk, io, pool, syms = ctx["disk"], ctx["io"], ctx["pool"], ctx["syms"]
    SL, SM, base, d0 = ctx["SL"], ctx["SM"], ctx["base"], ctx["returned_d0"]
    sx = ctx["sx"]
    facts, notes = {}, {}

    def word(a):
        return pool.get((a - base) // 4, 0)

    def page_off(b):
        return SM.BANK_AREA + (b - 1) * SM.BANK_PAGE

    def boot(limit=12000):
        machine.write(syms["smp_booted"], bytes(4))
        pool.clear()
        n = 0
        while n < limit:
            period()
            call("smp_boot")
            n += 1
            if long("smp_booted") == 2 and long("smp_lstate") in (0, 4) and n > 50:
                break
        for _ in range(60):
            period()
            call("smp_boot")
        return n

    def settle(n=300):
        for _ in range(n):
            period()
            call("smp_boot")

    def ret(name, *args):
        call(name, *args)
        return d0() & 0xFFFFFFFF

    def sret(name, *args):
        v = ret(name, *args)
        return v - (1 << 32) if v & 0x80000000 else v

    def cstr(addr, n=40):
        b = machine.read(addr, n)
        return b.split(b"\0")[0].decode("latin-1")

    def disk_bytes(off, n):
        s0 = STORE_SECTOR + 1 + off // 512
        raw = b"".join(disk.get(s0 + k, bytes(512)) for k in range((off % 512 + n + 511) // 512))
        return raw[off % 512:off % 512 + n]

    def dsp_bytes(off, n):
        return b"".join(struct.pack("<I", pool.get((off // 4) + j, 0)) for j in range((n + 3) // 4))[:n]

    # -- the image: bank A's two samples, bank B's page with slot 4 -------------------------------------
    snd = [[0.5 * ((k * 7) % 100 / 50 - 1) for k in range(1600)],
           [0.3 * ((k * 11) % 60 / 30 - 1) for k in range(1200)]]
    img = bytearray(SL.pool_bytes(snd, base, [1.0, 1.0], [SM.FMT_I16] * 2, ["ASND0", "ASND1"]))
    img += bytes((-len(img)) % 512)
    b_frames = bytes((j * 37 + 11) & 0xFF for j in range(2 * 1500))
    b_off = (len(img) + 0x10000) & ~511                    # its frames: in the user area, after A's
    page = bytearray(SM.BANK_PAGE)
    struct.pack_into("<II", page, 0, SM.BANK_MAGIC, 5)
    struct.pack_into("<IIfI", page, 8 + 16 * 4, base + b_off, 1500, 1.0, SM.FMT_I16)
    page[SM.NAMES_OFFSET + SM.NAME_BYTES * 4:SM.NAMES_OFFSET + SM.NAME_BYTES * 4 + 4] = b"BSND"
    struct.pack_into("<II", page, SM.BANK_META, SM.META_MAGIC, 1)
    for s in range(SM.POOL_SLOTS):
        page[SM.BANK_META + 12 + SM.META_FOLDERS * SM.META_FOLDER_BYTES + SM.META_SLOT_BYTES * s] = 0xFF
    bpage_ck = csum(bytes(page[:SM.DATA_OFFSET]))

    def write_image(bank_ck=None, rec_over=False):
        disk.clear()
        im = bytearray(img)
        if rec_over:                                       # an old recording where the pages go
            struct.pack_into("<IIfI", im, 8 + 16 * (SM.REC_FIRST + 1), base + SM.BANK_AREA - 0x8000, 40000, 1.0, 1)
        hdr_dir = bytes(im[:SM.DATA_OFFSET])
        magic, nbytes, ck = 0x444E3251, SM.TABLE_AREA, csum(hdr_dir)
        h = [magic, 2, nbytes, ck, (~magic ^ nbytes ^ ck) & 0xFFFFFFFF]
        w5 = 0x314B4E42
        w6 = bpage_ck if bank_ck is None else bank_ck
        h += [w5, w6, 0, 0, w5 ^ w6 ^ 0 ^ 0 ^ 0x5A5A5A5A]
        disk[STORE_SECTOR] = struct.pack(">10I", *h).ljust(512, b"\0")
        for k in range(len(im) // 512):
            disk[STORE_SECTOR + 1 + k] = bytes(im[512 * k:512 * k + 512])
        bf = b_frames + bytes((-len(b_frames)) % 512)
        for k in range(len(bf) // 512):
            disk[STORE_SECTOR + 1 + b_off // 512 + k] = bf[512 * k:512 * k + 512]
        for k in range(SM.BANK_PAGE // 512):
            chunk = bytes(page[512 * k:512 * k + 512])
            if any(chunk):
                disk[STORE_SECTOR + 1 + page_off(1) // 512 + k] = chunk

    # 1. power-on -------------------------------------------------------------------------------------
    write_image()
    n1 = boot()
    a_ok = SL.slot_plays(word, base, 0) and SL.slot_plays(word, base, 1)
    b_plays = SL.slot_plays(word, base, 4, 1)
    b_frames_ok = dsp_bytes(b_off, len(b_frames)) == b_frames
    a4 = SL.slot_plays(word, base, 4, 0)
    cd = [(word(base + page_off(b)), word(base + page_off(b) + 4)) for b in (2, 3)]
    facts["1 power-on: bank A plays, B005 plays from B's page (its frames the image's), A005 does not, C and D empty pages"] = (
        a_ok and b_plays and b_frames_ok and not a4 and cd == [(SM.BANK_MAGIC, 0)] * 2
        and not SL.slot_plays(word, base, 0, 2) and not SL.slot_plays(word, base, 0, 3))
    notes["1"] = {"periods": n1, "a": a_ok, "b_plays": b_plays, "b_frames": b_frames_ok, "a4": a4, "cd": [list(x) for x in cd]}

    # 2. the ColdFire's view --------------------------------------------------------------------------
    live = [ret("smp_bank_live", b) for b in range(4)]
    counts = [sret("smp_bank_count", b) for b in range(4)]
    nm = cstr(ret("smp_name", 128 + 4))
    facts["2 the ColdFire: every bank live, B's count 5, global slot 132 is BSND"] = (
        live == [1, 1, 1, 1] and counts[1] == 5 and counts[2] == 0 and nm == "BSND" and long("smp_bank_blocked") == 0)
    notes["2"] = {"live": live, "counts": counts, "name": nm}

    # 3. the rows -------------------------------------------------------------------------------------
    rows = {"A127+1": sret("smp_row_step", 127, 1), "B001-1": sret("smp_row_step", 128, -1),
            "row(A001)": sret("smp_word_row", 0x0100), "word(B005)": ret("smp_row_word", 132),
            "row(B005)": sret("smp_word_row", 0x0540), "D127+1": sret("smp_row_step", 508, 1)}
    facts["3 the list's rows run through the banks: A127+1 = B001, B001-1 = A127, B005 is 0x0540"] = (
        rows == {"A127+1": 128, "B001-1": 127, "row(A001)": 1, "word(B005)": 0x0540, "row(B005)": 132, "D127+1": 509})
    notes["3"] = rows

    # 4. an edit in bank B ----------------------------------------------------------------------------
    call("smp_discard", 128 + 4)
    settle(400)
    d_ent = disk_bytes(page_off(1) + 8 + 16 * 4, 16)
    hdr = struct.unpack(">10I", disk[STORE_SECTOR][:40])
    pg_disk = disk_bytes(page_off(1), SM.DATA_OFFSET)
    facts["4 an edit in B: B005 empty on the +Drive and the DSP, the header's word for B the page's checksum"] = (
        d_ent == bytes(16) and not SL.slot_plays(word, base, 4, 1) and hdr[6] == csum(pg_disk)
        and hdr[5] == 0x314B4E42 and hdr[9] == (hdr[5] ^ hdr[6] ^ hdr[7] ^ hdr[8] ^ 0x5A5A5A5A))
    notes["4"] = {"entry": d_ent.hex(), "hdr6": hex(hdr[6]), "page_ck": hex(csum(pg_disk))}

    # 5. LOAD TO PROJECT with the list on bank B -----------------------------------------------------------
    machine.write(syms["smp_lib_state"], bytes(4))
    _st, rf = sx(17, b"BANKS")
    data = bytes((j * 13 + 5) & 0xFF or 1 for j in range(2 * 900))
    st, r = sx(18, struct.pack("<IBBI", 900, 1, rf[0] if rf else 0, 0x3F800000) + b"INTO B")
    idx = struct.unpack_from("<II", r)[0] if st == 0 else None
    sent_ok = idx is not None
    if sent_ok:
        for o in range(0, len(data), 300):
            sent_ok = sent_ok and sx(19, struct.pack("<I", o) + data[o:o + 300])[0] == 0

        def adler(b):
            a_, b_ = 1, 0
            for x in b:
                a_ = (a_ + x) % 65521
                b_ = (b_ + a_) % 65521
            return b_ << 16 | a_
        sent_ok = sent_ok and sx(20, struct.pack("<I", adler(data)))[0] == 0
    machine.write(syms["smp_lp_bank"], struct.pack(">i", 1))
    done = long("smp_lp_done")
    if sent_ok:
        call("smp_lib_load", idx)
        for _ in range(3000):
            period()
            call("smp_boot")
            if long("smp_lp_done") > done and long("smp_lstate") in (0, 4):
                break
    settle(400)
    b1 = struct.unpack("<4I", disk_bytes(page_off(1) + 8, 16))
    b1_plays = SL.slot_plays(word, base, 0, 1)
    b1_frames = b1[1] == 900 and dsp_bytes(b1[0] - base, len(data)) == data
    a_slot0 = struct.unpack("<4I", disk_bytes(8, 16))
    hdr = struct.unpack(">10I", disk[STORE_SECTOR][:40])
    facts["5 LOAD TO PROJECT on bank B: into B001, plays from B's page, its frames exact, the +Drive's page and header follow"] = (
        sent_ok and b1_plays and b1_frames and word(base + page_off(1) + 4) >= 1
        and hdr[6] == csum(disk_bytes(page_off(1), SM.DATA_OFFSET)) and a_slot0[1] == 1600)
    notes["5"] = {"sent": sent_ok, "idx": idx, "b1": [hex(x) for x in b1], "plays": b1_plays, "frames": b1_frames,
                  "count": word(base + page_off(1) + 4)}

    # 6. a power cycle ----------------------------------------------------------------------------------
    boot()
    facts["6 a power cycle: B001 still plays, bank A as it was"] = (
        SL.slot_plays(word, base, 0, 1) and SL.slot_plays(word, base, 0) and SL.slot_plays(word, base, 1)
        and dsp_bytes(b1[0] - base, len(data)) == data)

    # 7. negative control: the header's word for B wrong ---------------------------------------------
    write_image(bank_ck=bpage_ck ^ 1)
    boot()
    facts["7 control: the header's word for B wrong: B empty (B005 silent), A plays"] = (
        not SL.slot_plays(word, base, 4, 1) and SL.slot_plays(word, base, 0) and sret("smp_bank_count", 1) == 0)

    # 8. negative control: an old recording where the pages go ------------------------------------------
    write_image(rec_over=True)
    w0 = dict(disk)
    boot()
    lo, hi = STORE_SECTOR + 1 + SM.BANK_AREA // 512, STORE_SECTOR + 1 + SM.TABLE_AREA // 512
    wrote = [s for s in disk if lo <= s < hi and disk[s] != w0.get(s)]
    rec_end = (SM.BANK_AREA - 0x8000 + 2 * 40000 + 511) & ~511   # (the recording itself loads, as any)
    dsp_words = [k for k in pool if rec_end // 4 <= k < SM.TABLE_AREA // 4]
    facts["8 control: a recording where the pages go: banks B..D off, nothing written or sent there, rows skip them"] = (
        long("smp_bank_blocked") == 1 and ret("smp_bank_live", 1) == 0 and not wrote and not dsp_words
        and sret("smp_row_step", 127, 1) == 509 and SL.slot_plays(word, base, 0))
    notes["8"] = {"wrote": [hex(s) for s in wrote[:4]], "dsp_words": len(dsp_words)}
    disk.clear()
    return {"facts": facts, "notes": notes, "ok": all(facts.values())}
