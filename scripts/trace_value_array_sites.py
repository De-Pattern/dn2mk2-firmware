"""Which value-array sites actually index a sound object, and with what slot.

`docs/lfo4-slot-plan.md` records this as the question step 4 of the build order
is sized against, and as the one three static readings have each answered
differently (144 regex hits, 29 sites, 33 sites). The reason is written up
there: `%aN@(0x14,%dM:l:2)` identifies an **offset**, not the value array. Any
structure with a 16-bit array at `+0x14` indexed by a scaled long matches, and
nothing in the encoding says `%aN` holds a sound object.

That is an identity question, and identity is a runtime fact. So this runs the
firmware and asks each candidate directly:

- **does it execute at all** -- a site the machine never reaches needs no hook;
- **is its base a sound object** -- `sound(i) = pool + 0x4414 + i*2388`, so bases
  drawn from the pool differ by multiples of **2388**. A site whose bases do not
  is indexing some other structure and is a false positive of the shape scan;
- **what slots does it see** -- the observed range, which bounds nothing by
  itself but separates the obviously-narrow sites from the generic ones.

**What this can and cannot settle.** It settles membership: a site whose base is
never a sound object is not a value-array site, and that is the 29-vs-33
discrepancy closed by measurement. It does **not** prove a site can never see a
slot >= 101 -- LFO4's records do not exist yet, so no index can reach there in
stock firmware. Observed range is evidence about provenance, not a bound. Read
the output as "which sites are real and which are generic", and treat any site
whose index provenance is `param_index_in_page` as reachable regardless of what
it happened to do in one run.

Not a new emulator: this drives digikit's `emu` as a library, the same
`build`/`spin`/`Timers` path `tools/addrtrace.py` uses on its `--resume` route.
`addrtrace` itself is not enough here because it records registers at **first
hit** only, and the whole question is about the range of values across a run.

Usage (from a WSL shell with the patched Unicorn venv, see docs/emulator.md):

    DIGIKIT=/mnt/d/01_Code/Z_Personal/digikit \\
    DT2_SECTIONS=/root/dn2-sections-111 \\
    python scripts/trace_value_array_sites.py \\
        --snapshot ~/dn2-snapshots/Digitone_II_OS1.11/boot400M.snap \\
        --syx .../Digitone_II_OS1.11.syx --limit 200000000 --json out.json

**The sections directory must match the snapshot's firmware.** `emu/config.py`
resolves MAIN OS by globbing `sections/*MAIN_OS*.bin` and `--syx` does not
repoint it; `docs/emulator.md` records a whole session lost to a stale 1.10E
extraction running against 1.11 snapshots.
"""

import argparse
import collections
import json
import os
import pathlib
import struct
import sys

SOUND_STRIDE = 2388          # sound(i) = pool + 0x4414 + i*2388
SOUND_COUNT = 128
VALUE_OFF = 0x14             # the array's displacement inside the object
SLOTS = 101                  # slots 0..100 exist today


def derive_sites(img, load_addr):
    """-> [(opcode_va, an, dm, which)] for every `%aN@(0x14,%dM:l:2)` access.

    Derived from the image rather than hardcoded, so this re-runs on the next
    build. Two filters make the shape scan honest: the extension word must be
    word-aligned, and the opcode before it must really name mode 110 in one of
    its effective-address fields.
    """
    out = []
    for m in range(8):
        pat = struct.pack(">H", (m << 12) | 0x0A14)
        i = img.find(pat)
        while i >= 0:
            va = i + load_addr
            if va % 2 == 0 and i >= 2:
                w = struct.unpack_from(">H", img, i - 2)[0]
                if (w & 0x38) == 0x30:
                    out.append((va - 2, w & 7, m, "src"))
                elif (w >> 14) == 0 and (w >> 12) in (1, 2, 3) \
                        and ((w >> 6) & 7) == 6:
                    out.append((va - 2, (w >> 9) & 7, m, "dst"))
            i = img.find(pat, i + 1)
    return sorted(out)


