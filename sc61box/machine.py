"""本体: メモリ、キーボード、タイマ、液晶、ブザー

PC-1251の配置はMAMEとPockEmulの実装、ポートのビットはPOPCOM 1984年9〜11月号の講座の表7による。

    0000-1FFF  内部ROM(8KB)
    4000-7FFF  BASIC ROM(16KB)
    B800-C7FF  RAM(4KB)。B000-B7FFはB800-BFFFのミラー
    F800-F87F  液晶RAM。F900-FFFFの各256バイトにも同じものが見える

PC-1245は同じつくりで、RAMがC000-C7FFの2KB、液晶が16桁、モードスイッチにRSVの段がない。

PC-1260/1261/1262の配置は次のとおり。キー、モードスイッチ、タイマ、ブザー、カセットの
ポートはPC-1251と同じ。

    0000-1FFF  内部ROM(8KB)
    2000-20FF  液晶RAM(左の12桁)。2000-203Bが1行目、2040-207Bが2行目。
               203C-203Fと207C-207Fに表示記号のビット。2080-20FFはROMの作業域
    2800-28FF  液晶RAM(右の12桁)。並びは2000-20FFと同じ。2880-28FFは式の計算のスタック
    4000-67FF  RAM(PC-1261・1262は10KB、PC-1260は5800-67FFの4KB)。6600-67FFはBASICの作業域
    8000-FFFF  BASIC ROM(32KB)

PC-1260/1261/1262の水晶は768kHz(PC-1251は576kHz)。ROMのテープを読むルーチンの待ちの回数が
PC-1251の約4/3倍で、576kHzとして動かすとROMが自分で書いたテープを読めない。
PC-1350はクラスPC1350(このファイルの後半)。
"""

import base64
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace

from . import paths
from .i18n import tr
from .printer import LEAD_1251, LEAD_1350, SWAP_1350, Printer
from .sc61860 import SC61860, Bus

CLOCK = 192_000  # 命令サイクルの周波数(水晶576kHzの1/3)
TICK_2MS = CLOCK // 500  # 2msごとに反転するタイマ
LCD_LO, LCD_HI = 0xF800, 0xF900

# キーの配置。(ポート, ストローブのビット, 読むビット)。("B", n)はIBのビットn、
# ("A", n)はIAのビットnを出したときに読める(MAMEとPockEmulによる)
KEYS = {
    "-": ("B", 0, 0x01),
    "CL": ("B", 0, 0x02),
    "*": ("B", 0, 0x04),
    "/": ("B", 0, 0x08),
    "DOWN": ("B", 0, 0x10),
    "E": ("B", 0, 0x20),
    "D": ("B", 0, 0x40),
    "C": ("B", 0, 0x80),
    "+": ("B", 1, 0x01),
    "9": ("B", 1, 0x02),
    "3": ("B", 1, 0x04),
    "6": ("B", 1, 0x08),
    "SHIFT": ("B", 1, 0x10),
    "W": ("B", 1, 0x20),
    "S": ("B", 1, 0x40),
    "X": ("B", 1, 0x80),
    ".": ("B", 2, 0x01),
    "8": ("B", 2, 0x02),
    "2": ("B", 2, 0x04),
    "5": ("B", 2, 0x08),
    "DEF": ("B", 2, 0x10),
    "Q": ("B", 2, 0x20),
    "A": ("B", 2, 0x40),
    "Z": ("B", 2, 0x80),
    "7": ("A", 0, 0x02),
    "1": ("A", 0, 0x04),
    "4": ("A", 0, 0x08),
    "UP": ("A", 0, 0x10),
    "R": ("A", 0, 0x20),
    "F": ("A", 0, 0x40),
    "V": ("A", 0, 0x80),
    "=": ("A", 1, 0x04),
    "P": ("A", 1, 0x08),
    "LEFT": ("A", 1, 0x10),
    "T": ("A", 1, 0x20),
    "G": ("A", 1, 0x40),
    "B": ("A", 1, 0x80),
    "O": ("A", 2, 0x08),
    "RIGHT": ("A", 2, 0x10),
    "Y": ("A", 2, 0x20),
    "H": ("A", 2, 0x40),
    "N": ("A", 2, 0x80),
    "U": ("A", 3, 0x20),
    "J": ("A", 3, 0x40),
    "M": ("A", 3, 0x80),
    "I": ("A", 4, 0x20),
    "K": ("A", 4, 0x40),
    "SPC": ("A", 4, 0x80),
    "L": ("A", 5, 0x40),
    "ENTER": ("A", 5, 0x80),
    "0": ("A", 6, 0x80),
}

# 液晶の表示記号: (番地, ビット)。PockEmulによる
SYMBOLS = {
    "BUSY": (0xF83D, 0x01),
    "P": (0xF83C, 0x02),
    "DEF": (0xF83C, 0x01),
    "SHIFT": (0xF83D, 0x02),
    "PRO": (0xF83E, 0x01),
    "RUN": (0xF83E, 0x02),
    "RESERVE": (0xF83E, 0x04),
    "DE": (0xF83C, 0x08),
    "G": (0xF83C, 0x04),
    "RAD": (0xF83D, 0x04),
    "E": (0xF83D, 0x08),
}


# PC-1260/1261/1262の表示記号。GRAD(207Cのビット2)の記号は液晶にない。207Cのビット6は、
# 筐体に字のない横棒(ERRORの右)を点ける(POKE &207C,&40で確かめられた。HIDDEN)。ROMは
# このビットを立てず、電源を入れたときに消す(内部ROMの080B〜080C)。
# SHIFT+8(内部ROMの11FD〜122A)は、203Cのビット7が1ならカナの入力(KANA)を、0なら英小文字の
# 入力(SMALL)を切り替える。ビット7は電源を入れたときに1になり(1927、INBのビット3が0のとき)、
# POKE &203C,PEEK &203C AND &7Fで0にすると英小文字を打てる
SYMBOLS_1261 = {
    "BUSY": (0x203D, 0x01),
    "PRINT": (0x203D, 0x02),
    "KANA": (0x203D, 0x08),
    "SMALL": (0x203D, 0x10),
    "SHIFT": (0x203D, 0x20),
    "DEF": (0x203D, 0x40),
    "DEG": (0x207C, 0x01),
    "RAD": (0x207C, 0x02),
    "ERROR": (0x207C, 0x20),
    "HIDDEN": (0x207C, 0x40),
}


