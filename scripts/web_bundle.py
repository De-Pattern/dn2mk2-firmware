"""Bundle the build's Python for dn2mk2's in-browser patcher (tools/patcher).

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


STOCK = pathlib.Path(os.environ.get("DN2_STOCK_DIR", ROOT.parent / "stock"))
STOCK_FILES = {"dt2": "Digitakt_II_OS1.17.syx", "md": "Elektron_SPS1-1UW_OS1.63.syx",
               "mnm": "Elektron_SFX6-60_OS1.32B.syx"}


def isolated_rebuild(zbytes: bytes, version: str) -> str:
    """the zip's build, run as the browser runs it -> its sha256 (or an error's text)"""
    import subprocess
    import tempfile
    for f in STOCK_FILES.values():
        if not (STOCK / f).is_file():
            return f"no {STOCK / f} (set DN2_STOCK_DIR to the folder with Elektron's files)"
    with tempfile.TemporaryDirectory() as td:
        run = pathlib.Path(td)
        (run / "code").mkdir()
        with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
            z.extractall(run / "code")
        (run / "VERSION").write_text(version + "\n")     # as patcher-worker.js writes it
        prog = (
            "import sys, pathlib\n"
            "sys.path.insert(0, sys.argv[1] + '/code')\n"
            "import dn2patch\n"
            "dn2patch.WORK = pathlib.Path(sys.argv[1] + '/work')\n"
            "print('SHA=' + dn2patch.build(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[1] + '/out.syx',"
            " mnm=sys.argv[5]))\n")
        r = subprocess.run([sys.executable, "-I", "-c", prog, str(run), str(ROOT.parent / "Digitone_II_OS1.11.syx"),
                            str(STOCK / STOCK_FILES["dt2"]), str(STOCK / STOCK_FILES["md"]),
                            str(STOCK / STOCK_FILES["mnm"])], cwd=td, capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith("SHA="):
                return line[4:]
        return (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "no output"


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
    # v0.40: rebuild from the zip ALONE, as the browser does (patcher-worker.js: the zip in
    # RUN/code, the version as RUN/VERSION, nothing from this repository), in a clean
    # interpreter. v0.39's bundle passed the in-repo rebuild above but stopped in the
    # browser: the build read VERSION from the repository, which the zip does not carry.
    iso = isolated_rebuild(zbuf.getvalue(), version)
    if iso != want:
        print(f"the zip alone does not rebuild the cleared file: {iso}")
        return 1
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
