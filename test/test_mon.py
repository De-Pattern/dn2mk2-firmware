"""v0.59 MON (owner, 2026-11-17: the RECORDER's C; niko_24956's "a monitor switch to choose if
input src can be heard or not while recording"): with MON on, SRC IN and the recorder armed or
recording, the DSP's pvmix adds the input to the main mix at unity; otherwise the mix is untouched
(each "otherwise" its own case, so a MON that ignored any of them fails)."""

from __future__ import annotations

import math

from dnfw.perc.dsl import bits, f32, flt
from dnfw.sampler import live as SL
from dnfw.sampler import machines as SM
from dnfw.sampler import program as P

MON = 1 << SM.MON_BIT
IN_L = [0.4 * math.sin(2 * math.pi * k / 32) for k in range(32)]
IN_R = [-0.25 * math.cos(2 * math.pi * k / 16) for k in range(32)]
MIX = [0.01 * k - 0.3 for k in range(64)]


def _mix_after(cmd: int, src: int, chan: int, thres: float = 0.0, then=None) -> list[float]:
    h = SL.Harness(0)
    h.defaults()
    h.command(cmd, src=src, chan=chan, thres=thres, dest=5, place=0x100)
    h.recorder(inp=(IN_L, IN_R))
    if then is not None:
        h.command(then, src=src, chan=chan, dest=5, place=0x100)
        h.recorder(inp=(IN_L, IN_R))
    for k in range(64):
        h.mem.put(SM.MIX_BUF + 4 * k, bits(MIX[k]))
    P.pvmix_run(h.L, h.mem)
    return [flt(h.mem.get(SM.MIX_BUF + 4 * k)) for k in range(64)]


HEARD = [f32(f32(m) + f32(x)) for m, x in zip(MIX, IN_L + IN_R)]
UNTOUCHED = [f32(m) for m in MIX]


def test_mon_on_in_recording_adds_the_input():
    assert _mix_after(SM.CMD_NOW, 0, MON) == HEARD


def test_mon_on_in_armed_adds_the_input():
    # armed above the input's level: still armed when the block is mixed
    assert _mix_after(SM.CMD_ARM, 0, MON, thres=0.95) == HEARD


def test_mon_on_any_channel_setting_hears_both_sides():
    for chan in (0, 1, 2):
        assert _mix_after(SM.CMD_NOW, 0, chan | MON) == HEARD


def test_mon_off_leaves_the_mix():
    assert _mix_after(SM.CMD_NOW, 0, 0) == UNTOUCHED


def test_mon_ignored_for_main_and_tracks():
    assert _mix_after(SM.CMD_NOW, 1, MON) == UNTOUCHED          # MAIN
    assert _mix_after(SM.CMD_NOW, 2, MON) == UNTOUCHED          # TRK1


def test_mon_only_while_armed_or_recording():
    assert _mix_after(SM.CMD_MONITOR, 0, MON) == UNTOUCHED      # idle: the meter only
    assert _mix_after(SM.CMD_NOW, 0, MON, then=SM.CMD_STOP) == UNTOUCHED


def test_the_links_commands_do_not_change_mon():
    # v0.39's rule: only the recorder's own commands carry its settings (VERIFY's words are not)
    h = SL.Harness(0)
    h.defaults()
    h.command(SM.CMD_NOW, src=0, chan=MON, dest=5, place=0x100)
    h.recorder(inp=(IN_L, IN_R))
    assert h.mem.get(SM.REC_MON) == 1
    h.link(SM.CMD_VERIFY, 0, 2, 0)
    h.recorder(inp=(IN_L, IN_R))
    assert h.mem.get(SM.REC_MON) == 1
