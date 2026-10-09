"""PC-1251/PC-1245エミュレータの画面とキー操作

uv run pc1251                 # 起動
uv run pc1251 --model 1245    # PC-1245として起動する
uv run pc1251 --type prog.bas # 起動後にファイルの中身をキー入力する
uv run pc1251 --load dump.txt # 16進ダンプをRAMへ書き込む
uv run pc1251 primes --run    # 置き場所のprimes.basを読み込んで実行する
"""

import os
import subprocess
import sys
import time
import wave
from array import array
from types import SimpleNamespace

import pygame
import typer

from . import basictext, display, programs, tape
from .audio import RATE, Buzzer, SoundQueue, speed_adjust
from .keytype import keys_for, keys_for_program
from .machine import CLOCK, MODELS, PC1251, RomNotFound

FPS = 30
STATE_DIR = os.path.expanduser("~/.pc1251")
RAM_FILE = os.path.join(STATE_DIR, "ram.bin")


def ram_file(model: str = "1251") -> str:
    """終了時にRAMを保存するファイル。RAMの大きさが違うので機種ごとに分ける"""
    return RAM_FILE if model == "1251" else os.path.join(STATE_DIR, f"ram-{model}.bin")


# そのまま押しっぱなしで伝えるキー
DIRECT = {
    pygame.K_RETURN: "ENTER",
    pygame.K_KP_ENTER: "ENTER",
    pygame.K_SPACE: "SPC",
    pygame.K_UP: "UP",
    pygame.K_DOWN: "DOWN",
    pygame.K_LEFT: "LEFT",
    pygame.K_RIGHT: "RIGHT",
    pygame.K_TAB: "SHIFT",
    pygame.K_LALT: "DEF",
    pygame.K_RALT: "DEF",
    pygame.K_DELETE: "CL",
}
DIGITS = {}
for _i in range(10):
    DIGITS[getattr(pygame, f"K_{_i}")] = str(_i)
    DIGITS[getattr(pygame, f"K_KP{_i}")] = str(_i)
LETTERS = {getattr(pygame, f"K_{_c}"): _c.upper() for _c in "abcdefghijklmnopqrstuvwxyz"}
# 矢印キーを数字キーの8・2・4・6として押すモード(テンキーのないパソコン用)
NUMPAD_ARROWS = {pygame.K_UP: "8", pygame.K_DOWN: "2", pygame.K_LEFT: "4", pygame.K_RIGHT: "6"}
# 記号はキーボードの配列によって位置が違うので、打たれた文字(TEXTINPUT)で受け、
# PC-1251でのキー操作(必要ならSHIFT付き)に直して打つ。

MAC = sys.platform == "darwin"
CMD = "⌘" if MAC else "Ctrl+"  # 画面に出すショートカットの修飾キー
SHIFT = "⇧" if MAC else "Shift+"


def speed_label(speed: float) -> str:
    return "×1/2" if speed == 0.5 else f"×{speed}"


HELP = [
    "マウス: キーを押す(押しているあいだは押しっぱなし)、モードスイッチはクリックかドラッグ",
    f"右クリック: メニュー   {CMD}O: プログラムの一覧   {CMD}↑↓: スイッチ   {CMD}/: この表示",
    "英数字・Enter・矢印・Space: そのまま   Tab: SHIFT   Option(WindowsはAlt): DEF",
    f"{CMD}K: 矢印キーを数字キーの8・2・4・6にする/戻す(テンキーの代わり。F7でも)",
    '記号(: " ( ) など)は打てばSHIFT付きで入る   Backspace: 1字消す   Delete: CL',
    f"Esc: BRK/ON   {CMD}R: RESET   {CMD}S: 画面保存   {CMD}V: 貼り付け",
    f"{CMD}T: 速くする   {SHIFT}{CMD}T: 遅くする(1/2倍〜8倍。1倍以外では音の高さも変わる)",
    f"{CMD}E: いまのBASICのプログラムを.basのファイルに書き出す(プログラムの置き場所へ)",
    "ファイルのドロップ: 読み込む   F1〜F7、F9、F10、F12も使える(手引きの表)",
]


def export_program(m, folder: str, prog: "programs.Program | None" = None) -> str | None:
    """BASICのプログラムを「名前-日時.bas」に書き出してパスを返す。なければNone

    最後に読み込んだプログラムがわかれば、その名前を使い、組になっていた
    16進ダンプを「# hex:」で指しておく(RAMのマシン語そのものは書き出さない)。
    機種用のフォルダ(pc1245など)にあったものなら、folderの中の同じ名前のフォルダに書く。
    """
    body = basictext.program_text(m.mem, start=m.model.prog_start)
    if not body:
        return None
    name = prog.name if prog else "program"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    when = time.strftime("%Y-%m-%d %H:%M")
    head = [f"# title: {prog.title if prog else 'BASIC'}({when}の書き出し)"]
    if prog:
        head += [f"# hex: {os.path.basename(p)}" for p in prog.paths if p.lower().endswith(".hex")]
        head += [f"# {link}" for link in prog.bin_links]
        if prog.run:
            head.append(f"# run: {prog.run}")
    if prog and programs.folder_model(prog.paths[0]):
        folder = os.path.join(folder, programs.model_dir(programs.folder_model(prog.paths[0])))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}-{stamp}.bas")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n" + body)
    return path


def parse_hexdump(path: str) -> list[tuple[int, bytes]]:
    """16進ダンプのファイルを読む(形はprograms.parse_hexと同じ)"""
    return programs.parse_hex(open(path, encoding="utf-8").read())[0]


# 説明の表示に使う日本語フォント。pygame.font.SysFontはmacOSでXQuartzの
# フォント一覧を読んで存在しないファイルを開こうとすることがあるので、
# ファイルを直接探す。
HELP_FONTS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
]


def load_help_font(size: int) -> pygame.font.Font:
    for path in HELP_FONTS:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except (OSError, pygame.error):
                continue
    return pygame.font.Font(None, size)


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home) :] if path.startswith(home) else path