# PC-1245の表示記号はF83CとF83Dの8つ(ht-deko.comによる)。モードの記号はない
SYMBOLS_1245 = {
    name: SYMBOLS[name] for name in ("DEF", "P", "G", "DE", "BUSY", "SHIFT", "RAD", "E")
}


@dataclass(frozen=True)
class Model:
    """機種ごとの違い"""

    name: str  # --modelで選ぶ名前("1251")
    title: str  # "PC-1251"
    ram: tuple[int, int]  # RAMの範囲(終わりは含まない)
    mirror: tuple[int, int, int] | None  # RAMのミラー(始め, 終わり, 足す数)。足した番地と同じもの
    # 液晶RAMのミラーになる256バイトの区画の頭。同じ2KBの中にある液晶RAMが見える。
    # 同じ2KBの中になければ、最初の液晶RAM
    lcd_mirrors: tuple[int, ...]
    cells: int  # 液晶の1行の桁数
    modes: tuple[str, ...]  # モードスイッチの段(上から)
    symbols: dict[str, tuple[int, int]]
    prog_start: int  # BASICのプログラムの先頭(FFの番地)
    # BASICがプログラムの終わり(終わりのFFの番地)を置くところと、プログラムが使える上限
    # (MEMが0になる終わりの番地)
    prog_end_ptr: int = 0xC6E3
    prog_top: int = 0xC5CF
    rom: str = ""  # ROMのファイル名の機種の部分。空ならnameと同じ
    bas_addr: int = 0x4000  # BASIC ROMの先頭
    bas_size: int = 0x4000
    lcd: tuple[tuple[int, int], ...] = ((0xF800, 0xF900),)  # 液晶RAMの範囲
    lines: int = 1  # 液晶の行数
    ratio: tuple[int, int] = (1, 1)  # CPUのサイクルに掛けて時刻(192kHz)にする比
    family: str = ""  # PC-1350は"1350"
    base: str = ""  # ROMと筐体の絵が同じで、RAMの範囲だけが違う機種(そのプログラムも使える)

    @property
    def roms(self) -> tuple[str, str]:
        """(内部ROM, BASIC ROM)のファイル名"""
        r = self.rom or self.name
        return (f"cpu-{r}.rom", f"bas-{r}.rom")


MODELS = {
    "1251": Model(
        name="1251",
        title="PC-1251",
        ram=(0xB800, 0xC800),
        mirror=(0xB000, 0xB800, 0x800),
        lcd_mirrors=tuple(range(0xF900, 0x10000, 0x100)),
        cells=24,
        modes=("RSV", "PRO", "RUN", "OFF"),
        symbols=SYMBOLS,
        prog_start=0xB830,
    ),
    "1245": Model(
        name="1245",
        title="PC-1245",
        ram=(0xC000, 0xC800),
        mirror=None,
        # E800-EFFFは、PC-1245用のプログラムがこの番地で液晶に書いていることから
        lcd_mirrors=tuple(range(0xE800, 0xF000, 0x100)) + tuple(range(0xF900, 0x10000, 0x100)),
        cells=16,
        modes=("PRO", "RUN", "OFF"),
        symbols=SYMBOLS_1245,
        prog_start=0xC000,
    ),
}

# PC-1260/1261/1262は同じROMで、RAMの大きさだけが違う
for _name, _lo in (("1260", 0x5800), ("1261", 0x4000), ("1262", 0x4000)):
    MODELS[_name] = Model(
        name=_name,
        title=f"PC-{_name}",
        ram=(_lo, 0x6800),
        mirror=None,
        # 液晶RAMは番地の下位8ビットしか見ない(コンパイラLC-3のTRONは27xxに書く)
        lcd_mirrors=tuple(range(0x2100, 0x2800, 0x100)) + tuple(range(0x2900, 0x3000, 0x100)),
        cells=24,
        modes=("RSV", "PRO", "RUN", "OFF"),
        symbols=SYMBOLS_1261,
        prog_start=_lo + 0x80,
        prog_end_ptr=0x66E3,
        prog_top=0x64F0,
        rom="1260",
        base="" if _name == "1261" else "1261",
        bas_addr=0x8000,
        bas_size=0x8000,
        lcd=((0x2000, 0x2100), (0x2800, 0x2900)),
        lines=2,
        ratio=(3, 4),
    )


# PC-1250とPC-1255はPC-1251と同じROMで、RAMの範囲だけが違う(MAMEのpc1250_mem、pc1255_mem)
for _name, _lo in (("1250", 0xC000), ("1255", 0xA000)):
    MODELS[_name] = replace(
        MODELS["1251"],
        name=_name,
        title=f"PC-{_name}",
        ram=(_lo, 0xC800),
        # PC-1255の8000-9FFFはA000-BFFFのミラーとした。ROMは起動のときに、RAMの頭を下へ探しながら
        # 書いた印が上の区画に写るかを見ていて、ミラーがないと8000からRAMがあるとみる
        # (ミラーがあるとMEMが9630になり、カタログの値と合う)
        mirror=(0x8000, 0xA000, 0x2000) if _name == "1255" else None,
        prog_start=_lo + 0x30,
        rom="1251",
        base="1251",
    )

# PC-1350。RAMは本体の4KB(6000-6FFF)。7000-7DFF(液晶RAMとROMの作業域)もRAMとして扱う
MODELS["1350"] = Model(
    name="1350",
    title="PC-1350",
    ram=(0x6000, 0x7000),
    mirror=None,
    lcd_mirrors=(),
    cells=24,
    modes=("ON", "OFF"),
    symbols={},
    prog_start=0x6030,
    prog_end_ptr=0x6F03,
    prog_top=0,  # 6F07に置かれる(PC1350._program_top)
    bas_addr=0x8000,
    bas_size=0x8000,
    lcd=((0x7000, 0x7E00),),
    lines=4,
    ratio=(3, 4),
    family="1350",
)


