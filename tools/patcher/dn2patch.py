"""The DN2 mod patcher, run in the browser (Pyodide) by dn2mk2's index.html.

It builds the mod from the owner's own files, the same way the gated build was made, and
the page then checks the result's sha256 against the gated build's. Nothing of Elektron's
is shipped with it: the DN2 OS 1.11 file is patched, the DT2's DSP image (section 7 of DT2
OS 1.17), the Machinedrum's OS 1.63 and (v0.26 on) the Monomachine's OS 1.32B are read for
their tables.

    build(dn2, dt2, md, out, mnm=None, dn2_112=None) -> the sha256 of OUT

v0.73-t1 (docs/os112-port.md): a version for OS 1.12 also reads the owner's stock 1.12 file. The
build is made on 1.11 exactly as before, then ported to 1.12 by replaying its recipe
(`osport_recipe.json` in the bundle: offsets and addresses only, made by `dnfw.osport.port.recipe`
from the cleared build), and the result is assembled on the 1.12 file.
"""

from __future__ import annotations

import hashlib
import os
import pathlib

WORK = pathlib.Path("/work")
DT2_SEC7_SHA = "0f514a12a2255f5c081e292c47f1f29462003177658da4bbae0a22fd737fffa2"


class PatchError(Exception):
    pass


def unzip(data: bytes, exts: tuple[str, ...]) -> bytes:
    """The file itself, or the one file ending in EXTS inside a .zip (as Elektron ship them)."""
    if data[:4] != b"PK\x03\x04":
        return data
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(exts) and "__MACOSX" not in n]
        if len(names) != 1:
            raise PatchError(f"expected one {'/'.join(exts)} file in the .zip, found {len(names)}")
        return z.read(names[0])


def md_image(data: bytes) -> bytes:
    """The Machinedrum UW OS 1.63 flash image: the .bin as it is, or rebuilt from
    Elektron's .syx (64 bytes a message, its address in 6 nibbles, 16 bits in three
    7-bit bytes). The parts the syx does not carry stay 0xFF; the build reads only the
    compressed chain from 0x4000, which the syx carries whole."""
    if len(data) == 8 << 20:
        return data
    img = bytearray(b"\xff" * (8 << 20))
    i = n = 0
    while True:
        a = data.find(b"\xf0", i)
        if a < 0:
            break
        b = data.find(b"\xf7", a)
        if b < 0:
            break
        m = data[a:b + 1]
        i = b + 1
        if len(m) != 112 or m[1:6] != b"\x00\x20\x3c\x02\x00" or m[6] != 0x7E:
            continue
        addr = 0
        for k in range(9, 15):
            addr = (addr << 4) | (m[k] & 0x0F)
        if addr + 64 > len(img):
            raise PatchError("the Machinedrum file has an address past its flash")
        p = m[15:-1]
        for k in range(0, 96, 3):
            v = (p[k] << 14) | (p[k + 1] << 7) | p[k + 2]
            img[addr + 2 * (k // 3)] = v >> 8
            img[addr + 2 * (k // 3) + 1] = v & 0xFF
        n += 1
    if n < 1000:
        raise PatchError("that is not the Machinedrum UW OS 1.63 file (.syx or .bin)")
    return bytes(img)


def dt2_section7(data: bytes) -> bytes:
    from dnfw.firmware.load import load
    try:
        sec = load(data).container.find(7)
    except Exception as e:                       # noqa: BLE001 -- any parse failure
        raise PatchError(f"that is not a Digitakt II OS file ({e})") from None
    body = sec.unpack() if sec is not None else None
    if body is None or hashlib.sha256(body).hexdigest() != DT2_SEC7_SHA:
        raise PatchError("that is not Digitakt II OS 1.16 or 1.17 (its DSP image differs)")
    return body


def build(dn2: str, dt2: str, md: str, out: str, mnm: str | None = None,
          dn2_112: str | None = None) -> str:
    WORK.mkdir(parents=True, exist_ok=True)
    d = WORK / "dn2.syx"
    d.write_bytes(unzip(pathlib.Path(dn2).read_bytes(), (".syx",)))
    dn2 = str(d)
    s7 = WORK / "dt2_section7.bin"
    s7.write_bytes(dt2_section7(unzip(pathlib.Path(dt2).read_bytes(), (".syx",))))
    mdb = WORK / "md_os163.bin"
    mdb.write_bytes(md_image(unzip(pathlib.Path(md).read_bytes(), (".syx", ".bin"))))
    os.environ["DT2_SECTION7"] = str(s7)
    os.environ["MD_OS_BIN"] = str(mdb)
    from dnfw.md import rom
    try:
        rom.blocks()
    except Exception as e:                       # noqa: BLE001
        raise PatchError(f"that is not the Machinedrum UW OS 1.63 ({e})") from None
    if mnm is not None:                          # v0.26: the Monomachine machines' tables
        mb = WORK / "mnm_os132b.syx"
        mb.write_bytes(unzip(pathlib.Path(mnm).read_bytes(), (".syx",)))
        os.environ["MNM_OS"] = str(mb)
        from dnfw.mnm import rom as mnm_rom
        try:
            mnm_rom.blocks()
        except Exception as e:                   # noqa: BLE001
            raise PatchError(f"that is not the Monomachine SFX-6 OS 1.32B ({e})") from None
    else:                                        # (v0.24, v0.25: none)
        os.environ["MNM_OS"] = str(WORK / "no-mnm")
    from dnfw.cli.main import main
    out11 = out if dn2_112 is None else str(WORK / "build_OS1.11.syx")
    rc = main(["mods", "apply", dn2, "--mod", "waverider", "-o", out11])
    if rc not in (0, None) or not pathlib.Path(out11).is_file():
        raise PatchError("the build stopped (see the log); is that DN2 OS 1.11?")
    if dn2_112 is not None:
        port_to_112(out11, unzip(pathlib.Path(dn2_112).read_bytes(), (".syx",)), out)
    return hashlib.sha256(pathlib.Path(out).read_bytes()).hexdigest()


def port_to_112(build11: str, stock12: bytes, out: str) -> None:
    import json
    from dnfw.firmware.load import load
    from dnfw.osport import port
    rec = json.loads((pathlib.Path(__file__).with_name("osport_recipe.json")).read_text())
    try:
        s12 = {x.id: x for x in load(stock12).container.sections}
    except Exception as e:                       # noqa: BLE001
        raise PatchError(f"that is not a Digitone II OS file ({e})") from None
    if s12[3].unpack() is None or len(s12[3].unpack()) != rec["stock12_length"]:
        raise PatchError("that is not stock Digitone II OS 1.12")
    b11 = {x.id: x for x in load(pathlib.Path(build11).read_bytes()).container.sections}
    try:
        main12 = port.replay(rec, b11[3].unpack(), s12[3].unpack())
        pathlib.Path(out).write_bytes(port.assemble(stock12, main12, b11[7].unpack()))
    except port.PortError as e:
        raise PatchError(f"the port to 1.12 stopped: {e} (is the second file stock DN2 OS 1.12?)") from None
