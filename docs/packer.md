# The optimal packer (v0.65)

**Why.** v0.64 HOLD left 291 bytes of the 2 MiB the USB upgrade can take
(`docs/usb-upgrade-limit.md`); every feature after it needed room. The image's size is the
*compressed* size of the sections the build changes (MAIN OS, 3, and the DSP program, 7), and
they were packed by `codec/aplibpack.py`: greedy matching with one step of lookahead, chosen in
2026-09 because a full parse was out of reach in Python.

**What.** `codec/apopt.c` chooses the tokens by a forward dynamic program over every byte (the
least bits to reach each position; the last offset carried along each best path; a 1,024-deep
2-byte hash chain, nearest offset first for each length). Same format, same cost model, same
limits as aplibpack (offset at most 1,044,480, inside Elektron's 1 MiB window; length at most
2,048; min 3 past offset 3,328). The bits are still written by aplibpack's own `_Writer`
(`codec/aplibopt.py`). `container.section.compress` uses it and depacks every stream it makes
before using it.

| v0.64 HOLD's sections | greedy (v0.64) | optimal | |
|---|---|---|---|
| 3 MAIN OS (3,449,156 B) | 1,291,136 | 1,219,072 | -72,064 |
| 7 DSP (1,018,432 B) | 653,056 | 637,984 | -15,072 |
| USB bytes free | 291 | **87,454** | |

**One source, three runs, the same tokens.** The build runs natively (the gate) and in the
browser under Pyodide (the patcher, which must make the cleared file byte for byte):
- native: apopt.c compiled with the system's `cc` into a cached shared library, through ctypes;
- pyodide: `codec/apopt.wasm` (`scripts/build_apopt_wasm.py`: clang wasm32, no libc), through
  the browser's WebAssembly;
- node: the same apopt.wasm under node (`DNFW_APOPT=node`): web_bundle's rebuild from the zip
  alone uses it, so a bundle is refused unless the WebAssembly planner rebuilds the cleared file.

Integer arithmetic on fixed-width types only, so the two agree (`test/test_apopt.py`: native =
wasm on every case; the wasm is the committed C's build). Measured 2026-11-20 on v0.65-dev:
native, node, and the whole patcher build under Pyodide 0.27.7 in node
(`scripts/pyodide_rebuild.mjs`, 87 s; v0.24's took 3.4 min) all give sha256 355fa022....

**The instrument's own depacker agrees.** The gate's new step `depack`
(`scripts/emu_depack_check.py`) runs the bootstrap's aPLib routine (0x80000432, digikit's
emu.oracle, from stock's untouched section 2) on every compressed section the build changed:
it must give exactly our bytes (v0.65-dev: section 3 in 98 s, section 7 in 42 s, both
identical). Negative control: one flipped byte in a stream does not give its content back.
The preflight's existing check (`firmware.verify._limits`) still holds every stream to the
window and the match cap.

**What it does not change.** The token types and their bit layout are the ones every build since
v0.3 has used; only which matches are taken. Sections the build does not touch (2, 4, 5, 8)
are stock's bytes, as before. `aplibpack.pack` stays (the JS port's test pins its bytes).
