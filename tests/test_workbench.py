"""ROMなしのマシン語の作業欄(打ち込み、実行、1命令ずつ、止める所、貼り付け、逆アセンブル)"""

import os

import pygame
import pytest
from helpers import make_app

from sc61box import app as appmod
from sc61box import benchview, disasm, workbench
from sc61box.machine import CLOCK, RomNotFound, new_machine

VLINE = "C000 027F10F800523700 12"  # 本のダンプリストの縦線(第4章)
ev = pygame.event.Event


def bench():
    m = new_machine("1251", rom=False)
    return m, workbench.Bench(m)


def type_line(b, text):
    for ch in text:
        if ch == " ":
            b.to_data()
        elif ch == "\n":
            b.next_line()
        else:
            assert b.type_hex(int(ch, 16)) == ""


def run_until_stop(m, b, seconds=3.0):
    """App._advanceと同じ手順で、止まるまで(最長seconds秒)動かす"""
    used = 0
    while b.state == "run" and used < CLOCK * seconds:
        if b.pass_pc is not None:
            c = m.cpu.cycles
            b.pass_step()
            used += m.cpu.cycles - c
            continue
        if m.run(CLOCK // 200, b.guard()):
            b.trapped()
        used += CLOCK // 200


def test_norom_machine():
    """ROMを読まずに作った本体は、ROMの番地が0でRAMと液晶は使える"""
    m = new_machine("1251", rom=False)
    assert m.norom and not any(m.mem[0:0x2000]) and not any(m.mem[0x4000:0x8000])
    assert m.writable(0xC000) and m.writable(0xF800) and not m.writable(0x1000)


def test_type_book_line():
    """番地、Space、16字、Enterで、本のダンプリストの1行を打てる。番地を打ったあとのSpaceは
    区切りとして読み飛ばし、Enterで次の行の頭に移る"""
    m, b = bench()
    type_line(b, "C000 027F10F800523700\n")
    assert bytes(m.mem[0xC000:0xC008]) == bytes.fromhex("027F10F800523700")
    assert workbench.checksum(b.row_bytes(0xC000)) == 0x12
    assert (b.row, b.col, b.field) == (0xC008, 0, "data") and b.start == 0xC000
    type_line(b, "0102030405060708")
    assert b.col == 8 and b.type_hex(1) != ""  # 行の終わりではそれ以上打てない
    assert bytes(m.mem[0xC008:0xC010]) == bytes(range(1, 9))


def test_cursor_moves_between_fields():
    """番地の4桁目の右はバイトの欄。←→は行の端で前と次の行へ回る(番地の欄へはTabかHome)"""
    _m, b = bench()
    b.to_addr()
    b.right()
    b.right()
    b.right()
    b.right()  # 番地の4桁目の右はバイトの欄
    assert (b.row, b.field, b.col, b.nib) == (0xC000, "data", 0, 0)
    b.left()  # 行の最初のバイトの左は、前の行の最後のバイトの下の桁
    assert (b.row, b.field, b.col, b.nib) == (0xBFF8, "data", 7, 1)
    b.right()  # 行の最後のバイトの下の桁の右は、次の行の最初のバイト
    assert (b.row, b.col, b.nib) == (0xC000, 0, 0)
    b.row_end()  # 行の終わり(最後のバイトの後ろ)から
    b.right()
    assert (b.row, b.col, b.nib) == (0xC008, 0, 0)
    b.row_end()
    b.left()
    assert (b.row, b.col, b.nib) == (0xC008, 7, 1)
    b.to_addr()
    b.left()
    assert (b.row, b.field, b.nib) == (0xC008, "addr", 0)  # 番地の欄の中では回らない


def test_run_vline():
    """実行すると液晶を消して表示をつけ、RTNで戻ると編集に戻る。かかったサイクルを出す"""
    m, b = bench()
    type_line(b, "C000 027F10F800523700")
    m.mem[0xF810] = 0x55
    b.run()
    run_until_stop(m, b)
    assert b.state == "edit" and "RTN" in b.reason and "18サイクル" in b.reason
    assert m.columns()[0] == 0x7F and m.mem[0xF810] == 0 and m.display_on()
    assert 0xF800 in b.changed


def test_step_and_finish():
    """編集中に1命令を押すと、開始番地の最初の命令の前で止まる。1命令ずつ進んでRTNで終わる"""
    m, b = bench()
    type_line(b, "C000 027F10F800523700")
    b.step()
    assert b.state == "pause" and m.cpu.pc == 0xC000
    pcs = []
    while b.state == "pause":
        b.step()
        pcs.append(m.cpu.pc)
    assert pcs == [0xC002, 0xC005, 0xC006, 0]
    assert b.state == "edit" and m.cpu.ram[2] == 0x7F  # A


def test_breakpoint_and_resume():
    """止める所で止まり、続けるとその命令から実行する"""
    m, b = bench()
    # C000 LIB 3 / C002 DECB / C003 JRNZM C002 / C005 RTN
    type_line(b, "C000 0303C3290237")
    b.toggle_break(0xC002)
    b.run()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0xC002 and m.cpu.ram[3] == 3
    b.resume()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0xC002 and m.cpu.ram[3] == 2
    b.breaks.clear()
    b.resume()
    run_until_stop(m, b)
    assert b.state == "edit" and m.cpu.ram[3] == 0


def test_step_over_call():
    """呼び出しを飛び越すと、呼んだ先を実行して次の命令で止まる"""
    m, b = bench()
    # C000 CALL C010 / C003 RTN ... C010 LIA 5 / C012 RTN
    type_line(b, "C000 78C01037\n")
    b.to_addr()  # 番地を打ち直す(Tab)
    type_line(b, "C010 020537")
    b.start = 0xC000
    b.step()
    b.step_over()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0xC003 and m.cpu.ram[2] == 5
    assert "戻りました" in b.reason


def test_jump_to_rom_stops():
    """まねていないROMのルーチンを呼ぶと、呼んだところで止まって名前を出す"""
    m, b = bench()
    type_line(b, "C000 EB5037")  # CAL 0B50(数の足し算)
    b.run()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0x0B50
    assert "FADD" in b.reason and "ROMなしでは使えません" in b.reason


def test_endless_loop_can_be_paused():
    m, b = bench()
    type_line(b, "C000 2D01")  # JR C000(自分へ)
    b.run()
    run_until_stop(m, b, 0.2)
    assert b.state == "run"
    b.pause()
    assert b.state == "pause" and m.cpu.pc in (0xC000, 0xC001)
    b.abandon()
    assert b.state == "edit"


def test_paste_book_lines_and_checksums():
    """本のダンプリスト(続きの行は番地なし)を貼り付けると書き、チェックサムを確かめる"""
    m, b = bench()
    text = "C000 10F8000305027F52 E3\n00004EFF41290402 BD\n005200004EFF4129 00\n"
    res = b.paste(text)
    assert res.written == 24 and res.first == 0xC000
    assert bytes(m.mem[0xC008:0xC010]) == bytes.fromhex("00004EFF41290402")
    assert res.bad_sums == [0xC010]  # 3行目は正しくは09
    res = b.paste("; 注釈\nC100 02 7F 37   ; LIA 7F\n# title: x\n")
    assert res.written == 3 and bytes(m.mem[0xC100:0xC103]) == bytes.fromhex("027F37")
    assert b.start == 0xC100


def test_disasm():
    mem = bytearray(0x10000)
    code = bytes.fromhex("027F10F800523729047AC0C0108A E044 2D01".replace(" ", ""))
    mem[0xC000 : 0xC000 + len(code)] = code

    def rd(a):
        return mem[a]

    out = []
    a = 0xC000
    for _ in range(9):
        ins = disasm.decode(rd, a)
        out.append((ins.addr, ins.text()))
        a += ins.size
    assert out == [
        (0xC000, "LIA 7F"),
        (0xC002, "LIDP F800"),
        (0xC005, "STD"),
        (0xC006, "RTN"),
        (0xC007, "JRNZ C004"),
        (0xC009, "PTC C0,C010"),
        (0xC00D, "LP 0A"),
        (0xC00E, "CAL 0044"),
        (0xC010, "JR C010"),
    ]
    assert disasm.is_call(rd, 0xC00E) and not disasm.is_call(rd, 0xC000)


def test_dump_text_reloads():
    """書き出した.hexは、エミュレータの16進ダンプとして読み直せる"""
    from sc61box import programs

    m, b = bench()
    type_line(b, "C000 027F10F800523700")
    end = b.used_end(0xC000)
    assert end == 0xC007
    text = b.dump_text(0xC000, end)
    assert "LIDP F800" in text
    blocks, errors = programs.parse_hex(text)
    assert not errors and b"".join(d for _a, d in blocks) == bytes(m.mem[0xC000:0xC007])


def _key(app, key, uni="", mod=0):
    app.handle(ev(pygame.KEYDOWN, key=key, unicode=uni, mod=mod, scancode=0))
    app.handle(ev(pygame.KEYUP, key=key, unicode=uni, mod=mod, scancode=0))


def _type(app, text):
    for ch in text:
        if ch == " ":
            _key(app, pygame.K_SPACE, " ")
        elif ch == "\n":
            _key(app, pygame.K_RETURN, "\r")
        else:
            _key(app, ord(ch.lower()), ch)


def test_app_without_rom(monkeypatch):
    """ROMのファイルがなければ、ROMなしで起動して右に作業欄を出す。打ったキーは作業欄へ行き、
    ⌘G(Ctrl+G)で実行する"""
    real = appmod.new_machine

    def no_rom(model="1251", card=0, overseas=False, rom=True):
        if rom:
            raise RomNotFound("ROMがない")
        return real(model, rom=False)

    monkeypatch.setattr(appmod, "new_machine", no_rom)
    app = make_app(scale=0.5, frames=3)
    assert app.bench is not None and app.m.norom
    assert app.window.get_width() == app.body_size[0] + benchview.PANE_W
    _type(app, "C000 027F10F800523700\n")
    assert bytes(app.m.mem[0xC000:0xC008]) == bytes.fromhex("027F10F800523700")
    assert not app.m.held  # 本体のキーは押していない
    _key(app, pygame.K_g, "g", pygame.KMOD_CTRL)
    for _ in range(3):
        app.frame()
    assert app.bench.state == "edit" and "RTN" in app.bench.reason
    assert app.m.columns()[0] == 0x7F
    # 作業欄のボタン(1命令)を押す
    app.frame()
    view = app.bench_view
    assert view is not None
    btn = next(b for b in view.buttons if b.action == "step")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=btn.rect.center))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=btn.rect.center))
    assert app.bench.state == "pause" and app.m.cpu.pc == 0xC000
    _key(app, pygame.K_ESCAPE)
    assert app.bench.state == "edit"
    app.close()