# RAMの範囲だけが違う機種(PC-1250・1255、PC-1260・1262)と、そのROMと絵を持つ元の機種
BASE_MODEL = {name: m.base for name, m in MODELS.items() if m.base}


def ram_span(model: Model, top: int | None) -> tuple[int, int]:
    """RAMの範囲。topはプログラムの# ram: で広げる終わり(含まない)。機種のRAMの終わりより
    下には狭めず、広げる先にROMか液晶RAM(そのミラーも)があれば広げない"""
    lo, hi = model.ram
    if top is None or top <= hi:
        return lo, hi
    top = min(top, 0x10000)
    taken = [(0, 0x2000), (model.bas_addr, model.bas_addr + model.bas_size), *model.lcd]
    taken += [(a, a + 0x100) for a in model.lcd_mirrors]
    if any(a < top and hi < b for a, b in taken):
        return lo, hi
    return lo, top


class RomNotFound(FileNotFoundError):
    pass


def find_rom(name: str) -> str:
    """ROMファイルを探す。SC61BOX_ROM(前の名前のPC1251_ROMも)、./rom、エミュレータの
    rom/、データのフォルダ(~/.sc61box)の順"""
    dirs = [
        paths.env("ROM"),
        "rom",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rom"),
        paths.data_dir(),
    ]
    for d in dirs:
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    model = name[4:-4]  # "cpu-1251.rom"の"1251"
    kb = rom_size(f"bas-{model}.rom") // 1024
    raise RomNotFound(
        tr("ROMのファイル{name}が見つかりません。実機から読み出した内部ROM(cpu-{model}.rom、"
           "8KB)とBASIC ROM(bas-{model}.rom、{kb}KB)をrom/に置くか、環境変数SC61BOX_ROMに"
           "置き場所を指定してください(READMEの「ROMの用意」)。", name=name, model=model, kb=kb)
    )  # fmt: skip


def rom_size(name: str) -> int:
    """内部ROMは8KB、BASIC ROMは16KB(PC-1260/1261/1262は32KB)"""
    if name.startswith("cpu-"):
        return 0x2000
    return 0x8000 if name in ("bas-1260.rom", "bas-1350.rom") else 0x4000


