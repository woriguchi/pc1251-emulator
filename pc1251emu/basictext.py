"""RAMにあるBASICのプログラムを文字に戻す(ファイルへの書き出し用)

PC-1251はプログラムを中間コードでRAMに置く。1行は次の形で、B830番地の
FFのあとに並び、最後にまたFFが来る。

    E0+百の位  十と一の位(BCD)  中身…  00

中身は文字コード(英字51h〜6Ah、数字40h〜49hなど。ASCIIではない)と、
命令や関数を表す1バイトの中間コード(7Dh以上)の並び。中間コードと
綴りの対応はBASIC ROMの中の命令の表から読むので、ROMの版が違っても
その版の表がそのまま使われる。空白はROMが打ち込みのときに捨てるので、
書き出すときは読みやすいように命令の前後に補う。
"""

PROG_START = 0xB830

# 中間コードではない文字(ROMに打ち込んで確かめた)
CHARS: dict[int, str] = {
    0x11: " ", 0x12: '"', 0x13: "?", 0x14: "!", 0x15: "#", 0x16: "%", 0x18: "$",
    0x1A: "√", 0x1B: ",", 0x1C: ";", 0x1D: ":", 0x1E: "@", 0x1F: "&",
    0x30: "(", 0x31: ")", 0x32: ">", 0x33: "<", 0x34: "=", 0x35: "+", 0x36: "-",
    0x37: "*", 0x38: "/", 0x39: "^", 0x4A: ".",
}  # fmt: skip
for _i in range(10):
    CHARS[0x40 + _i] = str(_i)
for _i in range(26):
    CHARS[0x51 + _i] = chr(ord("A") + _i)

# 命令の表に載っていない比較の記号
OPERATORS = {0x82: ">=", 0x83: "<=", 0x84: "<>"}

# 前後に空白を置かない中間コード(比較の記号)
_TIGHT = set(OPERATORS)
# 命令のあとにこれらが続くときは、あいだに空白を置く
_SPACE_BEFORE = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"&(-.√')


def keyword_table(mem) -> dict[int, str]:
    """BASIC ROMの命令の表を読む。{中間コード: 綴り}

    表は「上位4ビットが種類・下位4ビットが長さ」の1バイト、綴り、
    中間コード、処理の番地(2バイト)の並び。ROMの中でこの形が
    いちばん長く続くところを表とみなす。
    """
    rom = bytes(mem[0x4000:0x8000])
    best: dict[int, str] = {}
    i = 0
    while i < len(rom):
        table, j = _parse_run(rom, i)
        if len(table) > len(best):
            best = table
        i = j + 1 if table else i + 1
    out = dict(OPERATORS)
    out.update(best)
    return out


def _parse_run(rom: bytes, i: int) -> tuple[dict[int, str], int]:
    table: dict[int, str] = {}
    while i < len(rom):
        n = rom[i] & 0x0F
        if not 1 <= n <= 7 or i + n + 3 >= len(rom):
            break
        name = rom[i + 1 : i + 1 + n]
        ok = all(0x51 <= c <= 0x6A or c in (0x11, 0x18) for c in name)
        if not ok or not 0x51 <= name[0] <= 0x6A:
            break
        token = rom[i + 1 + n]
        if token < 0x7D:
            break
        if 0x11 not in name:  # 空白で埋めた項目(使われていない)は飛ばす
            table.setdefault(token, "".join(CHARS[c] for c in name))
        i += n + 4
    return (table, i) if len(table) >= 20 else ({}, i)


def program_lines(mem, start: int = PROG_START) -> list[tuple[int, bytes]]:
    """(行番号, 中身)の列。プログラムがなければ空"""
    out = []
    a = start + 1 if mem[start] == 0xFF else start
    while a < 0xC800:
        hi = mem[a]
        if hi == 0xFF or not 0xE0 <= hi <= 0xE9:
            break
        lo = mem[a + 1]
        number = (hi & 0x0F) * 100 + (lo >> 4) * 10 + (lo & 0x0F)
        end = a + 2
        while end < 0xC800 and mem[end] != 0x00:
            end += 1
        out.append((number, bytes(mem[a + 2 : end])))
        a = end + 1
    return out


def line_text(body: bytes, keywords: dict[int, str]) -> str:
    """1行の中身を文字にする"""
    out: list[str] = []
    in_string = False
    rest_raw = False  # REMのあとは打ったとおり
    for i, c in enumerate(body):
        if rest_raw or in_string or c < 0x7D:
            if c == 0x12 and not rest_raw:
                in_string = not in_string
            out.append(CHARS.get(c, "?"))
            continue
        word = keywords.get(c)
        if word is None:
            out.append("?")
            continue
        if c in _TIGHT:
            out.append(word)
            continue
        if out and (out[-1][-1].isalnum() or out[-1][-1] in '")$'):
            out.append(" ")
        out.append(word)
        nxt = body[i + 1] if i + 1 < len(body) else None
        if nxt is not None and (nxt >= 0x7D or CHARS.get(nxt, "?") in _SPACE_BEFORE):
            out.append(" ")
        if word == "REM":
            rest_raw = True
    return "".join(out).rstrip()


def program_text(mem, keywords: dict[int, str] | None = None) -> str:
    """RAMのプログラムをBASICの文字にする(1行ずつ改行で区切る)"""
    kw = keywords if keywords is not None else keyword_table(mem)
    return "".join(f"{n} {line_text(body, kw)}\n" for n, body in program_lines(mem))
