"""ウィンドウを出さずにアプリを数十フレーム動かす"""

import os
import re
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

    # 本体の絵での、スイッチの溝のまんなかのxと、溝の中のyの範囲
    slots = {"1251": (1347, 88, 187), "1245": (1344, 81, 191)}
    for model, (cx, top, bottom) in slots.items():
        assets = display.asset_dir(model)
        lay = display.layout(model)
        x0, y0 = lay["switch_xy"]
        for mode, y in lay["switch_stops"]:
            im = Image.open(os.path.join(assets, f"switch_{mode}.png")).convert("L")
            col = im.crop((cx - x0 - 10, 0, cx - x0 + 10, im.height))
            rows = np.asarray(col, int).sum(axis=1).tolist()
            inside = range(top - y0, bottom - y0)  # 溝の中だけを見る
            ridge = y0 + max(inside, key=rows.__getitem__)
            assert abs(ridge - y) <= 8, (model, mode, ridge, y)


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
    assert app.turbo == 2
    key(pygame.K_t, pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
    key(pygame.K_t, pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
    assert app.turbo == 0.5
    key(pygame.K_t)
    assert app.turbo == 1
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
    assert app.popup is None and app.menu is not None  # プログラムの一覧が開く
    app.frame()
    titles = [p.title for p in app.menu["items"]]
    assert "文字のアニメーション(WAITの例)" in titles
    # 見えている行のうち、選んでいない、この機種で動くもの(置き場所の中身で並びが変わる)
    items = app.menu["items"]
    i, rect = next(
        (i, r)
        for i, r in app._menu_rows
        if i != app.menu["sel"] and items[i].runs_on(app.m.model.name)
    )
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))  # 選ぶ
    assert app.menu is not None and app.menu["sel"] == i and not app.typer.busy
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))  # もう一度で実行
    assert app.menu is None and app.typer.busy
    assert app.typer.queue or app.typer.cur  # RUNまで打つ
    app.close()


def test_menu_scrolls():
    """入りきらない一覧は、ホイールとPageDownで動き、選んでいる行は見える範囲に残る"""
    from pc1251emu import programs

    app = _app()
    items = programs.scan() * 3
    rows = app.MENU_ROWS
    assert len(items) > rows
    app.menu = {"items": items, "sel": 0, "top": 0}
    app.frame()
    app.handle(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-2, flipped=False))
    assert app.menu["top"] == 2 and app.menu["sel"] == 2
    app.frame()
    assert app._menu_rows[0][0] == 2
    app.handle(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-100, flipped=False))
    assert app.menu["top"] == len(items) - rows
    app.handle(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=100, flipped=False))
    assert app.menu["top"] == 0 and app.menu["sel"] == rows - 1  # 見える範囲の下端に残る
    app.menu["sel"] = 0
    app.handle(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEDOWN, mod=0, unicode="", scancode=0)
    )
    assert app.menu["sel"] == rows and app.menu["top"] == 1
    app.frame()
    app.close()


def test_run_list_keys():
    """一覧はEnterで読み込んで実行し、Shift+Enterでは読み込むだけ。Rで読み直せる"""
    from pc1251emu import basictext

    app = _app()
    ev = pygame.event.Event

    def key(k, mod=0):
        app.handle(ev(pygame.KEYDOWN, key=k, mod=mod, unicode="", scancode=0))

    app.open_menu()
    key(pygame.K_r)
    assert app.menu is not None
    app.frame()
    app.menu["sel"] = next(i for i, p in enumerate(app.menu["items"]) if p.name == "primes")
    key(pygame.K_RETURN)
    assert app.menu is None
    while app.typer.busy:
        app.frame()
    shown = set()
    for _ in range(120):
        app.frame()
        shown.add(lcd_text(app.m).strip())
    assert any(t[:1].isdigit() for t in shown), shown  # 素数を出している
    # Shift+Enterは読み込むだけ(プログラムは入るが、動かさない)
    app.typer.add_text("NEW\n")
    _settle(app)
    app.open_menu()
    app.menu["sel"] = next(i for i, p in enumerate(app.menu["items"]) if p.name == "primes")
    key(pygame.K_RETURN, pygame.KMOD_SHIFT)
    _settle(app)
    shown = set()
    for _ in range(120):
        app.frame()
        shown.add(lcd_text(app.m).strip())
    assert basictext.program_lines(app.m.mem)
    assert not any(t[:1].isdigit() for t in shown), shown  # 動いていない
    app.close()


