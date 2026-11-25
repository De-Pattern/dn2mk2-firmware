# The stock NAME screen for our names (built in v0.54, 2026-11-15)

Owner, 2026-11-14: our sample and recording namer works, but it would be nicer if it were
the stock Elektron one: the same screen, keys and feel. The open question is whether the
stock screen can be given our name and hand it back on YES/NO, or whether it is tied to
saving a project or preset.

## What the MAIN OS has (DN2 OS 1.11, `section_3_MAIN_OS.bin`, read from the image)

- **A class of its own, `NameView`.** Its RTTI names are at `0x4021f7b4` (`8NameView`), with
  `8NameCopy` beside it (the clipboard for COPY NAME / PASTE NAME). The mangled lambda names
  carry its constructor's signature:
  `NameView::NameView(std::string, std::string, int, int, bool, std::string, std::function<void(std::string, int)>)`.
  That reads as a title, the starting name, two ints (likely the length limit and the cursor
  or mode), a flag, one more string, and **a callback that receives the result** (the name
  and an int, likely YES/NO). There is also `NameView::consumeKeyEvent(KeyEvent&)`.
- **Its key hints**, in the order the screen lists them, at `0x4021f71a..`: `FUNC+ARROW:EDIT`,
  `FUNC+NO:DELETE`, `FUNC+YES:INSERT`, `SETTINGS:RANDOM`, `U/D:CHAR +/-`, `L/R:MOVE CURSOR`,
  `NO:ABORT`, then `<<`, `>>`, `Name`, `COPY NAME`, `NAME CLEAR`, `PASTE NAME`.
- **Its code** sits around `0x4010e000..0x4010e700`: the hint strings are referenced from
  `0x4010e01e`, `0x4010e0de`, `0x4010e106`, `0x4010e2e4`, `0x4010e5a0` and `0x4010e666`, and
  `0x4010e6e8` pushes the class name.

## What that means

The screen is a **generic view**, not a part of project or preset saving: it takes the name
in and reports it out through a `std::function`. So it can in principle be opened with our
sample name, and our code told the result on YES or NO.

## What calling it would take (not done yet)

1. Find the constructor and one stock caller, such as the project or sound NAME, to learn how
   a `NameView` is made (`make_shared`, then pushed on the view controller).
2. Build the arguments from C: two old-ABI (COW) `std::string`s, and a `std::function` whose
   invoker is a function of ours. That means matching libstdc++'s layout exactly.
3. Find how a view is pushed and popped, and whether the callback runs before or after the
   pop.
4. Gate it: an emulator step that opens the stock screen on a sample, types, and checks that
   YES renames the sample and NO leaves it unchanged.

If step 2 proves fragile, the fallback is to copy its behaviour exactly into ours: the 35
characters, FUNC+ARROW EDIT, SETTINGS RANDOM and the copy/paste name. This is queued after
the stereo test build, with the MD/MM rewrite and the full sweep (`docs/full-sweep.md`).

## Built (v0.54)

Correction to the first read: the image is loaded at 0x40000400, not 0x40000000 (the
addresses above are 0x400 low). Read again on the right base:

- **NameView**'s constructor is `0x40119156(this, title, name, id, max, prefixed, prefix,
  callback)` (strings and the std::function by pointer, the caller destroying them).
  `0x40119304` is the same with the prefix `%03d:`. The view is 160 bytes, with five vtables
  and the primary at `0x40206ac0`.
- **PATTERN NAME** (`0x400795ba`) makes it in place: an `_Sp_counted_ptr_inplace` block
  (vtable `0x401e0bc8`, use 1, weak 1, the object pointer) of `0xb0` bytes with the view at
  +16, then `View::open(child, 0)` (`0x4011c8be`) on its own view.
- **MainScreenView** is held in a static `shared_ptr` at `0x44647980`. Its controller (+44)
  is the screen we draw over (`wr_screen_obj`).
- **The callback** is invoked as `invoker(functor, std::string *, int id)` (old libstdc++:
  the int by value), only on YES. NO closes the view without it.

`csrc/sampler/rec.c` (`sn_open`, `sn_poll`): FILE NAME (after a recording), the browser's
RENAME and CREATE FOLDER open the stock screen on the name, titled FILE NAME, SAMPLE NAME or
FOLDER NAME.
- **While it is up:** every key is stock's (`smp_question_up`), and nothing of ours draws
  (`page.c`).
- **YES:** the callback keeps the name, and the next UI pass finishes as our screen's YES did.
- **NO:** the view gone without a result is our screen's NO.
- **Fallback:** if the main view is not there, or its controller is not the screen, our own
  screen stays in use.

Found on the way: operator new (`0x40120264`) returns in d0, and our compiler reads a
pointer return from a0, so the C declares it as returning a `u32`.

**Gate:**
- **`recflow`:** spells AB with the stock screen's keys, and its YES names the recording.
- **`stockname`:** the screen up, drawn, opened once; its NO on to ASSIGN with no result. Its
  negative control (the main view pointer cleared): our own screen, nothing opened.
- **`drive`:** CREATE FOLDER through it.

**Hardware only:** the screen's look and keys as on the unit.
