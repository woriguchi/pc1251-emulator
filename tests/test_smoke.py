"""ウィンドウを出さずにアプリを数十フレーム動かす"""

import os
import sys
import types

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame  # noqa: E402

from pc1251emu.app import App  # noqa: E402
from pc1251emu.lcdtext import lcd_text  # noqa: E402


def test_app_types_and_computes():
    args = types.SimpleNamespace(
        scale=1.0, type=None, load=None, fresh=True, mute=True, persist=1.0
    )
    app = App(args)
    app.typer.add_text("12*3\n")
    for _ in range(90):
        app.frame()
    assert lcd_text(app.m).strip().startswith("36")
    for ch in "(+)":  # 記号はTEXTINPUTから入り、SHIFT付きの打鍵に直る
        app.handle(pygame.event.Event(pygame.TEXTINPUT, text=ch))
    assert app.typer.queue[0][0] == app.typer.LIVE and app.typer.queue[0][2:] == ["SHIFT"]
    for _ in range(30):
        app.frame()
    assert not app.typer.busy
    app.close()


def test_switch_knob_matches_label():
    """つまみの光る帯が、そのモードのラベルの段(マウスで選ぶ位置)に来ている"""
    import numpy as np
    from PIL import Image

    from pc1251emu import display

    assets = os.path.join(os.path.dirname(display.__file__), "assets")
    x0, y0 = map(int, open(os.path.join(assets, "switch_box.txt")).read().split())
    for mode, y in App.SW_STOPS:
        im = Image.open(os.path.join(assets, f"switch_{mode}.png")).convert("L")
        cx = 1342  # 溝(tools/body_art.pyのSW_SLOT)のまんなか
        col = im.crop((cx - x0 - 10, 0, cx - x0 + 10, im.height))
        rows = np.asarray(col, int).sum(axis=1).tolist()
        inside = range(90 - y0, 193 - y0)  # 溝の中だけを見る
        ridge = y0 + max(inside, key=rows.__getitem__)
        assert abs(ridge - y) <= 8, (mode, ridge, y)


def test_shortcuts_and_popup():
    """Fキーを使わずに、⌘/Ctrlの組み合わせと右クリックのメニューで操作できる"""
    app = _app()
    m = app.m
    ev = pygame.event.Event

    def key(k, mod=pygame.KMOD_CTRL):
        app.handle(ev(pygame.KEYDOWN, key=k, mod=mod, unicode="", scancode=0))

    key(pygame.K_UP)
    assert m.mode == "PRO"
    key(pygame.K_DOWN, pygame.KMOD_LMETA)
    assert m.mode == "RUN"
    key(pygame.K_t)
    assert app.turbo == 4
    key(pygame.K_o)
    assert app.menu is not None
    key(pygame.K_ESCAPE, 0)
    assert app.menu is None
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=(300, 200)))
    app.frame()
    assert app.popup is not None
    labels = [t for t, _k, _a in app.popup_items()]
    i, rect = next((i, r) for i, r in app.popup["rows"] if labels[i] == "スイッチ PRO")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    assert app.popup is None and m.mode == "PRO"
    # メニューからプログラムを選んで読み込み、実行する
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=3, pos=(300, 100)))
    app.frame()
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=app.popup["rows"][0][1].center))
    assert app.popup is not None and app.popup["page"] == "progs"
    app.frame()
    labels = [t for t, _k, _a in app.popup_items()]
    assert "文字のアニメーション(WAITの例)" in labels
    i, rect = next((i, r) for i, r in app.popup["rows"] if labels[i].startswith("HELLO"))
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    assert app.popup is None and app.typer.busy
    app.close()


def _app():
    args = types.SimpleNamespace(
        scale=1.0, type=None, load=None, fresh=True, mute=True, persist=1.0
    )
    app = App(args)
    for _ in range(40):
        app.frame()
    return app


def _settle(app, limit=3000):
    for _ in range(limit):
        app.frame()
        if not app.typer.busy:
            break
    for _ in range(10):
        app.frame()


def test_open_basic_and_hex_pair(tmp_path=None):
    """同じ名前の.basと.hexを組にして読み込み、#run:で実行できる"""
    import tempfile

    from pc1251emu import programs
    from pc1251emu.machine import CLOCK

    d = tmp_path or tempfile.mkdtemp()
    with open(os.path.join(d, "pair.hex"), "w") as f:
        f.write("# title: 組の試験\nC300 0102 0304:0A\n")
    with open(os.path.join(d, "pair.bas"), "w") as f:
        f.write('# run: RUN\n10 A=6*7\n20 PRINT "X";A\n')
    prog = programs.load_program(os.path.join(d, "pair.bas"))
    assert prog.title == "組の試験" and prog.kinds == "BASIC+HEX" and prog.size == 4
    app = _app()
    app.typer.add_text("10 PRINT 1\n")  # 前のプログラムはNEWで消える
    _settle(app)
    app.open_program(prog, run=True)
    assert bytes(app.m.mem[0xC300:0xC304]) == bytes([1, 2, 3, 4])
    _settle(app)
    app.m.run(CLOCK)
    assert lcd_text(app.m).strip().startswith("X"), lcd_text(app.m)
    assert "42" in lcd_text(app.m)
    assert app.m.mode == "RUN"
    app.close()


