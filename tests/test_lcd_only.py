"""液晶だけを見せるモード(--lcd、メニューの「液晶だけにする」)"""

import warnings
from unittest.mock import patch

import pygame
import pytest
from helpers import make_app

from sc61box.app import BAR_H

WIDE = [(1920, 1080)]


@pytest.mark.parametrize("model", ["1251", "1245", "1261", "1350"])
@pytest.mark.parametrize("alpha_mask", [False, True])
def test_lcd_resize_preserves_pixels_with_side_margins(model, alpha_mask):
    """大きな窓から横長の窓へ戻しても、拡大した液晶の各行と左右の余白が崩れない。"""
    backend = pygame.transform.get_smoothscale_backend()
    pygame.transform.set_smoothscale_backend("GENERIC")
    app = make_app(model=model, frames=2, lcd=True)
    try:
        app.status = ""
        # Cocoaでは透明度の保存領域があっても、通常の描画面は不透明として使う。
        # 未使用のalpha=0をsmoothscaleが透明として扱い始めても、画面が消えてはいけない。
        source = pygame.Surface(app.panel.out.get_size(), pygame.SRCALPHA if alpha_mask else 0, 32)
        source.set_alpha(None)
        source.fill((190, 210, 160, 0))
        for x in range(0, source.get_width(), 19):
            pygame.draw.line(source, (20, 40, 60, 0), (x, 0), (x, source.get_height()), 3)
        for y in range(0, source.get_height(), 13):
            pygame.draw.line(source, (100, 80, 40, 0), (0, y), (source.get_width(), y), 2)
        vw, vh = app.view_box().size
        for size in ((vw * 2, vh * 3 + BAR_H), (vw * 2, vh * 5 // 4 + BAR_H)):
            _native_resize(app, size)
            app._show(source)
            expected = pygame.transform.smoothscale(
                source.subsurface(app.view_box()), app.body_size
            )
            body = app.window.subsurface(pygame.Rect(app.origin, app.body_size))
            assert pygame.image.tobytes(body, "RGB") == pygame.image.tobytes(expected, "RGB")
        assert app.scale > 1 and app.origin[0] > 0
        # 余白に液晶の画素を書き込んでいないことも確かめる。
        assert all(
            app.window.get_at((0, y))[:3] == (20, 21, 24) for y in range(app.window.get_height())
        )
        app.toggle_lcd(False)
        app._show(source)
        expected = pygame.transform.smoothscale(source, app.body_size)
        body = app.window.subsurface(pygame.Rect(app.origin, app.body_size))
        assert pygame.image.tobytes(body, "RGB") == pygame.image.tobytes(expected, "RGB")
    finally:
        app.close()
        pygame.transform.set_smoothscale_backend(backend)


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_keeps_width_and_shows_lcd(_sizes, tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3)
    full = app.window.get_size()
    app.toggle_lcd()
    app.frame()
    box = app.view_box()
    x0, y0, x1, y1 = app.panel.lcd_box()
    assert box.contains(pygame.Rect(x0, y0, x1 - x0, y1 - y0)) and box.w > x1 - x0  # 縁を足す
    assert app.lcd_only and app.win_flags == pygame.RESIZABLE
    # 幅は本体を出すときと同じで、液晶だけがその幅に広がる
    assert app.window.get_width() == full[0]
    assert app.body_size == (int(box.w * app.scale), int(box.h * app.scale))
    assert app.window.get_height() == app.body_size[1] + BAR_H < full[1]
    # 本体のキーはないので、クリックしても何も押さない
    app.mouse_down((app.body_size[0] // 2, app.body_size[1] // 2))
    assert app.mouse_key is None and not app.typer.physical
    app.toggle_lcd()
    assert not app.lcd_only and app.window.get_size() == full
    assert app.win_flags == 0
    app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_window_can_be_enlarged(_sizes, tmp_path, monkeypatch):
    """利用者が窓を広げる(最大化など)と、液晶をその中に入る大きさにしてまんなかに描く"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=3, lcd=True)
    assert app.lcd_only
    before = app.scale
    app.handle(pygame.event.Event(pygame.VIDEORESIZE, w=1800, h=1000, size=(1800, 1000)))
    app.frame()
    assert app.window.get_size() == (1800, 1000) and app.scale > before
    content = app._window_size()
    assert content[0] <= 1800 and content[1] <= 1000
    assert app.origin == ((1800 - content[0]) // 2, (1000 - content[1]) // 2)
    # 操作欄のクリックは中身の位置で受ける
    ox, oy = app.origin
    r = next(r for r in app.bar.rects if r.width)
    pos = (r.centerx + ox, r.centery + oy)
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    assert app.popup is not None
    app.popup = None
    # 割り当ての欄や紙を出しても窓の大きさは変えず、中に収める
    app.toggle_pad_panel()
    app.frame()
    assert app.window.get_size() == (1800, 1000) and app._window_size()[1] <= 1000
    app.toggle_lcd(False)
    assert app.window.get_size() == app._window_size()
    app.close()


def _native_resize(app, size):
    """SDLの窓の大きさを変える(利用者が変えたのと同じ道筋。pygameは表示面も変える)"""
    from pygame._sdl2.video import Window

    pygame.event.clear()
    with warnings.catch_warnings():  # pygame-ceはfrom_display_moduleに非推奨の印をつけている
        warnings.simplefilter("ignore", DeprecationWarning)
        Window.from_display_module().size = size
    for ev in pygame.event.get():
        app.handle(ev)


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_follows_native_resize(_sizes, tmp_path, monkeypatch):
    """窓の大きさが実際に変わったときに置き直す(pygameが表示面を先に変えていても)。
    小さくしすぎても止まらず、下限まで戻す"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=2, lcd=True)
    assert app.window.get_width() > 1200
    _native_resize(app, (1200, 700))
    app.frame()
    assert app.free_size == (1200, 700) and app.window.get_size() == (1200, 700)
    assert app.body_size[0] <= 1200 and app.origin[1] > 0  # 幅に合わせて縮め、まんなかに
    _native_resize(app, (400, 200))
    app.frame()
    assert app.free_size is not None and app.free_size[0] >= 320
    app.resized(100, 100)  # 下限より小さければ、下限まで戻す
    app.frame()
    mw, mh = app._min_size()
    assert app.free_size[0] >= mw > 100 and app.free_size[1] >= mh
    assert app.window.get_rect().contains(pygame.Rect(app.origin, app._window_size()))
    app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_menus_use_whole_window(_sizes, tmp_path, monkeypatch):
    """細い窓では一覧やメニューを開くあいだだけ窓を高くし、どちらも窓全体に描く"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=2, lcd=True)
    thin = app.window.get_size()
    app.open_bar_popup("view")
    app.frame()
    assert app.popup is not None and app.window.get_height() >= app.MENU_ROOM
    win = app.window.get_rect()
    assert all(win.contains(r) for _i, r in app.popup.rows)
    from sc61box.overlay import LINE_H

    assert min(r.height for _i, r in app.popup.rows) == LINE_H  # 行を縮めていない
    app.popup = None
    app.frame()
    assert app.window.get_size() == thin
    app.open_menu()
    app.frame()
    assert app.menu is not None and app.window.get_height() >= app.MENU_ROOM
    assert all(win.contains(pygame.Rect(r)) for _act, r in app.menu.button_rects)
    # 一覧のボタンは窓の位置で押せる
    r = next(r for act, r in app.menu.button_rects if act == "close")
    app.mouse_down(pygame.Rect(r).center)
    assert app.menu is None
    app.frame()
    assert app.window.get_size() == thin
    # 操作欄に「本体を出す」があり、押すと本体の絵に戻る
    button = next(b for b in app.bar.buttons if b.label == "本体を出す")
    button.action()
    assert not app.lcd_only
    app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_small_window_grows_for_panels(_sizes, tmp_path, monkeypatch):
    """小さくした窓でも、操作欄のボタンは全部入り、割り当ての欄や紙を出せば入るだけ広がる"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=2, lcd=True)
    app.resized(100, 100)
    app.frame()
    win = app.window.get_rect()
    assert all(win.contains(r) for r in app.bar.rects if r.width)  # 省いたボタンは幅0
    assert app.body_size[0] + app.origin[0] <= win.width and app.origin[0] == 0
    labels = [b.label for b, r in zip(app.bar.buttons, app.bar.rects, strict=True) if r.width]
    assert "本体を出す" in labels and "録画" in labels
    app.toggle_pad_panel()
    app.frame()
    win = app.window.get_rect()
    panel = app.pad_panel
    assert panel is not None
    assert win.width >= 480 and all(win.contains(r) for r, _k, _v in panel.hits)
    assert win.height >= panel.top + panel.height + BAR_H
    app.toggle_pad_panel(False)
    assert app.m.printer is not None
    for code in b"HELLO\r":
        app.m.printer.put(code)
    app.frame()
    assert app.window.get_height() >= app.body_size[1] + app.paper.height + BAR_H
    app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_help_gets_room(_sizes, tmp_path, monkeypatch):
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=2, lcd=True)
    thin = app.window.get_size()
    app.toggle_help()
    app.frame()
    assert app.help and app.window.get_height() >= app.MENU_ROOM
    app.help = 0
    app.frame()
    assert app.window.get_size() == thin
    app.close()


@pytest.mark.parametrize("model", ["1251", "1245", "1261", "1350"])
def test_lcd_only_resuming_keeps_bar_buttons_visible(model):
    """一時停止中に幅を縮めても、再開後に長くなるボタンが録画ボタンを押し出さない。"""
    app = make_app(model=model, frames=2, lcd=True)
    try:
        app.toggle_halt()
        assert app.halted
        app.resized(100, 100)
        app.frame()
        app.toggle_halt()
        assert not app.halted
        app.frame()
        win = app.window.get_rect()
        assert all(win.contains(r.move(app.origin)) for r in app.bar.rects if r.width)
        visible = [b.label for b, r in zip(app.bar.buttons, app.bar.rects, strict=True) if r.width]
        assert "本体を出す" in visible and "録画" in visible
    finally:
        app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_hides_workbench_and_bar_toggles_it(_sizes, tmp_path, monkeypatch):
    """液晶だけのあいだは作業欄を出せず、出していれば戻るときに戻す。操作欄のボタンで出し入れ"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=2)
    app.frame()
    button = next(b for b in app.bar.buttons if b.label == "作業欄 ▶")
    button.action()
    assert app.pane_open
    app.frame()
    assert any(b.label == "◀ 作業欄" for b in app.bar.buttons)
    app.toggle_lcd(True)
    assert not app.pane_open
    app.toggle_pane(True)
    assert not app.pane_open  # 液晶だけのあいだは出せない
    app.frame()
    assert not any("作業欄" in b.label for b in app.bar.buttons)
    pane_item = next(it for it in app.popup_items("view") if "作業欄" in it.label)
    assert not pane_item.enabled
    app.toggle_lcd(False)
    assert app.pane_open  # 戻すと作業欄も戻る
    app.close()


def test_lcd_only_without_rom_hides_workbench_and_restores_it():
    """ROMなしでも液晶だけにでき、隠した作業欄に入力せず、戻せば編集を続けられる。"""
    app = make_app(frames=2, norom=True)
    try:
        assert app.pane_open and app.pane_keys()
        app.toggle_lcd(True)
        assert not app.pane_open and not app.pane_keys()
        app.resized(1100, 200)
        app.frame()
        assert app.window.get_rect().contains(pygame.Rect(app.origin, app._window_size()))
        app.toggle_lcd(False)
        app.frame()
        assert app.pane_open and app.pane_keys()
        assert app.window.get_height() >= app.bench_view.min_height()
    finally:
        app.close()


def _content_inside(app) -> bool:
    """中身(本体、割り当ての欄、操作欄)がすべて窓の中にあるか"""
    win = app.window.get_rect()
    content = pygame.Rect(app.origin, app._window_size())
    panel = app.pad_panel
    hits = [r for r, _k, _v in panel.hits] if panel is not None else []
    bars = [r for r in app.bar.rects if r.width]
    return win.contains(content) and all(win.contains(r.move(app.origin)) for r in hits + bars)


@pytest.mark.parametrize("model", ["1251", "1350"])
@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_pad_panel_fits_resized_window(_sizes, model, tmp_path, monkeypatch):
    """割り当ての欄の高さは幅で増えも減りもする。窓の大きさをどう変えても、中身が窓に入る"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(model=model, frames=2, lcd=True)
    app.status = ""
    app.toggle_pad_panel()
    app.frame()
    for size in ((633, 900), (670, 100)):  # 欄の高さの変わる幅をまたぐ
        app.resized(*size)
        app.frame()
        assert _content_inside(app), size
    for w in range(300, 1400, 37):
        for h in (100, 300, 500, 900):
            app.resized(w, h)
            app.frame()
            assert _content_inside(app), (w, h)
    app.close()


@patch.object(pygame.display, "get_desktop_sizes", return_value=WIDE)
def test_lcd_only_language_change_keeps_pane_setting(_sizes, tmp_path, monkeypatch):
    """液晶だけのあいだに言語を切り替えても、作業欄を出す設定は隠す前のまま覚える"""
    import json

    from sc61box.app import view_file

    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(frames=2)
    app.toggle_pane(True)
    app.toggle_lcd(True)
    app.set_language("en")
    app.set_language("ja")
    with open(view_file(), encoding="utf-8") as f:
        assert json.load(f)["show_pane"] is True
    app.close()
    again = make_app(frames=2)
    assert again.pane_open
    again.close()
