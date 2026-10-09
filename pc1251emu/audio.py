"""圧電ブザーの音

Cポートの上位4ビット(ビット6〜4)で出力が決まる(POPCOMの講座の表7、
PockEmulのcompute_xout)。

    0, 4  LOW        1, 5  HIGH
    2     2kHzの発振  3     4kHzの発振
    6, 7  カセット入力をそのまま出す(ここでは無音)

BASICのBEEP文は3(4kHz)を使い、PC-インタープリタのBEEPは5と4を交互に
書いて振動板を直接動かす。CPUのサイクル数で時刻を持っているので、
書き込みの間隔がそのまま音の高さになる。
"""

import ctypes
import glob
import math
import os
import re
import sys
from array import array

from .machine import CLOCK

RATE = 44100  # 22050Hzでは方形波の高調波の折り返しが耳につくので、この速さで作る
AMP = 9000
# 圧電素子は低音を返さない。50Hzあたりから下を切る一次のハイパス
HPF = 1.0 - 2 * math.pi * 50 / RATE
# 1.5kHzより上を約6dB下げる一次のシェルフ(方形波のままでは実機より軽い音になる)
SHELF_A = math.exp(-2 * math.pi * 1500 / RATE)
SHELF_G = 0.5
SPC = CLOCK / RATE  # 1サンプルあたりのCPUサイクル(約4.4)
OSC_HALF = {2: CLOCK / 2000 / 2, 3: CLOCK / 4000 / 2}  # 内蔵発振の半周期(サイクル)


class Buzzer:
    def __init__(self):
        self.mode = 0  # 次の標本の始まりの時刻での出力
        self.t = 0.0  # 次の標本の始まりのサイクル
        self.pending: list[tuple[int, int]] = []  # 標本にまだ入れていない書き込み
        self.x_prev = -1.0  # 止まっているときの出力(LOW)。0から始めると最初に1回鳴る
        self.y = 0.0
        self.lp = 0.0  # シェルフの低域側

    def hold(self, mode: int) -> None:
        """標本を作らずに時間が進んだとき(早送り中など)。そのモードで鳴り続けて落ち着いた
        状態にしておく。次に標本を作り始めたときに、前の状態との差で1回鳴らないように"""
        self.mode = mode
        self.x_prev = 1.0 if mode in (1, 5) else 0.0 if mode in OSC_HALF else -1.0
        self.y = self.lp = 0.0
        self.pending = []

    @staticmethod
    def _mean(mode: int, t0: float, t1: float) -> float:
        """サイクルt0〜t1の出力の平均(-1〜1)。内蔵発振は正確に積分する"""
        if mode in (1, 5):
            return 1.0
        half = OSC_HALF.get(mode)
        if half is None or t1 <= t0:
            return -1.0

        def tri(t: float) -> float:  # 発振の方形波(最初の半周期が+1)を0からtまで積分した値
            k, r = divmod(t, half)
            return r if int(k) % 2 == 0 else half - r

        return (tri(t1) - tri(t0)) / (t1 - t0)

    def render(
        self, events: list[tuple[int, int]], c0: int, c1: int, speed: float = 1, keep_silent=False
    ) -> bytes:
        """サイクルc0〜c1ぶんのPCMを作る。eventsは(サイクル, モード)の列。
        speedは速さの倍率。1標本にspeed倍のサイクルを詰めるので、音の高さもspeed倍になる。

        各サンプルの値は、その区間で出力がHIGHだった時間の割合。1〜3kHzの音は1周期が
        10サンプル前後なので、書き換えの時刻を点で拾うと半周期が揺れて濁る。
        標本の時刻はフレームをまたいでつなげる(端数を捨てると音が欠ける)。
        無音のときは空を返す(keep_silentなら無音の標本をそのまま返す)。
        """
        spc = SPC * speed
        if abs(self.t - c0) > 2 * spc:  # 早送りのあとなど、時刻が飛んだ
            self.t = float(c0)
            self.pending = []
        ev = self.pending + [e for e in events if c0 <= e[0] < c1]
        n = max(0, int((c1 - self.t) / spc))
        out = array("h", bytes(2 * n))
        idx = 0
        mode = self.mode
        silent = True
        x_prev, y, lp = self.x_prev, self.y, self.lp
        t0 = self.t
        for i in range(n):
            t1 = self.t + (i + 1) * spc
            if idx < len(ev) and ev[idx][0] < t1:
                acc = 0.0
                t = t0
                while idx < len(ev) and ev[idx][0] < t1:
                    tc = max(t, ev[idx][0])
                    if tc > t:
                        acc += self._mean(mode, t, tc) * (tc - t)
                    t = tc
                    mode = ev[idx][1]
                    idx += 1
                acc += self._mean(mode, t, t1) * (t1 - t)
                x = acc / (t1 - t0)
            else:
                x = self._mean(mode, t0, t1)
            y = HPF * (y + x - x_prev)
            x_prev = x
            lp = SHELF_A * lp + (1 - SHELF_A) * y
            z = lp + SHELF_G * (y - lp)
            if abs(z) > 1e-3:
                silent = False
            out[i] = int(max(-1.0, min(1.0, z)) * AMP)
            t0 = t1
        self.t = t0
        self.pending = ev[idx:]
        self.mode = mode
        self.x_prev, self.y, self.lp = x_prev, y, lp
        return b"" if silent and not keep_silent else out.tobytes()