def test_app_open_hex_program(tmp_path, monkeypatch):
    """ROMなしでプログラムを読み込むと、マシン語だけを書き、呼び出し用のBASICの最後のCALLを
    開始番地にする"""
    from sc61box import programs

    (tmp_path / "two.hex").write_text("C200 37\nC000 027F10F80052 37\n", encoding="utf-8")
    (tmp_path / "two.bas").write_text("10 CALL &C200:CALL &C000\n20 GOTO 20\n", encoding="utf-8")
    app = make_app(scale=0.5, frames=2, norom=True)
    assert app.bench is not None
    app.open_program(programs.load_program(str(tmp_path / "two.bas")), run=True)
    assert app.bench.start == 0xC000 and app.m.mem[0xC200] == 0x37
    for _ in range(3):
        app.frame()
    assert app.bench.state == "edit" and app.m.columns()[0] == 0x7F
    app.close()


def test_norom_font_at_rom_addresses():
    """ROMなしの本体には、ROMと同じ番地と並びで、1から描いた文字の形を置く(本の見本の
    電光掲示板などがROMの表を読むため)"""
    from sc61box import norom

    m, _b = bench()
    assert bytes(m.mem[0x43C4 + 5 * 0x51 :][:5]) == norom.glyph("A") != bytes(5)
    assert bytes(m.mem[0x4414 + 5 * 0x17 :][:5]) == norom.glyph("¥")


def test_norom_routines():
    """ROMのキーを読むルーチン(1F44)と文字の形の番地のルーチン(1FBC)は、エミュレータが
    働きをまねて、呼んだ所へ戻す"""
    m, b = bench()
    # C000 LIA 51h / C002 CAL 1FBC / C004 CAL 1F44 / C006 RTN
    type_line(b, "C000 0251FFBCFF4437")
    m.held.add("7")
    b.run()
    run_until_stop(m, b)
    assert b.state == "edit"
    x = m.cpu.ram[4] | m.cpu.ram[5] << 8
    assert x == 0x43C4 + 5 * 0x51 - 1
    assert m.cpu.ram[2] == 0x47 and m.cpu.c == 1  # 7の本体の文字コード
    m.held.clear()
    b.run()
    run_until_stop(m, b)
    assert m.cpu.c == 0


def test_basic_hints():
    """呼び出し用のBASICからは、数だけを書くPOKEと最後のCALLの番地を拾う。IFのあとは拾わない"""
    text = (
        '10 D=2:INPUT "1:EASY 2:NORMAL ? ";D\n'
        "20 POKE &C200,&02,1,&37:POKE &C5DF,0:IF D=1 POKE &C5DF,1\n"
        "30 CALL &C200:CALL &C000\n"
        "40 POKE &C300,D\n"
    )
    pokes, start = workbench.basic_hints(text)
    assert pokes == [(0xC200, bytes([2, 1, 0x37])), (0xC5DF, b"\x00")]
    assert start == 0xC000


def test_norom_ok():
    from sc61box import programs

    hexed = programs.Program("a", blocks=[(0xC000, b"\x37")])
    assert hexed.norom_ok
    assert not programs.Program("b", basic="10 PRINT 1\n").norom_ok
    assert not programs.Program("c", blocks=[(0xC000, b"\x37")], norom="off").norom_ok


BUNDLED = os.path.join(os.path.dirname(__file__), "..", "programs")


