"""ship_gate's tracer (v0.25): with DNFW_GATE_TRACE set, every Python process of a gate
step -- the step itself and any Python it starts -- notes each file it opens (reading or
writing), each directory it lists and each program it runs, one JSON line a new item, in
DNFW_GATE_TRACE/trace-<pid>.jsonl, written as it goes (so a process that ends without
its exit handlers still left its reads). ship_gate.py hashes the files read (not those a
step wrote) and reuses a step's pass only while every one is byte-identical.

Loaded as `sitecustomize` through PYTHONPATH; the system's own sitecustomize, if any,
still runs first."""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
for _p in list(sys.path):                           # the system's sitecustomize, if any
    if os.path.abspath(_p or ".") == _here:
        continue
    _f = os.path.join(_p or ".", "sitecustomize.py")
    if os.path.isfile(_f):
        try:
            exec(compile(open(_f, "rb").read(), _f, "exec"), {"__name__": "_system_sitecustomize"})
        except Exception:                           # noqa: BLE001 -- never break the step
            pass
        break

_dir = os.environ.get("DNFW_GATE_TRACE")
if _dir:
    import json

    _seen = set()
    _busy = [False]
    _out = [None]

    def _note(kind, item):
        key = (kind, json.dumps(item))
        if key in _seen:
            return
        _seen.add(key)
        if _out[0] is None:
            _out[0] = os.open(os.path.join(_dir, f"trace-{os.getpid()}.jsonl"),
                              os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.write(_out[0], (json.dumps([kind, item]) + "\n").encode())

    def _hook(event, args):
        if _busy[0]:
            return
        try:
            _busy[0] = True
            if event == "open":
                path, mode, flags = args
                if isinstance(path, int):
                    return
                if isinstance(path, bytes):
                    path = os.fsdecode(path)
                path = os.path.abspath(str(path))
                if path.startswith(_dir):
                    return
                writes = (mode is not None and any(c in str(mode) for c in "wax+")) or \
                    (flags is not None and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                _note("w" if writes else "r", path)
            elif event in ("os.listdir", "os.scandir"):
                path = args[0] if args else "."
                if isinstance(path, int):
                    return
                if isinstance(path, bytes):
                    path = os.fsdecode(path)
                _note("d", os.path.abspath(str(path if path is not None else ".")))
            elif event == "ctypes.dlopen":       # native libraries (the emulator's unicorn)
                name = args[0]
                if isinstance(name, bytes):
                    name = os.fsdecode(name)
                if name and os.path.isabs(str(name)):
                    _note("r", str(name))
            elif event == "subprocess.Popen":
                executable, argv = args[0], args[1]
                _note("x", [str(executable) if executable else None,
                            [os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in argv]
                            if isinstance(argv, (list, tuple)) else str(argv)])
        except Exception:                           # noqa: BLE001
            pass
        finally:
            _busy[0] = False

    def _modules():                                 # what was imported, native ones too
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f:
                try:
                    _note("r", os.path.abspath(f))
                except Exception:                   # noqa: BLE001
                    pass

    import atexit
    atexit.register(_modules)
    _note("py", [sys.executable, sys.version])
    sys.addaudithook(_hook)
