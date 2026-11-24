"""Route ownership and bypass-removal contract; no claim of compiled DSP parity."""
from dnfw.perc.dsl import Mem, Prog, bits
from dnfw.sidecar.native_return import (
    BLOCK, USB_PLANES, MAGIC, Config, route, TRACK_BUFFERS,
    FRAME_TAG, FRAME_NATIVE, FRAME_IDLE, publish_frame, FRAME,
)
from dnfw.sidecar.machines import TYPE

CFG = Config(0x290000)  # model-only address, not a proposed firmware allocation
BUFFERS = 0x291000


def fixture(owners, owned, enabled=MAGIC):
    mem = Mem()
    mem.put(CFG.enabled, enabled)
    mem.put(CFG.owned, owned)
    for lane in range(8):
        mem.put(CFG.owner(lane), owners[lane])
        for sample in range(BLOCK):
            mem.put(USB_PLANES + (lane * BLOCK + sample) * 4,
                    bits((lane * BLOCK + sample + 1) / 512))
    for voice in range(16):
        buf = BUFFERS + voice * BLOCK * 4
        mem.put(TRACK_BUFFERS + voice * 4, buf)
        for sample in range(BLOCK):
            mem.put(buf + sample * 4, bits(-0.125))
    return mem


def output(mem, voice):
    return [mem.get(BUFFERS + (voice * BLOCK + i) * 4) for i in range(BLOCK)]


def run(mem):
    route(Prog("run", mem), CFG)
    return mem


def test_eight_independent_returns_preserve_native_voices_and_remove_bypasses():
    owners = [15, 3, 12, 7, 9, 1, 6, 10]
    mem = fixture(owners, sum(1 << v for v in owners))
    inputs = [[mem.get(USB_PLANES + (lane * BLOCK + i) * 4)
               for i in range(BLOCK)] for lane in range(8)]
    run(mem)
    for lane, voice in enumerate(owners):
        assert output(mem, voice) == inputs[lane]
    for voice in set(range(16)) - set(owners):
        assert output(mem, voice) == [bits(-0.125)] * BLOCK
    assert all(mem.get(USB_PLANES + i * 4) == 0 for i in range(8 * BLOCK))


def test_reassignment_clears_previous_owner_without_touching_internal_voices():
    mem = fixture([2, -1, -1, -1, -1, -1, -1, -1], (1 << 2) | (1 << 5))
    run(mem)
    assert output(mem, 2) != [0] * BLOCK
    assert output(mem, 5) == [0] * BLOCK
    mem.put(CFG.owner(0), 5)
    for i in range(BLOCK): mem.put(USB_PLANES + 4 * i, bits(0.25))
    run(mem)
    assert output(mem, 2) == [0] * BLOCK
    assert output(mem, 5) == [bits(0.25)] * BLOCK
    assert output(mem, 0) == [bits(-0.125)] * BLOCK


def test_duplicate_invalid_and_unowned_destinations_are_silent():
    mem = fixture([2, 2, 16, -1, 0xFFFFFFFF, 8, -1, -1], 1 << 2)
    run(mem)
    assert output(mem, 2) == [0] * BLOCK
    assert output(mem, 8) == [bits(-0.125)] * BLOCK
    assert all(mem.get(USB_PLANES + i * 4) == 0 for i in range(8 * BLOCK))


def test_disabled_route_does_not_touch_any_audio_or_state():
    for enabled in (0, MAGIC ^ 1):
        mem = fixture(list(range(8)), 255, enabled)
        original = dict(mem.w)
        run(mem)
        assert mem.w == original


def test_enabled_without_owners_consumes_returns_without_audio_leak():
    mem = fixture([-1] * 8, 0)
    run(mem)
    assert all(output(mem, v) == [bits(-0.125)] * BLOCK for v in range(16))
    assert all(mem.get(USB_PLANES + i * 4) == 0 for i in range(8 * BLOCK))


def put_half(mem, offset, value):
    addr = FRAME + (offset & ~3)
    shift = (offset & 2) * 8
    mem.put(addr, (mem.get(addr) & ~(0xFFFF << shift)) | (value << shift))


def frame_voice(mem, voice, lane, native=True):
    put_half(mem, 148 + 2 * voice, TYPE)
    put_half(mem, 218 + 146 * voice, FRAME_TAG | (FRAME_NATIVE if native else 0) | lane)


def test_native_frame_publishes_nonidentity_owners_and_preserves_controls():
    owners = [15, 3, 12, 7, 9, 1, 6, 10]
    mem = fixture([-1] * 8, 0, 0)
    for lane, v in enumerate(owners): frame_voice(mem, v, lane)
    frame_voice(mem, 5, FRAME_IDLE)
    before = dict(mem.w)
    publish_frame(Prog("run", mem), CFG)
    assert mem.get(CFG.enabled) == MAGIC
    assert [mem.get(CFG.owner(i)) for i in range(8)] == owners
    run(mem)
    for lane, v in enumerate(owners):
        assert output(mem, v) == [before[USB_PLANES + (lane * BLOCK + i) * 4] for i in range(BLOCK)]
    assert output(mem, 5) == [0] * BLOCK
    assert output(mem, 0) == [bits(-0.125)] * BLOCK
    assert all(mem.get(a) == value for a, value in before.items() if FRAME <= a < FRAME + 2688)


def test_frame_owner_reuse_does_not_clear_new_internal_machine():
    mem = fixture([-1] * 8, 0, MAGIC)
    frame_voice(mem, 2, 0)
    publish_frame(Prog("run", mem), CFG)
    put_half(mem, 148 + 2 * 2, 1)
    frame_voice(mem, 5, 0)
    publish_frame(Prog("run", mem), CFG)
    run(mem)
    assert output(mem, 2) == [bits(-0.125)] * BLOCK
    assert output(mem, 5) != [bits(-0.125)] * BLOCK


def test_duplicate_lane_and_malformed_or_mixed_frame_fail_closed():
    for fault in ("duplicate", "tag", "lane", "mixed"):
        mem = fixture([-1] * 8, 0, MAGIC)
        frame_voice(mem, 2, 0)
        frame_voice(mem, 5, 0 if fault == "duplicate" else 1, native=fault != "mixed")
        if fault == "tag": put_half(mem, 218 + 146 * 5, 0)
        if fault == "lane": frame_voice(mem, 5, 8)
        publish_frame(Prog("run", mem), CFG)
        run(mem)
        assert output(mem, 2) == output(mem, 5) == [0] * BLOCK
        assert all(mem.get(USB_PLANES + i * 4) == 0 for i in range(8 * BLOCK))


def test_frame_mode_survives_empty_kit_until_explicit_legacy_handoff():
    mem = fixture([-1] * 8, 0, MAGIC)
    publish_frame(Prog("run", mem), CFG)
    assert mem.get(CFG.enabled) == MAGIC
    assert mem.get(CFG.owned) == 0
    frame_voice(mem, 5, FRAME_IDLE, native=False)
    publish_frame(Prog("run", mem), CFG)
    assert mem.get(CFG.enabled) == 0