def _app(model="1251"):
    args = types.SimpleNamespace(
        scale=1.0, type=None, load=None, fresh=True, mute=True, persist=1.0, model=model
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
    assert {p.name for p in items} >= {"anime", "primes", "mogura"}
    app = _app()
    for prog in items:
        assert not prog.errors, prog.errors
        if not prog.runs_on("1251"):  # PC-1245用は読み込まないので、LISTでは確かめられない
            continue
        app.open_program(prog)
        _settle(app)
        app.m.brk = True  # 読み込むと動き出す見本(anime)を止めてからLISTする
        for _ in range(10):
            app.frame()
        app.m.brk = False
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
    assert prog is not None
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


BALL2 = 0xBF84  # break.asmの2個目の玉


def _play_breakout(level: str, height: int, model: str = "1251") -> None:
    from pc1251emu import programs

    app = _app(model)
    m = app.m
    r = m.cpu.ram
    prog = programs.find("break", model)
    assert prog is not None and not prog.errors and prog.runs_on(model)
    start, field = (0xC000, 90) if model == "1251" else (0xC100, 75)
    app.open_program(prog, run=True)
    while app.typer.busy:
        app.frame()
    for _ in range(20):
        app.frame()
    assert "EASY" in lcd_text(m).replace("?", " "), lcd_text(m)
    app.typer.add_text(level)  # INPUTに難易度を答える。問いも答えも液晶に収まる
    while app.typer.busy:
        app.frame()
    for _ in range(5):
        app.frame()
    text = lcd_text(m)
    assert text.startswith("1") and level in text.split("NORMAL")[1], text
    app.typer.add_text("\n")
    while app.typer.busy:
        app.frame()
    for _ in range(90):
        app.frame()

    def column(x):  # 液晶の左からx列目の点(ビット0が上)
        return m.mem[0xF800 + x] if x < 60 else m.mem[0xF87B - (x - 60)]

    assert m.cpu.pc >= start and m.display_on()
    assert r[0x15] == height and bin(column(0)).count("1") == height  # パドルの高さ
    assert [column(field + i) for i in range(5)] == [0x1C, 0, 0x1C, 0, 0x1C]  # 残りの玉
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
        # パドルと壁のあいだに見えるのは玉の1点だけ。ただし画面を書き直している途中で
        # フレームが切れると、前の位置と新しい位置の2点がすぐ近くに見えることがある
        lit = [x for x in range(2, wall - 1) for _ in range(bin(column(x)).count("1"))]
        dots = len(lit)
        if model == "1251" and m.mem[BALL2] != 0xFF:  # 点滅するブロックを壊して2個になった
            assert dots <= 4, lit
        else:
            assert dots <= 1 or (dots == 2 and lit[1] - lit[0] <= 3), lit
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


def _start_breakout(app, level="2", model="1251"):
    from pc1251emu import programs

    app.open_program(programs.find("break", model), run=True)
    while app.typer.busy:
        app.frame()
    for _ in range(20):
        app.frame()
    app.typer.add_text(level + "\n")
    while app.typer.busy:
        app.frame()
    for _ in range(60):
        app.frame()


def _hex_rows(path):
    """.hexの各行の(番地, 注釈)。注釈には逆アセンブルした命令と、ラベルや説明が入っている"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            body, _, note = line.partition(";")
            words = body.split()
            if words and len(words[0]) == 4:
                rows.append((int(words[0], 16), note.strip()))
    return rows


def _hex_path(model, name):
    return os.path.join(os.path.dirname(__file__), "..", "programs", f"pc{model}", name)


def _break_label(model, name):
    rows = _hex_rows(_hex_path(model, "break.hex"))
    return next(a for a, note in rows if re.search(rf"(^|\s){name}:", note))


def _to_play(m, model="1251"):
    """遊んでいるあいだのフレームの頭(PLAY)まで進める。玉を入れ替えている途中で
    内部RAMを書き換えないように、玉を置き直す前に呼ぶ"""
    play = _break_label(model, "PLAY")
    for _ in range(100_000):
        if m.cpu.pc == play:
            return
        m.cpu.step()
    raise AssertionError("PLAYに来ない")


def test_model_folders(tmp_path, monkeypatch):
    """置き場所の直下はどの機種でも、pc1251/・pc1245/はその機種用。同じ名前でも別に並ぶ"""
    from pc1251emu import programs

    (tmp_path / "pc1245").mkdir()
    (tmp_path / "pc1251").mkdir()
    (tmp_path / "both.bas").write_text("10 PRINT 1\n", encoding="utf-8")
    (tmp_path / "pc1251" / "game.bas").write_text("# title: GAME\n10 PRINT 51\n", encoding="utf-8")
    (tmp_path / "pc1245" / "game.bas").write_text("# title: GAME\n10 PRINT 45\n", encoding="utf-8")
    (tmp_path / "pc1245" / "code.hex").write_text("C100 00\n", encoding="utf-8")
    (tmp_path / "pc1245" / "uses.bas").write_text(
        "# hex: code.hex\n10 CALL &C100\n", encoding="utf-8"
    )
    monkeypatch.setenv("PC1251_PROGRAMS", str(tmp_path))
    items = programs.scan([str(tmp_path)])
    assert sorted((p.name, p.model) for p in items) == [
        ("both", ""),
        ("game", "1245"),
        ("game", "1251"),
        ("uses", "1245"),
    ]
    for model in ("1251", "1245"):
        games = [p for p in programs.for_model(items, model) if p.title == "GAME"]
        assert [p.model for p in games] == [model]
        found = programs.find("game", model)
        assert found is not None and found.basic == f"10 PRINT {model[2:]}\n"
    other = programs.find("uses", "1251")
    assert other is not None and not other.runs_on("1251")  # pc1245/のものはPC-1245用
    uses = programs.find("uses", "1245")
    assert uses is not None
    assert uses.blocks == [(0xC100, b"\x00")] and not uses.errors


def test_helper_dumps_hidden(tmp_path):
    """# hex:や# after:で使われるだけのダンプは一覧に出さず、大きさは使う側に出る"""
    from pc1251emu import programs

    (tmp_path / "game.bas").write_text("# after: game-ml.hex\n10 DIM A$(9)\n", encoding="utf-8")
    (tmp_path / "game-ml.hex").write_text("C530 00 01 02\n", encoding="utf-8")
    (tmp_path / "solo.hex").write_text("C100 00\n", encoding="utf-8")
    items = programs.scan([str(tmp_path)])
    assert sorted(p.name for p in items) == ["game", "solo"]
    game = next(p for p in items if p.name == "game")
    assert game.kinds == "BASIC+HEX" and game.size == 3
    here = os.path.join(os.path.dirname(__file__), "..", "programs")
    names = {p.name for p in programs.scan([here])}
    assert {"pcint", "mogura"} <= names  # BASICと組のダンプは、ほかから使われていても出る


def test_yasm_dump():
    """YASM61860の16進ダンプ(dumpoutの出力)をそのまま.hexとして読める。
    行の途中から始まる所は、番地を8の倍数に切り下げ、手前を1バイト3文字の空白で埋めている"""
    from pc1251emu import programs

    # ORG &C103に01〜0B、ORG &C200にAA BBを置いたときの出力
    text = "\n\nc100 :          01 02 03 04 05 : 0f\nc108 : 06 07 08 09 0a 0b \n\nc200 : aa bb "
    blocks, errors = programs.parse_hex(text)
    assert not errors
    assert blocks == [
        (0xC103, bytes([1, 2, 3, 4, 5])),
        (0xC108, bytes(range(6, 12))),
        (0xC200, bytes([0xAA, 0xBB])),
    ]
    # 記事の形(番地のあとに空白、行末に「:チェックサム」)は今までどおり
    assert programs.parse_hex("C200 04F1F9:EE\nC208: 01 02")[0] == [
        (0xC200, bytes([0x04, 0xF1, 0xF9])),
        (0xC208, bytes([1, 2])),
    ]


def test_bin_link(tmp_path):
    """# bin: で.binを番地を添えて読み込む。# after: でも使える。番地がなければエラー"""
    from pc1251emu import programs
    from pc1251emu.app import export_program

    (tmp_path / "code.bin").write_bytes(bytes([0x12, 0x34, 0x56]))
    (tmp_path / "late.bin").write_bytes(bytes([0x9A]))
    (tmp_path / "game.bas").write_text(
        "# bin: code.bin &C300\n# after: late.bin 0xC400\n10 CALL &C300\n", encoding="utf-8"
    )
    (tmp_path / "noaddr.bas").write_text("# bin: code.bin\n10 END\n", encoding="utf-8")
    (tmp_path / "over.bas").write_text("# bin: code.bin &FFFE\n10 END\n", encoding="utf-8")
    items = programs.scan([str(tmp_path)])
    assert sorted(p.name for p in items) == ["game", "noaddr", "over"]  # .binは一覧に出ない
    game = next(p for p in items if p.name == "game")
    assert not game.errors
    assert game.blocks == [(0xC300, bytes([0x12, 0x34, 0x56]))]
    assert game.after == [(0xC400, bytes([0x9A]))]
    assert game.kinds == "BASIC+HEX" and game.size == 4
    noaddr = next(p for p in items if p.name == "noaddr")
    assert not noaddr.blocks and any("番地がない" in e for e in noaddr.errors)
    over = next(p for p in items if p.name == "over")
    assert not over.blocks and any("&FFFFを越える" in e for e in over.errors)

    # 読み込んで動かすと、RAMに書かれる
    app = _app("1251")
    app.open_program(game, run=False)
    _settle(app)
    assert bytes(app.m.mem[0xC300:0xC303]) == bytes([0x12, 0x34, 0x56])
    # BASICを書き出すと、# bin:・# after:もそのまま残る
    path = export_program(app.m, str(tmp_path / "out"), game)
    assert path is not None
    text = open(path, encoding="utf-8").read()
    assert "# bin: code.bin &C300" in text and "# after: late.bin &C400" in text


def test_ball_runs():
    """弾むボールは、どちらの機種でもボールが文字の区切りをまたがずに液晶の全幅を
    弾んで進み、BRKでBASICへ戻る"""
    from pc1251emu import programs

    for model, org in (("1251", 0xC000), ("1245", 0xC100)):
        app = _app(model)
        m = app.m
        prog = programs.find("ball", model)
        assert prog is not None
        app.open_program(prog, run=True)
        while app.typer.busy:
            app.frame()
        frames = set()
        visited = set()
        for _ in range(600):
            app.frame()
            cols = m.columns()
            frames.add(tuple(cols))
            cells = {i // 5 for i, c in enumerate(cols) if c}
            assert len(cells) <= 1, (model, sorted(cells))  # 区切りをまたがない
            visited |= cells
        assert max(visited) == len(m.columns()) // 5 - 1, (
            model,
            sorted(visited),
        )  # 右端の桁まで行く
        assert len(frames) > 10, model  # 絵を替えながら右へ進む
        squash = (0x40, 0x60, 0x60, 0x60, 0x40)
        assert any(f[i : i + 5] == squash for f in frames for i in range(0, len(f), 5)), (
            model
        )  # 地面でひしゃげる
        for shape in ((0x38, 0x7C, 0x38, 0, 0), (0, 0, 0x1C, 0x3E, 0x1C)):
            assert any(f[i : i + 5] == shape for f in frames for i in range(0, len(f), 5)), (
                model,
                shape,
            )  # 着地の前後の縦長は左右に寄せて、斜めに出入りする
        m.brk = True
        for _ in range(10):
            app.frame()
        m.brk = False
        for _ in range(10):
            app.frame()
        assert not org <= m.cpu.pc < org + 0x100, (model, hex(m.cpu.pc))  # マシン語から戻った
        app.close()


def test_scroll_runs():
    """文字を流すマシン語は、液晶の全幅を1コマで1列ずつずらして写し、BRKでBASICへ戻る"""
    from pc1251emu import programs

    for model, org in (("1251", 0xC000), ("1245", 0xC100)):
        rows = _hex_rows(_hex_path(model, "scroll.hex"))
        waitf = next(a for a, note in rows if note.startswith("WAIT FA"))  # 写し終えて待つところ
        after = next(a for a, note in rows if a > waitf and note.startswith("TEST 08"))
        app = _app(model)
        m = app.m
        prog = programs.find("scroll", model)
        assert prog is not None
        app.open_program(prog, run=True)
        while app.typer.busy:
            app.frame()
        for _ in range(10):
            app.frame()
        seen = []
        for _ in range(30):  # 1コマずつ、写し終えたところの液晶を見る
            for _ in range(100000):
                if m.cpu.pc == waitf:
                    break
                m.cpu.step()
            seen.append(tuple(m.columns()))
            while m.cpu.pc != after:
                m.cpu.step()
        assert len(seen[-1]) == (120 if model == "1251" else 80), model
        assert any(seen[-1][60:]), model  # 右半分にも写す
        for a, b in zip(seen, seen[1:], strict=False):
            assert b[:-1] == a[1:], model  # 1列ずつ左へずれる
        assert len(set(seen)) > 20, model
        m.brk = True
        for _ in range(10):
            app.frame()
        m.brk = False
        for _ in range(10):
            app.frame()
        assert not org <= m.cpu.pc < org + 0x200, (model, hex(m.cpu.pc))  # マシン語から戻った
        app.close()


def test_breakout_every_row():
    """どの段のブロックも壊せて、玉もその段に描かれる(表の引き方を間違えると上の段だけ壊れない)"""
    for model in ("1251", "1245"):
        app = _app(model)
        m = app.m
        r = m.cpu.ram
        _start_breakout(app, model=model)
        m.held.add("SPC")
        for _ in range(3):
            app.frame()
        m.held.clear()
        for row in range(7):
            wall = r[0x16]
            r[0x20:0x26] = bytes([0x7F] * 6)
            r[0x1C] = 42
            _to_play(m, model)
            r[0x10:0x14] = bytes([wall - 3, 32 * row + 36, 1, 4])
            for _ in range(4):
                app.frame()
                if r[0x20] != 0x7F:
                    break
            assert r[0x20] == 0x7F & ~(1 << row), (model, row, hex(r[0x20]))
        _to_play(m, model)
        r[0x10:0x14] = bytes([20, 36, 1, 0])  # 一番上の段を横に進む玉
        app.frame()
        app.frame()
        _to_play(m, model)  # フレームの途中だと、玉の位置は進んでいても描く前のことがある
        x = r[0x10]
        column = m.mem[0xF800 + x]
        assert column & 1 and not column & 0x7E, (model, x, hex(column))
        app.close()


def test_breakout_second_ball():
    """PC-1251版: 点滅するブロックを壊すと玉が2個になり、片方を落としても玉は減らない"""
    app = _app()
    m = app.m
    r = m.cpu.ram
    _start_breakout(app)

    def column(x):
        return m.mem[0xF800 + x] if x < 60 else m.mem[0xF87B - (x - 60)]

    wall = r[0x16]
    assert (r[0x2E], r[0x2F]) == (0x21, 8)  # 1面は2本目の4段目
    seen = set()
    for _ in range(16):
        app.frame()
        seen.add(column(wall + 6) & 8)
    assert seen == {0, 8}  # 点滅している
    m.held.add("SPC")
    for _ in range(3):
        app.frame()
    m.held.clear()
    _to_play(m)
    r[0x20] = 0  # 1本目をなくし、玉を2本目の4段目へ向ける
    r[0x1C] = 35
    r[0x10:0x14] = bytes([wall + 2, 4 * 32, 1, 4])
    for _ in range(10):
        app.frame()
    assert r[0x2E] == 0 and m.mem[BALL2] != 0xFF
    most = 0
    for _ in range(30):  # 壁の手前に2個とも見えるときがある
        app.frame()
        most = max(most, len([x for x in range(2, r[0x16] - 1) if column(x)]))
    assert most >= 2
    lives = r[0x18]
    _to_play(m)
    m.mem[BALL2 : BALL2 + 4] = bytes([20, 100, 1, 4])  # 2個目は空いたところを右へ
    r[0x10:0x14] = bytes([2, 7 * 32, 0xFF, 4])  # 1個目をパドルの下へ落とす
    r[0x14] = 0
    for _ in range(10):
        app.frame()
    assert r[0x18] == lives and r[0x10] != 0xFF and m.mem[BALL2] == 0xFF
    app.close()


def test_grid_disappears_when_power_is_off():
    """消灯ドットの薄い格子は電源が入っているときだけ見え、OFFにすると消える"""
    app = _app()
    for _ in range(30):
        app.frame()
    assert app.m.power and app.panel.grid_level > 0.9
    app.set_switch_from(dict(app.sw_stops)["OFF"])
    for _ in range(60):
        app.frame()
    assert not app.m.power and app.panel.grid_level == 0.0
    app.close()


def test_sound_has_no_gaps_between_frames():
    """1フレーム(CLOCK/30サイクル)ずつ音を作っても、1秒でちょうどRATE個の標本になる"""
    from pc1251emu.audio import RATE, Buzzer
    from pc1251emu.machine import CLOCK

    b = Buzzer()
    per = CLOCK // 30
    events = [(t, 5 if (t // 48) % 2 else 4) for t in range(0, CLOCK, 48)]  # 2kHz
    n = 0
    for c in range(0, CLOCK, per):
        n += len(b.render([e for e in events if c <= e[0] < c + per], c, c + per)) // 2
    assert abs(n - RATE) <= 1


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
    assert os.path.basename(os.path.dirname(path)) == "pc1251"  # 機種用のフォルダに書く
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
    test_grid_disappears_when_power_is_off()
    test_sound_has_no_gaps_between_frames()
    test_export_basic_round_trip()
    test_fast_typing_is_not_dropped()
    print("ok")


def test_arrows_as_numpad():
    """⌘K(Ctrl+K)で矢印キーが数字キーの8・2・4・6になり、もう一度で戻る"""
    app = _app()
    ev = pygame.event.Event
    app.key_down(ev(pygame.KEYDOWN, key=pygame.K_k, mod=pygame.KMOD_CTRL))
    assert app.numpad_arrows
    for key, name in ((pygame.K_UP, "8"), (pygame.K_LEFT, "4")):
        app.key_down(ev(pygame.KEYDOWN, key=key, mod=0))
        assert app.typer.queue[-1][2:] == [name]
        app.key_up(ev(pygame.KEYUP, key=key, mod=0))
        assert name not in app.typer.physical
    app.key_down(ev(pygame.KEYDOWN, key=pygame.K_F7, mod=0))
    assert not app.numpad_arrows
    app.key_down(ev(pygame.KEYDOWN, key=pygame.K_DOWN, mod=0))
    assert app.typer.queue[-1][2:] == ["DOWN"]
    app.close()


def test_symbol_shadow_cleared():
    """表示記号の影は記号が消えると残らない(影のはみ出す下の段も毎フレーム貼り直す)"""
    from pc1251emu import display

    app = _app()
    p = app.panel
    x0, y0 = p.mat_x, p.ann_y
    box = pygame.Rect(x0, y0, p.mat_w, p.mat_y - 4 - y0)  # ドットの面の上まで
    off = p.draw([0] * p.w, set(), True, "RUN")
    for _ in range(30):
        off = p.draw([0] * p.w, set(), True, "RUN")
    before = pygame.image.tobytes(off.subsurface(box.move(display.MARGIN, display.MARGIN)), "RGB")
    for _ in range(30):
        p.draw([0] * p.w, set(p.symbols), True, "RUN")
    for _ in range(60):
        off = p.draw([0] * p.w, set(), True, "RUN")
    after = pygame.image.tobytes(off.subsurface(box.move(display.MARGIN, display.MARGIN)), "RGB")
    assert before == after
    app.close()


def test_power_on_is_silent():
    """スイッチを入れてもブザーは鳴らない(RESETが見えないので、ROMは検査用の道に入らない)"""
    app = _app()
    m = app.m
    stops = dict(app.sw_stops)
    app.set_switch_from(stops["OFF"])
    for _ in range(30):
        app.frame()
    m.sound_events.clear()
    app.set_switch_from(stops["RUN"])
    events = []
    for _ in range(45):
        events += m.sound_events
        app.frame()
    events += m.sound_events
    assert m.power and not events, events
    app.close()


def test_help_closes_on_input():
    """最初に出るキーの説明は、キーを押すかクリックすると消える。⌘/では出し入れできる"""
    ev = pygame.event.Event
    app = _app()
    app.help = 100
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode="a", scancode=0))
    assert app.help == 0
    app.help = 100
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5)))
    assert app.help == 0
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_SLASH, mod=pygame.KMOD_CTRL, unicode="", scancode=0))
    assert app.help > 0
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_SLASH, mod=pygame.KMOD_CTRL, unicode="", scancode=0))
    assert app.help == 0
    app.close()


