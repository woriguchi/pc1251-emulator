"""ROMなしで動くCPUコアの試験(命令の並びは『PC-インタープリタを読む』の逆アセンブルに合わせた)"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pc1251emu.sc61860 import SC61860, A, B, Bus  # noqa: E402


class FlatBus(Bus):
    """64KBをすべてRAMとして見せるだけのバス"""

    def __init__(self, code: bytes, at: int = 0):
        self.mem = bytearray(0x10000)
        self.mem[at : at + len(code)] = code

    def read(self, a: int) -> int:
        return self.mem[a]

    def write(self, a: int, v: int) -> None:
        self.mem[a] = v


def run(code: bytes, steps: int, extra: dict[int, bytes] | None = None):
    bus = FlatBus(code)
    for at, data in (extra or {}).items():
        bus.mem[at : at + len(data)] = data
    cpu = SC61860(bus)
    for _ in range(steps):
        cpu.step()
    return cpu, bus


def test_load_and_exchange():
    # LIA 12 / LP 10 / EXAM / LIA 00 / LDM / INCA
    cpu, _ = run(bytes([0x02, 0x12, 0x90, 0xDB, 0x02, 0x00, 0x59, 0x42]), 6)
    assert cpu.ram[0x10] == 0x12  # EXAMで(P)に12が入る
    assert cpu.ram[A] == 0x13  # LDMで12を読み戻して1足した


def test_call_and_return():
    # CALL 0010 / (0010) LIA 2A / RTN
    cpu, _ = run(bytes([0x78, 0x00, 0x10]), 3, {0x10: bytes([0x02, 0x2A, 0x37])})
    assert cpu.ram[A] == 0x2A
    assert cpu.pc == 3


def test_count_down_loop():
    # LIB 03 / LIA 00 / INCA / DECB / JRNZM (INCAへ)
    code = bytes([0x03, 0x03, 0x02, 0x00, 0x42, 0xC3, 0x29, 0x03])
    cpu, _ = run(code, 2 + 3 * 3)
    assert cpu.ram[A] == 3 and cpu.ram[B] == 0
    assert cpu.pc == 8


def test_external_memory():
    # LIDP 1234 / LIA 99 / STD / LIA 00 / LDD
    code = bytes([0x10, 0x12, 0x34, 0x02, 0x99, 0x52, 0x02, 0x00, 0x57])
    cpu, bus = run(code, 5)
    assert bus.mem[0x1234] == 0x99
    assert cpu.ram[A] == 0x99


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
