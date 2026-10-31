"""圧電ブザーの音と、音の出力先

Cポートのビット6〜4で出力が決まる(POPCOMの講座の表7、PockEmulのcompute_xout)。

    0, 4  LOW        1, 5  HIGH
    2     2kHzの発振  3     4kHzの発振
    6, 7  カセット入力をそのまま出す(ここでは無音)

BEEP文は3を使い、マシン語は5と4を交互に書いて振動板を直接動かすことが多い。
"""

import ctypes
import glob
import math
import os
import random
import re
import sys
from array import array

from .i18n import tr
from .machine import CLOCK

RATE = 44100  # 22050Hzでは方形波の高調波の折り返しが耳につく
AMP = 9000
# 圧電素子は低音を返さない。50Hzと500Hzから下を一次のハイパスで切る。500Hzのほうは、出力を
# HIGHにしたまま数ms置いたときの段差(PC-1350のROMが計算のたびにする)を小さな音にするため
HPF = 1.0 - 2 * math.pi * 50 / RATE
HPF2 = 1.0 - 2 * math.pi * 500 / RATE
# 1.5kHzより上を約6dB下げる一次のシェルフ(方形波のままでは実機より軽い音になる)
SHELF_A = math.exp(-2 * math.pi * 1500 / RATE)
SHELF_G = 0.5
SPC = CLOCK / RATE  # 1サンプルあたりのCPUサイクル(約4.4)
OSC_HALF = {2: CLOCK / 2000 / 2, 3: CLOCK / 4000 / 2}  # 内蔵発振の半周期(サイクル)


class Buzzer:
    def __init__(self):
        self.mode = 0  # 次のサンプルの始まりでの出力
        self.t = 0.0  # 次のサンプルの始まりのサイクル
        self.pending: list[tuple[int, int]] = []  # サンプルにまだ入れていない書き込み
        self.x_prev = -1.0  # LOWから始める(0から始めると最初に1回鳴る)
        self.y = 0.0
        self.y2 = 0.0  # 500Hzのハイパスの出力
        self.lp = 0.0  # シェルフの低域側

    def hold(self, mode: int) -> None:
        """サンプルを作らずに時間が進んだとき(早送り中など)に呼び、modeのまま落ち着いた状態に
        する。次にサンプルを作り始めたときに、前の状態との差で1回鳴らないように"""
        self.mode = mode
        self.x_prev = 1.0 if mode in (1, 5) else 0.0 if mode in OSC_HALF else -1.0
        self.y = self.y2 = self.lp = 0.0
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
        speedは速さの倍率で、音の高さもspeed倍になる。

        サンプルの値は、その区間で出力がHIGHだった時間の割合から作る(1〜3kHzの音は1周期が
        10サンプルほどなので、書き換えの時刻を点で拾うと濁る)。無音なら空を返す
        (keep_silentなら無音のサンプルを返す)。
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
        x_prev, y, y2, lp = self.x_prev, self.y, self.y2, self.lp
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
            y_new = HPF * (y + x - x_prev)
            y2 = HPF2 * (y2 + y_new - y)
            y = y_new
            x_prev = x
            lp = SHELF_A * lp + (1 - SHELF_A) * y2
            z = lp + SHELF_G * (y2 - lp)
            if abs(z) > 1e-3:
                silent = False
            out[i] = int(max(-1.0, min(1.0, z)) * AMP)
            t0 = t1
        self.t = t0
        self.pending = ev[idx:]
        self.mode = mode
        self.x_prev, self.y, self.y2, self.lp = x_prev, y, y2, lp
        return b"" if silent and not keep_silent else out.tobytes()


# ---- プリンタの音 ----
# 感熱プリンタ(CE-126P)の音は、紙を送るステッピングモータのステップの連なり。ステップごとに
# 短い雑音を入れ、3つの共振(周波数、減衰、大きさ)で色をつける。値はCE-126Pの録音に合わせた
# (ステップの速さは自己相関、共振は帯域ごとの強さが録音と同じになる組み合わせを探した)。
# 紙が動いているあいだ鳴らす。印字の速さ(1行0.96秒、行のあいだ0.06秒)も同じ録音から
PRINT_STEP = RATE // 147  # ステップの間隔(サンプル)
PRINT_BURST = 10  # ステップごとに入れる雑音の長さ(サンプル)
PRINT_NOISE = 0.6  # ステップのあいだも続く雑音の大きさ
PRINT_EMPHASIS = 0.95  # 続く雑音の高域の強め方(前のサンプルを引く割合)
PRINT_RESONANCES = ((1000.0, 0.002, 0.5), (3500.0, 0.003, 2.0), (5300.0, 0.002, 3.0))
PRINT_AMP = 12000 / 25  # 共振の出力(最大25ほど)を16ビットの振幅にする
PRINT_ATTACK = 1 / (0.05 * RATE)  # 動き始めに音量が上がる速さ
PRINT_RELEASE = 1 / (0.01 * RATE)  # 止まるときに音量が下がる速さ
PRINT_LINE = 0.96  # 1行を印字する時間(秒)
PRINT_GAP = 0.06  # 行と行のあいだ(秒)
PRINT_KEEP = 3  # 紙に出していない行がこれより多ければ、速めて出す
PRINT_CATCH_UP = 2.5  # 速めるとき、出していない行をこの秒数で出し切る