def test_power_on_pcm_is_quiet():
    """起動したときと、スイッチを切って入れ直したときに、作った音の標本がほぼ0のまま"""
    from array import array

    app = _app()  # 起動の最初のフレームから録る
    pcm = []
    app.sound = object()
    app.feed_sound = pcm.append  # pyrefly: ignore[bad-assignment]
    stops = dict(app.sw_stops)

    def frames(n):
        for _ in range(n):
            app.frame()

    app.buzzer = type(app.buzzer)()
    frames(40)
    app.set_switch_from(stops["OFF"])
    frames(30)
    app.set_switch_from(stops["RUN"])
    frames(45)
    peak = max((max(map(abs, array("h", p))) for p in pcm if p), default=0)
    assert peak < 100, peak
    app.close()


def test_sound_at_other_speeds():
    """1倍以外でも音が出る。標本の数は実時間ぶんのまま、音の高さが倍率だけ変わる"""
    from array import array
    from itertools import pairwise

    from pc1251emu.app import FPS
    from pc1251emu.audio import RATE

    for speed in (2, 0.5):
        app = _app()
        app.typer.add_text("BEEP 3")
        _settle(app, 200)
        pcm = []
        app.sound = object()
        app.feed_sound = pcm.append  # pyrefly: ignore[bad-assignment]
        app.turbo = speed
        app.m.held.add("ENTER")
        for _ in range(4):
            app.frame()
        app.m.held.clear()
        for _ in range(30):
            app.frame()
        assert len(pcm) == 34
        sound = [array("h", p) for p in pcm if p]
        assert sound, speed
        # 1フレームごとの数は命令の切れ目で少し揺れるので、合計で比べる
        total = sum(map(len, sound))
        assert abs(total / (len(sound) * RATE / FPS) - 1) < 0.02, (speed, total)

        # 鳴りっぱなしのフレームで、符号の変わり目から高さを数える(BEEPは4kHz)
        def sounding(a):
            return all(max(map(abs, a[i : i + 40])) > 1000 for i in range(0, len(a) - 40, 40))

        loud = [a for a in sound if sounding(a)]
        assert loud, speed
        crossings = sum(sum(1 for x, y in pairwise(a) if (x < 0) != (y < 0)) for a in loud)
        hz = crossings / 2 / (sum(map(len, loud)) / RATE)
        assert abs(hz / (4000 * speed) - 1) < 0.1, (speed, hz)
        app.close()