class Typer:
    """文字列を実機のキー操作として順に打つ。時間はエミュレータのサイクルで数える。"""

    DOWN = CLOCK * 70 // 1000
    UP = CLOCK * 60 // 1000
    AFTER_ENTER = CLOCK * 450 // 1000

    MODE_WAIT = CLOCK * 300 // 1000  # スイッチを動かしたあとROMが気づくまで待つ

    LIVE = "@LIVE"  # パソコンのキーボードで押されたキーの印
    # パソコンのキーを届けるときに押しておく時間と、次のキーまであける時間。
    # ROMは離したあと40ms ほどキーがない時間がないと次のキーを取りこぼすので、
    # 1打鍵に0.1秒(毎秒10打鍵)かける。これより速く打った分は順番待ちになる。
    LIVE_DOWN = CLOCK * 50 // 1000
    LIVE_UP = CLOCK * 50 // 1000
    # 連打しすぎて順番待ちが溜まったとき、これより長く待ったキーは捨てる
    # (実機でも受け取れない速さの分。遅れて流れてくるのを防ぐ)
    LIVE_MAX_WAIT = CLOCK * 600 // 1000

    def __init__(self, machine: PC1251, on_mode=None):
        self.m = machine
        self.on_mode = on_mode  # "@MODE:PRO"のような印でスイッチを動かす
        self.queue: list[list[str]] = []
        self.writes: dict[str, list[tuple[int, bytes]]] = {}
        self.cur: list[str] | None = None
        self.until = 0
        self.phase = 0
        # パソコンのキーボードで押されているキー。速く打つと、押して離すまでが
        # 1フレームに収まったり、前のキーを離す前に次を押したりするので、押された
        # キーは順番待ちに入れ、1つずつ一定の時間押して届ける。押し続けていれば、
        # 離すまで(か次のキーが来るまで)そのまま押しておく。
        self.physical: set[str] = set()
        self.live = False
        self.quick = False
        self.stamp = ""

    def press_live(self, name: str) -> None:
        """パソコンのキーが押された。順番待ちに入れる"""
        if name not in self.physical:
            self.physical.add(name)
            self.queue.append([self.LIVE, str(self.m.cpu.cycles), name])

    def add_live_keys(self, keys: list[list[str]]) -> None:
        """パソコンで打った記号やBackspaceを、ふつうの速さで順に押す(押すのが見える)。
        いくつかの打鍵でできた1文字は、同じ時刻の印をつけてまとめて扱う"""
        stamp = str(self.m.cpu.cycles)
        self.queue.extend([self.LIVE, stamp, *k] for k in keys)

    def release_live(self, name: str) -> None:
        """パソコンのキーが離された(押したままの段階なら、次のstepで離す)"""
        self.physical.discard(name)

    @property
    def scripted(self) -> bool:
        """打ち込み(ファイルや貼り付け)の途中か。パソコンのキーの順番待ちは含めない"""
        if self.cur is not None and not self.live:
            return True
        return any(e[:1] != [self.LIVE] for e in self.queue)

    def add_text(self, text: str) -> None:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.queue.extend(keys_for(text, self.m.model.name))

    def add_program(self, text: str) -> None:
        """BASICの行を打つ。79字を超える行は分けて打つ(keytype.keys_for_program)"""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.queue.extend(keys_for_program(text, self.m.model.name))

    def add_keys(self, keys: list[list[str]]) -> None:
        self.queue.extend(keys)

    def add_mode(self, mode: str) -> None:
        self.queue.append([f"@MODE:{mode}"])

    def add_write(self, blocks: list[tuple[int, bytes]]) -> None:
        """前の打鍵が終わったところで、ダンプをRAMに書き込む"""
        key = f"@WRITE:{len(self.writes)}:{id(blocks)}"
        self.writes[key] = blocks
        self.queue.append([key])

    @property
    def busy(self) -> bool:
        return bool(self.queue) or self.cur is not None

    def step(self) -> None:
        c = self.m.cpu.cycles
        if self.cur is None:
            if not self.queue:
                return
            self.cur = self.queue.pop(0)
            if self.cur and self.cur[0].startswith("@WRITE:"):
                # 打ち込みの途中でRAMに書き込む(# after: のダンプ)
                for addr, data in self.writes.pop(self.cur[0], []):
                    for i, b in enumerate(data):
                        self.m.write(addr + i, b)
                self.until = c
                self.phase = 1
                return
            if self.cur and self.cur[0].startswith("@MODE:"):
                self.live = False
                mode = self.cur[0][6:]
                if self.on_mode:
                    self.on_mode(mode)
                else:
                    self.m.mode = mode
                self.until = c + self.MODE_WAIT
                self.phase = 1
                return
            if self.cur[:1] == [self.LIVE]:
                stamp = self.cur[1]
                self.cur = self.cur[2:]
                late = c - int(stamp) > self.LIVE_MAX_WAIT
                if stamp != self.stamp and late and not set(self.cur) <= self.physical:
                    # 待ちすぎた打鍵は、同じ文字の残りの打鍵ごと捨てる(押し続けているキーは残す)
                    while self.queue and self.queue[0][:2] == [self.LIVE, stamp]:
                        self.queue.pop(0)
                    self.cur = None
                    return
                self.stamp = stamp  # 1文字の途中の打鍵は、遅れていても最後まで押す
                self.live = True
            else:
                self.live = False
            # パソコンのキーそのもの(英数字など)は短く押す。記号やBackspaceを直した
            # 打鍵(SHIFTや◀を続けて押す)は、ROMが追いつくように打ち込みと同じ長さにする
            self.quick = self.live and set(self.cur) <= self.physical
            self.m.held.update(self.cur)
            self.until = c + (self.LIVE_DOWN if self.quick else self.DOWN)
            self.phase = 0
        elif self.phase == 2:
            # 押したままの段階: 離されたか、次のキーが来たら離す
            if not set(self.cur) <= self.physical or self.queue:
                self._release(c)
        elif c >= self.until:
            if self.phase == 0:
                if self.live and set(self.cur) <= self.physical and not self.queue:
                    self.phase = 2  # まだ押されている。離すまで押したままにする
                else:
                    self._release(c)
            else:
                self.cur = None

    def _release(self, c: int) -> None:
        assert self.cur is not None
        self.m.held.difference_update(self.cur)
        if self.cur == ["ENTER"]:
            self.until = c + self.AFTER_ENTER
        else:
            self.until = c + (self.LIVE_UP if self.quick else self.UP)
        self.phase = 1


