# The symbol map, and the Ghidra workflow

Reverse-engineering this firmware produces two kinds of name, and they are kept
differently.

**Names the image already carries** — GCC left RTTI and mangled symbols in MAIN
OS, several hundred of them. These are *derived*, never written down: `dnfw
symbols` and `dnfw symbolmap` recover them from the bytes each time.

**Names a person assigned by analysis** — the receive handler, the parameter
table, the service dispatcher. No scan recovers these; they are the knowledge
the project accumulates. They live in `symbols/*.py` as curated records, and
`dnfw symbolmap` merges them with the RTTI and emits a script that seeds a fresh
Ghidra project with both.

## No Elektron bytes are committed

A curated symbol carries an **address**, a **name**, an **evidence note**, and a
**guard** — and the guard is a *SHA-256 of the bytes at the address*, never the
bytes. So `symbols/` holds our analysis and a set of digests, and no firmware.
The guard still does its job: `symbolmap` recomputes it from the image you
supply and reports any symbol whose bytes no longer hash to it — an address that
drifted between OS builds, or a wrong reading. This is the `STOCK_SHA256` idea
from the patch model, applied per symbol.

The two things that *are* Elektron IP — the Ghidra project (`.gpr`, it embeds
the firmware) and any decompiled `.c` you export — are generated locally and
never committed. Keep them under `00_Resources/` or `ghidra/*.gpr`, both
gitignored.

## Commands

```
dnfw symbolmap <image> --section 3            # list curated + RTTI for MAIN OS
dnfw symbolmap <image> --section 2            # the bootstrap
dnfw symbolmap <image> --section 3 --ghidra apply_names.py
```

The last writes a Jython script that names functions, labels data, and attaches
each evidence note as a comment. A curated symbol whose guard no longer matches
is listed as skipped, not applied — so running a 1.10E map against a later build
labels only what still lines up.

## Seeding a Ghidra project (Windows, native)

Ghidra runs without WSL (`docs/mainos-image.md`). To open MAIN OS named:

1. Extract the section and note its base:
   ```
   dnfw extract <image> --section 3 -o out/     # MAIN OS, base 0x40000400
   dnfw extract <image> --section 2 -o out/     # bootstrap; run base 0x800003fc
   ```
   The bootstrap's ELE3 dest is `0x02000000` but it **runs** at `0x800003fc`
   (`docs/bootstrap.md`); import it there, not at the dest, or the addresses and
   the string references will not line up.
2. Analyse it, keeping the project:
   ```
   ghidra\analyze.bat 00_Resources\03_Ghidra dn2_mainos out\section_3_MAIN_OS.aplib.bin 0x40000400
   ```
3. Generate and run the seeding script:
   ```
   dnfw symbolmap <image> --section 3 --ghidra 00_Resources\03_Ghidra\apply_names.py
   ```
   Run it from the Ghidra GUI's Script Manager, or as a `-postScript` to a
   second `analyze.bat` pass.
4. Open the project in the **GUI** — `ghidraRun.bat` in the Ghidra install — to
   browse it: decompiler beside the disassembly, cross-references, click to
   rename.

## Feeding renames back

When the GUI teaches you a new name worth keeping, add it to `symbols/*.py`: the
address, a name, an evidence note pointing at the doc that explains it, and a
guard. Compute the guard with `dnfw` rather than by reading bytes into the file:

```
python -c "import hashlib,pathlib; from dnfw.firmware.load import load; \
from dnfw.cli.files import read_image; \
c=load(read_image(pathlib.Path('<image>'))).container.find(3).unpack(); \
o=<addr>-0x40000400; print(hashlib.sha256(c[o:o+16]).hexdigest())"
```

That keeps the loop closed: analysis in the GUI, the durable names in
`symbols/`, and a script that rebuilds the named project for the next reader —
with no firmware in the repository.
