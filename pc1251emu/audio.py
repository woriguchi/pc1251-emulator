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

from array import array

from .machine import CLOCK

RATE = 22050
AMP = 9000
HPF = 0.985  # 圧電素子は低音を返さない。一次のハイパス
SPC = CLOCK / RATE  # 1サンプルあたりのCPUサイクル(約8.7)
OSC_HALF = {2: CLOCK / 2000 / 2, 3: CLOCK / 4000 / 2}  # 内蔵発振の半周期(サイクル)
SUB = 4  # 内蔵発振を1サンプルの中で見る点の数


class Buzzer:
    def __init__(self):
        self.mode = 0
        self.x_prev = 0.0
        self.y = 0.0

    @staticmethod
    def _mean(mode: int, t0: float, t1: float) -> float:
        """サイクルt0〜t1の出力の平均(-1〜1)"""
        if mode in (1, 5):
            return 1.0
        half = OSC_HALF.get(mode)
        if half is None:
            return -1.0
        acc = 0.0
        step = (t1 - t0) / SUB
        for k in range(SUB):
            acc += 1.0 if int((t0 + (k + 0.5) * step) / half) % 2 == 0 else -1.0
        return acc / SUB

    def render(self, events: list[tuple[int, int]], c0: int, c1: int) -> bytes:
        """サイクルc0〜c1ぶんのPCMを作る。eventsは(サイクル, モード)の列。

        PC-インタープリタは1〜3kHzの音を、Cポートを書き換える間隔で作る。1周期が
        10サンプル前後しかないので、書き換えの時刻をサンプルの点で拾うと、半周期の
        長さが1サンプルずつ揺れて濁った音になる。そこで各サンプルの区間で、出力が
        HIGHだった時間の割合を平均して値にする。
        """
        n = max(1, int((c1 - c0) / SPC))
        out = array("h", bytes(2 * n))
        ev = [e for e in events if c0 <= e[0] < c1]
        idx = 0
        mode = self.mode
        silent = True
        x_prev, y = self.x_prev, self.y
        for i in range(n):
            t0 = c0 + i * SPC
            t1 = t0 + SPC
            if idx < len(ev) and ev[idx][0] < t1:
                acc = 0.0
                t = t0
                while idx < len(ev) and ev[idx][0] < t1:
                    tc = max(t, ev[idx][0])
                    acc += self._mean(mode, t, tc) * (tc - t) if tc > t else 0.0
                    t = tc
                    mode = ev[idx][1]
                    idx += 1
                acc += self._mean(mode, t, t1) * (t1 - t)
                x = acc / SPC
            else:
                x = self._mean(mode, t0, t1)
            y = HPF * (y + x - x_prev)
            x_prev = x
            if abs(y) > 1e-3:
                silent = False
            out[i] = int(max(-1.0, min(1.0, y)) * AMP)
        while idx < len(ev):
            mode = ev[idx][1]
            idx += 1
        self.mode = mode
        self.x_prev, self.y = x_prev, y
        return b"" if silent else out.tobytes()