class _Resonator:
    """2次の共振。freqで鳴り、decay秒で1/eに減る"""

    def __init__(self, freq: float, decay: float) -> None:
        r = math.exp(-1 / (decay * RATE))
        self.a1 = 2 * r * math.cos(2 * math.pi * freq / RATE)
        self.a2 = -r * r
        self.y1 = self.y2 = 0.0

    @property
    def ringing(self) -> bool:
        return abs(self.y1) > 1e-3 or abs(self.y2) > 1e-3

    def step(self, x: float) -> float:
        y = x + self.a1 * self.y1 + self.a2 * self.y2
        self.y2, self.y1 = self.y1, y
        return y


class PrinterSound:
    """紙を送っているあいだのプリンタの音。mix()で本体の音のサンプルに足す"""

    def __init__(self) -> None:
        self.rng = random.Random(1350)
        self.gain = 0.0  # 音量の包絡(0〜1)
        self.until = 0  # 次のステップまでのサンプル数
        self.burst = 0  # ステップの雑音の残りのサンプル数
        self.prev = 0.0  # 続く雑音の前のサンプル(高域を強めるために差を取る)
        self.res = [(_Resonator(f, d), g) for f, d, g in PRINT_RESONANCES]

    @property
    def active(self) -> bool:
        return self.gain > 0.002 or any(r.ringing for r, _g in self.res)

    def mix(self, pcm: bytes, running: bool, speed: float = 1.0) -> bytes:
        """pcm(16ビットのサンプル。無音なら空でもよい)にプリンタの音を足す。runningは紙が
        動いているか、speedは紙送りが実機の何倍の速さか。鳴らすものがなければpcmをそのまま返す"""
        if not running and not self.active:
            return pcm
        n = len(pcm) // 2 or FRAME_SAMPLES
        out = array("h", pcm) if pcm else array("h", bytes(2 * n))
        target, rate = (1.0, PRINT_ATTACK) if running else (0.0, PRINT_RELEASE)
        gain, until, burst, prev, rng = self.gain, self.until, self.burst, self.prev, self.rng
        res = self.res
        step = round(PRINT_STEP / min(speed, 4))  # 4倍より速いステップは音が高くなって耳につく
        for i in range(n):
            gain += (target - gain) * rate
            x = 0.0
            if gain > 0.002:
                if until <= 0:
                    until = step + rng.randint(-3, 3)
                    burst = PRINT_BURST
                until -= 1
                if burst > 0:
                    x += (rng.random() - 0.5) * 2 * burst / PRINT_BURST
                    burst -= 1
                w = (rng.random() - 0.5) * PRINT_NOISE
                x += w - PRINT_EMPHASIS * prev
                prev = w
                x *= gain
            v = 0.0
            for r, g in res:
                v += g * r.step(x)
            s = out[i] + int(max(-25.0, min(25.0, v)) * PRINT_AMP)
            out[i] = max(-32768, min(32767, s))
        self.gain, self.until, self.burst, self.prev = gain, until, burst, prev
        return out.tobytes()


# ---- 音の出力先 ----
# サンプルはSDL2のSDL_QueueAudioでキューに積む(pygame.mixer.Channelは待ちを1つしか持てず、
# フレームが少し遅れると途切れる)。たまっている量を見て、進めるサイクルを少し増減する。

FRAME_SAMPLES = RATE // 30  # 1フレームぶんのサンプル(app.FPSは30)
TARGET = FRAME_SAMPLES * 3  # 目標のたまり具合(100ms)
LOW = FRAME_SAMPLES // 2  # これより少なければ、無音を足して目標まで戻す
LIMIT = RATE // 4  # これより多くたまっていれば、そのフレームの音は積まない
MAX_ADJUST = 0.03  # 進めるサイクルの細かい増減の上限(フレームの速さと装置の時計のずれ)
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
    dirs = [here, os.path.join(here, ".dylibs")]
    # Linuxのwheelは、隣のpygame.libs(pygame-ceはpygame_ce.libs)に入れる
    dirs += [os.path.join(here, os.pardir, x) for x in ("pygame.libs", "pygame_ce.libs")]
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*"))):
            if name.fullmatch(os.path.basename(path)):
                return ctypes.CDLL(path)
    found = ctypes.util.find_library("SDL2")
    if found is None:
        raise OSError(tr("SDL2のライブラリが見つかりません"))
    return ctypes.CDLL(found)


