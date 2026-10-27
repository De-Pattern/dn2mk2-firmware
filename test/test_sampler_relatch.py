"""v0.28: a SLICE note whose slice (SLCE, or the note) reaches the DSP a block after its
trigger is taken again with the right slice (dnfw.sampler.program.relatch; a user's report:
"when I trigger the next slice, sometimes a small section of the slice before plays")."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dnfw.sampler import live as SL, machines as SM            # noqa: E402

T = SM.TYPE_OF["SLICE"]


def _run(when: int | None, blocks: int = 14):
    beat = len(SL.test_samples()[3])
    sl = [(), (), (), [(beat * k // 16, beat * (k + 1) // 16, beat * k // 16) for k in range(16)]]
    h = SL.Harness(0, slices=sl)
    h.defaults()
    h.set(SM.SAMP_REC, 4)
    h.set(SM.SLICE_REC, 2 * 3)
    out = []
    for b in range(blocks):
        if when is not None and b == when:
            h.set(SM.SLICE_REC, 2 * 9)
        out.append(h.block(T, trig=b in (0, 6)))
    return out


def test_a_slice_lock_a_block_late_is_taken():
    on, late = _run(6), _run(7)
    assert all(on[b] == late[b + 1] for b in range(8, 13))


def test_a_change_long_after_the_note_is_not_a_note():
    # SLCE turned well after the note: the note goes on with its slice (as before)
    base, turned = _run(None), _run(10)
    assert base == turned
