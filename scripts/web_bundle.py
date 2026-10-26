"""Bundle the build's Python for dn2-tools' in-browser patcher (tools/patcher).

    python scripts/web_bundle.py BUILD.syx VERSION NAME OUTDIR

BUILD.syx must be a gated build (its .gate.json beside it, CLEARED, same sha256). This
builds it again here from the stock files, noting every dnfw module and data file the
build touches, checks the rebuild is byte-identical to BUILD.syx, and writes
OUTDIR/dnfw-VERSION.zip (those files and tools/patcher/dn2patch.py) and adds the version
to OUTDIR/builds.json. The zip holds only this repository's code: the build reads
Elektron's files from the owner's own copies, in the browser as here."""

from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def main() -> int:
    build, version, name, outdir = sys.argv[1:5]
    build = pathlib.Path(build)
    outdir = pathlib.Path(outdir)
    want = hashlib.sha256(build.read_bytes()).hexdigest()
    gate = json.loads(pathlib.Path(str(build) + ".gate.json").read_text())
    if gate.get("sha256") != want or not gate.get("gates") or \
            not all(str(v).startswith(("PASS", "n/a")) for v in gate["gates"].values()):   # n/a: a data-only chunk
        print("not a gated build: its .gate.json does not clear this sha256")
        return 1
    touched: set[str] = set()

    def hook(ev, args):
        if ev == "open" and isinstance(args[0], str):
            touched.add(os.path.abspath(args[0]))
    sys.path.insert(0, str(SRC))
    sys.addaudithook(hook)
    from dnfw.cli.main import main as dnfw
    tmp = outdir / "_rebuild.syx"
    rc = dnfw(["mods", "apply", str(ROOT.parent / "Digitone_II_OS1.11.syx"), "--mod", "waverider",
               "-o", str(tmp)])
    if rc not in (0, None) or not tmp.is_file():
        print("the rebuild stopped")
        return 1
    got = hashlib.sha256(tmp.read_bytes()).hexdigest()
    tmp.unlink()
    if got != want:
        print(f"the rebuild differs: {got}")
        return 1
    files = {pathlib.Path(m.__file__).resolve() for k, m in list(sys.modules.items())
             if k.split(".")[0] == "dnfw" and getattr(m, "__file__", None)}
    files |= {pathlib.Path(p) for p in touched if p.startswith(str(SRC / "dnfw")) and not p.endswith(".pyc")}
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(files):
            z.writestr(zipfile.ZipInfo(str(f.relative_to(SRC)), (2026, 1, 1, 0, 0, 0)), f.read_bytes(),
                       compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo("dn2patch.py", (2026, 1, 1, 0, 0, 0)),
                   (ROOT / "tools" / "patcher" / "dn2patch.py").read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    zname = f"dnfw-v{version}.zip"
    (outdir / zname).write_bytes(zbuf.getvalue())
    man = outdir / "builds.json"
    rows = json.loads(man.read_text()) if man.exists() else []
    rows = [r for r in rows if r["version"] != version]
    row_inputs = ["dn2", "dt2", "md"]
    mnm = sys.modules.get("dnfw.mnm.rom")      # v0.26: the build read the Monomachine OS too
    if mnm is not None and str(mnm.path().resolve()) in touched:
        row_inputs.append("mnm")
    rows.insert(0, {"version": version, "name": name, "sha256": want, "zip": zname, "inputs": row_inputs,
                    "zip_sha256": hashlib.sha256(zbuf.getvalue()).hexdigest(),
                    "file": f"DN2mod_v{version}_{name}_OS1.11.syx"})
    man.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"{zname}: {len(files)} files, {len(zbuf.getvalue())} bytes; rebuild matches {want[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
