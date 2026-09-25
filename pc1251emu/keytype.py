"""文字列をPC-1251のキー操作に直す(貼り付けと自動入力用)"""

# SHIFTを押してから打つ記号。MAMEのキー名(下段がSHIFTのときの文字)による。
SHIFTED = {
    ">": "-",
    "<": "*",
    "^": "/",
    "(": "DOWN",
    "#": "E",
    "!": "Q",
    "@": "3",
    '"': "W",
    ")": "UP",
    "$": "R",
    ";": "P",
    "%": "T",
    ",": "O",
    "&": "Y",
    "?": "U",
    ":": "I",
    "√": ".",
    "π": "0",
}
PLAIN = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-*/=.")


def keys_for(text: str) -> list[list[str]]:
    """1文字ごとに押すキーの列。[["SHIFT"], ["I"]]のように、1打鍵ずつ並べる。"""
    out: list[list[str]] = []
    for ch in text.upper():
        if ch == "\n":
            out.append(["ENTER"])
        elif ch == " ":
            out.append(["SPC"])
        elif ch in PLAIN:
            out.append([ch])
        elif ch in SHIFTED:
            out.append(["SHIFT"])
            out.append([SHIFTED[ch]])
        # それ以外の文字はPC-1251のキーにないので捨てる
    return out
