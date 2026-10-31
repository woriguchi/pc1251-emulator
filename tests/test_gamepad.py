"""ゲームパッドの割り当て(gamepad.PadMap)と、イベントから本体のキーへの変換、割り当ての画面"""

import os
from unittest.mock import patch

import pygame
import pytest
from helpers import make_app, settle

from sc61box import display, gamepad, programs
from sc61box.app import BAR_H

WIDE = [(1920, 1080)]  # 本体を縮めずに欄を出せる画面


def test_pad_map_text_roundtrip():
    m, bad = gamepad.PadMap.parse("dpup=8 dpdown=2 a=SPC b=0 start=ENTER", "test")
    assert not bad and m.get("a") == "SPC" and m.get("x") is None
    again, bad = gamepad.PadMap.parse(m.text())
    assert not bad and again.keys == m.keys
    assert m.text().startswith("dpup=8 dpdown=2 ")  # ORDERの順


def test_pad_map_parse_reports_bad_words():
    m, bad = gamepad.PadMap.parse("a=SPC z=1 b=NOSUCHKEY c, dpleft=4")
    assert bad == ["z=1", "b=NOSUCHKEY", "c,"]
    assert m.keys == {"a": "SPC", "dpleft": "4"}


def test_pad_map_comma_key_roundtrip():
    """PC-1350の「,」のキーを割り当てた行も読み戻せる(区切りは空白だけ)"""
    names = gamepad.key_names("1350")
    m = gamepad.PadMap({"dpup": "8", "a": ",", "b": ";", "x": "=", "y": "("})
    assert m.text() == "dpup=8 a=, b=; x== y=("
    back, bad = gamepad.PadMap.parse(m.text(), "", names)
    assert not bad and back.keys == m.keys


def test_pad_map_parse_checks_model_keys():
    m, bad = gamepad.PadMap.parse("a=MODE b=1 x=CL y=,", "", gamepad.key_names("1251"))
    assert bad == ["a=MODE", "y=,"] and m.keys == {"b": "1", "x": "CL"}
    m, bad = gamepad.PadMap.parse("a=MODE b=1 x=CL y=,", "", gamepad.key_names("1350"))
    assert bad == ["x=CL"] and m.keys == {"a": "MODE", "b": "1", "y": ","}


