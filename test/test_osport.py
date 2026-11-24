"""The 1.11 -> 1.12 port (docs/os112-port.md): the translator, the porter and A()."""
import pathlib
import struct

import pytest

from dnfw.osport import port
from dnfw.osport import os as O
from dnfw.osport.addrmap import BASE, AddrMap, main_os

ROOT = pathlib.Path(__file__).resolve().parents[1]
S11, S12 = ROOT.parent / "Digitone_II_OS1.11.syx", ROOT.parent / "Digitone_II_OS1.12.syx"
need = pytest.mark.skipif(not (S11.exists() and S12.exists()), reason="stock 1.11 and 1.12 not beside the repo")


@pytest.fixture(scope="module")
def m():
    return AddrMap(main_os(S11), main_os(S12))


def test_A_is_identity_on_111(monkeypatch):
    monkeypatch.setenv("DN2_OS", "1.11")
    assert O.A(0x4011EA6A) == 0x4011EA6A


@need
def test_known_addresses(m):
    assert m.map(0x40000400)[0] == 0x40000400                  # before the first change
    assert m.map(0x4011EA6A)[0] == 0x4011ED4A                  # the fault reporter, +736
    assert m.map(0x42431A6C)[0] == 0x42432A6C                  # BSS: the active track, +4096
    assert m.map(0x4038AED4)[0] - 0x4038AED4 == m.map(0x4058AEE0)[0] - 0x4058AEE0   # USB buffer 2 MiB
    assert m.map(0x80005308)[0] == 0x80005308                  # fast SRAM did not move


@need
def test_refuses_changed_code(m):
    """negative control: an address inside code 1.12 changed has no translation"""
    gaps = [(a[1], b[0]) for a, b in zip(m.segs, m.segs[1:]) if b[0] - a[1] > 64]
    lo, hi = gaps[0]
    assert m.map(BASE + (lo + hi) // 2)[0] is None


@need
def test_edit_on_changed_code_is_refused(m):
    """negative control: an edit over code 1.12 changed is refused, never moved"""
    gaps = [(a[1], b[0]) for a, b in zip(m.segs, m.segs[1:]) if b[0] - a[1] > 64]
    lo, hi = gaps[0]
    b = bytearray(m.a)
    o = (lo + hi) // 2 & ~1
    b[o:o + 6] = bytes.fromhex("4ef946700000")
    rep = port.Report()
    port.port_edits(m.a, bytes(b), m.b, m, rep)
    assert rep.refused and not rep.edits


@need
def test_operand_translated(m):
    """a jsr to a stock routine that moved is translated in our code; a jsr to our RAM is not"""
    code = bytearray(struct.pack(">HI", 0x4EB9, 0x4011EA6A) + struct.pack(">HI", 0x4EB9, 0x46AC0000))
    rep = port.Report()
    port.relocate_code(code, 0x46AC1000, m, rep, "t")
    assert struct.unpack(">I", code[2:6])[0] == 0x4011ED4A
    assert struct.unpack(">I", code[8:12])[0] == 0x46AC0000
