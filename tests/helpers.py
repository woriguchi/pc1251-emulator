"""試験で共通に使う関数(本体を起動する、キーを打つ、アプリを作る)"""

import os
import sys
from dataclasses import replace

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sc61box.autotype import Typer  # noqa: E402
from sc61box.lcdtext import lcd_text  # noqa: E402
from sc61box.machine import CLOCK, new_machine  # noqa: E402


def boot(model="1251", card=0, **kw):
    """本体を作って1秒動かす。(本体, Typer)を返す"""
    m = new_machine(model, card, **kw)
    m.run(CLOCK)
    return m, Typer(m)


def finish(m, t):
    """Typerが打ち終わるまで動かす"""
    while t.busy:
        t.step()
        m.run(CLOCK // 200)


def typ(m, t, text, wait=0.5, mode=None):
    """textを打ち、wait秒動かして液晶の文字を返す"""
    if mode:
        t.add_mode(mode)
    t.add_text(text)
    finish(m, t)
    m.run(int(CLOCK * wait))
    return lcd_text(m)


def lines(m):
    return [s.rstrip() for s in lcd_text(m).split("\n")]


def make_app(model="1251", frames=40, **kwargs):
    """ウィンドウを出さずにアプリを作り、framesフレーム動かす"""
    from sc61box.app import App, Options

    app = App(replace(Options(model=model, fresh=True, mute=True), **kwargs))
    for _ in range(frames):
        app.frame()
    return app


def settle(app, limit=3000):
    """打ち込みが終わるまで(最長limitフレーム)動かし、さらに10フレーム動かす"""
    for _ in range(limit):
        app.frame()
        if not app.typer.busy:
            break
    for _ in range(10):
        app.frame()


def typed_and_stored(model, src):
    """srcを打ち込んだ本体と、中間コードを直に置いた本体を作って返す"""
    from sc61box import basictext, keytype

    typed, t = boot(model)
    t.add_mode("PRO")
    t.add_text("NEW\n")
    t.add_program(src)
    finish(typed, t)
    stored, t2 = boot(model)
    t2.add_mode("PRO")
    t2.add_text("NEW\n")
    finish(stored, t2)
    data = basictext.encode_program(keytype.typed_text(src, model), stored.mem)
    assert data is not None and stored.store_program(data)
    return typed, stored
