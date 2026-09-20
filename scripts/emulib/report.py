"""Checks that print, and an exit status that means something.

A harness that prints `ok` for everything is a harness nobody reads. These
print the detail **on a pass as well as a failure**, because the number is
usually the finding -- "16 copies in 640 refreshes" says more than "ok".
"""

from __future__ import annotations

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Print one result and remember it. -> `ok`, so callers can branch."""
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def report() -> int:
    """-> a process exit status, and the list of what failed."""
    print(f"\n{len(failures)} failure(s): {failures}" if failures else "\nall checks pass")
    return 1 if failures else 0
