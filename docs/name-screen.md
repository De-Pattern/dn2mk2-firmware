# The stock NAME screen: can ours be the Digitone II's own? (first read, 2026-11-14)

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
