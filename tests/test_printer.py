"""プリンタをつなぐと、LPRINTとLLISTの印字が受け取れる"""

import os

import pygame
import pytest
from helpers import boot, finish, make_app, settle, typ

from sc61box import programs
from sc61box.app import BAR_H, FPS
from sc61box.audio import PRINT_CATCH_UP, PRINT_GAP, PRINT_LINE
from sc61box.machine import CLOCK


def _printed(model, src, command="RUN"):
    m, t = boot(model)
    m.connect_printer()
    if model in ("1251", "1245"):  # 電源を入れたときにプリンタを調べる
        m.power_off()
        m.mode = "RUN"
        m.wake()
        m.run(CLOCK)
    typ(m, t, src, mode="PRO")
    typ(m, t, command + "\n", wait=3, mode="PRO" if command == "LLIST" else "RUN")
    assert m.printer is not None
    return m.printer.text()


@pytest.mark.parametrize("model", ["1251", "1245", "1261", "1350"])
def test_lprint(model):
    src = '10 LPRINT "AB0O";12\n20 LPRINT "π√"\n'
    assert _printed(model, src) == "AB0O12.\nπ√\n"


@pytest.mark.parametrize("model", ["1251", "1261", "1350"])
def test_llist(model):
    text = _printed(model, '10 PRINT "OK"\n20 A=10\n', "LLIST")
    assert [line.split(":", 1)[1] for line in text.splitlines()] == ['PRINT "OK"', "A=10"]


def test_kana_on_s1():
    assert _printed("1261", '10 LPRINT "ｱｲｳ"\n') == "ｱｲｳ\n"


def test_no_printer_skips_lprint():
    """プリンタがなければ、LPRINTは何もせずに次へ進む"""
    m, t = boot()
    typ(m, t, '10 LPRINT "A"\n20 PRINT 7\n', mode="PRO")
    assert typ(m, t, "RUN\n", mode="RUN").strip().rstrip("?.") == "7"
    assert m.printer is None


def test_paper_appears_when_printing(tmp_path, monkeypatch):
    """プリンタはいつもつながっていて、印字したときだけ窓の下に紙が出る。印字は紙の絵として
    保存でき、紙はしまえる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app()
    h = app.window.get_height()
    assert app.m.printer is not None and not app.paper_open
    prog = programs.Program(name="p", title="p", basic='10 LPRINT "HELLO"\n', run="RUN")
    app.open_program(prog, run=True)
    settle(app)
    for _ in range(60):
        app.frame()
    assert app.m.printer.lines == [b"HELLO"]
    # 紙のぶん窓が高くなる(画面に入らなければ本体を縮めるので、本体の高さから数える)
    assert app.paper_open
    assert app.window.get_height() == app.body_size[1] + app.paper.height + BAR_H
    app.save_printout()
    saved = list(tmp_path.glob("print-*.png"))
    assert len(saved) == 1
    img = pygame.image.load(str(saved[0]))
    assert img.get_width() == app.paper.width * 2
    dark = sum(
        1
        for x in range(img.get_width())
        for y in range(img.get_height())
        if sum(img.get_at((x, y))[:3]) < 300
    )
    assert dark > 100  # 点が打ってある
    app.handle(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=app.paper.close_rect.center)
    )
    assert not app.paper_open and app.window.get_height() == h
    finish(app.m, app.typer)
    app.close()


def test_printer_sound_while_paper_moves():
    """紙が動いているあいだだけプリンタの音が出て、止まると消える。本体の音(空なら無音)に
    足したサンプルになる"""
    from array import array

    from sc61box.audio import FRAME_SAMPLES, PrinterSound

    snd = PrinterSound()
    assert snd.mix(b"", False) == b""
    for _ in range(3):
        pcm = snd.mix(b"", True)
    assert len(pcm) == 2 * FRAME_SAMPLES and max(abs(v) for v in array("h", pcm)) > 500
    for _ in range(30):  # 止めてから1秒で鳴りやむ
        pcm = snd.mix(bytes(2 * FRAME_SAMPLES), False)
    assert not snd.active and max(abs(v) for v in array("h", pcm)) == 0


class _Ear:
    """音の出力先の代わり。渡されたサンプルをためる"""

    keep_silent = False

    def __init__(self) -> None:
        self.pcm: list[bytes] = []

    def level(self) -> int:
        from sc61box.audio import TARGET

        return TARGET

    def push(self, pcm: bytes) -> None:
        self.pcm.append(pcm)

    def clear(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_app_sounds_printer_on_new_lines(tmp_path, monkeypatch):
    """印字が出て紙が送られるあいだ、スピーカーにプリンタの音が入る"""
    from array import array

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    ear = _Ear()
    app.speaker = ear  # pyrefly: ignore
    printer = app.m.printer
    assert printer is not None
    for _ in range(5):
        app.frame()
    assert all(not p or max(abs(v) for v in array("h", p)) == 0 for p in ear.pcm)
    printer.put(0x41)
    printer.put(0x0D)
    for _ in range(10):
        app.frame()
    assert app.paper_open and any(p and max(abs(v) for v in array("h", p)) > 500 for p in ear.pcm)
    app.close()


def test_lines_come_out_at_printer_speed(tmp_path, monkeypatch):
    """印字した行は、実機と同じ速さで1行ずつ紙に出る(1行の印字と、次の行までの間)。
    改行していない途中の行は出さない。紙をしまうと、出ていない行は次の紙に出さない"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    printer = app.m.printer
    assert printer is not None
    for code in b"ONE\rTWO\rTHREE\rFOU":
        printer.put(code)
    app.frame()
    assert app.paper_rows() == [b"ONE"] and app.paper.moving
    per_line = round((PRINT_LINE + PRINT_GAP) * FPS)
    for _ in range(per_line):
        app.frame()
    assert app.paper_rows() == [b"ONE", b"TWO"]
    for _ in range(per_line):
        app.frame()
    assert app.paper_rows() == [b"ONE", b"TWO", b"THREE"]  # 途中の行FOUは出さない
    assert app.printout is not None and app.printout.rows() == [b"ONE", b"TWO", b"THREE", b"FOU"]
    printer.put(0x0D)
    for code in b"FIVE\rSIX\r":
        printer.put(code)
    app.frame()
    assert app.paper_rows() == [b"ONE", b"TWO", b"THREE"]  # 4行目はまだ送り出していない
    app.close_paper()
    assert not app.paper.moving and app.paper_rows() == []
    printer.put(0x41)
    printer.put(0x0D)
    for _ in range(2):
        app.frame()
    assert app.paper_rows() == [b"A"]  # 前の紙の残りは出さない
    app.close()


