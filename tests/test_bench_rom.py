"""ROMのある本体で使うマシン語の作業欄(出し入れ、止める所、1命令ずつ、キーの行き先)"""

import pygame
import pytest
from helpers import make_app

from sc61box import app as appmod
from sc61box import benchview

ev = pygame.event.Event


def _ctrl(app, key):
    app.handle(ev(pygame.KEYDOWN, key=key, mod=pygame.KMOD_CTRL, unicode="", scancode=0))
    app.handle(ev(pygame.KEYUP, key=key, mod=pygame.KMOD_CTRL, unicode="", scancode=0))


def _rom_app(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(appmod, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [(1920, 1080)])
    return make_app(scale=0.5, **kw)


def _call(app, addr, frames=30):
    """RUNモードでCALL &addrと打って、framesフレーム動かす"""
    app.typer.add_text(f"CALL &{addr:04X}\n")
    for _ in range(frames):
        app.frame()
        if app.bench.state == "pause":
            break


def test_pane_toggles_and_is_remembered(tmp_path, monkeypatch):
    """ROMがあれば作業欄は初めはしまってあり、⌘Dか「表示・入力」のメニューで出し入れする。
    出したかどうかは次に起動したときも同じ"""
    app = _rom_app(tmp_path, monkeypatch)
    assert not app.norom and not app.pane_open and app.bench.rom
    narrow = app.window.get_width()
    _ctrl(app, pygame.K_d)
    assert app.pane_open and app.window.get_width() == narrow + benchview.PANE_W
    labels = [it.label for it in app.popup_items("view")]
    assert "マシン語の作業欄をしまう" in labels
    app.close()
    app = _rom_app(tmp_path, monkeypatch)
    assert app.pane_open
    app.toggle_pane(False)
    assert app.window.get_width() == narrow
    app.close()


def test_break_in_called_code(tmp_path, monkeypatch):
    """BASICのCALLで呼んだマシン語の止める所で止まり、しまってあった作業欄が出る。1命令ずつ
    進め、続けるとBASICに戻る"""
    app = _rom_app(tmp_path, monkeypatch)
    m, b = app.m, app.bench
    for i, v in enumerate(bytes.fromhex("027F10F8005237")):  # LIA 7F / LIDP F800 / STD / RTN
        m.write(0xC000 + i, v)
    b.toggle_break(0xC000)
    _call(app, 0xC000)
    assert b.state == "pause" and m.cpu.pc == 0xC000 and app.pane_open and app.halted
    app.bench_do("step")
    assert m.cpu.pc == 0xC002 and m.cpu.ram[2] == 0x7F
    app.bench_do("step")
    app.bench_do("step")
    assert m.mem[0xF800] == 0x7F
    app.bench_do("resume")
    for _ in range(20):
        app.frame()
    assert b.state == "run" and not app.halted and m.halted  # BASICの入力待ちに戻った
    app.close()


def test_break_and_step_over_in_rom(tmp_path, monkeypatch):
    """ROMの中にも止める所を置ける。ROMのルーチンを呼ぶCALLは「CALLごと」で飛び越せる
    (ROMがあるので、ROMの中身をそのまま実行する)"""
    app = _rom_app(tmp_path, monkeypatch)
    m, b = app.m, app.bench
    for i, v in enumerate(bytes.fromhex("FF4437")):  # CAL 1F44(キーを1回読む) / RTN
        m.write(0xC000 + i, v)
    assert b.toggle_break(0x1F44) is True
    _call(app, 0xC000)
    assert b.state == "pause" and m.cpu.pc == 0x1F44
    b.toggle_break(0x1F44)
    b.toggle_break(0xC000)
    app.bench_do("resume")
    for _ in range(20):
        app.frame()
    _call(app, 0xC000)
    assert b.state == "pause" and m.cpu.pc == 0xC000
    app.bench_do("over")
    for _ in range(5):
        app.frame()
    assert b.state == "pause" and m.cpu.pc == 0xC002 and "戻りました" in b.reason
    app.close()


def test_pause_is_one_state(tmp_path, monkeypatch):
    """ROMがあるときも、⌘Pの一時停止と作業欄の一時停止は同じ状態。作業欄を出せば、そこから
    続けられる。入力待ち(HALT)で止めたときは、1命令ずつは進めない"""
    app = _rom_app(tmp_path, monkeypatch)
    for _ in range(10):
        app.frame()
    _ctrl(app, pygame.K_p)
    assert app.halted and app.bench.state == "pause"
    cycles = app.m.cpu.cycles
    for _ in range(3):
        app.frame()
    assert app.m.cpu.cycles == cycles
    app.toggle_pane(True)
    assert app.m.halted  # ROMは入力待ち
    app.bench_do("step")
    assert app.m.cpu.cycles == cycles and "HALT" in app.bench.reason
    app.bench_do("go")
    assert not app.halted
    app.frame()
    assert app.m.cpu.cycles > cycles
    app.close()


def test_keys_go_where_clicked(tmp_path, monkeypatch):
    """作業欄をクリックするとキーは作業欄へ(ダンプを書く)、本体をクリックすると本体へ"""
    app = _rom_app(tmp_path, monkeypatch)
    app.toggle_pane(True)
    app.frame()
    v, b, m = app.bench_view, app.bench, app.m
    pane = (app.body_size[0] + 40, 400)
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=pane))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=pane))
    assert v.focus and app.pane_keys()
    b.go(0xC100)
    for ch in "3A":
        app.handle(ev(pygame.KEYDOWN, key=ord(ch.lower()), mod=0, unicode=ch, scancode=0))
    assert m.mem[0xC100] == 0x3A and not m.held
    body = (20, 20)
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=body))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=body))
    assert not v.focus and not app.pane_keys()
    app.handle(ev(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode="a", scancode=0))
    assert "A" in m.held or app.typer.queue
    app.close()


