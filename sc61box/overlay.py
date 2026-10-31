"""窓の上に重ねる表示(プログラムの一覧、メニュー、キーの説明、知らせ)と、本体の下の
操作欄と紙"""

import os
import time
from collections.abc import Callable
from typing import NamedTuple

import pygame

from .i18n import tr

WHITE = (240, 240, 235)
GREY = (160, 162, 168)
SELECTED = (70, 92, 140, 255)
LINE_H = 26

# 日本語のフォント。pygame.font.SysFontはmacOSで存在しないファイルを開こうとすることが
# あるので、ファイルを直接探す
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


def _panel(w: int, h: int, alpha: int = 215) -> pygame.Surface:
    box = pygame.Surface((w, h), pygame.SRCALPHA)
    box.fill((20, 22, 26, alpha))
    return box


SEP = "   "  # 説明の1行の中で、項目を分ける空白


def _breakable(text: str, i: int) -> bool:
    """text[i]の前で行を分けてよいか。英字や数字の語の途中では分けない"""
    a, b = text[i - 1], text[i]
    return a == " " or b == " " or not (a.isascii() and b.isascii())


def cut(font: pygame.font.Font, text: str, width: int) -> tuple[str, str]:
    """textを、幅widthに入る頭と残りに分ける。語の途中では切らない(1語も入らなければ字で
    切る)。空白で分けたときは、残りの頭の空白を落とす"""
    k = len(text)
    while k > 1 and font.size(text[:k])[0] > width:
        k -= 1
    if k < len(text):
        j = next((j for j in range(k, 0, -1) if _breakable(text, j)), 0)
        if j:
            k = j
    head, rest = text[:k], text[k:]
    if head.endswith(" ") or rest.startswith(" "):
        head, rest = head.rstrip(" ") or head, rest.lstrip(" ")
    return head, rest


def wrap_text(font: pygame.font.Font, text: str, width: int) -> list[str]:
    """textを幅widthで折り返す(語の途中では切らない)"""
    lines = []
    while font.size(text)[0] > width and len(text) > 1:
        head, text = cut(font, text, width)
        lines.append(head)
    return lines + [text] if text or not lines else lines


def wrap(font: pygame.font.Font, text: str, width: int) -> list[str]:
    """textを幅widthに収まるように折り返す。なるべく項目の区切り(SEP)で切る"""
    out: list[str] = []
    line = ""
    for item in text.split(SEP):
        joined = line + SEP + item if line else item
        if font.size(joined)[0] <= width:
            line = joined
            continue
        if line:
            out.append(line)
        line = item
        if font.size(line)[0] > width:  # 1項目でも入らなければ、語の切れ目で切る
            *heads, line = wrap_text(font, line, width)
            out += heads
    out.append(line)
    return out


def shrink(box: pygame.Surface, height: int) -> pygame.Surface:
    """boxが高さheightに入らなければ、縦横を同じ割合で縮める"""
    if box.get_height() <= height:
        return box
    f = height / box.get_height()
    return pygame.transform.smoothscale(box, (int(box.get_width() * f), height))