@pytest.mark.parametrize(
    ("model", "name"),
    [("1251", "pc1251/ball"), ("1251", "pc1251/break"), ("1251", "pc1251/scroll"),
     ("1245", "pc1245/break"), ("1261", "pc1261/ball")],
)  # fmt: skip
def test_bundled_programs_without_rom(model, name):
    """同梱の弾むボール、ブロック崩し、文字を流す見本は、ROMなしでも遊べて、BRKで戻る"""
    from sc61box import programs

    prog = programs.load_program(os.path.join(BUNDLED, name + ".bas"))
    assert prog.norom_ok
    m = new_machine(model, rom=False)
    b = workbench.Bench(m)
    pokes, start = workbench.basic_hints(prog.basic)
    b.load_blocks(prog.blocks + pokes, start)
    b.run()
    used = 0
    while b.state == "run" and used < CLOCK * 4:
        m.brk = CLOCK * 2 <= used < CLOCK * 2.5
        if m.run(CLOCK // 200, b.guard()):
            b.trapped()
        used += CLOCK // 200
    assert b.state == "edit" and "RTN" in b.reason
    assert any(m.columns())
    if name.endswith("break"):
        assert m.mem[0xC5DF] == 1  # ROMなしでは難しさを聞けないので、EASYで始める


def test_moves_home_end_page():
    """Home・Endで行の頭と終わり、PageUp・PageDownで1画面、終わりへは書いた所の後ろへ"""
    m, b = bench()
    type_line(b, "C000 0102030405060708\n")
    type_line(b, "090A0B")
    b.row_home()
    assert (b.row, b.col, b.field) == (0xC008, 0, "data")
    b.row_home()
    assert b.field == "addr"
    b.row_end()
    assert (b.field, b.col) == ("data", 8)
    b.page(1, 8)
    assert b.row == 0xC048
    b.page(-2, 8)
    assert b.row == 0xBFC8
    b.go_end(8)
    assert (b.row, b.col) == (0xC008, 3)  # C00Aの後ろ
    b.go(b.start, 8)
    assert (b.row, b.col) == (0xC000, 0)


def test_key_repeat_only_while_editing(monkeypatch):
    """作業欄に打っているあいだだけ、押し続けたカーソルのキーをリピートする。1フレームに
    1回まで動かし、離せばすぐ止まる。実行中は本体にキーをそのまま送り、リピートしない"""
    from sc61box import app as appmod

    now = [100.0]
    monkeypatch.setattr(appmod.time, "monotonic", lambda: now[0])
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert pygame.key.get_repeat() == (0, 0)  # pygameのリピートは使わない
    _type(app, "C000 2D01")  # JR C000(自分へ)
    b.go(0xC000)
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_DOWN, unicode="", mod=0, scancode=0))
    assert b.row == 0xC008
    now[0] += 0.3
    app.frame()
    assert b.row == 0xC008  # まだ始まらない
    now[0] += 0.5  # フレームが遅れても、1フレームに1回だけ
    app.frame()
    assert b.row == 0xC010
    now[0] += 0.06
    app.frame()
    assert b.row == 0xC018
    app.handle(ev(pygame.KEYUP, key=pygame.K_DOWN, unicode="", mod=0, scancode=0))
    now[0] += 1.0
    app.frame()
    assert b.row == 0xC018  # 離せばすぐ止まる
    _type(app, "1")  # 16進表記の字はリピートしない
    assert app.held_key is None
    b.go(0xC000)
    _key(app, pygame.K_g, "g", pygame.KMOD_CTRL)
    app.frame()
    assert b.state == "run"
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_DOWN, unicode="", mod=0, scancode=0))
    now[0] += 1.0
    app.frame()
    assert app.held_key is None and b.row == 0xC000  # 実行中は作業欄に届かない
    app.handle(ev(pygame.KEYUP, key=pygame.K_DOWN, unicode="", mod=0, scancode=0))
    _key(app, pygame.K_PERIOD, ".", pygame.KMOD_CTRL)
    app.frame()
    _key(app, pygame.K_UP, "", pygame.KMOD_CTRL)  # ⌘↑で開始番地へ
    assert b.row == 0xC000
    app.close()


def test_dump_follows_pc_and_disasm_follows_cursor():
    """一時停止するたびにダンプのカーソルがPCの命令に移り、カーソルを動かせば逆アセンブルが
    ついていく。逆アセンブルの行を押しても、ダンプの行の並び(開始番地から8バイトずつ)は
    変わらない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    _type(app, "C000 0201020203020402\n05020602070208")  # LIA 1 / LIA 2 / ... / LIA 8
    b.start = 0xC000
    _key(app, pygame.K_j, "j", pygame.KMOD_CTRL)  # 開始番地の前で止まる
    for _ in range(5):
        _key(app, pygame.K_j, "j", pygame.KMOD_CTRL)
        app.frame()
        assert b.cursor == app.m.cpu.pc
        first = (b.row - 8 * b.top_rows) & 0xFFFF
        assert (first - 0xC000) % 8 == 0
    _key(app, pygame.K_UP)
    app.frame()
    assert b.cursor == app.m.cpu.pc - 8
    assert b.ins_at(b.cursor) == b.cursor - (b.cursor - 0xC000) % 2
    hit = next(h for h in v.hits if h[1] == "goto" and h[2] == 0xC004)
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=hit[0].center))
    assert b.cursor == 0xC004 and b.row == 0xC000
    app.close()


def _hex_lines(addr, data):
    """dataを8バイトずつ、番地つきのダンプの行にする"""
    return "".join(
        f"{addr + i:04X} {data[i : i + 8].hex().upper()}\n" for i in range(0, len(data), 8)
    )


# C000でC020へ飛び、あいだの29バイトは0、C020に縦線を描いて戻る(39バイト)
JUMP_OVER_ZEROS = bytes.fromhex("79C020") + bytes(29) + bytes.fromhex("027F10F8005237")


def test_export_keeps_code_after_zeros(tmp_path, monkeypatch):
    """書き出しは、作業欄で書いた範囲を0のバイトも含めて保存する(0が続いても、その先の
    コードを落とさない)。離れた番地に書いたものは別の行のまとまりにする"""
    from sc61box import programs

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert b is not None
    b.paste(_hex_lines(0xC000, JUMP_OVER_ZEROS) + "C300 37\n")
    b.start = 0xC000
    assert b.export_ranges() == [(0xC000, 0xC027), (0xC300, 0xC301)]
    app.bench_export()
    path = next(tmp_path.rglob("dump-*.hex"))
    blocks, errors = programs.parse_hex(path.read_text(encoding="utf-8"))
    assert not errors
    got = {a + i: v for a, data in blocks for i, v in enumerate(data)}
    assert bytes(got[0xC000 + i] for i in range(len(JUMP_OVER_ZEROS))) == JUMP_OVER_ZEROS
    assert got[0xC300] == 0x37
    app.close()


def test_menu_paste_and_export_use_bench(tmp_path, monkeypatch):
    """ROMなしでは、メニューの貼り付けと書き出しも⌘V・⌘Eと同じく作業欄のダンプを扱う"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True)
    monkeypatch.setattr(app, "clipboard", lambda: "C000 027F10F8005237")
    actions = {it.label: it.action for it in app.popup_items("program") if it.action}
    actions["クリップボードからダンプを貼り付ける"]()
    assert bytes(app.m.mem[0xC000:0xC007]) == bytes.fromhex("027F10F8005237")
    assert not app.typer.busy  # 本体のキーとして打っていない
    actions["ダンプをファイル(.hex)に書き出す"]()
    assert list(tmp_path.rglob("dump-*.hex"))
    app.close()