def test_tape_round_trip(tmp_path):
    """プログラムをROMのCSAVEでwavにし、別のエミュレータでCLOAD・CLOAD Mして元と同じになる"""
    from pc1251emu import basictext, programs, tape
    from pc1251emu.machine import CLOCK, PC1251

    prog = programs.find("break", "1251")
    assert prog is not None
    files = tape.program_wavs(prog, "1251", str(tmp_path))
    assert [os.path.basename(p) for p, _ in files] == ["break.wav", "break-m.wav"]
    assert [c for _, c in files] == ['CLOAD "BREAK"', 'CLOAD M "BREAK"']
    m = PC1251()
    m.run(CLOCK)
    for path, command in files:
        m.tape = tape.TapeIn(path)
        tape._type(m, command + "\n")
        while not m.tape.done(m.cpu.cycles):
            m.run(CLOCK)
        m.run(CLOCK)
    loaded = basictext.program_text(m.mem)
    assert loaded.replace(" ", "") == prog.basic.replace(" ", "")  # 空白は書き出しの都合で違う
    for addr, data in prog.blocks:
        assert bytes(m.mem[addr : addr + len(data)]) == data, hex(addr)


def test_csave_writes_wav(tmp_path, monkeypatch):
    """画面でCSAVEすると、置き場所にwavができ、別のエミュレータでCLOADすると元に戻る。
    BEEPの音はwavにしない"""
    from pc1251emu import basictext, tape
    from pc1251emu.machine import CLOCK, PC1251

    monkeypatch.setenv("PC1251_PROGRAMS", str(tmp_path))
    app = _app()
    app.turbo = 8
    app.typer.add_text("BEEP 3\n")
    _settle(app)
    for _ in range(120):
        app.frame()
    assert not list(tmp_path.glob("*.wav"))  # BEEPはテープの音ではない
    app.typer.add_mode("PRO")
    app.typer.add_text('NEW\n10 PRINT "HI"\n20 END\n')
    app.typer.add_mode("RUN")
    app.typer.add_text('CSAVE "HI"\n')
    _settle(app)
    for _ in range(600):
        app.frame()
        if list(tmp_path.glob("tape-*.wav")):
            break
    wavs = list(tmp_path.glob("tape-*.wav"))
    assert len(wavs) == 1, wavs
    app.close()
    m = PC1251()
    m.run(CLOCK)
    m.tape = tape.TapeIn(str(wavs[0]))
    tape._type(m, 'CLOAD "HI"\n')
    while not m.tape.done(m.cpu.cycles):
        m.run(CLOCK)
    m.run(CLOCK)
    assert basictext.program_text(m.mem).replace(" ", "") == '10PRINT"HI"\n20END\n'


