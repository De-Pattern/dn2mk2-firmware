# The emulator, and how this repository refers to one it does not own

`m-dwyer/digikit` emulates the Digitone II's control processor well enough to
boot the OS, render the panel and take encoder input (`docs/references.md`).
This records how it is wired in, and why that way.

## Where it lives

```
00_Resources/01_Reference/digikit/     a plain git clone, tracking origin/main
```

`00_Resources/` is gitignored **wholesale**, so nothing of digikit's enters this
repository. That is the same place the other seven reference repositories live,
and consistency is most of the reason.

## Why a plain clone and not a submodule

Three ways to depend on someone else's repository, and only one suits this:

| | what it does | why not / why yes |
|---|---|---|
| **submodule** | records URL + **a pinned commit** inside our tree | it writes a **GPL-2.0 dependency into a public AGPL repository's history** — legal, but a statement about this project that is not true: we *run* digikit, we do not build on it. It also pins rather than tracks, so "tied to main" needs `git submodule update --remote` and a commit every time; and it leaves contributors on a detached HEAD, which is how stale pointers get committed |
| **subtree / vendoring** | copies their source into our tree | licence mixing and bloat, and this repository holds only its own code and docs |
| **plain clone, gitignored** ✅ | an ordinary working copy beside the others | simplest; `git pull` tracks their `main` with no ceremony; **zero entanglement** — nothing about digikit appears in our history, which keeps the AGPL/GPL question academic for as long as we only run it |

**It is not in `ZZ_Personal/` root** because that level is for the owner's own
projects — `DNX` is a sibling because the owner wrote it. digikit is
third-party tooling used by *this* project. If DNX ever needs it too, promote it
then; premature promotion just puts a shared dependency somewhere nobody owns.

## Tracking their main — and the discipline that makes it safe

```sh
cd 00_Resources/01_Reference/digikit
git pull                 # follows origin/main
git log --oneline -1     # <- record this
```

A plain clone follows `main` for free. The hazard is the opposite one: **their
main moves, and our findings drift without anyone noticing.** A result produced
against one revision of an emulator is not automatically true against the next,
and this project has already spent a week on results that were not what they
appeared to be.

> **Rule: every finding produced in the emulator records the digikit commit it
> was produced against**, in the same line as the finding. Not in a setup
> section, not once at the top of a file — beside the claim, like a date.

Because it is emphatically a *moving* dependency: the licence itself landed in
`c282f0c`, days after the repository became useful, and the README already
disagrees with the handover notes about what works.

### Working revision

| | |
|---|---|
| clone date | 2026-09-13 |
| commit | **`c282f0c`** — "Licence this GPL-2.0-or-later, because it cannot be MIT" |
| licence at that commit | GPL-2.0-or-later (`LICENSE` = GPL v2 text) |

## Running it on this machine

digikit needs **Python 3.12** and `uv`, and its Unicorn patch installs through a
shell script. This machine:

| | |
|---|---|
| Windows Python | 3.14.7 — **too new**, digikit pins 3.12 |
| WSL Python | **3.12.3** — correct |
| `uv` | not installed on either side |
| `tools/install-patched-unicorn.sh` | a shell script — wants a POSIX shell |

So **WSL is the natural home**, which is also where this project already reaches
for `m68k-linux-gnu-as` and `objdump` (`patch/assemble.py`, `image/objdump.py`).
The clone stays on the Windows side and is reached from WSL as
`/mnt/c/ZZ_Code/zz_personal/dn2_firmware/00_Resources/01_Reference/digikit`.

One caveat worth knowing before it wastes an hour: building a native extension
against a `/mnt/c` path is slow and occasionally trips on permissions. Put the
**virtualenv inside WSL's own filesystem** even when the source is on `/mnt/c`.

## Stock Unicorn cannot run this firmware

digikit ships `tools/install-patched-unicorn.sh` for a **destructive SR read**
that corrupts the condition flags. Anyone standing one up from scratch would
debug the *firmware* for days instead of the emulator.

This is the third time this project has met the same trap — radare2's m68k
backend inventing instructions (`docs/mainos-image.md`), and our own trace
harness reporting blanks that meant nothing. **Validate the tool before trusting
its output** is the standing rule, and an emulator is a tool.

So the first thing to run is not our image. It is digikit's own
`tools/bootcheck.py` against a firmware its author has tested, to establish that
the emulator works *here* before anything it says about our image is believed.

## What it is for

Three questions this project has failed to answer by flashing, each of which is
a trace or a memory watch in an emulator:

1. **Is `0x40287ef6` live?** A write watch over that 16-record array either
   confirms the 2026-09-13 crash diagnosis (`docs/flashing.md`) or overturns it.
   The cheapest possible test of the most recent conclusion.
2. **What runs when an encoder turns?** The question behind four silent flashes.
   The author flags **encoder deltas as buggy**, so verify the input path
   delivers a value change and not merely an event before believing any trace —
   a broken delta lights the wrong half of the path and looks like a result.
3. **Where is the display path?** `set_pixel` (DN2 1.10E `0x40105964`) is a
   *named role*, not a pattern match. Everything on that screen goes through it,
   so hooking it and walking back is how the path gets identified — instead of
   the two functions this project named by eye and was wrong about both times.

## Version

digikit documents DN2 **1.10E**; its author says "latest"; ours is **1.11**.
Unresolved, and it decides whether the addresses above transfer directly or need
re-deriving. Ask, or measure — do not assume.
