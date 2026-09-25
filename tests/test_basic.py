"""実ROMで電卓・BASIC・PC-インタープリタを動かす

ROM(rom/cpu-1251.rom, rom/bas-1251.rom)が必要。PC-インタープリタの試験には
記事のダンプ(PC1251_PCINT_DUMP、既定はprograms/pcint.hex)を使う。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pc1251emu.app import Typer, parse_hexdump  # noqa: E402
from pc1251emu.audio import Buzzer  # noqa: E402
from pc1251emu.lcdtext import lcd_text  # noqa: E402
from pc1251emu.machine import CLOCK, PC1251  # noqa: E402

DUMP = os.environ.get(
    "PC1251_PCINT_DUMP",
    os.path.join(os.path.dirname(__file__), "..", "programs", "pcint.hex"),
)


def boot():
    m = PC1251()
    m.run(CLOCK)
    return m, Typer(m)


def typ(m, t, text, wait=0.5):
    t.add_text(text)
    while t.busy:
        t.step()
        m.run(CLOCK // 200)
    m.run(int(CLOCK * wait))
    return lcd_text(m)


def test_prompt():
    m, _ = boot()
    assert m.display_on()
    assert {"RUN", "DE", "G"} <= m.symbols()


def test_calc():
    m, t = boot()
    assert typ(m, t, "12*3\n").strip() == "36?"  # 末尾は小数点(記号は?で出る)


def test_program():
    m, t = boot()
    m.mode = "PRO"
    m.run(CLOCK // 5)
    typ(m, t, "10 FOR I=1 TO 20:NEXT I\n20 PRINT I*2\n")
    m.mode = "RUN"
    m.run(CLOCK // 5)
    typ(m, t, "RUN\n", wait=3)
    assert lcd_text(m).strip().startswith("40")


def _enter_program(text):
    m, t = boot()
    m.mode = "PRO"
    m.run(CLOCK // 5)
    typ(m, t, text)
    return m, t


def test_program_survives_power_off():
    """スイッチをOFFにしてから戻しても、プログラムが残る"""
    m, t = _enter_program("10 PRINT 123\n")
    assert m.power_off()
    m.wake()
    m.mode = "PRO"
    m.run(CLOCK)
    assert typ(m, t, "LIST\n").startswith("10")


def test_program_survives_restart(tmp="/tmp/pc1251_test_ram.bin"):
    """終了時の保存と次の起動での読み込みで、プログラムが残る"""
    m, _ = _enter_program("10 PRINT 123\n")
    assert m.power_off()
    m.save_ram(tmp)
    m2 = PC1251()
    assert m2.load_ram(tmp)
    m2.mode = "PRO"
    m2.run(CLOCK)
    assert typ(m2, Typer(m2), "LIST\n").startswith("10")


def test_auto_power_off_about_11_minutes():
    """何もしないと約11分で電源が切れ、プログラムは残る(Cポートのビット2で止まって
    512msのタイマごとに起きる回数を数えている)"""
    m, t = _enter_program("10 PRINT 123\n")
    m.mode = "RUN"
    seconds = 0
    while m.power and seconds < 900:
        m.run(CLOCK)
        seconds += 1
    assert 600 <= seconds <= 720, seconds
    m.brk = True  # ONキー
    m.run(CLOCK // 10)
    m.brk = False
    m.mode = "PRO"
    m.run(CLOCK)
    assert typ(m, t, "LIST\n").startswith("10")


def test_direct_print_is_error_1():
    # ROM(56BA)は手動計算の状態でPRINTを受け付けず、ERROR 1にする
    m, t = boot()
    assert typ(m, t, "PRINT 3\n").strip() == "ERROR 1"


def test_basic_beep_uses_4khz():
    m, t = boot()
    typ(m, t, "BEEP 1", wait=0.0)
    m.sound_events.clear()
    c0 = m.cpu.cycles
    typ(m, t, "\n", wait=0.5)
    modes = {e[1] for e in m.sound_events}
    assert 3 in modes  # 内蔵の4kHz発振
    assert Buzzer().render(m.sound_events, c0, m.cpu.cycles)


def test_pc_interpreter():
    if not os.path.exists(DUMP):
        return
    m, t = boot()
    for addr, data in parse_hexdump(DUMP):
        for i, b in enumerate(data):
            m.write(addr + i, b)
    m.mode = "PRO"
    m.run(CLOCK // 5)
    typ(m, t, "10 A=03+04*02:B=A*02:BEEP 09,05:END\n")
    m.mode = "RUN"
    m.run(CLOCK // 5)
    m.sound_events.clear()
    typ(m, t, "CALL &C300\n", wait=1)
    # 変数はC686〜C69Fの1バイト(A=C686)
    assert m.mem[0xC686] == 0x0E
    assert m.mem[0xC687] == 0x1C
    # BEEPは5と4を交互に書いて振動板を動かす
    ev = [e for e in m.sound_events if e[1] in (4, 5)]
    assert {4, 5} <= {e[1] for e in ev}
    # 書き込みの時刻は命令ごとのサイクルで記録される(2msのまとまりに潰れない)。
    # BEEP 09の1周期は128サイクル(192kHzで1.5kHz)
    gaps = [ev[i + 1][0] - ev[i][0] for i in range(len(ev) - 1)]
    assert min(gaps) > 0
    assert gaps[0] + gaps[1] == 128


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