def test_timer_flags():
    """TESTのタイマの印は2msごと・512msごとに立ち、読むと消える。置いておくと約11分で電源が切れる"""
    from pc1251emu.machine import CLOCK, PC1251, TICK_2MS

    m = PC1251()
    m.run(CLOCK)
    m.halted = True  # ROMに読まれないよう、時間だけ進める
    m.t2ms = m.t512 = 0
    m.t2, m.t512cnt = TICK_2MS - 1, 254
    m.run(1)  # 2ms(255回目)。512msはまだ
    assert m.test(0x03) == 0x02 and m.test(0x02) == 0  # 2回目は消えている
    m.halted = True
    m.t2 = TICK_2MS - 1
    m.run(1)  # 256回目で512ms
    assert m.test(0x01) == 0x01 and m.test(0x01) == 0
    m = PC1251()
    seconds = 0
    while m.power and seconds < 900:
        m.run(CLOCK)
        seconds += 1
    assert 600 < seconds < 720, seconds


def test_version():
    """--versionでpyproject.tomlの版を出して終わる"""
    from typer.testing import CliRunner

    from pc1251emu.app import app_cli

    with open(
        os.path.join(os.path.dirname(__file__), "..", "pyproject.toml"), encoding="utf-8"
    ) as f:
        found = re.search(r'^version = "(.+)"', f.read(), re.M)
    assert found is not None
    want = found.group(1)
    result = CliRunner().invoke(app_cli, ["--version"])
    assert result.exit_code == 0 and result.output.strip() == f"pc1251-emu {want}"


