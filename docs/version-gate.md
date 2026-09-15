
# The OS-upgrade version gate on the DN2

`docs/STATUS.md` has carried an open item since 2026-09-15: *"Is there a
minimum-version gate on the DN2?"* — lalzart records MAIN validating a content
checksum, **minimum version** and the cryptographic trailer before erase and
program, and nothing in this repository had checked it.

**2026-09-16: confirmed from our own image, and partially located.** The gate
exists, it is in MAIN OS as lalzart says, and its failure message is found.
The exact comparison is not yet read.

## What is established

**The upgrade error-string table is at `0x40208748`**, six entries indexed by
`validator_return - 1`:

| index | string |
|---|---|
| 0 | `No error` |
| 1, 2, 3 | `Checksum failed` |
| 4 | `Power adapter must be connected` |
| **5** | **`Unsupported downgrade`** |

**The consumer is the OS-upgrade receive state machine, `0x40129c56`.** It walks
incoming SysEx (`0xF0`/`0xF7` = 240/247 framing), and at `0x40129e1c` calls a
validator; a return of 1 advances the state, anything else is turned into an
error index by `subql #1,%d0`, bounded to 5, and looked up in the table at
`0x40129e70`.

```
0x40129e1c  jsr 0x400dbc4c      ; validate
0x40129e24  moveq #1,%d1
0x40129e26  cmpl %d0,%d1
0x40129e28  bnes 0x40129e68     ; not 1 -> error path
0x40129e68  subql #1,%d0        ; error index
0x40129e6a  moveq #5,%d1        ; bound
0x40129e70  lea 0x40208748,%a0  ; the table
```

**A second, independent string exists in the UI**: `Downgrade not possible` at
`0x4021f3bc`, loaded as an immediate at `0x401095d0` in a six-way jump table of
error messages (beside `Missing data!` and `Checksum error!`) — a different
error-code-to-string mapper, reached from the upgrade menu.

So **the DN2 does refuse a downgrade, and says so in two places.** That is the
open item answered in the affirmative, from our image rather than from lalzart's
account — the two now agree.

## What is not yet established

**Which comparison produces the downgrade code.** The validator the state
machine calls, `0x400dbc4c`, is only 52 bytes and cannot be it:

```
0x400dbc54  jsr 0x40122418     ; zero -> return 3
0x400dbc66  jsr 0x400d2a60     ; false -> return 4, true -> return 1
```

It returns **1, 3 or 4** — indices 0, 2 and 3, all `No error` or
`Checksum failed`. **It never returns 6**, which is the value that would index
`Unsupported downgrade`.

So the downgrade verdict is produced on a different path — either inside
`0x400d2a60`/`0x40122418` by a route that reports separately, or by another
caller of the same display code. **Do not assume the version compare lives in
`0x400dbc4c`.**

## Next, cheapest first

1. Read `0x40122418` and `0x400d2a60` — the two checks the validator delegates
   to. One of them may carry the version comparison and report it elsewhere.
2. Find every writer of the state field `%a2@(4)` in `0x40129c56`'s object, and
   every other caller of the `0x40208748` lookup — the value 6 has to be written
   somewhere.
3. Compare against the **container version string at header `+0x13`** (`"1.11"`
   on this image, with the build string `"0059"` at `+0x08` and the u32 product
   code 52 at `+0x04`) — whatever parses that string is a short path to the
   comparison.

## Why it matters

A minimum-version gate constrains **flashing a downgraded or modified image**.
This project's recovery path is to reflash stock from the Early Start-up Menu —
if that menu's path runs the same gate, flashing an *older* stock image than the
resident one could be refused. That has never been tested here, and it is worth
knowing before it is needed rather than during a recovery.
