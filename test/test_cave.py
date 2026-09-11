"""The code-cave detour: its guards, and that a plan splices the right bytes."""

import pytest

from dnfw.image.coldfire import LoadedImage
from dnfw.patch.cave import Cave, CaveError, CaveHook, apply, plan
from dnfw.patch.coldfire import jmp_abs

BASE = 0x40000400
# A section: 0x40 bytes of "code" then a 0x40-byte free (zero) run for the cave.
# move.l (0x401e29d0).l, %d0 -- exactly 6 bytes, straight-line (not PC-relative).
STOCK_AT_HOOK = bytes.fromhex("2039401e29d0")  # 6 bytes = one jmp's worth, no pad


def _image() -> LoadedImage:
    content = bytearray(0x80)
    content[0x10 : 0x10 + len(STOCK_AT_HOOK)] = STOCK_AT_HOOK
    # everything from 0x40 on stays zero -- the cave
    return LoadedImage(dest=BASE, content=bytes(content))


def _hook(**over) -> CaveHook:
    fields = dict(
        id="t",
        site=BASE + 0x10,
        stock=STOCK_AT_HOOK,
        payload=bytes.fromhex("7001"),  # moveq #1,d0 -- a stand-in payload
        cave=Cave(address=BASE + 0x40, capacity=0x40),
    )
    fields.update(over)
    return CaveHook(**fields)


def test_plan_builds_payload_then_displaced_then_return_jump():
    p = plan(_image(), _hook())
    expected = b"\x70\x01" + STOCK_AT_HOOK + jmp_abs(BASE + 0x10 + len(STOCK_AT_HOOK))
    assert p.cave_bytes == expected
    assert p.return_address == BASE + 0x16


def test_plan_writes_a_jmp_at_the_hook():
    p = plan(_image(), _hook())
    _, hook_write = p.writes
    assert hook_write.new == jmp_abs(BASE + 0x40)  # stock was exactly 6 bytes -> no pad


def test_hook_longer_than_a_jmp_is_nop_padded():
    stock = STOCK_AT_HOOK + b"\x4e\x71\x4e\x71"  # 10 bytes: 6 for jmp + 2 nops
    img = bytearray(_image().content)
    img[0x10 : 0x10 + len(stock)] = stock
    image = LoadedImage(dest=BASE, content=bytes(img))
    p = plan(image, _hook(stock=stock))
    _, hook_write = p.writes
    assert hook_write.new == jmp_abs(BASE + 0x40) + b"\x4e\x71\x4e\x71"


def test_apply_leaves_everything_else_untouched():
    image = _image()
    out = apply(image, _hook())
    # hook site now a jmp into the cave
    assert out[0x10:0x16] == jmp_abs(BASE + 0x40)
    # cave now holds the body
    body = b"\x70\x01" + STOCK_AT_HOOK + jmp_abs(BASE + 0x16)
    assert out[0x40 : 0x40 + len(body)] == body
    # untouched span between hook and cave stays zero
    assert out[0x16:0x40] == bytes(0x40 - 0x16)
    assert len(out) == len(image.content)


def test_wrong_stock_is_refused():
    image = _image()
    with pytest.raises(CaveError, match="expected"):
        plan(image, _hook(stock=b"\xde\xad\xbe\xef\xca\xfe"))


def test_a_non_free_cave_is_refused():
    img = bytearray(_image().content)
    img[0x44] = 0xFF  # dirty a byte inside the intended cave
    image = LoadedImage(dest=BASE, content=bytes(img))
    with pytest.raises(CaveError, match="not free"):
        plan(image, _hook())


def test_a_cave_too_small_is_refused():
    with pytest.raises(CaveError, match="cave body"):
        plan(_image(), _hook(cave=Cave(address=BASE + 0x40, capacity=8)))


def test_stock_shorter_than_a_jmp_is_refused():
    with pytest.raises(CaveError, match="at least"):
        _hook(stock=b"\x4e\x75\x4e\x75")  # 4 bytes


def test_pcrel_displaced_bytes_are_refused_by_default():
    # 0x67 is beq.b -- a PC-relative branch; replaying it verbatim retargets it.
    stock = b"\x67\x10" + STOCK_AT_HOOK[:4]
    img = bytearray(_image().content)
    img[0x10 : 0x10 + len(stock)] = stock
    image = LoadedImage(dest=BASE, content=bytes(img))
    with pytest.raises(CaveError, match="PC-relative"):
        plan(image, _hook(stock=stock))


def test_pcrel_can_be_overridden_when_verified_safe():
    stock = b"\x67\x10" + STOCK_AT_HOOK[:4]
    img = bytearray(_image().content)
    img[0x10 : 0x10 + len(stock)] = stock
    image = LoadedImage(dest=BASE, content=bytes(img))
    p = plan(image, _hook(stock=stock, allow_pcrel=True))
    assert p.cave_bytes.startswith(b"\x70\x01" + stock)


# --- authoring aids ---

def test_find_free_runs_reports_only_runs_at_least_min_size():
    from dnfw.patch.cave import find_free_runs

    # 0x00..0x10 zeros, 0x10..0x16 stock, then zeros to 0x80 (a 0x6a-byte run).
    runs = find_free_runs(_image(), BASE, BASE + 0x80, min_size=8)
    assert len(runs) == 2  # the 0x10 lead-in zeros, and the big tail run
    tail = max(runs, key=lambda r: r.size)
    assert tail.address == BASE + 0x16
    assert tail.size == 0x80 - 0x16
    # min_size filters the 16-byte lead-in out, leaving only the tail.
    assert len(find_free_runs(_image(), BASE, BASE + 0x80, min_size=0x20)) == 1


def test_find_free_runs_refuses_a_range_outside_the_section():
    from dnfw.patch.cave import find_free_runs

    with pytest.raises(CaveError, match="outside"):
        find_free_runs(_image(), BASE, BASE + 0x100, min_size=4)


def test_displaced_stock_accumulates_whole_instructions_to_min_len():
    from dnfw.patch.cave import displaced_stock

    # two 2-byte instructions then a 4-byte one; need >= 6 -> first three.
    parts = [b"\x70\x01", b"\x4e\x71", b"\x22\x39\x40\x1f", b"\x7f\xc8"]
    assert displaced_stock(parts, min_len=6) == b"\x70\x01\x4e\x71\x22\x39\x40\x1f"


def test_displaced_stock_raises_when_too_few_bytes():
    from dnfw.patch.cave import displaced_stock

    with pytest.raises(CaveError, match="need 6"):
        displaced_stock([b"\x4e\x75"], min_len=6)