def test_pause_shortcut_controls_bench():
    """ROMなしでは、⌘Pと右クリックの一時停止も作業欄の一時停止と続けるになる(止めた状態は
    1つだけで、作業欄の「続ける」でそのまま動き出す)"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert b is not None
    b.paste("C000 2D01")  # JR C000(自分へ)
    app.bench_do("run")
    app.frame()
    _key(app, pygame.K_p, "p", pygame.KMOD_CTRL)
    assert b.state == "pause" and not app.halted
    pause = next(
        it for it in app.popup_items("context") if getattr(it, "label", "").startswith("実行を")
    )
    assert pause.label == "実行を再開する"
    app.bench_do("go")
    c = app.m.cpu.cycles
    app.frame()
    assert b.state == "run" and app.m.cpu.cycles > c
    app.toggle_halt()
    assert b.state == "pause"
    app.toggle_halt()
    assert b.state == "run"
    app.close()


def test_state_restores_bench(tmp_path, monkeypatch):
    """どこでもセーブに作業欄の開始番地と実行の状態も書く。実行中に保存したものは、保存した
    ときのPCで一時停止した状態に戻り、「続ける」で続きから動く"""
    app = make_app(scale=0.5, frames=2, norom=True)
    monkeypatch.setattr(app, "state_file", str(tmp_path / "state.json"))
    b = app.bench
    assert b is not None
    b.paste("C100 2D01")
    app.bench_do("run")
    app.frame()
    pc = app.m.cpu.pc
    app.save_state()
    app.bench_do("abandon")
    b.paste("C200 37")
    assert b.start == 0xC200
    app.load_state()
    assert b.start == 0xC100 and b.state == "pause" and app.m.cpu.pc == pc
    assert f"{pc:04X}" in b.reason
    app.bench_do("go")
    c = app.m.cpu.cycles
    app.frame()
    assert b.state == "run" and app.m.cpu.cycles > c and app.m.cpu.pc in (0xC100, 0xC101)
    app.close()


def test_restart_keeps_written_ranges(tmp_path, monkeypatch):
    """ROMなしで終了して起動し直しても、書いた範囲と開始番地はRAMと一緒に残り、書き出しで
    0が続いた先のコードを落とさない。範囲を保存していない前の版のRAMでは、0でない所を
    すべて書き出す"""
    monkeypatch.setattr(appmod, "STATE_DIR", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True, fresh=False)
    b = app.bench
    assert b is not None
    b.paste(_hex_lines(0xC000, JUMP_OVER_ZEROS))
    b.paste("C300 37")
    b.start = 0xC000
    app.close()
    app = make_app(scale=0.5, frames=2, norom=True, fresh=False)
    b = app.bench
    assert b is not None and b.start == 0xC000 and b.state == "edit"
    assert b.export_ranges() == [(0xC000, 0xC027), (0xC300, 0xC301)]
    app.close()
    os.remove(appmod.bench_file(appmod.ram_file("1251", norom=True)))
    app = make_app(scale=0.5, frames=2, norom=True, fresh=False)
    assert app.bench is not None
    assert app.bench.export_ranges() == [(0xC000, 0xC027), (0xC300, 0xC301)]
    app.close()


def test_undo_loading_resumes_running_program(tmp_path):
    """実行中に別のプログラムを読み込んでから「読み込む前に戻す」と、そのときのPCで一時停止
    した状態に戻り、「続ける」で続きから動く"""
    from sc61box import programs

    (tmp_path / "other.hex").write_text("C200 37\n", encoding="utf-8")
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert b is not None
    b.paste("C100 2D01")
    app.bench_do("run")
    app.frame()
    pc = app.m.cpu.pc
    app.open_program(programs.load_program(str(tmp_path / "other.hex")))
    assert b.start == 0xC200 and b.state == "edit"
    app.undo_loading()
    assert b.start == 0xC100 and b.state == "pause" and app.m.cpu.pc == pc
    app.bench_do("go")
    c = app.m.cpu.cycles
    app.frame()
    assert b.state == "run" and app.m.cpu.cycles > c and app.m.cpu.pc in (0xC100, 0xC101)
    app.close()


def test_export_keeps_start_address(tmp_path, monkeypatch):
    """書き出した.hexには開始番地を# run:で書き、読み直すと同じ番地から動く(開始番地より
    前にデータがあっても)"""
    from sc61box import programs

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert b is not None
    b.paste("C000 37\nC100 027F10F8005237")
    b.start = 0xC100
    app.bench_export()
    app.close()
    path = next(tmp_path.rglob("dump-*.hex"))
    assert "# run: CALL &C100" in path.read_text(encoding="utf-8")
    app = make_app(scale=0.5, frames=2, norom=True)
    assert app.bench is not None
    app.open_program(programs.load_program(str(path)), run=True)
    assert app.bench.start == 0xC100
    for _ in range(3):
        app.frame()
    assert app.bench.state == "edit" and app.m.columns()[0] == 0x7F
    app.close()


@pytest.mark.parametrize("routine", ["FF44", "FFBC"])
def test_step_over_rom_routine(routine):
    """ROMのルーチンの代わり(CAL 1F44・CAL 1FBC)も、「CALLごと」で戻り先の命令の前で止まる
    (戻り先の命令はまだ実行しない)"""
    m, b = bench()
    b.paste(f"C000 {routine}026337")  # CAL / LIA 63 / RTN
    b.start = 0xC000
    b.step()
    b.step_over()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0xC002 and m.cpu.ram[2] != 0x63
    assert "戻りました" in b.reason


def test_rom_routine_advances_timer():
    """ROMのルーチンの代わりにかかったことにするサイクルも、タイマ(2ms・512ms)を進める"""
    from sc61box.machine import TICK_2MS

    m, b = bench()
    b.paste("C000 FF44FF44FF44FF4437")  # CAL 1F44を4回 / RTN
    b.start = 0xC000
    b.run()
    c0 = m.cpu.cycles
    t0 = m.t512cnt * TICK_2MS + m.t2
    run_until_stop(m, b)
    assert b.state == "edit"
    assert m.t512cnt * TICK_2MS + m.t2 - t0 == m.cpu.cycles - c0


def test_step_does_not_run_missing_rom():
    """ROMなしで使えないROMの番地で止まったあと、「1命令」や「CALLごと」を押しても、
    そこの命令(ROMの代わりの0)は実行せず、レジスタもPCも変えない"""
    m, b = bench()
    b.paste("C000 0007EB5037")  # LII 07 / CAL 0B50 / RTN
    b.start = 0xC000
    b.run()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0x0B50 and m.cpu.ram[0] == 7
    why = b.reason
    for act in (b.step, b.step_over):
        act()
        assert b.state == "pause" and m.cpu.pc == 0x0B50 and m.cpu.ram[0] == 7
        assert b.reason == why
    b.resume()  # 続けても、同じ所でまた止まる
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0x0B50 and m.cpu.ram[0] == 7


def test_step_over_recursive_call():
    """再帰の呼び出しを「CALLごと」で飛び越すと、内側の呼び出しが同じ戻り先へ戻っても止まらず、
    押したCALLが戻ってきたところで止まる"""
    m, b = bench()
    # C000 LIA 3 / CALL C010 / RTN
    # C010 DECA / JRZ C018(RTNへ) / CALL C010 / INCB / RTN
    b.paste("C000 020378C01037\nC010 437EC01878C010C237")
    b.start = 0xC000
    b.step()
    while m.cpu.pc != 0xC014:  # 1回目の呼び出しの中の、再帰のCALLの前まで
        b.step()
    r = m.cpu.r
    assert (m.cpu.ram[2], m.cpu.ram[3]) == (2, 0)
    b.step_over()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0xC017 and m.cpu.r == r
    assert m.cpu.ram[3] == 1  # 内側のINCBは済み、外側のINCBはまだ
    assert "戻りました" in b.reason


def test_step_over_recursive_stops_at_break():
    """再帰の呼び出しを飛び越している途中でも、戻り先に置いた止める所では止まる"""
    m, b = bench()
    b.paste("C000 020378C01037\nC010 437EC01878C010C237")
    b.start = 0xC000
    b.step()
    while m.cpu.pc != 0xC014:
        b.step()
    b.toggle_break(0xC017)
    b.step_over()
    run_until_stop(m, b)
    assert b.state == "pause" and m.cpu.pc == 0xC017 and "止める所" in b.reason
    assert m.cpu.ram[3] == 0  # 内側の戻りで、INCBの前に止まっている


def test_step_over_recursive_return_loops():
    """再帰の内側の戻り先で終わらないループになっても、フレームごとに画面へ戻り、一時停止
    できる(戻り先を通り過ぎるたびに、呼び出しを入れ子にしない)"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, m = app.bench, app.m
    assert b is not None
    # C017でJR C017を繰り返す(内側から戻ったあと、そこから先へ進まない)
    b.paste("C000 020378C01037\nC010 437EC01978C0102D0137")
    b.start = 0xC000
    b.step()
    while m.cpu.pc != 0xC014:
        b.step()
    app.bench_do("over")
    for _ in range(5):
        app.frame()
    assert b.state == "run" and m.cpu.pc in (0xC017, 0xC018)
    app.bench_do("pause")
    assert b.state == "pause"
    app.close()


