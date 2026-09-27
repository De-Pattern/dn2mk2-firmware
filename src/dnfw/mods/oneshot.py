"""ONESHOT: the Digitakt II's sample machine, moved into the Digitone II from the user's
own DT2 1.16 file, with one sample of the user's baked in.

**Not yet on the instrument.** Everything here passed in the emulators (ColdFire:
digikit's; DSP: digikit's SHARC runner), nothing on silicon. The hardware test
is `docs/dt2-machine-port.md`, "The first flash".

## What it is

MACHINE SEL offers **ONESHOT** after SWARMER (the DT2's own name for it). A
ONESHOT track is machine type 5. Its SYN page is the DT2's SRC page -- TUNE,
PLAY, SAMP, STRT, LEN, LOOP, LEV, the DT2's records with the DT2's value
formatters -- drawn by the DN2's page view. The DSP plays the track with the
DT2's own voice render, relocated, driven by our adapter from those values.

**One sample.** The bank holds the WAV the user names (48 kHz mono after
conversion, at most about half a second: it lives in L1 block 2), and every SAMP
value plays it. There is no sample browser, no +Drive, no sample pool.

## What it needs

Two firmware files, both the user's: the Digitone II 1.11 image being modified
and the Digitakt II 1.16 OS the machine comes from (`--donor`), plus a WAV
(`--sample`). Nothing of the DT2's is in this repository: the render, its
tables, the records, their names and the page's knob list are read from
`--donor` when the mod is applied, each checked against a SHA-256 first.

## Exclusive with

Waverider (the same machine type and the same entry sites), LFO4 (the loader
cave and the chunk address). `docs/mods-compatibility.md`.

## A sound saved with a ONESHOT track

Saved as machine type 5. This build keeps 5 on LOAD; stock firmware loads it as
FM Tone (the stock LOAD bound's fallback) with its parameters as they were.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result
from ..firmware.load import load
from ..image import sharc_object
from ..oneshot import build as OB
from ..oneshot import coldfire as OC
from ..oneshot import sample as SA
from ..oneshot import samples as SM
from ..oneshot import bank as BK
from ..transplant import cfplan, oneshot_cf, oneshot_dt2
from ..transplant import plan as sharc_plan

ID = "oneshot"
NAME = "ONESHOT, the Digitakt II's sample machine"
SUMMARY = ("MACHINE SEL gains ONESHOT: the DT2's SRC page and voice render, moved from the "
           "user's own DT2 1.16 file, playing one baked sample. First transplant build.")
DEVICE = 0x15
MAIN_OS, DSP_STREAM = 3, 7
BASE = 0x40000400
HERE = pathlib.Path(__file__).resolve()
CODE = HERE.with_name("oneshot_code.json")
ADAPTER = HERE.parents[3] / "csrc" / "oneshot" / "sharc" / "oneshot5.json"


def _json(path: pathlib.Path) -> dict:
    if not path.exists():
        raise ModError(f"{path.name} is missing (scripts/gen_oneshot_code.py, "
                       "scripts/gen_oneshot_sharc.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def shims() -> dict:
    spec = _json(CODE)
    return {"code": bytes.fromhex(spec["shims"]), "labels": spec["labels"],
            "group": bytes.fromhex(spec["group"])}


def adapter() -> tuple[bytes, bytes]:
    spec = _json(ADAPTER)
    return (sharc_object.load_bytes(bytes.fromhex(spec["object_parcels_be"])),
            sharc_object.load_bytes(bytes.fromhex(spec["entry_jump"]["object_parcels_be"])))


def bank_limit() -> int:
    """How many samples one entry may have: the bank's room less its header."""
    return (OB.BANK_END - OB.BANK_DM - BK.HEADER - BK.ENTRY) // 2


def extents(firmware=None) -> list[Extent]:
    out = [Extent(MAIN_OS, 0, 0x30B580, "MAIN OS: the machine-type edits, eight records, the "
                                        "startup loader and its appended CODE chunk (declared whole)"),
           Extent(DSP_STREAM, 0, 836_956, "the DSP boot stream, rebuilt: the DT2 render, our "
                                         "adapter, the bank, the entry jump, the machine lookup")]
    return out


def compose(dn2_raw: bytes, dt2_raw: bytes, pcm: list[int]) -> dict:
    """-> {MAIN_OS: bytes, DSP_STREAM: bytes, "report": {...}}. Both firmwares are the user's."""
    dn2, dt2 = load(dn2_raw), load(dt2_raw)
    main_os = dn2.container.find(MAIN_OS).unpack()
    stream = dn2.container.find(DSP_STREAM).unpack()
    donor_os = dt2.container.find(MAIN_OS).unpack()
    if main_os is None or stream is None or donor_os is None:
        raise ModError("a MAIN OS or DSP boot stream did not depack")
    cf = cfplan.build(oneshot_cf.SPEC, donor_os, main_os)
    if not cf.ok:
        raise ModError("the ColdFire transplant refused: " + "; ".join(cf.refusals))
    sp = sharc_plan.build(oneshot_dt2.SPEC, dt2_raw, dn2_raw)
    if not sp.ok:
        raise ModError("the DSP transplant refused: " + "; ".join(sp.refusals))
    try:
        cf_out = OC.compose(main_os, cf, shims())
    except OC.ComposeError as exc:
        raise ModError(f"MAIN OS: {exc}") from exc
    code, entry = adapter()
    try:
        s7, s7_report = OB.section7(stream, sp, code, [pcm], entry_jump=entry)
    except ValueError as exc:
        raise ModError(f"the DSP boot stream: {exc}") from exc
    return {MAIN_OS: cf_out["content"], DSP_STREAM: s7,
            "report": {"coldfire": cf.report(), "layout": cf_out["layout"],
                       "edits": len(cf_out["edits"]), "dsp": s7_report,
                       "dsp_plan": sp.report()}}


def apply(firmware, *, donor: pathlib.Path | None = None, sample: pathlib.Path | None = None,
          raw: bytes | None = None) -> Result:
    if donor is None:
        raise ModError("--donor is required: the Digitakt II 1.16 OS file ONESHOT comes from")
    if raw is None:
        raise ModError("the Digitone II image's bytes are needed (the DSP plan hashes them)")
    from ..cli.files import read_image
    dt2_raw = read_image(donor)
    if sample is not None:
        pcm, note = SA.from_wav(sample.read_bytes(), bank_limit())
        what = f"{sample.name}: {note['seconds']} s at 48 kHz" + (" (trimmed)" if note["trimmed"] else "")
    else:
        pcm = SM.chirp()
        what = "no --sample: the original test chirp (220 -> 1760 Hz, 0.15 s)"
    out = compose(raw, dt2_raw, pcm)
    rep = out["report"]
    return Result(payloads={MAIN_OS: out[MAIN_OS], DSP_STREAM: out[DSP_STREAM]},
                  extents=extents(firmware),
                  notes=[f"MACHINE SEL offers ONESHOT after SWARMER (type {OC.NEW_TYPE}); its SYN "
                         f"page is the DT2's, entries {rep['layout']['page_entries']}",
                         f"the sample: {what}",
                         f"MAIN OS {len(out[MAIN_OS]):,} B ({rep['edits']} edits + loader + chunk); "
                         f"section 7 {rep['dsp']['bytes']:,} B"])
