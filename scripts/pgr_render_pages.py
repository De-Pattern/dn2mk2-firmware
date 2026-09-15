"""Render classic-PGR opcode pages, several stacked per image for reading."""
import collections, pathlib, sys
import pymupdf
from PIL import Image

pdf, outdir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
lo, hi = int(sys.argv[3]), int(sys.argv[4])
batch = int(sys.argv[5]) if len(sys.argv) > 5 else 3
dpi = int(sys.argv[6]) if len(sys.argv) > 6 else 260
outdir.mkdir(parents=True, exist_ok=True)
doc = pymupdf.open(pdf)


def grids(page):
    by_line = collections.defaultdict(list)
    for x0, y0, x1, _y1, text, *_ in page.get_text("words"):
        if text.isdigit() and 0 <= int(text) <= 47:
            by_line[round(y0, 0)].append((int(text), x0))
    rows = []
    for y, items in sorted(by_line.items()):
        items.sort(key=lambda t: t[1])
        nums = [n for n, _x in items]
        if len(nums) < 8:
            continue
        if sum(1 for a, b in zip(nums, nums[1:]) if b == a - 1) >= len(nums) - 2:
            rows.append(y)
    return rows


def save(group, index):
    width = max(i.width for _p, i in group)
    height = sum(i.height + 14 for _p, i in group)
    sheet = Image.new("RGB", (width, height), "white")
    y = 0
    for _pno, img in group:
        sheet.paste(img, (0, y))
        y += img.height + 14
    name = f"batch{index:02d}_p{group[0][0]}-{group[-1][0]}.png"
    sheet.save(outdir / name)
    print(f"  {name}  {sheet.width}x{sheet.height}  pages {[p for p, _ in group]}")


group, index = [], 0
for pno in range(lo, hi + 1):
    page = doc[pno - 1]
    rows = grids(page)
    if not rows:
        continue
    clip = pymupdf.Rect(40, max(0, min(rows) - 26), page.rect.width - 18,
                        min(page.rect.height, max(rows) + 95))
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    group.append((pno, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
    if len(group) == batch:
        index += 1
        save(group, index)
        group = []
if group:
    index += 1
    save(group, index)
print(f"\n{index} composite images in {outdir}")
