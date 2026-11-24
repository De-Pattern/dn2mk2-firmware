"""Perkons words through the booted instrument's sound SAVE/LOAD converters.

This checks serialization, not the project UI, storage device, or Pi reconnect.
"""
from __future__ import annotations

import itertools
import struct

from dnfw.sidecar import machines as sc

LOAD, SAVE = 0x400DD1EA, 0x400DD6A6
SOUND_BYTES, STORED_BYTES, MACHINE_AT = 1163, 359, 0xDE


def cases():
    defaults = tuple(k['default'] << 8 for k in sc.KNOBS)
    yield 'defaults', defaults
    yield 'minimum', (0,) * 11
    yield 'maximum', (0x7F00,) * 11
    fractional = tuple((0x019D + i * 0x0B13) % 0x7F01 for i in range(11))
    yield 'fractional', fractional
    for voice, algorithm, mode in itertools.product(range(4), range(3), range(3)):
        selectors = tuple(((2 * n + 1) * 128 // (2 * count)) << 8
                          for n, count in zip((voice, algorithm, mode), (4, 3, 3)))
        yield f'program-{voice + 1}-{algorithm + 1}-{mode + 1}', fractional[:8] + selectors


def verify(after, real):
    """Raise on loss, noncanonical second save, or an instruction-limit stop."""
    from unicorn.m68k_const import UC_M68K_REG_PC

    assert len(real) == SOUND_BYTES

    def call(fn, *args):
        after.call(fn, *args)
        assert after.uc.reg_read(UC_M68K_REG_PC) == after.ret, 'converter did not return'

    count = 0
    for label, values in cases():
        sound = bytearray(real)
        sound[MACHINE_AT] = sc.TYPE
        for (_, slot), value in zip(sc.RECORDS, values):
            struct.pack_into('>H', sound, 20 + 2 * slot, value)
        live = after.alloc(SOUND_BYTES + 16)
        after.write(live, bytes(sound))
        stored = after.alloc(STORED_BYTES + 16)
        call(SAVE, stored, live, 0)
        original = bytes(after.uc.mem_read(stored, STORED_BYTES))
        assert original[244] == sc.TYPE, f'{label}: saved machine changed'
        back = after.alloc(SOUND_BYTES + 16)
        # A distinct destination rules out a converter that leaves fields untouched.
        after.write(back, b'\xA5' * SOUND_BYTES)
        call(LOAD, back, stored)
        loaded = bytes(after.uc.mem_read(back, SOUND_BYTES))
        assert loaded[MACHINE_AT] == sc.TYPE, f'{label}: loaded machine changed'
        got = tuple(struct.unpack_from('>H', loaded, 20 + 2 * slot)[0]
                    for _, slot in sc.RECORDS)
        assert got == values, f'{label}: Perkons parameter words changed: {got} != {values}'
        again = after.alloc(STORED_BYTES + 16)
        call(SAVE, again, back, 0)
        assert bytes(after.uc.mem_read(again, STORED_BYTES)) == original, f'{label}: second save differs'
        count += 1
    assert count == 40
    return count