# ---- 鳴らす音の出口 ----
# フレームごとにpygame.mixer.Channelへ渡すやり方は、持てる待ちが1つだけで先読みが
# 1フレームぶんほどしかなく、フレームが少し遅れるだけで音が途切れた。ここでは
# pygameが読み込んでいるSDL2のSDL_QueueAudioを使い、標本をSDLの待ち行列に積む。
# 待ち行列にたまっている量(SDL_GetQueuedAudioSize)をフレームの側から見て、進める
# サイクルを少し増減し、たまり具合を目標の近くに保つ。

FRAME_SAMPLES = RATE // 30  # 1フレームぶんの標本(app.FPSは30)
TARGET = FRAME_SAMPLES * 3  # 目標のたまり具合(100ms)
LOW = FRAME_SAMPLES // 2  # 積む時点でこれより少なければ、無音を足して目標まで戻す
LIMIT = RATE // 4  # これより多くたまっていれば、そのフレームの音は積まない(0.25秒)
# 進めるサイクルの細かい増減の上限。clock.tick(30)は1フレームを33msで待つので、
# フレームは30.3回/秒ほどになりうる(1%速い)。装置の時計のずれも見込んで3%までとする
MAX_ADJUST = 0.03
CATCH_UP = 2.0  # 遅れを取り戻すときに、1フレームで余分に進める上限(フレームの数)


class _AudioSpec(ctypes.Structure):  # SDL2のSDL_AudioSpec
    _fields_ = [
        ("freq", ctypes.c_int),
        ("format", ctypes.c_uint16),
        ("channels", ctypes.c_uint8),
        ("silence", ctypes.c_uint8),
        ("samples", ctypes.c_uint16),
        ("padding", ctypes.c_uint16),
        ("size", ctypes.c_uint32),
        ("callback", ctypes.c_void_p),
        ("userdata", ctypes.c_void_p),
    ]


SDL_INIT_AUDIO = 0x10
AUDIO_S16SYS = 0x8010 if sys.byteorder == "little" else 0x9010


def _sdl_library() -> ctypes.CDLL:
    """pygameに入っているSDL2(pygameと同じものを使う)。なければシステムのもの"""
    import ctypes.util

    import pygame

    here = os.path.dirname(pygame.__file__)
    name = re.compile(r"(lib)?SDL2(-[0-9a-f.-]*)?\.(so(\.[0-9]+)*|dylib|dll)", re.IGNORECASE)
    for d in (here, os.path.join(here, ".dylibs"), os.path.join(here, os.pardir, "pygame.libs")):
        for path in sorted(glob.glob(os.path.join(d, "*"))):
            if name.fullmatch(os.path.basename(path)):
                return ctypes.CDLL(path)
    found = ctypes.util.find_library("SDL2")
    if found is None:
        raise OSError("SDL2のライブラリが見つかりません")
    return ctypes.CDLL(found)


