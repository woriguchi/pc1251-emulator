"""PC-1251/PC-1245/PC-1261/PC-1350エミュレータの画面とキー操作

uv run sc61box          # 起動
uv run sc61box --model 1245  # PC-1245として起動する
uv run sc61box --model 1261  # PC-1261として起動する(1260、1262も選べる)
uv run sc61box --model 1350 --card 16  # PC-1350として、16KBのRAMカードを差して起動する
uv run sc61box --type prog.bas # 起動後にファイルの中身をキー入力する
uv run sc61box --load dump.txt # 16進ダンプをRAMへ書き込む
uv run sc61box primes --run  # 置き場所のprimes.basを読み込んで実行する
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pygame
import typer

from . import (
    audio,
    basictext,
    benchview,
    display,
    gamepad,
    i18n,
    keytype,
    padmenu,
    paths,
    programs,
    recorder,
    tape,
    workbench,
)
from .audio import (
    PRINT_CATCH_UP,
    PRINT_GAP,
    PRINT_KEEP,
    PRINT_LINE,
    RATE,
    Buzzer,
    PrinterSound,
    speed_adjust,
)
from .autotype import Typer
from .i18n import tr
from .keytype import keys_for, keys_for_program
from .machine import CLOCK, MODELS, RomNotFound, new_machine
from .overlay import (
    BAR_H,
    SEPARATOR,
    Bar,
    BarButton,
    MenuItem,
    Paper,
    Popup,
    ProgramMenu,
    draw_halted,
    draw_help,
    draw_recording,
    draw_status,
    load_help_font,
)
from .printer import load_font
from .printout import Printout

FPS = 30
# 1フレームの本体の実行をこの数に分け、合間にもキーのイベントを受け取る(キーを押してから
# 本体に届くまでの遅れを1/(FPS*SUBSTEPS)秒以下にする。ゲームの細かいキー操作のため)
SUBSTEPS = 4
RUSH = 8  # パソコンのキーをROMの入力待ちに届けるあいだの速さ(Typer.rushing)
STATE_DIR = paths.data_dir()  # RAM、状態、作業欄の見え方などを置くところ


@dataclass
class Options:
    """起動のオプション(コマンドの引数。試験やツールからはこのまま作る)"""

    model: str = "1251"
    card: int = 0
    overseas: bool = False
    norom: bool = False
    scale: float = 1.0
    persist: float = 1.0
    fresh: bool = False
    mute: bool = False
    numpad: bool = False
    lcd: bool = False  # 本体の絵を出さず、液晶だけを見せる
    lang: str | None = None
    program: str | None = None
    run: bool = False
    type: str | None = None
    load: str | None = None
    tape: str | None = None
    state: str | None = None
    moved_data: str = ""  # 起動のときに移した前のデータのフォルダ(~/.pc1251など。paths.migrate)


def undo_hint() -> str:
    return tr("メニューの「読み込む前に戻す」で元に戻せます")


def ram_file(model: str = "1251", card: int = 0, norom: bool = False) -> str:
    """終了時にRAMを保存するファイル。RAMの大きさが違うので機種(とRAMカード)ごとに分ける。
    ROMなしで動かしたときのRAMは、ROMで動かしたときのRAMと混ざらないように別にする"""
    if card:
        model = f"{model}-{card}k"
    if norom:
        return os.path.join(STATE_DIR, f"ram-{model}-norom.bin")
    name = "ram.bin" if model == "1251" else f"ram-{model}.bin"
    return os.path.join(STATE_DIR, name)


def bench_file(ram: str) -> str:
    """終了したときに、RAMと一緒に作業欄の情報(開始番地、止める所、書いた範囲)を保存する
    ファイル"""
    return os.path.splitext(ram)[0] + "-bench.json"


def saved_info(ram: str) -> object:
    """終了したときにRAMと一緒に保存した情報(作業欄の状態とRAMの終わり)。なければNone"""
    try:
        with open(bench_file(ram), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def apply_ram_top(m, info: object) -> None:
    """保存した情報のRAMの終わりに動かす(RAMを読む前に、同じ大きさにしておく)"""
    top = info.get("ram_top") if isinstance(info, dict) else None
    if type(top) is int and m.ram_top_ok(top):
        m.set_ram_top(top)


def view_file() -> str:
    """作業欄の見え方(内部RAMを開いておくか)と、メニューで選んだ画面の言語を覚えておくファイル"""
    return os.path.join(STATE_DIR, "bench-view.json")


def state_file(model: str = "1251", card: int = 0, norom: bool = False) -> str:
    """どこでもセーブの保存先(機種とRAMカードごとに1つ。ROMなしは別)"""
    name = f"{model}-{card}k" if card else model
    return os.path.join(STATE_DIR, f"state-{name}{'-norom' if norom else ''}.json")


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
# PC-1350で名前の違うキー。DeleteとInsertはDELとINS、HomeはCLS。
# カナキーはパソコンにないので、F6の隣のF8に置く
DIRECT_1350 = {
    pygame.K_DELETE: "DEL",
    pygame.K_INSERT: "INS",
    pygame.K_HOME: "CLS",
    pygame.K_F8: "KANA",
}
DIGITS = {}
for _i in range(10):
    DIGITS[getattr(pygame, f"K_{_i}")] = str(_i)
    DIGITS[getattr(pygame, f"K_KP{_i}")] = str(_i)
LETTERS = {getattr(pygame, f"K_{_c}"): _c.upper() for _c in "abcdefghijklmnopqrstuvwxyz"}
# 矢印キーを数字キーの8・2・4・6として押すモード(テンキーのないパソコン用)
NUMPAD_ARROWS = {pygame.K_UP: "8", pygame.K_DOWN: "2", pygame.K_LEFT: "4", pygame.K_RIGHT: "6"}
# 記号はキーボードの配列で位置が違うので、打たれた文字(TEXTINPUT)で受けてキー操作に直す
PAD_EVENTS = (
    pygame.CONTROLLERDEVICEADDED, pygame.CONTROLLERDEVICEREMOVED, pygame.CONTROLLERBUTTONDOWN,
    pygame.CONTROLLERBUTTONUP, pygame.CONTROLLERAXISMOTION,
)  # fmt: skip

MAC = sys.platform == "darwin"
CMD = "⌘" if MAC else "Ctrl+"  # 画面に出すショートカットの修飾キー
SHIFT = "⇧" if MAC else "Shift+"


def speed_label(speed: float) -> str:
    return "×1/2" if speed == 0.5 else f"×{speed}"


def switch_label(name: str) -> str:
    """メニューのスイッチの項目(●をつける項目を、この名前で見分ける)"""
    return tr("スイッチ {name}", name=name)


def break_message(addr: int, on: bool) -> str:
    """止める所を置いた(on)か外したときの知らせ"""
    if on:
        return tr("{addr:04X}番地の止める所を置きました", addr=addr)
    return tr("{addr:04X}番地の止める所を外しました", addr=addr)


def outside_message(name: str, addr: int) -> str:
    """プログラムがRAMの外の番地addrに書くので読み込まないときの知らせ"""
    return tr("{name}を読み込みません。{addr:04X}番地はRAMの外です", name=name, addr=addr)


# 表示・入力のメニューの、言語を切り替える項目の名前(切り替えた先の言語で書く)
LANGUAGE_NAMES = {"ja": "日本語", "en": "English"}


def help_lines(norom: bool = False, is1350: bool = False) -> list[str]:
    """キーの説明。パソコンのキーとポケコンのキーで対応が違うものだけを書く(英数字、記号、
    Enter、矢印、Spaceはそのまま打てるので書かない)。エミュレータの操作は操作欄のメニューに
    出る。ROMなしでは作業欄のキー"""
    c, s = CMD, SHIFT
    if norom:
        return [
            tr("ROMなしの作業欄(右)"),
            tr("0〜9・A〜F: ダンプを書く   Enter: 次の行   Space: 番地からバイトへ   "
               "Tab: 番地を打って飛ぶ"),
            tr("{c}G: 実行・続ける   {s}{c}G: カーソルから実行   {c}.: 一時停止   Esc: 編集に戻る",
               c=c, s=s),
            tr("{c}J: 次の1命令だけ実行   {s}{c}J: CALLの呼び先を戻るまで実行   {c}B: 止める所",
               c=c, s=s),
            tr("{c}V: 本のダンプリストや.hexを貼り付け   {c}Z: 取り消す   {s}{c}Z: やり直す",
               c=c, s=s),
            tr("PageUp・PageDown: 1画面   Home・End({c}←→): 行の頭・終わり   "
               "{c}↑↓: 開始番地・終わり", c=c),
            tr("{c}E: .hexに書き出す   {s}{c}E: ダンプリストの形(8バイト:チェックサム)で書き出す",
               c=c, s=s),
            tr("範囲の行をクリック: 書き出す範囲を打つ   "
               "{c}O: プログラムの一覧(.hexのマシン語だけを使う)", c=c),
            tr("実行中のキーは本体へ(Tab: SHIFT  Option: DEF  Delete: CL  Esc: BRK)"),
        ]  # fmt: skip
    head = tr("パソコンのキーとポケコンのキーで違うもの(ほかのキーはそのまま打てます)")
    arrows = tr("{c}K: 矢印キーを数字キーの8・2・4・6にする・戻す(テンキーの代わり)", c=c)
    menus = tr("エミュレータの操作は下の操作欄のメニューから(ショートカットはメニューに出ます)")
    if is1350:
        return [
            head,
            tr("Tab: SHIFT   Option(WindowsはAlt): DEF   F8: カナ   "
               "Esc: BRK(電源が切れていればON)"),
            tr("Delete: DEL   Insert: INS   Home: CLS   "
               "Backspace: 1字消す(◀とDELを押す)   \\: ¥"),
            tr("F1・F2: MODEキーでRUN・PROにする   F3・F4・{c}↑↓: 電源スイッチ   F5・{c}R: RESET",
               c=c),
            arrows,
            menus,
        ]  # fmt: skip
    return [
        head,
        tr("Tab: SHIFT   Option(WindowsはAlt): DEF   Delete: CL   Esc: BRK(電源が切れていればON)"),
        tr("Backspace: 1字消す(◀とSHIFT+◀を押す)   \\(バックスラッシュ): ¥"),
        tr("F1〜F4・{c}↑↓: モードスイッチ   F5・{c}R: 裏のRESETボタン", c=c),
        arrows,
        menus,
    ]


def export_program(m, folder: str, prog: "programs.Program | None" = None) -> str | None:
    """BASICのプログラムを「名前-日時.bas」に書き出してパスを返す。なければNone

    progは最後に読み込んだプログラム。その名前を使い、組になっていたダンプなどの指示を
    書き写す(RAMのマシン語は書き出さない)。機種のフォルダにあったものなら、folderの中の
    同じ名前のフォルダに書く。
    """
    body = basictext.program_text(m.mem, start=m.program_start())
    if not body:
        return None
    name = prog.name if prog else "program"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    when = time.strftime("%Y-%m-%d %H:%M")
    title = prog.title if prog else "BASIC"
    head = ["# title: " + tr("{title}({when}の書き出し)", title=title, when=when)]
    if prog:
        if prog.model:
            head.append(f"# model: {prog.model}")
        head += [f"# {link}" for link in prog.links]
        for key in ("setup", "run", "help"):
            head += [f"# {key}: {line}" for line in getattr(prog, key).split("\n") if line]
        if prog.mode:
            head.append(f"# mode: {prog.mode}")
        if prog.pad is not None:
            head.append(f"# pad: {prog.pad}".rstrip())
        if prog.ram is not None:
            head.append(f"# ram: {prog.ram[0]:04X}-{prog.ram[1] - 1:04X}")
    where = programs.folder_model(prog.paths[0]) if prog and prog.paths else ""
    if where:
        folder = os.path.join(folder, programs.model_dir(where))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}-{stamp}.bas")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head) + "\n" + body)
    return path


def parse_hexdump(path: str) -> list[tuple[int, bytes]]:
    """16進ダンプのファイルを読む(形はprograms.parse_hexと同じ)"""
    return programs.parse_hex(open(path, encoding="utf-8").read())[0]


def opaque(surf: pygame.Surface) -> pygame.Surface:
    """アルファのない24ビットのコピー。窓と同じ形式の絵は、アルファの成分が意味のない値の
    ことがあり、そのままPNGにすると透けてしまう"""
    out = pygame.Surface(surf.get_size(), 0, 24)
    out.blit(surf, (0, 0))
    return out


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home) :] if path.startswith(home) else path


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("sc61box")
    except PackageNotFoundError:
        return "?"


class App:
    def __init__(self, args: Options):
        # 頼んだ形式(モノラル44.1kHz)で開き、装置への変換はSDLにまかせる
        # (2チャンネルで開かれると、渡した列が2倍の速さで鳴る)
        pygame.mixer.pre_init(RATE, -16, 1, 512, allowedchanges=0)
        i18n.set_language(i18n.choose(args.lang, self._view_pref("lang")))
        model = args.model
        card = args.card if MODELS[model].family == "1350" else 0
        # ROMがなければROMなしで動かし、マシン語の作業欄を出す(PC-1350はROMなしでは
        # 動かせないので、ここで止まる)
        norom = args.norom
        if not norom:
            try:
                self.m = new_machine(model, card, args.overseas)
            except RomNotFound:
                if MODELS[model].family == "1350":
                    raise
                norom = True
        if norom:
            self.m = new_machine(model, rom=False)
        self.is1350 = self.m.model.family == "1350"
        self.norom = norom
        # マシン語の作業欄。ROMなしではいつも右に出し、ROMがあればメニューで出し入れする
        self.bench = workbench.Bench(self.m)
        pygame.init()
        self.bench_view = benchview.BenchView(self.bench, load_help_font(15), CMD, SHIFT)
        self.pane_open = norom or self._view_pref("show_pane") is True
        self.bench_at = 0  # 作業欄の右クリックのメニューで扱う番地
        pygame.display.set_caption(f"SHARP {self.m.model.title}")
        try:  # 窓とDockのアイコン(assets/icon.png)
            pygame.display.set_icon(pygame.image.load(os.path.join(display.ASSETS, "icon.png")))
        except (pygame.error, FileNotFoundError):
            pass
        self.out_w, self.out_h = display.out_size(model)
        pane = benchview.PANE_W if self.pane_open else 0
        self.want_scale = args.scale  # 指定された拡大率(画面に入らなければ、これより縮める)
        self.scale = self._fit(args.scale, self.out_w, self.out_h, pane, BAR_H)
        self.body_size = (int(self.out_w * self.scale), int(self.out_h * self.scale))
        self.font: pygame.font.Font | None = None
        self.small_font: pygame.font.Font | None = None
        # プリンタはいつもつないでおき、印字したときだけ紙を出す
        self.m.connect_printer()
        self.paper = Paper(load_font())
        self.printout: Printout | None = None  # 出している紙(しまっていればNone)
        self.print_cut = (0, 0)  # 次の紙の始まり(Printout.cut)
        self.paper_back = 0  # 紙を何行さかのぼって見せているか
        self.printed = 0  # 紙に出した行の数(印字は1行ずつ出す。check_printer)
        self.print_gap = 0  # 行を出し終えてから次の行を出すまでの残りのフレーム
        self.print_rate = 1.0  # 紙送りが実機の何倍の速さか(プリンタの音の速さ)
        self.print_hold = 0.0  # 溜まった行を速めて出しているときの速さ(出し切るまで保つ)
        self.paper.line_frames = round(PRINT_LINE * FPS)
        self.print_seen = 0  # 紙に反映したときのprinter.changes
        self.pads = gamepad.Pads()
        self.pad_map = self.pad_map_for(None)
        self.pad_dirty = False  # 割り当てに保存していない変更があるか
        self.pad_note = ""  # 読み込んだプログラムの# pad: の読めない語の知らせ
        self.pad_down: dict[str, str] = {}  # パッドの入力(pad1:aなど)ごとに、押したときのキー
        self.pad_panel: padmenu.PadPanel | None = None  # 出していればゲームパッドの割り当ての画面
        # 割り当ての対象のプログラム。last_progと違い、.hexだけのプログラムでも替わる
        self.pad_prog: programs.Program | None = None
        self.bench_view.show_iram = self._iram_shown()
        self.window = pygame.display.set_mode(self._window_size())
        self.bar = Bar([])
        self.rec_paused = False
        self.panel = display.Panel(model)
        self.panel.set_fps(FPS, args.persist)
        self.scaled_body: pygame.Surface | None = None  # 拡大・縮小の結果を置く独立した面
        self.lcd_only = False  # 本体の絵を隠して、液晶だけを見せているか
        self.pane_before_lcd = False  # 液晶だけにする前に作業欄を出していたか
        self.free_size: tuple[int, int] | None = None  # 液晶だけのとき、利用者が変えた窓の大きさ
        self.origin = (0, 0)  # 窓の中で中身を描く位置(窓が中身より大きいとき、まんなかに)
        self.win_flags = 0  # 窓を作ったときのフラグ(液晶だけのときはRESIZABLE)
        self.window_stale = False  # 窓の大きさが外から変わったので、表示面を作り直すか
        self.laid_out = (0, 0)  # 最後に中身を置いたときの窓の大きさ(利用者が変えたか見る)
        self.laid_content = (0, 0)  # そのときの中身の大きさ
        self.sw_stops = self.panel.switch_stops  # スイッチの段(上から)と、その中心のy
        self.ram_file = ram_file(model, card, norom)
        self.state_file = state_file(model, card, norom)
        self.typer = Typer(self.m, self.set_mode)
        self.typer.on_write = self.write_dump
        self.fast = False  # 読み込み中は時計に合わせず全速で動かす
        self.menu: ProgramMenu | None = None
        self.status = ""  # 画面の下に出す知らせ
        self.status_until = 0.0
        self.tape_out = tape.TapeOut()  # CSAVEの音を見張ってwavに書き出す
        self.loading = ""
        self.load_help = ""  # 読み込み終わりに出す説明(# help:)
        self.undo_state: dict | None = None  # 最後にプログラムを読み込む直前の状態
        self.undo_title = ""
        # 読み込む直前の(last_prog, loading, load_help, pad_prog, pad_map, pad_dirty)
        self.undo_prog: tuple = (None, "", "", None, self.pad_map, False)
        self.undo_bench: dict | None = None  # 読み込む直前の作業欄
        self.load_total = 1
        self.load_typing = False  # 打ち込みで入れているところか(進み具合の表示用)
        self.popup: Popup | None = None  # 右クリックのメニュー
        self.reset_frames = 0  # RESETボタンを押している残りのフレーム
        self.speaker = None if args.mute else audio.open_output()
        self.buzzer = Buzzer()
        self.print_sound = PrinterSound()
        self.recorder: recorder.Recorder | None = None
        self.rec_buzzer = Buzzer()  # 録画の音は鳴らす音とは別に作る
        self.rec_print_sound = PrinterSound()
        self.overshoot = 0  # 前のフレームで進みすぎたサイクル
        self.closing = False  # 窓を閉じる操作があった(run)
        self.rush_spans: list[tuple[int, int]] = []  # このフレームで速く回したサイクルの範囲
        # このフレームのあいだに中身が変わった液晶の列と、その列の各ドットが点いていた時間の
        # 割合(_lcd_duty)。列の番号は、その列の液晶RAMの番地から引く
        self.lcd_duty: dict[int, list[float]] = {}
        self.lcd_cols: dict[int, list[int]] = {}
        for i, a in enumerate(self.m.column_addrs()):
            self.lcd_cols.setdefault(a, []).append(i)
        self.turbo: float = 1  # 速さの倍率(SPEEDSのどれか)
        self.numpad_arrows = args.numpad
        self.dragging_switch = False
        self.mouse_key: str | None = None
        self.brk_by: set[str] = set()  # BRKキーを押している入力元(EscキーとマウスでBRK)
        self.help = 0  # キーの説明を出しておく残りのフレーム
        if self.norom:
            self.say(tr("ROMがないので、ROMなしでマシン語だけを動かします(右の作業欄)"), 8)
        else:
            self.say(tr("操作は下の操作欄のボタンから。キーの説明は{c}/", c=CMD), 8)
        if args.moved_data:
            self.say(
                tr(
                    "データの置き場所を~/.sc61boxに移しました({old}はそこへのリンク)",
                    old=args.moved_data,
                ),
                10,
            )
        self.save_ram = not args.fresh
        info = saved_info(self.ram_file) if self.save_ram else None
        apply_ram_top(self.m, info)
        if self.save_ram and self.m.load_ram(self.ram_file):
            self.m.cpu.reset()
            self.bench.prev_regs = bytes(self.m.cpu.ram)
            self._load_bench_info(info)
        self.load = args.load
        self.boot_frames = FPS  # 起動してから貼り付けを始めるまで
        if args.type:
            self.typer.add_text(open(args.type, encoding="utf-8").read())
        self.pending: tuple[programs.Program, bool] | None = None
        self.last_prog: programs.Program | None = None  # 書き出しと録画の題名に使う
        if args.tape:
            self.insert_tape(args.tape)
        if args.state:
            self.load_state(args.state)
        if args.program:
            prog = programs.find(args.program, self.m.model.name)
            if prog is None:
                raise FileNotFoundError(tr("{name}が見つかりません", name=args.program))
            self.pending = (prog, args.run)
        if args.lcd:
            self.toggle_lcd(True)
        pygame.key.set_repeat()  # リピートは作業欄だけで、自分で数える(_key_repeat)
        # 作業欄で押し続けているキーと、次にリピートする時刻
        self.held_key: tuple[object, float] | None = None
        pygame.key.start_text_input()

    @staticmethod
    def _fit(
        scale: float,
        out_w: int = display.OUT_W,
        out_h: int = display.OUT_H,
        pane: int = 0,
        below: int = 0,
    ) -> float:
        """拡大率。画面に収まらなければ縮める(paneは右に足す作業欄の幅、belowは本体の下に
        足す操作欄などの高さ。どちらも拡大率によらない画素数)"""
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except (pygame.error, IndexError):
            return scale
        room = min((dw - 80 - pane) / out_w, (dh - 120 - below) / out_h)
        return min(scale, max(0.35, room))

    LCD_MARGIN = 26  # 液晶だけのとき、液晶の枠のまわりに見せる本体の絵(拡大前の画素)

    def view_box(self) -> pygame.Rect:
        """本体の絵のうち窓に出す範囲。液晶だけのときは、録画で拡大するのと同じ液晶の枠に、
        まわりの本体の絵を少し足したもの(窓の縁に液晶がくっつかないように)"""
        if not self.lcd_only:
            return pygame.Rect(0, 0, self.out_w, self.out_h)
        x0, y0, x1, y1 = self.panel.lcd_box()
        m = 2 * self.LCD_MARGIN
        box = pygame.Rect(x0, y0, x1 - x0, y1 - y0).inflate(m, m)
        return box.clip(pygame.Rect(0, 0, self.out_w, self.out_h))

    def _refit(self) -> None:
        """本体の下に足すもの(プリンタの紙、割り当ての欄、操作欄)と右の作業欄も合わせて画面に
        入るように、本体の拡大率を決め直して窓を作り直す(すべてしまえば、指定された拡大率まで
        戻る)。割り当ての欄の高さは本体の幅で増えも減りもするので、決めた幅で測った高さが
        見込みを超えるあいだ、見込みを増やして決め直す。液晶だけのときは、本体を出すときと
        同じ幅に液晶を広げる。利用者が窓の大きさを変えていれば(free_size)、その中に
        入る大きさにして窓はそのままにする"""
        pane = benchview.PANE_W if self.pane_open else 0
        vw, vh = self.view_box().size
        want = self.want_scale * self.out_w / vw
        free = self.free_size
        panel_h = 0
        for _ in range(10):
            below = BAR_H + panel_h
            if self.paper_open:
                below += self.paper.height
            if free is not None:
                # 利用者が決めた大きさに入れる。ただし操作欄のボタンが入る幅と液晶の最低の
                # 高さは保ち、紙や割り当ての欄を出して入らなくなれば、そのぶん窓を広げる
                fw, fh = free
                mw, mh = self._min_size(below)
                scale = min((fw - pane) / vw, (fh - below) / vh)
                self.scale = max(scale, (mw - pane) / vw, (mh - below) / vh)
                bw, bh = int(vw * self.scale), int(vh * self.scale)
                self.free_size = (max(fw, bw + pane), max(fh, bh + below))
            else:
                self.scale = self._fit(want, vw, vh, pane, below)
            self.body_size = (int(vw * self.scale), int(vh * self.scale))
            measured = self._pad_panel_height()
            if measured <= panel_h:
                break
            panel_h = measured
        self._open_window()

    MENU_ROOM = 420  # 液晶だけの細い窓で一覧やメニューを開くあいだ、窓を広げる高さ

    def _open_window(self, room: bool | None = None) -> None:
        """窓を中身の大きさ(利用者が変えていればその大きさ)で作り直す。液晶だけのときは
        大きさを変えられる窓にし、一覧やメニューを開いているあいだ(room)は、入るだけの高さに
        広げる。中身より大きければ、中身はまんなかに描く"""
        content = self._window_size()
        size = self.free_size if self.free_size is not None else content
        if room is None:
            room = self.menu is not None or self.popup is not None or bool(self.help)
        if self.lcd_only and room:
            size = (size[0], max(size[1], self.MENU_ROOM))
        flags = pygame.RESIZABLE if self.lcd_only else 0
        if self.window_stale or size != self.window.get_size() or flags != self.win_flags:
            # 大きさが外から変わったあと(全画面から戻ったときなど)は、同じ大きさでも作り直す。
            # pygameが用意した現在の表示面を取り直す。
            self.window = pygame.display.set_mode(size, flags)
            self.win_flags = flags
            self.window_stale = False
        self.laid_out, self.laid_content = size, content
        self.origin = (max(0, (size[0] - content[0]) // 2), max(0, (size[1] - content[1]) // 2))

    def _min_size(self, below: int | None = None) -> tuple[int, int]:
        """窓の大きさの下限(操作欄のボタン、作業欄、本体の下に足したものが入る大きさ)。
        belowは本体の下に足すものの高さ(なければ測る)"""
        pane = benchview.PANE_W if self.pane_open else 0
        if below is None:
            below = self._window_size()[1] - self.body_size[1]
        width = max(320, Bar.min_width(self._font(), self.bar_buttons()))
        if self.pad_panel is not None:
            width = max(width, 480)
        return pane + width, below + 40

    def toggle_lcd(self, on: bool | None = None) -> None:
        """本体の絵を隠して液晶だけにする・本体を出す"""
        on = not self.lcd_only if on is None else on
        if on == self.lcd_only:
            return
        self.release_all()
        if on:
            # 液晶だけのあいだは作業欄を出さない(細い窓に合わない)。戻るときに元に戻す
            self.pane_before_lcd = self.pane_open
            self.pane_open = False
        else:
            self.pane_open = self.pane_before_lcd
        # ROMなしでも一時的に隠す。通常表示での作業欄の設定は書き換えない。
        self.bench_view.focus = False
        self.lcd_only = on
        self.free_size = None
        self._refit()

    def _track_window(self) -> None:
        """表示面を取り直す(pygameが作り直していれば、そちらに描く)"""
        win = pygame.display.get_surface()
        if win is not None and win is not self.window:
            self.window = win

    def resized(self, w: int, h: int) -> None:
        """窓の大きさが外から変わった(利用者の操作、最大化、全画面の出入り)。液晶だけのときは
        その大きさに合わせて置き直す。どの場合も表示面は作り直す(_open_window)"""
        self._track_window()
        self.window_stale = True
        if self.lcd_only and (w, h) != self.laid_out:
            mw, mh = self._min_size()
            self.free_size = (max(w, mw), max(h, mh))  # 小さくしすぎたら、下限まで戻す
            self._refit()
        else:
            self._open_window()

    def _make_room(self) -> tuple[int, int]:
        """一覧やメニューを出す前に窓を広げ、中身の位置のずれを返す(出す位置を直すため)"""
        bx, by = self.origin
        self._open_window(room=True)
        return self.origin[0] - bx, self.origin[1] - by

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
        cmd = mods & (pygame.KMOD_META | pygame.KMOD_CTRL)
        if self.pad_panel is not None and not cmd:
            self.pad_key(ev)
            return
        if cmd and self.shortcut(ev.key, mods):
            return
        if self.pad_panel is not None:
            return
        if self.pane_keys():
            # キーを作業欄の打ち込みに使う(本体のキーには送らない)
            if not mods & (pygame.KMOD_META | pygame.KMOD_CTRL):
                self.bench_key(ev)
                # 押し続けたカーソルのキーはリピートする(ほかのキーを押したらやめる)
                at = time.monotonic() + self.REPEAT[0]
                self.held_key = (ev, at) if ev.key in self.REPEAT_KEYS else None
            return
        actions = {
            pygame.K_F6: self.open_menu,
            pygame.K_F7: self.toggle_arrows,
            pygame.K_F9: lambda: self.change_speed(-1 if mods & pygame.KMOD_SHIFT else 1),
            pygame.K_F10: self.toggle_help,
            pygame.K_F12: self.screenshot,
        }
        if ev.key in actions:
            actions[ev.key]()
            return
        if ev.key == pygame.K_ESCAPE and self.fast:  # 読み込みの途中ならやめる
            self.cancel_loading()
            return
        if ev.key == pygame.K_ESCAPE:
            self.press_brk("key")
            return
        if ev.key == pygame.K_F5:
            m.reset_key = True
            return
        fkeys = {pygame.K_F1: "RUN", pygame.K_F2: "PRO", pygame.K_F3: "RSV", pygame.K_F4: "OFF"}
        if ev.key in fkeys:
            mode = fkeys[ev.key]
            if self.is1350:  # F1・F2はMODEキーでRUN・PROに、F3・F4は電源スイッチ
                mode = "ON" if mode == "RSV" else mode
                if mode in ("RUN", "PRO"):
                    self.typer.add_mode(mode)
                else:
                    self.set_mode(mode)
            elif mode in m.model.modes:  # PC-1245にはRSVがない
                self.set_mode(mode)
            return
        if ev.key == pygame.K_BACKSPACE:
            if self.is1350:
                self.typer.add_live_keys([["LEFT"], ["DEL"]])
            else:
                self.typer.add_live_keys([["LEFT"], ["SHIFT"], ["LEFT"]])
            return
        if mods & (pygame.KMOD_META | pygame.KMOD_CTRL):
            return
        name = self.key_name(ev.key)
        if name is None and not mods & pygame.KMOD_SHIFT:
            name = DIGITS.get(ev.key)  # Shift付きの数字キーは記号になる
        if name:
            self.typer.press_live(name, ev.key)

    def key_name(self, key: int) -> str | None:
        """パソコンのキーを本体のキーの名前にする(数字キーを除く)"""
        if self.numpad_arrows and key in NUMPAD_ARROWS:
            return NUMPAD_ARROWS[key]
        if self.is1350 and key in DIRECT_1350:
            return DIRECT_1350[key]
        return DIRECT.get(key) or LETTERS.get(key)

    def key_up(self, ev) -> None:
        m = self.m
        if self.held_key is not None and getattr(self.held_key[0], "key", None) == ev.key:
            self.held_key = None
        if ev.key == pygame.K_ESCAPE:
            self.release_brk("key")
        elif ev.key == pygame.K_F5:
            m.reset_key = False
        name = self.key_name(ev.key) or DIGITS.get(ev.key)
        if name:
            self.typer.release_live(name, ev.key)
        if ev.key in NUMPAD_ARROWS:  # 押しているあいだにモードを切り替えたとき
            self.typer.release_live(DIRECT[ev.key], ev.key)
            self.typer.release_live(NUMPAD_ARROWS[ev.key], ev.key)

    def text_input(self, text: str) -> None:
        menu = self.menu
        if menu is not None:  # 一覧では「/」で探し始め、そのあとの字で絞る
            if menu.query is not None:
                menu.search(menu.query + text)
            elif text == "/":
                menu.search("")
            return
        if self.popup is not None:
            return
        panel = self.pad_panel
        if panel is not None:
            # 記号のキーは打った字で割り当てる。英数字はKEYDOWNで割り当てている
            alnum = text.isascii() and text.isalnum()
            if panel.selected is not None and not alnum and text in self.pad_key_names():
                self.pad_assign(text)
            return
        if self.pane_keys():
            return  # 作業欄の打ち込みはKEYDOWNで受けている
        # KEYDOWNで押しっぱなしとして伝えた英数字と空白を除いて、まとめて打つ
        rest = "".join(ch for ch in text if not (ch.isascii() and (ch.isalnum() or ch == " ")))
        if rest:
            self.typer.add_live_keys(keys_for(rest, self.m.model.name))

    # ---- ゲームパッド ----
    @staticmethod
    def pad_file(prog: "programs.Program | None") -> str:
        """保存した割り当てのファイル。progがNoneなら既定(pads/default.json)。プログラム用は
        pads/programs/の中に、置き場所と同じく機種のフォルダで分けて置く"""
        pads = os.path.join(programs.user_dir(), "pads")
        if prog is None:
            return os.path.join(pads, "default.json")
        model = programs.folder_model(prog.paths[0]) if prog.paths else ""
        sub = programs.model_dir(model) if model else ""
        return os.path.join(pads, "programs", sub, f"{prog.name}.json")

    def pad_map_for(self, prog: "programs.Program | None") -> gamepad.PadMap:
        """プログラムprogを読み込んだときの割り当て。自分でそのプログラム用に保存したもの、
        プログラムの# pad:、自分で保存した既定、初期設定の順"""
        if prog is not None:
            saved = gamepad.PadMap.load(
                self.pad_file(prog), tr("{name}用に保存したもの", name=prog.name)
            )
            if saved is not None:
                return saved
            if prog.pad is not None:
                return self.pad_map_of(prog)
        default = gamepad.PadMap.load(self.pad_file(None), tr("保存した既定"))
        return default if default is not None else gamepad.PadMap(source=tr("初期設定"))

    def pad_key_names(self) -> frozenset[str]:
        """この機種で割り当てられるキーの名前"""
        return gamepad.key_names(self.m.model.family)

    def pad_map_of(self, prog: programs.Program) -> gamepad.PadMap:
        """プログラムの# pad: の割り当て。読めない語(この機種にないキーも)があれば知らせる"""
        source = tr("{name}の# pad:", name=prog.title or prog.name)
        found, bad = gamepad.PadMap.parse(prog.pad or "", source, self.pad_key_names())
        self.pad_note = tr("# pad: の{text}が読めません", text=" ".join(bad)) if bad else ""
        if bad:
            self.say(self.pad_note, 6)
        return found

    def set_pad_map(self, pad_map: gamepad.PadMap) -> None:
        """割り当てを替える。押しているパッドの入力は、前の割り当てのキーで離す"""
        self.pad_release_all()
        self.pad_map = pad_map
        self.pad_dirty = False
        self._pad_fit()

    def pad_event(self, ev) -> None:
        """ゲームパッドのイベント。割り当ての画面を出しているあいだは入力を選ぶだけで、
        本体には送らない"""
        for name, iid, pressed in self.pads.handle(ev):
            if self.pad_panel is not None:
                if pressed:
                    self.pad_panel.selected = name
                continue
            self.pad_press(name, iid, pressed)

    def pad_press(self, name: str, iid: int, pressed: bool) -> None:
        """パッドの入力nameを押した・離した。離すときは、押したときに割り当てていたキーを離す
        (そのあいだに割り当てが変わっていても)"""
        source = f"pad{iid}:{name}"
        if pressed:
            key = self.pad_map.get(name)
            if key is None:
                return
            self.pad_down[source] = key
            if key == "BRK":
                self.press_brk(source)
            else:
                self.typer.press_live(key, source)
            return
        key = self.pad_down.pop(source, None)
        if key == "BRK":
            self.release_brk(source)
        elif key is not None:
            self.typer.release_live(key, source)

    def pad_release_all(self) -> None:
        for name, iid, _ in self.pads.release_all():
            self.pad_press(name, iid, False)

    def pad_sync(self) -> None:
        """イベントを受け取れなかった回のあと、外れたパッドの入力を離す"""
        for name, iid, _ in self.pads.sync():
            self.pad_press(name, iid, False)

    def toggle_pad_panel(self, on: bool | None = None) -> None:
        """割り当ての画面を本体の下に出す・しまう(窓の高さが変わる)"""
        on = self.pad_panel is None if on is None else on
        if on == (self.pad_panel is not None):
            return
        self.release_all()
        self.pad_panel = padmenu.PadPanel() if on else None
        self._refit()

    def _pad_fit(self) -> None:
        """割り当ての欄の中身が変わったあと、欄の高さが変わっていれば窓を作り直す"""
        if self.pad_panel is not None and self.laid_content != self._window_size():
            self._refit()

    def _pad_panel_height(self) -> int:
        """割り当ての画面の高さ(出していなければ0)"""
        panel = self.pad_panel
        if panel is None:
            return 0
        return panel.measure(
            self._font(), self._small_font(), self.body_size[0], self.pads.names(), self.pad_map,
            *self._pad_target(),
        )  # fmt: skip

    def _pad_target(self) -> tuple[str | None, bool]:
        """割り当ての欄に出す対象のプログラムの題名(なければNone)と、# pad: の行があるか
        (値のない行も含める)"""
        prog = self.pad_prog
        if prog is None:
            return None, False
        return prog.title or prog.name, prog.pad is not None

    def pad_assign(self, key: str | None) -> None:
        """選んである入力にキーを割り当てる(Noneなら外す)。割り当てたら選びを解く"""
        panel = self.pad_panel
        if panel is None or panel.selected is None:
            return
        self.pad_release_all()
        self.pad_map.set(panel.selected, key)
        self.pad_dirty = True
        panel.selected = None
        self._pad_fit()

    def pad_key(self, ev) -> None:
        """割り当ての画面を出しているあいだのキー"""
        panel = self.pad_panel
        assert panel is not None
        if ev.key == pygame.K_ESCAPE:
            if panel.selected is None:
                self.toggle_pad_panel(False)
            panel.selected = None
            return
        if panel.selected is None:
            return
        if ev.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
            self.pad_assign(None)
            return
        name = DIRECT.get(ev.key) or LETTERS.get(ev.key)
        if name is None and not ev.mod & pygame.KMOD_SHIFT:
            name = DIGITS.get(ev.key)  # Shift付きの数字キーの記号はtext_inputで
        if self.is1350 and ev.key in DIRECT_1350:
            name = DIRECT_1350[ev.key]
        if name is not None:
            self.pad_assign(name)

    def pad_action(self, act: str) -> None:
        """割り当ての画面のボタン"""
        prog = self.pad_prog
        if act == "close":
            self.toggle_pad_panel(False)
        elif act == "reset":
            self.set_pad_map(gamepad.PadMap(source=tr("初期設定")))
        elif act == "from_prog":
            if prog is not None and prog.pad is not None:
                self.set_pad_map(self.pad_map_of(prog))
        elif act == "copy":
            self.set_clipboard(f"# pad: {self.pad_map.text()}".rstrip() + "\n")
            self.say(tr("# pad: の行をクリップボードにコピーしました"), 4)
        elif act in ("save_prog", "save_default"):
            if act == "save_prog" and prog is None:
                return
            path = self.pad_file(prog if act == "save_prog" else None)
            try:
                self.pad_map.save(path)
            except OSError as e:
                self.say(tr("割り当てを保存できません: {error}", error=e), 5)
                return
            if act == "save_default":
                self.pad_map.source = tr("保存した既定")
            elif prog is not None:
                self.pad_map.source = tr("{name}用に保存したもの", name=prog.name)
            self.pad_dirty = False
            self.say(tr("割り当てを{path}に保存しました", path=_short(path)), 5)
        self._pad_fit()

    def pad_click(self, pos) -> bool:
        """割り当ての画面を出しているあいだのクリック。画面の中なら入力かボタン、入力を選んで
        あれば本体の絵のキーをその入力に割り当てる。それ以外(操作欄など)ならFalseを返し、
        普通のクリックとして扱う"""
        panel = self.pad_panel
        assert panel is not None
        hit = panel.hit(pos)
        if hit is not None:
            kind, value = hit
            if kind == "input":
                panel.selected = None if panel.selected == value else value
            else:
                self.pad_action(value)
            return True
        if panel.top <= pos[1] < panel.top + panel.height and pos[0] < self.body_size[0]:
            return True
        if pos[1] >= self.body_size[1] or panel.selected is None or self.lcd_only:
            return False
        x = pos[0] / self.scale - display.MARGIN
        y = pos[1] / self.scale - display.MARGIN
        name = self.panel.key_at(x, y)
        if name is None:
            return False
        self.pad_assign(name)
        return True

    def set_clipboard(self, text: str) -> None:
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
            return
        except (pygame.error, NotImplementedError):
            pass
        cmds = {"darwin": ["pbcopy"], "win32": ["clip"]}
        cmd = cmds.get(sys.platform, ["xclip", "-selection", "clipboard"])
        try:
            subprocess.run(cmd, input=text, text=True, check=False)
        except OSError:
            pass

    # ---- ショートカットと右クリックのメニュー ----
    # Fキーはほかのアプリに取られることがあるので、同じ操作を⌘(Windows・LinuxはCtrl)との
    # 組み合わせと右クリックのメニューにも置く
    def shortcut(self, key: int, mods: int = 0) -> bool:
        if (self.norom or self.pane_keys()) and self.bench_shortcut(key, mods):
            return True
        actions = {
            pygame.K_o: self.open_menu,
            pygame.K_t: lambda: self.change_speed(-1 if mods & pygame.KMOD_SHIFT else 1),
            pygame.K_r: self.toggle_recording if mods & pygame.KMOD_SHIFT else self.press_reset,
            pygame.K_p: self.toggle_pause if mods & pygame.KMOD_SHIFT else self.toggle_halt,
            pygame.K_s: self.save_state if mods & pygame.KMOD_SHIFT else self.screenshot,
            pygame.K_l: self.load_state if mods & pygame.KMOD_SHIFT else None,
            pygame.K_e: self.export_program,
            pygame.K_v: self.paste,
            pygame.K_SLASH: self.toggle_help,
            pygame.K_k: self.toggle_arrows,
            pygame.K_d: None if self.norom else self.toggle_pane,
            pygame.K_UP: lambda: self.move_switch(-1),
            pygame.K_DOWN: lambda: self.move_switch(1),
        }
        act = actions.get(key)
        if act is None:
            return False
        act()
        return True

    # ---- マシン語の作業欄(ROMなし) ----
    def bench_shortcut(self, key: int, mods: int) -> bool:
        """作業欄の⌘(Ctrl)のショートカット。扱ったらTrue"""
        shift = bool(mods & pygame.KMOD_SHIFT)
        b, v = self.bench, self.bench_view
        if b.state != "run" or b.rom:
            # ⌘↑↓(Ctrl+Home・End)で開始番地と書いた所の終わりへ、⌘←→で行の頭と終わりへ
            moves = {
                pygame.K_UP: lambda: b.go(b.start, v.rows),
                pygame.K_HOME: lambda: b.go(b.start, v.rows),
                pygame.K_DOWN: lambda: b.go_end(v.rows),
                pygame.K_END: lambda: b.go_end(v.rows),
                pygame.K_LEFT: b.row_home,
                pygame.K_RIGHT: b.row_end,
            }
            if key in moves:
                moves[key]()
                return True
        if b.start_buf is not None or b.span_buf is not None:
            # 開始番地か範囲の欄に打っているあいだ、貼り付けは欄へ入れる。全体にかかる⌘Aは
            # 使わず、⌘Zは欄に打った字を消す。ほかのショートカットは、欄をやめてから
            if key == pygame.K_v:
                if b.start_buf is not None:
                    self.bench_said(b.paste_start(self.clipboard()))
                else:
                    self.bench_span_said(b.paste_span(self.clipboard()))
                return True
            if key == pygame.K_z:
                if b.start_buf is not None:
                    b.start_buf = ""
                else:
                    b.span_buf = ""
                return True
            if key == pygame.K_a:
                return True
            b.start_buf = b.span_buf = None
        actions = {
            pygame.K_g: lambda: self.bench_do("runcursor" if shift else "go"),
            pygame.K_PERIOD: lambda: self.bench_do("pause"),
            pygame.K_j: lambda: self.bench_do("over" if shift else "step"),
            pygame.K_b: lambda: self.bench_do("break"),
            pygame.K_a: lambda: self.bench_start_at(b.cursor),
            pygame.K_v: self.bench_paste,
            pygame.K_e: lambda: self.bench_export(listing=shift),
            pygame.K_z: lambda: self.bench_undo(redo=shift),
        }
        act = actions.get(key)
        if act is None:
            return False
        act()
        return True

    def bench_do(self, what: str) -> None:
        """作業欄のボタンとショートカットの操作"""
        b, v = self.bench, self.bench_view
        if what == "go":
            what = "resume" if b.state == "pause" else "run"
        if what in ("run", "runcursor") and (b.state == "run" or b.rom):
            return  # ROMのある本体では、マシン語はBASICのCALLで呼ぶ
        self.release_all()
        if what == "run":
            b.run()
        elif what == "runcursor":
            why = b.start_refusal(b.cursor)
            if why:
                v.say(why, 3)
                return
            b.set_start_at(b.cursor)
            b.run()
        elif what == "resume":
            b.resume()
        elif what == "pause":
            b.pause()
        elif what == "step":
            b.step()
        elif what == "over":
            b.step_over()
        elif what == "abandon":
            b.abandon()
        elif what in ("undo", "redo"):
            self.bench_undo(redo=what == "redo")
            return
        elif what == "break":
            a = b.ins_at(b.cursor)
            on = b.toggle_break(a)
            if on is None:
                v.say(
                    tr("{addr:04X}番地はROMなしでは使えないので、止める所を置けません", addr=a), 3
                )
            else:
                v.say(break_message(a, on), 2)
        self.overshoot = 0

    def bench_start_at(self, addr: int) -> None:
        """番地addrを開始番地に決める"""
        b, v = self.bench, self.bench_view
        msg = b.set_start_at(addr)
        v.say(msg, 3, ok=b.start == addr & 0xFFFF)

    def bench_said(self, msg: str) -> None:
        """開始番地を決める操作の知らせを出す(決められたなら緑、理由なら赤)"""
        b, v = self.bench, self.bench_view
        v.say(msg, 3, ok=msg == tr("開始番地を{addr:04X}にしました", addr=b.start))

    def bench_field_skip(self, ch: str) -> bool:
        """開始番地か範囲の欄に打っているあいだの、16進表記でない字。欄に打ったままにし
        (やめてダンプのキーにすると、続けて打った字がダンプを書き換える)、区切りの字
        (空白、-、~、,、&)でなければ知らせを出す。字でないキー(矢印など)ならFalse"""
        if len(ch) != 1 or not ch.isprintable():
            return False
        if ch not in " -~,&〜":
            self.bench_view.say(tr("番地は16進表記(0〜9、A〜F)で打ちます"), 3)
        return True

    def bench_span_said(self, msg: str) -> None:
        """書き出す範囲を決める操作の知らせを出す(決められたなら緑、理由なら赤)"""
        b, v = self.bench, self.bench_view
        ok = b.span is not None and msg == tr(
            "書き出す範囲を{where}にしました", where=workbench.span_text(*b.span)
        )
        v.say(msg, 3, ok=ok)

    def bench_span_key(self, ev) -> None:
        """範囲の欄に打っているあいだのキー。始めと終わりの番地を16進表記で8桁打てば決まる。
        何も打たずにEnterで自動に戻す。Backspaceで1字消し、Escでやめる。ほかのキーの扱いは
        開始番地の欄と同じ"""
        b = self.bench
        k = ev.key
        ch = (ev.unicode or "").upper()
        if len(ch) == 1 and ch in "0123456789ABCDEF":
            msg = b.type_span(int(ch, 16))
            if msg:
                self.bench_span_said(msg)
            return
        if k == pygame.K_BACKSPACE and b.span_buf:
            b.span_buf = b.span_buf[:-1]
            return
        if self.bench_field_skip(ch):
            return
        if k in (pygame.K_RETURN, pygame.K_KP_ENTER) and not b.span_buf:
            self.bench_view.say(b.clear_span(), 3, ok=True)
            return
        b.span_buf = None
        if k not in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
            self.bench_key(ev)

    def bench_start_key(self, ev) -> None:
        """開始番地の欄に打っているあいだのキー。16進表記の4桁を打てば決まる。Backspaceで
        1字消し、Escでやめる。16進表記でない字は欄で止め、字でないキー(矢印など)は、やめた
        うえでダンプのキーとして扱う"""
        b = self.bench
        k = ev.key
        ch = (ev.unicode or "").upper()
        if len(ch) == 1 and ch in "0123456789ABCDEF":
            msg = b.type_start(int(ch, 16))
            if msg:
                self.bench_said(msg)
            return
        if k == pygame.K_BACKSPACE and b.start_buf:
            b.start_buf = b.start_buf[:-1]
            return
        if self.bench_field_skip(ch):
            return
        b.start_buf = None
        if k not in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
            self.bench_key(ev)

    def bench_key(self, ev) -> None:
        """実行していないときのキー。16進表記の字でダンプを書き、矢印で動く"""
        b, v = self.bench, self.bench_view
        if b.start_buf is not None:
            self.bench_start_key(ev)
            return
        if b.span_buf is not None:
            self.bench_span_key(ev)
            return
        k = ev.key
        if k == pygame.K_ESCAPE:
            if b.rom:  # キーを本体へ戻す
                v.focus = False
            elif b.state == "pause":
                b.abandon()
            return
        ch = (ev.unicode or "").upper()
        msg = ""
        if len(ch) == 1 and ch in "0123456789ABCDEF":
            msg = b.type_hex(int(ch, 16))
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            b.next_line()
        elif k == pygame.K_SPACE:
            b.to_data()
        elif k in (pygame.K_LEFT, pygame.K_BACKSPACE):
            b.left(v.rows)
        elif k == pygame.K_RIGHT:
            b.right(v.rows)
        elif k in (pygame.K_UP, pygame.K_DOWN):
            b.move_rows(-1 if k == pygame.K_UP else 1, v.rows)
        elif k in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            b.page(-1 if k == pygame.K_PAGEUP else 1, v.rows)
        elif k == pygame.K_TAB:
            b.to_addr()
        elif k == pygame.K_HOME:
            b.row_home()
        elif k == pygame.K_END:
            b.row_end()
        if msg:
            v.say(msg)

    REPEAT = (0.45, 0.05)  # 作業欄のキーのリピート(押してから始まるまで、間隔。秒)
    # リピートするキー(カーソルを動かすもの。16進表記の字は押し続けても1字だけ)
    REPEAT_KEYS = frozenset(
        (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_PAGEUP,
         pygame.K_PAGEDOWN, pygame.K_BACKSPACE)
    )  # fmt: skip

    def _key_repeat(self) -> None:
        """作業欄にキーを打っているあいだだけ、押し続けたカーソルのキーを1フレームに1回まで
        リピートさせる(pygameのリピートは、フレームが遅れるとたまった分をまとめて届け、
        離したあとにも残りが届いて行き過ぎる)"""
        held = self.held_key
        if held is None:
            return
        if not self.pane_keys() or self.menu is not None or self.popup is not None:
            self.held_key = None
            return
        ev, at = held
        now = time.monotonic()
        if now >= at:
            self.bench_key(ev)
            self.held_key = (ev, now + self.REPEAT[1])

    def bench_click(self, pos) -> None:
        b, v = self.bench, self.bench_view
        hit = v.hit(pos)
        if hit is None:
            return
        kind, a = hit
        if kind != "start":
            b.start_buf = None
        if kind != "span":
            b.span_buf = None
        if kind == "button":
            if v.buttons[a].enabled:
                self.bench_do(v.buttons[a].action)
        elif kind == "clearlcd":
            b.clear_lcd = not b.clear_lcd
        elif kind == "start":
            if b.state == "run" and not b.rom:
                v.say(
                    tr("実行中は打てません。{c}Aか右クリックで、カーソルの所を開始番地にできます",
                       c=CMD), 4
                )  # fmt: skip
            else:
                b.start_buf = "" if b.start_buf is None else None
        elif kind == "export":
            self.bench_export()
        elif kind == "listing":
            self.bench_export(listing=True)
        elif kind == "spanauto":
            v.say(b.clear_span(), 3, ok=True)
        elif kind == "span":
            if b.state == "run" and not b.rom:
                v.say(tr("実行中は範囲を打てません"), 3)
            else:
                b.span_buf = "" if b.span_buf is None else None
        elif kind == "iram":
            v.show_iram = not v.show_iram
            self._save_view()
            self._refit()
        elif kind == "break":
            if b.toggle_break(a) is None:
                v.say(
                    tr("{addr:04X}番地はROMなしでは使えないので、止める所を置けません", addr=a), 3
                )
        elif kind in ("addr", "byte", "goto", "why") and (b.state != "run" or b.rom):
            first = (b.row - 8 * b.top_rows) & 0xFFFF
            off = (a - first) & 0xFFFF
            if kind == "addr":
                b.row, b.top_rows, b.field, b.nib = a, off // 8, "addr", 0
            else:
                b.place(a, v.rows)  # バイトか逆アセンブルの行。行の並びは変えない

    def bench_open(self, prog: programs.Program, run: bool = False) -> None:
        """ROMなしでプログラムを読み込む。マシン語のダンプをRAMに書き、BASICは実行しない。
        呼び出し用のBASICから、数だけを書くPOKE(IFのあとを除く)を拾って書き、最後のCALLの
        番地を開始番地にする(CALLがなければ最初のダンプの番地)"""
        b, m = self.bench, self.m
        name = prog.title or prog.name
        if prog.errors:
            self.say(tr("{name}を読み込みません。{why}", name=name, why=prog.errors[0]), 8)
            return
        pokes, start = workbench.basic_hints(f"{prog.basic}\n{prog.run}")
        blocks = prog.blocks + pokes + prog.after
        if not prog.norom_ok:
            if prog.blocks:
                why = tr("{name}はBASICとROMのルーチンを使うプログラムなので、"
                         "ROMなしでは使えません", name=name)  # fmt: skip
            else:
                why = tr("{name}はBASICのプログラムなので、ROMなしでは使えません", name=name)
            self.say(why, 6)
            return
        if not self._ram_fits(prog):
            return
        outside = self._outside(blocks, prog.ram_top)
        if outside:
            self.say(outside_message(name, outside[0]), 8)
            return
        self.undo_bench = b.save()  # 実行中・一時停止中なら、その状態のまま覚える
        if b.state != "edit":
            b.abandon()
        self.undo_state, self.undo_title = m.snapshot(), name
        self.undo_prog = self._prog_undo()
        m.set_ram_top(prog.ram_top)
        b.use_data(prog.data)
        n = b.load_blocks(blocks, start)
        b.calls = workbench.basic_calls(f"{prog.basic}\n{prog.run}")
        self.pad_prog, self.pad_note = prog, ""
        self.set_pad_map(self.pad_map_for(prog))
        self.last_prog = prog
        self.loading, self.load_help = prog.title, prog.norom
        done = tr("{name}を読み込みました({n}バイト、開始番地{addr:04X})。{c}Gで実行",
                  name=name, n=n, addr=b.start, c=CMD)  # fmt: skip
        self.say_loaded(f"{done}\n{prog.norom}" if prog.norom else done, 12 if prog.norom else 6)
        if run:
            self.bench_do("run")

    def bench_undo(self, redo: bool = False) -> None:
        """作業欄の書き込みを取り消す(redoならやり直す)。ROMのある本体では、続けて⌘Zで
        取り消せるように、キーを作業欄で受けるようにする"""
        b, v = self.bench, self.bench_view
        done = b.can_redo() if redo else b.can_undo()
        v.say(b.redo() if redo else b.undo(), 3, ok=done)
        if done and b.rom:
            v.focus = True

    def bench_paste(self) -> None:
        """クリップボードのダンプ(本のダンプリストか.hexの行)を書く"""
        b, v = self.bench, self.bench_view
        if b.state == "run" and not b.rom:
            return
        start = b.start
        res = b.paste(self.clipboard())
        if not res.written:
            v.say(tr("貼り付けた文字にダンプの行がありません"), 4)
            return
        parts = [tr("{n}バイトを書きました", n=res.written)]
        if res.bad_sums:
            where = tr("、").join(f"{a:04X}" for a in res.bad_sums[:4])
            parts.append(tr("チェックサムが合わない行: {where}", where=where))
        if res.outside:
            parts.append(tr("RAMの外の{n}バイトは書けません", n=res.outside))
        if b.start != start:
            parts.append(tr("開始番地は{addr:04X}", addr=b.start))
        v.say(tr("。").join(parts), 8)

    def bench_export(self, listing: bool = False) -> None:
        """書き出す範囲のマシン語を、置き場所に.hexで書き出す。逆アセンブルつきか、listingなら
        本のダンプリストの形(8バイト:チェックサム)。どちらも読み込める"""
        b, v = self.bench, self.bench_view
        ranges = b.export_ranges()
        if not ranges:
            v.say(tr("書き出すダンプがありません"), 4)
            return
        where = tr("、").join(workbench.span_text(lo, hi) for lo, hi in ranges)
        try:
            folder = os.path.join(programs.user_dir(), programs.model_dir(self.m.model.name))
            os.makedirs(folder, exist_ok=True)
            stem = "dumplist" if listing else "dump"
            path = paths.unused_file(folder, f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}", ".hex")
            # 開始番地は# run:に書く(読み込むと、ROMなしではここから、ROMがあればこのCALLで動く)
            note = tr("{where}(マシン語の作業欄から書き出し)", where=where)
            # 自分で決めたデータの範囲は# data: に書く(読み込むと同じ指定になる)
            head = f"; {note}\n# run: CALL &{b.start:04X}\n" + programs.data_line(b.data_spans())
            head += self._ram_line()  # 広げたRAMにあるダンプを、読み込み直せるように
            dump = b.dump_list if listing else b.dump_text
            body = "".join(dump(lo, hi) for lo, hi in ranges)
            with open(path, "w", encoding="utf-8") as f:
                f.write(head + body)
        except OSError as e:
            v.say(tr("書き出せません: {error}", error=e), 5)
            return
        size = sum(hi - lo for lo, hi in ranges)
        name = os.path.basename(path)
        v.say(
            tr("{name}を書き出しました({n}バイト)。置き場所: {folder}",
               name=name, n=size, folder=_short(folder)), 8
        )  # fmt: skip

    def clipboard(self) -> str:
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
        return text

    SPEEDS = (0.5, 1, 2, 4, 8)

    def change_speed(self, step: int) -> None:
        """速さを1段上げる(step=1)か下げる(step=-1)。両端ではそのまま"""
        i = self.SPEEDS.index(self.turbo) + step
        self.turbo = self.SPEEDS[min(max(i, 0), len(self.SPEEDS) - 1)]
        self.say(tr("速さ {speed}", speed=speed_label(self.turbo)), 1.5)

    def toggle_arrows(self) -> None:
        self.numpad_arrows = not self.numpad_arrows
        if self.numpad_arrows:
            self.say(tr("矢印キー → 数字キーの8・2・4・6"), 2.5)
        else:
            self.say(tr("矢印キー → ↑↓◀▶"), 2.5)

    def toggle_help(self) -> None:
        self.help = 0 if self.help else FPS * 10

    # ---- 操作欄とプリンタ ----
    def _window_size(self) -> tuple[int, int]:
        """窓の大きさ。本体の下に、プリンタの紙(印字したとき)と操作欄を足す"""
        w, h = self.body_size
        if self.paper_open:
            h += self.paper.height
        h += self._pad_panel_height() + BAR_H
        if self.pane_open:
            return w + benchview.PANE_W, max(h, self.bench_view.min_height())
        return w, h

    def bar_buttons(self) -> list[BarButton]:
        """操作欄のボタン。左に目的ごとのメニュー、続けて実行の一時停止と速さ、右端に録画。
        録画しているあいだは、録画のボタンが録画中の印と経過時間になり、押すと止めるか
        一時停止するかのメニューが出る"""

        def menu(kind: str):
            return lambda: self.open_bar_popup(kind)

        c, s = CMD, SHIFT
        view_tip = tr(
            "キーの説明({c}/)、矢印キー・ゲームパッドの割り当て、液晶だけ、画面の画像、印字", c=c
        )
        buttons = [
            BarButton(tr("プログラム"), menu("program"), short=tr("プログラム"), menu="program",
                      tip=tr("一覧、書き出し、貼り付け(一覧は{c}O)", c=c)),
            BarButton(tr("本体"), menu("machine"), short=tr("本体"), menu="machine",
                      tip=tr("状態の保存と復元、スイッチ、RESET")),
            BarButton(tr("表示・入力"), menu("view"), short=tr("表示"), menu="view",
                      tip=view_tip),
        ]  # fmt: skip
        if self.halted:
            tip = tr("止めている実行を続ける({c}P)", c=c)
            buttons.append(BarButton(tr("実行を再開"), self.toggle_halt, "play", tr("再開"), tip))
        elif not self.norom:  # ROMなしでは、実行と一時停止は作業欄のボタンで行う
            tip = tr("CPUの実行を止める({c}P)。録画は止まりません", c=c)
            buttons.append(
                BarButton(tr("実行を一時停止"), self.toggle_halt, "pause", tr("一時停止"), tip)
            )
        if not self.norom and not self.lcd_only:
            # 作業欄の出し入れ。矢印は作業欄が動く向き(右へ出す・左へしまう)
            if self.pane_open:
                label, tip = tr("◀ 作業欄"), tr("マシン語の作業欄をしまう({c}D)", c=c)
            else:
                label, tip = tr("作業欄 ▶"), tr("マシン語の作業欄を出す({c}D)", c=c)
            buttons.append(BarButton(label, self.toggle_pane, "", label, tip, True))
        if self.lcd_only:  # 液晶だけのあいだは、メニューを開かずに本体へ戻れるように
            tip = tr("本体の絵を出す(窓の大きさは固定に戻ります)")
            buttons.append(BarButton(tr("本体を出す"), self.toggle_lcd, "", tr("本体を出す"), tip))
        speed = speed_label(self.turbo)
        tip = tr("実行の速さを選ぶ({c}Tで速く、{s}{c}Tで遅く)", c=c, s=s)
        label = tr("速さ {speed}", speed=speed)
        buttons.append(BarButton(label, menu("speed"), "", speed, tip, True, "speed"))
        rec = self.recorder
        if rec is None:
            tip = tr("録画を始める({s}{c}R)", c=c, s=s)
            buttons.append(BarButton(tr("録画"), self.toggle_recording, "rec", tr("録画"), tip))
        else:
            sec = int(rec.seconds)
            clock = f"{sec // 60}:{sec % 60:02d}"
            tip = tr("録画を止める({s}{c}R)か、一時停止する({s}{c}P)", c=c, s=s)
            if self.rec_paused:
                label, icon = tr("録画を一時停止中 {clock}", clock=clock), "recpause"
            else:
                label, icon = tr("録画中 {clock}", clock=clock), "rec"
            buttons.append(BarButton(label, menu("rec"), icon, clock, tip, menu="rec"))
        return buttons

    def bar_info(self) -> str:
        """操作欄の右に出す、いまの設定(速さと一時停止はボタンに出る)"""
        m = self.m
        parts = [m.model.title + (" " + tr("{n}KBカード", n=m.card) if m.card else "")]
        if self.last_prog is not None:
            parts.append(self.last_prog.title or self.last_prog.name)
        if self.numpad_arrows:
            parts.append(tr("矢印→8246"))
        if m.tape is not None:
            parts.append(tr("テープ"))
        return "   ".join(parts)

    def cancel_loading(self) -> None:
        """読み込みの打ち込みをやめる。打ち込んだところまではRAMに残る"""
        self.typer.clear()
        self.fast = False
        self.say(tr("読み込みをやめました(途中まで入っています)。{hint}", hint=undo_hint()), 6)

    @property
    def paper_open(self) -> bool:
        return self.printout is not None

    def close_paper(self) -> None:
        """プリンタの紙をしまう(窓の高さが変わる)"""
        if self.printout is None:
            return
        self._finish_paper()
        self.paper_back = 0
        self._refit()
        # まだ出していない行は次の紙に出さない(保存はprinter.rowsから済んでいる)
        self.printed = self.m.printer.count if self.m.printer is not None else 0
        self.paper.feed, self.print_gap, self.print_hold = 0.0, 0, 0.0

    def _finish_paper(self) -> None:
        """いまの紙を終わりにする。まだ保存していない印字を保存し、次の印字は新しい紙と
        ファイルにする(途中の行なら、その先の字から)"""
        if self.printout is None:
            return
        self.save_printout()
        self.print_cut = self.printout.cut()
        self.printout.close()
        self.printout = None

    def paper_rows(self) -> list[bytes]:
        """いまの紙に出ている行のコード。まだ出していない行と、改行していない途中の行は除く
        (実機も、行の終わりを受け取ってから印字する)"""
        printer = self.m.printer
        if self.printout is None or printer is None:
            return []
        rows = self.printout.rows()
        waiting = printer.count - self.printed
        partial = 1 if bytes(printer.line).rstrip(b" ") else 0
        return rows[: max(0, len(rows) - waiting - partial)]

    def _print_next_line(self) -> None:
        """紙に出していない行があれば、前の行を出し終えたあとに次の行を出し始める。速さは
        実機の速さに速さの設定(turbo)を掛けたもの。出していない行がPRINT_KEEPより多ければ、
        PRINT_CATCH_UP秒で出し切る速さに上げて、出し切るまでその速さを保つ。1フレームに1行より
        速ければ、何行かまとめて出す(紙送りは1行ぶんにして、紙に出した行が見えなくならないように)"""
        printer = self.m.printer
        if printer is None or self.printout is None:
            return
        if self.print_gap:
            self.print_gap -= 1
            return
        if self.paper.moving or self.printed >= printer.count:
            return
        waiting = printer.count - self.printed
        rate = max(float(self.turbo), self.print_hold)
        if waiting > PRINT_KEEP:
            rate = max(rate, waiting * (PRINT_LINE + PRINT_GAP) / PRINT_CATCH_UP)
        line, gap = PRINT_LINE / rate, PRINT_GAP / rate
        lines = min(waiting, math.ceil(1 / ((line + gap) * FPS)))
        line_frames = max(1, round(lines * line * FPS))
        self.printed += lines
        self.paper_back = 0
        self.paper.line_frames = line_frames
        self.paper.fed(1)
        self.print_rate = rate
        self.print_hold = rate if rate > self.turbo and self.printed < printer.count else 0.0
        # 次の行は、印字と間のフレームが過ぎた次のフレームから
        self.print_gap = max(line_frames, round(lines * (line + gap) * FPS)) - 1

    def check_printer(self) -> None:
        """新しく印字したものがあれば紙を出し、行を1つずつ送り出す(_print_next_line)。印字が
        とぎれたら保存する"""
        printer = self.m.printer
        if printer is None:
            return
        if printer.changes == self.print_seen:
            self._print_next_line()
            if self.printout is not None and self.printout.due():
                self.save_printout()
            return
        self.print_seen = printer.changes
        if self.printout is None:  # 新しい紙
            self.printout = Printout(printer, self.print_cut, programs.user_dir())
            if self.printout.error is not None:  # 紙は出すが、印字の絵は保存しない
                self.say(tr("印字を保存できません: {error}", error=self.printout.error), 5)
            self._refit()
            self.save_printout()  # 名前を取っておくため、すぐに1度保存する
        self.printout.touched()
        self._print_next_line()

    def save_printout(self) -> None:
        """いまの紙の印字を保存する(Printout.save)。保存したら、できなければ知らせる"""
        out = self.printout
        if out is None:
            return
        try:
            saved = out.save(self.paper)
        except (OSError, pygame.error) as e:
            self.say(tr("印字を保存できません: {error}", error=e), 5)
            out.file = None
            return
        if saved and out.file is not None:
            self.say(tr("印字を{path}に保存しました", path=_short(out.file)), 5)

    def reveal_printout(self) -> None:
        """印字を保存したフォルダを開く"""
        self.save_printout()
        out = self.printout
        file = out.file if out is not None else None
        self.reveal(os.path.dirname(file) if file else programs.user_dir())

    def scroll_paper(self, step: int) -> None:
        """紙の上でホイールを回すと、前の行を見せる"""
        printer = self.m.printer
        y = pygame.mouse.get_pos()[1] - self.origin[1]
        h = self.body_size[1]
        if printer is None or not self.paper_open or not h <= y < h + self.paper.height:
            return
        rows = len(self.paper_rows())
        self.paper_back = min(max(self.paper_back + step, 0), max(0, rows - 1))

    def press_reset(self) -> None:
        """裏のRESETボタンを0.3秒押す。ROMなしでは、実行をやめて作業欄に戻る"""
        if self.norom:
            self.bench_do("abandon")
            return
        self.m.reset_key = True
        self.reset_frames = max(1, FPS * 3 // 10)

    def move_switch(self, step: int) -> None:
        order = [name for name, _y in self.sw_stops]
        i = order.index(self.m.mode) if self.m.mode in order else order.index(order[-2])
        self.set_mode(order[min(max(i + step, 0), len(order) - 1)])

    def popup_items(self, kind: str | None = None) -> list[MenuItem]:
        """メニューの項目。kindは操作欄のボタンのメニュー(program、machine、view、speed、
        録画中のrec)か、右クリックのメニュー(context、paper)。なければいま出しているメニュー"""
        if kind is None:
            kind = self.popup.kind if self.popup is not None else "context"
        sep, item = SEPARATOR, MenuItem
        c, s = CMD, SHIFT
        stopped = self.bench.state == "pause"
        pause = item(tr("実行を再開する") if stopped else tr("実行を一時停止する"), f"{c}P",
                     self.toggle_halt)  # fmt: skip
        if kind == "program":
            # ROMなしでは、⌘E・⌘Vと同じく作業欄のダンプを書き出す・貼り付ける
            if self.norom:
                export = item(tr("ダンプをファイル(.hex)に書き出す"), f"{c}E", self.bench_export,
                              self.bench.export_summary())  # fmt: skip
                listing = item(tr("ダンプリストの形で書き出す"), f"{s}{c}E",
                               lambda: self.bench_export(listing=True),
                               tr("8バイト:チェックサムの行"))  # fmt: skip
                paste = item(tr("クリップボードからダンプを貼り付ける"), f"{c}V", self.bench_paste)
            else:
                export = item(tr("プログラムをファイルに書き出す"), f"{c}E", self.export_program)
                listing = None
                paste = item(tr("クリップボードから打ち込む"), f"{c}V", self.paste)
            items = [
                item(tr("プログラムの一覧…"), f"{c}O", self.open_menu),
                export,
                *([listing] if listing else []),
                paste,
                item(tr("置き場所のフォルダを開く"), "", lambda: self.reveal(programs.user_dir())),
            ]
            if self.norom or self.pane_open:
                # 作業欄の書き込みの取り消しとやり直し。下に、何を取り消すか(できなければ理由)
                note, on = self.bench.undo_note()
                rnote, ron = self.bench.undo_note(redo=True)
                items += [
                    sep,
                    item(tr("ダンプの書き込みを取り消す"), f"{c}Z", self.bench_undo, note,
                         enabled=on),
                    item(tr("ダンプの書き込みをやり直す"), f"{s}{c}Z",
                         lambda: self.bench_undo(redo=True), rnote, enabled=ron),
                ]  # fmt: skip
            if self.load_help:
                show = lambda: self.say(self.load_help, 20)  # noqa: E731
                items += [sep, item(tr("読み込んだプログラムの説明"), "", show, self.loading)]
            return items
        if kind == "machine":
            items = [
                item(tr("いまの状態を保存(どこでもセーブ)"), f"{s}{c}S", self.save_state),
                item(tr("保存した状態に戻す"), f"{s}{c}L", self.load_state, self.saved_when()),
            ]
            if self.undo_state is not None:
                note = tr("{title}を読み込む前", title=self.undo_title)
                items.append(item(tr("プログラムを読み込む前に戻す"), "", self.undo_loading, note))
            items.append(sep)
            for name, _y in self.sw_stops:
                key = f"{c}↑↓" if self.m.mode == name else ""
                items.append(item(switch_label(name), key, lambda n=name: self.set_mode(n)))
            return items + [sep, item(tr("RESETボタンを押す"), f"{c}R", self.press_reset)]
        if kind == "view":
            if self.numpad_arrows:
                arrows = tr("矢印キーを↑↓◀▶に戻す")
            else:
                arrows = tr("矢印キーを8・2・4・6にする")
            pads = self.pads.names()
            if pads:
                note = tr("{names}がつながっています", names=tr("、").join(pads))
            else:
                note = tr("パッドはつながっていません")
            lcd = tr("本体の絵を出す") if self.lcd_only else tr("液晶だけにする(窓を広げられる)")
            items = [
                item(tr("キーの説明"), f"{c}/", self.toggle_help),
                item(arrows, f"{c}K", self.toggle_arrows),
                item(tr("ゲームパッドの割り当て…"), "", self.toggle_pad_panel, note),
                sep,
                item(lcd, "", self.toggle_lcd),
                item(tr("画面を画像で保存"), f"{c}S", self.screenshot),
            ]
            if not self.norom:
                if self.pane_open:
                    pane = tr("マシン語の作業欄をしまう")
                else:
                    pane = tr("マシン語の作業欄を出す")
                note = tr("液晶だけのあいだは出せません") if self.lcd_only else ""
                items[3:3] = [item(pane, f"{c}D", self.toggle_pane, note, enabled=not note)]
            # 言語の切り替え。項目の名前は、切り替えた先の言語で書く
            other = "en" if i18n.language() == "ja" else "ja"
            name = LANGUAGE_NAMES[other]
            items += [sep, item(name, "", lambda: self.set_language(other))]
            paper = self.popup_items("paper")
            return items + ([sep, *paper] if paper else [])
        if kind == "rec":
            if self.rec_paused:
                pause = item(tr("録画を再開する"), f"{s}{c}P", self.toggle_pause, icon="rec")
            else:
                pause = item(tr("録画を一時停止する"), f"{s}{c}P", self.toggle_pause,
                             icon="recpause")  # fmt: skip
            stop = item(tr("録画を止めて保存"), f"{s}{c}R", self.toggle_recording, icon="stop")
            return [stop, pause]
        if kind == "speed":
            return [item(tr("速さ {speed}", speed=speed_label(v)), "",
                         lambda v=v: self.set_speed(v))
                    for v in self.SPEEDS]  # fmt: skip
        if kind == "bench":
            return self.bench_items()
        if kind == "paper":
            out = self.printout
            if out is None:
                return []
            items = [item(tr("プリンタの紙をしまう"), "", self.close_paper)]
            if out.file:
                items.insert(0, item(tr("印字の保存先を開く"), "", self.reveal_printout))
            return items
        return [  # 右クリック(場所によらない、よく使うものだけ)
            pause,
            item(tr("プログラムの一覧…"), f"{c}O", self.open_menu),
            item(tr("画面を画像で保存"), f"{c}S", self.screenshot),
            item(tr("キーの説明"), f"{c}/", self.toggle_help),
        ]

    def popup_mark(self) -> str:
        """いま出しているメニューで●をつける項目(スイッチの位置か、いまの速さ)"""
        kind = self.popup.kind if self.popup is not None else ""
        if kind == "speed":
            return tr("速さ {speed}", speed=speed_label(self.turbo))
        return switch_label(self.m.mode)

    def set_speed(self, speed: float) -> None:
        self.turbo = speed
        self.say(tr("速さ {speed}", speed=speed_label(speed)), 1.5)

    def set_language(self, lang: str) -> None:
        """画面の言語を切り替えて、次に起動したときのために覚えておく"""
        i18n.set_language(lang)
        self.bench_view.flash = ""
        self._save_view(lang)
        self.say(tr("表示を日本語にしました"), 3)

    def saved_when(self) -> str:
        """保存した状態の日時(「10/22 15:30に保存」)。保存していなければそう書く"""
        try:
            t = os.path.getmtime(self.state_file)
        except OSError:
            return tr("まだ保存していません")
        when = time.strftime("%m/%d %H:%M", time.localtime(t)).lstrip("0")
        return tr("{when}に保存", when=when)

    def toggle_halt(self) -> None:
        """実行を一時停止する。止めているあいだはCPUも時計も進まない(録画の一時停止とは別)。
        ROMなしでは、作業欄の一時停止と続けるにする(止めた状態を1つにする)"""
        state = self.bench.state
        if state == "run":
            self.bench_do("pause")
            if not self.norom:
                self.say(
                    tr("実行を一時停止しました。{c}Pか操作欄の「実行を再開」で続けます", c=CMD), 4
                )
        elif state == "pause":
            self.bench_do("resume")
            if not self.norom and self.bench.state == "run":
                self.say(tr("実行を再開しました"), 1.5)
        else:
            self.say(tr("実行していません。{c}Gで開始番地から実行します", c=CMD), 3)

    @property
    def halted(self) -> bool:
        """ROMのある本体で、実行を一時停止しているか(作業欄の一時停止と同じ状態)。ROMなしの
        本体の実行と一時停止は作業欄が扱うので、いつもFalse"""
        return not self.norom and self.bench.state == "pause"

    @halted.setter
    def halted(self, on: bool) -> None:
        if not self.norom and on != self.halted:
            self.toggle_halt()

    def _prog_undo(self) -> tuple:
        """読み込む前に戻すために覚える、読み込んだプログラムの情報と割り当て"""
        return (
            self.last_prog, self.loading, self.load_help, self.pad_prog, self.pad_map,
            self.pad_dirty,
        )  # fmt: skip

    def undo_loading(self) -> None:
        """プログラムを読み込む直前の状態に戻す"""
        state, title = self.undo_state, self.undo_title
        if state is None:
            return
        try:
            self.m.restore(state)
        except ValueError as e:
            self.say(tr("読み込む前に戻せません: {error}", error=e), 5)
            return
        # 書き出しや説明に使う、読み込んだプログラムの情報も読み込む前のものに戻す
        self.last_prog, self.loading, self.load_help, self.pad_prog, pad_map, dirty = self.undo_prog
        self.set_pad_map(pad_map)
        self.pad_dirty = dirty
        done = tr("{title}を読み込む前に戻しました", title=title)
        self.bench.restore(self.undo_bench, done)
        self.undo_state = None
        self._restored(done)

    def open_bar_popup(self, kind: str) -> None:
        """操作欄のボタンのメニューを、そのボタンのすぐ上に出す"""
        i = next((i for i, b in enumerate(self.bar.buttons) if b.menu == kind), -1)
        r = self.bar.rects[i] if 0 <= i < len(self.bar.rects) else None
        if r is None or not r.width:
            r = pygame.Rect(8, self.body_size[1], 0, 0)
        self._make_room()
        ox, oy = self.origin
        self.popup = Popup((r.x + ox, r.y + oy), kind, above=True, source=i)

    def next_bar_popup(self, step: int) -> None:
        """開いている操作欄のメニューから、左右の隣のメニューのボタンへ移る(←→)"""
        popup = self.popup
        assert popup is not None
        menus = [i for i, b in enumerate(self.bar.buttons) if b.menu and self.bar.rects[i].width]
        if popup.source in menus:
            i = menus[(menus.index(popup.source) + step) % len(menus)]
            self.open_bar_popup(self.bar.buttons[i].menu)

    def open_popup(self, win) -> None:
        """右クリックのメニュー(winは窓の中の位置)。作業欄の上ならクリックした番地の操作、
        プリンタの紙の上なら紙の操作、ほかはよく使う操作だけ。メニューは窓全体に描くので、
        窓を広げたぶん位置をずらす"""
        pos = self._in_content(win)
        dx, dy = self._make_room()
        win = (win[0] + dx, win[1] + dy)
        if self.pane_open and pos[0] >= self.body_size[0]:
            self.bench_menu(pos, win)
            return
        on_paper = self.paper_open and self.body_size[1] <= pos[1] < self._paper_bottom()
        if on_paper and self.popup_items("paper"):
            self.popup = Popup(win, "paper")
        else:
            self.popup = Popup(win, "context")

    def _in_content(self, win) -> tuple[int, int]:
        """窓の中の位置を中身の中の位置に直す(窓が中身より大きいとき、中身はまんなかにある)"""
        return win[0] - self.origin[0], win[1] - self.origin[1]

    def bench_menu(self, pos, win=None) -> None:
        """作業欄の右クリック(posは中身の中の位置、winは窓の中の位置)。ダンプのバイトか
        逆アセンブルの行なら、その番地にカーソルを置き(ROMなしで実行中は置かない)、その番地の
        操作のメニューを出す。ほかの所ならカーソルの番地の操作"""
        b, v = self.bench, self.bench_view
        b.start_buf = b.span_buf = None
        v.focus = True
        hit = v.hit(pos)
        kind, a = hit if hit is not None else ("", 0)
        if kind in ("byte", "goto", "break", "addr", "why"):
            if b.state != "run" or b.rom:
                b.place(a, v.rows)
            self.bench_at = a
        else:
            self.bench_at = b.cursor
        self.popup = Popup(pos if win is None else win, "bench")

    def bench_items(self) -> list[MenuItem]:
        """作業欄の右クリックのメニュー(App.bench_menuで選んだ番地の操作)"""
        b, item = self.bench, MenuItem
        a = self.bench_at
        here = a == b.cursor  # ショートカットは、カーソルの所に効く
        why = b.start_refusal(a)
        if a == b.start:
            why = tr("いまの開始番地です")
        items = [
            item(tr("{addr:04X}番地を開始番地にする", addr=a), f"{CMD}A" if here else "",
                 lambda: self.bench_start_at(a), why, enabled=not why),
        ]  # fmt: skip
        if not b.rom:
            why = b.start_refusal(a) or (tr("実行中です") if b.state == "run" else "")
            items.append(
                item(tr("{addr:04X}番地から実行する", addr=a), f"{SHIFT}{CMD}G" if here else "",
                     lambda: self.bench_run_at(a), why, enabled=not why)
            )  # fmt: skip
        ins = b.ins_at(a)
        on = ins in b.breaks
        why = "" if on or not b.blocked(ins) else tr("ROMなしでは使えない番地です")
        if on:
            label = tr("{addr:04X}番地の止める所を外す", addr=ins)
        else:
            label = tr("{addr:04X}番地の止める所を置く", addr=ins)
        items.append(
            item(label, f"{CMD}B" if here and ins == b.ins_at(b.cursor) else "",
                 lambda: self.bench_break_at(ins), why, enabled=not why)
        )  # fmt: skip
        # 逆アセンブルで、その番地からをデータか命令に決める(決めなければ推し量る)
        items.append(SEPARATOR)
        marks = (
            ("data", tr("{addr:04X}番地からデータにする", addr=a),
             tr("次の指定か、実行済みの命令の手前までデータ")),
            ("code", tr("{addr:04X}番地から命令にする", addr=a),
             tr("ここから静的解析する")),
            (None, tr("{addr:04X}番地の指定を消す", addr=a), tr("推定に戻す")),
        )  # fmt: skip
        for what, label, note in marks:
            why = b.mark_refusal(a, what)
            items.append(
                item(label, "", lambda w=what: self.bench_mark_at(a, w), why or note,
                     enabled=not why)
            )  # fmt: skip
        return items

    def bench_mark_at(self, addr: int, what: str | None) -> None:
        """番地addrから、逆アセンブルでデータか命令に決める(Noneなら指定を消す)"""
        b, v = self.bench, self.bench_view
        ok = not b.mark_refusal(addr, what)
        v.say(b.set_mark(addr, what), 3, ok=ok)

    def bench_run_at(self, addr: int) -> None:
        """番地addrを開始番地にして実行する"""
        b = self.bench
        if b.set_start_at(addr) and b.start == addr:
            self.bench_do("run")

    def bench_break_at(self, addr: int) -> None:
        on = self.bench.toggle_break(addr)
        if on is not None:
            self.bench_view.say(break_message(addr, on), 2)

    def _paper_bottom(self) -> int:
        return self.body_size[1] + (self.paper.height if self.paper_open else 0)

    def popup_run(self, i: int) -> None:
        items = self.popup_items()
        act = items[i].action if 0 <= i < len(items) else None
        self.popup = None
        if callable(act):
            act()

    def popup_key(self, ev) -> None:
        popup = self.popup
        assert popup is not None
        if ev.key == pygame.K_ESCAPE:
            self.popup = None
        elif ev.key in (pygame.K_UP, pygame.K_DOWN):
            popup.move(-1 if ev.key == pygame.K_UP else 1, self.popup_items())
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT) and popup.source >= 0:
            self.next_bar_popup(-1 if ev.key == pygame.K_LEFT else 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and popup.sel >= 0:
            self.popup_run(popup.sel)

    # ---- マウス ----
    def mouse_down(self, win) -> None:
        """クリック(winは窓の中の位置)。窓全体に描く一覧とメニューは窓の位置で、本体・紙・
        割り当ての欄・操作欄・作業欄は中身の中の位置で当たりを見る"""
        pos = self._in_content(win)
        if self.menu is not None:
            self.menu_click(win)
            return
        if self.pad_panel is not None and self.popup is None and self.pad_click(pos):
            return
        if self.pane_open and self.popup is None and pos[0] >= self.body_size[0]:
            self.bench_view.focus = True  # ROMのある本体では、キーを作業欄で受ける
            self.bench_click(pos)
            return
        self.bench_view.focus = False
        self.bench.start_buf = self.bench.span_buf = None
        if self.popup is not None:
            popup = self.popup
            i = popup.hit(win)
            if i >= 0:
                self.popup_run(i)
                return
            self.popup = None
            # 操作欄のほかのボタンなら、閉じたうえでそのボタンの操作をする(同じボタンなら
            # 閉じるだけ)
            b = self.bar.hit(pos) if pos[1] >= self.body_size[1] else -1
            if b < 0 or b == popup.source:
                return
        if pos[1] >= self.body_size[1]:  # 本体の下の紙と操作欄
            i = self.bar.hit(pos)
            if i >= 0:
                self.bar.buttons[i].action()
            elif self.paper_open and self.paper.close_rect.collidepoint(pos):
                self.close_paper()
            elif self.paper_open and self.paper.where_rect.collidepoint(pos):
                self.reveal_printout()
            return
        if self.lcd_only:  # 液晶だけなので、押せるキーもスイッチもない
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
            self.press_brk("mouse")
        else:
            self.typer.press_mouse(name)

    def press_brk(self, source: str) -> None:
        """BRKキーを押す。sourceはEscキー("key")か、本体の絵のBRKをマウスで("mouse")"""
        self.brk_by.add(source)
        self.m.brk = True

    def release_brk(self, source: str) -> None:
        """BRKキーを離す。もう一方の入力元でまだ押していれば、押したままにする"""
        self.brk_by.discard(source)
        self.m.brk = bool(self.brk_by)

    def mouse_up(self) -> None:
        self.dragging_switch = False
        name, self.mouse_key = self.mouse_key, None
        if name == "BRK":
            self.release_brk("mouse")
        elif name:
            self.typer.release_mouse(name)

    def set_switch_from(self, y: float) -> None:
        mode = min(self.sw_stops, key=lambda s: abs(s[1] - y))[0]
        self.set_mode(mode)

    def set_mode(self, new: str) -> None:
        """スイッチを動かす。PC-1350のスイッチは電源だけで、RUNとPROはMODEキーで切り替える"""
        m = self.m
        if self.is1350:
            if new == "OFF":
                m.power_off()
            elif new == "ON":
                m.power_on()
            elif new in ("RUN", "PRO"):
                if not m.power:
                    m.power_on()
                self.typer.add_mode(new)
            return
        # OFFにしたときはROMが自分で電源を切るので、ここでは切らない
        if new != "OFF" and (m.mode == "OFF" or not m.power):
            m.wake()
        m.mode = new

    # ---- プログラムの読み込み ----
    def _ram_fits(self, prog: programs.Program) -> bool:
        """プログラムの# ram: の範囲にRAMを広げられるか。広げられなければ知らせる"""
        if prog.ram is None or self.m.ram_top_ok(prog.ram_top):
            return True
        lo, hi = prog.ram
        self.say(
            tr("{name}を読み込みません。# ram: の{lo:04X}-{hi:04X}はROMか液晶RAMにかかります",
               name=prog.title or prog.name, lo=lo, hi=hi - 1), 8
        )  # fmt: skip
        return False

    def _ram_line(self) -> str:
        """いまRAMを広げていれば、その範囲の# ram: の行(なければ空)"""
        base, top = self.m.ram_top(None), self.m.model.ram[1]
        return f"# ram: {base:04X}-{top - 1:04X}\n" if top > base else ""

    def _outside(self, blocks: list[tuple[int, bytes]], top: int | None) -> list[int]:
        """RAMの終わりをtopに動かしたときに、blocksのうちRAMの外になる番地(いま広げている
        所を狭めるときは、そこも外になる)"""
        m, now = self.m, self.m.model.ram[1]
        new = m.ram_top(top)

        def ok(a: int) -> bool:
            if now <= a < new:  # 広げる所
                return True
            if new <= a < now:  # 狭めて外す所
                return False
            return m.writable(a)

        return [a for at, data in blocks for a in range(at, at + len(data)) if not ok(a)]

    def open_program(self, prog: programs.Program, run: bool = False) -> None:
        """ダンプをRAMに書き、BASICはPROモードでNEWしてから入れる。runなら実行の命令も打つ。
        読めない行があるときや、RAMの外に書くダンプがあるときは、何もせずに知らせる"""
        if self.norom:
            self.bench_open(prog, run)
            return
        m = self.m
        name = prog.title or prog.name
        if not prog.runs_on(m.model.name) and not prog.fits(m.writable):
            self.say(
                tr("{program}なので、{model}では読み込みません",
                   program=prog.label(m.model.name), model=m.model.title), 5
            )  # fmt: skip
            return
        if prog.errors:
            self.say(tr("{name}を読み込みません。{why}", name=name, why=prog.errors[0]), 8)
            return
        if not self._ram_fits(prog):
            return
        outside = self._outside(prog.blocks + prog.after, prog.ram_top)
        if outside:
            self.say(outside_message(name, outside[0]), 8)
            return
        long = keytype.too_long(prog.basic, m.model.name) if prog.basic else None
        if long is not None:
            hit = re.match(r"\s*(\d+)", long)
            if hit:
                msg = tr(
                    "{name}を読み込みません。{line}行が長すぎて、打ち込むと欠けます"
                    "(行番号と中身で79字まで)",
                    name=name,
                    line=hit[1],
                )
            else:
                msg = tr(
                    "{name}を読み込みません。「{text}」の行が長すぎて、打ち込むと欠けます"
                    "(行番号と中身で79字まで)",
                    name=name,
                    text=long.strip()[:16],
                )
            self.say(msg, 8)
            return
        data = self._encoded(prog.basic) if prog.basic and not prog.setup else None
        if data is not None and len(data) > m.program_room():
            self.say(
                tr("{name}を読み込みません。BASICが{size}バイトで、RAMに入りません"
                   "(使えるのは{room}バイト)", name=name, size=len(data), room=m.program_room()),
                8,
            )  # fmt: skip
            return
        if not prog.blocks and not prog.basic and not prog.after:
            self.say(tr("{name}: 中身がありません", name=prog.name), 4)
            return
        self.undo_state, self.undo_title = m.snapshot(), prog.title or prog.name
        self.undo_prog = self._prog_undo()
        self.undo_bench = self.bench.save()
        m.set_ram_top(prog.ram_top)
        # 読み込みを始めたら、前の書き込みは取り消せなくする(読み込みは「読み込む前に戻す」で)。
        # 前のプログラムのために決めた書き出す範囲も消す
        self.bench.forget_edits()
        self.bench.span = None
        # 開始番地は、呼び出し用のBASICの最後のCALLの番地。書いた範囲はwrite_dumpで覚える
        _pokes, call = workbench.basic_hints(f"{prog.basic}\n{prog.run}")
        self.bench.use_data(prog.data)
        self.bench.set_start(prog.blocks + prog.after, call)
        self.bench.calls = workbench.basic_calls(f"{prog.basic}\n{prog.run}")
        self.pad_prog, self.pad_note = prog, ""
        self.set_pad_map(self.pad_map_for(prog))
        if self.is1350 and not m.power:
            self.set_mode("ON")
        elif not m.power:
            self.set_mode(m.mode if m.mode != "OFF" else "RUN")
        if not prog.setup:
            self.write_dump(prog.blocks)
        back = m.mode if m.mode in ("RUN", "PRO") else "RUN"
        if self.is1350:
            back = "PRO" if "PRO" in m.symbols() else "RUN"
        if prog.basic or prog.setup:
            self.typer.add_mode("PRO")
            self.typer.add_text("NEW\n")
        if prog.setup:
            # BASICの置き場所を動かす命令などを打ってから、空いたところにダンプを書く
            self.typer.add_text(prog.setup + "\n")
            self.typer.add_write(prog.blocks)
        if prog.basic:
            # 打ち込むかわりに、ROMが作るのと同じ中間コードをRAMに置く
            text, title = prog.basic, prog.title or prog.name
            self.typer.add_call(lambda: self.store_basic(text, title))
        if run and prog.run_command:
            self.typer.add_mode(prog.mode.upper() or "RUN")
            for i, line in enumerate(prog.run_command.split("\n")):
                if i:
                    self.typer.add_idle()  # 前の命令が終わって入力待ちに戻るのを待つ
                self.typer.add_text(line + "\n")
        elif prog.basic and not prog.after:
            self.typer.add_mode(back)
        if prog.after:
            self.typer.add_write(prog.after)
        if prog.basic:
            self.last_prog = prog
        self.fast = self.typer.busy
        self.loading = prog.title
        self.load_help = prog.help
        self.load_total = max(1, len(self.typer.queue))
        self.load_typing = False
        if not self.fast:
            if prog.help:
                self.say_loaded(prog.help, 20)
            else:
                self.say_loaded(
                    tr("{name}を読み込みました({n}バイト)", name=prog.title, n=prog.size)
                )

    def write_dump(self, blocks: list[tuple[int, bytes]]) -> None:
        """ダンプをRAMに書き、作業欄の書いた範囲(書き出しに使う)にも0のバイトを含めて入れる。
        ダンプを書くところ(すぐ書く、# setup:のあと、# after:、--load)は、すべてここを通す"""
        for addr, data in blocks:
            for i, b in enumerate(data):
                self.m.write(addr + i, b)
        self.bench.note_written(blocks)

    def _encoded(self, text: str) -> bytes | None:
        """BASICを中間コードの行の並びにする。打ち込みで欠ける行があるなどで置けなければNone"""
        model = self.m.model.name
        if not keytype.typeable(text, model):
            return None
        return basictext.encode_program(keytype.typed_text(text, model), self.m.mem)

    def store_basic(self, text: str, title: str = "") -> None:
        """BASICのプログラムを、打ち込んだときにROMが作るのと同じ中間コードでRAMに置く。
        入りきらないときや、打ち込みでも欠ける長い行があるときは打ち込み、結果をROMに任せる。
        どちらでも、入れたあとですべての行が入ったかを確かめる(check_basic)"""
        m = self.m
        data = self._encoded(text)
        check = self.typer.call(lambda: self.check_basic(text, title))
        if data is not None and m.store_program(data):
            self.typer.queue[0:0] = [check]
        else:
            keys = keys_for_program(text, m.model.name)
            self.typer.queue[0:0] = [*keys, ["@IDLE"], check]
            self.load_total = len(self.typer.queue)  # ここからは打ち込みの進み具合を出す
            self.load_typing = True

    def check_basic(self, text: str, title: str) -> None:
        """textの行がすべて、欠けずにRAMに入ったかを確かめる。入っていない行や中身が違う行が
        あれば(RAMが足りないなど)、そのあとの実行やダンプの書き込みをやめて知らせる"""
        m = self.m
        want: set[int] = set()
        for line in keytype.typed_text(text, m.model.name).split("\n"):
            hit = re.match(r"\s*(\d+)(.*)", line)
            if hit and hit[2].strip():
                want.add(int(hit[1]))
            elif hit:  # 行番号だけの行は、その行を消す
                want.discard(int(hit[1]))
        have = {n for n, _ in basictext.program_lines(m.mem, m.program_start())}
        missing = sorted(want - have)
        if missing:
            why = tr("{name}はRAMに入りきりませんでした({line}行から{n}行が入っていません)。"
                     "実行と、そのあとの書き込みはやめました。{hint}",
                     name=title, line=missing[0], n=len(missing), hint=undo_hint())  # fmt: skip
        else:
            bad = self._differs(text)
            if bad is None:
                return
            why = tr("{name}の{line}行が、思ったとおりに入りませんでした。実行と、そのあとの"
                     "書き込みはやめました。{hint}",
                     name=title, line=bad, hint=undo_hint())  # fmt: skip
        self.typer.clear()
        self.fast = False
        self.say(why, 10)

    def _differs(self, text: str) -> int | None:
        """RAMのプログラムが、textを中間コードにしたものと違えば、最初に違う行の番号。
        中間コードにできないとき(行番号がおかしいなど)は比べずにNone"""
        m = self.m
        data = basictext.encode_program(keytype.typed_text(text, m.model.name), m.mem)
        if data is None:
            return None
        start = m.program_start()
        if start + 1 + len(data) >= len(m.mem):
            return None
        want = bytearray(m.mem)
        want[start + 1 : start + 1 + len(data)] = data
        want[start + 1 + len(data)] = 0xFF
        got = basictext.program_lines(m.mem, start)
        exp = basictext.program_lines(want, start)
        for (n, body), (en, ebody) in zip(got, exp, strict=False):
            if (n, body) != (en, ebody):
                return min(n, en)
        if len(got) != len(exp):
            return (got if len(got) > len(exp) else exp)[min(len(got), len(exp))][0]
        return None

    def insert_tape(self, path: str) -> None:
        """wavのテープをセットする。ROMがカセットの入力を読み始めたときに再生が始まる"""
        try:
            self.m.tape = tape.TapeIn(path)
        except (OSError, EOFError, wave.Error) as e:
            self.say(tr("{name}を読めません({error})", name=os.path.basename(path), error=e), 5)
            return
        self.say(
            tr("テープ {name} をセットしました。CLOADかCLOAD Mで読み込みます",
               name=os.path.basename(path)), 6
        )  # fmt: skip

    def open_file(self, path: str) -> None:
        if path.lower().endswith(".wav"):
            self.insert_tape(path)
            return
        if os.path.splitext(path)[1].lower() in programs.EXTS:
            self.open_program(programs.load_program(path))
            return
        name = os.path.basename(path)
        if path.lower().endswith(".bin"):  # 置く番地がわからない
            self.say(
                tr("{name}は、.basに「# bin: 名前.bin &C300」と書いて読み込みます", name=name), 6
            )
            return
        try:
            self.typer.add_text(open(path, encoding="utf-8").read())
        except (OSError, UnicodeDecodeError):
            self.say(tr("{name}を読めません", name=name), 4)

    def say(self, text: str, seconds: float = 3.0) -> None:
        self.status = text
        self.status_until = time.monotonic() + seconds

    def say_loaded(self, text: str, seconds: float = 3.0) -> None:
        """読み込み終わりの知らせ。# pad: に読めない語があれば、その知らせも続けて出す"""
        if self.pad_note:
            text, seconds = f"{text}\n{self.pad_note}", max(seconds, 8)
            self.pad_note = ""
        self.say(text, seconds)

    def open_menu(self) -> None:
        """プログラムの一覧を開く"""
        items = programs.scan()
        if self.norom:  # ROMなしでは、ROMなしで使えるものだけ
            items = [p for p in items if p.norom_ok]
        self.menu = ProgramMenu(programs.for_model(items, self.m.model.name, self.m.writable))
        self._make_room()

    def menu_key(self, ev) -> None:
        menu = self.menu
        assert menu is not None
        if menu.query is not None and ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            # 探しているあいだ: Escで探すのをやめ、Backspaceで1字消す
            menu.search(None if ev.key == pygame.K_ESCAPE else menu.query[:-1])
        elif ev.key in (pygame.K_ESCAPE, pygame.K_F6):
            self.menu = None
        elif ev.key in (pygame.K_UP, pygame.K_DOWN):
            menu.move(-1 if ev.key == pygame.K_UP else 1)
        elif ev.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            menu.page(-1 if ev.key == pygame.K_PAGEUP else 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and menu.items:
            self.menu = None
            self.open_program(menu.items[menu.sel], run=not ev.mod & pygame.KMOD_SHIFT)
        elif menu.query is not None:  # 探す字はtext_inputで受ける
            return
        elif ev.key == pygame.K_o:
            self.reveal(programs.user_dir())
        elif ev.key == pygame.K_r:
            self.open_menu()

    def menu_click(self, pos) -> None:
        """行を押すと選ぶだけ(選んである行でも読み込まない)。読み込むのは下のボタンかEnter。
        一覧の外を押すと閉じる"""
        menu = self.menu
        assert menu is not None
        act = menu.button_at(pos)
        if act:
            self.menu_action(act)
            return
        i = menu.hit(pos)
        if i >= 0:
            menu.sel = i
        elif not menu.box.collidepoint(pos):
            self.menu = None

    def menu_action(self, act: str) -> None:
        """一覧の下のボタンと、上の探す欄"""
        menu = self.menu
        assert menu is not None
        if act == "search":
            if menu.query is None:
                menu.search("")
        elif act in ("run", "load") and menu.items:
            self.menu = None
            self.open_program(menu.items[menu.sel], run=act == "run")
        elif act == "folder":
            self.reveal(programs.user_dir())
        elif act == "reload":
            self.open_menu()
        elif act == "close":
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
        self.typer.add_text(self.clipboard())

    def export_program(self) -> None:
        """RAMにあるBASICのプログラムを、置き場所に.basのファイルとして書き出す"""
        if self.typer.scripted:
            self.say(tr("打ち込みが終わってから書き出してください"))
            return
        prog = self.last_prog
        try:
            path = export_program(self.m, programs.user_dir(), prog)
        except OSError as e:
            self.say(tr("書き出せません: {error}", error=e), 5)
            return
        if path is None:
            self.say(tr("書き出すプログラムがありません"))
        else:
            self.say(tr("{path}に書き出しました", path=_short(path)), 5)

    def save_tape(self, samples) -> None:
        """CSAVEの音を、置き場所に「tape-日時.wav」として書き出す"""
        try:
            path = os.path.join(programs.user_dir(), f"tape-{time.strftime('%Y%m%d-%H%M%S')}.wav")
            tape.write_wav(path, samples)
        except OSError as e:
            self.say(tr("テープの音を書き出せません: {error}", error=e), 5)
            return
        self.say(tr("テープの音を{path}に書き出しました", path=_short(path)), 6)

    def save_state(self) -> None:
        """いまの状態(RAM、CPU、ポート、タイマ)を保存する"""
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            self.m.save_state(self.state_file, self._prog_info())
        except OSError as e:
            self.say(tr("状態を保存できません: {error}", error=e), 5)
            return
        self.say(tr("状態を保存しました。{s}{c}Lで戻せます", c=CMD, s=SHIFT))

    def load_state(self, path: str | None = None) -> None:
        """保存した状態に戻す。pathがなければsave_stateの保存先から"""
        try:
            extra = self.m.load_state(path or self.state_file)
        except FileNotFoundError:
            self.say(tr("保存した状態がありません"))
            return
        except (OSError, ValueError) as e:
            self.say(tr("状態を読み込めません: {error}", error=e), 5)
            return
        self._set_prog_info(extra)
        self._restored(tr("保存した状態に戻しました"))

    # 状態のファイルに書く、読み込んだプログラムの情報(書き出しと説明に使う)。元のファイルは
    # 保存したあとで書き換えられるかもしれないので、場所ではなく中身を書いておく
    PROG_TEXT = ("name", "title", "run", "mode", "setup", "help", "model")
    PROG_LISTS = ("paths", "links")

    def _prog_fields(self, prog: programs.Program | None) -> dict | None:
        if prog is None:
            return None
        fields = {k: getattr(prog, k) for k in (*self.PROG_TEXT, *self.PROG_LISTS, "pad")}
        fields["ram"] = list(prog.ram) if prog.ram else None
        return fields

    def _prog_info(self) -> dict:
        info = {
            "program": self._prog_fields(self.last_prog),
            "loading": self.loading,
            "help": self.load_help,
        }
        info["bench"] = self.bench.save()
        # 使っている割り当て(保存していない変更も)と、その対象のプログラム
        info["pad"] = {
            "keys": self.pad_map.keys, "source": self.pad_map.source, "dirty": self.pad_dirty,
            "program": self._prog_fields(self.pad_prog),
        }  # fmt: skip
        return info

    def _saved_prog(self, saved) -> programs.Program | None:
        """_prog_fieldsで書いたプログラムの情報を読む。おかしければNone"""
        if not isinstance(saved, dict):
            return None
        text = {k: saved.get(k, "") for k in self.PROG_TEXT}
        pad = saved.get("pad")  # 前の版の状態にはない
        ram = saved.get("ram")  # 同じく
        lists = {k: saved.get(k) for k in self.PROG_LISTS}
        ram_ok = ram is None or (
            isinstance(ram, list) and len(ram) == 2 and all(type(x) is int for x in ram)
        )
        if (
            all(isinstance(v, str) for v in text.values())
            and all(
                isinstance(v, list) and all(isinstance(x, str) for x in v) for v in lists.values()
            )
            and (pad is None or isinstance(pad, str))
            and ram_ok
        ):
            fields: dict[str, Any] = {**text, **lists, "pad": pad}
            if ram is not None:
                fields["ram"] = (ram[0], ram[1])
            return programs.Program(**fields)
        return None

    def _set_prog_info(self, info: dict | None) -> None:
        """_prog_infoで書いた情報に戻す。なければ、おかしければ、前に読み込んだプログラムの
        情報は使わずに消す(書き出すファイルに、RAMと関係のない名前や# hex:が付かないように)"""
        info = info if isinstance(info, dict) else {}
        prog = self._saved_prog(info.get("program"))
        loading, load_help = info.get("loading"), info.get("help")
        self.last_prog = prog
        self.loading = loading if isinstance(loading, str) else ""
        self.load_help = load_help if isinstance(load_help, str) else ""
        self.bench.restore(info.get("bench"))
        pad = info.get("pad")
        # 前の版の状態には割り当ての対象がないので、last_progを対象にする
        if isinstance(pad, dict) and "program" in pad:
            self.pad_prog = self._saved_prog(pad["program"])
        else:
            self.pad_prog = prog
        pad_map, dirty = self._saved_pad_map(pad, self.pad_prog)
        self.set_pad_map(pad_map)
        self.pad_dirty = dirty

    def _saved_pad_map(self, saved, prog: programs.Program | None) -> tuple[gamepad.PadMap, bool]:
        """状態に書いた割り当てと、保存していない変更があったか。なければ(前の版の状態)、
        おかしければ、読み込んだときのもの"""
        if isinstance(saved, dict) and isinstance(saved.get("keys"), dict):
            keys = {
                n: k for n, k in saved["keys"].items()
                if n in gamepad.ORDER and isinstance(k, str) and k in gamepad.KEY_NAMES
            }  # fmt: skip
            source = saved.get("source")
            pad_map = gamepad.PadMap(keys, source if isinstance(source, str) else "")
            return pad_map, saved.get("dirty") is True
        return self.pad_map_for(prog), False

    def _restored(self, message: str) -> None:
        """状態を戻したあと、打ち込みの残りや音を捨てる"""
        self.typer.restored()
        self.fast = False
        self.overshoot = 0
        self.buzzer.hold(self.m.pc_out >> 4)
        if self.speaker is not None:
            self.speaker.clear()
        self.say(message)

    def screenshot(self) -> None:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            n = 1
            while os.path.exists(os.path.join(STATE_DIR, f"shot{n:03d}.png")):
                n += 1
            path = os.path.join(STATE_DIR, f"shot{n:03d}.png")
            shot = self.panel.out
            if self.lcd_only:
                shot = shot.subsurface(self.view_box())
            pygame.image.save(opaque(shot), path)
        except (OSError, pygame.error) as e:
            self.say(tr("画面の画像を保存できません: {error}", error=e), 5)
            return
        self.say(tr("{path}に保存しました", path=_short(path)))

    # ---- 録画 ----
    def toggle_recording(self) -> None:
        """録画を始める。録画中なら止めて、置き場所に「rec-日時.mp4」として保存する"""
        if self.recorder is None:
            prog = self.last_prog
            title = prog.title if prog else f"SHARP {self.m.model.title}"
            sub = f"SHARP {self.m.model.title} / sc61box {_version()}"
            path = os.path.join(programs.user_dir(), f"rec-{time.strftime('%Y%m%d-%H%M%S')}.mp4")
            try:
                size = (self.panel.out_w, self.panel.out_h)
                self.recorder = recorder.Recorder(path, title, sub, size, self.panel.lcd_box())
            except (OSError, ImportError) as e:
                self.say(tr("録画を始められません: {error}", error=e), 6)
                return
            self.rec_buzzer = Buzzer()
            self.rec_print_sound = PrinterSound()
            self.say(
                tr("録画を始めました。止めて保存するときは、もう一度{s}{c}Rを押します",
                   c=CMD, s=SHIFT), 4
            )  # fmt: skip
            return
        rec, self.recorder = self.recorder, None
        self.rec_paused = False
        self.say(tr("録画を保存しています…"), 2)
        try:
            path = rec.close()
        except OSError as e:
            self.say(tr("録画を保存できません: {error}", error=e), 6)
            return
        secs = round(rec.seconds)
        self.say(tr("録画を{path}に保存しました({n}秒)", path=_short(path), n=secs), 6)

    def toggle_pause(self) -> None:
        """録画を一時停止する。一時停止中なら続きを録る(止めているあいだは動画に入らない)"""
        if self.recorder is None:
            return
        self.rec_paused = not self.rec_paused
        if not self.rec_paused:
            self.rec_buzzer.hold(self.m.pc_out >> 4)
        self.say(tr("録画を一時停止しました") if self.rec_paused else tr("録画を続けます"), 2)

    def record_frame(self, surf, c0: int, live: bool) -> None:
        """1フレームぶんの絵と音を録画に足す。liveでないとき(読み込み中、電源が切れている
        とき)は無音にする"""
        rec = self.recorder
        assert rec is not None
        m = self.m
        if live and m.cpu.cycles != c0:
            pcm = self._render(self.rec_buzzer, c0, keep_silent=True)
            pcm = self.rec_print_sound.mix(pcm, self.paper.moved, self.print_rate)
        else:
            self.rec_buzzer.hold(m.pc_out >> 4)
            pcm = bytes(2 * recorder.SPF)
        rec.add(pygame.image.tobytes(surf, "RGB"), pcm)
        if rec.error:
            self.recorder = None
            rec.abort()
            self.say(tr("録画を止めました: {error}", error=rec.error), 6)

    def _font(self) -> pygame.font.Font:
        if self.font is None:
            self.font = load_help_font(17)
        return self.font

    def _small_font(self) -> pygame.font.Font:
        if self.small_font is None:
            self.small_font = load_help_font(13)
        return self.small_font

    # ---- 本体 ----
    def handle(self, ev) -> bool:
        if ev.type == pygame.QUIT:
            return False
        if self.help and ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            # キーの説明は、何か押すかクリックしたら消す(その操作もそのまま効く)
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
        elif ev.type in PAD_EVENTS:
            self.pad_event(ev)
        elif ev.type == pygame.MOUSEWHEEL and self.menu is not None:
            self.menu.scroll(-ev.y)
        elif (
            ev.type == pygame.MOUSEWHEEL
            and self.pane_open
            and self.pane_keys()
            and pygame.mouse.get_pos()[0] - self.origin[0] >= self.body_size[0]
        ):
            self.bench.page(-ev.y, 1)  # 作業欄の上のホイールで、ダンプを1行ずつ動かす
        elif ev.type == pygame.MOUSEWHEEL and self.paper_open:
            self.scroll_paper(ev.y)
        elif ev.type == pygame.MOUSEMOTION and self.popup is not None:
            self.popup.sel = self.popup.hit(ev.pos)
        elif ev.type == pygame.MOUSEMOTION and not self.dragging_switch:
            pos = self._in_content(ev.pos)
            self.bar.hover = self.bar.hit(pos)
            if self.pane_open:
                hit = self.bench_view.hit(pos)
                self.bench_view.hover = hit[1] if hit and hit[0] == "button" else -1
                self.bench_view.why_at = hit[1] if hit and hit[0] == "why" else -1
                self.bench_view.span_hover = bool(hit and hit[0] == "span")
        elif ev.type == pygame.MOUSEMOTION and self.dragging_switch:
            self.set_switch_from(self._in_content(ev.pos)[1] / self.scale - display.MARGIN)
        elif ev.type == pygame.VIDEORESIZE:
            self.resized(ev.w, ev.h)
        elif ev.type == pygame.WINDOWSIZECHANGED:
            self.resized(ev.x, ev.y)
        elif ev.type in (pygame.WINDOWRESTORED, pygame.WINDOWMAXIMIZED):
            self.resized(*self.window.get_size())
        elif ev.type == pygame.DROPFILE:
            self.open_file(ev.file)
        elif ev.type == pygame.WINDOWLEAVE:
            self.bar.hover = -1
        elif ev.type == pygame.WINDOWFOCUSLOST:
            self.release_all()
        return True

    def release_all(self) -> None:
        """パソコンのキーとマウスで押しているものを、すべて離す。ほかのウィンドウに移ると
        キーを離したことが届かないので、押したままにならないようにする"""
        self.typer.release_physical()
        self.held_key = None
        self.mouse_up()
        self.pad_release_all()
        self.brk_by.clear()
        self.m.brk = self.m.reset_key = False

    def frame(self, poll: Callable[[], None] | None = None) -> None:
        """1フレームぶん(1/FPS秒)動かして描く。pollがあれば、本体の実行をSUBSTEPSに分けた
        合間に呼ぶ(runがキーのイベントを受け取り、時間を合わせる)"""
        m = self.m
        self._key_repeat()
        if not self.halted:
            self._count_down()
        typing = self.typer.scripted and not self.boot_frames
        speed = self.turbo * (8 if typing else 1)
        c0 = m.cpu.cycles
        m.sound_events.clear()
        if self.halted or (self.norom and self.bench.state != "run"):
            speed = 0
        elif self.fast and self.typer.busy and not self.boot_frames:
            # 読み込み中は時計に合わせず、1フレームの時間いっぱいまで回す
            speed = 0
            end = time.perf_counter() + 0.8 / FPS
            while time.perf_counter() < end and self.typer.busy:
                self.typer.step()
                # 打ったCALLでマシン語が動き出せば、止める所で止まる(読み込みの途中でも)
                if self._run_cpu(CLOCK // 200):
                    break
        elif self.fast:
            self.fast = False
            if self.load_help:
                self.say_loaded(self.load_help, 20)
            else:
                self.say_loaded(tr("{name}を読み込みました", name=self.loading))
        speaker = self.speaker if bool(speed) and not typing else None  # 鳴らすときだけ
        adjust = speed_adjust(speaker.level()) if speaker is not None else 1
        self.paper.tick()
        if self._advance(int(speed * (CLOCK // FPS) * adjust), poll):
            # 合間に状態を復元した。音と録画は復元した所から先だけにする(復元前の時刻からの
            # 差で、何秒ぶんもの音を作らないように)
            c0 = m.cpu.cycles
            self.rush_spans = []  # 復元前のサイクルで記録した、速く回した区間も使わない
            self.buzzer.hold(m.pc_out >> 4)
            self.rec_buzzer.hold(m.pc_out >> 4)
        wav = self.tape_out.feed(m.sound_events, m.cpu.cycles, m.pc_out >> 4)
        if wav is not None:
            self.save_tape(wav)
        if speaker is not None:
            printing = self.paper.moved
            keep = speaker.keep_silent or printing or self.print_sound.active
            pcm = self._render(self.buzzer, c0, keep_silent=keep)
            speaker.push(self.print_sound.mix(pcm, printing, self.print_rate))
        elif self.speaker is not None:
            self.buzzer.hold(m.pc_out >> 4)
            self.speaker.clear()
        if m.tape is not None and m.tape.done(m.cpu.cycles):
            m.tape = None
            self.say(tr("テープが終わりました"))
        pressed = set(m.held) | ({"BRK"} if m.brk else set())
        surf = self.panel.draw(
            m.columns(), m.symbols(), m.display_on(), m.mode, pressed, powered=m.power,
            duty=self.lcd_duty,
        )  # fmt: skip
        if self.recorder is not None and not self.rec_paused:
            self.record_frame(surf, c0, bool(speed) and not typing)
        self._show(surf)

    def _count_down(self) -> None:
        """起動のあとの待ちと、RESETボタンを押している時間を数える"""
        m = self.m
        if self.boot_frames:
            self.boot_frames -= 1
            if self.boot_frames == 0 and self.load:
                blocks = parse_hexdump(self.load)
                self.write_dump(blocks)
                self.bench.set_start(blocks)
            if self.boot_frames == 0 and self.pending:
                prog, run = self.pending
                self.open_program(prog, run)
                self.pending = None
        if self.reset_frames:
            self.reset_frames -= 1
            if self.reset_frames == 0:
                m.reset_key = False

    def _render(self, buzzer: Buzzer, c0: int, keep_silent: bool) -> bytes:
        """このフレーム(サイクルc0〜いま)の音。パソコンのキーを速く届けたあいだ(rush_spans)は
        RUSH倍に縮めて、実際にたった時間の長さの音にする(録画やスピーカーの音が、速く
        回したぶん長く引き延ばされないように。ほかのところの音の高さと長さは変えない)"""
        m = self.m
        out, at = [], c0
        for a, b in [*self.rush_spans, (m.cpu.cycles, m.cpu.cycles)]:
            if a > at:
                out.append(buzzer.render(m.sound_events, at, a, self.turbo, keep_silent))
            if b > a:
                out.append(buzzer.render(m.sound_events, a, b, self.turbo * RUSH, keep_silent))
            at = max(at, b)
        return b"".join(out)

    def _advance(self, cycles: int, poll: Callable[[], None] | None = None) -> bool:
        """cyclesだけ動かす。前のフレームで命令の途中まではみ出した分は差し引く
        (音のサンプルの数が再生の速さとそろうように)。pollがあればSUBSTEPSに分けて、
        合間に呼ぶ。合間に状態を復元した(サイクルが変わった)ときはTrue"""
        m = self.m
        target = m.cpu.cycles + cycles - self.overshoot
        self.overshoot = 0
        self.rush_spans = []
        # このフレームのあいだに液晶RAMに書いたものを記録する(_lcd_duty)
        start = m.cpu.cycles
        m.lcd_trace = []
        parts = SUBSTEPS if poll is not None else 1
        done, restored = True, False
        for k in range(parts):
            end = m.cpu.cycles + max(0, target - m.cpu.cycles) // (parts - k)
            while (left := target - m.cpu.cycles) > 0 and m.cpu.cycles < end:
                rush = False
                if not self.boot_frames:
                    self.typer.step()
                    rush = self.typer.rushing and bool(cycles)
                before = m.cpu.cycles
                if self._run_cpu(min(left, CLOCK // (1000 if rush else 200))):
                    done = False
                    break
                if rush:
                    # パソコンのキーをROMの入力待ちに届けているあいだは、RUSH倍の速さで回す
                    # (1打鍵ごとのROMの読み取りの待ちを縮めて、打ち込みのもたつきをなくす)
                    grown = (m.cpu.cycles - before) * (RUSH - 1) // RUSH
                    target += grown
                    end += grown
                    spans = self.rush_spans
                    if spans and spans[-1][1] == before:
                        spans[-1] = (spans[-1][0], m.cpu.cycles)
                    else:
                        spans.append((before, m.cpu.cycles))
                if m.cpu.cycles == before:  # 電源が切れていて時間が進まない
                    done = False
                    break
            if not done:
                break
            if poll is not None and k < parts - 1:
                mark = m.cpu.cycles
                poll()
                # 合間の操作で、一時停止、状態の復元(サイクルが変わる)、作業欄の実行の中止、
                # 窓を閉じる操作があれば、復元前の目標では動かさない
                stopped = self.norom and self.bench.state != "run"
                restored = m.cpu.cycles != mark
                if self.closing or self.halted or stopped or restored:
                    done = False
                    break
        if done:
            self.overshoot = m.cpu.cycles - target
        self.lcd_duty = self._lcd_duty(start, m.lcd_trace or [])
        m.lcd_trace = None
        return restored

    def _lcd_duty(
        self, start: int, trace: list[tuple[int, int, int, int]]
    ) -> dict[int, list[float]]:
        """液晶RAMに書いた記録から、このフレーム(サイクルstart〜いま)のあいだに中身が
        変わった列の、各ドット(ビット0〜7)が点いていた時間の割合を求める。書き換えの
        途中の短い中身は、その短さの分だけ薄く出る"""
        end = self.m.cpu.cycles
        total = end - start
        if not trace or total <= 0:
            return {}
        cols = self.lcd_cols
        cur: dict[int, tuple[int, int]] = {}  # 番地: (いまの値, その値になったサイクル)
        lit: dict[int, list[int]] = {}

        def add(a: int, v: int, n: int) -> None:
            if v and n > 0:
                acc = lit.setdefault(a, [0] * 8)
                for b in range(8):
                    if v >> b & 1:
                        acc[b] += n

        for c, a, old, new in trace:
            if a not in cols:
                continue
            v, since = cur.get(a, (old, start))
            add(a, v, c - since)
            cur[a] = (new, c)
        duty: dict[int, list[float]] = {}
        for a, (v, since) in cur.items():
            add(a, v, end - since)
            share = [n / total for n in lit.get(a, [0] * 8)]
            for i in cols[a]:
                duty[i] = share
        return duty

    def _run_cpu(self, cycles: int) -> bool:
        """CPUを最大cyclesサイクル動かす。作業欄の止める所、呼び出しの戻り先、ROMなしでは
        RAMの外とROMのルーチンの代わりも、ここで調べる(本体を動かすところは、すべてここを
        通す)。作業欄の実行が止まったらTrue"""
        m, bench = self.m, self.bench
        if bench.state == "run" and bench.pass_pc is not None:
            # 再帰の内側の戻り先を、止めずに1命令だけ進める。終わらないプログラムでも、
            # 1回に1命令ずつなので、フレームのサイクルを使い切れば画面に戻る
            bench.pass_step()
            stopped = bench.state != "run"
        else:
            guard = bench.guard() if bench.state == "run" and bench.needs_guard() else None
            # 作業欄を出しているあいだは、実行した番地を覚える(逆アセンブルの命令の印)。
            # しまっていれば覚えない(ROMのBASICを、印をつけずに速く動かす)
            seen = bench.executed if self.pane_open else None
            # 止まっても、ROMのルーチンの代わりを済ませただけなら(trapped)続ける
            stopped = m.run(cycles, guard, seen) and not bench.trapped()
        if stopped:
            self._bench_stopped()  # 終わったか、止める所かRAMの外で一時停止した
        return stopped

    def _bench_stopped(self) -> None:
        """作業欄の実行が止まった(終わったか、止める所などで一時停止した)。押しているキーを
        離す。ROMのある本体で作業欄をしまっていれば、止まった所を見せるために出す"""
        self.release_all()
        if not self.norom and self.bench.state == "pause":
            self.toggle_pane(True)

    def _show(self, surf: pygame.Surface) -> None:
        """本体の絵を窓に貼り、一覧や知らせを重ねる"""
        self.check_printer()
        self._track_window()
        font = self._font()
        if (
            self.lcd_only
            and self.free_size is not None
            and self.body_size[0] < Bar.min_width(font, self.bar_buttons())
        ):
            # 再開・録画・言語の切り替えなどでボタンが広がったときも、全部入る幅にする。
            self._refit()
        self._open_window()  # 一覧やメニューの開け閉めで、液晶だけの細い窓の高さが変わる
        win = out = self.window
        content = self._window_size()
        copy = False  # 中身を別の面に描いて窓にコピーするか(窓が中身より小さいとき)
        if win.get_size() != content:  # 利用者が変えた窓。中身はまんなかに、まわりは暗く
            win.fill((20, 21, 24))
            ox, oy = self.origin
            copy = content[0] + ox > win.get_width() or content[1] + oy > win.get_height()
            out = pygame.Surface(content) if copy else win.subsurface((ox, oy, *content))
        w, h = self.body_size
        body = out.subsurface((0, 0, w, h))
        if self.lcd_only:
            surf = surf.subsurface(self.view_box())
        if self.scale == 1.0:
            body.blit(surf, (0, 0))
        else:
            # pygame 2.6.1のGENERICの縦拡大は、描画先の行の余白(pitch)を飛ばさない。
            # 窓の一部へ直接書くと絵が斜めに流れるので、独立した面に拡大してから貼る。
            if self.scaled_body is None or self.scaled_body.get_size() != (w, h):
                self.scaled_body = pygame.transform.smoothscale(surf, (w, h))
                # 本体の絵は不透明。Cocoaの未使用alpha=0をsmoothscaleが透明として
                # 引き継ぐことがあるので、貼るときは透明度を使わない。
                self.scaled_body.set_alpha(None)
            else:
                pygame.transform.smoothscale(surf, (w, h), self.scaled_body)
            body.blit(self.scaled_body, (0, 0))
        top = h
        if self.printout is not None:
            rows = self.paper_rows()
            where = []
            if self.printout.file:
                folder, name = os.path.split(_short(self.printout.file))
                where = [tr("保存先(クリックで開く)"), folder + os.sep, name]
            self.paper.draw(out, top, rows[: len(rows) - self.paper_back], where)
            top += self.paper.height
        self.bar.buttons = self.bar_buttons()
        left = out.subsurface((0, 0, w, out.get_height())) if self.pane_open else out
        if self.pad_panel is not None:
            pressed = self.pads.pressed()
            small = self._small_font()
            if not self.lcd_only:
                padmenu.draw_badges(
                    body, small, self.panel.key_rects, self.scale, display.MARGIN, self.pad_map,
                    self.pad_panel.selected, pressed,
                )  # fmt: skip
            self.pad_panel.draw(
                left, top, font, small, self.pads.names(), self.pad_map, pressed,
                *self._pad_target(), self.pad_dirty,
            )  # fmt: skip
            top += self.pad_panel.height
        self.bar.draw(left, font, top, self.bar_info())
        notice = body  # 知らせを出す場所
        if self.pane_open:
            # 作業欄は右に置き、本体と操作欄の下のあいたところに知らせを出す
            below = top + BAR_H
            if below < out.get_height():
                out.fill((20, 21, 24), (0, below, w, out.get_height() - below))
                notice = out.subsurface((0, below, w, out.get_height() - below))
            pane = pygame.Rect(w, 0, benchview.PANE_W, out.get_height())
            self.bench_view.draw(out, pane)
        if self.fast:
            done = int(100 * min(1.0, max(0.0, 1 - len(self.typer.queue) / self.load_total)))
            if self.load_typing:
                text = tr("{name}を打ち込み中… {pct}%(Escでやめる)", name=self.loading, pct=done)
            else:
                text = tr("{name}を読み込み中… {pct}%(Escでやめる)", name=self.loading, pct=done)
            draw_status(notice, font, text)
        elif self.status and time.monotonic() < self.status_until:
            draw_status(notice, font, self.status)
        if self.recorder is not None:
            draw_recording(out, font, self.recorder.seconds, self.rec_paused)
        if self.halted and not self.pane_open:  # 作業欄を出していれば、作業欄に出る
            draw_halted(out, font, tr("実行を一時停止中({c}Pで再開)", c=CMD))
        if copy:
            win.blit(out, self.origin)
        # キーの説明、一覧、メニューは窓全体に描く(液晶だけの窓では、中身より広い所を使う)
        if self.help:
            self.help -= 1
            draw_help(win, font, help_lines(self.norom, self.is1350))
        if self.menu is not None:
            self.menu.draw(win, font, self.m.model.name, _short(programs.user_dir()))
        if self.popup is not None:
            self.popup.draw(win, font, self.popup_items(), self.popup_mark())
        pygame.display.flip()

    @staticmethod
    def _view_prefs() -> dict:
        """作業欄の見え方の記録(view_file)。なければ空"""
        try:
            with open(view_file(), encoding="utf-8") as f:
                prefs = json.load(f)
        except (OSError, ValueError):
            return {}
        return prefs if isinstance(prefs, dict) else {}

    def _view_pref(self, key: str) -> object:
        return self._view_prefs().get(key)

    def _iram_shown(self) -> bool:
        """作業欄の内部RAMを開いておくか。前に開いた・閉じたものがあればそれに従う。なければ
        開いておくが、開いた作業欄が画面の高さに入らなければ閉じておく"""
        shown = self._view_pref("show_iram")
        if isinstance(shown, bool):
            return shown
        try:
            _dw, dh = pygame.display.get_desktop_sizes()[0]
        except (pygame.error, IndexError):
            return True
        return self.bench_view.min_height(True) <= dh - 120

    def _save_view(self, lang: str | None = None) -> None:
        """作業欄の内部RAMを開いたか閉じたか、ROMのある本体で作業欄を出したかを覚えておく
        (次に起動したときも同じにする)。langはメニューで選んだ画面の言語"""
        prefs = self._view_prefs()
        prefs["show_iram"] = self.bench_view.show_iram
        if not self.norom:
            # 液晶だけのあいだは作業欄を隠しているだけなので、隠す前のほうを覚える
            prefs["show_pane"] = self.pane_before_lcd if self.lcd_only else self.pane_open
        if lang:
            prefs["lang"] = lang
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(view_file(), "w", encoding="utf-8") as f:
                json.dump(prefs, f)
        except OSError:
            pass

    def pane_keys(self) -> bool:
        """パソコンのキーを、本体ではなく作業欄で受けるか。ROMなしでは実行していないあいだ。
        ROMがあれば、作業欄を出していて、作業欄をクリックしたあとか一時停止しているあいだ"""
        b = self.bench
        if self.lcd_only:
            return False
        if self.norom:
            return b.state != "run"
        return self.pane_open and (self.bench_view.focus or b.state == "pause")

    def toggle_pane(self, on: bool | None = None) -> None:
        """ROMのある本体で、マシン語の作業欄を出すかしまう(窓の幅が変わる)。液晶だけの
        あいだは出せない"""
        if self.norom:
            return
        on = not self.pane_open if on is None else on
        if on == self.pane_open or (on and self.lcd_only):
            return
        self.pane_open = on
        self.bench_view.focus = False
        self.release_all()
        self._save_view()
        self._refit()

    def _load_bench_info(self, info: object) -> None:
        """終了したときに保存した作業欄の情報を戻す。なければ(前の版のRAM)、RAMの0でない
        所を書いた範囲とする"""
        b = self.bench
        if isinstance(info, dict):
            info["state"] = "edit"  # CPUは起動し直しているので、続きからは動かせない
            b.restore(info, "")
        elif self.norom:  # ROMのある本体のRAMにはBASICなども入っているので、推し量らない
            b.mark_nonzero()

    def close(self) -> None:
        self._finish_paper()
        if self.save_ram:
            if self.m.power and not self.norom:
                self.m.power_off()
            # 作業欄の開始番地、止める所、書いた範囲も、RAMと一緒に覚えておく。保存できなくても
            # (置き場所に同じ名前のファイルがあるなど)、録画の保存と後始末は続ける
            try:
                os.makedirs(STATE_DIR, exist_ok=True)
                self.m.save_ram(self.ram_file)
                with open(bench_file(self.ram_file), "w", encoding="utf-8") as f:
                    info = {**self.bench.save(), "state": "edit", "ram_top": self.m.model.ram[1]}
                    json.dump(info, f)
            except OSError as e:
                print(tr("RAMを保存できません: {error}", error=e), file=sys.stderr)
        if self.recorder is not None:
            self.toggle_recording()  # 録画中に閉じたら、そこまでを保存する
        if self.speaker is not None:
            self.speaker.close()
        pygame.quit()

    def run(self) -> None:
        clock = pygame.time.Clock()
        self.closing = False

        def poll() -> None:
            clock.tick(FPS * SUBSTEPS)
            self._pump()

        try:
            while not self.closing:
                self._pump()
                self.frame(poll)
                clock.tick(FPS * SUBSTEPS)
        finally:  # 思わぬ誤りで止まっても、RAMと印字は保存する
            self.close()

    def _pump(self) -> None:
        """たまっているイベントを本体に届ける。閉じる操作があればclosingにする"""
        try:
            events = pygame.event.get()
        except (KeyError, SystemError):  # パッドを外したときのpygameの誤り(Pads.sync)
            events = []
            self.pad_sync()
        for ev in events:
            if not self.handle(ev):
                self.closing = True


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"sc61box {_version()}")
        raise typer.Exit()


def make_cli() -> typer.Typer:
    """コマンドラインの入口。オプションの説明は、作ったときの言語で書く(cliは、--langと
    SC61BOX_LANGなどで言語を決めてから作る)"""
    app = typer.Typer(
        add_completion=False, help=tr("SHARP PC-1251/PC-1245/PC-1261/PC-1350エミュレータ")
    )

    @app.command()
    def main(
        program: str | None = typer.Argument(
            None, help=tr("読み込むプログラム(.bas/.hexのパスか、置き場所にある名前)")
        ),
        run: bool = typer.Option(False, "--run", help=tr("読み込んだあと実行する")),
        scale: float = typer.Option(1.0, help=tr("拡大率")),
        type_: str | None = typer.Option(
            None, "--type", help=tr("起動後にこのファイルの中身をキー入力する")
        ),
        load: str | None = typer.Option(None, help=tr("16進ダンプ(番地 データ)をRAMに書き込む")),
        fresh: bool = typer.Option(False, help=tr("保存したRAMを読まず、終了時にも保存しない")),
        mute: bool = typer.Option(False, help=tr("音を出さない")),
        persist: float = typer.Option(1.0, help=tr("液晶の残像の強さ(0で残像なし)")),
        export: str | None = typer.Option(
            None,
            help=tr("保存したRAMのBASICのプログラムを、このフォルダに.basで書き出して終わる"),
        ),
        model: str = typer.Option(
            "1251",
            help=tr(
                "機種(1250、1251、1255、1245、1260、1261、1262、1350)。ROMはcpu-機種.romと"
                "bas-機種.rom(1250と1255は1251の、1260〜1262はどれも1260のROMを使う)"
            ),
        ),
        card: int = typer.Option(0, help=tr("PC-1350に差すRAMカードの大きさ(KB)。0、8、16")),
        overseas: bool = typer.Option(
            False,
            help=tr("PC-1350を輸出向けの配線で動かす(カナの代わりに英小文字、¥の代わりに\\)"),
        ),
        numpad: bool = typer.Option(
            False, help=tr("矢印キーを数字キーの8・2・4・6として押す(⌘K/Ctrl+Kで切り替え)")
        ),
        lcd: bool = typer.Option(
            False, "--lcd", help=tr("本体の絵を出さず、液晶だけを見せる(窓の大きさを変えられる)")
        ),
        tape_: str | None = typer.Option(
            None, "--tape", help=tr("カセットの音(wav)をセットする。CLOAD・CLOAD Mで読み込める")
        ),
        state: str | None = typer.Option(None, help=tr("保存した状態(⇧⌘Sで書いたもの)から始める")),
        norom: bool = typer.Option(
            False,
            "--norom",
            help=tr("ROMを使わず、マシン語の作業欄で動かす(ROMがなければ自動でこうなる)"),
        ),
        lang: str | None = typer.Option(
            None,
            "--lang",
            help=tr("画面の言語(jaかen)。なければSC61BOX_LANG、メニューで選んだもの、ロケールの順"),
        ),
        version_: bool = typer.Option(
            False, "--version", callback=_show_version, is_eager=True, help=tr("版を出して終わる")
        ),
    ) -> None:
        args = Options(
            model=model,
            card=card,
            overseas=overseas,
            norom=norom,
            scale=scale,
            persist=persist,
            fresh=fresh,
            mute=mute,
            numpad=numpad,
            lcd=lcd,
            lang=lang,
            program=program,
            run=run,
            type=type_,
            load=load,
            tape=tape_,
            state=state,
        )
        start(args, export)

    return app


def start(args: Options, export: str | None = None) -> None:
    """オプションを確かめて起動する。exportがあれば、保存したRAMのBASICを書き出して終わる。
    前の名前のデータのフォルダ(~/.pc1251)があれば、新しい名前(~/.sc61box)に移す"""
    global STATE_DIR
    old = paths.old_data_dir()
    if old is not None and paths.migrate():
        args.moved_data = "~/" + os.path.basename(old)
    STATE_DIR = paths.data_dir()
    if args.lang is not None and args.lang not in i18n.LANGUAGES:
        typer.echo(tr("言語はjaかenです"), err=True)
        raise typer.Exit(2)
    i18n.set_language(i18n.choose(args.lang, App._view_prefs().get("lang")))
    model, card = args.model, args.card
    if model not in MODELS:
        typer.echo(tr("機種は{models}のどれかです", models=tr("、").join(sorted(MODELS))), err=True)
        raise typer.Exit(2)
    if card not in (0, 8, 16):
        typer.echo(tr("RAMカードの大きさは0、8、16のどれかです"), err=True)
        raise typer.Exit(2)
    if MODELS[model].family != "1350":
        args.card = card = 0
    if export is not None:
        try:
            m = new_machine(model, card)
        except RomNotFound as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e
        apply_ram_top(m, saved_info(ram_file(model, card)))
        if not m.load_ram(ram_file(model, card)):
            typer.echo(tr("{path}がありません", path=ram_file(model, card)), err=True)
            raise typer.Exit(1)
        path = export_program(m, export)
        typer.echo(path or tr("書き出すプログラムがありません"))
        return
    try:
        App(args).run()
    except (RomNotFound, FileNotFoundError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


def _asked_language(argv: list[str]) -> str | None:
    """コマンドの引数の--lang(--helpの説明の言語を決めるため、typerが読む前に見る)"""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def cli() -> None:
    asked = _asked_language(sys.argv[1:])
    i18n.set_language(i18n.choose(asked, App._view_prefs().get("lang")))
    make_cli()()


if __name__ == "__main__":
    cli()