def classify_bases(bases):
    """-> ('sound-pool', pool) | ('other', None), from the base values seen.

    Sound objects sit on a 2388-byte stride, so a site fed from the pool shows
    bases that are congruent modulo 2388 and span no more than 128 of them.
    One base alone cannot show a stride, so it is reported as 'single' rather
    than guessed at either way.
    """
    if not bases:
        return "never-ran", None
    uniq = sorted(bases)
    if len(uniq) == 1:
        return "single", uniq[0]
    residues = {b % SOUND_STRIDE for b in uniq}
    if len(residues) == 1:
        span = (uniq[-1] - uniq[0]) // SOUND_STRIDE
        if span < SOUND_COUNT:
            return "sound-pool", uniq[0] - 0x4414
        return "sound-stride-oversized", uniq[0]
    return "other", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--syx", required=True)
    ap.add_argument("--limit", type=lambda s: int(s, 0), default=200_000_000)
    ap.add_argument("--step", type=lambda s: int(s, 0), default=10_000_000)
    ap.add_argument("--max-distinct", type=int, default=4096,
                    help="cap on distinct index/base values kept per site")
    ap.add_argument("--json")
    ap.add_argument("--input", action="append", default=[],
                    help="WHEN:press|release|encoder:CODE[:ARG], as guirun")
    ap.add_argument("--control", action="append", default=[],
                    help="ADDR=NAME extra hook, for positive controls")
    ap.add_argument("--accessor", type=lambda s: int(s, 0), default=None,
                    help="sound-object accessor; its stack args give the pool")
    ap.add_argument("--watch", action="append", default=[],
                    help="LO:HI write watch, reporting the PCs that write")
    ap.add_argument("--dump", action="append", default=[],
                    help="WHEN:LO:LEN memory dump; consecutive dumps of "
                         "the same LO are diffed, which finds an edit with "
                         "no hook at all")
    ap.add_argument("--png", action="append", default=[],
                    help="WHEN:PATH screen capture, the control that says "
                         "whether an input reached the UI at all")
    ap.add_argument("--argsat", action="append", default=[],
                    help="ADDR[=NAME] record the address registers at "
                         "each hit, so a copier can be asked what it is "
                         "actually copying between")
    ap.add_argument("--send",
                    help="file of raw bytes to place in the UART8 receive "
                         "queue, e.g. a SysEx dump")
    ap.add_argument("--find", action="append", default=[],
                    help="WHEN:LO:LEN:HEX search mapped memory for a byte "
                         "pattern -- a known plaintext needs no stimulus")
    ap.add_argument("--pagemap", action="append", default=[],
                    help="WHEN:LO:LEN page-hash sweep. Hashes every 4K "
                         "page instead of copying it, so a whole 100 MB "
                         "BSS can be compared for a few hundred KB.")
    ap.add_argument("--exclude", action="append", default=[],
                    help="LO:HI absolute range to drop from every diff. "
                         "The framebuffers belong here: they change "
                         "whenever the screen does, which is every time "
                         "an edit is visible, and they will dominate.")
    ap.add_argument("--no-sites", action="store_true",
                    help="skip the per-site code hooks; use with --watch alone")
    args = ap.parse_args()

    digikit = os.environ.get("DIGIKIT")
    if not digikit:
        raise SystemExit("set DIGIKIT to the digikit checkout (see docs/emulator.md)")
    sys.path.insert(0, digikit)

    from unicorn.m68k_const import (
        UC_M68K_REG_A0, UC_M68K_REG_A1, UC_M68K_REG_A2, UC_M68K_REG_A3,
        UC_M68K_REG_A4, UC_M68K_REG_A5, UC_M68K_REG_A6, UC_M68K_REG_A7,
        UC_M68K_REG_D0, UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_D3,
        UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7)
    from unicorn import UC_HOOK_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_PC
    from emu import config, device as devices, panel, panelin, symbols
    import emu.dspboot as db
    from emu.longrun import build, spin
    from emu.pit import Pits, intro_running
    from emu.dtim import Dtims, Timers

    areg = [UC_M68K_REG_A0, UC_M68K_REG_A1, UC_M68K_REG_A2, UC_M68K_REG_A3,
            UC_M68K_REG_A4, UC_M68K_REG_A5, UC_M68K_REG_A6, UC_M68K_REG_A7]
    dreg = [UC_M68K_REG_D0, UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_D3,
            UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7]

    main_img = pathlib.Path(config.main_image()).read_bytes()
    profile = symbols.resolve(main_img, load_addr=db.MAIN_LOAD)
    sites = derive_sites(main_img, db.MAIN_LOAD)
    print("MAIN OS %s, %d bytes" % (config.main_image(), len(main_img)))
    print("%d candidate sites\n" % len(sites))

    feed = b""
    if args.send:
        feed = pathlib.Path(args.send).read_bytes()
        print("feeding %d bytes into the UART receive queue" % len(feed))
    m, ev, st, pc, inq, at = build(args.snapshot, syx=args.syx, send=feed,
                                   unblock=True, softfloat=True,
                                   bitmap=True, weakptr=True, slc=True)

    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        def handover(uc, a, s_, d):
            pits.release()
        at(profile.intro_done, handover)

    hits = collections.Counter()
    idx = collections.defaultdict(collections.Counter)
    base = collections.defaultdict(collections.Counter)
    cap = args.max_distinct

    def make(addr, an, dm):
        ar, dr = areg[an], dreg[dm]

        def cb(uc, a, size, data):
            hits[addr] += 1
            if len(idx[addr]) < cap:
                idx[addr][uc.reg_read(dr)] += 1
            if len(base[addr]) < cap:
                base[addr][uc.reg_read(ar)] += 1
        return cb

    # A ranged write watch is expensive on its own; installing 37 code hooks
    # beside it is what pushed this over the host's memory on a 16 GB box.
    # The two questions are separable, so let either half run alone.
    if not args.no_sites:
        for va, an, dm, _which in sites:
            at(va, make(va, an, dm))
    else:
        print("site hooks disabled (--no-sites)")

    ctl = collections.Counter()
    ctl_names = {}
    ctl_regs = collections.defaultdict(collections.Counter)
    for spec in args.control:
        addr_s, _, nm = spec.partition("=")
        addr = int(addr_s, 0)
        ctl_names[addr] = nm or addr_s

        def cmake(a):
            def cb(uc, x, size, data):
                ctl[a] += 1
                if len(ctl_regs[a]) < 64:
                    # d0..d3 plus the first stack argument: a per-column
                    # accessor takes the parameter id in one of them.
                    sp = uc.reg_read(areg[7])
                    try:
                        arg = int.from_bytes(uc.mem_read(sp + 4, 4), "big")
                    except Exception:           # noqa: BLE001
                        arg = -1
                    ctl_regs[a][tuple(uc.reg_read(r) for r in dreg[:4])
                                 + (arg,)] += 1
            return cb
        at(addr, cmake(addr))

    # The accessor is sound(base, index) = base + 0x4414 + index*2388, with
    # both arguments on the stack. Reading them gives the live pool without
    # guessing at it, which is what makes the write watch below aimable.
    objs = collections.Counter()
    pool_hint = [None]

    if args.accessor is not None:
        def acc_cb(uc, a, size, data):
            try:
                sp = uc.reg_read(UC_M68K_REG_A7)
                arg = uc.mem_read(sp + 4, 8)
                b_ = int.from_bytes(arg[:4], "big")
                i_ = int.from_bytes(arg[4:], "big")
                if 0 <= i_ < SOUND_COUNT:
                    objs[b_ + 0x4414 + i_ * SOUND_STRIDE] += 1
            except Exception:                       # noqa: BLE001
                pass
        at(args.accessor, acc_cb)

    writers = collections.defaultdict(collections.Counter)
    for spec in args.watch:
        lo_s, _, hi_s = spec.partition(":")
        lo, hi = int(lo_s, 0), int(hi_s, 0)

        def wcb(uc, access, address, size, value, data, _lo=lo):
            writers[_lo][uc.reg_read(UC_M68K_REG_PC)] += 1
        m.uc.hook_add(UC_HOOK_MEM_WRITE, wcb, begin=lo, end=hi)
        print("write watch 0x%08x..0x%08x" % (lo, hi))

    pending_finds = []
    for spec in args.find:
        w_s, lo_s, ln_s, hx = spec.split(":")
        w = int(float(w_s[:-1]) * 1e6) if w_s.endswith("M") else int(w_s, 0)
        pending_finds.append((w, int(lo_s, 0), int(ln_s, 0),
                              bytes.fromhex(hx)))
    pending_finds.sort()

    pending_pngs = []
    for spec in args.png:
        w_s, _, path = spec.partition(":")
        w = int(float(w_s[:-1]) * 1e6) if w_s.endswith("M") else int(w_s, 0)
        pending_pngs.append((w, path))
    pending_pngs.sort()

    import hashlib as _hl
    pagemaps = collections.defaultdict(list)
    pending_maps = []
    for spec in args.pagemap:
        w_s, lo_s, ln_s = spec.split(":")
        w = int(float(w_s[:-1]) * 1e6) if w_s.endswith("M") else int(w_s, 0)
        pending_maps.append((w, int(lo_s, 0), int(ln_s, 0)))
    pending_maps.sort()

    dumps = collections.defaultdict(list)
    pending_dumps = []
    for spec in args.dump:
        w_s, lo_s, ln_s = spec.split(":")
        w = int(float(w_s[:-1]) * 1e6) if w_s.endswith("M") else int(w_s, 0)
        pending_dumps.append((w, int(lo_s, 0), int(ln_s, 0)))
    pending_dumps.sort()

    argsites = {}
    for spec in args.argsat:
        a_s, _, nm = spec.partition("=")
        addr = int(a_s, 0)
        argsites[addr] = nm or ("0x%08x" % addr)
    argrec = collections.defaultdict(list)

    def amake(a):
        def cb(uc, x, size, data):
            if len(argrec[a]) < 32:
                argrec[a].append(tuple(uc.reg_read(r) for r in areg))
        return cb
    for a in argsites:
        at(a, amake(a))

    held = device = None
    if args.input:
        # devices/ is resolved relative to the digikit checkout, so identify
        # has to run from there; every path this script takes is absolute.
        cwd = os.getcwd()
        try:
            os.chdir(digikit)
            device, _fw = devices.identify(config.firmware(args.syx))
        finally:
            os.chdir(cwd)
        held = panelin.Held(device)
    pending = []
    for spec in args.input:
        parts = spec.split(":")
        when = int(float(parts[0].rstrip("M")) * 1e6) if parts[0].endswith("M")             else int(parts[0], 0)
        pending.append((when, parts[1], int(parts[2], 0),
                        int(parts[3], 0) if len(parts) > 3 else 0))
    pending.sort()

    done, pc_ = 0, pc
    while done < args.limit:
        pc_, executed, stop = spin(m, pc_, args.step, pits=pits)
        done += executed
        while pending_finds and pending_finds[0][0] <= done:
            _w, lo, ln, pat = pending_finds.pop(0)
            found, step = [], 0x10000
            for off in range(0, ln, step):
                try:
                    chunk = bytes(m.uc.mem_read(
                        lo + off, min(step + len(pat), ln - off)))
                except Exception:           # noqa: BLE001
                    continue
                j = chunk.find(pat)
                while j >= 0:
                    found.append(lo + off + j)
                    j = chunk.find(pat, j + 1)
            print("  find %dM %s : %d hit(s)"
                  % (done // 1_000_000, pat.hex(), len(found)))
            for a_ in found[:20]:
                print("      0x%08x" % a_)
        while pending_maps and pending_maps[0][0] <= done:
            _w, lo, ln = pending_maps.pop(0)
            book = {}
            for off in range(0, ln, 4096):
                try:
                    pg = bytes(m.uc.mem_read(lo + off, 4096))
                except Exception:           # noqa: BLE001
                    continue                # demand-mapped, absent
                book[off] = _hl.blake2b(pg, digest_size=8).digest()
            pagemaps[lo].append((done, book))
            print("  pagemap %dM 0x%08x +%d : %d mapped pages"
                  % (done // 1_000_000, lo, ln, len(book)))
        while pending_pngs and pending_pngs[0][0] <= done:
            _w, path = pending_pngs.pop(0)
            try:
                panel.write_png(panel.read(m, profile.fb_front), path)
                print("  png %dM -> %s" % (done // 1_000_000, path))
            except Exception as exc:            # noqa: BLE001
                print("  png %dM failed: %s" % (done // 1_000_000, exc))
        while pending_dumps and pending_dumps[0][0] <= done:
            _w, lo, ln = pending_dumps.pop(0)
            try:
                dumps[lo].append((done, bytes(m.uc.mem_read(lo, ln))))
                print("  dump %dM 0x%08x +%d bytes"
                      % (done // 1_000_000, lo, ln))
            except Exception as exc:            # noqa: BLE001
                # BSS is demand-mapped, so a window can be legitimately
                # absent; that is data, not a reason to lose the run.
                print("  dump %dM 0x%08x unmapped: %s"
                      % (done // 1_000_000, lo, exc))
        while pending and pending[0][0] <= done:
            _w, kind, code, arg = pending.pop(0)
            out = b""
            try:
                if kind == "encoder":
                    ch = device.encoder_channel(code)
                    if ch is not None:
                        out = panelin.encode_encoder(ch, arg)
                elif kind == "press":
                    pos = held.press(code)
                    out = panelin.encode_buttons(*pos) if pos else b""
                elif kind == "release":
                    pos = held.release(code)
                    out = panelin.encode_buttons(*pos) if pos else b""
            except Exception as exc:                # noqa: BLE001
                # One malformed input must not throw away the whole run; the
                # trace of everything before it is still evidence.
                print("  input %dM %s:%d rejected: %s" % (done // 1_000_000,
                                                          kind, code, exc))
                continue
            if out:
                try:
                    pc_ = panelin.feed(m, profile, bytes(out))
                    print("  input %dM %s:%d -> %s"
                          % (done // 1_000_000, kind, code, bytes(out).hex()))
                except Exception as exc:            # noqa: BLE001
                    print("  input failed: %s" % exc)
        if stop != "limit":
            print("stopped: %s at %dM" % (stop, done // 1_000_000))
            break
    print("ran %dM instructions\n" % (done // 1_000_000))
    if args.send:
        # The decisive diagnostic: if the queue is untouched the guest
        # never read a byte, and nothing downstream means anything.
        print("uart receive queue: %d of %d bytes left unread"
              % (len(inq), len(feed)))
        print("uart transmitted: %d bytes" % len(ev["uart_out"]))


    rows = []
    for va, an, dm, which in sites:
        kind, pool = classify_bases(list(base[va]))
        ks = sorted(idx[va])
        row = {
            "va": va, "base_reg": "a%d" % an, "index_reg": "d%d" % dm,
            "ea": which, "hits": hits[va], "kind": kind,
            "pool": pool, "distinct_bases": len(base[va]),
            "index_min": ks[0] if ks else None,
            "index_max": ks[-1] if ks else None,
            "distinct_index": len(ks),
            "index_over_100": sorted(k for k in ks if k >= SLOTS)[:8],
        }
        rows.append(row)

    print("%-12s %-4s %-4s %8s  %-22s %s"
          % ("site", "base", "idx", "hits", "base kind", "index range"))
    for r in rows:
        rng = ("-" if r["index_min"] is None
               else "%d..%d (%d distinct)"
               % (r["index_min"], r["index_max"], r["distinct_index"]))
        print("0x%08x  %-4s %-4s %8d  %-22s %s"
              % (r["va"], r["base_reg"], r["index_reg"], r["hits"],
                 r["kind"], rng))

    if ctl_names:
        print("\ncontrols (positive controls -- a zero here invalidates the run):")
        for a, nm in sorted(ctl_names.items()):
            print("  %-20s 0x%08x  hits=%d  distinct-args=%d"
                  % (nm, a, ctl[a], len(ctl_regs[a])))
            for regs, n in ctl_regs[a].most_common(6):
                print("      d0=%-6d d1=%-6d d2=%-6d d3=%-6d arg1=%-10d x%d"
                      % (regs[0], regs[1], regs[2], regs[3], regs[4], n))

    for a, nm in sorted(argsites.items()):
        rows_ = argrec[a]
        print("")
        print("%s 0x%08x: %d hit(s) recorded" % (nm, a, len(rows_)))
        for n, regs in enumerate(rows_[:6]):
            print("   hit %d: %s" % (n, " ".join(
                "a%d=0x%08x" % (i, v) for i, v in enumerate(regs))))

    if objs:
        top = objs.most_common(8)
        print("\nsound objects seen via the accessor (%d distinct):" % len(objs))
        for o, n in top:
            print("  0x%08x  x%d   value array 0x%08x..0x%08x"
                  % (o, n, o + VALUE_OFF, o + VALUE_OFF + SLOTS * 2))
    if writers:
        print("\nwrite watches:")
        for lo, pcs in writers.items():
            print("  0x%08x: %d writes from %d PCs" % (lo, sum(pcs.values()), len(pcs)))
            for pc_, n in pcs.most_common(12):
                print("      pc=0x%08x  x%d" % (pc_, n))

    excl = []
    for spec in args.exclude:
        a_s, _, b_s = spec.partition(":")
        excl.append((int(a_s, 0), int(b_s, 0)))
    diff_report = []

    page_report = []
    for lo, seq in pagemaps.items():
        for (w0, a), (w1, c) in zip(seq, seq[1:]):
            moved = sorted(o for o in a if o in c and a[o] != c[o])
            gone = sorted(set(a) ^ set(c))
            print("")
            print("pagemap 0x%08x  %dM -> %dM : %d pages changed, "
                  "%d appeared/vanished"
                  % (lo, w0 // 1_000_000, w1 // 1_000_000,
                     len(moved), len(gone)))
            page_report.append({"lo": lo, "from": w0, "to": w1,
                                "pages": [lo + o for o in moved]})
            for o in moved[:40]:
                print("    page 0x%08x" % (lo + o))

    for lo, seq in dumps.items():
        for (w0, a), (w1, c) in zip(seq, seq[1:]):
            diff = [i for i in range(min(len(a), len(c))) if a[i] != c[i]]
            if excl:
                n0 = len(diff)
                diff = [i for i in diff
                        if not any(x <= lo + i < y for x, y in excl)]
                if n0 != len(diff):
                    print("  (dropped %d bytes inside excluded ranges)"
                          % (n0 - len(diff)))

            print("")
            print("pool diff 0x%08x  %dM -> %dM : %d bytes changed"
                  % (lo, w0 // 1_000_000, w1 // 1_000_000, len(diff)))
            diff_report.append({"lo": lo, "from": w0, "to": w1,
                                "offsets": diff,
                                "vals": [[o, a[o], c[o]] for o in diff]})
            seen = {}

            is_pool = lo in {o for o in objs} or lo == pool_hint[0]
            for off in (diff if is_pool else []):

                obj, within = divmod(off, SOUND_STRIDE)
                if VALUE_OFF <= within < VALUE_OFF + SLOTS * 2:
                    slot = (within - VALUE_OFF) // 2
                    seen.setdefault((obj, slot), (a[off], c[off]))
            for (obj, slot), (x, y) in sorted(seen.items())[:24]:
                print("    object %3d slot %3d : 0x%02x -> 0x%02x"
                      % (obj, slot, x, y))
            if diff:
                for o in diff[:24]:
                    print("    0x%08x : 0x%02x -> 0x%02x"
                          % (lo + o, a[o], c[o]))
            if not seen and diff:
                print("    changes fall outside every value array")

    real = [r for r in rows if r["kind"] == "sound-pool"]
    ran = [r for r in rows if r["hits"]]
    print("\n%d of %d candidates executed; %d index the sound-object pool"
          % (len(ran), len(rows), len(real)))
    if real:
        print("sound-pool sites:",
              " ".join("0x%08x" % r["va"] for r in real))

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({"sites": rows, "instrs": done,
                    "diffs": diff_report,
                    "pages": page_report}, indent=1))
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