class SoundQueue:
    """SDLの待ち行列に標本(16ビット、モノラル)を積む出口"""

    def __init__(self) -> None:
        sdl = _sdl_library()
        sdl.SDL_OpenAudioDevice.restype = ctypes.c_uint32
        sdl.SDL_OpenAudioDevice.argtypes = [
            ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(_AudioSpec),
            ctypes.POINTER(_AudioSpec), ctypes.c_int,
        ]  # fmt: skip
        sdl.SDL_QueueAudio.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]
        sdl.SDL_GetQueuedAudioSize.restype = ctypes.c_uint32
        sdl.SDL_GetQueuedAudioSize.argtypes = [ctypes.c_uint32]
        sdl.SDL_ClearQueuedAudio.argtypes = [ctypes.c_uint32]
        sdl.SDL_PauseAudioDevice.argtypes = [ctypes.c_uint32, ctypes.c_int]
        sdl.SDL_CloseAudioDevice.argtypes = [ctypes.c_uint32]
        sdl.SDL_GetError.restype = ctypes.c_char_p
        if sdl.SDL_InitSubSystem(SDL_INIT_AUDIO) != 0:
            raise OSError(sdl.SDL_GetError().decode(errors="replace"))
        want = _AudioSpec(freq=RATE, format=AUDIO_S16SYS, channels=1, samples=512)
        got = _AudioSpec()
        # 装置の名前をNULLにすると、いまの既定の出力を開く。形式は頼んだとおり
        # (変換はSDLにまかせる。allowed_changes=0)
        dev = sdl.SDL_OpenAudioDevice(None, 0, ctypes.byref(want), ctypes.byref(got), 0)
        if not dev:
            raise OSError(sdl.SDL_GetError().decode(errors="replace"))
        self.sdl, self.dev = sdl, dev
        self.underruns = 0  # 尽きかけて無音を足した回数(途切れの数)
        self.started = False
        sdl.SDL_PauseAudioDevice(dev, 0)

    def level(self) -> int:
        """待ち行列にたまっている標本の数"""
        return self.sdl.SDL_GetQueuedAudioSize(self.dev) // 2

    def push(self, pcm: bytes) -> None:
        level = self.level()
        if level > LIMIT:
            return
        if level < LOW and pcm:  # 尽きかけている(鳴り始めも)。無音を足して先読みを戻す
            if self.started:
                self.underruns += 1
            self.started = True
            need = TARGET - level - len(pcm) // 2
            if need > 0:
                pcm = bytes(2 * need) + pcm
        if pcm:
            self.sdl.SDL_QueueAudio(self.dev, pcm, len(pcm))

    def clear(self) -> None:
        self.sdl.SDL_ClearQueuedAudio(self.dev)
        self.started = False  # 次に積むときは鳴り始めと同じ(途切れとは数えない)

    def close(self) -> None:
        self.sdl.SDL_PauseAudioDevice(self.dev, 1)
        self.sdl.SDL_CloseAudioDevice(self.dev)


def speed_adjust(level: int) -> float:
    """待ち行列のたまり具合から、次のフレームで進めるサイクルの倍率を決める。

    目標との差が1フレームぶんまでは、3%までの増減でゆっくり合わせる(フレームの速さと
    音の装置の時計のずれ)。それより少ないのは、フレームが遅れてエミュレータの進みが
    実時間より遅れたということなので、超えた分を次のフレームでまとめて進めて取り戻す
    (2フレームぶんまで)。ほとんど空のとき(鳴り始め、読み込みのあと、長く止まったあと)は、
    pushが無音を足して目標まで戻すので、取り戻さない"""
    if level < LOW:
        return 1.0
    r = (TARGET - level) / FRAME_SAMPLES
    return 1 + MAX_ADJUST * max(-1.0, min(1.0, r)) + min(CATCH_UP, max(0.0, r - 1))
