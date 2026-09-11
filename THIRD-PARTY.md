# Third-party notices

`dn_firmware` is licensed under the [GNU AGPL-3.0-or-later](LICENSE). Parts of
it are derived from the MIT-licensed projects below, which permits their
incorporation into an AGPL work provided their copyright and permission notices
travel with it. Those notices are reproduced here.

What was taken from each is set out in `docs/references.md`, and every module
that ports from one names its source — and, more usefully, names where it
diverges and why.

None of these projects is affiliated with Elektron, and neither is this one.

---

## elektron-firmware-tool

<https://github.com/mischa85/elektron-firmware-tool> — Marcel Bierling.

The reference for the SysEx transport, the ELE3 container, the aPLib codec and
the integrity algorithms. Ported into `src/dnfw/syx/`, `src/dnfw/codec/`,
`src/dnfw/container/`, `src/dnfw/integrity/` and `src/dnfw/firmware/build.py`.

> Copyright (c) 2026 Marcel Bierling

## octa-bt-pt

<https://github.com/bryantysinger/octa-bt-pt> — Bryan Tysinger.

The declarative patch model — patch records carrying the bytes they expect, a
guard that refuses the wrong image, and discovery over `patches/*.py`. Adapted
into `src/dnfw/patch/`.

> Copyright (c) 2026 Bryan Tysinger

## octabam

<https://github.com/sambanks/octabam> — Sam Banks.

The ColdFire V4e disassembly findings that `src/dnfw/cli/disasm.py` and
`docs/mainos-image.md` rest on, including the measurement that radare2's m68k
backend misreads this CPU silently. Its code-cave model is the intended
mechanism for Phase 2. No code has been ported yet; the debt here is to its
measurements and its method.

> Copyright (c) 2026 Sam Banks

## midisc

<https://github.com/bkkbrls-del/midisc> — Sam Banks.

The ColdFire `Asm` encoder (`tools/ot3_asm.py`) and the cave helpers
(`tools/midisc/util.py`) — every instruction encoding checked against a stock
instruction, `.w` branch displacements resolved rather than hand-typed. Ported
into `src/dnfw/patch/coldfire.py` and `src/dnfw/patch/cave.py`. Only the
CPU-level encoding transfers; nothing about the Octatrack's engine or memory
map is carried over.

> Copyright (c) 2026 Sam Banks

## octamax

<https://github.com/mxldyn/octamax> — Maxolydian.

midisc's upstream, credited in midisc's own notice. No code is ported from it
directly; its Octatrack architecture account is used only as a hypothesis to
test against the DN2, never as fact about it.

> Copyright (c) 2025-2026 Maxolydian

---

## The MIT License

They all carry the same terms:

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Not third-party, and not bundled

**Elektron firmware.** This repository contains none, and never will. `dnfw`
operates on an OS file you obtain yourself from Elektron. No key is stored
here either: the Digitone II signing key is recomputed at run time from
material inside the image you supply, and accepted only when it reproduces that
image's own digest.

**DNX**, the sibling project this one depends on for Digitone data formats,
shares no code with it. It is referenced, not incorporated.

**ems-octakit** (<https://github.com/emuyia/ems-octakit>) ships **no licence**,
so none of its code is used. It was read only for architecture — the idea of
assembling real `.S` with the GNU toolchain into linker-placed caves — and that
general technique, not its expression, informs `src/dnfw/patch/assemble.py`.