def test_paper_follows_speed(tmp_path, monkeypatch):
    """速さの設定を2倍にすると、紙に行が出る速さとプリンタの音の速さも2倍になる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    app.turbo = 2
    printer = app.m.printer
    assert printer is not None
    for code in b"ONE\rTWO\r":
        printer.put(code)
    app.frame()
    assert app.paper_rows() == [b"ONE"] and app.print_rate == 2
    per_line = round((PRINT_LINE + PRINT_GAP) / 2 * FPS)
    for _ in range(per_line - 1):
        app.frame()
    assert app.paper_rows() == [b"ONE"]
    app.frame()
    assert app.paper_rows() == [b"ONE", b"TWO"]
    app.close()


def test_backlog_catches_up(tmp_path, monkeypatch):
    """出していない行がPRINT_KEEPより多いと、PRINT_CATCH_UP秒で出し切る速さに上げ、出し切る
    までその速さを保つ。1フレームに1行より速ければ、何行かまとめて出す。出し切ったあとの短い
    印字は実機の速さに戻る"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    printer = app.m.printer
    assert printer is not None
    rows = [b"L%03d" % i for i in range(120)]
    for row in rows:
        for code in row + b"\r":
            printer.put(code)
    app.frame()
    assert 1 < len(app.paper_rows()) < len(rows) and app.print_rate > 1
    for _ in range(round(PRINT_CATCH_UP * FPS)):
        app.frame()
    assert app.paper_rows() == rows
    for _ in range(FPS):
        app.frame()
    for code in b"A\rB\r":
        printer.put(code)
    app.frame()
    assert app.paper_rows()[-1] == b"A" and app.print_rate == 1
    for _ in range(round((PRINT_LINE + PRINT_GAP) * FPS) - 1):
        app.frame()
    assert app.paper_rows()[-1] == b"A"
    app.close()


def test_fast_printing_sounds_and_shows_lines(tmp_path, monkeypatch):
    """何行かまとめて出すほど速くても、紙が動くフレームにはプリンタの音が入り、紙送りは1行
    ぶんまでなので、紙に出した行が紙の外へずれて見えなくなることはない"""
    from array import array

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    ear = _Ear()
    app.speaker = ear  # pyrefly: ignore
    printer = app.m.printer
    assert printer is not None
    for i in range(400):
        for code in b"L%03d\r" % i:
            printer.put(code)
    app.frame()
    line = app.paper.DOT * app.paper.LINE
    for _ in range(40):
        app.frame()
        assert app.paper.feed <= line
    loud = [bool(p) and max(abs(v) for v in array("h", p)) > 500 for p in ear.pcm[-40:]]
    assert 2 < len(app.paper_rows()) < 400 and sum(loud) >= 38
    app.close()


