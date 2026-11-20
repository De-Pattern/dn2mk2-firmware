"""Build src/dnfw/codec/apopt.wasm from apopt.c (v0.65, docs/packer.md).

    python3 scripts/build_apopt_wasm.py [--check]

clang for wasm32, no libc, the planner's three functions and __heap_base exported. --check
builds it to a temporary file and fails if the committed module differs (the unit tests run it).
"""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "dnfw" / "codec" / "apopt.c"
OUT = ROOT / "src" / "dnfw" / "codec" / "apopt.wasm"
CMD = ["clang", "--target=wasm32", "-O2", "-nostdlib", "-fno-builtin", "-ffile-prefix-map=/=",
       "-Wl,--no-entry", "-Wl,--export=apopt_plan", "-Wl,--export=apopt_need",
       "-Wl,--export=apopt_tokens", "-Wl,--export=__heap_base", "-Wl,--strip-all"]


def build(out: pathlib.Path) -> None:
    subprocess.run(CMD + ["-o", str(out), str(SRC)], check=True)


def main() -> int:
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td) / "apopt.wasm"
            build(t)
            same = t.read_bytes() == OUT.read_bytes()
        print("apopt.wasm is apopt.c's" if same else "apopt.wasm is stale: run scripts/build_apopt_wasm.py")
        return 0 if same else 1
    build(OUT)
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
