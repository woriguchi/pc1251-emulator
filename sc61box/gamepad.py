"""ゲームパッドでポケコンのキーを押す

OSにつながっているゲームパッドのうち、SDLのGameControllerの対応表にあるもの(8BitDo、Xbox、
PlayStation、Switchのコントローラなど)を使う。ボタン、十字キー、スティックの向き、トリガーの
それぞれに、ポケコンのキーを1つ割り当てる(PadMap)。割り当ては、読み込んだプログラムの
「# pad:」の行、置き場所に保存した自分の割り当て、既定の順に決まる(App.pad_map_for)。

PadMapは画面を持たず、試験から直接使える。パッドのイベントを入力の名前に直すのはPads。
"""

import json
import os

import pygame
from pygame._sdl2 import controller

from . import machine

# 入力の名前はSDLの対応表の書き方(a、dpup、leftshoulderなど)。表示はLABELS
BUTTONS = {
    pygame.CONTROLLER_BUTTON_A: "a",
    pygame.CONTROLLER_BUTTON_B: "b",
    pygame.CONTROLLER_BUTTON_X: "x",
    pygame.CONTROLLER_BUTTON_Y: "y",
    pygame.CONTROLLER_BUTTON_BACK: "back",
    pygame.CONTROLLER_BUTTON_START: "start",
    pygame.CONTROLLER_BUTTON_GUIDE: "guide",
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "leftshoulder",
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "rightshoulder",
    pygame.CONTROLLER_BUTTON_LEFTSTICK: "leftstick",
    pygame.CONTROLLER_BUTTON_RIGHTSTICK: "rightstick",
    pygame.CONTROLLER_BUTTON_DPAD_UP: "dpup",
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: "dpdown",
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: "dpleft",
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "dpright",
}
# 軸: (負の向きの入力, 正の向きの入力)。スティックは十字キーと同じ入力にする
AXES = {
    pygame.CONTROLLER_AXIS_LEFTX: ("dpleft", "dpright"),
    pygame.CONTROLLER_AXIS_LEFTY: ("dpup", "dpdown"),
    pygame.CONTROLLER_AXIS_RIGHTX: ("dpleft", "dpright"),
    pygame.CONTROLLER_AXIS_RIGHTY: ("dpup", "dpdown"),
    pygame.CONTROLLER_AXIS_TRIGGERLEFT: (None, "lefttrigger"),
    pygame.CONTROLLER_AXIS_TRIGGERRIGHT: (None, "righttrigger"),
}
PRESS, RELEASE = 0.5, 0.3  # 軸をこの割合より倒すと押したことに、戻すと離したことにする

ORDER = (
    "dpup", "dpdown", "dpleft", "dpright", "a", "b", "x", "y",
    "leftshoulder", "rightshoulder", "lefttrigger", "righttrigger",
    "back", "start", "leftstick", "rightstick", "guide",
)  # fmt: skip
LABELS = {
    "dpup": "↑", "dpdown": "↓", "dpleft": "←", "dpright": "→",
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "leftshoulder": "L", "rightshoulder": "R", "lefttrigger": "ZL", "righttrigger": "ZR",
    "back": "Select", "start": "Start", "leftstick": "L3", "rightstick": "R3", "guide": "Home",
}  # fmt: skip

# 割り当てられるポケコンのキーの名前(全機種のキーとBRK)
KEY_NAMES = frozenset(machine.KEYS) | frozenset(machine.KEYS_1350) | {"BRK"}


def key_names(family: str) -> frozenset[str]:
    """機種の系列familyで割り当てられるキーの名前"""
    return frozenset(machine.KEYS_1350 if family == "1350" else machine.KEYS) | {"BRK"}


DEFAULT = {
    "dpup": "8", "dpdown": "2", "dpleft": "4", "dpright": "6",
    "a": "SPC", "b": "0", "start": "ENTER", "back": "BRK",
}  # fmt: skip


class PadMap:
    """入力の名前からポケコンのキーの名前への割り当て。sourceは割り当ての出どころの説明"""

    def __init__(self, keys: dict[str, str] | None = None, source: str = "") -> None:
        self.keys = dict(DEFAULT if keys is None else keys)
        self.source = source

    def get(self, name: str) -> str | None:
        return self.keys.get(name)

    def set(self, name: str, key: str | None) -> None:
        if key is None:
            self.keys.pop(name, None)
        else:
            self.keys[name] = key

    def copy(self, source: str) -> "PadMap":
        return PadMap(self.keys, source)

    def text(self) -> str:
        """# pad: の行の値(「dpup=8 dpdown=2 a=SPC」)"""
        return " ".join(f"{name}={self.keys[name]}" for name in ORDER if name in self.keys)

    @classmethod
    def parse(
        cls, value: str, source: str = "", names: frozenset[str] = KEY_NAMES
    ) -> tuple["PadMap", list[str]]:
        """# pad: の値を読む。読めなかった語も返す(入力の名前が違うものと、キーの名前が
        namesにないもの)。区切りは空白だけ(PC-1350には「,」のキーがある)"""
        keys: dict[str, str] = {}
        bad = []
        for word in value.split():
            name, _, key = word.partition("=")
            name, key = name.lower(), key.upper()
            if name not in ORDER or key not in names:
                bad.append(word)
                continue
            keys[name] = key
        return cls(keys, source), bad

    @classmethod
    def load(cls, path: str, source: str) -> "PadMap | None":
        """保存した割り当てを読む。なければ、読めなければNone"""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        keys = {
            n: k for n, k in data.items() if n in ORDER and isinstance(k, str) and k in KEY_NAMES
        }
        return cls(keys, source)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({name: self.keys[name] for name in ORDER if name in self.keys}, f, indent=1)