@pytest.mark.parametrize("act", ["step", "over", "resume"])
@pytest.mark.parametrize("brk", [False, True])
def test_unsupported_rom_never_runs(act, brk):
    """ROMなしで使えないROMの番地で止まったあと、止める所の有無にかかわらず、「1命令」
    「CALLごと」「続ける」のどれでもROMの番地の命令(0)を実行しない。止める所も置けない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, m = app.bench, app.m
    assert b is not None
    b.paste("C000 0007EB5037")  # LII 07 / CAL 0B50 / RTN
    b.start = 0xC000
    app.bench_do("run")
    app.frame()
    assert b.state == "pause" and m.cpu.pc == 0x0B50
    if brk:
        assert b.toggle_break(0x0B50) is None and 0x0B50 not in b.breaks
        b.breaks.add(0x0B50)  # 前の版で置いた止める所が残っていても
    app.bench_do(act)
    for _ in range(3):
        app.frame()
    assert b.state == "pause" and m.cpu.pc == 0x0B50 and m.cpu.ram[0] == 7
    assert app.bench_view is not None
    assert [btn.action for btn in app.bench_view.button_specs()] == ["abandon"]
    app.close()


@pytest.mark.parametrize("act", ["step", "over", "resume"])
@pytest.mark.parametrize("brk", [False, True])
def test_ram_call_paths(act, brk):
    """RAMの中では、止める所の有無にかかわらず、「1命令」「CALLごと」「続ける」が動く"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, m = app.bench, app.m
    assert b is not None
    b.paste("C000 78C01037\nC010 020537")  # CALL C010 / RTN、C010 LIA 5 / RTN
    b.start = 0xC000
    if brk:
        b.toggle_break(0xC000)
    app.bench_do("step")
    assert b.state == "pause" and m.cpu.pc == 0xC000
    app.bench_do(act)
    for _ in range(3):
        app.frame()
    want = {"step": (0xC010, "pause"), "over": (0xC003, "pause"), "resume": (None, "edit")}
    pc, state = want[act]
    assert b.state == state and (pc is None or m.cpu.pc == pc)
    if act != "step":
        assert m.cpu.ram[2] == 5
    app.close()


def test_internal_ram_folds(tmp_path, monkeypatch):
    """内部RAMの見出しをクリックすると行を閉じ、作業欄が低くなる。開いた・閉じたは次に
    起動したときも同じ。覚えたものがなければ開いておく"""
    monkeypatch.setattr(appmod, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [(1920, 1080)])
    app = make_app(scale=0.5, frames=2, norom=True)
    v = app.bench_view
    assert v is not None and v.show_iram
    tall = app.window.get_height()
    rect = next(r for r, kind, _a in v.hits if kind == "iram")
    pos = rect.center  # hitsの場所は窓の座標
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=pos))
    assert not v.show_iram and v.min_height() < v.min_height(True)
    app.frame()
    assert app.window.get_height() <= tall
    assert not any(kind == "iram" and r.bottom > rect.bottom + 20 for r, kind, _a in v.hits)
    app.close()
    app = make_app(scale=0.5, frames=2, norom=True)
    assert app.bench_view is not None and not app.bench_view.show_iram
    app.close()


def test_internal_ram_folded_on_small_screen(tmp_path, monkeypatch):
    """覚えたものがなく、開いた作業欄が画面の高さに入らなければ、内部RAMは閉じておく"""
    monkeypatch.setattr(appmod, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [(1280, 720)])
    app = make_app(scale=0.5, frames=2, norom=True)
    assert app.bench_view is not None and not app.bench_view.show_iram
    app.close()


def test_undo_typing_byte_by_byte():
    """打ち込みは1バイト(2桁)ずつ取り消せ、やり直せる。取り消すとカーソルも戻り、
    書いた印(書き出す範囲)も消える"""
    m, b = bench()
    type_line(b, "C000 0102")
    assert bytes(m.mem[0xC000:0xC002]) == b"\x01\x02"
    assert b.undo() == "C001番地の打ち込みを取り消しました"
    assert bytes(m.mem[0xC000:0xC002]) == b"\x01\x00"
    assert (b.cursor, b.nib, b.field) == (0xC001, 0, "data")
    assert b.redo() == "C001番地の打ち込みをやり直しました"
    assert m.mem[0xC001] == 2 and b.cursor == 0xC002
    b.undo()
    b.undo()
    assert m.mem[0xC000] == 0 and b.export_ranges() == []
    assert b.undo() == "取り消せる書き込みはありません"


def test_undo_half_typed_byte_and_new_edit_clears_redo():
    """上の桁だけ打ったバイトも取り消せる。取り消したあとに打つと、やり直しは消える"""
    m, b = bench()
    type_line(b, "C000 4")
    assert m.mem[0xC000] == 0x40
    b.undo()
    assert m.mem[0xC000] == 0 and b.nib == 0
    type_line(b, "55")
    assert b.redo() == "やり直せる書き込みはありません"
    assert m.mem[0xC000] == 0x55


def test_undo_paste_restores_bytes_and_start():
    """貼り付けは1回分まとめて取り消し、開始番地も貼り付ける前に戻る"""
    m, b = bench()
    type_line(b, "C100 99")
    b.start = 0xC000
    res = b.paste("C0FE 1122334455")
    assert res.written == 5 and b.start == 0xC0FE and m.mem[0xC100] == 0x33
    assert b.undo() == "貼り付け(5バイト)を取り消しました"
    assert bytes(m.mem[0xC0FE:0xC103]) == bytes.fromhex("0000990000")
    assert b.start == 0xC000
    b.redo()
    assert m.mem[0xC100] == 0x33 and b.start == 0xC0FE