def test_program_pad_reports_keys_of_other_models(tmp_path, monkeypatch):
    """# pad: に機種にないキーがあれば、読めない語として知らせ、割り当てに入れない"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    prog = programs.Program(
        name="g", title="g", basic='10 PRINT "A"\n', run="RUN", pad="a=KANA b=1 x=, y=-"
    )
    app.open_program(prog, run=False)
    assert "# pad: のa=KANA x=,が読めません" in app.status
    assert app.pad_map.keys == {"b": "1", "y": "-"}
    app.close()


def test_pad_map_save_and_load(tmp_path):
    m = gamepad.PadMap({"a": "SPC", "dpup": "UP"})
    path = str(tmp_path / "pads" / "x.json")
    m.save(path)
    back = gamepad.PadMap.load(path, "x")
    assert back is not None and back.keys == m.keys and back.source == "x"
    assert gamepad.PadMap.load(str(tmp_path / "none.json"), "") is None


def _event(kind, **fields):
    return pygame.event.Event(kind, **fields)


def _button(kind, button, iid=1):
    return _event(kind, instance_id=iid, button=button)


class _Stub:
    """attached()だけを持つコントローラの代わり"""

    def __init__(self, attached: bool) -> None:
        self._attached = attached

    def attached(self) -> bool:
        return self._attached


def test_pads_sync_releases_detached():
    """pygame.event.get()が失敗して、外したイベントを受け取れなかったパッドは、syncで閉じて
    押していた入力を離す。つながっているパッドはそのまま"""
    pads = gamepad.Pads()
    pads.devices[3], pads.devices[4] = _Stub(False), _Stub(True)  # pyrefly: ignore
    pads.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_A, iid=3))
    pads.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_B, iid=4))
    assert pads.sync() == [("a", 3, False)]
    assert list(pads.devices) == [4] and pads.held == {(4, "b"): {"button"}}


def test_run_survives_event_get_failure():
    """pygame.event.get()がKeyErrorで失敗しても(pygame/pygame#3634)落ちず、その回に外れた
    パッドが押していたキーを離す"""
    app = make_app()
    app.pads.devices[3] = _Stub(False)  # pyrefly: ignore
    app.pad_event(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_A, iid=3))
    assert "SPC" in app.typer.physical
    answers = iter([KeyError(1), [_event(pygame.QUIT)]])  # 2回目で閉じる。あとは空

    def get():
        answer = next(answers, [])
        if isinstance(answer, Exception):
            raise answer
        return answer

    with patch("pygame.event.get", side_effect=get):
        app.run()
    assert "SPC" not in app.typer.physical and not app.pads.devices


def test_pads_buttons_and_axes():
    pads = gamepad.Pads()
    down = _event(pygame.CONTROLLERBUTTONDOWN, instance_id=3, button=pygame.CONTROLLER_BUTTON_A)
    up = _event(pygame.CONTROLLERBUTTONUP, instance_id=3, button=pygame.CONTROLLER_BUTTON_A)
    assert pads.handle(down) == [("a", 3, True)]
    assert pads.handle(down) == []  # 押したまま
    assert pads.handle(up) == [("a", 3, False)]
    axis = pygame.CONTROLLER_AXIS_LEFTX

    def move(v):
        return pads.handle(_event(pygame.CONTROLLERAXISMOTION, instance_id=3, axis=axis, value=v))

    assert move(int(0.4 * 32767)) == []  # しきい値の手前
    assert move(int(0.8 * 32767)) == [("dpright", 3, True)]
    assert move(int(0.4 * 32767)) == []  # 離すのは0.3を下回ってから
    assert move(int(-0.9 * 32767)) == [("dpright", 3, False), ("dpleft", 3, True)]
    assert move(0) == [("dpleft", 3, False)]
    # 反対側へ戻しただけ(押すほどではない)でも、倒していた向きは離す
    assert move(int(0.8 * 32767)) == [("dpright", 3, True)]
    assert move(int(-0.4 * 32767)) == [("dpright", 3, False)]
    assert move(int(-0.6 * 32767)) == [("dpleft", 3, True)]
    assert move(int(0.4 * 32767)) == [("dpleft", 3, False)]
    pads.handle(down)
    gone = _event(pygame.CONTROLLERDEVICEREMOVED, instance_id=3)
    assert pads.handle(gone) == [("a", 3, False)] and not pads.held


def test_pad_presses_pocket_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    assert app.pad_map.get("a") == "SPC"
    app.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_A))
    assert "SPC" in app.typer.physical
    app.handle(_button(pygame.CONTROLLERBUTTONUP, pygame.CONTROLLER_BUTTON_A))
    assert "SPC" not in app.typer.physical
    # Select → BRK
    app.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_BACK))
    assert app.m.brk
    app.handle(_button(pygame.CONTROLLERBUTTONUP, pygame.CONTROLLER_BUTTON_BACK))
    assert not app.m.brk
    app.close()


def test_program_pad_directive_applies(tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    prog = programs.Program(
        name="game", title="game", basic='10 PRINT "A"\n', run="RUN", pad="a=1 b=2 dpup=UP"
    )
    app.open_program(prog, run=False)
    assert app.pad_map.get("a") == "1" and app.pad_map.get("dpup") == "UP"
    assert app.pad_map.get("start") is None  # # pad: に書いたものだけ
    app.close()


def _key_pos(app, key: str):
    """本体の絵のキーkeyの、窓の中での中心"""
    x0, y0, x1, y1 = app.panel.key_rects[key]
    m = display.MARGIN
    return (int(((x0 + x1) / 2 + m) * app.scale), int(((y0 + y1) / 2 + m) * app.scale))


def test_pad_panel_assigns_by_click_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    prog = programs.Program(name="game", title="game", basic='10 PRINT "A"\n', run="RUN")
    app.open_program(prog, run=False)
    app.toggle_pad_panel()
    assert app.pad_panel is not None
    # 欄は本体の下に足され、本体の絵は隠れない
    assert app.window.get_height() == app.body_size[1] + app.pad_panel.height + BAR_H
    # ボタンを押すと、その入力が選ばれる(本体には送らない)
    app.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_Y))
    assert app.pad_panel.selected == "y" and "SPC" not in app.typer.physical
    app.frame()
    app.mouse_down(_key_pos(app, "1"))  # 本体の絵の「1」のキーをクリック
    assert app.pad_map.get("y") == "1" and app.pad_panel.selected is None
    assert app.pad_dirty
    # パソコンのキーでも割り当てられる
    app.pad_panel.selected = "x"
    app.key_down(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, mod=0, unicode="z"))
    assert app.pad_map.get("x") == "Z"
    app.frame()
    app.pad_action("save_prog")
    saved = os.path.join(str(tmp_path), "pads", "programs", "game.json")
    assert os.path.exists(saved) and not app.pad_dirty
    # 読み直すと保存した割り当てになる
    app.open_program(prog, run=False)
    assert app.pad_map.get("y") == "1" and app.pad_map.get("x") == "Z"
    assert "game" in app.pad_map.source
    app.pad_action("reset")
    assert app.pad_map.get("y") is None and app.pad_map.get("a") == "SPC"
    app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_pad_panel_keeps_pad_shape_and_wraps_buttons(_sizes, tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    app.toggle_pad_panel()
    app.frame()
    panel = app.pad_panel
    assert panel is not None
    rects = {value: r for r, kind, value in panel.hits if kind == "input"}
    # 十字キーは十字に、A・B・X・Yは右側にひし形に
    assert rects["dpup"].centerx == rects["dpdown"].centerx
    assert rects["dpleft"].right <= rects["dpright"].left
    assert rects["dpup"].bottom <= rects["dpleft"].top < rects["dpdown"].top
    assert rects["x"].bottom <= rects["y"].top and rects["y"].right <= rects["a"].left
    assert rects["dpright"].right < rects["back"].left < rects["start"].left < rects["y"].left
    # ボタンはすべて窓の中にある
    width = app.window.get_width()
    for r, kind, _ in panel.hits:
        assert r.right <= width, (kind, r)
    app.close()


def test_pad_shows_default_program_mapping_separately(tmp_path, monkeypatch):
    """「default」という名前のプログラム用の保存が、既定の保存と別のファイルになる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    prog = programs.Program(name="default", title="default", basic='10 PRINT "A"\n', run="RUN")
    app.open_program(prog, run=False)
    app.pad_map.set("a", "1")
    app.pad_action("save_prog")
    assert not os.path.exists(os.path.join(str(tmp_path), "pads", "default.json"))
    assert os.path.exists(os.path.join(str(tmp_path), "pads", "programs", "default.json"))
    app.pad_map.set("a", "2")
    app.pad_action("save_default")
    default = gamepad.PadMap.load(os.path.join(str(tmp_path), "pads", "default.json"), "")
    assert default is not None and default.get("a") == "2"
    app.close()


def test_pad_release_uses_mapping_at_press(tmp_path, monkeypatch):
    """押しているあいだに割り当てが変わっても(プログラムを読み込むなど)、押したときのキーを離す"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    app.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_A))
    assert "SPC" in app.typer.physical
    prog = programs.Program(name="g", title="g", basic='10 PRINT "A"\n', run="RUN", pad="a=1")
    app.open_program(prog, run=False)
    # 読み込みで割り当てが替わるときに、押していたキーは離される
    assert "SPC" not in app.typer.physical and "1" not in app.typer.physical
    app.handle(_button(pygame.CONTROLLERBUTTONUP, pygame.CONTROLLER_BUTTON_A))
    assert not app.typer.physical
    # 割り当ての画面での変更も同じ
    app.handle(_button(pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLER_BUTTON_A))
    assert "1" in app.typer.physical
    app.toggle_pad_panel()
    assert "1" not in app.typer.physical
    app.handle(_button(pygame.CONTROLLERBUTTONUP, pygame.CONTROLLER_BUTTON_A))
    app.toggle_pad_panel(False)
    assert not app.typer.physical
    app.close()


def test_pad_dpad_and_stick_release_together():
    """十字キーとスティックで同じ向きを押しているとき、片方を戻しても離さない"""
    pads = gamepad.Pads()
    right = pygame.CONTROLLER_BUTTON_DPAD_RIGHT

    def stick(axis, v):
        return pads.handle(_event(pygame.CONTROLLERAXISMOTION, instance_id=1, axis=axis, value=v))

    assert pads.handle(_button(pygame.CONTROLLERBUTTONDOWN, right)) == [("dpright", 1, True)]
    assert stick(pygame.CONTROLLER_AXIS_LEFTX, 30000) == []
    assert stick(pygame.CONTROLLER_AXIS_LEFTX, 0) == []  # 十字キーをまだ押している
    assert pads.handle(_button(pygame.CONTROLLERBUTTONUP, right)) == [("dpright", 1, False)]
    # 左右のスティック同士でも同じ
    assert stick(pygame.CONTROLLER_AXIS_LEFTX, 30000) == [("dpright", 1, True)]
    assert stick(pygame.CONTROLLER_AXIS_RIGHTX, 30000) == []
    assert stick(pygame.CONTROLLER_AXIS_LEFTX, 0) == []
    assert stick(pygame.CONTROLLER_AXIS_RIGHTX, 0) == [("dpright", 1, False)]
    assert not pads.held


def test_pad_map_restored_with_state_and_undo(tmp_path, monkeypatch):
    """状態の保存・復元と「読み込む前に戻す」で、割り当ても一緒に戻る"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    a = programs.Program(name="a", title="a", basic='10 PRINT "A"\n', run="RUN", pad="a=1")
    b = programs.Program(name="b", title="b", basic='10 PRINT "B"\n', run="RUN", pad="a=2")
    app.open_program(a, run=False)
    app.pad_map.set("b", "9")  # 保存していない調整も状態に入る
    state = str(tmp_path / "state.json")
    app.m.save_state(state, app._prog_info())
    app.open_program(b, run=False)
    assert app.pad_map.get("a") == "2" and app.pad_map.get("b") is None
    app.undo_loading()
    assert app.last_prog is a and app.pad_map.get("a") == "1" and app.pad_map.get("b") == "9"
    app.open_program(b, run=False)
    app.load_state(state)
    assert app.last_prog.name == "a" and app.pad_map.get("a") == "1" and app.pad_map.get("b") == "9"
    app.pad_action("from_prog")
    assert app.pad_map.get("b") is None and app.pad_map.get("a") == "1"
    app.close()


def _inside(app) -> bool:
    """割り当ての欄のすべてのものが窓の中にあるか"""
    panel = app.pad_panel
    win = app.window.get_rect()
    bar_bottom = max(r.bottom for r in app.bar.rects)
    return all(win.contains(r) for r, _kind, _v in panel.hits) and bar_bottom <= win.height


def test_pad_panel_fits_on_screen(tmp_path, monkeypatch):
    """欄を出すと本体を縮めてでも画面に入れ、入力を選ぶ・やめるで窓の高さが変わらない"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    for screen in ((1024, 768), (1440, 900)):
        with patch.object(pygame.display, "get_desktop_sizes", return_value=[screen]):
            app = make_app(frames=3)
            app.status = ""
            scale = app.scale
            app.toggle_pad_panel()
            app.frame()
            assert app.window.get_height() <= screen[1] - 120 and _inside(app)
            size = app.window.get_size()
            assert app.pad_panel is not None
            app.pad_panel.selected = "back"
            app.frame()
            app.pad_action("save_default")
            app.frame()
            app.key_down(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode=""))
            app.frame()
            assert app.window.get_size() == size == app._window_size() and _inside(app)
            app.toggle_pad_panel(False)
            assert app.scale == scale  # しまえば元の拡大率に戻る
            app.close()


def test_pad_panel_leaves_bench_clicks(tmp_path, monkeypatch):
    """欄と同じ高さにある作業欄のクリックは、欄が受け取らない"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3, norom=True)
    app.status = ""
    app.toggle_pad_panel()
    app.frame()
    panel = app.pad_panel
    assert panel is not None
    hits = [
        (r, v) for r, k, v in app.bench_view.hits
        if k == "break" and panel.top <= r.centery < panel.top + panel.height
    ]  # fmt: skip
    assert hits
    r, addr = hits[0]
    app.mouse_down(r.center)
    assert addr in app.bench.breaks
    app.close()


def test_pad_dirty_mark_restored_with_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3, norom=True)
    prog = programs.Program(name="g", title="g", blocks=[(0xC000, b"\x37")], pad="a=1")
    app.open_program(prog, run=False)
    app.pad_map.set("a", "2")
    app.pad_dirty = True
    state = str(tmp_path / "state.json")
    app.m.save_state(state, app._prog_info())
    app.pad_action("reset")
    assert not app.pad_dirty
    app.load_state(state)
    assert app.pad_map.get("a") == "2" and app.pad_dirty
    app.close()


