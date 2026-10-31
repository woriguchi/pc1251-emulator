"""カセットの音(wav)の書き出しと読み込み

書き出しは、CSAVEがCポートのビット4〜6を3(内蔵の4kHzの発振)と2(2kHzの発振)に
切り替える時刻から波形を作る。192kHzのCLOCKは48kHzの4倍なので、サンプル1つが4サイクル。

読み込みは、wavの波形を0と1の列に直し、ROMがXin(TESTのビット7、CUP・CDN)を読んだ
時刻の値を返す。再生はROMが初めてXinを読んだときに始まる。
"""

import bisect
import os
import wave
from array import array

from .autotype import Typer
from .machine import CLOCK, new_machine

RATE = 48000
SPS = CLOCK // RATE  # 1サンプルあたりのサイクル(4)
OSC = {2: CLOCK // 2000, 3: CLOCK // 4000}  # 内蔵発振の周期(サイクル)
AMP = 22000


def render(events: list[tuple[int, int]], c0: int, c1: int) -> array:
    """サイクルc0〜c1の音を16ビットのサンプルの列にする。eventsは(サイクル, モード)の列"""
    n = (c1 - c0) // SPS
    out = array("h", bytes(2 * n))
    ev = sorted(e for e in events if e[0] < c1)
    mode = 0
    k = 0
    while k < len(ev) and ev[k][0] <= c0:
        mode = ev[k][1]
        k += 1
    for i in range(n):
        c = c0 + i * SPS
        while k < len(ev) and ev[k][0] <= c:
            mode = ev[k][1]
            k += 1
        period = OSC.get(mode)
        if period:  # 発振は回り続けているので、位相は通しのサイクルで決まる
            out[i] = AMP if c % period < period // 2 else -AMP
    return out


def write_wav(path: str, samples: array) -> None:
    # ファイルを先に開く(開けないときに、作りかけのwave.Wave_writeが後始末で警告を出さない)
    with open(path, "wb") as f, wave.open(f, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())


class TapeOut:
    """Cポートに出る音を見張り、CSAVEの音を取り出す。

    内蔵の発振が鳴り始めてから、音が止まって1秒たつまでをひと続きとみる。BEEPも4kHzの
    発振を使うので、2秒以上続き、2kHzへの切り替えが何度もあるものだけをCSAVEの音とする。
    """

    QUIET = CLOCK  # 音が止まってからこれだけたったら、ひと続きの終わり
    MIN_LEN = 2 * CLOCK
    MIN_LOW = 16  # 2kHzへの切り替えの回数(データの0のビット)

    def __init__(self) -> None:
        self.ev: list[tuple[int, int]] | None = None
        self.last = 0
        self.lows = 0

    def feed(self, events: list[tuple[int, int]], cycle: int, mode: int) -> array | None:
        """1フレームぶんの音の切り替え(サイクル, モード)と、いまのサイクルとモードを渡す。
        CSAVEの音がひと続き終わったときに、そのサンプルの列を返す"""
        for c, v in events:
            if self.ev is None:
                if v in OSC:
                    self.ev, self.last, self.lows = [(c, v)], c, 0
                continue
            self.ev.append((c, v))
            self.last = c
            self.lows += v == 2
        if self.ev is None:
            return None
        if mode in OSC:  # まだ鳴っている
            self.last = cycle
            return None
        if cycle - self.last < self.QUIET:
            return None
        ev, self.ev = self.ev, None
        start = ev[0][0]
        if self.last - start < self.MIN_LEN or self.lows < self.MIN_LOW:
            return None
        return render(ev, start - CLOCK // 5, self.last + CLOCK * 3 // 10)


class TapeIn:
    """wavのテープ。level(サイクル)でその時刻のXinを返す"""

    def __init__(self, path: str):
        with wave.open(path, "rb") as w:
            ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
        vals = _samples(raw, width)[::ch]  # 2チャンネルなら左だけ
        peak = max((abs(v) for v in vals), default=0) or 1
        hi, lo = peak * 0.15, -peak * 0.15  # 雑音で細かく反転しないように幅を持たせる
        level = 0
        self.edges: list[float] = []  # 値が変わる時刻(再生を始めてからのサイクル)
        for i, v in enumerate(vals):
            new = 1 if v > hi else 0 if v < lo else level
            if new != level:
                level = new
                self.edges.append(i * CLOCK / rate)
        self.length = len(vals) * CLOCK / rate
        self.start: int | None = None
        self.path = path

    def level(self, cycle: int) -> int:
        if self.start is None:
            self.start = cycle
        t = cycle - self.start
        if t >= self.length:
            return 0
        return bisect.bisect_right(self.edges, t) & 1

    def done(self, cycle: int) -> bool:
        return self.start is not None and cycle - self.start >= self.length


def _samples(raw: bytes, width: int) -> list[int]:
    if width == 1:  # 8ビットは0〜255で、128が真ん中
        return [b - 128 for b in raw]
    if width == 2:
        return list(array("h", raw))
    if width == 3:
        return [
            int.from_bytes(raw[i : i + 3], "little", signed=True) for i in range(0, len(raw), 3)
        ]
    return list(array("i", raw))


# ---- エミュレータでCSAVEさせて録る ----
def _finish(m, t: Typer) -> None:
    """Typerが打ち終わるまで本体を動かす"""
    while t.busy:
        t.step()
        m.run(CLOCK // 200)


def _type(m, text: str, mode: str | None = None) -> None:
    t = Typer(m)
    if mode:
        t.add_mode(mode)
    t.add_text(text)
    _finish(m, t)


def record(m, command: str) -> array:
    """RUNモードでcommand(CSAVEかCSAVE M)を打って実行し、出てきた音を返す"""
    mode_key = m.model.family == "1350"  # PC-1350はMODEキーでRUNにする
    if not mode_key:
        m.mode = "RUN"
    m.run(CLOCK // 5)
    m.sound_events.clear()
    c0 = m.cpu.cycles
    mode0 = m.pc_out >> 4
    _type(m, command + "\n", "RUN" if mode_key else None)
    quiet = 0
    while quiet < 10:  # 音が止まって1秒たつまで(前置きの音は8秒続く)
        n = len(m.sound_events)
        m.run(CLOCK // 10)
        busy = len(m.sound_events) != n or (m.pc_out >> 4) in OSC
        quiet = 0 if busy else quiet + 1
    ev = [(c0, mode0)] + m.sound_events
    sound = [c for c, v in ev if v in OSC]
    if not sound:
        raise RuntimeError(f"{command}: 音が出なかった")
    start = sound[0] - CLOCK // 5
    end = max(c for c, _v in ev) + CLOCK * 3 // 10
    return render(ev, start, end)


# ---- プログラムのファイルからテープを作る ----
def tape_name(name: str) -> str:
    """CSAVEに付ける名前(英字と数字だけで7字まで)"""
    out = "".join(ch for ch in name.upper() if ch.isascii() and ch.isalnum())[:7]
    return out or "PROG"


GAP = 32  # ダンプの塊のあいだがこれ以下なら、すき間ごと1本のテープにする


def merge_ranges(blocks: list[tuple[int, bytes]]) -> list[tuple[int, int]]:
    """ダンプの行を、テープに録る番地の範囲(始め, 終わり)にまとめる"""
    out: list[list[int]] = []
    for addr, data in sorted(blocks):
        end = addr + len(data) - 1
        if out and addr - out[-1][1] - 1 <= GAP:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([addr, end])
    return [(a, b) for a, b in out]


def program_wavs(prog, model: str, out_dir: str) -> list[tuple[str, str]]:
    """プログラム(programs.Program)を読み込み、ROMにCSAVE・CSAVE Mさせてwavにする。
    (ファイル, 実機で打つ読み込みの命令)の列を返す。BASICが先、ダンプが後"""
    m = new_machine(model)
    m.run(CLOCK)
    name = tape_name(prog.name)
    if prog.basic:
        t = Typer(m)
        t.add_mode("PRO")
        t.add_text("NEW\n")
        t.add_program(prog.basic)
        t.add_mode("RUN")
        _finish(m, t)
    for addr, data in prog.blocks + prog.after:  # 打ち込みで消えないよう、BASICのあとで書く
        for i, b in enumerate(data):
            m.write(addr + i, b)
    ranges = merge_ranges(prog.blocks + prog.after)
    os.makedirs(out_dir, exist_ok=True)
    out = []
    if prog.basic:
        path = os.path.join(out_dir, f"{prog.name}.wav")
        write_wav(path, record(m, f'CSAVE "{name}"'))
        out.append((path, f'CLOAD "{name}"'))
    for k, (addr, end) in enumerate(ranges):
        suffix = "-m" if len(ranges) == 1 else f"-m{k + 1}"
        path = os.path.join(out_dir, f"{prog.name}{suffix}.wav")
        write_wav(path, record(m, f'CSAVE M "{name}";&{addr:04X},&{end:04X}'))
        out.append((path, f'CLOAD M "{name}"'))
    return out