def test_undo_keeps_running_code_alone():
    """実行中(ROMなし)は取り消せない。読み込んだダンプの前の書き込みは取り消せなくなる"""
    m, b = bench()
    b.paste("C000 2D01")  # JR C000(自分へ)
    b.run()
    assert b.undo() == "実行中は取り消せません"
    b.abandon()
    b.load_blocks([(0xC200, b"\x37")])
    assert b.undo() == "取り消せる書き込みはありません"


def test_undo_shortcut_and_menu():
    """⌘Z(Ctrl+Z)で取り消し、⇧⌘Zでやり直す。プログラムのメニューにも同じ項目がある"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert b is not None
    _type(app, "C000 AB")
    assert app.m.mem[0xC000] == 0xAB
    _key(app, pygame.K_z, "z", pygame.KMOD_CTRL)
    assert app.m.mem[0xC000] == 0
    _key(app, pygame.K_z, "z", pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
    assert app.m.mem[0xC000] == 0xAB
    items = {it.label: it for it in app.popup_items("program") if it.action}
    assert items["ダンプの書き込みを取り消す"].note == "C000番地をABから00に戻す"
    undo = items["ダンプの書き込みを取り消す"].action
    assert undo is not None
    undo()
    assert app.m.mem[0xC000] == 0
    app.close()


def test_undo_paste_through_ram_mirror():
    """同じRAMを指すミラーの番地(PC-1251のB000〜B7FFはB800〜BFFF)を1回で貼り付けても、
    取り消すと貼り付ける前の値と書いた印に戻る"""
    m, b = bench()
    b.paste("B800 11\nB000 22\n")
    assert m.read(0xB800) == 0x22
    b.undo()
    assert m.read(0xB800) == 0 and m.read(0xB000) == 0
    assert not b.written[0xB800] and b.export_ranges() == []
    b.redo()
    assert m.read(0xB800) == 0x22 and b.written[0xB800]


def test_undo_disabled_states():
    """取り消せないときは、メニューの項目と作業欄のボタンを押せない状態にし、理由を出す。
    取り消せたことの知らせは警告の色にしない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None

    def menu():
        return {it.label: it for it in app.popup_items("program") if it.action}

    undo = menu()["ダンプの書き込みを取り消す"]
    assert not undo.enabled and undo.note == "取り消せる書き込みはありません"
    app.frame()
    btn = next(x for x in v.buttons if x.action == "undo")
    assert not btn.enabled
    _type(app, "C000 2D01")  # JR C000(自分へ)
    app.frame()
    assert next(x for x in v.buttons if x.action == "undo").enabled
    app.bench_do("run")
    app.frame()
    assert not menu()["ダンプの書き込みを取り消す"].enabled
    assert menu()["ダンプの書き込みを取り消す"].note == "実行中は取り消せません"
    app.bench_do("pause")
    app.bench_do("abandon")
    app.bench_undo()
    assert v.flash_ok and app.m.mem[0xC001] == 0
    b.undos.clear()
    app.bench_undo()
    assert not v.flash_ok
    app.close()


def test_undo_button_in_pane():
    """作業欄の取り消すボタンを押すと、1バイトの打ち込みを取り消す"""
    app = make_app(scale=0.5, frames=2, norom=True)
    v = app.bench_view
    assert v is not None
    _type(app, "C000 AB")
    app.frame()
    btn = next(x for x in v.buttons if x.action == "undo")
    assert btn.tip.startswith("C000番地をABから00に戻す")
    app.bench_click(btn.rect.center)
    assert app.m.mem[0xC000] == 0
    app.close()


def test_undo_notes_read_naturally_and_dump_stays():
    """取り消しの説明は、1バイトなら値の変化、ほかは「貼り付け(2バイト)を取り消す」の形。
    書き出す範囲がなくなっても、ダンプの位置は変わらない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    b.paste("C000 0102")
    assert b.undo_note() == ("貼り付け(2バイト)を取り消す", True)
    v._ranges = ([], 0.0)
    app.frame()
    top = next(r for r, kind, a in v.hits if kind == "addr").y
    b.undo()
    assert b.undo_note(redo=True) == ("貼り付け(2バイト)をやり直す", True)
    v._ranges = ([], 0.0)
    app.frame()
    assert next(r for r, kind, a in v.hits if kind == "addr").y == top
    app.close()


def test_start_follows_first_address_only():
    """開始番地は、まだ決めていなければ最初に打った番地になる。書き始めたあとに番地を
    打っても、カーソルが動くだけで開始番地は変わらない"""
    m, b = bench()
    assert b.start == 0xC000 and b.start_by == ""
    type_line(b, "C100 37")
    assert b.start == 0xC100 and b.start_by == "auto"
    b.to_addr()
    type_line(b, "C200 37")
    assert b.start == 0xC100 and b.row == 0xC200


def test_set_start_is_kept():
    """自分で決めた開始番地は、貼り付けでも、取り消しでも変わらない。プログラムを読み込めば
    そのプログラムの開始番地になる"""
    m, b = bench()
    b.paste("C000 37")
    assert b.set_start_at(0xC010) == "開始番地をC010にしました"
    assert (b.start, b.start_by) == (0xC010, "user")
    b.paste("C100 2D01")
    assert b.start == 0xC010
    b.undo()
    assert b.start == 0xC010
    b.to_addr()
    type_line(b, "C300 37")
    assert b.start == 0xC010
    assert "RAMの外" in b.set_start_at(0x1000) and b.start == 0xC010
    b.load_blocks([(0xC400, b"\x37")], 0xC400)
    assert (b.start, b.start_by) == (0xC400, "auto")


def test_start_survives_state_save():
    """どこでもセーブに、開始番地を自分で決めたかも書く。前の版の保存(決め方がない)は、
    自動で決めたものとして読む"""
    m, b = bench()
    b.set_start_at(0xC020)
    info = b.save()
    m2, b2 = bench()
    b2.restore(info)
    assert (b2.start, b2.start_by) == (0xC020, "user")
    del info["start_by"]
    b2.restore(info)
    assert (b2.start, b2.start_by) == (0xC020, "auto")


def test_start_field_typing():
    """開始番地の欄をクリックして16進表記の4桁を打つと、開始番地になる。Escでやめると
    変わらない。打っているあいだ、カーソルは動かない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    _type(app, "C000 37")
    app.frame()
    rect = next(r for r, kind, _a in v.hits if kind == "start")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    assert b.start_buf == ""
    app.frame()
    _type(app, "C1")
    _key(app, pygame.K_ESCAPE)
    assert b.start_buf is None and b.start == 0xC000
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    cursor = b.cursor
    _type(app, "C08")
    _key(app, pygame.K_BACKSPACE)
    _type(app, "10")
    assert (b.start, b.start_by, b.start_buf) == (0xC010, "user", None)
    assert b.cursor == cursor and app.m.mem[0xC001] == 0
    app.frame()
    app.close()


