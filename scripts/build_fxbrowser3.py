"""`fxbrowser2`, plus the one longword that makes Chorus say `CHR` and not `ERR`.

    python scripts/build_fxbrowser3.py

`fxbrowser2` is on the instrument and works: an LFO can be aimed at a Chorus,
Delay or Reverb parameter chosen by name from the `DEST` list, and it modulates.
One defect blocked shipping — the owner, 2026-09-23:

> "chorus section appears like ERR in the modal"
> "no, they show their correct short names (REV and DEL). That's why I reported
>  chorus only."

## The cause, which is one longword of Elektron's, not one byte of ours

`0x400dc3f0` is *the* group -> short-name lookup. It answers `'SYN'` for groups
0..4, `'ERR'` for anything above 30, and otherwise indexes a 26-longword table
at `0x401f76f4` with `group - 5`:

| group | slot | holds | reads |
|---|---|---|---|
| 16 Chorus | `0x401f7720` | `0x40210c9e` | **`'ERR'` — the out-of-range fallback's own pointer** |
| 17 Reverb | `0x401f7724` | `0x402107d2` | `'REV'` |
| 18 Delay  | `0x401f7728` | `0x40210919` | `'DEL'` |

And 17's and 18's pointers are not merely *strings* that read `REV` and `DEL` —
they are **the very pointers those groups' `<Group> Mix Vol.` records carry as
their own short name**: entry 129 `Reverb Mix Vol.` holds `0x402107d2` at +56,
entry 120 `Delay Mix Vol.` holds `0x40210919`. Group 16's slot does *not* hold
entry 111 `Chorus Mix Vol.`'s `'CHR'` at `0x4021077c`; it holds the fallback.
The symmetry is exact everywhere except the one slot the owner is looking at.

So this build writes `0x4021077c` into `0x401f7720`, and nothing else.

## Why this explains all three groups, which is what §22's dead leads did not

The rule §22 paid for: *a mechanism that accounts for Chorus and says nothing
about Delay and Reverb has been fitted to the symptom, not tested by it.* This
one is read off the same table for all three and predicts each one's observed
behaviour separately — Chorus `ERR`, Reverb `REV`, Delay `DEL` — before it
predicts anything about the fix. `scripts/emu_fxname.py` runs `0x400dc3f0` on a
booted machine for every group and refuses to report Chorus at all unless 17 and
18 come back `'REV'` and `'DEL'` first.

It also explains why every one of the six dead leads failed. They were all about
the *records*, and the name is not on a record: the section title comes from a
**group** table that no record edit can reach, and which the destination modal
reads only when a row is drawn.

## The scope of the edit, measured rather than asserted

`lea 0x401f76f4,%a0` at `0x400dc404` is the **only** longword in the image that
names the table. The scan covered every longword in the section holding a value
within +/-104 bytes of the base — the table's own length — and found two: that
`lea`, and `0x400dc266 -> 0x401f775c`, which is the *next* table starting where
this one ends. So there is one reader, and changing group 16's slot changes
group 16's name everywhere and nothing else's anywhere.

Groups 19, 20 and 22 also read `'ERR'` in this table. They are left alone: no
build enumerates them, and a name invented for a group nothing shows would be
this project's own invention appearing on an Elektron screen.

## What this build cannot gate, said before it is built

The modal is drawn by a panel this emulator does not have, so *"the header now
reads CHR"* is the instrument's question. What is gated is that `0x400dc3f0`
returns `'CHR'` for group 16 and is bit-for-bit unchanged for every other group,
that the destination modal's rows for Chorus resolve their text through that
table, that nothing outside the declared edits moved, and that the image boots
from reset.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_fxbrowser as one                                 # noqa: E402
import build_fxbrowser2 as two                                # noqa: E402

NAME_TABLE = 0x401F76F4       # 26 longwords, indexed by `group - 5`
CHORUS_SLOT = NAME_TABLE + 4 * (16 - 5)     # 0x401f7720

# Every address this build reasons from, asserted against the stock image before
# a byte is written. The three record pointers are here because the argument for
# the fix is the symmetry between them and the table, and an argument that is
# not checked is prose.
CONTROLS = (
    (0x400DC404, "41f9401f76f4",
     "lea 0x401f76f4,%a0 -- the table's only reader"),
    (0x400DC418, "203c40210c9e",
     "movel #0x40210c9e,%d0 -- `ERR`, what a group above 30 gets"),
    (CHORUS_SLOT, "40210c9e", "group 16 Chorus -> 'ERR', the fallback's pointer"),
    (NAME_TABLE + 4 * (17 - 5), "402107d2", "group 17 Reverb -> 'REV'"),
    (NAME_TABLE + 4 * (18 - 5), "40210919", "group 18 Delay  -> 'DEL'"),
    (0x4021077C, "43485200", "'CHR' -- the string this build points group 16 at"),
    (0x401F99C8, "4021077c", "entry 111 'Chorus Mix Vol.' short name = 'CHR'"),
    (0x401F9E00, "402107d2", "entry 129 'Reverb Mix Vol.' short name = group 17's"),
    (0x401F9BE4, "40210919", "entry 120 'Delay Mix Vol.'  short name = group 18's"),
)

EDIT = (CHORUS_SLOT, "40210c9e", "4021077c",
        "group 16 Chorus: 'ERR' -> 'CHR', entry 111's own short name")


if __name__ == "__main__":
    anchor = one.ANCHORS[3_192_192]
    anchor["convert"] = anchor["convert"] + two.MISSED        # fxbrowser2's four
    anchor["controls"] = anchor["controls"] + CONTROLS
    one.EXTRA_LONGWORDS.append(EDIT)
    one.OUT = pathlib.Path("00_Resources/02_Builds/fxbrowser3_DN2_1.11.syx")
    one.SECTION_OUT = pathlib.Path("out/fxbrowser3/section_3_MAIN_OS.bin")
    raise SystemExit(one.main())