class Pads:
    """つながっているゲームパッドと、押している入力。pygameのイベントから入力の名前の
    押す・離すを作る(handle)。同じ入力を十字キーとスティックの両方から押せるので、入力ごとに
    押している元(ボタンか、どの軸か)を覚え、すべて離れたときに離す"""

    def __init__(self) -> None:
        self.devices: dict[int, controller.Controller] = {}  # instance_id: 開いたコントローラ
        # (instance_id, 入力の名前): 押している元の集まり("button"か軸の番号)
        self.held: dict[tuple[int, str], set[int | str]] = {}
        self.axis_on: dict[tuple[int, int], str] = {}  # (instance_id, 軸): 倒している向きの入力
        try:
            controller.init()
            if hasattr(controller, "set_eventstate"):  # pygame-ceはinit()で有効になる
                controller.set_eventstate(True)
            for i in range(controller.get_count()):
                self._open(i)
        except pygame.error:
            pass

    def _open(self, index: int) -> None:
        if not controller.is_controller(index):
            return
        try:
            c = controller.Controller(index)
        except pygame.error:
            return
        self.devices[c.as_joystick().get_instance_id()] = c

    def names(self) -> list[str]:
        return [c.name for c in self.devices.values()]

    def pressed(self) -> set[str]:
        """いま押している入力の名前"""
        return {name for _iid, name in self.held}

    def handle(self, ev) -> list[tuple[str, int, bool]]:
        """イベントを(入力の名前, instance_id, 押したか)の列にする。パッドを外したときは、
        押していた入力を離す"""
        t = ev.type
        if t == pygame.CONTROLLERDEVICEADDED:
            self._open(ev.device_index)
            return []
        if t == pygame.CONTROLLERDEVICEREMOVED:
            self.devices.pop(ev.instance_id, None)
            return self._release(lambda iid: iid == ev.instance_id)
        if t in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            name = BUTTONS.get(ev.button)
            if name is None:
                return []
            return self._change(ev.instance_id, name, "button", t == pygame.CONTROLLERBUTTONDOWN)
        if t == pygame.CONTROLLERAXISMOTION and ev.axis in AXES:
            return self._axis(ev.instance_id, ev.axis, ev.value / 32767)
        return []

    def _change(
        self, iid: int, name: str, by: int | str, pressed: bool
    ) -> list[tuple[str, int, bool]]:
        """元byが入力nameを押した・離した。入力が押されていない状態から押されたとき、
        押している元がなくなったときだけ、押す・離すを返す"""
        key = (iid, name)
        sources = self.held.get(key, set())
        if pressed:
            was = bool(sources)
            sources.add(by)
            self.held[key] = sources
            return [] if was else [(name, iid, True)]
        sources.discard(by)
        if sources or key not in self.held:
            return []
        del self.held[key]
        return [(name, iid, False)]

    def _axis(self, iid: int, axis: int, value: float) -> list[tuple[str, int, bool]]:
        """軸の値から、倒した向きの入力を押す・離す。PRESSを越えて押し、倒している向きの値が
        RELEASEを下回って(反対側へ越えたときも)離す"""
        minus, plus = AXES[axis]
        now = self.axis_on.get((iid, axis))
        want = now
        if now is not None and value * (1 if now == plus else -1) < RELEASE:
            want = None
        if abs(value) > PRESS:
            want = plus if value > 0 else minus
        if want == now:
            return []
        out = []
        if now is not None:
            out += self._change(iid, now, axis, False)
        if want is not None:
            out += self._change(iid, want, axis, True)
            self.axis_on[(iid, axis)] = want
        else:
            self.axis_on.pop((iid, axis), None)
        return out

    def _release(self, which) -> list[tuple[str, int, bool]]:
        """which(instance_id)が真のパッドの、押している入力をすべて離す"""
        out = [(name, iid, False) for iid, name in self.held if which(iid)]
        for name, iid, _ in out:
            del self.held[(iid, name)]
        for key in [k for k in self.axis_on if which(k[0])]:
            del self.axis_on[key]
        return out

    def release_all(self) -> list[tuple[str, int, bool]]:
        """押している入力をすべて離す(割り当てを変える前など)"""
        return self._release(lambda _iid: True)

    def sync(self) -> list[tuple[str, int, bool]]:
        """外れたのにイベントが来なかったパッドを閉じ、押していた入力を離す。pygame 2.6までは、
        つないだときのイベントを取り出す前に外れたパッド(Joy-Conを2つつないで1つにまとめた
        ときなど)でpygame.event.get()がKeyErrorになり(pygame/pygame#3634)、その回の
        イベントが失われる"""
        gone = []
        for iid, c in self.devices.items():
            try:
                attached = c.attached()
            except pygame.error:
                attached = False
            if not attached:
                gone.append(iid)
        for iid in gone:
            del self.devices[iid]
        return self._release(lambda iid: iid in gone)
