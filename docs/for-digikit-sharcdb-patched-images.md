# For digikit: `tools/sharcdb.py` on patched DN2 images (2026-09-27)

Written for m-dwyer/digikit. We used `sharcdb` (`work/sharc-emulator`, `2cd02ee`,
DB_VERSION 13) as a tool on stock DN2 1.11, DT2 1.16 and six modified DN2 section 7s.
It did the job. Below are the rough edges we hit. None of them blocked us, so there is
no PR.

1. **Patched images need `--blocks`, and the indices depend on the stream.** A
   modified section 7 is refused, which is right, but the only override is a list of
   block indices. Our blocks happen to land at indices 94 and 95 because we insert
   before the final block, so the stock list plus `94,95` worked. A `--blocks-by-target
   0x28380548,...` form, or "the known image's code targets plus these", would survive
   any insertion.
2. **`decomp` is always empty for SHARC.** The schema comment says so. It would help
   if `build` logged it for a SHARC image, because the table's name suggests
   otherwise.
3. **`regdef` does not model implicit status writes.** ALU, shifter and multiplier
   ops set ASTAT flags, and FP ops set STKY, but only explicit `ASTATX`/`STKYX`
   writes appear. A question like "is ASTAT live across this splice point" still
   needs a hand listing.
4. **CJUMP renders as `CALL (linked, delayed)`.** Form 25a with the CJUMP bit is a
   jump plus `R2 = I6, I6 = I7` (SHARC+ PRM), with no PC-stack push. The text
   suggests a PC-stack call, which is what we were asked to rule out.
5. **`!!GAP!!` on `float_by` is loud for a common form.** The stock DN2 image uses
   `float_by` about 100 times (2a_short 41, 4a 43, ...). If the gap flag is still
   wanted, a count in the build report would be less alarming than a flag on every
   line.
6. **Build time.** About 160-280 s per image on a shared WSL machine, with two builds
   in parallel. The skip-rebuild check (sha256 + version) made re-runs free. Thanks.
