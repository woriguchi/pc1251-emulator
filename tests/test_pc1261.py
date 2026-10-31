"""PC-1261(とPC-1260・PC-1262)として動かす(rom/cpu-1260.romとrom/bas-1260.romが必要)"""

import os

import pygame
from helpers import boot as _boot
from helpers import finish, lines, make_app, typ

from sc61box import basictext, display, keytype, programs
from sc61box.app import Typer
from sc61box.lcdtext import lcd_text
from sc61box.machine import CLOCK, PC1251


def boot(model="1261"):
    return _boot(model)


def enter(m, t, program):
    t.add_mode("PRO")
    t.add_program(program)
    t.add_mode("RUN")
    finish(m, t)
    m.run(CLOCK // 2)


def test_prompt_two_lines_and_memory():
    m, t = boot()
    assert m.display_on()
    assert lines(m) == [">", ""]  # 2行×24桁
    assert len(m.columns()) == 2 * 24 * 5
    assert m.symbols() == {"DEG"}
    typ(m, t, "MEM\n")
    assert lines(m)[1].strip() == "9342."


def test_open_bus_reads_high_byte():
    """何もつながっていない番地は、番地の上位バイトが読める"""
    m, t = boot()
    assert m.read(0x7FFF) == 0x7F
    assert m.read(0x3000) == 0x30
    m.write(0x7FFF, 0)
    assert m.read(0x7FFF) == 0x7F


def test_hidden_symbol_right_of_error():
    """ERRORの右の字のない横棒は207Cのビット6で点く(実機で確かめた)"""
    m, t = boot()
    typ(m, t, "POKE &207C,&40\n")
    assert "HIDDEN" in m.symbols()
    typ(m, t, "POKE &207C,0\n")
    assert "HIDDEN" not in m.symbols()
    pygame.init()
    pygame.display.set_mode((display.OUT_W, display.OUT_H))
    panel = display.Panel("1261")
    assert panel.symbols["HIDDEN"][0] > panel.symbols["ERROR"][0]


def test_pc1260_has_4kb():
    m, t = boot("1260")
    assert m.model.ram == (0x5800, 0x6800)
    typ(m, t, "MEM\n")
    assert lines(m)[1].strip() == "3198."


def test_expression_uses_lcd_chip_ram():
    """式の計算はROMが2880-28FFをスタックに使う(書けないとERROR 1になる)"""
    m, t = boot()
    typ(m, t, "1+2*3/7\n")
    assert lines(m)[1].strip() == "1.857142857"
    assert "ERROR" not in m.symbols()


def test_shifted_symbols():
    """括弧は1と2の上、¥は6の上。指数は英字のE"""
    m, t = boot()
    typ(m, t, "(1+2)*3E2\n")
    assert lines(m)[1].strip() == "900."
    assert keytype.keys_for("¥", "1261") == [["SHIFT"], ["6"]]


def test_symbols():
    m, t = boot()
    t.add_keys([["SHIFT"]])
    typ(m, t, "")
    assert "SHIFT" in m.symbols()
    t.add_keys([["SHIFT"]])
    typ(m, t, "")
    t.add_keys([["SHIFT"], ["8"]])  # カナの入力
    typ(m, t, "")
    assert "KANA" in m.symbols() and "SMALL" not in m.symbols()
    t.add_keys([["SHIFT"], ["8"]])
    typ(m, t, "RADIAN\n")
    assert m.symbols() == {"RAD"}
    typ(m, t, "1/0\n")
    assert "ERROR" in m.symbols()


def test_kana_typing():
    m, t = boot()
    typ(m, t, '"ポケコン ガッコウ"\n')
    assert lines(m)[1] == "ﾎﾟｹｺﾝ ｶﾞｯｺｳ"
    assert "KANA" not in m.symbols()  # 打ち終わったらカナの入力から戻る


def test_program_export_and_save(tmp_path):
    m, t = boot()
    src = '10 A=π*√4:B$="¥ｱ":IF A>=B THEN 10\n20 REM PRINT A<>B\n30 PRINT SIN 30;CHR$ 65\n'
    enter(m, t, src)
    assert m.mem[m.model.prog_start] == 0xFF
    text = basictext.program_text(m.mem, start=m.model.prog_start)
    assert text == src
    # 液晶RAM(角度の単位の印がある)も保存する
    typ(m, t, "RADIAN\n")
    path = tmp_path / "ram.bin"
    m.save_ram(str(path))
    m2 = PC1251(model="1261")
    assert m2.load_ram(str(path))
    assert basictext.program_text(m2.mem, start=m2.model.prog_start) == src
    assert m2.symbols() == {"RAD"}


def test_run_program_on_two_lines():
    m, t = boot()
    enter(m, t, '10 PRINT "**** HELLO! PC-1261 ****";"ABCDEFGHIJKLMNOPQRSTUVWX"\n')
    typ(m, t, "RUN\n")
    assert lines(m) == ["**** HELLO! PC-1261 ****", "ABCDEFGHIJKLMNOPQRSTUVWX"]


def test_panel_draws_two_lines():
    pygame.init()
    pygame.display.set_mode((display.OUT_W, display.OUT_H))
    m, t = boot()
    enter(m, t, '10 PRINT "ABC";"IIIIIIIIIIIIIIIIIIIIIIII"\n')
    typ(m, t, "RUN\n")
    panel = display.Panel("1261")
    panel.set_fps(30, persist=0)
    surf = panel.draw(m.columns(), m.symbols(), m.display_on(), m.mode)
    # 2行目の1桁目の「I」のまんなかの縦線は点き、1行目の同じ列は消えている
    x = display.MARGIN + panel.mat_x + panel.col_x[2] + 2
    y2 = display.MARGIN + panel.mat_y + panel.line_pitch + 3 * panel.pitch_y + 2
    y1 = display.MARGIN + panel.mat_y + 3 * panel.pitch_y + 2
    assert sum(surf.get_at((x, y2))[:3]) < sum(surf.get_at((x, y1))[:3]) - 150
    assert display.asset_dir("1262") == display.asset_dir("1261")
    assert "pc1262" in display.asset_path("1262", "body_top.png")


def test_programs_for_1261_family():
    items = programs.scan([os.path.join(os.path.dirname(__file__), "..", "programs")])
    hello = [p for p in items if p.title.startswith("2行の表示")]
    assert hello and all(p.runs_on(x) for p in hello for x in ("1260", "1261", "1262"))
    assert not hello[0].runs_on("1251")
    pcint = [p for p in items if p.title.startswith("PC-インタープリタ")]
    assert pcint and not any(p.runs_on("1261") for p in pcint)


def test_tape_round_trip(tmp_path):
    """ROMのCSAVEでwavにし、別の本体でCLOADすると同じプログラムになる
    (CPUの速さが合っていないと、ROMはテープを読み違える)"""
    from sc61box import tape

    prog = programs.find("hello", "1261")
    assert prog is not None
    files = tape.program_wavs(prog, "1261", str(tmp_path))
    assert [c for _, c in files] == ['CLOAD "HELLO"']
    src = PC1251(model="1261")
    src.run(CLOCK)
    enter(src, Typer(src), prog.basic)
    m = PC1251(model="1261")
    m.run(CLOCK)
    for path, command in files:
        m.tape = tape.TapeIn(path)
        tape._type(m, command + "\n")
        while not m.tape.done(m.cpu.cycles):
            m.run(CLOCK)
        m.run(CLOCK)
    loaded = basictext.program_text(m.mem, start=m.model.prog_start)
    assert loaded and loaded == basictext.program_text(src.mem, start=src.model.prog_start)


def test_switch_off_keeps_program():
    """スイッチをOFFにするとROMが自分で電源を切り、入れ直してもプログラムは残る"""
    m, t = boot()
    enter(m, t, "10 PRINT 1\n")
    assert m.power_off()
    m.mode = "RUN"
    m.brk = True
    m.run(CLOCK // 10)
    m.brk = False
    m.run(CLOCK)
    assert m.power
    assert basictext.program_text(m.mem, start=m.model.prog_start) == "10 PRINT 1\n"


def test_bouncing_ball_uses_both_lines():
    """見本の弾むボールは2行目の下端で弾んで1行目まで上がり、弾むたびに鳴る。
    BRKでBASICに戻る"""
    prog = programs.find("ball", "1261")
    assert prog is not None and prog.blocks[0][0] == 0x5A00
    end = prog.blocks[-1][0] + len(prog.blocks[-1][1])
    assert end < 0x6400  # BASICの変数の場所(6400より上)にかからない
    m, t = boot()
    for addr, data in prog.blocks:
        for i, b in enumerate(data):
            m.write(addr + i, b)
    typ(m, t, "CALL &5A00\n", wait=0)
    m.sound_events.clear()
    rows = [0, 0]  # 行ごとに、点いたことのあるドットの行のビット
    for _ in range(45):  # 1.5秒(最初の着地と、跳ね上がり)
        m.run(CLOCK // 30)
        cols = m.columns()
        for line in (0, 1):
            for c in cols[line * 120 : (line + 1) * 120]:
                rows[line] |= c
        lit = sum(bin(c).count("1") for c in cols)
        assert lit <= 30  # ボールは1個だけ
    assert rows[0] and rows[1] & 0x40  # 1行目にも出て、2行目のいちばん下まで下りる
    # 音はCポートのビット4で鳴らす。70〜200Hzくらい
    ups = [c for c, v in m.sound_events if v == 1]
    assert len(ups) > 10
    periods = [b - a for a, b in zip(ups, ups[1:], strict=False)]
    assert CLOCK // 1000 < min(periods) and sorted(periods)[len(periods) // 2] < CLOCK // 70
    m.brk = True
    m.run(CLOCK // 5)
    m.brk = False
    m.run(CLOCK)
    assert not 0x5A00 <= m.cpu.pc < end  # BASICに戻っている
    assert m.pc_out & 0x10 == 0  # 音は止まっている
    typ(m, t, "1+1\n")
    assert lines(m)[1].strip() == "2."


def test_lc3_compiler_sample():
    """コンパイラLC-3の見本のブロック崩しを、コンパイルして動かす。ブロックとパドル
    (液晶RAMのミラーの27xxに書かれる)が出て、2でパドルが下がり、打ち返さなければGAME OVERになる"""
    prog = programs.find("lc3-block", "1261")
    assert prog is not None
    assert prog.setup == "EQU#43" and prog.mode == "PRO"
    assert prog.run_command == "CALL &4000\nCALL &4900"
    assert prog.blocks[0][0] == 0x4000 and prog.size == 2306
    app = make_app("1261")
    app.open_program(prog, run=True)
    while app.typer.busy:
        app.frame()
    for _ in range(30):
        app.frame()
    assert lines(app.m)[0].strip() == "LC-3 BLOCK"
    assert app.m.program_start() == 0x5600  # BASICは5600から
    app.m.held.add("5")
    for _ in range(5):
        app.frame()
    app.m.held.discard("5")
    for _ in range(30):
        app.frame()

    def rows(col):  # 列colの点いているドットの行(1行目が0〜6、2行目が7〜13)
        c = app.m.columns()
        return [b for b in range(7) if c[col] >> b & 1] + [
            7 + b for b in range(7) if c[120 + col] >> b & 1
        ]

    assert rows(90) == [0, 1, 3, 4, 6, 7, 9, 10, 12, 13]  # ブロックの左の列
    assert rows(1) == [5, 6, 7, 8]  # パドル
    app.m.held.add("2")
    for _ in range(3):
        app.frame()
    app.m.held.discard("2")
    assert rows(1)[0] > 5
    for _ in range(3000):  # パドルをボールから遠ざけておく
        ball = [y for x in range(3, 89) for y in rows(x)]
        app.m.held.discard("2")
        app.m.held.discard("8")
        if ball:
            app.m.held.add("2" if ball[0] < 7 else "8")
        app.frame()
        if "GAME OVER" in lcd_text(app.m):
            break
    assert lines(app.m)[0].startswith("GAME OVER")
    app.close()


def test_store_basic_matches_typing():
    """App.store_basicでRAMに置いたプログラムと終わりの番地が、打ち込んだときと同じになる"""
    src = (
        '10 FORT=1TO5:PRINT T;"ab c":NEXT T\n'
        "20 IF A>=B AND C<>D THEN 10:REM PRINT  TO\n"
        '30 A=1E3:B=π*√4:C$="¥ｱｲ ポ"\n'
        "5 DATA 1,TO\n"
    )
    m, t = boot()
    enter(m, t, src)
    typed = bytes(m.mem[0x4080:0x4200]), bytes(m.mem[0x66E3:0x66E5])
    app = make_app("1261")
    app.typer.add_mode("PRO")
    app.typer.add_text("NEW\n")
    app.typer.add_call(lambda: app.store_basic(src))
    while app.typer.busy:
        app.frame()
    m2 = app.m
    assert (bytes(m2.mem[0x4080:0x4200]), bytes(m2.mem[0x66E3:0x66E5])) == typed
    assert basictext.program_text(m2.mem, start=m2.program_start()).startswith("5 DATA 1,TO\n")
    app.close()


def test_lcd_ram_mirrors():
    """2100-27FFに2000-20FF、2900-2FFFに2800-28FFと同じものが見える"""
    m = PC1251(model="1261")
    m.write(0x2705, 0x55)
    m.write(0x2A47, 0x2A)
    assert m.mem[0x2005] == 0x55 and m.mem[0x2847] == 0x2A
    assert m.read(0x2105) == 0x55 and m.read(0x2F47) == 0x2A


def test_lowercase_after_poke():
    """203Cのビット7を0にすると、SHIFT+8がカナの代わりに英小文字の入力を切り替え、SMALLが
    点く(電源を入れ直すと、SHIFT+8はカナの切り替えに戻る)"""
    m, t = boot()
    typ(m, t, "POKE &203C,PEEK &203C AND &7F\n")
    t.add_keys([["SHIFT"], ["8"]])
    assert typ(m, t, "ABC").startswith("abc")
    assert "SMALL" in m.symbols() and "KANA" not in m.symbols()
    t.add_keys([["SHIFT"], ["8"]])
    typ(m, t, "\n")
    m.mode = "OFF"
    m.run(CLOCK)
    m.mode = "RUN"
    m.brk = True
    m.run(CLOCK // 5)
    m.brk = False
    m.run(CLOCK)
    t.add_keys([["SHIFT"], ["8"]])
    typ(m, t, "")
    assert "KANA" in m.symbols() and "SMALL" not in m.symbols()


# ---- # ram: でRAMの終わりを広げる ----
def test_ram_top_extends_and_shrinks():
    """RAMの終わりは、ROMや液晶RAMにかかるまで広げられ、既定に戻せる。広げた所は0で始まり、
    戻すとつながっていない番地に戻る"""
    m = PC1251(model="1261")
    assert m.ram_top_ok(0x8000) and not m.ram_top_ok(0x8001)
    assert m.ram_top_ok(0x4000) and m.ram_top_ok(None)  # 既定より下には狭めない
    m.set_ram_top(0x8000)
    assert m.model.ram == (0x4000, 0x8000) and m.read(0x7FFF) == 0
    m.write(0x7FFF, 5)
    assert m.read(0x7FFF) == 5 and m.writable(0x7FFF)
    m.set_ram_top(None)
    assert m.model.ram == (0x4000, 0x6800) and m.read(0x7FFF) == 0x7F
    m.write(0x7FFF, 5)
    assert m.read(0x7FFF) == 0x7F
    # PC-1251はF800の液晶RAMの手前まで、PC-1245はE800の液晶RAMのミラーの手前まで
    assert PC1251(model="1251").ram_top_ok(0xF800) and not PC1251(model="1251").ram_top_ok(0xF801)
    assert PC1251(model="1245").ram_top_ok(0xE800) and not PC1251(model="1245").ram_top_ok(0xE900)


def test_state_restores_ram_top():
    """状態には保存したときのRAMの終わりが入っていて、戻すとその終わりになる"""
    m = PC1251(model="1261")
    plain = m.snapshot()
    m.set_ram_top(0x8000)
    m.write(0x7000, 0x37)
    wide = m.snapshot()
    m.restore(plain)
    assert m.model.ram == (0x4000, 0x6800) and m.read(0x7000) == 0x70
    m.restore(wide)
    assert m.model.ram == (0x4000, 0x8000) and m.read(0x7000) == 0x37


def _ram_hex(tmp_path, name="wide", ram="# ram: 6800-7FFF\n"):
    d = tmp_path / "pc1261"
    d.mkdir(exist_ok=True)
    path = d / f"{name}.hex"
    path.write_text(f"# title: {name}\n{ram}# run: CALL &7000\n7000 37\n", encoding="utf-8")
    return str(path)


def test_program_ram_directive(tmp_path):
    prog = programs.load_program(_ram_hex(tmp_path))
    assert prog.ram == (0x6800, 0x8000) and prog.ram_top == 0x8000 and not prog.errors
    assert prog.runs_on("1261") and prog.runs_on("1260")
    bad = programs.load_program(_ram_hex(tmp_path, "bad", "# ram: 6800\n"))
    assert bad.errors and "# ram:" in bad.errors[0]
    # 置き場所の直下に置いたものは、広げたRAMに収まる機種で動く
    top = tmp_path / "top.hex"
    top.write_text("# ram: 6800-7FFF\n7F00 37\n", encoding="utf-8")
    assert programs.load_program(str(top)).inferred == ["1261"]  # PC-1350は7000から液晶RAM
    top.write_text("7F00 37\n", encoding="utf-8")
    assert programs.load_program(str(top)).inferred == []


def test_open_program_extends_ram_and_keeps_it(tmp_path, monkeypatch):
    """# ram: のプログラムを読み込むとRAMが広がり、終わって起動し直しても広がったまま。
    # ram: のないプログラムを読み込むと機種のRAMに戻り、読み込む前に戻すと広がる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    wide = programs.load_program(_ram_hex(tmp_path))
    app = make_app("1261", frames=3, fresh=False)
    app.open_program(wide, run=False)
    assert app.m.model.ram == (0x4000, 0x8000) and app.m.read(0x7000) == 0x37
    assert app.bench.ram == app.m.model.ram
    app.close()
    app = make_app("1261", frames=3, fresh=False)
    assert app.m.model.ram == (0x4000, 0x8000) and app.m.read(0x7000) == 0x37
    plain = programs.Program(name="plain", title="plain", basic='10 PRINT "A"\n', run="RUN")
    app.open_program(plain, run=False)
    assert app.m.model.ram == (0x4000, 0x6800) and app.m.read(0x7000) == 0x70
    app.undo_loading()
    assert app.m.model.ram == (0x4000, 0x8000) and app.m.read(0x7000) == 0x37
    # 広げられない範囲は読み込まない
    rom = programs.load_program(_ram_hex(tmp_path, "rom", "# ram: 6800-8000\n"))
    app.open_program(rom, run=False)
    assert "ROM" in app.status and app.m.model.ram == (0x4000, 0x8000)
    # 広げたRAMに書くのに# ram: のないプログラムは、RAMが戻ると外になるので読み込まない
    narrow = programs.load_program(_ram_hex(tmp_path, "narrow", ""))
    app.open_program(narrow, run=False)
    assert "7000" in app.status and app.m.model.ram == (0x4000, 0x8000)
    # 書き出しの頭と、状態に書くプログラムの情報に# ram: が残る
    assert app._ram_line() == "# ram: 6800-7FFF\n"
    back = app._saved_prog(app._prog_fields(wide))
    assert back is not None and back.ram == (0x6800, 0x8000)
    app.close()