# C000 LIDP C100 / LDD / INCA / STD / RTN(C100を1増やして戻る)
INC_C100 = bytes.fromhex("10C10057425237")


def _stopped_before_write(app):
    m, b = app.m, app.bench
    assert b.state == "pause" and m.cpu.pc == 0xC000 and m.mem[0xC100] == 0


def test_break_when_loading_and_running(tmp_path, monkeypatch):
    """一覧から「読み込んで実行」したときも、止める所で止まる(読み込みを速く回している
    あいだも、止める所を調べる)。止まったときは、まだC100を書いていない"""
    from sc61box import programs

    src = tmp_path / "inc.hex"
    src.write_text("# run: CALL &C000\nC000 " + INC_C100.hex().upper() + "\n", "utf-8")
    app = _rom_app(tmp_path, monkeypatch)
    app.bench.toggle_break(0xC000)
    app.open_program(programs.load_program(str(src)), run=True)
    for _ in range(300):
        app.frame()
        if app.bench.state == "pause":
            break
    _stopped_before_write(app)
    app.close()


def test_break_when_pasting(tmp_path, monkeypatch):
    """貼り付けで打ったCALLでも、止める所で止まる"""
    app = _rom_app(tmp_path, monkeypatch)
    for i, v in enumerate(INC_C100):
        app.m.write(0xC000 + i, v)
    app.bench.toggle_break(0xC000)
    monkeypatch.setattr(app, "clipboard", lambda: "CALL &C000\n")
    app.paste()
    for _ in range(100):
        app.frame()
        if app.bench.state == "pause":
            break
    _stopped_before_write(app)
    app.close()


def test_pane_fits_screen(tmp_path, monkeypatch):
    """作業欄をあとから出しても、窓が画面の幅に入るように本体を縮める。しまえば元に戻る"""
    monkeypatch.setattr(appmod, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(pygame.display, "get_desktop_sizes", lambda: [(1280, 720)])
    app = make_app(scale=1.0)
    size = app.window.get_size()
    app.toggle_pane(True)
    assert app.window.get_width() <= 1280 - 80
    app.toggle_pane(False)
    assert app.window.get_size() == size
    app.close()


def test_stop_reason_in_rom(tmp_path, monkeypatch):
    """ROMがあれば、ROMの中の止める所で止まったときや1命令進めたときに、「ROMなしでは
    使えません」とは出さない"""
    app = _rom_app(tmp_path, monkeypatch)
    m, b = app.m, app.bench
    for i, v in enumerate(bytes.fromhex("FF4437")):
        m.write(0xC000 + i, v)
    b.toggle_break(0x1F44)
    _call(app, 0xC000)
    assert b.state == "pause" and m.cpu.pc == 0x1F44
    assert "ROMなし" not in b.reason and "止める所" in b.reason
    app.bench_do("step")
    assert b.state == "pause" and m.cpu.pc != 0x1F44 and "ROMなし" not in b.reason
    app.close()


def test_export_after_loading_with_rom(tmp_path, monkeypatch):
    """ROMのある本体で読み込んだダンプも、作業欄から書き出すと0のバイトを含めて全部が出る。
    「読み込む前に戻す」と、作業欄の覚えも読み込む前に戻る"""
    from sc61box import programs

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path / "out"))
    code = bytes.fromhex("79C020") + bytes(29) + bytes.fromhex("027F10F8005237")
    src = tmp_path / "jump.hex"
    lines = [f"{0xC000 + i:04X} {code[i : i + 8].hex().upper()}" for i in range(0, len(code), 8)]
    src.write_text("\n".join(lines) + "\n", "utf-8")
    app = _rom_app(tmp_path, monkeypatch)
    app.open_program(programs.load_program(str(src)))
    for _ in range(5):
        app.frame()
    b = app.bench
    assert b.start == 0xC000 and b.export_ranges() == [(0xC000, 0xC000 + len(code))]
    app.bench_export()
    out = next((tmp_path / "out").rglob("dump-*.hex"))
    blocks, errors = programs.parse_hex(out.read_text("utf-8"))
    got = {a + i: v for a, d in blocks for i, v in enumerate(d)}
    assert not errors and bytes(got[0xC000 + i] for i in range(len(code))) == code
    app.undo_loading()
    assert not b.export_ranges()
    app.close()


