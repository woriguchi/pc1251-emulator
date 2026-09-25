"""液晶RAMを文字に読み戻す(テストと貼り付けの確認用)

BASIC ROMの文字パターン(4504hからの数字・英字)と照らし合わせる。
それ以外の記号は既知のパターンだけを並べる。
"""

_EXTRA = {
    bytes(5): " ",
}


def _table(mem) -> dict[bytes, str]:
    t = dict(_EXTRA)
    base = 0x43C4
    for code in range(0x40, 0x4A):
        t[bytes(mem[base + 5 * code : base + 5 * code + 5])] = chr(ord("0") + code - 0x40)
    for code in range(0x51, 0x6B):
        t[bytes(mem[base + 5 * code : base + 5 * code + 5])] = chr(ord("A") + code - 0x51)
    return t


def lcd_text(machine, unknown: str = "?") -> str:
    t = getattr(machine, "_glyphs", None)
    if t is None:
        t = machine._glyphs = _table(machine.mem)
    cols = machine.columns()
    return "".join(t.get(bytes(cols[i : i + 5]), unknown) for i in range(0, 120, 5))


def learn(machine, text: str) -> None:
    """表示中の文字列から、記号のパターンを覚える(テスト用)"""
    t = getattr(machine, "_glyphs", None) or _table(machine.mem)
    cols = machine.columns()
    for i, ch in enumerate(text[:24]):
        t.setdefault(bytes(cols[5 * i : 5 * i + 5]), ch)
    machine._glyphs = t
