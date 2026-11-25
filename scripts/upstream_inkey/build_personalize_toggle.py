"""An on/off item in SETTINGS > PERSONALIZE, for a mod's one-byte toggle.

Assembly shared by the mods that add a PERSONALIZE switch (reloadconfirm, arpscale).
A mod assembles `routines` and `append_item` into its own CODE chunk, defines the
label `item_name` (the item's text, `.asciz`) in the same source, and reaches
`append_item` from its own hook in `PersonalizeMenuView`'s constructor, with `%a4`
the view. Where each mod hooks the constructor is its own choice, so two mods with
items never hook the same bytes.

## The item

`PersonalizeMenuView`'s constructor `0x40097d48` builds its eleven items one
block each: four `std::function`s (16 bytes: functor, -, manager, invoker),
`new(0x54)`, `0x401170d8(item, &name, &press, &value, &adjust, -1, 8)`,
`0x4011690e(view, item)`, then each function's destructor `0x40188086`. PAGE
AUTOCOPY (`0x40098166`) is the model, an on/off item whose press and adjust
capture the view:

| function | PAGE AUTOCOPY's invoker / manager | here |
|---|---|---|
| name | `0x40096464` / `0x40096ee2` | `name`, the same manager |
| press | `0x400966d8` / `0x40096f34` (captures the view) | `press` |
| value | `0x40097802` / `0x40096f90` (ON/OFF from `*0x44644d84 + 28 * on`) | `value` |
| adjust | `0x4009670a` / `0x40096fe2` (captures the view) | `adjust` |

The stock managers are reused: they only allocate, copy and free the 1- or
4-byte functor, so they are right for ours.

## The toggle

One byte of the settings block's unaddressed tail (`scripts/build_reload_confirm.py`,
"Where the toggle lives"): saved and restored with the block, zero on a fresh
instrument, ignored by stock. Only the value 1 means on. `set` writes it only
through the stock setting writer `0x400bb4f8`, which re-signs the block.
"""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "src"))
from dnfw import osport  # noqa: E402

SETTINGS_WRITE = 0x400BB4F8     # (dst, src, n): write a setting, re-sign the block
NEW = 0x40120264                # operator new(size)
STR_CTOR = 0x401CE69E           # std::string(this, const char *, const alloc &)
FUNC_DTOR = 0x40188086          # std::function destructor(this)
ITEM_BUILD = 0x401170D8
ITEM_APPEND = 0x4011690E
REDRAW = 0x4011C7BA             # the view's redraw(view + 56)
VALUE_DRAW = 0x401157FC
ONOFF = 0x44644D84              # -> OFF; ON at +28
MGR_NAME, MGR_PRESS, MGR_VALUE, MGR_ADJUST = 0x40096EE2, 0x40096F34, 0x40096F90, 0x40096FE2

# Read, not written: the stock code the item relies on. A mod includes these in
# its guards.
CONTEXT = (
    (0x400BB4F8, bytes.fromhex("206f0008"), "the setting writer"),
    (0x40098174, bytes.fromhex("41fae2ee"), "PAGE AUTOCOPY: name 0x40096464"),
    (0x40098178, bytes.fromhex("43faed68"), "...its manager 0x40096ee2"),
    (0x40098622, bytes.fromhex("4e96"), "constructor: the item builder (%fp = 0x401170d8)"),
    (0x4009862C, bytes.fromhex("4e95"), "constructor: the append (%a5 = 0x4011690e)"),
    (0x40097846, bytes.fromhex("d0b944644d84"), "value text: the ON/OFF strings"),
)


def toggle(flag: int, os: str = "1.11") -> str:
    """Assembly: `get` -> `%d0` 1 when the toggle byte FLAG is on, else 0; `set(on)`
    writes it. For a mod whose toggle has no PERSONALIZE item."""
    return osport.render("""| -> %d0 1 when the toggle is on, else 0.
get:
    mvz.b   {flag:#x},%d0
    subq.l  #1,%d0
    seq     %d0
    andi.l  #1,%d0
    rts

| (on): the toggle, through the stock setting writer.
set:
    link    %a6,#-4
    moveq   #0,%d0
    tst.b   11(%a6)
    sne     %d0
    andi.l  #1,%d0
    move.b  %d0,-4(%a6)
    pea     1
    pea     -4(%a6)
    pea     {flag:#x}
    jsr     {SETTINGS_WRITE:#x}
    lea     12(%sp),%sp
    unlk    %a6
    rts

""", {**globals(), "flag": flag}, os)