def test_loading_with_rom_clears_span(tmp_path, monkeypatch):
    """ROMのある本体でも、プログラムを読み込むと前に決めた書き出す範囲は消える。
    「読み込む前に戻す」と、決めた範囲も戻る"""
    from sc61box import programs

    src = tmp_path / "late.hex"
    src.write_text("# run: CALL &C100\nC100 37\n", "utf-8")
    app = _rom_app(tmp_path, monkeypatch)
    b = app.bench
    b.set_span(0xC000, 0xC007)
    app.open_program(programs.load_program(str(src)))
    for _ in range(5):
        app.frame()
    assert b.start == 0xC100 and b.span is None and b.export_ranges() == [(0xC100, 0xC101)]
    app.undo_loading()
    assert b.span == (0xC000, 0xC008)
    app.close()


JUMP_CODE = bytes.fromhex("79C020") + bytes(29) + bytes.fromhex("027F10F8005237")


def _hex_text(addr, data):
    return "".join(
        f"{addr + i:04X} {data[i : i + 8].hex().upper()}\n" for i in range(0, len(data), 8)
    )


def test_export_after_load_option(tmp_path, monkeypatch):
    """--loadで書いたダンプも、0のバイトを含めて書き出す範囲に入り、開始番地になる"""
    src = tmp_path / "jump.txt"
    src.write_text(_hex_text(0xC000, JUMP_CODE), "utf-8")
    app = _rom_app(tmp_path, monkeypatch, load=str(src), frames=0)
    for _ in range(app.boot_frames + 2):
        app.frame()
    assert app.m.mem[0xC020] == 0x02
    assert app.bench.start == 0xC000
    assert app.bench.export_ranges() == [(0xC000, 0xC000 + len(JUMP_CODE))]
    assert app.bench.export_summary() == f"C000〜C026({len(JUMP_CODE)}バイト)"
    app.close()


def test_cancelled_setup_does_not_mark(tmp_path, monkeypatch):
    """# setup:のあとに書くダンプは、実際に書いたときに書き出す範囲に入る。書く前に読み込みを
    やめれば入らない。最後まで読み込めば入る"""
    import os

    from sc61box import programs

    path = os.path.join(os.path.dirname(__file__), "..", "programs", "pc1261", "lc3.bas")
    prog = programs.load_program(path)
    app = _rom_app(tmp_path, monkeypatch, model="1261")
    app.open_program(prog)
    app.frame()
    app.cancel_loading()
    assert not any(lo <= 0x4000 < hi for lo, hi in app.bench.export_ranges())
    app.undo_loading()
    app.open_program(prog)
    for _ in range(600):
        app.frame()
        if not app.fast:
            break
    size = sum(len(d) for _a, d in prog.blocks)
    assert app.bench.export_ranges() == [(0x4000, 0x4000 + size)]
    app.close()


