"""プリンタ(CE-126Pにあたるもの。どの機種にもつながる)

本体は11ピンの端子から、1バイトを下位のビットから1ビットずつ送る。データの線にビットを
出してから合図の線を上げ、プリンタが応答の線(INBのビット6)を動かすのを待つ。
プリンタはこの合図の立ち上がりでデータの線を読む。最初の1バイトは命令(LPRINTなど)で、
そのあとに字のコードが続き、0Dで改行する。

字の形はプリンタが持っている。コードは00〜FFのすべてに字があり、20〜7EはおおむねASCII、
A1〜DFは半角カナ、ほかに記号、小さい数字、アクセント付きのラテン文字、年月日円などがある
(assets/printer_font.txt)。本体のROMは、送る前に自分の字のコードをプリンタのコードに
置き換える。PC-1251・PC-1245のBASICから送れるのは01〜0C、0E、0F、20〜60だけで、残りの字は
マシン語で送ったときに出る。

紙の幅や印字の遅さ、紙送りのキーは再現していない。
"""

import os

FONT_FILE = os.path.join(os.path.dirname(__file__), "assets", "printer_font.txt")

# 印字を文字列にするときの字(試験や書き出し用)。字の形とは別に、意味の近いUnicodeの字を当てる
# 00〜1F。00、08、0A、0Dは空き。07は上に線のあるm
_LOW = (*" ≠Σℂℙ𝔼ₘ", "m̄", *" Ⅱ ◣◿ θ⇒+−×÷=◇≧‐√π⥮→←↑↓↻")
_HIGH = {
    0x5B: "√",
    0x5C: "¥",
    0x5D: "π",
    0x60: "E",  # 指数のE(PC-1251・PC-1245は1E5のEをこれで送る)
    0x7F: "▒",
    0x8D: "♪",
    0x8E: "㏂",
    0x8F: "㏘",
    0xA0: " ",
}
_SMALL = "⁰¹²³⁴⁵⁶⁷⁸⁹"  # 80〜89。8A〜8Cは10〜12
_SIGNS = ("⁺", "⁻", "×", "÷", "/", "⁻", "⁻¹", "_", "⁽", "⁾", "ˣ", "␣", "x̄", "¬", '"', "¯")  # 90〜9F
_LATIN = "ÄËÜÏÖÀÈÙÂÊÛÎÔÉÇß"  # E0〜EF
_LAST = "0年月日円♠♥♦♣αβγσλδ£"  # F0〜FF(F0は斜線のある0)


def char(code: int) -> str:
    """プリンタのコードを、意味の近い字にする"""
    if code < 0x20:
        return _LOW[code]
    if code in _HIGH:
        return _HIGH[code]
    if code < 0x7F:
        return chr(code)
    if code < 0x8A:
        return _SMALL[code - 0x80]
    if code < 0x8D:
        return "¹" + _SMALL[code - 0x8A]
    if code < 0xA0:
        return _SIGNS[code - 0x90]
    if code < 0xE0:
        return bytes([code]).decode("cp932")
    if code < 0xF0:
        return _LATIN[code - 0xE0]
    return _LAST[code - 0xF0]


def load_font(path: str = FONT_FILE) -> dict[int, bytes]:
    """字の形の表を読む。{コード: 5列(1バイトが縦の1列、ビット0が上)}"""
    font: dict[int, bytes] = {}
    codes: list[int] = []
    rows: list[list[str]] = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            words = raw.split()
            if not words or raw.startswith(";"):
                continue
            if all(set(w) <= {"#", "."} for w in words):
                rows.append(words)
                if len(rows) == 7:
                    for k, code in enumerate(codes):
                        cols = bytes(
                            sum(1 << j for j in range(7) if rows[j][k][i] == "#") for i in range(5)
                        )
                        font[code] = cols
                    rows = []
            else:
                codes = [int(w, 16) for w in words]
    return font


# PC-1350は数字の0をF0(斜線のある0)で、英字のOを30で送る。PC-1350につなぐプリンタは
# 30を斜線のない形で打つと考え、30はOとして扱う
SWAP_1350 = {0x30: 0x4F}
# PC-1350は行の頭ごとに、字のコードと同じ送り方で0F(最初の行)か0E(次の行から)を送る。
# 印字モード(SHIFT+ENTER)では、行の終わり(0Dのあと)にも0Eを送るので、次の行の頭には0Eと0Fが
# 続く。字ではないので、行の頭に続くあいだは打たない(行の途中なら字として打つ)
LEAD_1350 = frozenset((0x0E, 0x0F))
# PC-1251・PC-1245のLLISTは、プログラムの行を打ち終わるごとに03を1つ送る。これも同じに扱う
LEAD_1251 = frozenset((0x03,))


class Printer:
    def __init__(
        self, swap: dict[int, int] | None = None, lead: frozenset[int] = frozenset()
    ) -> None:
        self.swap = swap or {}
        self.lead = lead
        self.lines: list[bytes] = []  # 印字し終わった行のコード(行末の空白は落とす)
        self.line = bytearray()  # 印字している途中の行
        self.count = 0  # 印字し終わった行の数(消したあとも数える)
        self.changes = 0  # 印字が変わった回数(字を打つか改行するたびに増える)
        self.at_start = True  # まだ行の字を受け取っていないか(leadのコードなら打たない)
        self._bits = 0
        self._n = 0

    def restart(self) -> None:
        """1バイトの途中で送り方が変わったときに、読みかけのビットを捨てる"""
        self._bits = self._n = 0

    def bit(self, value: int, command: bool) -> None:
        """合図の立ち上がりで、データの線のビットを読む。commandなら命令のバイト"""
        self._bits |= (value & 1) << self._n
        self._n += 1
        if self._n == 8:
            code = self._bits
            self.restart()
            if not command:
                self.put(code)

    def put(self, code: int) -> None:
        if code == 0x0D:
            self.lines.append(bytes(self.line).rstrip(b" "))
            self.line = bytearray()
            self.count += 1
            self.changes += 1
            self.at_start = True
            return
        if self.at_start and code in self.lead:
            return
        self.at_start = False
        self.line.append(self.swap.get(code, code))
        self.changes += 1

    def rows(self) -> list[bytes]:
        """印字した行(途中の行も、空白でなければ含める)"""
        rest = bytes(self.line).rstrip(b" ")
        return self.lines + ([rest] if rest else [])

    def text(self) -> str:
        """印字したものを1つの文字列にする(途中の行も含める)"""
        return "".join("".join(char(c) for c in row).rstrip() + "\n" for row in self.rows())

    def clear(self) -> None:
        self.lines = []
        self.line = bytearray()
        self.at_start = True