def test_pad_panel_and_paper_fit_together(tmp_path, monkeypatch):
    """プリンタの紙と割り当ての欄を両方出しても(どちらが先でも)画面に入る"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    with patch.object(pygame.display, "get_desktop_sizes", return_value=[(1440, 900)]):
        for pad_first in (True, False):
            app = make_app(frames=3)
            app.status = ""
            scale = app.scale
            if pad_first:
                app.toggle_pad_panel()
            assert app.m.printer is not None
            for code in b"ABC\r":
                app.m.printer.put(code)
            app.frame()
            if not pad_first:
                app.toggle_pad_panel()
            app.frame()
            assert app.paper_open and app.pad_panel is not None
            assert app.window.get_height() <= 780 and _inside(app)
            app.close_paper()
            app.toggle_pad_panel(False)
            assert app.scale == scale
            app.close()


def _hex_prog(name="game", pad="a=1 dpup=UP"):
    """BASICのない.hexだけのプログラム"""
    return programs.Program(
        name=name, title=name.upper(), blocks=[(0xC000, b"\x37")], run="CALL &C000", pad=pad
    )


def test_hex_only_program_is_pad_target(tmp_path, monkeypatch):
    """ROMのある本体で.hexだけを読み込むと、割り当ての対象はそのプログラムになる。書き出しに
    使うlast_progは、RAMのBASICのプログラムのまま"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    basic = programs.Program(
        name="other", title="other", basic='10 PRINT "A"\n', run="RUN", pad="a=9"
    )
    app.open_program(basic, run=False)
    game = _hex_prog()
    app.open_program(game, run=False)
    assert app.last_prog is basic and app.pad_prog is game
    assert app.pad_map.get("a") == "1" and "GAME" in app.pad_map.source
    app.toggle_pad_panel()
    app.frame()
    panel = app.pad_panel
    assert panel is not None
    enabled = {v for _r, kind, v in panel.hits if kind == "action"}
    assert {"save_prog", "from_prog"} <= enabled
    app.pad_map.set("b", "5")
    app.pad_action("save_prog")
    assert os.path.exists(os.path.join(str(tmp_path), "pads", "programs", "game.json"))
    assert not os.path.exists(os.path.join(str(tmp_path), "pads", "programs", "other.json"))
    app.pad_action("from_prog")
    assert app.pad_map.get("a") == "1" and app.pad_map.get("b") is None
    # 状態の保存・復元で、割り当ての対象も戻る
    state = str(tmp_path / "state.json")
    app.m.save_state(state, app._prog_info())
    app.open_program(_hex_prog("next", "a=2"), run=False)
    assert app.pad_prog is not None and app.pad_prog.name == "next"
    app.load_state(state)
    assert app.last_prog is not None and app.last_prog.name == "other"
    assert app.pad_prog is not None and app.pad_prog.name == "game"
    # 読み込む前に戻すと、割り当ての対象も前のプログラムに戻る
    app.open_program(_hex_prog("next", "a=2"), run=False)
    app.undo_loading()
    assert app.pad_prog is not None and app.pad_prog.name == "game"
    assert app.last_prog is not None and app.last_prog.name == "other"
    app.close()