def test_samples_load():
    """リポジトリのprograms/にある見本が読め、PROモードでLISTできる"""
    from pc1251emu import programs

    here = os.path.join(os.path.dirname(__file__), "..", "programs")
    items = programs.scan([here])
    assert {p.name for p in items} >= {"hello", "beep", "primes"}
    app = _app()
    for prog in items:
        assert not prog.errors, prog.errors
        app.open_program(prog)
        _settle(app)
        app.typer.add_mode("PRO")
        app.typer.add_text("LIST\n")
        _settle(app)
        first = prog.basic.split("\n")[0]
        assert lcd_text(app.m).replace("?", " ").split()[0] == first.split()[0], (
            prog.name,
            lcd_text(app.m),
        )
        app.typer.add_mode("RUN")
    app.close()


def test_mogura_on_pc_interpreter():
    """もぐらたたき(# hex: でPC-インタープリタを読む)で、出た穴の数字キーを押すと得点が入る"""
    from pc1251emu import programs

    prog = programs.find("mogura")
    if prog is None:  # 記事のプログラムは公開版に入っていない
        return
    assert prog.size == 976 and not prog.errors
    app = _app()
    m = app.m
    app.open_program(prog, run=True)
    for _ in range(3000):
        app.frame()
        if app.typer.busy:
            continue
        c = m.mem[0xC688]  # 変数C(押すキーのコード。数字1〜6は41h〜46h)
        want: set[str] = {str(c - 0x40)} if 0x41 <= c <= 0x46 else set()
        m.held.difference_update(set("123456") - want)
        m.held.update(want)
        if m.mem[0xC69F] >= 2:  # 変数Z(得点)
            break
    assert m.mem[0xC69F] >= 2
    app.close()


def test_display_stays_on_while_computing():
    """見本noise.bas: CALLで表示をオンにすると、計算中も表示が消えず、棒が伸びる"""
    from pc1251emu import programs

    app = _app()
    m = app.m
    prog = programs.find("noise")
    assert prog is not None
    app.open_program(prog, run=True)
    while app.typer.busy:
        app.frame()
    for _ in range(90):
        app.frame()
        assert m.display_on()
    assert m.mem[0xF87B] == 0x7F and m.mem[0xF878] == 0x7F
    app.close()


def test_breakout_in_machine_code():
    """見本break: easyとnormalの両方で、打ち出すとブロックが減り、BRKで戻って得点が読める"""
    for level, height in (("1", 3), ("2", 2)):
        _play_breakout(level, height)


def _play_breakout(level: str, height: int) -> None:
    from pc1251emu import programs

    app = _app()
    m = app.m
    r = m.cpu.ram
    prog = programs.find("break")
    assert prog is not None and not prog.errors
    app.open_program(prog, run=True)
    while app.typer.busy:
        app.frame()
    for _ in range(20):
        app.frame()
    assert "EASY" in lcd_text(m).replace("?", " "), lcd_text(m)
    app.typer.add_text(level + "\n")  # INPUTに難しさを答える
    while app.typer.busy:
        app.frame()
    for _ in range(90):
        app.frame()

    def column(x):  # 液晶の左からx列目の点(ビット0が上)
        return m.mem[0xF800 + x] if x < 60 else m.mem[0xF87B - (x - 60)]

    assert m.cpu.pc >= 0xC000 and m.display_on()
    assert r[0x15] == height and bin(column(0)).count("1") == height  # パドルの高さ
    for _ in range(40):  # パドルは下の限りまで動く
        m.held.add("DOWN")
        app.frame()
    m.held.clear()
    app.frame()
    assert r[0x14] == 7 - height and column(0) >> 7 == 0
    m.held.add("SPC")
    for _ in range(5):
        app.frame()
    m.held.clear()

    first_hit = None
    seen_ball = False
    left0 = 42
    for _ in range(30 * 8):  # パドルを玉の段に合わせ続ける
        app.frame()
        bx, wall = r[0x10], r[0x16]
        # パドルと壁のあいだに見えるのは玉の1点だけ
        dots = sum(bin(column(x)).count("1") for x in range(2, wall - 1))
        assert dots <= 1, [column(x) for x in range(2, wall - 1)]
        seen_ball = seen_ball or dots == 1
        if first_hit is None and r[0x1C] < left0:
            first_hit = bx  # 最初にブロックが壊れたときの玉の位置は、壁の手前か中
            assert bx >= wall - 4, (bx, wall)  # 当たったあと同じコマで数歩戻る
        m.held.difference_update({"UP", "DOWN"})
        row = (r[0x11] - 16) // 32
        if row < r[0x14]:
            m.held.add("UP")
        elif row > r[0x14] + height - 1:
            m.held.add("DOWN")
    assert seen_ball and first_hit is not None
    assert r[0x1C] < 42  # 残りのブロック
    score = list(r[0x26:0x2B])
    assert sum(score) > 0
    m.held.clear()
    m.brk = True
    for _ in range(10):
        app.frame()
    m.brk = False
    for _ in range(30):
        app.frame()
    assert m.cpu.pc < 0xC000
    assert list(m.mem[0xC5F6:0xC5FB]) == score  # 変数は退避先に残る
    app.close()


