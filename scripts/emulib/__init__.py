"""Shared parts of the emulator harnesses, so a new one composes instead of copies.

Five scripts had grown their own copy of the same machinery -- restore a
snapshot, write memory that may not be mapped, enter a routine with arguments,
diff a build against stock, drive the panel, archive a screen, print a check.
This package holds each of those once:

| module | one subject |
|---|---|
| `machine` | a restored snapshot: memory, calls, instruction counts |
| `panel` | driving it as a person would: taps, holds, push-and-turn, screens |
| `image` | what a build produced: its changed runs, its `CODE` chunk, its sites |
| `report` | checks that print, and an exit status that means something |

Anything specific to one feature stays in that feature's script -- this is the
part that is the same whatever is being asked.

It imports digikit only inside the functions that need it, so `image` and
`report` can be used on Windows where digikit's emulator cannot run.
"""

from .image import code_chunk, code_chunks, differences, load_build, sites            # noqa: F401
from .report import check, failures, report                              # noqa: F401