def test_printer_sound_steps_faster():
    """紙送りが速いと、プリンタの音のステップの間隔がその分だけ縮む"""
    from sc61box.audio import PrinterSound

    class Steps:
        """ステップを数える乱数の代わり(ステップごとにrandintを1回呼ぶ)"""

        def __init__(self) -> None:
            self.n = 0

        def randint(self, _a: int, _b: int) -> int:
            self.n += 1
            return 0

        def random(self) -> float:
            return 0.5

    counts = []
    for speed in (1, 4):
        snd, steps = PrinterSound(), Steps()
        snd.rng = steps  # pyrefly: ignore
        for _ in range(30):
            snd.mix(b"", True, speed)
        counts.append(steps.n)
    assert 140 <= counts[0] <= 150 and abs(counts[1] - 4 * counts[0]) <= 10  # 1秒に147ステップ


def test_printer_font():
    """紙に打つ字の形はプリンタの字の表から取る。00〜FFのすべてに形があり、本体のROMに
    よらない"""
    from sc61box.printer import char, load_font

    font = load_font()
    assert sorted(font) == list(range(256)) and all(len(g) == 5 for g in font.values())
    assert font[0x41] == bytes.fromhex("7c1211127c")  # A
    assert font[0x20] == font[0x00] == bytes(5) and font[0xB1] != bytes(5)  # 空白とｱ
    assert font[0x18] == font[0x5B] and font[0x19] == font[0x5D]  # √とπは2か所にある
    assert "".join(char(c) for c in (0x01, 0x0E, 0x5C, 0x61, 0xB1, 0xF1)) == "≠θ¥aｱ年"


def test_raw_codes_printed():
    """マシン語で送ったコードは、BASICから出せない字(小文字やカナ、記号)もそのまま打つ"""
    from sc61box.printer import Printer

    p = Printer()
    for code in b"\x0e\x1babc\xb1\xb2\r":
        p.put(code)
    assert p.lines == [b"\x0e\x1babc\xb1\xb2"] and p.text() == "θ→abcｱｲ\n"


def test_pc1350_line_lead_and_letter_o():
    """PC-1350は行の頭ごとに0Fか0Eを送り、英字のOを30で送る。行の頭に続く0F・0Eは打たず
    (印字モードでは行の終わりにも0Eが来て、次の行の頭で0Eと0Fが続く)、行の途中なら字(θ、⇒)
    として打つ。30はOの形で打つ"""
    m, _ = boot("1350")
    m.connect_printer()
    p = m.printer
    assert p is not None
    for code in b"\x0fO\x30\xf0\r\x0e\x0e\x0fA\x0f\x0eB\r":
        for i in range(8):  # 本体と同じく、1ビットずつ字として送る
            p.bit(code >> i, command=False)
    assert p.lines == [b"OO\xf0", b"A\x0f\x0eB"] and p.text() == "OO0\nA⇒θB\n"