def test_hex_only_program_from_nothing_can_be_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    app.open_program(_hex_prog(pad=None), run=False)
    assert app.last_prog is None and app.pad_prog is not None
    app.pad_map.set("a", "7")
    app.pad_action("save_prog")
    saved = gamepad.PadMap.load(os.path.join(str(tmp_path), "pads", "programs", "game.json"), "")
    assert saved is not None and saved.get("a") == "7"
    app.undo_loading()
    assert app.pad_prog is None
    app.close()


def _key(key, mod=0, text=""):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod, unicode=text)


def test_pad_panel_leaves_command_keys_to_shortcuts(tmp_path, monkeypatch):
    """欄を出していても、⌘(Ctrl)との組み合わせは割り当てずにショートカットとして扱う"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    app.toggle_pad_panel()
    panel = app.pad_panel
    assert panel is not None
    for mod in (pygame.KMOD_META, pygame.KMOD_CTRL):
        panel.selected = "x"
        app.handle(_key(pygame.K_s, mod, "s"))
        assert app.pad_map.get("x") is None and panel.selected == "x"
        assert "shot" in app.status  # 画面の画像を保存した
    app.handle(_key(pygame.K_o, pygame.KMOD_META, "o"))
    assert app.menu is not None and app.pad_map.get("x") is None
    app.close()


def test_pad_panel_assigns_symbol_keys(tmp_path, monkeypatch):
    """パソコンで打った記号が本体のキーの名前なら割り当てる。英数字はKEYDOWNだけで扱う"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    app.toggle_pad_panel()
    panel = app.pad_panel
    assert panel is not None

    def typed(name, key, text, mod=0):
        panel.selected = name
        app.handle(_key(key, mod, text))
        app.handle(pygame.event.Event(pygame.TEXTINPUT, text=text))

    typed("y", pygame.K_MINUS, "-")
    assert app.pad_map.get("y") == "-" and panel.selected is None
    typed("x", pygame.K_8, "*", pygame.KMOD_SHIFT)  # 数字のキーの記号は数字にしない
    assert app.pad_map.get("x") == "*"
    for text in "/+.=":
        typed("b", pygame.K_UNKNOWN, text)
        assert app.pad_map.get("b") == text
    typed("a", pygame.K_9, "(", pygame.KMOD_SHIFT)  # PC-1251ではSHIFTで打つ記号
    assert app.pad_map.get("a") == "SPC" and panel.selected == "a"
    typed("a", pygame.K_1, "1")
    assert app.pad_map.get("a") == "1" and panel.selected is None
    panel.selected = "x"  # 英数字の字は、選んであってもTEXTINPUTでは割り当てない
    app.handle(pygame.event.Event(pygame.TEXTINPUT, text="2"))
    assert app.pad_map.get("x") == "*" and panel.selected == "x"
    app.close()


