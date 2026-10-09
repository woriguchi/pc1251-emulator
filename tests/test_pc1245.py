"""PC-1245として動かす(rom/cpu-1245.romとrom/bas-1245.romが必要)"""

import os
import sys
import types

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pc1251emu import basictext  # noqa: E402
from pc1251emu.app import App, Typer, export_program, parse_hexdump  # noqa: E402
from pc1251emu.lcdtext import lcd_text  # noqa: E402
from pc1251emu.machine import CLOCK, PC1251  # noqa: E402

DUMP = os.path.join(os.path.dirname(__file__), "..", "programs", "pcint.hex")


def boot():
    m = PC1251(model="1245")
    m.run(CLOCK)
    return m, Typer(m)


def typ(m, t, text, wait=0.5):
    t.add_text(text)
    while t.busy:
        t.step()
        m.run(CLOCK // 200)
    m.run(int(CLOCK * wait))
    return lcd_text(m)


def value(text):
    """表示の数(末尾の小数点は字の表にないので?になる)"""
    return text.replace("?", " ").strip()


def enter(m, t, program):
    m.mode = "PRO"
    m.run(CLOCK // 5)
    t.add_program(program)
    while t.busy:
        t.step()
        m.run(CLOCK // 200)
    m.run(CLOCK // 2)


def test_prompt_and_memory():
    m, t = boot()
    assert m.display_on()
    assert len(lcd_text(m)) == 16  # 液晶は16桁
    # 液晶にはモードの表示がない(DEGだけ点く)
    assert m.symbols() == {"DE", "G"}
    assert value(typ(m, t, "MEM\n")) == "1486"


def test_parentheses_are_on_1_and_2():
    """PC-1245の括弧はSHIFT+1、SHIFT+2(PC-1251は↓↑)"""
    m, t = boot()
    assert value(typ(m, t, "(1+2)*3\n")) == "9"


def test_shift_letter_gives_keyword():
    """A〜=の段、Z〜SPCの段はSHIFTで命令になる(キーの上の刷り)"""
    m, t = boot()
    m.mode = "PRO"
    m.run(CLOCK // 5)
    typ(m, t, "10 ")
    t.add_keys([["SHIFT"], ["Z"], ["1"], ["SHIFT"], ["N"], ["ENTER"]])
    typ(m, t, "")
    text = basictext.program_text(m.mem, start=m.model.prog_start)
    assert text == "10 PRINT 1 END\n" or text.replace(" ", "") == "10PRINT1END\n", text


def test_program_at_c000_and_export(tmp_path=None):
    import tempfile

    m, t = boot()
    enter(m, t, '10 A=(2+3)*4\n20 PRINT "X";A\n')
    assert m.mem[0xC000] == 0xFF and m.mem[0xC001] == 0xE0
    d = tmp_path or tempfile.mkdtemp()
    path = export_program(m, str(d))
    assert path is not None
    body = open(path, encoding="utf-8").read().split("\n", 1)[1]
    assert body == '10 A=(2+3)*4\n20 PRINT "X";A\n', body
    m.mode = "RUN"
    m.run(CLOCK // 5)
    assert value(typ(m, t, "RUN\n", wait=3)).replace(" ", "") == "X20"


def test_long_line():
    """79字を超える行も分けて打ち込める"""
    line = "20 " + ": ".join(f"PRINT A{i}" for i in range(9))
    m, t = boot()
    enter(m, t, "10 PRINT 1\n" + line + "\n30 END\n")
    lines = basictext.program_text(m.mem, start=m.model.prog_start).splitlines()
    assert lines[1].replace(" ", "") == line.replace(" ", "")
    assert lines[2] == "30 END"


def test_full_line_by_inserting():
    """上限ちょうど(行番号の桁と中間コードで79字)の行も、命令を先に打ってから挿入して入れられる"""
    line = (
        '310 "C":LPRINT "":FOR K=0 TO M-11:FOR J=0 TO N-11:D(K,J)=0:FOR I=0 TO L-1:'
        "D(K,J)=D(K,J)+B(K,I)*C(I,J):NEXT I"
    )
    m, t = boot()
    enter(m, t, line + "\n")
    lines = dict(basictext.program_lines(m.mem, m.model.prog_start))
    assert len("310") + len(lines[310]) == 79
    text = basictext.program_text(m.mem, start=m.model.prog_start)
    assert text.splitlines()[0].replace(" ", "") == line.replace(" ", "")


def test_program_survives_power_off():
    m, t = boot()
    enter(m, t, "10 PRINT 123\n")
    assert m.power_off()
    m.mode = "RUN"
    m.wake()
    m.run(CLOCK)
    assert basictext.program_text(m.mem, start=m.model.prog_start) == "10 PRINT 123\n"


def test_pc_interpreter():
    m, t = boot()
    for addr, data in parse_hexdump(DUMP):
        for i, b in enumerate(data):
            m.write(addr + i, b)
    enter(m, t, "10 A=03+04*02:B=A*02:BEEP 09,05:END\n")
    m.mode = "RUN"
    m.run(CLOCK // 5)
    m.sound_events.clear()
    typ(m, t, "CALL &C300\n", wait=1)
    assert (m.mem[0xC686], m.mem[0xC687]) == (0x0E, 0x1C)
    assert {4, 5} <= {e[1] for e in m.sound_events}


def test_lcd_right_part():
    """左の12桁はF800から順に、残りの4桁はF87Bから逆順に並ぶ"""
    m, _t = boot()
    m.mem[0xF800] = 0x7F
    m.mem[0xF87B] = 0x41
    m.mem[0xF868] = 0x22
    m.mem[0xF867] = 0x7F  # 17桁目(液晶にない)
    cols = m.columns()
    assert len(cols) == 80
    assert (cols[0], cols[60], cols[79]) == (0x7F, 0x41, 0x22)


def test_breakout_versions():
    """ブロック崩しはPC-1251用とPC-1245用があり、一覧にはその機種のものだけが出る"""
    from pc1251emu import programs

    here = os.path.join(os.path.dirname(__file__), "..", "programs")
    items = programs.scan([here])
    for model in ("1251", "1245"):
        shown = [p for p in programs.for_model(items, model) if p.title.startswith("ブロック崩し")]
        assert [p.model for p in shown] == [model]
        assert os.path.basename(os.path.dirname(shown[0].paths[0])) == "pc" + model
        found = programs.find("break", model)
        assert found is not None and found.model == model
    old = next(p for p in items if p.name == "break" and p.model == "1251")
    assert old.label("1245").endswith("(PC-1251用)")
    args = types.SimpleNamespace(
        scale=1.0, type=None, load=None, fresh=True, mute=True, persist=1.0, model="1245"
    )
    app = App(args)
    app.open_program(old, run=True)  # PC-1251用はPC-1245では読み込まない
    assert not app.typer.busy and "PC-1251用" in app.status
    app.close()


def test_breakout_on_pc1245():
    from test_smoke import _play_breakout

    for level, height in (("1", 3), ("2", 2)):
        _play_breakout(level, height, "1245")


def test_app_starts_as_pc1245():
    import pygame

    args = types.SimpleNamespace(
        scale=1.0, type=None, load=None, fresh=True, mute=True, persist=1.0, model="1245"
    )
    app = App(args)
    for _ in range(40):
        app.frame()
    assert pygame.display.get_caption()[0] == "SHARP PC-1245"
    assert [m for m, _y in app.sw_stops] == ["PRO", "RUN", "OFF"]
    app.move_switch(-1)
    assert app.m.mode == "PRO"
    app.move_switch(-1)  # いちばん上で止まる(RSVはない)
    assert app.m.mode == "PRO"
    app.key_down(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F3, mod=0))
    assert app.m.mode == "PRO"
    app.set_mode("RUN")
    for _ in range(20):
        app.frame()
    app.typer.add_text("6*7\n")
    for _ in range(200):
        app.frame()
        if not app.typer.busy:
            break
    for _ in range(10):
        app.frame()
    assert value(lcd_text(app.m)) == "42"
    app.close()