def test_start_shortcut_and_menu():
    """⌘Aでカーソルの所を開始番地にする。作業欄の右クリックでは、クリックした番地を開始番地に
    する、そこから実行する、止める所を置くを選べる。開始番地の行には印を描く"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    b.paste("C000 37\nC010 027F10F8005237")
    b.place(0xC010)
    _key(app, pygame.K_a, "a", pygame.KMOD_CTRL)
    assert (b.start, b.start_by) == (0xC010, "user")
    b.go(0xC000)
    app.frame()
    hit = next(h for h in v.hits if h[1] == "goto" and h[2] == 0xC000)
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=hit[0].center))
    assert app.popup is not None and app.popup.kind == "bench" and b.cursor == 0xC000
    items = app.popup_items()
    labels = [it.label for it in items]
    assert labels == [
        "C000番地を開始番地にする",
        "C000番地から実行する",
        "C000番地の止める所を置く",
        "",
        "C000番地からデータにする",
        "C000番地から命令にする",
        "C000番地の指定を消す",
    ]
    app.popup_run(2)
    assert 0xC000 in b.breaks and app.popup is None
    app.frame()  # 開始番地の印と止める所を描く
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=hit[0].center))
    assert app.popup_items()[2].label == "C000番地の止める所を外す"
    app.popup_run(0)
    assert b.start == 0xC000
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=hit[0].center))
    assert not app.popup_items()[0].enabled  # いまの開始番地
    b.breaks.clear()
    app.popup = None
    app.bench_run_at(0xC010)
    assert b.start == 0xC010
    for _ in range(3):
        app.frame()
    assert b.state == "edit" and app.m.columns()[0] == 0x7F
    app.close()


def test_paste_into_start_field(monkeypatch):
    """開始番地の欄に打っているあいだの⌘Vは、番地として欄へ入れ、ダンプは書き換えない。
    番地でなければ欄はそのまま。⌘Zは欄の字を消すだけ、⌘Aは何もしない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    _type(app, "C000 020137")
    b.place(0xC000)
    app.frame()
    rect = next(r for r, kind, _a in v.hits if kind == "start")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    monkeypatch.setattr(app, "clipboard", lambda: "LIA 01")
    _key(app, pygame.K_v, "v", pygame.KMOD_CTRL)
    assert b.start_buf == "" and bytes(app.m.mem[0xC000:0xC003]) == bytes.fromhex("020137")
    assert "番地ではありません" in v.flash
    _type(app, "C0")
    _key(app, pygame.K_z, "z", pygame.KMOD_CTRL)
    _key(app, pygame.K_a, "a", pygame.KMOD_CTRL)
    assert b.start_buf == "" and b.start == 0xC000 and b.can_undo()
    monkeypatch.setattr(app, "clipboard", lambda: " &C010\n")
    _key(app, pygame.K_v, "v", pygame.KMOD_CTRL)
    assert (b.start, b.start_by, b.start_buf) == (0xC010, "user", None)
    assert bytes(app.m.mem[0xC000:0xC003]) == bytes.fromhex("020137")
    app.close()


def test_counter_reset_clears_timer_flags():
    """OUTCでカウンタをリセットすると、立ったままのタイマのフラグも消える。リセットのあとTEST 01で
    512msを待つプログラム(押し続けたキーの繰り返しまでの待ちなど)が、前に立った印で
    すぐに抜けない"""
    from sc61box.machine import TICK_2MS

    m, _b = bench()
    m.halted = True  # 時間だけ進める
    m.run(TICK_2MS * 257)
    assert m.test_bits() & 0x03 == 0x03  # 読まれないまま立っている
    m.out_c(0x03)
    assert m.test(0x03) == 0
    m.halted = True
    m.run(TICK_2MS * 255)
    assert m.test(0x01) == 0  # 510msではまだ
    m.halted = True
    m.run(TICK_2MS)
    assert m.test(0x01) == 0x01  # 512msで立つ


def test_timer_counts_only_after_reset_in_a_run():
    """まとめて動かす区切りの途中でカウンタをリセットしても、タイマはリセットのあとの
    時間だけ進む(区切りの頭からの時間を足すと、リセットの直後に2msの印が立つ)"""
    from sc61box.machine import TICK_2MS

    m, b = bench()
    # WAIT FFを並べて2msの8割ほど待ってから、Cポートに02を出してカウンタをリセットし、
    # その場で回る(WAIT FFは6+255サイクル)
    waits = TICK_2MS * 8 // 10 // 261
    code = bytes.fromhex("4EFF" * waits + "0202125FDBDF2D01")
    b.load_blocks([(0xC000, code)], 0xC000)
    m.cpu.pc = 0xC000
    m.t2 = m.t512cnt = 0
    m.t2ms = m.t512 = 0
    m.run(TICK_2MS)
    assert m.cpu.pc == 0xC000 + len(code) - 2 and m.t2 < TICK_2MS // 2
    assert m.test(0x02) == 0
    m.run(TICK_2MS)
    assert m.test(0x02) == 0x02


def test_lcd_duty_from_real_writes():
    """液晶RAMに書いた時刻から、点いていた時間の割合を求める。ほんの数サイクルだけ点いた
    ドットは、そのフレームのあいだずっと点いていたようには出ない"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    # F800に7Fを書いてすぐ00に戻し、WAITで待って繰り返す
    b.paste("C000 027F10F800520200524EFF4EFF2D0E")
    app.bench_do("run")
    for _ in range(3):
        app.frame()
    share = app.lcd_duty[0]
    assert 0 < share[0] < 0.03 and share[7] == 0
    assert app.panel.level[0][0] < 0.05
    app.close()


def test_tab_jumps_to_typed_address():
    """Tabで番地の欄へ移り、4桁打つとその番地の行へ飛ぶ(メモリは書き換えない)。説明にも出す"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    _type(app, "C000 37")
    assert "Tab" in v.hint()
    _key(app, pygame.K_TAB, "\t")
    assert b.field == "addr"
    _type(app, "C010")
    assert (b.row, b.field, b.col) == (0xC010, "data", 0) and b.start == 0xC000
    assert app.m.mem[0xC010] == 0
    app.close()


def test_dump_list_export_reloads(tmp_path, monkeypatch):
    """⇧⌘Eで、本のダンプリストの形(番地 8バイト:チェックサム)に書き出す。読み込みでも
    貼り付けでも、同じバイトに戻る"""
    from sc61box import programs

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    assert b is not None
    b.paste(_hex_lines(0xC000, JUMP_OVER_ZEROS))
    _key(app, pygame.K_e, "e", pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
    path = next(tmp_path.rglob("dumplist-*.hex"))
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln[:1] not in (";", "#")]
    assert lines[0] == "C000 79C0200000000000:59"
    assert lines[-1] == "C020 027F10F8005237:12" and len(lines) == 5
    assert "# run: CALL &C000" in text
    blocks, errors = programs.parse_hex(text)
    assert not errors
    got = b"".join(data for _a, data in blocks)
    assert blocks[0][0] == 0xC000 and got == JUMP_OVER_ZEROS
    m2, b2 = bench()
    res = b2.paste(text)
    assert res.written == len(JUMP_OVER_ZEROS) and not res.bad_sums and not res.skipped
    assert bytes(m2.mem[0xC000 : 0xC000 + len(JUMP_OVER_ZEROS)]) == JUMP_OVER_ZEROS
    labels = [it.label for it in app.popup_items("program")]
    assert "ダンプリストの形で書き出す" in labels
    app.close()


