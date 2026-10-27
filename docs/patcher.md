# The in-browser patcher (dn2mk2's patcher.html)

The mod's build is pure Python (the standard library only) and reads three files of
Elektron's: the DN2 OS 1.11 it patches, the DT2 OS 1.16/1.17 DSP image (section 7, for
the sample reader's tables) and the Machinedrum UW OS 1.63 (for PERC's MD machines). So the
same build runs in a browser under Pyodide, from the owner's own copies of those files,
and nothing of Elektron's is ever published.

- `tools/patcher/dn2patch.py` is the entry: it takes the three files as Elektron ship
  them (.syx, or inside their .zip; the MD as .syx or the 8 MB flash .bin), and runs
  `dnfw mods apply ... --mod waverider`, the gated builds' own recipe.
  - The MD's .syx is rebuilt into the flash image: 112-byte messages, each 64 bytes at
    the address in its bytes 9-14 (one nibble each), 16 bits in three 7-bit bytes. The
    syx carries the whole compressed chain from 0x4000, which is all the build reads
    (`dnfw.md.rom.blocks`); the bootloader below 0x4000 is not in it and stays 0xFF.
  - The DT2's section 7 comes from `dnfw.firmware.load`, checked against its sha256.
- `scripts/web_bundle.py BUILD.syx VERSION NAME OUTDIR` takes a gated build (its
  `.gate.json` beside it, every gate PASS, the same sha256), builds it again here noting
  every dnfw module and data file the build touches, checks the rebuild is byte-identical,
  and writes `OUTDIR/dnfw-VERSION.zip` and its row in `OUTDIR/builds.json`.
- `tools/web/patcher.html` and `patcher-worker.js` (copied to dn2mk2) run it in a
  worker with Pyodide 0.27.7 from jsDelivr. The worker checks the zip's sha256 against
  builds.json; the page saves the result **only if its sha256 is the cleared build's**.
  Anything else is shown as "does not match: do not flash".

Checked: v0.24's zip, run under Pyodide 0.27.7 in node from the DN2 1.11 .syx, the DT2
1.17 .syx and the MD 1.63 .syx, gave f5853cdb... (v0.24's cleared sha256) in 3.4 minutes.
The page itself, end to end in headless Chromium (the three files chosen, Build, the worker,
the sha256 compare): 202 s, "exactly v0.24's cleared file", Save enabled.
