"""Disassemble with selache, reassemble with selache, compare the bytes.

    # inside WSL or Linux, where selache is built:
    python3 scripts/sharc_selache_roundtrip.py out/sharc/code_283825c4.bin \\
        --selmap /root/selmap-target/release/selmap \\
        --selas /root/selache-target/release/selas

Takes every distinct instruction a linear walk of the region meets (from
offset 0, the way `tools/selmap` sizes it), skips all-zero 48-bit padding and
anything selache prints with a `?`, and assembles each one alone in its own
VISA section -- `.NOCOMPRESS` where the original is 48 bits, so width is not the
assembler's free choice. Then compares each section's bytes with the original.

The answer decides what selache's disassembly is good for: a byte-identical
round trip would make its text a patch format; anything less makes it a reading
aid, and patches have to be written as source (`docs/sharc-selache.md`).

selas stops at the first line it rejects and occasionally panics without a line
number, so batches that fail are split until each failure is one instruction.
Standard library only; no dnfw import, so it runs where selache runs.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import struct
import subprocess
import tempfile


def instructions(region: bytes, selmap: str):
    """-> [(big-endian hex, length, text)], unique, in walk order."""
    out = subprocess.run([selmap], input=region, capture_output=True, check=True).stdout
    m = {}
    for line in out.decode().splitlines():
        off, n, text = line.split("\t", 2)
        m[int(off)] = (int(n), text)
    seen, order, off = set(), [], 0
    while off in m:
        n, text = m[off]
        raw = bytearray(region[off:off + n])
        for j in range(0, len(raw) & ~1, 2):
            raw[j], raw[j + 1] = raw[j + 1], raw[j]
        key = raw.hex()
        if "?" not in text and key not in seen and not (n == 6 and not any(raw)):
            seen.add(key)
            order.append((key, n, text))
        off += n
    return order


def sections(path: pathlib.Path) -> dict:
    """-> {section name: bytes} from an ELF32 object."""
    d = path.read_bytes()
    shoff, = struct.unpack_from("<I", d, 0x20)
    ent, num, stridx = struct.unpack_from("<HHH", d, 0x2E)
    hdrs = [struct.unpack_from("<10I", d, shoff + i * ent) for i in range(num)]
    names = hdrs[stridx][4]
    out = {}
    for h in hdrs:
        name = d[names + h[0]:].split(b"\0")[0].decode()
        out[name] = d[h[4]:h[4] + h[5]]
    return out


def assemble(selas: str, order, items, work: pathlib.Path, result: dict) -> None:
    items = list(items)
    while items:
        src = []
        for k in items:
            _, n, text = order[k]
            src += [f".section/pm/sw s{k};", ".NOCOMPRESS;" if n == 6 else ".COMPRESS;", text + ";"]
        (work / "rt.s").write_text("\n".join(src) + "\n")
        r = subprocess.run([selas, "-proc", "ADSP-21569", "-o", str(work / "rt.doj"), str(work / "rt.s")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            got = sections(work / "rt.doj")
            for k in items:
                result[k] = ("ok", got.get(f"s{k}", b"").hex())
            return
        hit = re.search(r"line (\d+): (.*)", r.stderr)
        line = int(hit.group(1)) - 1 if hit else -1
        if hit and line % 3 == 2 and line // 3 < len(items):
            k = items.pop(line // 3)
            result[k] = ("rejected", hit.group(2))
            continue
        if len(items) == 1:
            if hit:
                result[items[0]] = ("rejected", hit.group(2).strip())
                return
            why = re.search(r"(EncodeError.*|panicked.*)", r.stderr)
            result[items[0]] = ("crashed", (why.group(1) if why else r.stderr[-120:]).strip()[:120])
            return
        half = len(items) // 2
        assemble(selas, order, items[:half], work, result)
        assemble(selas, order, items[half:], work, result)
        return


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("region", type=pathlib.Path, help="a code region as the firmware stores it")
    p.add_argument("--selmap", required=True)
    p.add_argument("--selas", required=True)
    args = p.parse_args(argv)

    order = instructions(args.region.read_bytes(), args.selmap)
    result = {}
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(0, len(order), 500):
            assemble(args.selas, order, range(i, min(i + 500, len(order))), pathlib.Path(tmp), result)

    tally, kinds = collections.Counter(), collections.Counter()
    for k, (status, value) in result.items():
        key, n, _ = order[k]
        if status != "ok":
            tally[status] += 1
            kinds[re.sub(r"0x[0-9a-fA-F]+|\d+", "N", value)[:60]] += 1
        elif value == key:
            tally["identical"] += 1
        elif len(value) == len(key):
            tally["same width, other bits"] += 1
        else:
            tally[f"width {n} -> {len(value) // 2}"] += 1
    print(f"{len(order)} unique instructions")
    for k, v in tally.most_common():
        print(f"  {k:24} {v:6}  ({100 * v / len(order):.1f}%)")
    print("most common failures:")
    for k, v in kinds.most_common(8):
        print(f"  {v:4}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