def draw_help(dst: pygame.Surface, font: pygame.font.Font, lines: list[str]) -> None:
    """キーの説明を窓のまんなかに出す。窓が狭ければ折り返し、低ければ縮める"""
    w = dst.get_width() - 40
    rows = [r for line in lines for r in wrap(font, line, w - 28)]
    box = _panel(w, LINE_H * len(rows) + 16)
    for i, line in enumerate(rows):
        box.blit(font.render(line, True, (235, 235, 230)), (14, 8 + LINE_H * i))
    box = shrink(box, dst.get_height() - 20)
    x = (dst.get_width() - box.get_width()) // 2
    dst.blit(box, (x, (dst.get_height() - box.get_height()) // 2))


def draw_status(dst: pygame.Surface, font: pygame.font.Font, text: str) -> None:
    """窓の下に知らせを出す。改行があれば行を重ね、窓に入らない行は折り返す"""
    room = dst.get_width() - 48
    rows = [r for line in text.split("\n") for r in wrap(font, line, room)]
    imgs = [font.render(line, True, WHITE) for line in rows]
    lh = max(i.get_height() for i in imgs)
    box = _panel(max(i.get_width() for i in imgs) + 28, lh * len(imgs) + 14)
    for k, img in enumerate(imgs):
        box.blit(img, (14, 7 + lh * k))
    x = (dst.get_width() - box.get_width()) // 2
    dst.blit(box, (x, dst.get_height() - box.get_height() - 12))


def _badge(dst: pygame.Surface, font: pygame.font.Font, text: str, icon: str, right: bool) -> None:
    """窓の上の隅(rightなら右)に、絵つきの短い知らせを出す。iconは_iconの種類で、
    "rec"なら赤い丸を点滅させる"""
    label = font.render(text, True, WHITE)
    w, h = label.get_width() + 34, label.get_height() + 10
    x, y = (dst.get_width() - w - 10 if right else 10), 10
    dst.blit(_panel(w, h, 200), (x, y))
    if icon != "rec" or time.monotonic() % 1 < 0.6:
        _icon(dst, icon, x + 9, y + h // 2)
    dst.blit(label, (x + 26, y + 5))


def draw_recording(
    dst: pygame.Surface, font: pygame.font.Font, seconds: float, paused: bool = False
) -> None:
    """録画中であることを窓の右上に出す(録画には入らない)。一時停止中はそう出す"""
    sec = int(seconds)
    clock = f"{sec // 60}:{sec % 60:02d}"
    if paused:
        _badge(dst, font, tr("録画を一時停止中 {clock}", clock=clock), "pause", right=True)
    else:
        _badge(dst, font, tr("録画中 {clock}", clock=clock), "rec", right=True)


def draw_halted(dst: pygame.Surface, font: pygame.font.Font, text: str) -> None:
    """実行を一時停止していることを窓の左上に出す(録画には入らない)"""
    _badge(dst, font, text, "pause", right=False)


class ProgramMenu:
    """プログラムの一覧。itemsはprograms.Programの列"""

    ROWS = 12  # 見える行の数(窓が低ければ減らす)

    def __init__(self, items: list) -> None:
        self.all = items
        self.items = items  # 探す文字に合うもの
        self.query: str | None = None  # 探す文字。Noneなら探していない
        self.sel = 0
        self.top = 0
        self.visible = self.ROWS  # いま見えている行の数(drawで決める)
        self.rows: list[tuple[int, pygame.Rect]] = []  # 描いた行の(番号, 窓の中の範囲)
        self.search_rect = pygame.Rect(0, 0, 0, 0)
        self.box = pygame.Rect(0, 0, 0, 0)  # 一覧の枠全体(外を押すと閉じる)
        self.button_rects: list[tuple[str, pygame.Rect]] = []

    def search(self, query: str | None) -> None:
        """名前かファイル名にqueryを含むものだけを出す(大文字と小文字は区別しない)。
        Noneならすべて出す"""
        self.query = query
        q = (query or "").casefold()
        self.items = [p for p in self.all if q in p.title.casefold() or q in p.name.casefold()]
        self.sel = self.top = 0

    def move(self, step: int) -> None:
        """1行ずつ動かす(端から端へ回る)"""
        if self.items:
            self.sel = (self.sel + step) % len(self.items)
            self._show_selected()

    def page(self, step: int) -> None:
        """1画面ずつ動かす(端で止まる)"""
        if self.items:
            self.sel = min(max(self.sel + step * self.visible, 0), len(self.items) - 1)
            self._show_selected()

    def scroll(self, lines: int) -> None:
        """見える範囲を行単位で動かし、選んでいる行は見える範囲に入れる(ホイール)"""
        last = max(0, len(self.items) - self.visible)
        self.top = min(max(self.top + lines, 0), last)
        if self.items:
            self.sel = min(max(self.sel, self.top), self.top + self.visible - 1)

    def _show_selected(self) -> None:
        self.top = min(max(self.top, self.sel - self.visible + 1), self.sel)

    def hit(self, pos) -> int:
        return next((i for i, r in self.rows if r.collidepoint(pos)), -1)

    # ボタン: (表示, 短い表示, 動作の名前)。動作はApp.menu_actionが受ける。上の右には一覧
    # そのものの操作、下には選んだプログラムの操作を置く。下の2つは窓が狭くても名前を略さない
    @staticmethod
    def top_buttons() -> tuple[tuple[str, str, str], ...]:
        return (
            (tr("フォルダを開く(O)"), tr("フォルダ"), "folder"),
            (tr("読み直す(R)"), tr("読み直す"), "reload"),
            (tr("閉じる(Esc)"), tr("閉じる"), "close"),
        )

    @staticmethod
    def bottom_buttons() -> tuple[tuple[str, str, str], ...]:
        return (
            (tr("読み込むだけ(Shift+Enter)"), tr("読み込むだけ"), "load"),
            (tr("読み込んで実行(Enter)"), tr("読み込んで実行"), "run"),
        )

    def button_at(self, pos) -> str:
        """posにあるボタンの動作の名前(探す欄ならsearch)。なければ空"""
        if self.search_rect.collidepoint(pos):
            return "search"
        return next((act for act, r in self.button_rects if r.collidepoint(pos)), "")

    @staticmethod
    def _buttons(box, font, specs, x, y, h, short, right=False) -> list[tuple[str, pygame.Rect]]:
        """ボタンを横に並べて描く。rightなら右端をxにそろえる"""
        imgs = [
            (act, font.render(brief if short else label, True, WHITE))
            for label, brief, act in specs
        ]
        if right:
            x -= sum(img.get_width() + 18 for _a, img in imgs) + 6 * (len(imgs) - 1)
        out = []
        for act, img in imgs:
            r = pygame.Rect(x, y, img.get_width() + 18, h)
            pygame.draw.rect(box, BUTTON, r, border_radius=4)
            box.blit(img, (r.x + 9, r.centery - img.get_height() // 2))
            out.append((act, r))
            x = r.right + 6
        return out

    @staticmethod
    def _fit(font, text: str, room: int) -> str:
        while len(text) > 1 and font.size(text)[0] > room:  # 入らなければ後ろを略す
            text = text[:-2] + "…"
        return text

    def draw(self, dst: pygame.Surface, font: pygame.font.Font, model: str, folder: str) -> None:
        """modelは一覧を開いた機種、folderは置き場所。窓が低ければ行を減らす。上に名前で探す
        欄と一覧の操作、下に選んでいるものの説明(2行)と、読み込むボタンを出す"""
        items, lh = self.items, LINE_H
        w = min(dst.get_width() - 40, 900)
        rows = max(1, min(self.ROWS, (dst.get_height() - 36) // lh - 5))
        if rows != self.visible:
            self.visible = rows
            self._show_selected()
        h = lh * (rows + 5) + 16
        x0 = (dst.get_width() - w) // 2
        y0 = max(10, (dst.get_height() - h) // 2)
        box = _panel(w, h, 255)
        self.box = pygame.Rect(x0, y0, w, h)
        title = font.render(tr("プログラム"), True, WHITE)
        # 右上の一覧の操作(幅が足りなければ短い表示にし、左の見出しを省いて探す欄を広く取る)
        top_specs = self.top_buttons()
        full = sum(font.size(b[0])[0] + 24 for b in top_specs)
        short = full > w - title.get_width() - 220
        tops = self._buttons(box, font, top_specs, w - 10, 6, lh - 4, short, right=True)
        sx = 14
        if not short:
            box.blit(title, (14, 8))
            sx += title.get_width() + 14
        # 名前で探す欄
        search = pygame.Rect(sx, 6, max(60, min(320, tops[0][1].x - sx - 12)), lh - 4)
        pygame.draw.rect(box, (44, 47, 54), search, border_radius=4)
        if self.query is None:
            text, color = tr("名前で探す( / )"), GREY
        else:
            text, color = self.query + "▏", WHITE
        img = font.render(self._fit(font, text, search.width - 12), True, color)
        box.blit(img, (search.x + 8, search.centery - img.get_height() // 2))
        self.search_rect = search.move(x0, y0)
        if not items:
            text = tr("まだ何もありません。.basか.hexを置いてください")
            if self.query is not None:
                text = tr("合うものがありません(Escで探すのをやめる)")
            box.blit(font.render(text, True, GREY), (14, 8 + lh))
        above, below = self.top, max(0, len(items) - self.top - rows)
        bar = 12 if above or below else 0  # 入りきらないときは右に位置のバーを出す
        where = []
        if above:
            where.append(tr("▲ 上にあと{n}本", n=above))
        if below:
            where.append(tr("▼ 下にあと{n}本", n=below))
        if where:
            img = font.render(tr("{where}(↑↓かホイールで)", where="   ".join(where)), True, GREY)
            box.blit(img, (w - img.get_width() - 14 - bar, 8 + lh * (rows + 1)))
        if self.query is not None and items:
            img = font.render(tr("Escで探すのをやめる"), True, GREY)
            box.blit(img, (14, 8 + lh * (rows + 1)))
        if bar:
            ty, th = 8 + lh, lh * rows - 2
            pygame.draw.rect(box, (60, 62, 68), (w - 12, ty, 5, th), border_radius=2)
            ky = ty + th * self.top // len(items)
            kh = max(12, th * rows // len(items))
            pygame.draw.rect(box, (150, 152, 158), (w - 12, ky, 5, kh), border_radius=2)
        self.rows = []
        for n, prog in enumerate(items[self.top : self.top + rows]):
            i = self.top + n
            y = 8 + lh * (n + 1)
            if i == self.sel:
                pygame.draw.rect(box, SELECTED, (6, y - 2, w - 12 - bar, lh))
            info = prog.kinds + (f" {prog.size}B" if prog.size else "")
            if prog.errors:
                info += " " + tr("読めない行あり")
            img = font.render(info, True, GREY)
            box.blit(img, (w - img.get_width() - 14 - bar, y))
            label = self._fit(font, prog.label(model), w - img.get_width() - 40 - bar)
            box.blit(font.render(label, True, WHITE), (14, y))
            self.rows.append((i, pygame.Rect(x0 + 6, y0 + y - 2, w - 12 - bar, lh)))
        # 選んでいるものの説明。1行目はファイル名と動く機種、2行目は# help:か読めない行
        y = 8 + lh * (rows + 2)
        pygame.draw.line(box, (70, 72, 78), (10, y - 4), (w - 10, y - 4))
        if items:
            prog = items[self.sel]
            name = os.path.basename(prog.paths[0]) if prog.paths else prog.name
            models = prog.models
            if models is None:
                runs = tr("どの機種でも")
            else:
                runs = tr("{models}用", models=tr("・").join(f"PC-{m}" for m in models))
            meta = self._fit(font, f"{name}   {runs}", w - 28)
            box.blit(font.render(meta, True, GREY), (14, y))
            note = prog.errors[0] if prog.errors else "  ".join(prog.help.split("\n"))
            if note:
                color = (236, 170, 150) if prog.errors else WHITE
                box.blit(font.render(self._fit(font, note, w - 28), True, color), (14, y + lh))
        # 下のボタン。入らなければ( )のキーの説明を落とす
        y = 8 + lh * (rows + 4)
        specs = self.bottom_buttons()
        full = sum(font.size(b[0])[0] + 24 for b in specs)
        short = full > w - 20
        self.button_rects = [
            (act, r.move(x0, y0))
            for act, r in tops + self._buttons(box, font, specs, 10, y - 2, lh - 2, short)
        ]
        right = self.button_rects[-1][1].right - x0
        img = font.render(folder, True, GREY)
        if right + 16 + img.get_width() <= w - 10:
            box.blit(img, (w - 12 - img.get_width(), y))
        dst.blit(box, (x0, y0))


class MenuItem(NamedTuple):
    """メニューの1項目。actionがNoneなら区切り線。noteは下に小さく出す補足、iconは左に出す
    絵(_iconの種類)"""

    label: str
    key: str = ""  # ショートカット
    action: Callable[[], object] | None = None
    note: str = ""
    icon: str = ""
    enabled: bool = True  # Falseなら暗く出し、選べない(noteに理由を書く)


SEPARATOR = MenuItem("")


class BarButton(NamedTuple):
    """操作欄のボタン。menuは押すと出すメニューの種類(App.popup_items)で、メニューを出す
    ボタンでなければ空。optionalなら、窓が狭いときに省いてよい"""

    label: str
    action: Callable[[], object]
    icon: str = ""  # _iconの種類
    short: str = ""  # 窓が狭いときの表示
    tip: str = ""  # マウスを載せたときの説明
    optional: bool = False
    menu: str = ""


class Popup:
    """操作欄のボタンや右クリックで出す短いメニュー。項目はMenuItemの列。kindはメニューの
    種類(App.popup_itemsが受ける)。aboveなら、posを下の端にして上へ出す(操作欄のボタンの
    すぐ上)。sourceは出したボタンの番号(右クリックなら-1)"""

    def __init__(self, pos, kind: str = "context", above: bool = False, source: int = -1) -> None:
        self.pos = pos
        self.kind = kind
        self.above = above
        self.source = source
        self.sel = -1
        self.rows: list[tuple[int, pygame.Rect]] = []
        self.small: pygame.font.Font | None = None

    def move(self, step: int, items: list) -> None:
        """区切り線を飛ばして選ぶ項目を動かす"""
        live = [i for i, it in enumerate(items) if it.action is not None and it.enabled]
        k = live.index(self.sel) if self.sel in live else (-1 if step > 0 else 0)
        self.sel = live[(k + step) % len(live)]

    def hit(self, pos) -> int:
        return next((i for i, r in self.rows if r.collidepoint(pos)), -1)

    def draw(self, dst: pygame.Surface, font: pygame.font.Font, items: list, mark: str) -> None:
        """markと同じ表示の項目に●をつける。1列で、字の大きさは変えない(窓に入らないときだけ
        縮める)。背景は透かさない"""
        if self.small is None:
            self.small = load_help_font(13)
        small = self.small
        lh, note_h, sep_h, pad = LINE_H, 17, 9, 8

        def row_h(it: MenuItem) -> int:
            if it.action is None:
                return sep_h
            return lh + (note_h if it.note else 0)

        width = 32 + max(font.size(it.label)[0] + 40 + font.size(it.key)[0] for it in items) + 14
        notes = [small.size(it.note)[0] + 46 for it in items if it.note]
        width = max([width, *notes])
        height = pad * 2 + sum(row_h(it) for it in items)
        f = min(1.0, (dst.get_height() - 8) / height, (dst.get_width() - 8) / width)
        x = max(4, min(self.pos[0], dst.get_width() - int(width * f) - 4))
        y = self.pos[1] - int(height * f) - 4 if self.above else self.pos[1]
        y = max(4, min(y, dst.get_height() - int(height * f) - 4))
        box = pygame.Surface((width, height))
        box.fill((30, 32, 36))
        pygame.draw.rect(box, (96, 98, 104), box.get_rect(), 1)
        self.rows = []
        cy = pad
        for i, it in enumerate(items):
            text, key, act = it.label, it.key, it.action
            h = row_h(it)
            if act is None:
                mid = cy + sep_h // 2
                pygame.draw.line(box, (80, 82, 88), (8, mid), (width - 8, mid))
                cy += h
                continue
            ink = WHITE if it.enabled else (110, 112, 118)
            if i == self.sel and it.enabled:
                pygame.draw.rect(box, SELECTED, (4, cy, width - 8, h))
            if it.icon:
                _icon(box, it.icon, 12, cy + lh // 2)
            elif text == mark:
                box.blit(font.render("●", True, WHITE), (12, cy + 3))
            box.blit(font.render(text, True, ink), (32, cy + 3))
            if key:
                img = font.render(key, True, (150, 152, 158) if it.enabled else (90, 92, 98))
                box.blit(img, (width - 14 - img.get_width(), cy + 3))
            if h > lh:
                box.blit(small.render(it.note, True, (170, 172, 178)), (34, cy + lh - 3))
            if it.enabled:  # 選べない項目はクリックしても当たらない
                self.rows.append((i, pygame.Rect(x + 4 * f, y + cy * f, (width - 8) * f, h * f)))
            cy += h
        if f < 1.0:
            box = pygame.transform.smoothscale(box, (int(width * f), int(height * f)))
        dst.blit(box, (x, y))


# ---- 本体の下の操作欄と紙 ----
BAR_H = 34  # 操作欄の高さ(拡大率によらない)
BAR_BG = (34, 36, 40)
BUTTON = (58, 61, 68)
TIP_BG = (20, 21, 24)
BUTTON_ON = (84, 90, 104)


def _icon(dst: pygame.Surface, kind: str, x: int, cy: int) -> int:
    """ボタンの絵(録画の赤い丸、停止の四角、一時停止の2本の棒、録画の一時停止、再開の三角)を
    描き、幅を返す"""
    if kind == "rec":
        pygame.draw.circle(dst, (225, 50, 45), (x + 6, cy), 6)
    elif kind == "stop":
        pygame.draw.rect(dst, WHITE, (x + 1, cy - 5, 10, 10))
    elif kind == "pause":
        pygame.draw.rect(dst, WHITE, (x + 1, cy - 6, 4, 12))
        pygame.draw.rect(dst, WHITE, (x + 7, cy - 6, 4, 12))
    elif kind == "recpause":  # 録画の一時停止。録画の赤い丸に白い2本の棒
        pygame.draw.circle(dst, (225, 50, 45), (x + 6, cy), 7)
        pygame.draw.rect(dst, WHITE, (x + 3, cy - 4, 2, 8))
        pygame.draw.rect(dst, WHITE, (x + 7, cy - 4, 2, 8))
    elif kind == "play":
        pygame.draw.polygon(dst, WHITE, [(x + 1, cy - 6), (x + 1, cy + 6), (x + 11, cy)])
    else:
        return 0
    return 18


class Bar:
    """本体の下の操作欄。左にボタン(BarButtonの列)、右にいまの設定を出す。窓の幅が足りなければ
    短い表示にし、それでも入らなければoptionalのボタンを省く。マウスを載せたボタンの説明
    (ショートカットなど)は、ボタンの上に出す"""

    def __init__(self, buttons: list[BarButton]) -> None:
        self.buttons = buttons
        self.rects: list[pygame.Rect] = []  # 描いたボタンの窓の中の範囲
        self.hover = -1

    def hit(self, pos) -> int:
        return next((i for i, r in enumerate(self.rects) if r.collidepoint(pos)), -1)

    @staticmethod
    def _width(font: pygame.font.Font, b: BarButton, short: bool) -> int:
        text = b.short if short else b.label
        return (font.size(text)[0] + 20 if text else 6) + (18 if b.icon else 0) + 6

    @classmethod
    def min_width(cls, font: pygame.font.Font, buttons: list[BarButton]) -> int:
        """省けないボタンを短い表示で並べたときの幅(窓の幅の下限に使う)"""
        return 16 + sum(cls._width(font, b, True) for b in buttons if not b.optional)

    def draw(self, dst: pygame.Surface, font: pygame.font.Font, top: int, info: str) -> None:
        w = dst.get_width()
        pygame.draw.rect(dst, BAR_BG, (0, top, w, BAR_H))
        x = 8
        self.rects = []

        def width(b, short: bool) -> int:
            return self._width(font, b, short)

        short = sum(width(b, False) for b in self.buttons) > w - 16
        # 短くしても入らなければ、後ろの「?」などの補助のボタンから省く(省いたボタンの
        # 操作はメニューとキーでもできる)。省いたボタンのrectsは空の範囲にする
        shown = [True] * len(self.buttons)
        for i in reversed(range(len(self.buttons))):
            total = sum(width(b, short) for b, on in zip(self.buttons, shown, strict=True) if on)
            if total <= w - 16:
                break
            if self.buttons[i].optional:
                shown[i] = False
        for i, b in enumerate(self.buttons):
            label, icon, brief = b.label, b.icon, b.short
            if not shown[i]:
                self.rects.append(pygame.Rect(0, 0, 0, 0))
                continue
            text = brief if short else label
            img = font.render(text, True, WHITE)
            iw = 18 if icon else 0
            pad = 20 if text else 6
            r = pygame.Rect(x, top + 5, img.get_width() * bool(text) + pad + iw, BAR_H - 10)
            pygame.draw.rect(dst, BUTTON_ON if i == self.hover else BUTTON, r, border_radius=5)
            _icon(dst, icon, r.x + (9 if text else 4), r.centery)
            if text:
                dst.blit(img, (r.x + 10 + iw, r.centery - img.get_height() // 2))
            self.rects.append(r)
            x = r.right + 6
        img = font.render(info, True, GREY)
        if x + 12 + img.get_width() <= w - 10:
            dst.blit(img, (w - 10 - img.get_width(), top + (BAR_H - img.get_height()) // 2))
        if 0 <= self.hover < len(self.rects) and self.buttons[self.hover].tip:
            self._tip(dst, font, self.buttons[self.hover].tip, self.rects[self.hover])

    @staticmethod
    def _tip(dst: pygame.Surface, font: pygame.font.Font, text: str, at: pygame.Rect) -> None:
        """ボタンatの上に説明を出す。窓からはみ出さないように左右をずらす"""
        img = font.render(text, True, WHITE)
        r = pygame.Rect(0, 0, img.get_width() + 16, img.get_height() + 8)
        r.bottomleft = (at.x, at.y - 6)
        r.right = min(r.right, dst.get_width() - 4)
        r.x = max(r.x, 4)
        pygame.draw.rect(dst, TIP_BG, r, border_radius=5)
        dst.blit(img, (r.x + 8, r.y + 4))


class Paper:
    """プリンタの感熱紙。字は1字5×7の点で、点を少しずつ濃さを変えて打つ。新しい行が
    出ると紙が送られて上へずれる。fontはプリンタの字の形{コード: 5列}(printer.load_font)"""

    ROWS = 5  # 見せる行の数
    COLS = 24  # 1行の字数
    DOT = 3  # 点の間隔(px)
    LINE = 10  # 1行の高さ(点の数。字が7で、行のすき間が3)
    MARGIN = 24  # 字の外側の紙の余白(px)。左右と上下で同じにする
    PAPER = (249, 249, 245)
    INK = (2, 2, 10)

    def __init__(self, font: dict[int, bytes]) -> None:
        self.font = font
        self.cache: dict[tuple[int, int], pygame.Surface] = {}
        self.feed = 0.0  # 紙送りの残り(px)。0に向かって減る
        self.line_frames = 29  # 1行を印字する時間(フレーム。Appが行ごとに決める)
        self.moved = False  # 直前のtick()で紙を送ったか(プリンタの音を鳴らす)
        self.close_rect = pygame.Rect(0, 0, 0, 0)
        self.where_rect = pygame.Rect(0, 0, 0, 0)  # 保存先の表示
        self.small: pygame.font.Font | None = None

    @property
    def height(self) -> int:
        return self.DOT * self.LINE * self.ROWS + 16

    def fed(self, lines: int) -> None:
        """lines行ぶん紙を送る"""
        self.feed += self.DOT * self.LINE * lines

    @property
    def moving(self) -> bool:
        """紙送りが残っている"""
        return self.feed > 0.5

    def tick(self) -> None:
        """1フレームぶん紙送りを進める(毎フレーム呼ぶ。紙を出していなくても)。line_framesで
        決まる一定の速さで送る"""
        self.moved = self.moving
        self.feed = max(0.0, self.feed - self.DOT * self.LINE / self.line_frames)

    def _char(self, code: int, shade: int) -> pygame.Surface:
        """コードcodeの字の絵。shadeで点の濃さを少し変える(感熱紙のむら)"""
        key = (code, shade)
        img = self.cache.get(key)
        if img is None:
            d = self.DOT
            img = pygame.Surface((6 * d, 7 * d), pygame.SRCALPHA)
            cols = self.font.get(code, bytes(5))
            for c, bits in enumerate(cols):
                for r in range(7):
                    if bits >> r & 1:
                        a = 255 - 4 * ((c * 7 + r + shade) % 4)
                        pygame.draw.rect(img, (*self.INK, a), (c * d, r * d, d - 1, d - 1))
            self.cache[key] = img
        return img

    def _sheet(self, dst: pygame.Surface, paper: pygame.Rect) -> None:
        """紙の地。両端を少し暗くして丸みを出す"""
        pygame.draw.rect(dst, self.PAPER, paper)
        x0, top, pw, h = paper
        for k in range(4):
            shade = tuple(c - 5 - 3 * (3 - k) for c in self.PAPER)
            pygame.draw.line(dst, shade, (x0 + k, top), (x0 + k, top + h - 1))
            pygame.draw.line(dst, shade, (x0 + pw - 1 - k, top), (x0 + pw - 1 - k, top + h - 1))

    def _rows(self, dst: pygame.Surface, x: int, y: int, rows: list[bytes], first: int) -> None:
        """rowsを(x, y)から打つ。firstはrowsの最初の行が何行目か(点のむらを行ごとに変える)"""
        d = self.DOT
        for n, row in enumerate(rows):
            for k, code in enumerate(row[: self.COLS]):
                if any(self.font.get(code, b"")):
                    dst.blit(self._char(code, (first + n) * 7 + k), (x + k * 6 * d, y + 3 * d))
            y += d * self.LINE

    @property
    def width(self) -> int:
        # 字は5列の点のあとに1列あけるので、行の右端の字のあとのすき間は数えない
        return (self.COLS * 6 - 1) * self.DOT + 2 * self.MARGIN

    def picture(self, rows: list[bytes]) -> pygame.Surface:
        """印字したすべての行を、紙の絵にする(画像に保存する用)"""
        d, m = self.DOT, self.MARGIN
        h = d * self.LINE * max(1, len(rows)) - 3 * d + 2 * m  # 最後の行の下の3点は数えない
        # 窓の形式にならうと、アルファの成分があるのに字の上で透明になることがある(macOS)
        # ので、アルファのない24ビットで作る
        img = pygame.Surface((self.width, h), 0, 24)
        self._sheet(img, img.get_rect())
        self._rows(img, m, m - 3 * d, rows, 0)  # 字は行の頭から3点下に打つ
        return img

    def draw(self, dst: pygame.Surface, top: int, rows: list[bytes], where: list[str]) -> None:
        """rowsの最後の行を紙の下の端に打つ。whereは紙の左に出す保存先の行"""
        w, h, d = dst.get_width(), self.height, self.DOT
        pygame.draw.rect(dst, (28, 30, 34), (0, top, w, h))
        pw = min(w - 60, self.width)
        x0 = (w - pw) // 2
        paper = pygame.Rect(x0, top, pw, h)
        self._sheet(dst, paper)
        clip = dst.get_clip()
        dst.set_clip(paper)
        shown = rows[-(self.ROWS + 2) :]
        y = top + h - 8 - d * self.LINE * len(shown) + int(self.feed)
        self._rows(dst, x0 + self.MARGIN, y, shown, len(rows) - len(shown))
        dst.set_clip(clip)
        # 紙が出てくるプリンタの口
        pygame.draw.rect(dst, (16, 17, 20), (x0 - 10, top + h - 5, pw + 20, 5), border_radius=2)
        # 保存先(紙の左のすきまに、入るだけ)
        self.where_rect = pygame.Rect(0, 0, 0, 0)
        if where:
            if self.small is None:
                self.small = load_help_font(13)
            room = x0 - 16
            texts = []
            for t in where:  # 入らない行は頭を「…」にして縮める
                while len(t) > 2 and self.small.size(t)[0] > room:
                    t = "…" + t[2:]
                texts.append(t)
            imgs = [self.small.render(t, True, GREY) for t in texts]
            if room > 60:
                y = top + 8
                for img in imgs:
                    dst.blit(img, (x0 - 10 - img.get_width(), y))
                    y += img.get_height() + 2
                bw = max(i.get_width() for i in imgs)
                self.where_rect = pygame.Rect(x0 - 10 - bw, top + 8, bw, y - top - 8)
        # 紙をしまう印
        self.close_rect = pygame.Rect(x0 + pw + 8, top + 6, 22, 22)
        pygame.draw.rect(dst, (58, 61, 68), self.close_rect, border_radius=4)
        c = self.close_rect.center
        for sx in (-1, 1):
            pygame.draw.line(dst, WHITE, (c[0] - 5, c[1] - 5 * sx), (c[0] + 5, c[1] + 5 * sx), 2)
