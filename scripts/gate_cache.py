"""ship_gate's exact reuse of a step's pass (v0.25; the owner's go-ahead, 2026-10-25).

A gate step's pass is reused only when nothing it read has changed: while it runs, every
Python process of the step notes the files it opens, the directories it lists, the
native libraries it loads and the programs it starts (scripts/gate_trace/sitecustomize.py).
When the step passes, the files it read (not those it wrote) are hashed (sha256) and kept
with its commands. A later gate reuses the pass only if its commands are the same and
every one of those files is byte-identical now -- the build's sections it checked, the
scripts, the models, the emulator and its snapshot, the Python that ran it. Anything else,
including a file that has gone, means the step runs again.

Paths in the gate's own work directory (the build's sections it writes) are kept as
@WORK/..., so a later gate's own copies are what get compared."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import time

SKIP = ("/proc/", "/sys/", "/dev/", "/run/", "/tmp/pytest-")
KEEP = 6                                    # records kept a step


def _sha(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


def _listing(path: str) -> str | None:
    try:
        return hashlib.sha256("\n".join(sorted(os.listdir(path))).encode()).hexdigest()
    except OSError:
        return None


def _norm(path: str, work: pathlib.Path) -> str:
    w = str(work)
    return "@WORK" + path[len(w):] if path == w or path.startswith(w + os.sep) else path


def _real(path: str, work: pathlib.Path) -> str:
    return str(work) + path[5:] if path.startswith("@WORK") else path


def norm_cmd(cmd, work: pathlib.Path) -> list[str]:
    return [_norm(str(c), work) for c in cmd]


def inputs(trace_dir: pathlib.Path, work: pathlib.Path, logs: pathlib.Path) -> dict[str, str]:
    """The traces under TRACE_DIR -> {path (normalised): 'f:sha' | 'd:sha' | 'x:sha'}."""
    reads, written, dirs, progs, pys = set(), set(), set(), set(), set()
    for t in trace_dir.glob("trace-*.jsonl"):
        for line in t.read_text().splitlines():
            try:
                kind, item = json.loads(line)
            except ValueError:
                continue
            if kind == "r":
                reads.add(item)
            elif kind == "w":
                written.add(item)
            elif kind == "d":
                dirs.add(item)
            elif kind == "x":
                progs.add(item[0] or (item[1][0] if isinstance(item[1], list) and item[1] else ""))
            elif kind == "py":
                pys.add(item[0])
    for r in list(reads):                       # a compiled module stands for its source:
        p = pathlib.Path(r)                     # the source is what decides it
        if p.parent.name == "__pycache__" and p.suffix == ".pyc":
            src = p.parent.parent / (p.name.split(".")[0] + ".py")
            if src.is_file():
                reads.add(str(src))
    out = {}
    lg = str(logs)
    for r in sorted(reads - written):
        if r.startswith(SKIP) or r.startswith(lg) or not os.path.isfile(r):
            continue
        h = _sha(r)
        if h:
            out[_norm(r, work)] = "f:" + h
    for d in sorted(dirs):
        if d.startswith(SKIP) or not os.path.isdir(d):
            continue
        h = _listing(d)
        if h:
            out.setdefault(_norm(d, work), "d:" + h)
    for x in sorted(progs | pys):
        path = x if os.path.isabs(x) else (shutil.which(x) or "")
        h = _sha(path) if path else None
        out[_norm(path or x, work)] = "x:" + (h or "missing")
    return out


def _cache(root: pathlib.Path, name: str) -> pathlib.Path:
    slug = "".join(c if c.isalnum() else "_" for c in name)
    return root / "out" / "gate_cache" / f"{slug}.json"


def lookup(root: pathlib.Path, name: str, cmds, work: pathlib.Path):
    """-> the record whose commands are CMDS and whose every input is unchanged, or None."""
    f = _cache(root, name)
    if not f.exists():
        return None
    try:
        records = json.loads(f.read_text())
    except ValueError:
        return None
    for rec in reversed(records):
        if rec.get("cmds") != cmds or not rec.get("inputs"):
            continue
        ok = True
        for path, want in rec["inputs"].items():
            real = _real(path, work)
            kind, _, h = want.partition(":")
            now = (_sha(real) if kind in ("f", "x") else _listing(real)) if os.path.exists(real) else None
            if now != h:
                ok = False
                break
        if ok:
            return rec
    return None


def store(root: pathlib.Path, name: str, cmds, ins: dict[str, str], detail: str, build_sha: str) -> None:
    f = _cache(root, name)
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        records = json.loads(f.read_text()) if f.exists() else []
    except ValueError:
        records = []
    records.append({"cmds": cmds, "inputs": ins, "detail": detail, "build": build_sha,
                    "date": time.strftime("%Y-%m-%dT%H:%M:%S")})
    f.write_text(json.dumps(records[-KEEP:], indent=1))