def test_pad_panel_assigns_pc1350_symbols(tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(model="1350", frames=3)
    app.toggle_pad_panel()
    panel = app.pad_panel
    assert panel is not None
    for text in ",;:()":
        panel.selected = "y"
        app.handle(pygame.event.Event(pygame.TEXTINPUT, text=text))
        assert app.pad_map.get("y") == text
    panel.selected = "y"
    app.handle(pygame.event.Event(pygame.TEXTINPUT, text="!"))  # 本体のキーにない記号
    assert app.pad_map.get("y") == ")" and panel.selected == "y"
    back, bad = gamepad.PadMap.parse(app.pad_map.text(), "", app.pad_key_names())
    assert not bad and back.keys == app.pad_map.keys
    app.close()


SCREEN_W = (700, 800, 900, 980, 1024, 1280, 1440, 1920)
SCREEN_H = (600, 700, 768, 800, 900, 1080)
SCREENS = [(w, h) for w in SCREEN_W for h in SCREEN_H]


@pytest.mark.parametrize("model", ["1251", "1350"])
def test_pad_panel_fits_every_screen(model, tmp_path, monkeypatch):
    """欄の高さは幅で増えも減りもする。どの画面でも中身が窓に入り、窓は画面の上限
    (拡大率の下限に当たるときを除く)を超えない"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(model=model, frames=1)
    app.status = ""
    app.toggle_pad_panel()
    for dw, dh in SCREENS:
        with patch.object(pygame.display, "get_desktop_sizes", return_value=[(dw, dh)]):
            app._refit()
            app.frame()
            size = app.window.get_size()
            assert size == app._window_size(), (dw, dh)
            assert _inside(app), (dw, dh)
            if app.scale > 0.35:
                assert size[1] <= dh - 120, (dw, dh, size)
    app.close()


@pytest.mark.parametrize("norom", [False, True])
def test_pad_warning_survives_load_message(norom, tmp_path, monkeypatch):
    """# pad: の読めない語の知らせは、読み込み終わりの知らせに続けて出す(上書きしない)"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    path = tmp_path / "game.hex"
    path.write_text("# pad: a=KANA b=1\n# run: CALL &C000\nC000 37\n", encoding="utf-8")
    app = make_app(frames=3, norom=norom)
    app.open_program(programs.load_program(str(path)), run=False)
    settle(app)
    assert "を読み込みました" in app.status
    assert "# pad: のa=KANAが読めません" in app.status
    assert app.pad_map.keys == {"b": "1"}
    app.close()


def test_empty_pad_line_unassigns_everything(tmp_path, monkeypatch):
    """全部外した割り当てをコピーした行(値のない# pad:)は、何も割り当てない。# pad: の行が
    ないときだけ既定の割り当てになる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    copied = []
    monkeypatch.setattr(app, "set_clipboard", copied.append)
    for name in list(app.pad_map.keys):
        app.pad_map.set(name, None)
    app.pad_action("copy")
    assert copied == ["# pad:\n"]
    empty = tmp_path / "empty.bas"
    empty.write_text(copied[0] + '10 PRINT "A"\n', encoding="utf-8")
    plain = tmp_path / "plain.bas"
    plain.write_text('10 PRINT "A"\n', encoding="utf-8")
    prog = programs.load_program(str(empty))
    assert prog.pad == ""
    assert programs.load_program(str(plain)).pad is None
    app.open_program(prog, run=False)
    settle(app)
    assert app.pad_map.keys == {}
    assert app.pad_action("from_prog") is None and app.pad_map.keys == {}
    app.save_state()
    app.open_program(programs.load_program(str(plain)), run=False)
    settle(app)
    assert app.pad_map.keys == gamepad.DEFAULT
    app.load_state()  # 状態に入れたプログラムも、値のない# pad: のまま戻る
    assert app.pad_prog is not None and app.pad_prog.pad == ""
    assert app.pad_map.keys == {}
    app.close()


def test_pad_lines_join(tmp_path):
    """# pad: は何行に分けて書いてもよい"""
    path = tmp_path / "two.bas"
    path.write_text('# pad: a=1\n# pad: b=2\n10 PRINT "A"\n', encoding="utf-8")
    assert programs.load_program(str(path)).pad == "a=1 b=2"


def test_empty_pad_line_button_returns_to_it(tmp_path, monkeypatch):
    """値のない# pad: のプログラムでも、欄の「# pad: に戻す」をクリックして何もない割り当てに
    戻せる(描いたボタンが押せる)"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    prog = programs.Program(name="g", title="g", basic='10 PRINT "A"\n', run="RUN", pad="")
    app.open_program(prog, run=False)
    settle(app)
    app.toggle_pad_panel()
    assert app.pad_panel is not None
    app.pad_panel.selected = "a"
    app.key_down(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_z, mod=0, unicode="z"))
    assert app.pad_map.keys == {"a": "Z"}
    app.frame()
    buttons = [r for r, kind, act in app.pad_panel.hits if act == "from_prog"]
    assert buttons, "「# pad: に戻す」が押せない"
    app.mouse_down(buttons[0].center)
    assert app.pad_map.keys == {} and not app.pad_dirty
    app.close()
