"""Run native page dispatch and check its record contract against stock 1.11.

This is a focused instruction-level test, not the full boot/UI shipping gate.
"""

from pathlib import Path
from functools import lru_cache
import hashlib
import json
import os
import struct
import sys

import pytest

from dnfw.sidecar import machines as sc
from dnfw.waverider import pages
from dnfw.patch.assemble import assemble, available

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_and_generic_native_storage_contract():
    assert len({s for _, s in sc.RECORDS}) == len(sc.KNOBS) == 11
    assert len({r for r, _ in sc.RECORDS}) == 11
    assert tuple(r for p in sc.PAGES for r in p if r) == tuple(r for r, _ in sc.RECORDS)
    assert len(set(r for r, _ in sc.ALL_RECORDS)) == len(set(s for _, s in sc.ALL_RECORDS)) == 16
    assert tuple(r for page in sc.GENERIC_PAGES for r in page) == tuple(r for r, _ in sc.ALL_RECORDS)


def test_records_are_full_range_and_have_the_expected_native_storage():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load

    path = Path(os.environ.get("DNFW_STOCK_111", ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"))
    if not path.is_file():
        pytest.skip("stock 1.11 needed to verify native storage")
    image = load(read_image(path)).container.find(3).unpack()
    for record, slot in sc.RECORDS:
        off = 0x401F7F94 + 60 * record - 0x40000400
        kind, actual_slot, low, high = struct.unpack_from(">4I", image, off)
        assert (kind, actual_slot, low, high) == (1, slot, 0, 127 << 8)
        assert 25 <= slot <= 92  # slots carried in the completed voice control frame


@pytest.fixture(scope="module")
def dispatch():
    if not available():
        pytest.skip("ColdFire assembler required for native page dispatch")
    uc = pytest.importorskip("unicorn")
    from unicorn import m68k_const as reg

    names = ("wr_count", "wr_page")
    tail = "\n.align 2\n" + "\n".join(".long " + n for n in names)
    image = assemble(pages.source(0, 0) + tail, base=pages.LOAD)
    symbols = dict(zip(names, struct.unpack(">2I", image[-8:])))

    def run(machine, fn, page=0):
        cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
        cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
        for base, size in ((pages.LOAD, 0x4000), (0x42431000, 0x1000),
                           (0x80005000, 0x1000), (0x43000000, 0x10000),
                           (0x46000000, 0x1000)):
            cpu.mem_map(base, size)
        cpu.mem_write(pages.LOAD, image)
        cpu.mem_write(pages.KIT_POINTER, struct.pack(">I", 0x43000000))
        cpu.mem_write(pages.ACTIVE_TRACK, b"\x00")
        cpu.mem_write(0x43000000 + pages.SOUND_BASE + pages.SOUND_TYPE, bytes([machine]))
        stop, sp = 0x46000800, 0x46000400
        args = (stop, stop, machine) if fn == "wr_count" else (stop, 0x12345678, stop, machine, page & 0xFFFFFFFF)
        cpu.mem_write(sp, struct.pack(">" + "I" * len(args), *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
        cpu.reg_write(reg.UC_M68K_REG_A7, sp)
        cpu.emu_start(symbols[fn], stop, count=1000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
        result = cpu.reg_read(reg.UC_M68K_REG_D0)
        if fn == "wr_page" and result != pages.EMPTY_PAGE:
            descriptor = struct.unpack(">11I", cpu.mem_read(result, 44))
            assert cpu.reg_read(reg.UC_M68K_REG_D2) == 0x12345678
            return descriptor
        return result

    return run


def test_perkons_has_exactly_two_pages_and_no_out_of_range_descriptor(dispatch):
    assert dispatch(sc.TYPE, "wr_count") == 2
    for index, expected in enumerate(sc.PAGES):
        desc = dispatch(sc.TYPE, "wr_page", index)
        assert desc[2:10] == expected
        assert desc[10] == pages.TAG
    for index in (-1, 2, 3, 1000):
        assert dispatch(sc.TYPE, "wr_page", index) == pages.EMPTY_PAGE


def test_existing_machine_page_dispatch_stays_intact(dispatch):
    from dnfw.sampler import machines as smp
    for index, expected in enumerate(pages.PAGES):
        assert dispatch(5, "wr_page", index)[2:10] == expected
    assert dispatch(5, "wr_count") == 2
    for kind in pages.MNM_KINDS:
        assert dispatch(kind + 4, "wr_count") == 1
        assert dispatch(kind + 4, "wr_page", 0)[2:10] == pages.MNM_PAGE
        assert dispatch(kind + 4, "wr_page", 1) == pages.EMPTY_PAGE
    for machine in smp.NAMES:
        expected = pages.SMP_PAGES[smp.NAMES.index(machine)]
        for index in (0, 1):
            assert dispatch(smp.TYPE_OF[machine], "wr_page", index)[2:10] == expected


@pytest.fixture(scope="session")
@lru_cache(maxsize=1)
def compiled_runtime():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    from dnfw.waverider import coldfire, cpage

    stock_path = Path(os.environ.get("DNFW_STOCK_111", ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"))
    if not stock_path.exists() or not cpage.available():
        pytest.skip("stock 1.11 and ColdFire compiler required")
    stock = load(read_image(stock_path)).container.find(3).unpack()
    built = coldfire.compose(stock, assemble, cpage.compile_page)
    # compose checks displaced stock bytes, region limits and zero BSS.
    report = {"scope": "native page/capture source; USB delivery and hardware gates incomplete",
              "chunks": {k: len(built[k]["code"]) for k in ("chunk", "c_chunk", "machines_chunk")},
              "chunk_sha256": {k: hashlib.sha256(built[k]["code"]).hexdigest()
                               for k in ("chunk", "c_chunk", "machines_chunk")},
              "runtime_remaining_bytes": pages.C_SPAN - len(built["c_chunk"]["code"])}
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out/sidecar-pages-compile-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return stock, built


def test_compiled_formatters_match_plugin_selectors_and_restore_other_machines(compiled_runtime):
    uc = pytest.importorskip("unicorn")
    from unicorn import m68k_const as reg

    stock, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    for base, size in ((0x40000000, 0x400000), (0x42430000, 0x10000),
                       (pages.C_LOAD, pages.C_SPAN), (0x46A00000, 0x10000)):
        cpu.mem_map(base, size)
    cpu.mem_write(0x40000400, stock)
    cpu.mem_write(pages.C_LOAD, built["c_chunk"]["code"])
    stop, sp, buf = 0x46A08000, 0x46A04000, 0x46A02000

    def call(address, *args):
        cpu.mem_write(sp, struct.pack(">" + "I" * (1 + len(args)), stop, *(a & 0xFFFFFFFF for a in args)))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
        cpu.reg_write(reg.UC_M68K_REG_A7, sp)
        cpu.emu_start(address, stop, count=100000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop

    def snapshot():
        return bytes(cpu.mem_read(0x401F7F94 + 60 * 238, 60 * 25))

    def format_knob(index, value):
        record = sc.RECORDS[index][0]
        fn, = struct.unpack(">I", cpu.mem_read(0x401F7F94 + 60 * record + 0x34, 4))
        cpu.mem_write(buf, b"\xA5" * 32)
        call(fn, value, buf)
        return bytes(cpu.mem_read(buf, 16)).split(b"\0")[0].decode("ascii")

    formats = built["layout"]["smp_formats"]
    call(formats, sc.KIND)
    for index in range(11):
        for value in (0, 31, 32, 42, 43, 63, 64, 85, 86, 95, 96, 127):
            expected = value if index < 8 else 1 + value * (4 if index == 8 else 3) // 128
            assert format_knob(index, value << 8) == str(expected)
    for index in (8, 9, 10):
        count = 4 if index == 8 else 3
        for raw in (-1, 0, 0x1FFF, 0x2000, 0x2AAA, 0x2AAB,
                    0x3FFF, 0x4000, 0x5555, 0x5556, 0x5FFF, 0x6000, 0x7F00, 0xFFFF):
            expected = 1 + min(0x7F00, max(0, raw)) * count // 32768
            assert format_knob(index, raw) == str(expected)
    # Include stock, PERC, every sampler (fine ranges included), FLEX and MnM.
    for kind in range(sc.KIND):
        call(formats, kind)
        expected = snapshot()
        call(formats, sc.KIND)
        call(formats, kind)
        assert snapshot() == expected, f"shared parameter records not restored for kind {kind}"


@pytest.mark.parametrize('fault', [None, 'word', 'machine', 'return', 'second-save'])
def test_compiled_sound_converters_preserve_perkons_and_recall_check_rejects_loss(compiled_runtime, fault):
    """Real converters and composed hooks, without boot or project filesystem."""
    uc = pytest.importorskip('unicorn')
    from unicorn import m68k_const as reg
    sys.path.insert(0, str(ROOT / 'scripts'))
    from emulib import sidecar_recall as recall

    _, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(0x40000000, 0x08000000)
    cpu.mem_map(0x80000000, 0x10000)
    cpu.mem_write(0x40000400, built['content'])
    for key in ('chunk', 'c_chunk', 'machines_chunk'):
        cpu.mem_write(built[key]['load'], built[key]['code'])

    class ConverterMachine:
        uc = cpu
        ret = 0x46A00800
        at = 0x46A10000
        saves = 0

        def alloc(self, size):
            at = (self.at + 15) & ~15
            self.at = at + size
            self.write(at, bytes(size))
            return at

        def write(self, at, data):
            cpu.mem_write(at, data)

        def call(self, fn, *args):
            sp = 0x46A00000
            cpu.mem_write(sp, struct.pack('>' + 'I' * (len(args) + 1), self.ret, *args))
            cpu.reg_write(reg.UC_M68K_REG_SR, 0x2700)
            cpu.reg_write(reg.UC_M68K_REG_A7, sp)
            cpu.reg_write(reg.UC_M68K_REG_A6, 0)
            cpu.emu_start(fn, self.ret, count=200000)
            assert cpu.reg_read(reg.UC_M68K_REG_PC) == self.ret
            # Deliberately corrupt results only after the real converter returns.
            if fn == recall.LOAD:
                if fault == 'word':
                    cpu.mem_write(args[0] + 20 + 2 * sc.RECORDS[0][1], b'\x40\x01')
                elif fault == 'machine':
                    cpu.mem_write(args[0] + recall.MACHINE_AT, b'\x00')
                elif fault == 'return':
                    cpu.reg_write(reg.UC_M68K_REG_PC, 0)
            else:
                self.saves += 1
                if fault == 'second-save' and self.saves == 2:
                    cpu.mem_write(args[0], b'\x00')

    machine = ConverterMachine()
    if fault is None:
        assert recall.verify(machine, bytes(recall.SOUND_BYTES)) == 40
    else:
        reason = {'word': 'parameter words changed', 'machine': 'loaded machine changed',
                  'return': 'converter did not return', 'second-save': 'second save differs'}[fault]
        with pytest.raises(AssertionError, match=reason):
            recall.verify(machine, bytes(recall.SOUND_BYTES))


def test_generic_identity_and_sixteen_controls_survive_actual_sound_converters(compiled_runtime):
    """Stable full IDs, unaligned sound access, corruption and legacy fallback.

    This is a converter/metadata proof, not a UI/project/parameter-lock claim.
    """
    uc = pytest.importorskip('unicorn')
    from unicorn import m68k_const as reg
    _, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(0x40000000, 0x08000000); cpu.mem_map(0x80000000, 0x10000)
    cpu.mem_write(0x40000400, built['content'])
    for key in ('chunk', 'c_chunk', 'machines_chunk'):
        cpu.mem_write(built[key]['load'], built[key]['code'])
    live, stored, back, again, idbuf, output = (0x46a10001, 0x46a11000, 0x46a12001,
                                             0x46a13000, 0x46a14000, 0x46a14100)
    stop, stack = 0x46a00800, 0x46a04000
    def call(fn, *args):
        cpu.mem_write(stack, struct.pack('>' + 'I' * (1 + len(args)), stop, *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
        cpu.reg_write(reg.UC_M68K_REG_A7, stack); cpu.reg_write(reg.UC_M68K_REG_A6, 0)
        cpu.emu_start(built['layout'][fn] if isinstance(fn, str) else fn, stop, count=200000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
        assert cpu.reg_read(reg.UC_M68K_REG_SR) & 0x2700 == 0x2000
        return cpu.reg_read(reg.UC_M68K_REG_D0)
    control_slots = [s for _, s in sc.RECORDS] + list(range(25, 30))
    identity_slots = [31, *range(50, 65), 33, 34, 37, 39]
    assert not set(control_slots) & set(identity_slots)
    cases = [b'demo.bell', b'demo.long-tone', b'demo.tone', b'not.installed', b'x' * 31]
    results = []
    for n, name in enumerate(cases):
        initial = bytearray(1163); initial[0xde] = sc.TYPE
        values = [(0x7fff - i * 0x517 + n) & 0x7fff for i in range(16)]
        for slot, value in zip(control_slots, values): struct.pack_into('>H', initial, 20 + 2 * slot, value)
        cpu.mem_write(live, bytes(initial)); cpu.mem_write(idbuf, name.ljust(32, b'\0'))
        assert call('sc_sound_identity', live, output) == 0
        assert bytes(cpu.mem_read(output, 32)) == b'mega.perkons'.ljust(32, b'\0')
        assert call('sc_sound_store', live, idbuf) == 1
        tagged = bytes(cpu.mem_read(live, 1163))
        modified = {20 + 2 * s + b for s in identity_slots for b in range(2)}
        assert all(tagged[i] == initial[i] for i in range(1163) if i not in modified)
        assert call('sc_sound_identity', live, output) == 1
        assert bytes(cpu.mem_read(output, 32)) == name.ljust(32, b'\0')
        call(0x400dd6a6, stored, live, 0)
        packed = bytes(cpu.mem_read(stored, 359))
        cpu.mem_write(back, b'\xa5' * 1163); call(0x400dd1ea, back, stored)
        loaded = bytes(cpu.mem_read(back, 1163))
        assert loaded[0xde] == sc.TYPE
        assert [struct.unpack_from('>H', loaded, 20 + 2 * s)[0] for s in control_slots] == values
        assert call('sc_sound_identity', back, output) == 1
        assert bytes(cpu.mem_read(output, 32)) == name.ljust(32, b'\0')
        call(0x400dd6a6, again, back, 0)
        assert bytes(cpu.mem_read(again, 359)) == packed
        # One-bit damage in every metadata word is rejected without changing
        # the caller's output; unknown but valid IDs remain untouched above.
        for slot in identity_slots:
            damaged = bytearray(tagged); damaged[20 + 2 * slot + 1] ^= 1
            cpu.mem_write(live, bytes(damaged)); cpu.mem_write(output, b'\xa5' * 32)
            assert call('sc_sound_identity', live, output) == 0xffffffff
            assert bytes(cpu.mem_read(output, 32)) == b'\xa5' * 32
        cpu.mem_write(live, tagged)
        for bad in (bytes(32), b'x' * 32, b'.bad'.ljust(32, b'\0'),
                    b'a..b'.ljust(32, b'\0'), b'a/b'.ljust(32, b'\0'),
                    b'a b'.ljust(32, b'\0'), b'a\0junk'.ljust(32, b'\0')):
            cpu.mem_write(idbuf, bad)
            assert call('sc_sound_store', live, idbuf) == 0
            assert bytes(cpu.mem_read(live, 1163)) == tagged
        results.append(dict(engine=name.decode(), controls_exact=16, full_id_exact=True, second_save_exact=True))
    Path('out/sidecar-generic-storage.json').write_text(json.dumps(dict(
        scope='Compiled identity functions and actual SAVE/LOAD converters; not hardware or project UI.',
        cases=results, corruptions_rejected=len(cases) * len(identity_slots)), indent=2) + '\n')


def test_extra_native_record_ranges_and_actual_setter_write_sound_and_voice_mirrors(compiled_runtime):
    """Real setter/clamp/quantization/mirror writer, with a fixture sound object.

    Only the object reference's plain pointer getter is fixture code; no range,
    value, quantization, change test or voice write routine is stubbed. This is
    not a complete UI event or sequencer-lock playback test.
    """
    uc = pytest.importorskip('unicorn')
    from unicorn import m68k_const as reg
    _, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(0x40000000, 0x08000000); cpu.mem_map(0x80000000, 0x10000)
    cpu.mem_write(0x40000400, built['content'])
    for key in ('chunk', 'c_chunk', 'machines_chunk'):
        cpu.mem_write(built[key]['load'], built[key]['code'])
    put = lambda at, value: cpu.mem_write(at, struct.pack('>I', value))
    stop, stack = 0x46a00800, 0x46a04000
    visited = set()
    def trace(_, address, __, ___): visited.add(address)
    cpu.hook_add(uc.UC_HOOK_CODE, trace)
    def call(fn, *args):
        visited.clear()
        cpu.mem_write(stack, struct.pack('>' + 'I' * (1 + len(args)), stop, *(x & 0xffffffff for x in args)))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000); cpu.reg_write(reg.UC_M68K_REG_A7, stack)
        cpu.emu_start(built['layout'][fn] if isinstance(fn, str) else fn, stop, count=100000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
        return cpu.reg_read(reg.UC_M68K_REG_D0)
    record = lambda rid: 0x401f7f94 + 60 * rid
    entry = lambda rid: 0x4243325c + 68 * rid + 4
    # Opaque but distinct runtime value-type data proves copying AND restoration.
    for rid in [r for r, _ in sc.EXTRA_RECORDS] + [261]:
        cpu.mem_write(entry(rid), struct.pack('>4I', rid, rid + 1, rid + 2, rid + 3))
    baseline = {r: (bytes(cpu.mem_read(record(r), 60)), bytes(cpu.mem_read(entry(r), 16))) for r, _ in sc.EXTRA_RECORDS}
    call('smp_formats', sc.KIND)
    for rid, slot in sc.EXTRA_RECORDS:
        row = struct.unpack('>15I', cpu.mem_read(record(rid), 60))
        assert row[:6] == (1, slot, 0, 0x7f00, 0, 0)
        assert bytes(cpu.mem_read(entry(rid), 16)) == bytes(cpu.mem_read(entry(261), 16))
        # CC/lock identities and text pointers are not overwritten by range setup.
        assert bytes(cpu.mem_read(record(rid) + 24, 28)) == baseline[rid][0][24:52]
    obj, ref, ref_vt, getter, kit = 0x46a10000, 0x46a10100, 0x46a10200, 0x46a10400, 0x46a20000
    track = 7; sound = kit + 52 + 1163 * track
    put(obj, 0x401db7fc); put(obj + 16, ref); put(ref, ref_vt); put(ref + 4, sound)
    put(ref_vt + 40, getter)
    cpu.mem_write(getter, bytes.fromhex('206f0004202800044e75'))  # return ref->sound
    put(0x800052a0, kit); cpu.mem_write(sound + 0xde, bytes([sc.TYPE]))
    for voice in range(16):
        put(0x80005308 + 4 * voice, track if voice in (2, 5) else 99)
        put(0x800052a8 + 4 * voice, sound if voice in (2, 5) else 0)
    checked = 0
    for rid, slot in sc.ALL_RECORDS:
        for value in (-17, 1, 0x3981, 0x7f00, 0x7fff):
            expected = max(0, min(0x7f00, value))
            before = bytearray(cpu.mem_read(sound, 1163))
            # Native public setter's notification flags off: its real direct
            # mirror update still executes, and the sound remains allocated.
            call(0x40037326, obj, rid, value, track, 0, 0, 0)
            struct.pack_into('>H', before, 20 + 2 * slot, expected)
            assert bytes(cpu.mem_read(sound, 1163)) == bytes(before)
            for voice in (2, 5):
                at = 0x80003af0 + 2 * (17 + 101 * voice + slot)
                assert struct.unpack('>H', cpu.mem_read(at, 2))[0] == expected
                assert struct.unpack('>I', cpu.mem_read(0x800052a8 + 4 * voice, 4))[0] == sound
            assert 0x400dbff0 in visited  # actual range lookup, never stubbed
            if value in (1, 0x3981, 0x7f00):
                assert built['layout']['smp_quant'] in visited and 0x4002585a in visited
            checked += 1
    call('smp_formats', 0)
    for rid, _ in sc.EXTRA_RECORDS:
        assert bytes(cpu.mem_read(record(rid), 60)) == baseline[rid][0]
        assert bytes(cpu.mem_read(entry(rid), 16)) == baseline[rid][1]
    cpu.mem_write(sound + 0xde, b'\x01')
    call(0x40037326, obj, 247, 0x7f00, track, 0, 0, 0)
    assert struct.unpack('>H', cpu.mem_read(sound + 20 + 2 * 27, 2))[0] == 0x100
    call(0x40037326, obj, 238, 0, track, 0, 0, 0)
    assert struct.unpack('>H', cpu.mem_read(sound + 20 + 2 * 25, 2))[0] == 0x400
    # The actual sequencer lock applier is slot-based and must retain the full
    # generic domain while a different (stock-range) machine is in the UI.
    # Model already-built lock lists here; list creation/project persistence
    # and knob-to-lock recording are separate integration checks.
    cpu.mem_write(sound + 0xde, bytes([sc.TYPE]))
    lock_list = 0x46a30000
    lock_results = {}
    before_sound = bytes(cpu.mem_read(sound, 1163))
    for voice in (2, 5):
        locks = bytearray(20 + 202 * 8)
        struct.pack_into('>I', locks, 8, 16)
        values = [(0x4101 + i * 0x201 + voice) & 0x7fff for i in range(16)]
        for i, ((_, slot), value) in enumerate(zip(sc.ALL_RECORDS, values)):
            struct.pack_into('>HHI', locks, 20 + 8 * i, slot, value, 0)
        cpu.mem_write(lock_list, bytes(locks))
        call(0x400db092, voice, lock_list, 0x80003af0)
        assert 0x400db09a in visited  # displaced prologue returns to real stock body
        lock_results[voice] = values
        for other, expected_values in lock_results.items():
            for (_, slot), expected in zip(sc.ALL_RECORDS, expected_values):
                index = 17 + 101 * other + slot
                assert struct.unpack('>H', cpu.mem_read(0x80003af0 + 2 * index, 2))[0] == expected
                assert struct.unpack('>I', cpu.mem_read(0x8000de60 + 4 * index, 4))[0] == expected << 16
        assert bytes(cpu.mem_read(sound, 1163)) == before_sound
    Path('out/sidecar-native-setter.json').write_text(json.dumps(dict(
        scope='Compiled native setter and lock applier; fixture sound-reference getter and prebuilt lock lists; no full UI/recording/project claim.',
        sidecar_values_checked=checked, independent_allocated_voices=2,
        stock_ranges_restored=True, runtime_value_types_restored=True,
        fractional_locks_applied_with_stock_ui=32, locked_base_sound_unchanged=True), indent=2) + '\n')


def test_explicit_selection_uses_native_setters_and_restores_shared_records(compiled_runtime):
    """Real setters; only fixture sound-reference getter. No USB/UI claim."""
    uc = pytest.importorskip('unicorn')
    from unicorn import m68k_const as reg
    _, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(0x40000000, 0x08000000); cpu.mem_map(0x80000000, 0x10000)
    cpu.mem_write(0x40000400, built['content'])
    for key in ('chunk', 'c_chunk', 'machines_chunk'):
        cpu.mem_write(built[key]['load'], built[key]['code'])
    put = lambda at, value: cpu.mem_write(at, struct.pack('>I', value))
    stop, stack = 0x46a00800, 0x46a04000
    def call(fn, *args):
        cpu.mem_write(stack, struct.pack('>' + 'I' * (1 + len(args)), stop, *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000); cpu.reg_write(reg.UC_M68K_REG_A7, stack)
        cpu.emu_start(built['layout'][fn], stop, count=200000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
        return cpu.reg_read(reg.UC_M68K_REG_D0)
    obj, ref, ref_vt, getter, kit = 0x46a10000, 0x46a10100, 0x46a10200, 0x46a10400, 0x46a20000
    track = 3; sound = kit + 52 + 1163 * track
    put(obj, 0x401db7fc); put(obj + 16, ref); put(ref, ref_vt); put(ref + 4, sound)
    put(ref_vt + 40, getter); cpu.mem_write(getter, bytes.fromhex('206f0004202800044e75'))
    put(0x800052a0, kit); cpu.mem_write(sound + 0xde, bytes([sc.TYPE]))
    for voice in range(16):
        put(0x80005308 + 4 * voice, track if voice in (2, 5) else 99)
        put(0x800052a8 + 4 * voice, sound if voice in (2, 5) else 0)
    call('smp_formats', sc.KIND)
    record = lambda rid: 0x401f7f94 + 60 * rid
    entry = lambda rid: 0x4243325c + 68 * rid + 4
    # Deliberately restrictive previous-engine ranges. Selection must bypass and restore them.
    for rid, _ in sc.ALL_RECORDS:
        cpu.mem_write(record(rid)+8, struct.pack('>3I', 0x100, 0x200, 0x100))
    originals = {rid: (bytes(cpu.mem_read(record(rid), 60)), bytes(cpu.mem_read(entry(rid), 16)))
                 for rid, _ in sc.ALL_RECORDS}
    sets, view, ident = 0x46a11000, 0x46a12000, 0x46a15000
    cpu.mem_write(sets, struct.pack('>16I', *([obj]*16)))
    data = bytearray(5096); data[8:40] = b'demo.bell'.ljust(32, b'\0'); data[70] = 1
    defaults = [(i * 13 + 7) % 128 for i in range(16)]
    for i, default in enumerate(defaults):
        data[72+314*i+3:72+314*i+6] = bytes((0,127,default))
    cpu.mem_write(view, bytes(data))
    observed = []
    def enter_setter(_, at, size, user):
        sp = cpu.reg_read(reg.UC_M68K_REG_A7)
        args = struct.unpack('>8I', cpu.mem_read(sp, 32))
        assert struct.unpack('>I', cpu.mem_read(built['layout']['sc_edit_mask'],4))[0] == 1 << track
        assert bytes(cpu.mem_read(sound+20+2*33,2)) != b'\x53\x43'
        assert args[5:] == (0,0,0)  # no lock-recording, MIDI or announcement reentrancy
        observed.append(args[2])
    hook = cpu.hook_add(uc.UC_HOOK_CODE, enter_setter, begin=0x40037326, end=0x40037326)
    before = bytearray(cpu.mem_read(sound,1163))
    # Malformed descriptor and missing native parameter object leave everything untouched.
    cpu.mem_write(view+72+5, b'\xff')
    assert call('sc_select_apply', track, sound, sets, view) == 0
    cpu.mem_write(view, bytes(data)); put(sets+60,0)
    assert call('sc_select_apply', track, sound, sets, view) == 0
    assert bytes(cpu.mem_read(sound,1163)) == bytes(before) and not observed
    put(sets+60,obj)
    assert bytes(cpu.mem_read(built['layout']['sc_edit_mask'],4)) == bytes(4)
    assert call('sc_id_ok', view+8) == 1
    assert bytes(cpu.mem_read(sound+0xde,1)) == bytes([sc.TYPE])
    assert bytes(cpu.mem_read(sets,64)) == struct.pack('>16I', *([obj]*16))
    assert bytes(cpu.mem_read(view,5096)) == bytes(data)
    assert call('sc_select_apply', track, sound, sets, view) == 1, (observed, bytes(cpu.mem_read(view+70,10)).hex(), [struct.unpack('>H',cpu.mem_read(sound+20+2*slot,2))[0] for _,slot in sc.ALL_RECORDS])
    assert observed == [r for r,_ in sc.ALL_RECORDS]
    cpu.hook_del(hook)
    assert call('sc_sound_identity',sound,ident) == 1
    assert bytes(cpu.mem_read(ident,32)) == b'demo.bell'.ljust(32,b'\0')
    assert bytes(cpu.mem_read(built['layout']['sc_edit_mask'],4)) == bytes(4)
    for (rid,slot), default in zip(sc.ALL_RECORDS,defaults):
        assert struct.unpack('>H',cpu.mem_read(sound+20+2*slot,2))[0] == default << 8
        for voice in (2,5):
            assert struct.unpack('>H',cpu.mem_read(0x80003af0+2*(17+101*voice+slot),2))[0] == default << 8
        assert bytes(cpu.mem_read(record(rid),60)) == originals[rid][0]
        assert bytes(cpu.mem_read(entry(rid),16)) == originals[rid][1]
    # Fault-injected setter refusal: real remaining setters and rollback restore the old sound.
    snapshot = bytes(cpu.mem_read(sound,1163))
    data[8:40] = b'demo.tone'.ljust(32,b'\0')
    for i in range(16): data[72+314*i+5] = (defaults[i]+1)%128
    cpu.mem_write(view,bytes(data))
    refused = []
    def refuse_once(_,at,size,user):
        if refused:return
        refused.append(True)
        sp=cpu.reg_read(reg.UC_M68K_REG_A7)
        ret=struct.unpack('>I',cpu.mem_read(sp,4))[0]
        cpu.reg_write(reg.UC_M68K_REG_D0,0)
        cpu.reg_write(reg.UC_M68K_REG_A7,sp+4)
        cpu.reg_write(reg.UC_M68K_REG_PC,ret)
    hook=cpu.hook_add(uc.UC_HOOK_CODE,refuse_once,begin=0x40037326,end=0x40037326)
    assert call('sc_select_apply',track,sound,sets,view)==0
    cpu.hook_del(hook)
    assert refused and bytes(cpu.mem_read(sound,1163))==snapshot
    assert bytes(cpu.mem_read(built['layout']['sc_edit_mask'],4))==bytes(4)
    for (rid,slot),default in zip(sc.ALL_RECORDS,defaults):
        for voice in (2,5):
            assert struct.unpack('>H',cpu.mem_read(0x80003af0+2*(17+101*voice+slot),2))[0]==default<<8
        assert bytes(cpu.mem_read(record(rid),60))==originals[rid][0]
        assert bytes(cpu.mem_read(entry(rid),16))==originals[rid][1]
    # Refuse wrong tracks/machines rather than treating them as a Sidecar sound.
    snapshot = bytes(cpu.mem_read(sound,1163))
    assert call('sc_select_apply',8,sound,sets,view) == 0
    cpu.mem_write(sound+0xde,b'\x01')
    assert call('sc_select_apply',track,sound,sets,view) == 0
    cpu.mem_write(sound+0xde,bytes([sc.TYPE])); assert bytes(cpu.mem_read(sound,1163)) == snapshot
    # Final confirmation can commit a complete installed descriptor before the
    # Pi has a spare slot. Missing/bad/loading/muted descriptors cannot commit.
    for state in (2,3,4,5,6):
        cpu.mem_write(view+70,bytes([state]))
        assert call('sc_select_apply',track,sound,sets,view)==0
        assert bytes(cpu.mem_read(sound,1163))==snapshot
    for state in (0,):
        data[70]=state
        data[8:40]=b'demo.tone'.ljust(32,b'\0')
        cpu.mem_write(view,bytes(data))
        assert call('sc_select_apply',track,sound,sets,view)==1
        assert call('sc_sound_identity',sound,ident)==1
        assert bytes(cpu.mem_read(ident,32))==data[8:40]
        assert bytes(cpu.mem_read(built['layout']['sc_edit_mask'],4))==bytes(4)
    # A failed rollback must remain held, but final confirmation can repair it.
    # Emulate setter refusal once on the forward pass and once on rollback.
    mask=lambda:struct.unpack('>I',cpu.mem_read(built['layout']['sc_edit_mask'],4))[0]
    def hold_failed_selection():
        for i,(_,slot) in enumerate(sc.ALL_RECORDS):
            old=struct.unpack('>H',cpu.mem_read(sound+20+2*slot,2))[0]>>8
            data[72+314*i+5]=(old+1)%128
        data[8:40]=b'demo.noise'.ljust(32,b'\0')
        cpu.mem_write(view,bytes(data))
        calls=[]
        def refuse_two(_,at,size,user):
            n=len(calls);calls.append(n)
            if n not in (0,17):return
            sp=cpu.reg_read(reg.UC_M68K_REG_A7)
            ret=struct.unpack('>I',cpu.mem_read(sp,4))[0]
            cpu.reg_write(reg.UC_M68K_REG_D0,0)
            cpu.reg_write(reg.UC_M68K_REG_A7,sp+4)
            cpu.reg_write(reg.UC_M68K_REG_PC,ret)
        assert call('sc_sound_identity',sound,ident)==1
        old_id=bytes(cpu.mem_read(ident,32))
        hook=cpu.hook_add(uc.UC_HOOK_CODE,refuse_two,begin=0x40037326,end=0x40037326)
        cpu.ctl_remove_cache(0x40037326,0x40037328)
        result=call('sc_select_apply',track,sound,sets,view)
        assert result==0xffffffff,(result,len(calls),data[77],struct.unpack('>H',cpu.mem_read(sound+20+2*sc.ALL_RECORDS[0][1],2))[0])
        cpu.hook_del(hook)
        assert len(calls)==32 and mask()==1<<track
        assert call('sc_sound_identity',sound,ident)==1 and bytes(cpu.mem_read(ident,32))==old_id
        call('sc_select_poll');assert mask()==1<<track
    hold_failed_selection()
    # A refused retry cannot resume the earlier partially changed sound, even
    # if this retry successfully rolls back to that already-damaged snapshot.
    refused.clear()
    hook=cpu.hook_add(uc.UC_HOOK_CODE,refuse_once,begin=0x40037326,end=0x40037326)
    cpu.ctl_remove_cache(0x40037326,0x40037328)
    assert call('sc_select_apply',track,sound,sets,view)==0xffffffff
    cpu.hook_del(hook);assert mask()==1<<track
    assert call('sc_select_apply',track,sound,sets,view)==1 and mask()==0
    for i,(_,slot) in enumerate(sc.ALL_RECORDS):
        assert struct.unpack('>H',cpu.mem_read(sound+20+2*slot,2))[0]==data[72+314*i+5]<<8
    # Successful project LOAD/NEW and a new kit must not inherit a stale hold.
    for counter in ('smp_pj_loads','smp_pj_news'):
        hold_failed_selection()
        at=built['layout'][counter];put(at,struct.unpack('>I',cpu.mem_read(at,4))[0]+1)
        call('sc_select_poll');assert mask()==0
    hold_failed_selection();put(0x800052a0,kit+0x10000)
    call('sc_select_poll');assert mask()==0