def read_rom(name: str) -> bytes:
    """ROMのファイルを読む。版の違いがあるので、確かめるのは大きさだけ"""
    path = find_rom(name)
    data = open(path, "rb").read()
    size = rom_size(name)
    if len(data) < size:
        raise RomNotFound(
            tr("{path}は{have}バイトしかありません。{name}は{size}バイト({kb}KB)必要です。",
               path=path, have=len(data), name=name, size=size, kb=size // 1024)
        )  # fmt: skip
    return data


def new_machine(
    model: str = "1251", card: int = 0, overseas: bool = False, rom: bool = True
) -> "PC1251":
    """機種の本体を作る。cardとoverseasはPC-1350だけが使う。romがFalseなら、ROMを読まずに
    ROMの番地を0で埋めた本体を作る(マシン語の作業欄で、ROMなしでマシン語だけを動かす。
    PC-1350は液晶のつくりが違うので、ROMなしでは作れない)"""
    if MODELS[model].family == "1350":
        if not rom:
            raise ValueError(tr("PC-1350はROMなしでは動かせません"))
        return PC1350(model=model, card=card, overseas=overseas)
    return PC1251(model=model, norom=not rom)


class PC1251(Bus):
    """PC-1251、PC-1245、PC-1260/1261/1262の本体"""

    card = 0  # RAMカードの大きさ(KB)。PC-1350だけが差せる

    def __init__(
        self,
        cpu_rom: bytes | None = None,
        bas_rom: bytes | None = None,
        model: str = "1251",
        norom: bool = False,
    ):
        self.model = MODELS[model]
        if self.model.family == "1350" and type(self) is PC1251:
            raise ValueError("PC-1350はnew_machine()かPC1350で作る")
        self.mem = bytearray(0x10000)
        ba, bs = self.model.bas_addr, self.model.bas_size
        self.norom = norom  # ROMを読まずに作った(ROMの番地はすべて0)
        if not norom:
            cpu_name, bas_name = self.model.roms
            self.mem[0:0x2000] = (cpu_rom or read_rom(cpu_name))[:0x2000]
            self.mem[ba : ba + bs] = (bas_rom or read_rom(bas_name))[:bs]
        if self.model.lines == 2:
            # 何もつながっていない番地は、番地の上位バイトを返すとした(データバスに残る値)。
            # PEEK &7FFFが127になることで機種を見分けるプログラムがある
            used = (*self.model.lcd, self.model.ram)
            for a in range(0x2000, ba):
                if not any(lo <= a < hi for lo, hi in used):
                    self.mem[a] = a >> 8
        self.wmask = bytearray(0x10000)
        ram_lo, ram_hi = self.model.ram
        for a in range(ram_lo, ram_hi):
            self.wmask[a] = 1
        mirror = self.model.mirror
        self._mirror_lo, self._mirror_hi, self._mirror_add = mirror if mirror else (0, 0, 0)
        self._lcd_ram = bytearray(256)  # 上位バイトごとに、液晶RAMなら1
        for lo, hi in self.model.lcd:
            for a in range(lo, hi):
                self.wmask[a] = 1
            self._lcd_ram[lo >> 8] = 1
        # 上位バイトごとに、液晶RAMのミラーなら見える区画の上位バイト
        self._lcd_page = bytearray(256)
        for a in self.model.lcd_mirrors:
            same = [lo for lo, _ in self.model.lcd if lo & 0xF800 == a & 0xF800]
            self._lcd_page[a >> 8] = (same or [self.model.lcd[0][0]])[0] >> 8
        self.cpu = SC61860(self, self.model.ratio)
        self.held: set[str] = set()  # 押されているキー
        self.brk = False  # BRK(ON)キー
        self.reset_key = False  # 裏のRESETボタン
        self.mode = "RUN"
        self.pa = self.pb = self.pc_out = self.pf = 0
        self.lcd_dirty = True
        # 液晶RAMに書いた記録((サイクル, 番地, 前の値, 書いた値)の並び)。Noneなら記録しない
        self.lcd_trace: list[tuple[int, int, int, int]] | None = None
        self.reset_at: int | None = None  # 実行の区切りの中でカウンタをリセットしたサイクル
        self.power = True  # Cポートのビット3で切れる
        self.halted = False  # Cポートのビット2で止まっている
        self.printer: Printer | None = None  # つないだプリンタ
        self.cold_start()

    # ---- 電源とリセット ----
    def cold_start(self) -> None:
        self.cpu.reset()
        self.cpu.ram[:] = bytes(len(self.cpu.ram))
        self.t2 = 0
        self.t2ms = self.t512 = 0
        self.t512cnt = 0
        self.tape = None  # 再生中のテープ(tape.TapeIn)
        self.power = True
        self.sound_events: list[tuple[int, int]] = []  # (サイクル, Cポートの上位4ビット)

    def wake(self) -> None:
        """ONキーで電源を入れ直す。RAMの中身は残る"""
        self.cpu.reset()
        self.power = True
        self.halted = False

    def power_on(self) -> None:
        """電源を入れる(PC-1350では電源スイッチをONにする)"""
        self.wake()

    # ---- RAMの終わりを動かす(プログラムの# ram:) ----
    def _unused(self, a: int) -> int:
        """何もつながっていない番地を読んだときの値"""
        return a >> 8 if self.model.lines == 2 else 0

    def ram_top(self, top: int | None) -> int:
        """# ram: の終わりtopから、動かす先のRAMの終わり(含まない)。機種の既定より下には
        狭めず、Noneは既定"""
        base = MODELS[self.model.name].ram[1]
        return base if top is None else min(max(top, base), 0x10000)

    def ram_top_ok(self, top: int | None) -> bool:
        """RAMの終わり(含まない)をtopに動かせるか(ram_span)"""
        want = self.ram_top(top)
        return ram_span(replace(self.model, ram=MODELS[self.model.name].ram), want)[1] == want

    def set_ram_top(self, top: int | None) -> None:
        """RAMの終わりをtopに動かす(先にram_top_okで確かめる)。広げた所は0にし、狭めて外した
        所はつながっていない番地に戻す"""
        lo, hi = self.model.ram
        top = self.ram_top(top)
        for a in range(min(hi, top), max(hi, top)):
            self.wmask[a] = 1 if top > hi else 0
            self.mem[a] = 0 if top > hi else self._unused(a)
        self.model = replace(self.model, ram=(lo, top))

    # ---- バス ----
    def read(self, a: int) -> int:
        if self._mirror_lo <= a < self._mirror_hi:
            a += self._mirror_add
        elif self._lcd_page[a >> 8]:
            a = self._lcd_page[a >> 8] << 8 | (a & 0xFF)
        return self.mem[a]

    def writable(self, a: int) -> bool:
        """番地aに書いたものがRAMか液晶RAMに入るか"""
        if not 0 <= a < 0x10000:
            return False
        if self._mirror_lo <= a < self._mirror_hi:
            a += self._mirror_add
        elif self._lcd_page[a >> 8]:
            a = self._lcd_page[a >> 8] << 8 | (a & 0xFF)
        return bool(self.wmask[a])

    def write(self, a: int, v: int) -> None:
        if self._mirror_lo <= a < self._mirror_hi:
            a += self._mirror_add
        elif self._lcd_page[a >> 8]:
            a = self._lcd_page[a >> 8] << 8 | (a & 0xFF)
        if self.wmask[a]:
            if self._lcd_ram[a >> 8]:
                self.lcd_dirty = True
                if self.lcd_trace is not None and self.mem[a] != v:
                    self.lcd_trace.append((self.cpu.cycles, a, self.mem[a], v))
            self.mem[a] = v

    def _scan(self, port: str, strobe: int) -> int:
        v = 0
        for k in self.held:
            key = KEYS.get(k)
            if key and key[0] == port and strobe & (1 << key[1]):
                v |= key[2]
        return v

    def in_a(self) -> int:
        v = self._scan("B", self.pb & 0x07) | self._scan("A", self.pa & 0x7F)
        # PC-1261などはIBのビット3を出してINAのビット7でOFFを読む(内部ROMの18DA〜1918)
        if self.model.lines == 2 and self.pb & 0x08 and self.mode == "OFF":
            v |= 0x80
        return v

    def in_b(self) -> int:
        # IBのビット3を出すと、モードスイッチがビット0(RSV)、1(PRO)、2(OFF)に返る
        # (PockEmulによる)。OFFを読むと、ROMは自分で電源を切る
        data = self.pb & 0x0F
        ret = 0
        if self.pb & 0x08:
            ret |= {"PRO": 2, "RSV": 1, "OFF": 4}.get(self.mode, 0)
        if (self.pb & 0x02) and self.mode == "PRO":
            ret |= 0x08
        if (self.pb & 0x01) and self.mode == "RSV":
            ret |= 0x08
        v = (ret & ~data) | (self.pb & 0xF0)
        if self.printer is not None:
            # プリンタの応答(ビット6)は、合図(Fのビット0)をそのまま返す。ビット7は0
            v = (v & 0x3F) | (0x40 if self.pf & 0x01 else 0)
        return v

    def connect_printer(self, on: bool = True) -> None:
        """プリンタをつなぐ(onがFalseなら外す)。PC-1251・PC-1245のROMは、つながっているかを
        電源を入れたときに調べるので、つないだあとで電源を入れ直す"""
        if not on:
            self.printer = None
        elif self.model.family == "1350":
            self.printer = Printer(SWAP_1350, LEAD_1350)
        elif self.model.lines == 2:  # PC-1261などは、行の頭に字でないコードを送らない
            self.printer = Printer()
        else:
            self.printer = Printer(lead=LEAD_1251)

    def out_a(self, v: int) -> None:
        self.pa = v

    def out_b(self, v: int) -> None:
        self.pb = v
        if self.printer is not None:
            self.printer.restart()

    def out_f(self, v: int) -> None:
        # プリンタへ: Fのビット1がデータ、ビット0が合図。Bのビット5を下ろしているあいだは命令
        if self.printer is not None and v & 0x01 and not self.pf & 0x01:
            self.printer.bit(v >> 1, command=not self.pb & 0x20)
        self.pf = v

    def out_c(self, v: int) -> None:
        old = self.pc_out
        self.pc_out = v
        if v & 0x02:  # カウンタのリセット。立っているタイマのフラグも消す(リセットからTEST命令で
            # 512msを待つプログラムが、前に立ったままのフラグで待たずに抜けないように)
            self.t2 = 0
            self.t512cnt = 0
            self.t512 = self.t2ms = 0
            self.reset_at = self.cpu.cycles
        if (v ^ old) & 0xF0:
            self.sound_events.append((self.cpu.cycles, v >> 4))
        if v & 0x08:  # 電源オフ
            self.power = False
        if v & 0x04:  # 止まって待つ(キーか512msのタイマで起きる)
            self.halted = True
        self.lcd_dirty = True

    def xin(self, cycle: int) -> int:
        """カセットの入力(Xin)。テープがなければ0"""
        tape = self.tape
        return tape.level(cycle) if tape is not None else 0

    def test(self, n: int) -> int:
        """TEST命令。タイマのフラグ(ビット0が512ms、ビット1が2ms)は間隔ごとに立ち、読むと消える"""
        t = self.test_bits() & n
        if t & 0x01:
            self.t512 = 0
        if t & 0x02:
            self.t2ms = 0
        if n & 0x80 and self.xin(self.cpu.cycles):  # テープは読むときだけ見る
            t |= 0x80
        return t

    def test_bits(self) -> int:
        t = 0
        if self.t512:
            t |= 0x01
        if self.t2ms:
            t |= 0x02
        if self.brk:
            t |= 0x08
        if self.reset_key:  # 裏のRESETボタン
            t |= 0x40
        return t

    # ---- 実行 ----
    def run(
        self, cycles: int, guard: bytearray | None = None, seen: bytearray | None = None
    ) -> bool:
        """cyclesぶん動かし、2msごとにタイマを進める。guardとseenはSC61860.runと同じで、
        guardの番地で止まったらTrueを返す"""
        cpu = self.cpu
        cpu.trapped = False
        while cycles > 0:
            if not self.power:
                if self.brk:
                    self.wake()
                else:
                    return False
            chunk = min(cycles, TICK_2MS - self.t2)
            if self.halted and (self.held or self.brk or self.reset_key):
                self.halted = False
            self.reset_at = None
            if self.halted:  # 止まっているあいだは時間だけ進める
                used = chunk
                cpu.cycles += used
            else:
                used = cpu.run(chunk, guard, seen)
            cycles -= used
            # 途中でカウンタをリセットしたときは、リセットのあとの時間だけタイマを進める
            reset = self.reset_at
            self._tick(used if reset is None else cpu.cycles - reset)
            if cpu.trapped:
                return True
        return False

    def _tick(self, used: int) -> None:
        """タイマをusedサイクル進める(2msごとにフラグを立て、256回ごとに512msのフラグを立てる)"""
        self.t2 += used
        while self.t2 >= TICK_2MS:
            self.t2 -= TICK_2MS
            self.t2ms = 1
            self.t512cnt += 1
            if self.t512cnt >= 256:
                self.t512cnt = 0
                self.t512 = 1
                self.halted = False

    def pass_time(self, cycles: int) -> None:
        """命令を実行せずに、cyclesサイクルぶん時間を進める(CPUのサイクルとタイマ)。
        ROMなしでROMのルーチンの働きをまねたときに、そのルーチンにかかる時間として使う"""
        self.cpu.cycles += cycles
        self._tick(cycles)

    # ---- 液晶 ----
    def display_on(self) -> bool:
        return self.power and bool(self.pc_out & 0x01)

    def columns(self, mem: Sequence[int] | None = None) -> list[int]:
        """液晶の列(1バイトが縦の7ドット)を左から並べる。左の12桁はF800から順に、
        残りはF87Bから逆順。2行の液晶では1行目のあとに2行目が続き、各行の左の12桁は
        2000(2行目は2040)から、右の12桁は2800(2840)から順に並ぶ。memを渡すと、
        メモリの代わりにそこから読む(column_addrsが番地を求めるのに使う)"""
        m = self.mem if mem is None else mem
        if self.model.lines == 2:
            out: list[int] = []
            for row in (0x00, 0x40):
                out += m[0x2000 + row : 0x2000 + row + 60]
                out += m[0x2800 + row : 0x2800 + row + 60]
            return out
        n = self.model.cells * 5
        left = min(n, 60)
        return list(m[0xF800 : 0xF800 + left]) + [m[0xF87B - i] for i in range(n - left)]

    def column_addrs(self) -> list[int]:
        """columnsの各列が、液晶RAMのどの番地のバイトか"""
        return self.columns(range(0x10000))

    # PC-1260/1261/1262のBASICがプログラムの先頭(FFの番地)を置くところ。先頭はEQU#で動かせる
    PROG_START_PTR = 0x6619

    def program_start(self) -> int:
        """いまのBASICのプログラムの先頭(FFの番地)"""
        if self.model.lines == 2:
            a = self._word(self.PROG_START_PTR)
            lo, hi = self.model.ram
            if lo <= a < hi:
                return a
        return self.model.prog_start

    def _word(self, a: int) -> int:
        return self.mem[a] | self.mem[a + 1] << 8

    def _program_end_ptrs(self) -> tuple[int, ...]:
        return (self.model.prog_end_ptr,)

    def _program_top(self) -> int:
        return self.model.prog_top

    def program_room(self) -> int:
        """BASICのプログラムに使えるバイト数(中間コードの行の並びの長さで)"""
        return self._program_top() - self.program_start() - 1

    def store_program(self, data: bytes) -> bool:
        """中間コードの行の並び(先頭と終わりのFFを除く。basictext.encode_program)を、
        いまのプログラムとして置く。入りきらなければ何もせずFalse"""
        start = self.program_start()
        end = start + 1 + len(data)
        if end > self._program_top():
            return False
        self.mem[start + 1 : end] = data
        self.mem[end] = 0xFF
        for p in self._program_end_ptrs():
            self.mem[p], self.mem[p + 1] = end & 0xFF, end >> 8
        return True

    def symbols(self) -> set[str]:
        m = self.mem
        return {name for name, (a, bit) in self.model.symbols.items() if m[a] & bit}

    def power_off(self, limit: float = 3.0) -> bool:
        """スイッチをOFFにして、ROMが電源を切るまで動かす。切れたらTrue。
        ROMは電源を切るときに内部RAMに印を書き、次に入れたときにその印でRAMが
        生きているかを見るので、ROMに切らせないとプログラムが消える"""
        self.mode = "OFF"
        spent = 0
        while self.power and spent < limit * CLOCK:
            if spent == CLOCK:  # 1秒たっても切れなければBRKで止めてみる
                self.brk = True
            if spent == CLOCK + CLOCK // 10:
                self.brk = False
            self.run(CLOCK // 50)
            spent += CLOCK // 50
        self.brk = False
        return not self.power

    # ---- 状態の保存(どこでもセーブ) ----
    # RAMと液晶RAM、CPUのレジスタ、ポート、タイマ、スイッチを1つのJSONに書く
    STATE_FORMAT = 1
    STATE_FIELDS: tuple[str, ...] = ("mode", "pa", "pb", "pc_out", "pf", "power", "halted",
                                     "t2", "t2ms", "t512", "t512cnt")  # fmt: skip

    def _state_key(self) -> dict:
        """読み込む本体と合っているかを見る項目"""
        return {"model": self.model.name, "ram": list(self.model.ram)}

    def _rom_digest(self) -> str:
        ba, bs = self.model.bas_addr, self.model.bas_size
        rom = bytes(self.mem[0:0x2000]) + bytes(self.mem[ba : ba + bs])
        return hashlib.sha1(rom).hexdigest()

    def snapshot(self) -> dict:
        """いまの状態(RAM、CPU、ポート、タイマ)。restoreかsave_stateにわたす"""
        state = {"format": self.STATE_FORMAT, **self._state_key(), "rom": self._rom_digest()}
        state["machine"] = {name: getattr(self, name) for name in self.STATE_FIELDS}
        state["cpu"] = self.cpu.state()
        state["mem"] = base64.b64encode(bytes(self.mem)).decode("ascii")
        return state

    def save_state(self, path: str, extra: dict | None = None) -> None:
        """いまの状態をpathに書く。先に別の名前で書いてから置き換え、前の状態はpath.bakに残す。
        extraは本体の外の情報(読み込んだプログラムなど)で、load_stateがそのまま返す"""
        state = self.snapshot()
        if extra is not None:
            state["app"] = extra
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        if os.path.exists(path):
            os.replace(path, path + ".bak")
        os.replace(tmp, path)

    def load_state(self, path: str) -> dict | None:
        """save_stateで書いた状態に戻し、一緒に書いたextraを返す(なければNone)。読めないか、
        ほかの機種の状態ならValueError(ファイルがなければOSError)。どこかおかしければ、
        いまの状態には手を付けない"""
        with open(path, encoding="utf-8") as f:
            try:
                state = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(tr("状態のファイルとして読めません({error})", error=e)) from e
        self.restore(state)
        extra = state.get("app")
        return extra if isinstance(extra, dict) else None

    def restore(self, state: object) -> None:
        """snapshotで取った状態に戻す。合わなければValueErrorで、いまの状態には手を付けない"""
        if not isinstance(state, dict) or state.get("format") != self.STATE_FORMAT:
            raise ValueError(tr("状態のファイルとして読めません"))
        key = self._state_key()
        got = {k: state.get(k) for k in key}
        ram, want = got.pop("ram"), key.pop("ram")
        # RAMの終わりは保存したときのものに動かす(# ram: のプログラムを読み込む前に戻すなど)
        top = ram[1] if isinstance(ram, list) and len(ram) == 2 and ram[0] == want[0] else None
        if got != key or type(top) is not int or not self.ram_top_ok(top):
            raise ValueError(tr("ほかの機種(PC-{model})の状態です", model=state.get("model")))
        if "rom" in state and state["rom"] != self._rom_digest():
            raise ValueError(tr("ROMが保存したときと違います"))
        try:
            mem = base64.b64decode(state.get("mem", ""), validate=True)
        except (TypeError, ValueError):
            mem = b""
        if len(mem) != len(self.mem):
            raise ValueError(tr("メモリの大きさが違います"))
        fields = state.get("machine")
        if not isinstance(fields, dict):
            raise ValueError(tr("本体の状態がありません"))
        values = {name: self._check_field(name, fields.get(name)) for name in self.STATE_FIELDS}
        cpu = self.cpu.check_state(state.get("cpu"))
        # ここから先は失敗しない
        self.set_ram_top(top)
        for lo, hi in self._writable_ranges():
            self.mem[lo:hi] = mem[lo:hi]
        for name, v in values.items():
            setattr(self, name, v)
        self.cpu.set_state(cpu)
        self.held.clear()
        self.brk = self.reset_key = False
        self.tape = None
        self.sound_events.clear()
        self.lcd_dirty = True

    PORTS = ("pa", "pb", "pc_out", "pf", "ko")

    def _check_field(self, name: str, v: object):
        now = getattr(self, name)
        if name == "mode":
            ok = v in self.model.modes
        elif type(now) is bool:
            ok = type(v) is bool
        else:
            ok = type(v) is int and v >= 0 and (name not in self.PORTS or v <= 0xFF)
        if not ok:
            raise ValueError(tr("本体の{name}がおかしい値です", name=name))
        return v

    def _writable_ranges(self) -> list[tuple[int, int]]:
        return [self.model.ram, *self.model.lcd]

    # ---- RAMの保存 ----
    def _saved_parts(self) -> list[tuple[int, int] | None]:
        """保存する範囲の並び。NoneはCPUの内部RAM。2行以上の液晶の機種では、ROMが液晶RAMの
        表示に使わない部分にも値を置くので、液晶RAMも保存する"""
        parts: list[tuple[int, int] | None] = [self.model.ram, None]
        if self.model.lines > 1:
            parts += self.model.lcd
        return parts

    def save_ram(self, path: str) -> None:
        with open(path, "wb") as f:
            for part in self._saved_parts():
                f.write(self.cpu.ram if part is None else self.mem[part[0] : part[1]])

    def load_ram(self, path: str) -> bool:
        """save_ramで書いたファイルを読む。前の版が書いた、途中の範囲までのファイルも読める"""
        try:
            data = open(path, "rb").read()
        except OSError:
            return False
        sizes = [len(self.cpu.ram) if p is None else p[1] - p[0] for p in self._saved_parts()]
        ends = [sum(sizes[: k + 1]) for k in range(len(sizes))]
        if len(data) not in ends:
            return False
        pos = 0
        for part, size in zip(self._saved_parts(), sizes, strict=True):
            if pos >= len(data):
                break
            if part is None:
                self.cpu.ram[:] = data[pos : pos + size]
            else:
                self.mem[part[0] : part[1]] = data[pos : pos + size]
            pos += size
        self.lcd_dirty = True
        return True


# ---- PC-1350 ----
# キーの配置。("K", n, ビット)は、7E00-7FFFに書くストローブ(KO1〜KO7)のビットnを出したときに
# INAに出るビット。("A", n, ビット)は、IAのビットnとそのビットの2本の線のあいだのキー
KEYS_1350 = {
    ")": ("K", 0, 0x01),
    ":": ("K", 0, 0x02),
    ";": ("K", 0, 0x04),
    ",": ("K", 0, 0x08),
    "KANA": ("K", 0, 0x10),
    "DEF": ("K", 0, 0x20),
    "SHIFT": ("K", 0, 0x40),
    "(": ("K", 1, 0x01),
    "/": ("K", 1, 0x02),
    "*": ("K", 1, 0x04),
    "-": ("K", 1, 0x08),
    "Z": ("K", 1, 0x10),
    "A": ("K", 1, 0x20),
    "Q": ("K", 1, 0x40),
    "9": ("K", 2, 0x01),
    "6": ("K", 2, 0x02),
    "3": ("K", 2, 0x04),
    "+": ("K", 2, 0x08),
    "X": ("K", 2, 0x10),
    "S": ("K", 2, 0x20),
    "W": ("K", 2, 0x40),
    "8": ("K", 3, 0x01),
    "5": ("K", 3, 0x02),
    "2": ("K", 3, 0x04),
    ".": ("K", 3, 0x08),
    "C": ("K", 3, 0x10),
    "D": ("K", 3, 0x20),
    "E": ("K", 3, 0x40),
    "7": ("K", 4, 0x01),
    "4": ("K", 4, 0x02),
    "1": ("K", 4, 0x04),
    "0": ("K", 4, 0x08),
    "V": ("K", 4, 0x10),
    "F": ("K", 4, 0x20),
    "R": ("K", 4, 0x40),
    "UP": ("K", 5, 0x01),
    "DOWN": ("K", 5, 0x02),
    "LEFT": ("K", 5, 0x04),
    "RIGHT": ("K", 5, 0x08),
    "B": ("K", 5, 0x10),
    "G": ("K", 5, 0x20),
    "T": ("K", 5, 0x40),
    "INS": ("A", 0, 0x04),
    "DEL": ("A", 0, 0x08),
    "N": ("A", 0, 0x10),
    "H": ("A", 0, 0x20),
    "Y": ("A", 0, 0x40),
    "MODE": ("A", 1, 0x08),
    "M": ("A", 1, 0x10),
    "J": ("A", 1, 0x20),
    "U": ("A", 1, 0x40),
    "CLS": ("A", 2, 0x08),
    "SPC": ("A", 2, 0x10),
    "K": ("A", 2, 0x20),
    "I": ("A", 2, 0x40),
    "ENTER": ("A", 3, 0x10),
    "L": ("A", 3, 0x20),
    "O": ("A", 3, 0x40),
    "=": ("A", 4, 0x20),
    "P": ("A", 4, 0x40),
}
KEYS_1350["SHIFT2"] = KEYS_1350["SHIFT"]  # 右上のSHIFTも同じ線とした

# 液晶の左端の表示記号(783Cのビット)
# PC-1350の表示記号(783C)。ビット2は印字モード(SHIFT+ENTERのP↔NP)の印だが、液晶に記号は
# ない(ht-deko.comのPC-1350の頁も「モードを示すシンボルがない」としている)。787Cのビット0〜2
# (DEGREE・RADIAN・GRAD)も同じで、液晶に記号はない
SYMBOLS_1350 = {
    "SHIFT": (0x783C, 0x01),
    "DEF": (0x783C, 0x02),
    "RUN": (0x783C, 0x10),
    "PRO": (0x783C, 0x20),
    "KANA": (0x783C, 0x40),
    "SML": (0x783C, 0x80),
}

# 液晶RAM。30列ずつの5つの区画が横に並び、各区画は上から8ドットずつの4段。
# 段の頭は区画の頭から+00、+40、+1E、+5E
LCD_BLOCKS_1350 = (0x7000, 0x7200, 0x7400, 0x7600, 0x7800)
LCD_BANDS_1350 = (0x00, 0x40, 0x1E, 0x5E)

# RAMカードの大きさ(KB)ごとのRAMの範囲。8KBのカード(CE-201M)は2000-3FFFにも見える
CARDS_1350 = {0: None, 8: (0x4000, 0x6000), 16: (0x2000, 0x6000)}


class PC1350(PC1251):
    """PC-1350。CPU、タイマ、ブザー、カセットのポートはPC-1251と同じ。RUNとPROはMODEキーで
    切り替わり(ROMが覚えている)、スイッチは電源だけなので、self.modeはONかOFF"""

    def __init__(
        self,
        cpu_rom: bytes | None = None,
        bas_rom: bytes | None = None,
        model: str = "1350",
        card: int = 0,
        overseas: bool = False,
    ):
        super().__init__(cpu_rom, bas_rom, model)
        self.card = card
        # 仕向けの配線。ROMは起動のときにKO7を出してINAのビット7を読み、立っていれば輸出向け
        # (英小文字と\)、立っていなければ国内向け(カナと¥)として動く
        self.overseas = overseas
        # RAMカードを差すと、RAMはカードの頭から本体の終わりまで続き、プログラムはカードの頭+30hから
        lo = (CARDS_1350[card] or self.model.ram)[0]
        self.model = replace(self.model, ram=(lo, self.model.ram[1]), prog_start=lo + 0x30)
        for a in range(lo, 0x6000):
            self.wmask[a] = 1
        for a in range(0x2000, lo):  # 何もつながっていない番地(PC-1261と同じ扱い)
            self.mem[a] = a >> 8
        self.ko = 0  # 7E00-7FFFに書いたストローブ(KO1〜KO7)
        self.mode = "ON"

    # ---- バス ----
    def read(self, a: int) -> int:
        if 0x7E00 <= a < 0x8000:
            return self.ko
        if self.card == 8 and 0x2000 <= a < 0x4000:
            a += 0x2000
        return self.mem[a]

    def writable(self, a: int) -> bool:
        if not 0 <= a < 0x10000 or 0x7E00 <= a < 0x8000:
            return False
        if self.card == 8 and 0x2000 <= a < 0x4000:
            a += 0x2000
        return bool(self.wmask[a])

    def write(self, a: int, v: int) -> None:
        if 0x7E00 <= a < 0x8000:
            self.ko = v
            return
        if self.card == 8 and 0x2000 <= a < 0x4000:
            a += 0x2000
        if self.wmask[a]:
            if 0x7000 <= a < 0x7A00:
                self.lcd_dirty = True
                if self.lcd_trace is not None and self.mem[a] != v:
                    self.lcd_trace.append((self.cpu.cycles, a, self.mem[a], v))
            self.mem[a] = v

    def in_a(self) -> int:
        """IAに出した値に、押されたキーのビットを重ねる。IAの2本の線のあいだのキーは、
        どちらの線を出しても他方に出る"""
        pa, ko = self.pa, self.ko
        v = pa
        if self.overseas and ko & 0x40:
            v |= 0x80
        for k in self.held:
            key = KEYS_1350.get(k)
            if key is None:
                continue
            kind, n, bit = key
            if kind == "K":
                if ko & (1 << n):
                    v |= bit
            elif pa & (1 << n):
                v |= bit
            elif pa & bit:
                v |= 1 << n
        return v

    def in_b(self) -> int:
        if self.printer is None:
            return self.pb
        # プリンタの応答(ビット6)は、命令を送るあいだ(Cのビット4)は合図(Fのビット2)の逆、
        # 字を送るあいだは合図のまま
        ack = (self.pf >> 2 ^ self.pc_out >> 4) & 1
        return (self.pb & 0x3F) | ack << 6

    def out_f(self, v: int) -> None:
        # プリンタへ: Fのビット1がデータ、ビット2が合図
        if self.printer is not None and v & 0x04 and not self.pf & 0x04:
            self.printer.bit(v >> 1, command=bool(self.pc_out & 0x10))
        self.pf = v

    # ---- 液晶 ----
    def columns(self, mem: Sequence[int] | None = None) -> list[int]:
        """上の段から順に、各段の左から150列ぶんの液晶RAM(1バイトが縦8ドット)"""
        m = self.mem if mem is None else mem
        out: list[int] = []
        for band in LCD_BANDS_1350:
            for blk in LCD_BLOCKS_1350:
                out += m[blk + band : blk + band + 30]
        return out

    def symbols(self) -> set[str]:
        m = self.mem
        return {name for name, (a, bit) in SYMBOLS_1350.items() if m[a] & bit}

    def run(
        self, cycles: int, guard: bytearray | None = None, seen: bytearray | None = None
    ) -> bool:
        if self.mode == "OFF":  # スイッチが切れているあいだはONキーでも入らない
            self.power = False
            return False
        return super().run(cycles, guard, seen)

    # ROMの電源を切るルーチン。内部RAMの20hに5A、21h〜27hにA5の印を書いてから電源を切る
    OFF_ROUTINE = 0x04BF
    OFF_ROUTINE_CODE = bytes.fromhex("f4eef4ad")

    def power_off(self, limit: float = 1.0) -> bool:
        """電源スイッチをOFFにする。プログラムが残るように、ROMの電源を切るルーチンを走らせる
        (スイッチがROMに知らせる仕組みは再現していない)。ルーチンが見つからなければ印だけ書く"""
        cpu = self.cpu
        if self.power:
            if bytes(self.mem[self.OFF_ROUTINE : self.OFF_ROUTINE + 4]) == self.OFF_ROUTINE_CODE:
                cpu.pc = self.OFF_ROUTINE
                self.halted = False
                spent = 0
                while self.power and spent < limit * CLOCK:
                    super().run(CLOCK // 100)
                    spent += CLOCK // 100
            if self.power:
                cpu.ram[0x20] = 0x5A
                cpu.ram[0x21:0x28] = b"\xa5" * 7
        self.mode = "OFF"
        self.power = False
        return True

    def power_on(self) -> None:
        """電源スイッチをONにする"""
        self.mode = "ON"
        self.wake()

    STATE_FIELDS: tuple[str, ...] = PC1251.STATE_FIELDS + ("ko",)

    def _state_key(self) -> dict:
        return {**super()._state_key(), "overseas": self.overseas}

    # BASICは、プログラムの終わりの番地をRAMの頭(プログラムの30h手前)から9バイト目にも、
    # プログラムに使える上限を6F07に置く
    PROG_TOP_PTR = 0x6F07

    def _program_end_ptrs(self) -> tuple[int, ...]:
        return (self.model.prog_end_ptr, self.model.ram[0] + 9)

    def _program_top(self) -> int:
        return self._word(self.PROG_TOP_PTR)
