"""マシン語の作業欄を描く(BenchView)。状態と操作はworkbench.Bench

右の作業欄に、ボタン、開始番地、書き出す範囲、ダンプ、逆アセンブル、レジスタと内部RAM、
知らせを上から並べる。クリックの場所(hits)もここで覚える。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import pygame

from . import codemap, disasm
from .i18n import tr
from .overlay import load_help_font, wrap_text
from .workbench import ROW, Bench, checksum, span_text

MONO_FONTS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

PANE_W = 470  # 作業欄の幅(拡大率によらない)
BG = (28, 30, 34)
FG = (226, 228, 222)
DIM = (128, 132, 140)
HEAD = (150, 176, 220)
CURSOR = (88, 120, 190)
CHANGED = (240, 170, 80)  # 実行で変わったバイト
REGCHG = (255, 214, 120)  # 前に止まったときから変わったレジスタ
PCLINE = (52, 70, 52)
INSLINE = (44, 52, 72)  # カーソルのある命令(ダンプのバイトと逆アセンブルの行)
BREAK = (210, 70, 70)
OK = (120, 200, 140)
WARN = (236, 120, 110)
BTN = (58, 61, 68)
BTN_ON = (84, 90, 104)
BG_DIM = (44, 46, 52)  # 押せないボタンの地
TIP_BG = (14, 15, 18)
WHITE = (240, 240, 235)
START = (232, 184, 96)  # 開始番地(欄の値と、ダンプと逆アセンブルの印)
UNSURE = (160, 163, 170)  # 命令かどうかわからない行(どこからもたどれない)
DATA_FG = (134, 172, 160)  # データの行


def why_mark(why: str) -> str:
    """逆アセンブルの行の右に出す、命令かデータかを決めた理由の1字"""
    # 言語によらない記号にする。いちばん多い静的解析の命令は目立たない「.」、実行済みの
    # 命令は確かめたので「✓」、推定は「?」、ユーザ指定は「U」(user)
    marks = {"executed": "✓", "guessed": "?", "flow": ".", "user": "U"}
    return marks.get(why, "")


def why_text(cm: codemap.CodeMap, a: int) -> str:
    """番地aの行を命令かデータに決めた理由(印にマウスを載せたときに出す)"""
    code, data = cm.why[a & 0xFFFF], cm.state(a)[0] == "data"
    if code == codemap.EXEC:
        return tr("実行済みの命令")
    if code == codemap.FLOW:
        return tr("分岐と呼び出しをたどり、命令と判定")
    if code == codemap.TABLE:
        return tr("DTCの表(行の数はPTCから)")
    if code == codemap.GUESS:
        if data:
            return tr("DTCの表(参照されていない)")
        return tr("参照されていないため不明")
    if code == codemap.TEXT:
        return tr("文字列と推定")
    if code == codemap.FILL:
        return tr("00・FFの連続と推定")
    if code == codemap.JUNK:
        return tr("未定義命令などを含むため、データと推定")
    if code == codemap.NOEND:
        return tr("RTNやジャンプで終わらないため、データと推定")
    if code == codemap.USER:
        return tr("ユーザ指定のデータ") if data else tr("ユーザ指定の命令")
    return ""


def load_mono(size: int) -> pygame.font.Font:
    for path in MONO_FONTS:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except (OSError, pygame.error):
                continue
    return pygame.font.SysFont("monospace", size)


@dataclass
class Button:
    label: str
    action: str
    tip: str
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    enabled: bool = True  # 押せないときは暗く出し、押しても何もしない(説明は出す)


class BenchView:
    """作業欄を描き、クリックの場所を調べる"""

    LH = 18  # 行の高さ

    def __init__(self, bench: Bench, jfont: pygame.font.Font, cmd: str, shift: str) -> None:
        self.b = bench
        self.mono = load_mono(14)
        self.jfont = jfont
        self.small = load_help_font(13)
        self.cw = self.mono.size("0")[0]
        self.cmd, self.shift = cmd, shift
        self.buttons: list[Button] = []
        self.hits: list[tuple[pygame.Rect, str, int]] = []  # (場所, 種類, 番地)
        self.rows = 8  # ダンプと逆アセンブルの行の数
        self.hover = -1
        self.flash = ""  # 打てなかったときなどの短い知らせ
        self.flash_ok = False  # 済んだことの知らせなら緑、ほかは赤で出す
        self.flash_until = 0.0
        self.followed = -1  # 一時停止中に、ダンプをPCの行へ動かしたときのPC
        self.show_iram = True  # 内部RAMの16進表記を出すか(見出しのクリックで開く・閉じる)
        # パソコンのキーを作業欄で受けているか(ROMのある本体で、作業欄をクリックしたあと)。
        # ROMなしの本体では、実行していないあいだはいつも作業欄で受ける
        self.focus = False
        # 書き出す範囲と、それを求めた時刻(RAMを調べるので、毎フレームは求めない)
        self._ranges: tuple[list[tuple[int, int]], float] = ([], 0.0)
        self._ranges_span: tuple[int, int] | None = None  # 範囲を求めたときの自分で決めた範囲
        self.span_hover = False  # 書き出す範囲の行にマウスを載せているか
        self.why_at = -1  # マウスを載せている、逆アセンブルの行の理由の印の番地

    def say(self, text: str, seconds: float = 3.0, ok: bool = False) -> None:
        """作業欄の下に短く出す知らせ。okなら済んだことの知らせ(ふつうは打てなかったなど)"""
        self.flash = text
        self.flash_until = time.monotonic() + seconds
        self.flash_ok = ok

    IRAM_ROWS = 6  # 内部RAMの行の数(16バイトずつ)
    STATUS_LINES = 2  # 作業欄のいちばん下の知らせの行の数

    def min_height(self, show_iram: bool | None = None) -> int:
        """作業欄が収まる高さ。内部RAMを閉じていれば、その行の分だけ低い"""
        show = self.show_iram if show_iram is None else show_iram
        return 740 - (0 if show else self.IRAM_ROWS * self.LH)

    def _text(self, dst, x, y, s, color=FG, font=None) -> int:
        f = font or self.mono
        img = f.render(s, True, color)
        dst.blit(img, (x, y))
        return x + img.get_width()

    def button_specs(self) -> list[Button]:
        """いまの状態で押せるボタン。名前は短くし、マウスを載せたときの説明(tip)に、
        いま押すと何が起きるかを具体的に書く(次の命令、呼び先の番地など)"""
        b, c, s = self.b, self.cmd, self.shift
        at = b.ins_at(b.cursor)
        brk = Button(
            tr("● 止める所"), "break",
            tr("カーソルの命令({addr:04X}番地)に止める所を置く。置いてあれば外す({c}B)",
               addr=at, c=c),
        )  # fmt: skip
        back = Button(
            tr("編集へ"), "abandon",
            tr("実行を途中でやめて編集に戻る。書き換わったメモリはそのまま(Esc)"),
        )  # fmt: skip
        if b.state == "run":
            pause = Button(
                tr("■ 一時停止"), "pause", tr("実行を、いまの命令の前で止める({c}.)", c=c)
            )
            return [pause, brk] if b.rom else [pause, brk, back]
        if b.state == "edit":
            return [
                Button(
                    tr("▶ 実行"), "run",
                    tr("開始番地{addr:04X}から実行する。RTNで戻れば終わり({c}G)",
                       addr=b.start, c=c),
                ),
                Button(
                    tr("1命令ずつ"), "step",
                    tr("開始番地{addr:04X}の最初の命令の前で止める。そこから1命令ずつ進める({c}J)",
                       addr=b.start, c=c),
                ),
                brk,
            ]  # fmt: skip
        pc = b.m.cpu.pc
        if b.blocked(pc):
            # ROMなしで使えない番地で止まっている。続けることも1命令進めることもできない
            tip = tr("{addr:04X}番地からは続けられないので、編集に戻る(Esc)", addr=pc)
            return [Button(tr("編集へ"), "abandon", tip)]
        ins = disasm.decode(b.read, pc)
        specs = [
            Button(tr("▶ 続ける"), "resume",
                   tr("{addr:04X}番地から続けて実行する({c}G)", addr=pc, c=c)),
            Button(
                tr("1命令"), "step",
                tr("次の命令「{ins}」({addr:04X}番地)だけを実行して止まる({c}J)",
                   ins=ins.text(), addr=pc, c=c),
            ),
        ]  # fmt: skip
        if disasm.is_call(b.read, pc) and ins.target is not None:
            tip = tr(
                "「{ins}」で{addr:04X}番地を呼び、RTNで戻ってくるまで実行して、次の命令で止まる({s}{c}J)",
                ins=ins.text(), addr=ins.target, s=s, c=c,
            )  # fmt: skip
            specs.append(Button(tr("CALLごと"), "over", tip))
        return specs + [brk] if b.rom else specs + [brk, back]

    def _tip(self, dst: pygame.Surface, rect: pygame.Rect) -> None:
        """マウスを載せたボタンの説明を、ボタンのすぐ下に出す"""
        if not 0 <= self.hover < len(self.buttons):
            return
        btn = self.buttons[self.hover]
        width = min(rect.width - 24, 380) - 16
        body, key = btn.tip, ""
        if body.endswith(")") and "(" in body:  # 末尾のショートカットは途中で折り返さない
            cut = body.rindex("(")
            body, key = body[:cut], body[cut:]
        lines = wrap_text(self.jfont, body, width)
        if key and self.jfont.size(lines[-1] + key)[0] > width:
            lines.append(key)
        else:
            lines[-1] += key
        self._tooltip(dst, rect, lines, (btn.rect.x, btn.rect.bottom + 4))

    def _tooltip(
        self, dst: pygame.Surface, rect: pygame.Rect, lines: list[str], at: tuple[int, int],
        right: bool = False,
    ) -> None:  # fmt: skip
        """説明の箱を、atを左上(rightなら右上)にして出す。作業欄rectからはみ出さないように
        左右をずらす"""
        imgs = [self.jfont.render(t, True, WHITE) for t in lines]
        lh = imgs[0].get_height()
        box = pygame.Rect(0, 0, max(i.get_width() for i in imgs) + 16, lh * len(imgs) + 10)
        if right:
            box.topright = at
        else:
            box.topleft = at
        box.right = min(box.right, rect.right - 6)
        box.x = max(box.x, rect.x + 6)
        pygame.draw.rect(dst, TIP_BG, box, border_radius=5)
        pygame.draw.rect(dst, BTN_ON, box, 1, border_radius=5)
        for k, img in enumerate(imgs):
            dst.blit(img, (box.x + 8, box.y + 5 + lh * k))

    def _button(self, dst: pygame.Surface, btn: Button, index: int, y: int) -> None:
        """ボタンをbtn.rectに描く。マウスを載せていれば明るく、押せなければ暗く"""
        if not btn.enabled:
            color, ink = BG_DIM, DIM
        else:
            color, ink = (BTN_ON if index == self.hover else BTN), FG
        pygame.draw.rect(dst, color, btn.rect, border_radius=5)
        self._text(dst, btn.rect.x + 8, y, btn.label, ink, self.jfont)

    def draw(self, dst: pygame.Surface, rect: pygame.Rect) -> None:
        b = self.b
        dst.fill(BG, rect)
        self.hits = []
        x0, y = rect.x + 12, rect.y + 8
        state = {"edit": tr("編集中"), "run": tr("実行中"), "pause": tr("一時停止中")}[b.state]
        if b.rom:
            title = tr("マシン語の作業欄  {state}", state=state)
            x = self._text(dst, x0, y, title, HEAD, self.jfont)
            # パソコンのキーがどちらへ行くか(一時停止中はいつも作業欄へ)
            if self.focus or b.state == "pause":
                where, color = tr("キーは作業欄へ"), OK
            else:
                where, color = tr("キーは本体へ"), DIM  # 作業欄へ移す方法は、下の知らせに出る
            self._text(dst, x + 12, y + 1, where, color, self.jfont)
            if self.focus and b.state != "pause":
                pygame.draw.rect(dst, BTN_ON, rect, 2)
        else:
            title = tr("マシン語(ROMなし)  {state}", state=state)
            self._text(dst, x0, y, title, HEAD, self.jfont)
        y += 26
        # ボタン
        self.buttons = self.button_specs()
        bx = x0
        for i, btn in enumerate(self.buttons):
            w = self.jfont.size(btn.label)[0] + 16
            if bx > x0 and bx + w > rect.right - 12:  # 入らなければ次の段へ
                bx, y = x0, y + 32
            btn.rect = pygame.Rect(bx, y, w, 26)
            self._button(dst, btn, i, y + 3)
            bx += w + 6
        if b.state == "pause" and b.blocked(b.m.cpu.pc):
            # 続けられない理由を、ボタンのすぐ横に出す(詳しい理由は下の知らせに出る)
            note = tr("ROMなしでは使えない{addr:04X}番地で止まっています", addr=b.m.cpu.pc)
            if bx + self.jfont.size(note)[0] > rect.right - 12:
                bx, y = x0, y + 32
            self._text(dst, bx + 4, y + 3, note, WARN, self.jfont)
        y += 34
        # 開始番地と液晶の設定
        x = self._start_field(dst, x0, y)
        if b.rom:
            # ROMのある本体では、マシン語はBASICから呼ぶ。液晶はROMが使うので消さない
            note = tr("(BASICで CALL &{addr:04X} と打って呼ぶ)", addr=b.start)
            self._text(dst, x + 12, y, note, DIM, self.jfont)
            y = self._export_line(dst, x0, y + 24)
            return self._draw_rest(dst, rect, x0, y)
        r = pygame.Rect(x + 14, y + 2, 14, 14)
        pygame.draw.rect(dst, FG, r, 1)
        if b.clear_lcd:
            pygame.draw.line(dst, OK, (r.x + 3, r.y + 7), (r.x + 6, r.y + 11), 2)
            pygame.draw.line(dst, OK, (r.x + 6, r.y + 11), (r.x + 11, r.y + 3), 2)
        x = self._text(dst, r.right + 6, y, tr("実行の前に液晶を消す"), DIM, self.jfont)
        self.hits.append((pygame.Rect(r.x, r.y, x - r.x, 18), "clearlcd", 0))
        y = self._export_line(dst, x0, y + 24)
        self._draw_rest(dst, rect, x0, y)

    def _start_field(self, dst: pygame.Surface, x0: int, y: int) -> int:
        """開始番地の欄。クリックすると16進表記4桁で打てる。値は、ダンプと逆アセンブルの
        開始番地の印と同じ色で出す。まだ自分で決めていなければ(自動)を添える"""
        b, cw = self.b, self.cw
        x = self._text(dst, x0, y, tr("開始番地"), DIM, self.jfont) + 10
        box = pygame.Rect(x - 4, y - 1, 4 * cw + 8, 20)
        typing = b.start_buf is not None
        pygame.draw.rect(dst, CURSOR if typing else BTN, box, 1, border_radius=3)
        if typing:
            buf = b.start_buf or ""
            for i in range(4):
                if i == len(buf):
                    pygame.draw.rect(dst, CURSOR, (x + i * cw, y + 1, cw, self.LH - 2))
                self._text(dst, x + i * cw, y + 1, buf[i] if i < len(buf) else "_", FG)
        else:
            self._text(dst, x, y + 1, f"{b.start:04X}", START)
        x = box.right
        if b.start_by != "user" and not typing:
            x = self._text(dst, x + 4, y, tr("(自動)"), DIM, self.jfont)
        self.hits.append((pygame.Rect(x0, y - 1, x - x0, 20), "start", 0))
        return x

    def _undo_buttons(self, dst: pygame.Surface, right: int, y: int) -> None:
        """書き出しの行の右端に、取り消しとやり直しのボタンを置く(実行のボタンとは分ける)。
        押せないときは暗く出し、マウスを載せると理由を出す"""
        b, c, s = self.b, self.cmd, self.shift
        note, on = b.undo_note()
        tip = tr("{note}({key})", note=note, key=f"{c}Z") if on else note
        undo = Button(tr("取り消す"), "undo", tip, enabled=on)
        note, on = b.undo_note(redo=True)
        tip = tr("{note}({key})", note=note, key=f"{s}{c}Z") if on else note
        redo = Button(tr("やり直す"), "redo", tip, enabled=on)
        bx = right
        for btn in (redo, undo):
            w = self.jfont.size(btn.label)[0] + 16
            bx -= w
            btn.rect = pygame.Rect(bx, y - 2, w, 24)
            bx -= 6
        for btn in (undo, redo):
            self.buttons.append(btn)
            self._button(dst, btn, len(self.buttons) - 1, y + 1)

    def _export_line(self, dst: pygame.Surface, x0: int, y: int) -> int:
        """書き出しのボタン(右端に取り消しとやり直しのボタン)、次の行から書き出す範囲と合計の
        バイト数(作業欄の幅で折り返す)。ボタンはいつも左端に置き、範囲がいくつあっても位置が
        変わらないようにする。ボタンを押すと書き出す(⌘E・⇧⌘Eと同じ)。範囲の行をクリック
        すると、範囲を打てる"""
        b = self.b
        ranges, at = self._ranges
        # RAMを調べるので、0.5秒に1回だけ求める(自分で範囲を決めたときはすぐ)
        if time.monotonic() - at > 0.5 or self._ranges_span != b.span:
            ranges = b.export_ranges()
            self._ranges, self._ranges_span = (ranges, time.monotonic()), b.span
        self._undo_buttons(dst, x0 + PANE_W - 24, y)
        if ranges:
            x = x0
            for label, kind in (
                (tr(".hexに書き出す {c}E", c=self.cmd), "export"),
                (tr("ダンプリスト"), "listing"),  # ショートカット(⇧⌘E)はメニューと説明に出す
            ):
                btn = pygame.Rect(x, y - 2, self.jfont.size(label)[0] + 16, 24)
                pygame.draw.rect(dst, BTN, btn, border_radius=5)
                self._text(dst, x + 8, y + 1, label, FG, self.jfont)
                self.hits.append((btn, kind, 0))
                x = btn.right + 6
        else:
            self._text(dst, x0, y, tr("書き出すダンプはまだありません"), DIM, self.jfont)
        y += 26
        if b.span is not None:
            self._auto_button(dst, x0 + PANE_W - 24, y)
        if b.span_buf is not None:
            return self._span_field(dst, x0, y) + 4
        if not ranges:
            # 範囲の1行分をあけておき、取り消しで範囲がなくなってもダンプの位置を変えない。
            # 範囲を決める入口も置く
            x = self._text(dst, x0, y, tr("範囲を指定する"), FG if self.span_hover else DIM,
                           self.jfont)  # fmt: skip
            self.hits.append((pygame.Rect(x0, y, x - x0, 20), "span", 0))
            return y + 20 + 4
        size = sum(hi - lo for lo, hi in ranges)
        # 範囲は2行まで。入りきらなければ、残りの数を出す
        width = PANE_W - 24
        if b.span is not None:
            head = tr("範囲(指定、合計{n}バイト) ", n=size)
        elif len(ranges) > 1:
            head = tr("範囲({places}か所、合計{n}バイト) ", places=len(ranges), n=size)
        else:
            head = tr("範囲(合計{n}バイト) ", n=size)
        lines, line, comma = [], head, tr("、")
        for k, (lo, hi) in enumerate(ranges):
            part = span_text(lo, hi) + (comma if k < len(ranges) - 1 else "")
            rest = len(ranges) - k - 1
            # 2行目では、このあとに残りの数を書く場所もあけておく
            tail = tr("ほか{n}か所", n=rest) if rest and len(lines) == 1 else ""
            if self.jfont.size(line + part + tail)[0] > width:
                if len(lines) == 1:
                    line += tr("ほか{n}か所", n=len(ranges) - k)
                    break
                lines.append(line.rstrip())
                line = "　　 "
            line += part
        lines.append(line)
        top = y
        for t in lines:
            self._text(dst, x0, y, t, FG if self.span_hover else DIM, self.jfont)
            y += 20
        self.hits.append((pygame.Rect(x0, top, width, y - top), "span", 0))
        return y + 4

    def _auto_button(self, dst: pygame.Surface, right: int, y: int) -> None:
        """自分で決めた範囲を、書いた所から決める範囲に戻すボタン(範囲の行の右端)"""
        label = tr("自動に戻す")
        w = self.jfont.size(label)[0] + 16
        btn = pygame.Rect(right - w, y - 2, w, 22)
        pygame.draw.rect(dst, BTN, btn, border_radius=5)
        self._text(dst, btn.x + 8, y, label, FG, self.jfont)
        self.hits.append((btn, "spanauto", 0))

    def _span_field(self, dst: pygame.Surface, x0: int, y: int) -> int:
        """範囲を打っているあいだの欄(始めと終わりの番地を16進表記4桁ずつ)"""
        b, cw = self.b, self.cw
        x = self._text(dst, x0, y, tr("範囲"), DIM, self.jfont) + 10
        buf = b.span_buf or ""
        box = pygame.Rect(x - 4, y - 1, 10 * cw + 8, 20)
        pygame.draw.rect(dst, CURSOR, box, 1, border_radius=3)
        for i in range(8):
            cx = x + (i + 2 * (i >= 4)) * cw
            if i == len(buf):
                pygame.draw.rect(dst, CURSOR, (cx, y + 1, cw, self.LH - 2))
            self._text(dst, cx, y + 1, buf[i] if i < len(buf) else "_", FG)
        self._text(dst, x + 4 * cw, y, "〜", DIM, self.jfont)
        self.hits.append((pygame.Rect(x0, y - 1, box.right - x0, 20), "span", 0))
        return y + 20

    def _draw_rest(self, dst: pygame.Surface, rect: pygame.Rect, x0: int, y: int) -> None:
        """ダンプ、逆アセンブル、レジスタ、内部RAM、下の知らせ"""
        b, lh = self.b, self.LH
        # 残りの高さをダンプと逆アセンブルに分ける
        iram = lh * (self.IRAM_ROWS + 1) if self.show_iram else lh
        fixed = y - rect.y + lh * 2 + 8 + lh * 3 + 8 + lh * 4 + iram + 52
        self.rows = max(4, (rect.height - fixed) // (2 * lh))
        b.top_rows = min(b.top_rows, self.rows - 1)
        self._follow_pc()
        y = self._dump(dst, x0, y)
        y = self._disasm(dst, x0, y + 8)
        y = self._regs(dst, x0, y + 8)
        self._status(dst, x0, rect.bottom - 44, rect.width - 24)
        self._tip(dst, rect)
        self._why_tip(dst, rect)
        self._span_tip(dst, rect)

    def _follow_pc(self) -> None:
        """止まるたび(1命令進めたときも)、ダンプのカーソルをPCの命令に置く。そのあと
        カーソルを動かせば、逆アセンブルはカーソルについていく"""
        b = self.b
        pc = b.m.cpu.pc
        if b.state != "pause":
            self.followed = -1
            return
        if pc == self.followed:
            return
        self.followed = pc
        b.place(pc, self.rows)

    def _dump(self, dst, x0: int, y: int) -> int:
        b, cw, lh = self.b, self.cw, self.LH
        # 列の見出しは、バイトとチェックサムの列と同じ位置に1つずつ置く
        for i in range(ROW):
            self._text(dst, x0 + (5 + 3 * i) * cw, y, f"+{i}", DIM)
        sigma = self.mono.render("Σ", True, DIM)
        sx = x0 + (6 + 3 * ROW) * cw + (2 * cw - sigma.get_width()) // 2
        dst.blit(sigma, (sx, y))
        y += lh + 2
        first = (b.row - ROW * b.top_rows) & 0xFFFF
        pc = b.m.cpu.pc if b.state == "pause" else -1
        # カーソルのある命令のバイト(逆アセンブルで色をつけた行と同じ命令)
        at = b.ins_at(b.cursor)
        size = next(b.lines_from(at)).size
        here = {(at + i) & 0xFFFF for i in range(size)}
        # 開始番地か範囲の欄に打っているあいだはカーソルを出さない
        show_cursor = b.start_buf is None and b.span_buf is None
        for r in range(self.rows):
            a = (first + ROW * r) & 0xFFFF
            cur_row = a == b.row
            # 番地
            if cur_row and b.field == "addr" and show_cursor:
                for i, ch in enumerate(f"{a:04X}"):
                    if i == b.nib:
                        pygame.draw.rect(dst, CURSOR, (x0 + i * cw, y, cw, lh - 2))
                    self._text(dst, x0 + i * cw, y, ch, FG)
            else:
                self._text(dst, x0, y, f"{a:04X}", FG if cur_row else DIM)
            self.hits.append((pygame.Rect(x0, y, 4 * cw, lh), "addr", a))
            data = b.row_bytes(a)
            for i, v in enumerate(data):
                ba = (a + i) & 0xFFFF
                bx = x0 + (5 + 3 * i) * cw
                color = CHANGED if ba in b.changed else FG
                if not b.m.writable(ba):
                    color = DIM
                if ba in here:
                    pygame.draw.rect(dst, INSLINE, (bx - 2, y, 2 * cw + 4, lh - 2))
                if ba == pc:
                    pygame.draw.rect(dst, PCLINE, (bx - 2, y, 2 * cw + 4, lh - 2))
                if cur_row and b.field == "data" and i == b.col and show_cursor:
                    pygame.draw.rect(dst, CURSOR, (bx + b.nib * cw, y, cw, lh - 2))
                if ba == b.start:  # 開始番地のバイトの左の隙間に▶
                    tri = [(bx - cw + 1, y + 3), (bx - cw + 1, y + 13), (bx - 3, y + 8)]
                    pygame.draw.polygon(dst, START, tri)
                self._text(dst, bx, y, f"{v:02X}", color)
                self.hits.append((pygame.Rect(bx, y, 2 * cw, lh), "byte", ba))
            if cur_row and b.field == "data" and b.col >= ROW and show_cursor:
                pygame.draw.rect(dst, CURSOR, (x0 + (5 + 3 * ROW) * cw - cw, y + lh - 4, cw, 2))
            self._text(dst, x0 + (6 + 3 * ROW) * cw, y, f"{checksum(data):02X}", OK)
            y += lh
        return y

    def _disasm(self, dst, x0: int, y: int) -> int:
        b, cw, lh = self.b, self.cw, self.LH
        x = self._text(dst, x0, y, tr("逆アセンブル"), HEAD, self.jfont)
        note = tr("(左の印をクリックで止める所)")
        self._text(dst, max(x0 + 130, x + 12), y + 1, note, DIM, self.jfont)
        y += lh + 2
        pc = b.m.cpu.pc
        focus = b.cursor  # ダンプのカーソル(一時停止したときはPCに置かれる)
        cm = b.code_map()
        tag_w = self.jfont.size(tr("開始"))[0]
        for ins in b.disasm_from(focus, self.rows, focus):
            a = ins.addr
            if a <= b.cursor < a + ins.size:
                pygame.draw.rect(dst, INSLINE, (x0 - 4, y, PANE_W - 24, lh - 1))
            at_pc = b.state == "pause" and a == pc
            if at_pc:
                pygame.draw.rect(dst, PCLINE, (x0 - 4, y, PANE_W - 24, lh - 1))
            if at_pc or a == b.start:  # PCの行の印は開始番地の印より先
                tri = [(x0 + 12, y + 3), (x0 + 12, y + 13), (x0 + 18, y + 8)]
                pygame.draw.polygon(dst, OK if at_pc else START, tri)
            if a == b.start:
                tag = self.jfont.render(tr("開始"), True, START)
                dst.blit(tag, (x0 + PANE_W - 32 - tag.get_width(), y - 1))
            if a in b.breaks:
                pygame.draw.circle(dst, BREAK, (x0 + 5, y + 8), 5)
            else:
                pygame.draw.circle(dst, (60, 62, 68), (x0 + 5, y + 8), 5, 1)
            self.hits.append((pygame.Rect(x0 - 4, y, 24, lh), "break", a))
            data = "".join(f"{b.read(a + i):02X}" for i in range(min(ins.size, 4)))
            x = x0 + 3 * cw
            self._text(dst, x, y, f"{a:04X}", DIM)
            self._text(dst, x + 5 * cw, y, f"{data:<8}", DIM)
            if b.blocked(a):
                # ROMなしではROMの中身がない(0が並んでいるだけ)ので、命令としては出さない
                self._text(dst, x + 14 * cw, y, tr("(ROMの中身なし)"), DIM, self.jfont)
            else:
                kind, why = cm.state(a)
                if not b.in_ram(a):
                    color = DIM
                elif ins.name == "DB":
                    color = DATA_FG
                else:
                    color = UNSURE if why == "guessed" else FG
                text = f"{ins.name:<5} {ins.operand}"
                end = self._text(dst, x + 14 * cw, y, text, color)
                if ins.note:  # DTCの表の行の行き先
                    self._text(dst, end + cw, y, ins.note, DIM, self.jfont)
                mark = why_mark(why) if kind in ("head", "data") else ""
                if mark:
                    # 理由の1字は、開始番地の「開始」の左に並べる(重ならない)
                    img = self.jfont.render(mark, True, DIM if a != self.why_at else FG)
                    mx = x0 + PANE_W - 32 - tag_w - 8 - img.get_width()
                    dst.blit(img, (mx, y - 1))
                    self.hits.append((pygame.Rect(mx - 2, y, img.get_width() + 4, lh), "why", a))
            self.hits.append((pygame.Rect(x, y, 30 * cw, lh), "goto", a))
            y += lh
        # 右端の印の見方(詳しい理由は、印にマウスを載せると出る)
        legend = tr("✓:実行済み　.:静的解析　?:推定　U:ユーザ指定")
        self._text(dst, x0, y + 1, legend, DIM, self.small)
        return y + lh

    def _span_tip(self, dst: pygame.Surface, rect: pygame.Rect) -> None:
        """書き出す範囲の行にマウスを載せたら、範囲を打てることを、その行のすぐ下に出す"""
        if not self.span_hover or self.b.span_buf is not None:
            return
        hit = next((r for r, kind, _a in self.hits if kind == "span"), None)
        if hit is None:
            return
        lines = [tr("クリックすると、書き出す範囲を打てます")]
        self._tooltip(dst, rect, lines, (hit.x, hit.bottom + 2))

    def _why_tip(self, dst: pygame.Surface, rect: pygame.Rect) -> None:
        """マウスを載せた、理由の印の説明を、その行のすぐ下に出す(右に寄せる)"""
        if self.why_at < 0:
            return
        hit = next((r for r, kind, a in self.hits if kind == "why" and a == self.why_at), None)
        if hit is None:
            return
        text = why_text(self.b.code_map(), self.why_at)
        if not text:
            return
        lines = wrap_text(self.jfont, text, min(rect.width - 24, 380) - 16)
        self._tooltip(dst, rect, lines, (hit.right + 8, hit.bottom + 2), right=True)

    def _regs(self, dst, x0: int, y: int) -> int:
        b, cw, lh = self.b, self.cw, self.LH
        cpu = b.m.cpu
        ram, old = cpu.ram, b.prev_regs
        mark = b.state != "run" and b.ran
        x = self._text(dst, x0, y, tr("レジスタ"), HEAD, self.jfont)
        cyc = cpu.cycles - b.c0 if b.ran else 0
        self._text(dst, max(x0 + 80, x + 12), y + 1, tr("サイクル {n}", n=cyc), DIM, self.jfont)
        y += lh + 2

        def item(x: int, label: str, text: str, changed: bool) -> int:
            x = self._text(dst, x, y, label + "=", DIM)
            return self._text(dst, x, y, text, REGCHG if mark and changed else FG) + cw

        names = ["I", "J", "A", "B", "K", "L", "M", "N"]
        idx = [0, 1, 2, 3, 8, 9, 10, 11]
        x = x0
        for nm, i in zip(names, idx, strict=True):
            x = item(x, nm, f"{ram[i]:02X}", ram[i] != old[i])
        y += lh
        x = x0
        for nm, i in (("X", 4), ("Y", 6)):
            v, ov = ram[i] | ram[i + 1] << 8, old[i] | old[i + 1] << 8
            x = item(x, nm, f"{v:04X}", v != ov)
        pc, dp, p, q, r, c, z = b.ptrs()
        opc, odp, op_, oq, orr, oc, oz = b.prev_ptr
        x = item(x, "DP", f"{dp:04X}", dp != odp)
        x = item(x, "PC", f"{pc:04X}", pc != opc)
        y += lh
        x = x0
        x = item(x, "P", f"{p:02X}", p != op_)
        x = item(x, "Q", f"{q:02X}", q != oq)
        x = item(x, "R", f"{r:02X}", r != orr)
        x = item(x, "C", f"{c}", c != oc)
        x = item(x, "Z", f"{z}", z != oz)
        y += lh + 4
        # 見出しをクリックすると、内部RAMの行を開く・閉じる
        mark_s = "▼" if self.show_iram else "▶"
        x = self._text(dst, x0, y, f"{mark_s} " + tr("内部RAM"), HEAD, self.jfont)
        if self.show_iram:
            note = tr("(00〜0Bは I J A B XL XH YL YH K L M N)")
        else:
            note = tr("(クリックで開く)")
        x = self._text(dst, x + 8, y + 1, note, DIM, self.jfont)
        self.hits.append((pygame.Rect(x0, y, x - x0, lh), "iram", 0))
        y += lh + 2
        if not self.show_iram:
            return y
        for row in range(self.IRAM_ROWS):
            base = row * 16
            self._text(dst, x0, y, f"{base:02X}", DIM)
            for i in range(16):
                a = base + i
                color = REGCHG if mark and ram[a] != old[a] else (FG if a < 0x5C else DIM)
                if a == cpu.r and b.ran:  # スタックの頭
                    box = (x0 + (3 + 3 * i) * cw - 2, y, 2 * cw + 4, lh - 2)
                    pygame.draw.rect(dst, (70, 60, 90), box)
                self._text(dst, x0 + (3 + 3 * i) * cw, y, f"{ram[a]:02X}", color)
            y += lh
        return y

    def _status(self, dst, x0: int, y: int, width: int) -> None:
        b = self.b
        if self.flash and time.monotonic() < self.flash_until:
            text, color = self.flash, OK if self.flash_ok else WARN
        elif b.reason:
            text, color = b.reason, OK if b.state == "edit" else REGCHG
        else:
            text, color = self.hint(), DIM
        # 作業欄の幅で折り返し、下のあいたところに入る2行まで出す(入らなければ…で切る)
        lines = wrap_text(self.jfont, text, width) if text else []
        if len(lines) > self.STATUS_LINES:
            last = lines[self.STATUS_LINES - 1]
            while last and self.jfont.size(last + "…")[0] > width:
                last = last[:-1]
            lines = lines[: self.STATUS_LINES - 1] + [last + "…"]
        for k, t in enumerate(lines):
            self._text(dst, x0, y + 20 * k, t, color, self.jfont)

    def hint(self) -> str:
        b, c = self.b, self.cmd
        if b.start_buf is not None:
            return tr("開始番地を16進表記4桁で打つ  {c}Vで貼り付け  Escでやめる", c=c)
        if b.span_buf is not None:
            return tr(
                "始めと終わりの番地を16進表記4桁ずつ打つ  何も打たずにEnterで自動に戻す  "
                "{c}Vで貼り付け  Escでやめる",
                c=c,
            )
        if b.rom and b.state == "run":
            if not self.focus:
                return tr("作業欄をクリックすると、キーで作業欄のダンプを書けます")
            return tr(
                "16進表記で打つ  {c}.で一時停止  {c}Bで止める所  本体のクリックでキーは本体へ", c=c
            )
        if b.rom and b.state == "pause":
            return tr("{c}Gで続ける  {c}Jで次の1命令だけ実行  {s}{c}JでCALLごと", c=c, s=self.shift)
        if b.state == "run":
            return tr("実行中です。キーはPC-1251へ(EscはBRK)。{c}.で一時停止", c=c)
        if b.state == "pause":
            return tr("{c}Gで続ける  {c}Jで次の1命令だけ実行  Escで編集に戻る", c=c)
        if b.field == "addr":
            return tr("番地を4桁打ってSpace。続けて8バイトを打ってEnter(本のダンプリストと同じ)")
        return tr(
            "16進表記で打つ  Enterで次の行  Tabで番地を打って飛ぶ  {c}Gで実行  "
            "{c}Aでカーソルの所を開始番地に  {c}Vで貼り付け",
            c=c,
        )

    def hit(self, pos) -> tuple[str, int] | None:
        for i, btn in enumerate(self.buttons):
            if btn.rect.collidepoint(pos):
                return ("button", i)
        for r, kind, a in self.hits:
            if r.collidepoint(pos):
                return (kind, a)
        return None