def test_pc1350_print_mode_lines():
    """PC-1350の印字モード(SHIFT+ENTER)では、打った式と答えの行が印字される。ROMが行の頭と
    終わりに送る0F・0Eを字として打たない"""
    m, t = boot("1350")
    m.connect_printer()
    t.add_keys([["SHIFT"], ["ENTER"]])
    finish(m, t)
    m.run(CLOCK // 2)
    typ(m, t, "1+2\n", wait=1)
    typ(m, t, "3*4\n", wait=1)
    assert m.printer is not None
    assert m.printer.text() == "1+2\n                      3.\n3*4\n                     12.\n"


def test_exponent_mark_1251():
    """PC-1251は指数のEを60で送る。プリンタはそこに指数のEの形を持っている"""
    assert _printed("1251", "10 LPRINT 10^20\n").strip() == "1.E 20"


def test_printout_saved_automatically(tmp_path, monkeypatch):
    """印字がとぎれると、紙の絵が置き場所に保存され、紙の左に保存先が出る。紙をしまうと
    その紙は終わり、次の印字は新しいファイルになる"""
    import time

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app()
    prog = programs.Program(name="p", title="p", basic='10 LPRINT "ONE"\n', run="RUN")
    app.open_program(prog, run=True)
    settle(app)
    assert app.printout is not None
    first = app.printout.file
    assert first and first.startswith(str(tmp_path)) and app.paper.where_rect.width > 0
    assert open(first, "rb").read(4) == b"\x89PNG"  # 新しい紙はすぐに保存する
    assert app.m.printer is not None
    app.m.printer.put(ord("X"))  # 印字を足し、1秒より前に印字したことにする
    app.m.printer.put(0x0D)
    app.frame()
    app.printout.time -= 2
    app.frame()
    assert app.printout.saved == [b"ONE", b"X"] and "保存しました" in app.status
    app.close_paper()
    assert app.printout is None
    time.sleep(1.1)  # ファイルの名前(秒まで)が変わるように
    app.open_program(prog, run=True)
    settle(app)
    assert app.printout is not None and app.printout.file != first
    assert app.paper_rows() == [b"ONE"]
    app.close()  # 閉じるときも保存する
    assert len(list(tmp_path.glob("print-*.png"))) == 2


def test_partial_line_growth_is_saved(tmp_path, monkeypatch):
    """改行していない行に字を足しても、印字がとぎれたときに保存し直す(行の数は変わらない)"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app()
    assert app.m.printer is not None
    for code in b"START\rA":
        app.m.printer.put(code)
    app.frame()
    out = app.printout
    assert out is not None
    out.time -= 2
    app.frame()
    assert out.rows() == [b"START", b"A"] and out.saved == [b"START", b"A"]
    app.m.printer.put(ord("B"))
    app.frame()
    assert out.saved == [b"START", b"A"]  # 1秒たつまでは保存しない
    out.time -= 2
    app.frame()
    assert out.saved == [b"START", b"AB"]
    app.close()


def test_closing_paper_mid_line_starts_next_sheet_after_cut(tmp_path, monkeypatch):
    """改行の前に紙をしまうと、次の紙はその行の続きの字から(前の紙の字は入れない)"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app()
    assert app.m.printer is not None
    app.m.printer.put(ord("A"))
    app.frame()
    assert app.printout is not None and app.printout.rows() == [b"A"]
    first = app.printout.file
    app.close_paper()
    for code in b"B\rC":
        app.m.printer.put(code)
    app.frame()
    assert app.printout is not None and app.printout.file != first
    assert app.printout.rows() == [b"B", b"C"]
    app.close()
    files = sorted(tmp_path.glob("print-*.png"))
    assert len(files) == 2 and all(f.stat().st_size > 0 for f in files)


def test_blank_sheet_leaves_no_empty_file(tmp_path, monkeypatch):
    """空白だけの途中の行で紙を出してしまうと、名前を取るために作った空のファイルは残さない"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app()
    assert app.m.printer is not None
    app.m.printer.put(0x20)
    app.frame()
    assert app.printout is not None and app.printout.file
    assert os.path.getsize(app.printout.file) == 0
    app.close_paper()
    assert list(tmp_path.glob("print-*.png")) == []
    app.m.printer.put(0x20)
    app.frame()
    app.close()  # 終了のときも同じ
    assert list(tmp_path.glob("print-*.png")) == []


def test_print_files_do_not_overwrite(tmp_path, monkeypatch):
    """同じ秒に新しい紙になっても、前の紙のファイルを上書きしない"""
    from sc61box import printout

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    monkeypatch.setattr(printout.time, "strftime", lambda fmt, *a: "20261022-000000")
    app = make_app()
    for word in ("ONE", "TWO"):
        prog = programs.Program(name="p", title="p", basic=f'10 LPRINT "{word}"\n', run="RUN")
        app.open_program(prog, run=True)
        settle(app)
        app.close_paper()
    names = sorted(p.name for p in tmp_path.glob("print-*.png"))
    assert names == ["print-20261022-000000-2.png", "print-20261022-000000.png"]
    app.close()


def test_print_file_name_is_reserved(tmp_path):
    """印字の名前は、確かめると同時にファイルを作って取る(ほかのエミュレータと重ならない)"""
    from sc61box.paths import unused_file

    first = unused_file(str(tmp_path), "print-x", ".png")
    second = unused_file(str(tmp_path), "print-x", ".png")
    assert first != second and (tmp_path / "print-x.png").exists()


def test_printout_picture_is_opaque():
    """印字の絵はアルファのない形式で作る。窓がアルファの成分のある形式でも、字のところが
    透けない"""
    app = make_app()
    img = app.paper.picture([b"AB"])
    assert img.get_bitsize() == 24 and img.get_masks()[3] == 0
    assert any(sum(img.get_at((x, y))[:3]) < 400 for x in range(14, 40) for y in range(20, 40))
    app.close()


def test_opaque_drops_meaningless_alpha():
    """アルファの成分があってSRCALPHAでない絵(macOSの窓の形式)は、写すと透けずに色が残る"""
    from sc61box.app import opaque

    masks = (0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    src = pygame.Surface((4, 4), pygame.SRCALPHA)
    src.fill((36, 38, 70, 220))
    dst = pygame.Surface((8, 8), 0, 32, masks)
    dst.fill((238, 237, 229))
    dst.blit(src, (2, 2))
    assert dst.get_at((3, 3))[3] == 0  # この形式では、字のところのアルファが0になる
    out = opaque(dst)
    assert out.get_at((3, 3))[:3] == dst.get_at((3, 3))[:3] and out.get_masks()[3] == 0