def test_export_basic_round_trip(tmp_path=None):
    """RAMのプログラムを.basに書き出し、打ち込み直すと同じ中間コードになる"""
    import tempfile

    from pc1251emu import basictext, programs
    from pc1251emu.app import export_program

    d = str(tmp_path or tempfile.mkdtemp())
    app = _app()
    m = app.m
    src = (
        '5 REM !"#$%&()*+,-./:;<=>?@^\n'
        "10 A=1E3:B$=CHR$ 65+STR$ (2):C=&1F:IF A>=1 AND B<>2 THEN 5\n"
        '999 IF A<=B LET D=-1.5E-2:PRINT USING "###";A:INPUT "X";X\n'
    )
    app.typer.add_mode("PRO")
    app.typer.add_text("NEW\n" + src)
    _settle(app)
    before = basictext.program_lines(m.mem)
    assert [n for n, _ in before] == [5, 10, 999]
    prog = programs.find("break")
    path = export_program(m, d, prog)
    assert path is not None and os.path.basename(path).startswith("break-")
    text = open(path, encoding="utf-8").read()
    assert "# hex: break.hex" in text
    assert "10 A=1E3:B$=CHR$ 65+STR$ (2):C=&1F:IF A>=1 AND B<>2 THEN 5" in text
    again = programs.load_program(path)
    assert again.blocks  # 組になっていたダンプも読まれる
    app.typer.add_mode("PRO")
    app.typer.add_text("NEW\n" + again.basic)
    _settle(app)
    assert basictext.program_lines(m.mem) == before
    app.typer.add_text("NEW\n")
    _settle(app)
    assert export_program(m, d) is None
    app.close()


def test_fast_typing_is_not_dropped():
    """パソコンのキーを速く打っても(1フレームで押して離す、前のキーを離す前に次を押す)取りこぼさない"""
    app = _app()
    app.set_mode("PRO")
    for _ in range(20):
        app.frame()
    ev = pygame.event.Event
    text = "ABCDEFGHJKLMN"
    for i, ch in enumerate(text):
        k = getattr(pygame, "K_" + ch.lower())
        app.handle(ev(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
        if i:  # 前のキーは、次のキーを押してから離す
            prev = getattr(pygame, "K_" + text[i - 1].lower())
            app.handle(ev(pygame.KEYUP, key=prev, mod=0, unicode="", scancode=0))
        for _ in range(3):  # 毎秒10打鍵
            app.frame()
    last = getattr(pygame, "K_" + text[-1].lower())
    app.handle(ev(pygame.KEYUP, key=last, mod=0, unicode="", scancode=0))
    for _ in range(60):
        app.frame()
    assert lcd_text(app.m).replace("?", " ").strip() == text, lcd_text(app.m)
    # ゆっくり長く押しても(0.3秒)、1字だけ入る
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_z, mod=0, unicode="", scancode=0))
    for _ in range(9):
        app.frame()
    app.handle(ev(pygame.KEYUP, key=pygame.K_z, mod=0, unicode="", scancode=0))
    for _ in range(30):
        app.frame()
    assert lcd_text(app.m).replace("?", " ").strip() == text + "Z", lcd_text(app.m)
    # Backspaceを続けて押しても(1秒に2〜3回)、押した数だけ消える
    for _ in range(4):
        app.handle(ev(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0, unicode="", scancode=0))
        app.handle(ev(pygame.KEYUP, key=pygame.K_BACKSPACE, mod=0, unicode="", scancode=0))
        for _ in range(12):
            app.frame()
    for _ in range(90):
        app.frame()
    assert lcd_text(app.m).replace("?", " ").strip() == (text + "Z")[:-4], lcd_text(app.m)
    # 連打しすぎた分は捨て、あとから遅れて流れてこない
    for ch in "QWERTYUIOPQWERTYUIOP":
        k = getattr(pygame, "K_" + ch.lower())
        app.handle(ev(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
        app.handle(ev(pygame.KEYUP, key=k, mod=0, unicode="", scancode=0))
        app.frame()
    for _ in range(30):  # 最後に押してから1秒
        app.frame()
    settled = lcd_text(app.m)
    assert not app.typer.busy
    for _ in range(60):
        app.frame()
    assert lcd_text(app.m) == settled
    app.close()


if __name__ == "__main__":
    test_app_types_and_computes()
    test_switch_knob_matches_label()
    test_shortcuts_and_popup()
    test_open_basic_and_hex_pair()
    test_samples_load()
    test_mogura_on_pc_interpreter()
    test_display_stays_on_while_computing()
    test_breakout_in_machine_code()
    test_export_basic_round_trip()
    test_fast_typing_is_not_dropped()
    print("ok")
