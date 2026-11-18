"""The tables' READY with this build's checksum, on the SHARC runner (docs/mnm.md, "READY carries this build's
checksum"): the DSP's own decode (a cold init: nothing pre-filled) in three cases, then every decoded word compared
with the model's (dnfw.md.bench.table_mem, as the warm init pre-fills them):

  (a) another build's ready word in DDR (the magic, a wrong checksum) over another build's table bytes (here: all
      zero): the decode must wait; at block READY_AT the ColdFire's tables and READY arrive, it decodes this build's;
  (b) this build's word kept from the boot before (a restart on the same build): it decodes at once;
  (c) a cold DDR (nothing there): it waits for READY at block READY_AT, then decodes.

READY_AT comes after a whole decode's time, so a DSP that took (a)'s stale word decodes the stale bytes to the end
and never again: its tables differ from the model's. Each case: the decode's position (fill) before READY_AT and at
the end, and how many decoded words differ from the model's (0 required). The runner's step `tableready`
(sharc_waverider_m5.py, gate_sharc's part of its own); alone:
    python scripts/sharc_table_ready.py IMAGE DIGIKIT"""
import pathlib
import struct
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
from dnfw.md import bench as MDB  # noqa: E402
from dnfw.md import core as MDK  # noqa: E402
from dnfw.perc import live as PL  # noqa: E402
from dnfw.sampler import machines as SM  # noqa: E402

MIDI = 4                                  # every track on MIDI: the blocks run, no voice of ours
READY_AT = MDK.Z_N // MDK.Z_PER_BLOCK + 8  # after a whole decode (Z_PER_BLOCK words a block)
BLOCKS = 2 * READY_AT + 4


def run(M5, snap, m2mach, m5img, stockimg, sound, machines) -> dict:
    """cases a, b, c on the runner module M5 (sharc_waverider_m5) -> {"ok", "checks", "numbers"}"""
    m2 = M5.m2
    L = PL.layout().md
    shipped, at, total = MDK.tables_bytes(), L.T[MDK.SHIPPED], MDK.table_sum()
    words = [struct.unpack_from("<I", shipped, k)[0] for k in range(0, len(shipped), 4)]
    model = {a: w for a, w in MDB.table_mem(L).items() if L.tables <= a < at}

    def ready(st, magic, s):
        m2.poke(st, L.ready, magic)
        m2.poke(st, L.ready + SM.TABLE_SUM_AT, s)

    def ship(st, ws):
        for k, w in enumerate(ws):
            m2.poke(st, at + 4 * k, w)

    def fb(_b):
        return M5.base_frame(sound, machines, t0=MIDI).to_bytes()

    checks, numbers = {}, {}
    for case, what in (("a", "another build's ready word: waits, decodes this build's after READY"),
                       ("b", "this build's word kept: decodes at once"),
                       ("c", "a cold DDR: waits, decodes after READY")):
        init = M5.init_on(snap, m2mach, m5img, warm=False)          # this build's tables and READY, as today
        if case == "a":
            ship(init.state, [0] * len(words))
            ready(init.state, SM.TABLE_MAGIC, (total ^ 0x5A5A5A5A) & 0xFFFFFFFF)
        elif case == "c":
            ready(init.state, 0, 0)
        seen = {"n": 0, "fill": []}

        def at_dispatch(r, case=case, seen=seen):
            seen["fill"].append(m2.word(r.state, L.C["fill"]) or 0)
            if case in "ac" and seen["n"] == READY_AT:              # the ColdFire's tables, then READY
                ship(r.state, words)
                ready(r.state, SM.TABLE_MAGIC, total)
            seen["n"] += 1
        rr = M5.run_blocks(init, fb, BLOCKS, extra_hooks={M5.m3.DISPATCH: at_dispatch})
        st = rr["state"].state if rr.get("ok") else None
        differ = (sum(1 for a, w in model.items() if (m2.word(st, a) or 0) & 0xFFFFFFFF != w & 0xFFFFFFFF)
                  if st is not None else None)
        f = seen["fill"]
        before = f[READY_AT - 1] if len(f) >= READY_AT else None
        after = f[-1] if f else None
        timing = before == 0 if case in "ac" else (len(f) > 2 and f[2] > 0)
        checks[f"({case}) {what}; every decoded word the model's"] = (bool(rr.get("ok")) and timing
                                                                      and after == MDK.Z_N and differ == 0)
        numbers[case] = {"fill_before_ready": before, "fill_end": after, "words_differ": differ, "words": len(model)}
        print(f"  case {case}: fill before READY {before}, at the end {after} (Z_N {MDK.Z_N}); decoded words "
              f"differing from the model {differ} of {len(model)}", flush=True)
    return {"ok": all(checks.values()), "checks": checks, "numbers": numbers}


def main() -> int:
    import sharc_waverider_m5 as R
    from dnfw.waverider import dsp
    image, digikit = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    dk = R.m1.Digikit(digikit)
    R.fx.bind(str(digikit / "tools"))
    R.m4.IMAGE = image
    stock = R.m1.dn2_section7(image)
    sound, machines = R.m4.init_sound(image)
    m5 = R.Image(dk, dsp.section7(stock))
    R.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=R.OUT) as tmp:
        snap, m2mach = R.snapshot_path(dk, stock, pathlib.Path(tmp))
        res = run(R, snap, m2mach, m5, stock, sound, machines)
    for k, v in res["checks"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"\n  table ready: {'PASS' if res['ok'] else 'FAIL'}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