def test_export_line_in_pane(tmp_path, monkeypatch):
    """作業欄に書き出す範囲と合計のバイト数が出て、クリックすると書き出す"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path / "out"))
    app = _rom_app(tmp_path, monkeypatch)
    app.toggle_pane(True)
    app.bench.paste("C000 027F10F8005237")
    app.bench_view._ranges = ([], 0.0)
    app.frame()
    rect = next(r for r, kind, _a in app.bench_view.hits if kind == "export")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=rect.center))
    assert list((tmp_path / "out").rglob("dump-*.hex"))
    app.close()


@pytest.mark.parametrize("norom", [False, True])
@pytest.mark.parametrize("count", [1, 2, 3, 12])
def test_export_button_stays_in_pane(tmp_path, monkeypatch, norom, count):
    """書き出す範囲がいくつあっても、書き出しのボタンは作業欄の中の同じ場所にあり、押すと
    書き出す。範囲の説明は作業欄の幅に入る"""
    from sc61box import benchview

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path / "out"))
    app = _rom_app(tmp_path, monkeypatch, norom=norom, frames=2)
    app.toggle_pane(True)
    for k in range(count):
        app.bench.paste(_hex_text(0xC000 + 0x80 * k, JUMP_CODE))
    app.bench_view._ranges = ([], 0.0)
    app.frame()
    assert len(app.bench.export_ranges()) == count
    pane = pygame.Rect(app.body_size[0], 0, benchview.PANE_W, app.window.get_height())
    rect = next(r for r, kind, _a in app.bench_view.hits if kind == "export")
    assert pane.contains(rect) and rect.x == pane.x + 12
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=rect.center))
    assert list((tmp_path / "out").rglob("dump-*.hex"))
    app.close()


def test_export_notice_fits(tmp_path, monkeypatch):
    """範囲が多くても、書き出したときの知らせはファイルの名前とバイト数を先に出し、作業欄の
    下の2行に入る"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path / "out"))
    app = _rom_app(tmp_path, monkeypatch, norom=True, frames=2)
    for k in range(12):
        app.bench.paste(_hex_text(0xC000 + 0x80 * k, JUMP_CODE))
    app.bench_export()
    v = app.bench_view
    name = next((tmp_path / "out").rglob("dump-*.hex")).name
    assert v.flash.startswith(f"{name}を書き出しました({12 * len(JUMP_CODE)}バイト)")
    shown = []
    real = v._text

    def spy(dst, x, y, s, color=None, font=None):
        shown.append((y, s))
        return real(dst, x, y, s, color or (255, 255, 255), font)

    monkeypatch.setattr(v, "_text", spy)
    app.frame()
    height = app.window.get_height()
    notice = [(y, s) for y, s in shown if y >= height - 60]
    assert notice and all(y + 20 <= height for y, _s in notice)
    assert notice[0][1].startswith(name)
    app.close()


def test_unwritable_places_are_reported(tmp_path, monkeypatch):
    """プログラムの置き場所や状態の置き場所に同じ名前のファイルがあって作れなくても、
    書き出し・一覧・フォルダを開く・画面の保存・終了は止まらず、書けないことを知らせる"""
    blocker = tmp_path / "root-is-file"
    blocker.write_text("x", "utf-8")
    app = _rom_app(tmp_path, monkeypatch, norom=True, frames=2)
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(blocker))
    monkeypatch.setattr(appmod, "STATE_DIR", str(blocker))
    monkeypatch.setattr(app, "reveal", lambda path: None)
    app.bench.paste("C000 37")
    app.bench_view._ranges = ([], 0.0)
    app.frame()
    rect = next(r for r, kind, _a in app.bench_view.hits if kind == "export")
    app.handle(ev(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    app.handle(ev(pygame.MOUSEBUTTONUP, button=1, pos=rect.center))
    assert app.bench_view.flash.startswith("書き出せません")
    app.open_menu()
    app.frame()
    app.menu = None
    for it in app.popup_items("program"):
        if it.label == "置き場所のフォルダを開く" and it.action is not None:
            it.action()
    app.screenshot()
    assert app.status.startswith("画面の画像を保存できません")
    app.save_ram = True
    app.close()  # RAMを保存できなくても止まらない
    assert blocker.read_text("utf-8") == "x"


def test_loading_forgets_edits(tmp_path, monkeypatch):
    """ROMのある本体でも、プログラムを読み込むと、前の書き込みは取り消せなくなる
    (読み込んだプログラムを、前の書き込みを戻して壊さない)"""
    from sc61box import programs

    app = _rom_app(tmp_path, monkeypatch)
    b = app.bench
    b.paste("C000 AA")
    assert b.undos
    src = tmp_path / "rtn.hex"
    src.write_text("C000 37\n", "utf-8")
    app.open_program(programs.load_program(str(src)))
    for _ in range(5):
        app.frame()
    assert app.m.read(0xC000) == 0x37
    assert not b.undos and not b.redos
    assert b.undo() == "取り消せる書き込みはありません"
    assert app.m.read(0xC000) == 0x37
    app.close()