class SoundQueue:
    """SDLのキューにサンプル(16ビット、モノラル)を積む出力先"""

    keep_silent = True  # 無音のサンプルも積んで、たまり具合を保つ

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
        # 既定の出力を、頼んだ形式で開く(変換はSDLにまかせる)
        dev = sdl.SDL_OpenAudioDevice(None, 0, ctypes.byref(want), ctypes.byref(got), 0)
        if not dev:
            raise OSError(sdl.SDL_GetError().decode(errors="replace"))
        self.sdl, self.dev = sdl, dev
        self.underruns = 0  # 尽きかけて無音を足した回数
        self.started = False
        sdl.SDL_PauseAudioDevice(dev, 0)

    def level(self) -> int:
        """キューにたまっているサンプルの数"""
        return self.sdl.SDL_GetQueuedAudioSize(self.dev) // 2

    def push(self, pcm: bytes) -> None:
        level = self.level()
        if level > LIMIT:
            return
        if level < LOW and pcm:  # 尽きかけている(鳴り始めも)
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
        self.started = False

    def close(self) -> None:
        self.sdl.SDL_PauseAudioDevice(self.dev, 1)
        self.sdl.SDL_CloseAudioDevice(self.dev)


def speed_adjust(level: int) -> float:
    """キューのたまり具合から、次のフレームで進めるサイクルの倍率を決める。

    目標との差が1フレームぶんまでは3%までの増減で合わせ、それより少なければ(フレームが
    遅れた)超えた分を次のフレームで取り戻す。ほとんど空のときはpushが無音を足すので、
    取り戻さない"""
    if level < LOW:
        return 1.0
    r = (TARGET - level) / FRAME_SAMPLES
    return 1 + MAX_ADJUST * max(-1.0, min(1.0, r)) + min(CATCH_UP, max(0.0, r - 1))


class MixerOutput:
    """pygame.mixerのChannelで鳴らす出力先(SDLのキューが使えないとき)。Channelは待ちを
    1つしか持てないので、空くまでこちらでためておく"""

    keep_silent = False  # 無音のフレームには空を渡し、たまった残りをすぐ鳴らす
    PREBUFFER = FRAME_SAMPLES * 2 * 2  # 鳴り始めに2フレームぶんためる(16ビット)
    MAX_PENDING = RATE // 4 * 2  # これより遅れたら古い音を捨てる(16ビット)

    def __init__(self) -> None:
        import pygame

        pygame.mixer.init(RATE, -16, 1, 512, allowedchanges=0)
        opened = pygame.mixer.get_init()
        if opened is None:
            raise OSError(tr("ミキサーを開けません"))
        freq, _, channels = opened
        if freq != RATE:
            raise OSError(tr("ミキサーが{freq}Hzで開かれました", freq=freq))
        self.channel = pygame.mixer.Channel(0)
        self.channels = channels
        self.wait = bytearray()

    def level(self) -> int:
        return TARGET  # たまり具合は見えないので、進める速さは変えない

    def push(self, pcm: bytes) -> None:
        import pygame

        if pcm and self.channels > 1:  # 同じサンプルを各チャンネルに並べる
            mono = array("h", pcm)
            multi = array("h", bytes(len(pcm) * self.channels))
            for ch in range(self.channels):
                multi[ch :: self.channels] = mono
            pcm = multi.tobytes()
        self.wait += pcm
        limit = self.MAX_PENDING * self.channels
        if len(self.wait) > limit:
            del self.wait[: len(self.wait) - limit]
        if not self.wait:
            return
        if not self.channel.get_busy():
            if pcm and len(self.wait) < self.PREBUFFER * self.channels:
                return
            self.channel.play(pygame.mixer.Sound(buffer=bytes(self.wait)))
            self.wait.clear()
        elif self.channel.get_queue() is None:
            self.channel.queue(pygame.mixer.Sound(buffer=bytes(self.wait)))
            self.wait.clear()

    def clear(self) -> None:
        pass

    def close(self) -> None:
        pass


def open_output() -> "SoundQueue | MixerOutput | None":
    """音の出力先を開く。SDLのキューが使えなければpygame.mixer、それもだめならNone"""
    import pygame

    pygame.mixer.quit()  # pygame.initが開いたmixerの装置は使わない
    try:
        return SoundQueue()
    except (OSError, AttributeError) as e:
        print(tr("SDLのキューが使えないので、mixerで鳴らします({error})", error=e), file=sys.stderr)
    try:
        return MixerOutput()
    except (OSError, pygame.error) as e:
        print(tr("音を切ります({error})", error=e), file=sys.stderr)
    return None