def routines(flag: int, os: str = "1.11") -> str:
    """Assembly: the item's functions for the toggle byte FLAG: `toggle`'s `get` and
    `set`, then `name`, `press`, `value` and `adjust`, the item's invokers. `name`
    reads the label `item_name`."""
    return toggle(flag, os) + osport.render("""| name(&string, functor): the item's name (0x40096464).
name:
    link    %a6,#-4
    move.l  %d2,-(%sp)
    move.l  %a0,%d2
    pea     -1(%a6)
    pea     item_name
    move.l  %a0,-(%sp)
    jsr     {STR_CTOR:#x}
    lea     12(%sp),%sp
    move.l  %d2,%d0
    move.l  -8(%a6),%d2
    unlk    %a6
    rts

| press(functor): flip, redraw the view (0x400966d8).
press:
    move.l  %a2,-(%sp)
    move.l  8(%sp),%a0
    move.l  (%a0),%a2
    bsr.w   get
    eori.l  #1,%d0
    move.l  %d0,-(%sp)
    bsr.w   set
    addq.l  #4,%sp
    move.l  (%a2),%a2
    lea     56(%a2),%a2
    move.l  %a2,8(%sp)
    move.l  (%sp)+,%a2
    jmp     {REDRAW:#x}

| value(functor, out, x, y): ON or OFF (0x40097802).
value:
    bsr.w   get
    move.l  12(%sp),4(%sp)
    move.l  %d0,%d1
    lsl.l   #5,%d0
    lsl.l   #2,%d1
    sub.l   %d1,%d0
    add.l   {ONOFF:#x},%d0
    move.l  %d0,8(%sp)
    move.l  16(%sp),%d1
    addi.l  #11,%d1
    move.l  %d1,12(%sp)
    move.l  20(%sp),16(%sp)
    clr.l   20(%sp)
    jmp     {VALUE_DRAW:#x}

| adjust(functor, -, delta): on for a positive turn, off for a negative one
| (0x4009670a), and redraw.
adjust:
    move.l  %a2,-(%sp)
    move.l  %d2,-(%sp)
    move.l  12(%sp),%a0
    move.l  20(%sp),%d2
    move.l  (%a0),%a2
    bsr.w   get
    add.l   %d2,%d0
    bpl.s   1f
    moveq   #0,%d0
1:  moveq   #1,%d1
    cmp.l   %d1,%d0
    ble.s   2f
    move.l  %d1,%d0
2:  move.l  %d0,-(%sp)
    bsr.w   set
    addq.l  #4,%sp
    move.l  (%a2),%a2
    lea     56(%a2),%a2
    move.l  %a2,12(%sp)
    move.l  (%sp)+,%d2
    move.l  (%sp)+,%a2
    jmp     {REDRAW:#x}

""", {**globals(), "flag": flag}, os)


def append_item(os: str = "1.11") -> str:
    """Assembly: build the item from `routines`' functions and append it to the
    view in `%a4`. Leaves the stack as it found it; uses `%d6` and `%a3`, which a
    caller inside the constructor saves first, and the scratch registers."""
    return osport.render("""    lea     -64(%sp),%sp
    move.l  %sp,%a3
    pea     1
    jsr     {NEW:#x}
    move.l  %d0,(%a3)
    clr.l   4(%a3)
    lea     {MGR_NAME:#x},%a0
    move.l  %a0,8(%a3)
    lea     name,%a0
    move.l  %a0,12(%a3)
    pea     4
    jsr     {NEW:#x}
    move.l  %d0,%a0
    move.l  %a4,(%a0)
    move.l  %d0,16(%a3)
    clr.l   20(%a3)
    lea     {MGR_PRESS:#x},%a0
    move.l  %a0,24(%a3)
    lea     press,%a0
    move.l  %a0,28(%a3)
    pea     1
    jsr     {NEW:#x}
    move.l  %d0,32(%a3)
    clr.l   36(%a3)
    lea     {MGR_VALUE:#x},%a0
    move.l  %a0,40(%a3)
    lea     value,%a0
    move.l  %a0,44(%a3)
    pea     4
    jsr     {NEW:#x}
    move.l  %d0,%a0
    move.l  %a4,(%a0)
    move.l  %d0,48(%a3)
    clr.l   52(%a3)
    lea     {MGR_ADJUST:#x},%a0
    move.l  %a0,56(%a3)
    lea     adjust,%a0
    move.l  %a0,60(%a3)
    pea     0x54
    jsr     {NEW:#x}
    lea     20(%sp),%sp
    move.l  %d0,%d6
    pea     8
    pea     -1
    pea     48(%a3)
    pea     32(%a3)
    pea     16(%a3)
    move.l  %a3,-(%sp)
    move.l  %d6,-(%sp)
    jsr     {ITEM_BUILD:#x}
    move.l  %d6,-(%sp)
    move.l  %a4,-(%sp)
    jsr     {ITEM_APPEND:#x}
    pea     48(%a3)
    jsr     {FUNC_DTOR:#x}
    pea     32(%a3)
    jsr     {FUNC_DTOR:#x}
    pea     16(%a3)
    jsr     {FUNC_DTOR:#x}
    move.l  %a3,-(%sp)
    jsr     {FUNC_DTOR:#x}
    lea     52(%sp),%sp
    lea     64(%sp),%sp
""", {**globals(), }, os)