class App:
    def __init__(self, args):
        # allowedchanges=0: 頼んだ形式(モノラル44.1kHz)で開き、装置への変換はSDLにまかせる。
        # 2チャンネルで開かれると、渡した列が2倍の速さで鳴る
        pygame.mixer.pre_init(RATE, -16, 1, 512, allowedchanges=0)
        model = getattr(args, "model", "1251")
        self.m = PC1251(model=model)  # ROMがなければここで止まる(窓を開く前に)
        pygame.init()
        pygame.display.set_caption(f"SHARP {self.m.model.title}")
        self.scale = self._fit(args.scale)
        size = (int(display.OUT_W * self.scale), int(display.OUT_H * self.scale))
        self.window = pygame.display.set_mode(size)
        self.panel = display.Panel(model)
        self.panel.set_fps(FPS, args.persist)
        self.sw_stops = self.panel.switch_stops  # スイッチの段(上から)と、その中心のy
        self.ram_file = ram_file(model)
        self.typer = Typer(self.m, self.set_mode)
        self.fast = False  # 読み込み中は時計に合わせず全速で動かす
        self.menu: dict | None = None  # F6の一覧
        self.status = ""  # 画面の下に出す知らせ
        self.tape_out = tape.TapeOut()  # CSAVEの音を見張ってwavに書き出す
        self.status_until = 0.0
        self.loading = ""
        self.load_total = 1
        self._menu_rows: list[tuple[int, pygame.Rect]] = []
        self.popup: dict | None = None  # 右クリックのメニュー
        self.reset_frames = 0  # メニューやショートカットでRESETを押している残りフレーム
        self.sound = None  # SDLの待ち行列が使えないときの、mixerのChannel
        self.queue: SoundQueue | None = None  # 鳴らす音の出口(audio.SoundQueue)
        if not args.mute:
            try:
                pygame.mixer.quit()  # pygame.initが開いたmixerの装置は使わない
                self.queue = SoundQueue()
            except (OSError, AttributeError) as e:
                print(f"SDLの待ち行列が使えないので、mixerで鳴らします({e})", file=sys.stderr)
                try:
                    pygame.mixer.init(RATE, -16, 1, 512, allowedchanges=0)
                    self.sound = pygame.mixer.Channel(0)
                except pygame.error:
                    self.sound = None
        self.sound_channels = 1
        if self.sound is not None:
            freq, _, channels = pygame.mixer.get_init()
            if freq != RATE:
                print(f"音を切ります: ミキサーが{freq}Hzで開かれました", file=sys.stderr)
                self.sound = None
            self.sound_channels = channels
        self.buzzer = Buzzer()
        self.pcm_wait = bytearray()  # まだチャンネルに渡していない音
        self.overshoot = 0  # 前のフレームで進みすぎたサイクル
        self.turbo: float = 1  # 速さの倍率(SPEEDSのどれか)
        self.numpad_arrows = bool(getattr(args, "numpad", False))
        self.dragging_switch = False
        self.mouse_key: str | None = None
        self.help = FPS * 8
        self.font: pygame.font.Font | None = None
        self.save_ram = not args.fresh
        if self.save_ram and self.m.load_ram(self.ram_file):
            self.m.cpu.reset()
        self.load = args.load
        self.boot_frames = FPS  # 起動してから貼り付けを始めるまで
        if args.type:
            self.typer.add_text(open(args.type, encoding="utf-8").read())
        self.pending: tuple[programs.Program, bool] | None = None
        if getattr(args, "tape", None):
            self.insert_tape(args.tape)
        if getattr(args, "program", None):
            prog = programs.find(args.program, self.m.model.name)
            if prog is None:
                raise FileNotFoundError(f"{args.program}が見つかりません")
            self.pending = (prog, args.run)
        pygame.key.set_repeat()
        pygame.key.start_text_input()

    @staticmethod
    def _fit(scale: float) -> float:
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except (pygame.error, IndexError):
            return scale
        room = min((dw - 80) / display.OUT_W, (dh - 120) / display.OUT_H)
        return min(scale, max(0.35, room))

    # ---- キー ----
    def key_down(self, ev) -> None:
        m = self.m
        mods = ev.mod
        if self.menu is not None:
            self.menu_key(ev)
            return
        if self.popup is not None:
            self.popup_key(ev)
            return
        if mods & (pygame.KMOD_META | pygame.KMOD_CTRL) and self.shortcut(ev.key, mods):
            return
        if ev.key == pygame.K_F6:
            self.open_menu()
            return
        if ev.key == pygame.K_ESCAPE:
            m.brk = True
            return
        fkeys = {pygame.K_F1: "RUN", pygame.K_F2: "PRO", pygame.K_F3: "RSV", pygame.K_F4: "OFF"}
        if ev.key in fkeys:
            if fkeys[ev.key] in m.model.modes:  # PC-1245にはRSVがない
                self.set_mode(fkeys[ev.key])
            return
        if ev.key == pygame.K_F5:
            m.reset_key = True
            return
        if ev.key == pygame.K_F9:
            self.change_speed(-1 if mods & pygame.KMOD_SHIFT else 1)
            return
        if ev.key == pygame.K_F7:
            self.toggle_arrows()
            return
        if ev.key == pygame.K_F12:
            self.screenshot()
            return
        if ev.key == pygame.K_BACKSPACE:
            self.typer.add_live_keys([["LEFT"], ["SHIFT"], ["LEFT"]])
            return
        if ev.key == pygame.K_F10:
            self.toggle_help()
            return
        if mods & (pygame.KMOD_META | pygame.KMOD_CTRL):
            return
        name = self.key_name(ev.key)
        if name is None and not mods & pygame.KMOD_SHIFT:
            name = DIGITS.get(ev.key)  # Shift付きの数字キーは記号になる
        if name:
            self.typer.press_live(name)

    def key_name(self, key: int) -> str | None:
        """パソコンのキーをPC-1251のキーの名前にする(数字キーを除く)"""
        if self.numpad_arrows and key in NUMPAD_ARROWS:
            return NUMPAD_ARROWS[key]
        return DIRECT.get(key) or LETTERS.get(key)

    def key_up(self, ev) -> None:
        m = self.m
        if ev.key == pygame.K_ESCAPE:
            m.brk = False
        elif ev.key == pygame.K_F5:
            m.reset_key = False
        name = self.key_name(ev.key) or DIGITS.get(ev.key)
        if name:
            self.typer.release_live(name)
        if ev.key in NUMPAD_ARROWS:  # 押しているあいだにモードを切り替えたとき
            self.typer.release_live(DIRECT[ev.key])
            self.typer.release_live(NUMPAD_ARROWS[ev.key])

    def text_input(self, text: str) -> None:
        if self.menu is not None or self.popup is not None:
            return
        for ch in text:
            if ch.isascii() and (ch.isalnum() or ch == " "):
                continue  # KEYDOWNで押しっぱなしとして伝えた
            self.typer.add_live_keys(keys_for(ch, self.m.model.name))

    # ---- ショートカットと右クリックのメニュー ----
    # Fキーは明るさや音量、ほかのアプリに取られることがあるので、同じ操作を
    # ⌘(Windows・LinuxはCtrl)との組み合わせと右クリックのメニューにも置く。
    # Ctrl+↑↓はmacOSのMission Controlが使うので、Macでは⌘。
    def shortcut(self, key: int, mods: int = 0) -> bool:
        actions = {
            pygame.K_o: self.open_menu,
            pygame.K_t: lambda: self.change_speed(-1 if mods & pygame.KMOD_SHIFT else 1),
            pygame.K_r: self.press_reset,
            pygame.K_s: self.screenshot,
            pygame.K_e: self.export_program,
            pygame.K_v: self.paste,
            pygame.K_SLASH: self.toggle_help,
            pygame.K_k: self.toggle_arrows,
            pygame.K_UP: lambda: self.move_switch(-1),
            pygame.K_DOWN: lambda: self.move_switch(1),
        }
        act = actions.get(key)
        if act is None:
            return False
        act()
        return True

    SPEEDS = (0.5, 1, 2, 4, 8)

    def change_speed(self, step: int) -> None:
        """速さを1段上げる(step=1)か下げる(step=-1)。両端ではそのまま"""
        i = self.SPEEDS.index(self.turbo) + step
        self.turbo = self.SPEEDS[min(max(i, 0), len(self.SPEEDS) - 1)]
        self.say(f"速さ {speed_label(self.turbo)}", 1.5)

    def toggle_arrows(self) -> None:
        self.numpad_arrows = not self.numpad_arrows
        if self.numpad_arrows:
            self.say("矢印キー → 数字キーの8・2・4・6", 2.5)
        else:
            self.say("矢印キー → ↑↓◀▶", 2.5)

    def toggle_help(self) -> None:
        self.help = 0 if self.help else FPS * 10

    def press_reset(self) -> None:
        """裏のRESETボタンを0.3秒押す"""
        self.m.reset_key = True
        self.reset_frames = max(1, FPS * 3 // 10)

    def move_switch(self, step: int) -> None:
        order = [name for name, _y in self.sw_stops]
        i = order.index(self.m.mode) if self.m.mode in order else order.index("RUN")
        self.set_mode(order[min(max(i + step, 0), len(order) - 1)])

    def popup_items(self) -> list[tuple[str, str, object]]:
        """(表示, ショートカット, 動作)。動作がNoneなら区切り線"""
        items: list[tuple[str, str, object]] = [
            ("プログラムの一覧…", f"{CMD}O", self.open_menu),
            ("", "", None),
        ]
        for name, _y in self.sw_stops:
            key = f"{CMD}↑↓" if self.m.mode == name else ""
            items.append((f"スイッチ {name}", key, lambda n=name: self.set_mode(n)))
        items += [
            ("", "", None),
            (f"速くする(いま{speed_label(self.turbo)})", f"{CMD}T", lambda: self.change_speed(1)),
            ("遅くする", f"{SHIFT}{CMD}T", lambda: self.change_speed(-1)),
            (
                "矢印キーを↑↓◀▶に戻す" if self.numpad_arrows else "矢印キーを8・2・4・6にする",
                f"{CMD}K",
                self.toggle_arrows,
            ),
            ("RESETボタンを押す", f"{CMD}R", self.press_reset),
            ("プログラムをファイルに書き出す", f"{CMD}E", self.export_program),
            ("画面を画像で保存", f"{CMD}S", self.screenshot),
            ("クリップボードから打ち込む", f"{CMD}V", self.paste),
            ("キーの説明", f"{CMD}/", self.toggle_help),
        ]
        return items

    def open_popup(self, pos) -> None:
        self.popup = {"pos": pos, "sel": -1, "rows": []}

    def popup_run(self, i: int) -> None:
        items = self.popup_items()
        act = items[i][2] if 0 <= i < len(items) else None
        self.popup = None
        if callable(act):
            act()

    def popup_key(self, ev) -> None:
        popup = self.popup
        assert popup is not None
        items = self.popup_items()
        live = [i for i, it in enumerate(items) if it[2] is not None]
        if ev.key == pygame.K_ESCAPE:
            self.popup = None
        elif ev.key in (pygame.K_UP, pygame.K_DOWN):
            step = -1 if ev.key == pygame.K_UP else 1
            cur = popup["sel"]
            k = live.index(cur) if cur in live else (-1 if step > 0 else 0)
            popup["sel"] = live[(k + step) % len(live)]
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and popup["sel"] >= 0:
            self.popup_run(popup["sel"])

    def popup_hit(self, pos) -> int:
        popup = self.popup
        if popup is None:
            return -1
        for i, r in popup["rows"]:
            if r.collidepoint(pos):
                return i
        return -1

    # ---- マウス ----
    # モードスイッチ(ラベルと溝)の範囲と各段の位置は、絵のフォルダのlayout.jsonにある
    # (display.Panel.switch_area、switch_stops)

    def mouse_down(self, pos) -> None:
        if self.menu is not None:
            self.menu_click(pos)
            return
        if self.popup is not None:
            i = self.popup_hit(pos)
            if i >= 0:
                self.popup_run(i)
            else:
                self.popup = None
            return
        x = pos[0] / self.scale - display.MARGIN
        y = pos[1] / self.scale - display.MARGIN
        sx0, sy0, sx1, sy1 = self.panel.switch_area
        if sx0 <= x <= sx1 and sy0 <= y <= sy1:
            self.dragging_switch = True
            self.set_switch_from(y)
            return
        name = self.panel.key_at(x, y)
        if name is None:
            return
        self.mouse_key = name
        if name == "BRK":
            self.m.brk = True
        else:
            self.m.held.add(name)

    def mouse_up(self) -> None:
        self.dragging_switch = False
        name, self.mouse_key = self.mouse_key, None
        if name == "BRK":
            self.m.brk = False
        elif name:
            self.m.held.discard(name)

    def set_switch_from(self, y: float) -> None:
        mode = min(self.sw_stops, key=lambda s: abs(s[1] - y))[0]
        self.set_mode(mode)

    def set_mode(self, new: str) -> None:
        m = self.m
        # OFFにしたときはROMが自分で電源を切る(machine.in_b)。切るのを待たずに
        # 電源を落とすと、次に入れたときBASICがメモリを初期化してしまう
        if new != "OFF" and (m.mode == "OFF" or not m.power):
            m.wake()
        m.mode = new

    # ---- プログラムの読み込み ----
    def open_program(self, prog: programs.Program, run: bool = False) -> None:
        """ダンプをRAMに書き、BASICはPROモードでNEWしてから打ち込む"""
        m = self.m
        if not prog.runs_on(m.model.name):
            self.say(f"{prog.label(m.model.name)}なので、{m.model.title}では読み込みません", 5)
            return
        if prog.errors:
            self.say("読めない行があります: " + prog.errors[0], 6)
        if not prog.blocks and not prog.basic and not prog.after:
            self.say(f"{prog.name}: 中身がありません", 4)
            return
        if not m.power:
            self.set_mode(m.mode if m.mode != "OFF" else "RUN")
        for addr, data in prog.blocks:
            for i, b in enumerate(data):
                m.write(addr + i, b)
        back = m.mode if m.mode in ("RUN", "PRO") else "RUN"
        if prog.basic:
            self.typer.add_mode("PRO")
            self.typer.add_text("NEW\n")
            self.typer.add_program(prog.basic)
        if run and prog.run_command:
            self.typer.add_mode("RUN")
            self.typer.add_text(prog.run_command + "\n")
            if prog.after:
                self.typer.add_write(prog.after)
        elif prog.after:
            # 実行しないときは、そのまま書いておく(RUNで消えることがある)
            self.typer.add_write(prog.after)
        elif prog.basic:
            self.typer.add_mode(back)
        if prog.basic:
            self.last_prog = prog  # 書き出すときの名前と、組になるダンプに使う
        self.fast = self.typer.busy
        self.loading = prog.title
        self.load_total = max(1, len(self.typer.queue))
        if not self.fast:
            self.say(f"{prog.title}を読み込みました({prog.size}バイト)")

    def insert_tape(self, path: str) -> None:
        """wavのテープをセットする。ROMがCLOADでカセットの入力を読み始めたときに再生が始まる"""
        try:
            self.m.tape = tape.TapeIn(path)
        except (OSError, EOFError, wave.Error) as e:
            self.say(f"{os.path.basename(path)}を読めません({e})", 5)
            return
        self.say(
            f"テープ {os.path.basename(path)} をセットしました。CLOADかCLOAD Mで読み込みます", 6
        )

    def open_file(self, path: str) -> None:
        if path.lower().endswith(".wav"):
            self.insert_tape(path)
            return
        if os.path.splitext(path)[1].lower() in programs.EXTS:
            self.open_program(programs.load_program(path))
            return
        if path.lower().endswith(".bin"):  # 番地を持たないので、そのままでは置けない
            self.say(
                f"{os.path.basename(path)}は、.basに「# bin: 名前.bin &C300」と書いて読み込みます",
                6,
            )
            return
        try:
            self.typer.add_text(open(path, encoding="utf-8").read())
        except (OSError, UnicodeDecodeError):
            self.say(f"{os.path.basename(path)}を読めません", 4)

    def say(self, text: str, seconds: float = 3.0) -> None:
        self.status = text
        self.status_until = time.monotonic() + seconds

    def open_menu(self) -> None:
        """プログラムの一覧を開く。選ぶと読み込んで実行する(Shift+Enterは読み込むだけ)"""
        items = programs.for_model(programs.scan(), self.m.model.name)
        self.menu = {"items": items, "sel": 0, "top": 0}

    MENU_ROWS = 12

    def menu_key(self, ev) -> None:
        menu = self.menu
        assert menu is not None
        items = menu["items"]
        if ev.key in (pygame.K_ESCAPE, pygame.K_F6):
            self.menu = None
        elif ev.key == pygame.K_UP and items:
            menu["sel"] = (menu["sel"] - 1) % len(items)
        elif ev.key == pygame.K_DOWN and items:
            menu["sel"] = (menu["sel"] + 1) % len(items)
        elif ev.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN) and items:
            step = self.MENU_ROWS if ev.key == pygame.K_PAGEDOWN else -self.MENU_ROWS
            menu["sel"] = min(max(menu["sel"] + step, 0), len(items) - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and items:
            self.menu = None
            run = not ev.mod & pygame.KMOD_SHIFT
            self.open_program(items[menu["sel"]], run=run)
        elif ev.key == pygame.K_o:
            self.reveal(programs.user_dir())
        elif ev.key == pygame.K_r:
            self.open_menu()
        if self.menu is not None:
            sel = self.menu["sel"]
            top = self.menu["top"]
            self.menu["top"] = min(max(top, sel - self.MENU_ROWS + 1), sel)

    def menu_scroll(self, lines: int) -> None:
        """一覧を行単位で動かす(ホイール)。選んでいる行は見えている範囲に入れる"""
        menu = self.menu
        assert menu is not None
        rows = self.MENU_ROWS
        last = max(0, len(menu["items"]) - rows)
        menu["top"] = min(max(menu["top"] + lines, 0), last)
        if menu["items"]:
            menu["sel"] = min(max(menu["sel"], menu["top"]), menu["top"] + rows - 1)

    def menu_click(self, pos) -> None:
        menu = self.menu
        assert menu is not None
        rect = getattr(self, "_menu_rows", [])
        for i, r in rect:
            if r.collidepoint(pos):
                if menu["sel"] == i:  # 選んであるものをもう一度押すと読み込んで実行する
                    self.menu = None
                    self.open_program(menu["items"][i], run=True)
                else:
                    menu["sel"] = i
                return
        self.menu = None

    @staticmethod
    def reveal(path: str) -> None:
        """置き場所をFinder(など)で開く"""
        cmd = {"darwin": ["open"], "win32": ["explorer"]}.get(sys.platform, ["xdg-open"])
        try:
            subprocess.Popen(cmd + [path])
        except OSError:
            pass

    def paste(self) -> None:
        text = ""
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw:
                text = raw.decode("utf-8", "ignore").rstrip("\x00")
        except (pygame.error, NotImplementedError):
            pass
        if not text:
            try:
                text = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
            except OSError:
                text = ""
        self.typer.add_text(text)

    def export_program(self) -> None:
        """RAMにあるBASICのプログラムを、置き場所に.basのファイルとして書き出す"""
        if self.typer.scripted:
            self.say("打ち込みが終わってから書き出してください")
            return
        prog = getattr(self, "last_prog", None)
        try:
            path = export_program(self.m, programs.user_dir(), prog)
        except OSError as e:
            self.say(f"書き出せません: {e}", 5)
            return
        if path is None:
            self.say("書き出すプログラムがありません")
        else:
            self.say(f"{_short(path)}に書き出しました", 5)

    def save_tape(self, samples) -> None:
        """CSAVEの音を、置き場所に「tape-日時.wav」として書き出す"""
        try:
            path = os.path.join(programs.user_dir(), f"tape-{time.strftime('%Y%m%d-%H%M%S')}.wav")
            tape.write_wav(path, samples)
        except OSError as e:
            self.say(f"テープの音を書き出せません: {e}", 5)
            return
        self.say(f"テープの音を{_short(path)}に書き出しました", 6)

    def screenshot(self) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(STATE_DIR, f"shot{n:03d}.png")):
            n += 1
        path = os.path.join(STATE_DIR, f"shot{n:03d}.png")
        pygame.image.save(self.panel.out, path)
        self.say(f"{_short(path)}に保存しました")

    # ---- 描画の補助 ----
    def draw_help(self, dst) -> None:
        font = self._font()
        box = pygame.Surface((dst.get_width() - 40, 26 * len(HELP) + 16), pygame.SRCALPHA)
        box.fill((20, 22, 26, 215))
        for i, line in enumerate(HELP):
            box.blit(font.render(line, True, (235, 235, 230)), (14, 8 + 26 * i))
        dst.blit(box, (20, (dst.get_height() - box.get_height()) // 2))

    def _font(self) -> pygame.font.Font:
        if self.font is None:
            self.font = load_help_font(17)
        return self.font

    def draw_status(self, dst, text: str) -> None:
        f = self._font()
        img = f.render(text, True, (240, 240, 235))
        box = pygame.Surface((img.get_width() + 28, img.get_height() + 14), pygame.SRCALPHA)
        box.fill((20, 22, 26, 215))
        box.blit(img, (14, 7))
        dst.blit(
            box,
            ((dst.get_width() - box.get_width()) // 2, dst.get_height() - box.get_height() - 12),
        )

    def draw_popup(self, dst) -> None:
        popup = self.popup
        assert popup is not None
        f = self._font()
        items = self.popup_items()
        lh, sep_h, pad = 26, 9, 8
        width = 32 + max(f.size(t)[0] + 40 + f.size(k)[0] for t, k, _a in items) + 14
        height = pad * 2 + sum(sep_h if a is None else lh for _t, _k, a in items)
        x, y = popup["pos"]
        x = min(x, dst.get_width() - width - 4)
        y = min(y, dst.get_height() - height - 4)
        box = pygame.Surface((width, height), pygame.SRCALPHA)
        box.fill((28, 30, 34, 238))
        pygame.draw.rect(box, (90, 92, 98, 255), box.get_rect(), 1)
        white, grey = (240, 240, 235), (150, 152, 158)
        rows = []
        cy = pad
        for i, (text, key, act) in enumerate(items):
            if act is None:
                pygame.draw.line(
                    box, (80, 82, 88), (8, cy + sep_h // 2), (width - 8, cy + sep_h // 2)
                )
                cy += sep_h
                continue
            if i == popup["sel"]:
                pygame.draw.rect(box, (70, 92, 140), (4, cy, width - 8, lh))
            if text == f"スイッチ {self.m.mode}":
                box.blit(f.render("●", True, white), (12, cy + 3))
            box.blit(f.render(text, True, white), (32, cy + 3))
            if key:
                img = f.render(key, True, grey)
                box.blit(img, (width - 14 - img.get_width(), cy + 3))
            rows.append((i, pygame.Rect(x + 4, y + cy, width - 8, lh)))
            cy += lh
        popup["rows"] = rows
        dst.blit(box, (x, y))

    def draw_menu(self, dst) -> None:
        menu = self.menu
        assert menu is not None
        f = self._font()
        items = menu["items"]
        rows = self.MENU_ROWS
        lh = 26
        w = min(dst.get_width() - 40, 900)
        h = lh * (rows + 4) + 16
        x0 = (dst.get_width() - w) // 2
        y0 = max(10, (dst.get_height() - h) // 2)
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((20, 22, 26, 230))
        white, grey, hi = (240, 240, 235), (160, 162, 168), (70, 92, 140, 255)
        box.blit(f.render("プログラム", True, white), (14, 8))
        self._menu_rows = []
        if not items:
            box.blit(
                f.render("まだ何もありません。.basか.hexを置いてください", True, grey),
                (14, 8 + lh),
            )
        top = menu["top"]
        above, below = top, max(0, len(items) - top - rows)
        bar = 12 if above or below else 0  # 入りきらないときは右に位置のバーを出す
        if above:
            img = f.render(f"▲ 上にあと{above}本", True, white)
            box.blit(img, (w - img.get_width() - 14 - bar, 8))
        if below:
            img = f.render(f"▼ 下にあと{below}本(↓かホイールで)", True, white)
            box.blit(img, (w - img.get_width() - 14 - bar, 8 + lh * (rows + 1)))
        if bar:
            ty, th = 8 + lh, lh * rows - 2
            pygame.draw.rect(box, (60, 62, 68), (w - 12, ty, 5, th), border_radius=2)
            ky = ty + th * top // len(items)
            kh = max(12, th * rows // len(items))
            pygame.draw.rect(box, (150, 152, 158), (w - 12, ky, 5, kh), border_radius=2)
        for n, prog in enumerate(items[top : top + rows]):
            i = top + n
            y = 8 + lh * (n + 1)
            if i == menu["sel"]:
                pygame.draw.rect(box, hi, (6, y - 2, w - 12 - bar, lh))
            ink = white if prog.runs_on(self.m.model.name) else grey
            box.blit(f.render(prog.label(self.m.model.name), True, ink), (14, y))
            info = prog.kinds + (f" {prog.size}B" if prog.size else "")
            if prog.errors:
                info += " 読めない行あり"
            img = f.render(info, True, grey)
            box.blit(img, (w - img.get_width() - 14 - bar, y))
            self._menu_rows.append((i, pygame.Rect(x0 + 6, y0 + y - 2, w - 12 - bar, lh)))
        foot = [
            "↑↓: 選ぶ   Enter: 読み込んで実行   Shift+Enter: 読み込むだけ   Esc: 閉じる",
            f"O: 置き場所を開く({_short(programs.user_dir())})   R: 一覧を読み直す",
        ]
        for k, line in enumerate(foot):
            box.blit(f.render(line, True, grey), (14, h - 8 - lh * (2 - k)))
        dst.blit(box, (x0, y0))

    # ---- 本体 ----
    def handle(self, ev) -> bool:
        if ev.type == pygame.QUIT:
            return False
        if self.help and ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            # キーの説明は、何か押すか、クリックしたら消す。その操作はそのまま効く。
            # 説明を出し入れするキー(⌘/、F10)は、その処理に任せる
            if ev.type != pygame.KEYDOWN or ev.key not in (pygame.K_SLASH, pygame.K_F10):
                self.help = 0
        if ev.type == pygame.KEYDOWN:
            self.key_down(ev)
        elif ev.type == pygame.KEYUP:
            self.key_up(ev)
        elif ev.type == pygame.TEXTINPUT:
            self.text_input(ev.text)
        elif ev.type == pygame.MOUSEBUTTONDOWN and (
            ev.button == 3 or (ev.button == 1 and MAC and pygame.key.get_mods() & pygame.KMOD_CTRL)
        ):
            if self.menu is None:
                self.open_popup(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.mouse_down(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.mouse_up()
        elif ev.type == pygame.MOUSEWHEEL and self.menu is not None:
            self.menu_scroll(-ev.y)
        elif ev.type == pygame.MOUSEMOTION and self.popup is not None:
            self.popup["sel"] = self.popup_hit(ev.pos)
        elif ev.type == pygame.MOUSEMOTION and self.dragging_switch:
            self.set_switch_from(ev.pos[1] / self.scale - display.MARGIN)
        elif ev.type == pygame.DROPFILE:
            self.open_file(ev.file)
        return True

    def frame(self) -> None:
        """1フレームぶん(1/FPS秒)動かして描く"""
        m = self.m
        per_frame = CLOCK // FPS
        if self.boot_frames:
            self.boot_frames -= 1
            if self.boot_frames == 0 and self.load:
                for addr, data in parse_hexdump(self.load):
                    for i, b in enumerate(data):
                        m.write(addr + i, b)
            if self.boot_frames == 0 and self.pending:
                prog, run = self.pending
                self.open_program(prog, run)
                self.pending = None
        if self.reset_frames:
            self.reset_frames -= 1
            if self.reset_frames == 0:
                m.reset_key = False
        typing = self.typer.scripted and not self.boot_frames
        speed = self.turbo * (8 if typing else 1)
        c0 = m.cpu.cycles
        m.sound_events.clear()
        if self.fast and self.typer.busy and not self.boot_frames:
            # 読み込み中は1フレームの時間いっぱいまで回す
            speed = 0
            end = time.perf_counter() + 0.8 / FPS
            while time.perf_counter() < end and self.typer.busy:
                self.typer.step()
                m.run(CLOCK // 200)
        elif self.fast:
            self.fast = False
            self.say(f"{self.loading}を読み込みました")
        # 1フレームでちょうどCLOCK/FPSサイクル進める。前のフレームで命令の途中まで
        # はみ出した分は差し引く(音の標本の数が再生の速さとそろうように)
        # 音の待ち行列のたまり具合で、進めるサイクルを増減する。フレームが遅れたときは
        # その分を多めに進めて取り戻す(audio.speed_adjust)
        adjust = speed_adjust(self.queue.level()) if self.queue and speed and not typing else 1
        target = m.cpu.cycles + int(speed * per_frame * adjust) - self.overshoot
        self.overshoot = 0
        while (left := target - m.cpu.cycles) > 0:
            if not self.boot_frames:
                self.typer.step()
            before = m.cpu.cycles
            m.run(min(left, CLOCK // 200))
            if m.cpu.cycles == before:  # 電源が切れていて時間が進まない
                break
        else:
            self.overshoot = m.cpu.cycles - target
        wav = self.tape_out.feed(m.sound_events, m.cpu.cycles, m.pc_out >> 4)
        if wav is not None:
            self.save_tape(wav)
        if self.queue is not None and speed and not typing:
            # 無音のところも積み、待ち行列のたまり具合を保つ
            sound = self.buzzer.render(
                m.sound_events, c0, m.cpu.cycles, self.turbo, keep_silent=True
            )
            self.queue.push(sound)
        elif self.queue is not None:
            self.buzzer.hold(m.pc_out >> 4)
            self.queue.clear()
        elif self.sound is not None and speed and not typing:
            # 1倍でないときは、テープの早送りと同じく音の高さも速さの倍率だけ変わる
            sound = self.buzzer.render(m.sound_events, c0, m.cpu.cycles, self.turbo)
            self.feed_sound(sound)
        elif self.sound is not None:
            self.buzzer.hold(m.pc_out >> 4)
        if m.tape is not None and m.tape.done(m.cpu.cycles):
            m.tape = None
            self.say("テープが終わりました")
        mode = m.mode
        pressed = set(m.held) | ({"BRK"} if m.brk else set())
        surf = self.panel.draw(
            m.columns(), m.symbols(), m.display_on(), mode, pressed, powered=m.power
        )
        out = self.window
        if self.scale == 1.0:
            out.blit(surf, (0, 0))
        else:
            pygame.transform.smoothscale(surf, out.get_size(), out)
        if self.help:
            self.help -= 1
            self.draw_help(out)
        if self.fast:
            done = 1 - len(self.typer.queue) / self.load_total
            self.draw_status(out, f"{self.loading}を読み込み中… {int(done * 100)}%")
        elif self.status and time.monotonic() < self.status_until:
            self.draw_status(out, self.status)
        if self.menu is not None:
            self.draw_menu(out)
        if self.popup is not None:
            self.draw_popup(out)
        pygame.display.flip()

    PREBUFFER = RATE // FPS * 2 * 2  # 2フレームぶん(16ビット)
    MAX_PENDING = RATE // 4 * 2  # 0.25秒ぶん(16ビット)。これより遅れたら古い音を捨てる

    def feed_sound(self, pcm: bytes) -> None:
        """1フレームぶんの音をためて、チャンネルが空いたときに渡す。

        Channel.queue()は待ちを1つしか持てず、続けて呼ぶと前のものを捨てるので、
        空くまでこちらでためておく。
        """
        sound = self.sound
        if sound is None:
            return
        if pcm and self.sound_channels > 1:  # 同じ標本を各チャンネルに並べる
            mono = array("h", pcm)
            multi = array("h", bytes(len(pcm) * self.sound_channels))
            for ch in range(self.sound_channels):
                multi[ch :: self.sound_channels] = mono
            pcm = multi.tobytes()
        self.pcm_wait += pcm
        limit = self.MAX_PENDING * self.sound_channels
        if len(self.pcm_wait) > limit:
            del self.pcm_wait[: len(self.pcm_wait) - limit]
        if not self.pcm_wait:
            return
        if not sound.get_busy():
            # 鳴り始めは2フレームぶんためてから渡す。フレームの時刻が少し揺れても
            # 次の分が間に合い、途中で音が途切れない
            if pcm and len(self.pcm_wait) < self.PREBUFFER * self.sound_channels:
                return  # 音が切れたとき(pcmが空)は、たまった残りをすぐ渡す
            sound.play(pygame.mixer.Sound(buffer=bytes(self.pcm_wait)))
            self.pcm_wait.clear()
        elif sound.get_queue() is None:
            sound.queue(pygame.mixer.Sound(buffer=bytes(self.pcm_wait)))
            self.pcm_wait.clear()

    def close(self) -> None:
        if self.save_ram:
            if self.m.power:
                self.m.power_off()
            os.makedirs(STATE_DIR, exist_ok=True)
            self.m.save_ram(self.ram_file)
        if self.queue is not None:
            self.queue.close()
        pygame.quit()

    def run(self) -> None:
        clock = pygame.time.Clock()
        running = True
        while running:
            for ev in pygame.event.get():
                running = self.handle(ev) and running
            self.frame()
            clock.tick(FPS)
        self.close()


app_cli = typer.Typer(add_completion=False, help="SHARP PC-1251/PC-1245エミュレータ")


def _show_version(value: bool) -> None:
    if value:
        from importlib.metadata import version

        typer.echo(f"pc1251-emu {version('pc1251-emu')}")
        raise typer.Exit()


@app_cli.command()
def main(
    program: str | None = typer.Argument(
        None, help="読み込むプログラム(.bas/.hexのパスか、置き場所にある名前)"
    ),
    run: bool = typer.Option(False, "--run", help="読み込んだあと実行する"),
    scale: float = typer.Option(1.0, help="拡大率"),
    type_: str | None = typer.Option(
        None, "--type", help="起動後にこのファイルの中身をキー入力する"
    ),
    load: str | None = typer.Option(None, help="16進ダンプ(番地 データ)をRAMに書き込む"),
    fresh: bool = typer.Option(False, help="保存したRAMを読まず、終了時にも保存しない"),
    mute: bool = typer.Option(False, help="音を出さない"),
    persist: float = typer.Option(1.0, help="液晶の残像の強さ(0で残像なし)"),
    export: str | None = typer.Option(
        None, help="保存したRAMのBASICのプログラムを、このフォルダに.basで書き出して終わる"
    ),
    model: str = typer.Option("1251", help="機種(1251か1245)。ROMはcpu-機種.romとbas-機種.rom"),
    numpad: bool = typer.Option(
        False, help="矢印キーを数字キーの8・2・4・6として押す(⌘K/Ctrl+Kで切り替え)"
    ),
    tape_: str | None = typer.Option(
        None, "--tape", help="カセットの音(wav)をセットする。CLOAD・CLOAD Mで読み込める"
    ),
    version_: bool = typer.Option(
        False, "--version", callback=_show_version, is_eager=True, help="版を出して終わる"
    ),
) -> None:
    if model not in MODELS:
        typer.echo(f"機種は{'、'.join(MODELS)}のどれかです", err=True)
        raise typer.Exit(2)
    if export is not None:
        try:
            m = PC1251(model=model)
        except RomNotFound as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e
        if not m.load_ram(ram_file(model)):
            typer.echo(f"{ram_file(model)}がありません", err=True)
            raise typer.Exit(1)
        path = export_program(m, export)
        typer.echo(path or "書き出すプログラムがありません")
        return
    args = SimpleNamespace(
        scale=scale,
        type=type_,
        load=load,
        fresh=fresh,
        mute=mute,
        persist=persist,
        program=program,
        run=run,
        model=model,
        numpad=numpad,
        tape=tape_,
    )
    try:
        App(args).run()
    except (RomNotFound, FileNotFoundError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


def cli() -> None:
    app_cli()


if __name__ == "__main__":
    cli()
