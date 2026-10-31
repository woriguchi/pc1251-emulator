"""ROMを読んでわかったことが、エミュレータでも同じように起きるか"""

import os
import subprocess
import sys

from helpers import boot, finish, typ

from sc61box import romsyms
from sc61box.machine import CLOCK

ROOT = os.path.join(os.path.dirname(__file__), "..")
ASM = os.path.join(ROOT, "tools", "asm61860.py")


def value(text):
    return text.replace("?", " ").strip().splitlines()[-1].strip()


def enter(m, t, program):
    m.mode = "PRO"
    m.run(CLOCK // 5)
    t.add_program(program)
    finish(m, t)
    m.run(CLOCK // 2)
    m.mode = "RUN"
    m.run(CLOCK // 5)


def call(m, addr, ret=0xC4F0, limit=2_000_000):
    """CALと同じ形で戻り番地を積んでaddrを呼び、戻るまで1命令ずつ動かす"""
    cpu = m.cpu
    cpu.push(ret >> 8)
    cpu.push(ret & 0xFF)
    cpu.pc = addr
    n = 0
    while cpu.pc != ret:
        n += cpu.step()
        assert n < limit, f"{addr:04X}から戻らない"
    return n


def test_rom_version_byte():
    """7FFF番地で機種と版がわかる(本書のROMはF0版。PC-1245は01)"""
    for model, v in (("1251", 0xF0), ("1245", 0x01)):
        m, t = boot(model)
        assert m.mem[0x7FFF] == v
        assert v in romsyms.VERSIONS


def test_array_subscript_fixed_only_on_pc1245():
    """2つ目の添字に配列の要素を書くと、PC-1251は1つ目の添字を0にしてしまう"""
    prog = "10 DIM B(2,3),C(3):C(1)=2:B(1,C(1))=5:Z=B(0,2)*10+B(1,2)\n"
    for model, z in (("1251", "50"), ("1245", "5")):
        m, t = boot(model)
        enter(m, t, prog)
        typ(m, t, "RUN\n", 1.0)
        assert value(typ(m, t, "Z\n")) == z


def test_exponent_with_space_only_on_pc1245():
    """PC-1245だけ、指数の中の空白を飛ばすルーチン(0522)がある"""
    for model, v in (("1251", "1"), ("1245", "100")):
        m, t = boot(model)
        assert value(typ(m, t, 'VAL "1[E] 2"\n')) == v  # [E]は指数のE(4Bh)


def test_for_next_checks_before_adding_step():
    """PC-1251のNEXTは足す前の値で終わりを調べるので、終わりの値を越えた5でも1回回る"""
    m, t = boot()
    enter(m, t, "10 S=0:FOR I=1 TO 4 STEP 2:S=S*10+I:NEXT I\n")
    typ(m, t, "RUN\n", 1.0)
    assert value(typ(m, t, "S\n")) == "135"
    assert value(typ(m, t, "I\n")) == "5"


def test_twelve_digits_then_round():
    """計算は12桁で、式の値を出すときだけ10桁に丸める"""
    m, t = boot()
    assert value(typ(m, t, "1/3*3\n")) == "1"
    # -1.E-11と-1.E-10(負の符号と「.E」は字の表にないので?になる)
    assert value(typ(m, t, "1/3*3-1\n")).endswith("11")
    typ(m, t, "A=1/3\n")
    assert value(typ(m, t, "A*3-1\n")).endswith("10")


def _poke_add_sub(m, entry):
    """変数A・Bを演算Y・演算Xに写してentryを呼び、答えを変数Cに入れる機械語"""
    code = bytes.fromhex(
        "10C698 A8 0007 18"  # LIDP C698; LP 28; LII 7; MVWD(演算Y ← A)
        "10C690 A0 18"  # LIDP C690; LP 20; MVWD(演算X ← B)
        + f"{0xE000 | entry:04X}"  # CAL entry
        + "3A08"  # JRCP 末尾のRTN
        "10C688 A0 0007 19"  # LIDP C688; LP 20; LII 7; EXWD(C ← 演算X)
        "37"
    )
    m.mem[0xC500 : 0xC500 + len(code)] = code


def test_subtract_entry_is_0b67_not_0b69():
    """日本語版マニュアルの表の0B69(減算)は入口の途中。0B67から呼ぶと正しい"""
    for entry, negative in ((romsyms.symbols()["FSUB"], False), (0x0B69, True)):
        m, t = boot()
        _poke_add_sub(m, entry)
        for line in ("A=-2\n", "B=-7\n", "CALL &C500\n"):
            typ(m, t, line)
        c = m.mem[0xC688:0xC690]  # 変数C(-2-(-7)の答え)
        assert c[2] == 0x50  # 仮数は5
        assert bool(c[1] & 0x08) is negative  # 0B69では符号が狂って-5になる


def test_display_on_entry_is_11e0():
    """表示ONは11E0。表の11EDはRTNで、何もしない"""
    m, t = boot()
    m.pc_out = 0
    call(m, 0x11ED)
    assert m.pc_out & 1 == 0
    call(m, romsyms.symbols()["DISPON"])
    assert m.pc_out & 1 == 1


def test_glyph_needs_j_one():
    """1FBC(字の形の番地)は、中でJを入れずにMVBを使うので、Jが1でないと狂う"""
    m, t = boot()
    for j, ok in ((1, True), (0, False)):
        m.cpu.ram[0x01] = j
        m.cpu.ram[0x02] = 0x51  # Aの字
        call(m, romsyms.symbols()["GLYPH"])
        x = m.cpu.ram[0x04] | m.cpu.ram[0x05] << 8
        assert (x == 0x4558) is ok


def test_assembler_knows_rom_names(tmp_path):
    src = tmp_path / "t.asm"
    out = tmp_path / "t.hex"
    src.write_text("        ORG &C500\n        CAL FADD\n        CAL KEYSCAN\n        RTN\n")
    cmd = [sys.executable, ASM, str(src), str(out), "--rom", "1251"]
    subprocess.run(cmd, check=True, capture_output=True)
    text = out.read_text()
    assert "C500 EB 50" in text and "C502 FF 44" in text


def test_pc1350_rom_sums():
    """PC-1350のどこからも呼ばれないベクタ802D・802Aは、ROMの16ビットの和を表示する"""
    m, t = boot("1350")
    assert "31887" in typ(m, t, "CALL &802D\n", 4.0)


def test_pc1350_overseas_wiring():
    """KO7とINAのビット7がつながっていると、ROMは輸出向け(カナの代わりに英小文字)になる"""
    for overseas, bit7, sym in ((False, 0x80, "KANA"), (True, 0x00, "SML")):
        m, t = boot("1350", overseas=overseas)
        assert m.mem[0x6F16] & 0x80 == bit7
        t.add_keys([["KANA"]])
        typ(m, t, "", 0.3)
        assert sym in m.symbols()


def test_assembler_ptc_dtc(tmp_path):
    """PTC・DTCで値ごとに行き先を分け、処理のRTNでPTCの番地へ戻る(付録Cのフレーズ)"""
    src = tmp_path / "t.asm"
    out = tmp_path / "t.hex"
    src.write_text(
        "        ORG &C100\n        PTC 2,E\n        DTC\n"
        "        DB  5,hi(L1),lo(L1)\n        DB  7,hi(L2),lo(L2)\n        DB  hi(LD),lo(LD)\n"
        "E:      RTN\nL1:     LIB 1\n        RTN\nL2:     LIB 2\n        RTN\n"
        "LD:     LIB &FF\n        RTN\n"
    )
    subprocess.run([sys.executable, ASM, str(src), str(out)], check=True, capture_output=True)
    rows = [line for line in out.read_text().splitlines() if line[:1] == "C"]
    code = bytes.fromhex("".join(line.split(";")[0].split(None, 1)[1] for line in rows))
    assert code[:5] == bytes([0x7A, 0x02, 0xC1, 0x0D, 0x69])
    for a, b in ((5, 1), (7, 2), (9, 0xFF)):
        m, t = boot()
        m.mem[0xC100 : 0xC100 + len(code)] = code
        m.cpu.ram[0x02] = a
        call(m, 0xC100)
        assert m.cpu.ram[0x03] == b