def test_lcd_ram_mirrors():
    """液晶RAM(F800-F8FF)は、F900-FFFFの各256バイトにも見える。PC-1245ではE800-EFFFにも"""
    from pc1251emu.machine import PC1251

    for model in ("1251", "1245"):
        m = PC1251(cpu_rom=bytes(0x2000), bas_rom=bytes(0x4000), model=model)
        for page in (0xF900, 0xFF00, 0xE800, 0xEF00):
            m.write(page + 0x23, 0x5A)
            mirrored = page >= 0xF900 or model == "1245"
            assert (m.read(0xF823) == 0x5A) == mirrored, (model, hex(page))
            assert (m.read(page + 0x23) == 0x5A) == mirrored, (model, hex(page))
            m.write(0xF823, 0)
        assert m.read(0xE7FF) == 0 and m.read(0xF000) == 0


def _queue_run(fps: float, clock: float, jitter_ms: float, seconds: float = 60) -> tuple[int, int]:
    """SoundQueueに、フレームごとに標本を積み、音の装置が512標本ずつ取っていく様子をまねる。
    fpsは実際のフレームの速さ、clockは装置の時計の速さの比。音が切れた回数と、
    フレームの音を捨てた回数を返す"""
    import random

    from pc1251emu import audio

    class FakeSDL:
        def __init__(self):
            self.queued = 0  # バイト

        def SDL_GetQueuedAudioSize(self, dev):
            return self.queued

        def SDL_QueueAudio(self, dev, data, n):
            self.queued += n

    q = object.__new__(audio.SoundQueue)
    q.sdl, q.dev, q.underruns, q.started = FakeSDL(), 1, 0, False  # pyrefly: ignore
    rnd = random.Random(1)
    t_frame, t_dev, gaps, dropped = 0.0, 0.0, 0, 0
    step = 512 / (audio.RATE * clock)
    while t_frame < seconds:
        while t_dev <= t_frame:  # 装置が取る
            need = 512 * 2
            if q.sdl.queued < need and t_dev > 1:
                gaps += 1
            q.sdl.queued = max(0, q.sdl.queued - need)
            t_dev += step
        n = round(audio.FRAME_SAMPLES * audio.speed_adjust(q.level()))  # 進めたサイクルに比例
        before = q.sdl.queued
        q.push(bytes(2 * n))
        dropped += q.sdl.queued == before and t_frame > 1
        dt = 1 / fps + rnd.gauss(0, jitter_ms / 1000)
        if rnd.random() < 0.01:
            dt += 0.04  # ときどき40ms遅れるフレーム
        t_frame += max(0.0, dt)
    return gaps, dropped


def test_sound_queue_keeps_up():
    """フレームの速さが揺れたり、ときどき40ms遅れたり、音の装置の時計とずれたりしても、
    待ち行列が尽きず、あふれもしない(以前のmixer.Channelのやり方では何十回も途切れた)"""
    for fps in (29.9, 30.0, 30.3):
        for clock in (0.995, 1.0, 1.005):
            gaps, dropped = _queue_run(fps, clock, jitter_ms=2)
            assert (gaps, dropped) == (0, 0), (fps, clock, gaps, dropped)