def test_hex_file_checksums():
    """.hexの行末の「:チェックサム」は、合わなければエラーにして読み込まない。チェックサムは
    行のバイトの和の下2桁"""
    from sc61box import programs

    blocks, errors = programs.parse_hex("C000 027F10F800523700:12\nC008 0102:03\n")
    assert not errors and len(blocks) == 2
    blocks, errors = programs.parse_hex("C000 027F10F800523700:12\nC008 0102:04\n", "x.hex ")
    assert blocks == [(0xC000, bytes.fromhex("027F10F800523700"))]
    assert errors == ["x.hex 2行目のチェックサムが合わない(計算すると03): C008 0102:04"]
    for bad in ("0G", "3", "", "03:03"):
        blocks, errors = programs.parse_hex(f"C008 0102:{bad}\n")
        assert not blocks and "チェックサム(16進表記2桁)ではない" in errors[0]
    m, b = bench()
    res = b.paste("C000 027F10F800523700:13\nC008: 01 02 : 03\n")
    assert res.written == 10 and res.bad_sums == [0xC000]


def test_span_field_typing(monkeypatch, tmp_path):
    """範囲の行をクリックして始めと終わりの番地を8桁打つと、書き出す範囲になる。Escでやめる、
    何も打たずにEnterで自動に戻す。逆の順は理由を出す。⌘Vで貼り付けられる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    _type(app, "C000 020137")
    app.frame()
    rect = next(r for r, kind, _a in v.hits if kind == "span")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    assert b.span_buf == ""
    app.frame()
    assert next(r for r, kind, _a in v.hits if kind == "span")
    assert "Enter" in v.hint()
    _type(app, "C00")
    _key(app, pygame.K_ESCAPE)
    assert b.span_buf is None and b.span is None
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    cursor = b.cursor
    _type(app, "C010C00")
    _key(app, pygame.K_BACKSPACE)
    _type(app, "00")
    assert b.span is None and "前です" in v.flash and not v.flash_ok
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    _type(app, "C000C00F")
    assert b.span == (0xC000, 0xC010) and b.export_ranges() == [(0xC000, 0xC010)]
    assert v.flash == "書き出す範囲をC000〜C00Fにしました" and v.flash_ok
    assert b.cursor == cursor and app.m.mem[0xC003] == 0
    app.frame()
    app.bench_export(listing=True)
    text = next(tmp_path.rglob("dumplist-*.hex")).read_text(encoding="utf-8")
    assert "C000 0201370000000000:3A\nC008 0000000000000000:00\n" in text
    info = b.save()
    m2, b2 = bench()
    b2.restore(info)
    assert b2.span == (0xC000, 0xC010)
    app.frame()
    rect = next(r for r, kind, _a in v.hits if kind == "span")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    _key(app, pygame.K_RETURN, "\r")
    assert b.span is None and b.export_ranges() == [(0xC000, 0xC003)]
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    monkeypatch.setattr(app, "clipboard", lambda: "&C000-&C001\n")
    _key(app, pygame.K_v, "v", pygame.KMOD_CTRL)
    assert b.span == (0xC000, 0xC002) and b.span_buf is None
    assert bytes(app.m.mem[0xC000:0xC003]) == bytes.fromhex("020137")
    b.load_blocks([(0xC100, b"\x37")])
    assert b.span is None
    app.close()


def test_span_without_written_bytes():
    """書いた所がなくても、範囲を決めれば書き出せる(BASICのPOKEで書いたマシン語など)"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    app.frame()
    assert b.export_ranges() == []
    rect = next(r for r, kind, _a in v.hits if kind == "span")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    _type(app, "C000C007")
    assert b.export_ranges() == [(0xC000, 0xC008)]
    app.frame()
    assert any(kind == "listing" for _r, kind, _a in v.hits)
    app.close()


def test_full_range_export_finishes():
    """0000〜FFFFの範囲も書き出せる(逆アセンブルの番地がFFFFから0000へ戻っても止まる)"""
    from sc61box import programs

    m, b = bench()
    m.mem[0xFFFF] = 0x79  # 3バイトの命令がFFFFから0000へまたがる
    b.set_span(0x0000, 0xFFFF)
    assert b.export_ranges() == [(0, 0x10000)]
    for text in (b.dump_text(0, 0x10000), b.dump_list(0, 0x10000)):
        blocks, errors = programs.parse_hex(text)
        assert not errors and sum(len(d) for _a, d in blocks) == 0x10000
        assert blocks[0][0] == 0 and blocks[-1][0] + len(blocks[-1][1]) == 0x10000


def test_fields_keep_non_hex_keys():
    """開始番地と範囲の欄では、空白や区切りの字を打っても欄に打ったまま(続けて打った字で
    ダンプを書き換えない)。ほかの字は知らせを出す。矢印は欄をやめてカーソルを動かす"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    _type(app, "C000 37")
    app.frame()
    before = bytes(app.m.mem[0xC000:0xC200])
    span = next(r for r, kind, _a in v.hits if kind == "span")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=span.center))
    _type(app, "C000 ")
    _key(app, pygame.K_MINUS, "-")
    _type(app, "C0FF")
    assert b.span == (0xC000, 0xC100) and bytes(app.m.mem[0xC000:0xC200]) == before
    app.frame()
    start = next(r for r, kind, _a in v.hits if kind == "start")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=start.center))
    _key(app, pygame.K_7, "&")
    _key(app, pygame.K_g, "g")
    assert b.start_buf == "" and "16進表記" in v.flash
    _type(app, "C010")
    assert b.start == 0xC010 and bytes(app.m.mem[0xC000:0xC200]) == before
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=start.center))
    row = b.row
    _key(app, pygame.K_DOWN)
    assert b.start_buf is None and b.row == row + 8
    app.close()


def test_auto_button_clears_span():
    """自分で範囲を決めると、範囲の行の右に「自動に戻す」が出る。押すと書いた所からの範囲"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b, v = app.bench, app.bench_view
    assert b is not None and v is not None
    _type(app, "C000 37")
    app.frame()
    assert not any(kind == "spanauto" for _r, kind, _a in v.hits)
    b.set_span(0xC000, 0xC0FF)
    app.frame()
    btn = next(r for r, kind, _a in v.hits if kind == "spanauto")
    assert v.hit(btn.center) == ("spanauto", 0)
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=btn.center))
    assert b.span is None and b.export_ranges() == [(0xC000, 0xC001)] and v.flash_ok
    app.close()


def test_spaces_between_typed_bytes():
    """バイトの2桁を打った直後の空白は区切りとして読み飛ばす(「02 7F 10」と打っても
    バイトを飛ばさない)。続けてもう1度Spaceを押せば、次のバイトへ進む"""
    m, b = bench()
    type_line(b, "C000 02 7F 10 F8 00 52 37 00")
    assert bytes(m.mem[0xC000:0xC008]) == bytes.fromhex("027F10F800523700")
    assert workbench.checksum(b.row_bytes(0xC000)) == 0x12
    b.go(0xC010)
    type_line(b, "AA  BB")
    assert bytes(m.mem[0xC010:0xC013]) == bytes.fromhex("AA00BB")


def test_restore_puts_cursor_on_address():
    """保存した状態に戻すと、カーソルは番地の欄にある。続けて番地を打っても、前のバイトを
    書き換えない"""
    m, b = bench()
    type_line(b, "C000 027F")
    info = b.save()
    m2, b2 = bench()
    m2.mem[0xC000:0xC002] = bytes.fromhex("027F")
    b2.restore(info)
    assert b2.field == "addr"
    type_line(b2, "C000 37")
    assert bytes(m2.mem[0xC000:0xC002]) == bytes.fromhex("377F")
