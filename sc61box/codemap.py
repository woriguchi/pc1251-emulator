"""マシン語の作業欄の逆アセンブルで、RAMの番地ごとに命令かデータかを見分ける

番地ごとに、命令の頭(head)、命令の続きのバイト(body)、データ(data)のどれかと、そう決めた
理由を持つ。理由は次の4つ。

- executed: 作業欄を使っているあいだに、CPUがその番地から命令を読んだ
- flow: 入口(開始番地、BASICのCALLの番地、止める所、実行した命令、DTCの表の行き先)から
  命令の流れをたどって着いた。ジャンプと呼び出しの先、条件つきのジャンプは両方の先、
  呼び出しのあと(呼んだ先から戻るものとみる)をたどり、RTNと条件なしのジャンプで止める
- guessed: どこからもたどれないので、形から推し量った。文字が並んでいる、00かFFが並んで
  いる、命令として読むとない命令かRAMとROMの外へ飛ぶ命令がある、のどれかならデータ。
  ほかは命令として読む(どれでもないので、作業欄では暗く出す)
- user: 自分で決めた(作業欄の右クリックで、その番地からデータ・命令にした)

推し量るのは、作業欄で書いた範囲(書き出す範囲)の中だけ。流れはRAMの中ならどこでもたどる。
データは4バイトずつの行にする(DTCの表は表の行ごと)。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from . import disasm

# 番地ごとの種類
NONE, HEAD, BODY, DATA, DATA_BODY = 0, 1, 2, 3, 4  # DATAはデータの行の頭
# 理由(細かく分けて持ち、外へはexecuted・flow・guessed・userの4つで見せる)
EXEC, FLOW, TABLE, GUESS, TEXT, FILL, JUNK, USER, NOEND = 1, 2, 3, 4, 5, 6, 7, 8, 9
REASONS = {EXEC: "executed", FLOW: "flow", TABLE: "flow", GUESS: "guessed", TEXT: "guessed",
           FILL: "guessed", JUNK: "guessed", USER: "user", NOEND: "guessed"}  # fmt: skip
KINDS = {HEAD: "head", BODY: "body", DATA: "data", DATA_BODY: "data"}

DATA_ROW = 4  # データの1行のバイト数
TEXT_MIN = 5  # 文字がこのバイト数以上並べば文字列とみる
FILL_MIN = 4  # 00かFFがこのバイト数以上並べば埋め草とみる
MARK_SPAN = 256  # 書いた範囲の外で、データの指定が続く長さの上限

JUMPS = ("JP", "JR")  # 条件なしのジャンプ(先だけをたどる。条件つきは両方をたどる)


def printable(v: int) -> bool:
    return 0x20 <= v < 0x7F


class CodeMap:
    """番地ごとの種類と理由。build()で作る"""

    def __init__(self, read: Callable[[int], int]) -> None:
        self.read = read
        self.kind = bytearray(0x10000)
        self.why = bytearray(0x10000)
        self.rows: dict[int, disasm.Ins] = {}  # DTCの表の行(番地: 行)

    # ---- 見る ----
    def state(self, a: int) -> tuple[str, str]:
        """番地aの(種類, 理由)。種類はhead・body・data、理由はexecuted・flow・guessed・user。
        見分けていない番地は("", "")。guessedの命令(headかbody)は、命令かどうかわからないもの"""
        k = self.kind[a & 0xFFFF]
        if not k:
            return "", ""
        return KINDS[k], REASONS[self.why[a & 0xFFFF]]

    def start_of(self, a: int) -> int | None:
        """番地aを含む行(命令かデータの行)の頭。見分けていない番地ならNone"""
        a &= 0xFFFF
        for back in range(DATA_ROW + 1):
            b = (a - back) & 0xFFFF
            k = self.kind[b]
            if k in (HEAD, DATA):
                return b
            if k not in (BODY, DATA_BODY):
                return None
        return None

    def line_at(self, a: int) -> disasm.Ins | None:
        """番地aから始まる行。aが行の頭でなければNone"""
        a &= 0xFFFF
        k = self.kind[a]
        if k == HEAD:
            return disasm.decode(self.read, a)
        if k != DATA:
            return None
        if a in self.rows:
            return self.rows[a]
        n = 1
        while n < DATA_ROW and self.kind[(a + n) & 0xFFFF] == DATA_BODY:
            n += 1
        return data_line(self.read, a, n)

    def is_start(self, a: int) -> bool:
        return self.kind[a & 0xFFFF] in (HEAD, DATA)

    # ---- 作る ----
    def _put_data(self, lo: int, hi: int, why: int) -> None:
        """lo〜hi-1をデータにする(4バイトずつの行)"""
        for a in range(lo, hi):
            self.kind[a] = DATA if (a - lo) % DATA_ROW == 0 else DATA_BODY
            self.why[a] = why

    def _free(self, a: int, size: int) -> bool:
        return all(not self.kind[(a + i) & 0xFFFF] for i in range(size))

    def _put_ins(self, ins: disasm.Ins, why: int) -> None:
        a = ins.addr
        self.kind[a], self.why[a] = HEAD, why
        for i in range(1, ins.size):
            b = (a + i) & 0xFFFF
            if not self.kind[b]:
                self.kind[b], self.why[b] = BODY, why

    def _put_row(self, row: disasm.Ins, why: int) -> None:
        """DTCの表の1行(DB)をデータの行にする"""
        self.rows[row.addr] = row
        for i in range(row.size):
            b = (row.addr + i) & 0xFFFF
            self.kind[b], self.why[b] = (DATA if i == 0 else DATA_BODY), why

    def _put_table(self, at: int, rows: int, why: int) -> list[disasm.Ins]:
        """DTCの次の番地atからの表をデータの行にする。表の行を返す(置けなければ空)"""
        table = disasm.table(self.read, at, rows)
        if not self._free(at, 3 * rows + 2):
            return []
        for row in table:
            self._put_row(row, why)
        return table

    def _empty(self, a: int) -> bool:
        """aからFILL_MINバイトが、00かFFばかりか"""
        vals = {self.read((a + i) & 0xFFFF) for i in range(FILL_MIN)}
        return vals in ({0x00}, {0xFF})

    def follow(self, entries: Iterable[tuple[int, int]], in_ram: Callable[[int], bool]) -> None:
        """入口(番地, 理由)から命令の流れをたどる。たどった命令の理由は、入口の命令が入口の
        理由、続く命令はflow(実行した命令はexecutedのまま)"""
        todo: list[tuple[int, int, int | None]] = [(a, why, None) for a, why in entries]
        done: set[int] = set()
        while todo:
            a, why, rows = todo.pop()
            a &= 0xFFFF
            if a in done or not in_ram(a):
                continue
            ins = disasm.decode(self.read, a)
            if why == FLOW and (ins.name == "???" or self._empty(a)):
                continue  # ない命令や、何も書いていないところには、流れが着かないものとみる
            if self.kind[a] == HEAD:
                pass  # 実行した命令か、自分で決めた命令
            elif not self._free(a, ins.size):
                continue  # データか、ほかの命令の途中に重なる
            else:
                self._put_ins(ins, why)
            done.add(a)
            nxt = (a + ins.size) & 0xFFFF
            name, t = ins.name, ins.target
            if name == "RTN":
                continue
            if t is not None:
                # ジャンプと呼び出しの先。PTCでは、表の行き先から戻ってくる番地
                todo.append((t, FLOW, None))
            if name in JUMPS:
                continue
            if name == "PTC":
                rows = self.read((a + 1) & 0xFFFF)
            elif name == "DTC":
                n = rows if rows is not None else disasm.find_ptc(self.read, a)
                if n is not None:
                    for row in self._put_table(nxt, n, TABLE):
                        if row.target is not None:
                            todo.append((row.target, FLOW, None))
                continue  # 表の行の数がわからなければ、その先はたどらない
            todo.append((nxt, FLOW, rows))

    def guess(self, lo: int, hi: int, target_ok: Callable[[int], bool]) -> None:
        """lo〜hi-1のうち、まだ見分けていないところを形から推し量る"""
        a = lo
        while a < hi:
            if self.kind[a]:
                a += 1
                continue
            b = a
            while b < hi and not self.kind[b]:
                b += 1
            self._guess_gap(a, b, target_ok)
            a = b

    def _guess_gap(self, lo: int, hi: int, target_ok: Callable[[int], bool]) -> None:
        """見分けていないひと続きlo〜hi-1。文字と埋め草の並びを先にデータにし、残りを
        命令として読んでみる"""
        rest = lo
        a = lo
        while a < hi:
            v = self.read(a)
            b = a + 1
            if v in (0x00, 0xFF):
                while b < hi and self.read(b) == v:
                    b += 1
                why = FILL if b - a >= FILL_MIN else 0
            elif printable(v):
                while b < hi and printable(self.read(b)):
                    b += 1
                text = [self.read(i) for i in range(a, b)]
                letters = sum(chr(c).isalnum() for c in text)
                # 英数字が半分以上で、3種類以上の字(同じ字の並びは、字の形の点などが多い)
                ok = letters * 2 >= len(text) and len(set(text)) >= 3
                # 終わりの00か0Dまで文字列に入れる
                if b < hi and self.read(b) in (0x00, 0x0D):
                    b += 1
                why = TEXT if b - a >= TEXT_MIN and ok else 0
            else:
                why = 0
            if why:
                if rest < a:
                    self._guess_code(rest, a, target_ok)
                self._put_data(a, b, why)
                rest = b
            a = b
        if rest < hi:
            self._guess_code(rest, hi, target_ok)

    def _guess_code(self, lo: int, hi: int, target_ok: Callable[[int], bool]) -> None:
        """lo〜hi-1を命令として読んでみる。おかしな命令(ない命令、ありそうにない番地へ飛ぶ
        命令、終わりをまたぐ命令)のない並びのうち、RTNか条件なしのジャンプで終わるところ
        までを命令(guessed)にする。そのあとから、おかしな命令(なければ終わり)まではデータ。
        終わりの00・FFは、命令のあとの埋め草とみる"""
        end = hi
        while end > lo and self.read(end - 1) in (0x00, 0xFF):
            end -= 1
        if end < hi:
            self._put_data(end, hi, FILL)
        a = lo
        while a < end:
            seq: list[disasm.Ins] = []
            stop, bad = end, False
            for ins in disasm.lines(self.read, a):
                if not a <= ins.addr < end:
                    break
                t = ins.target if ins.name != "DB" else None
                if (
                    ins.name == "???"
                    or ins.addr + ins.size > end
                    or not (t is None or target_ok(t))
                ):
                    stop, bad = min(ins.addr + ins.size, end), True
                    break
                seq.append(ins)
            last = max((i for i, ins in enumerate(seq) if ins.name in ("RTN", *JUMPS)), default=-1)
            if last >= 0:
                self._put_code(seq[: last + 1])
                a = seq[last].addr + seq[last].size
            else:
                # おかしな命令があるか、RTNか条件なしのジャンプで終わらないまま途切れる
                self._put_data(a, stop, JUNK if bad else NOEND)
                a = stop

    def _put_code(self, seq: list[disasm.Ins]) -> None:
        """命令として読んだ並びを、guessedの命令にする(DTCの表はデータの行)"""
        for ins in seq:
            if ins.name == "DB":  # DTCの表
                self._put_row(ins, GUESS)
            else:
                self._put_ins(ins, GUESS)


def data_line(read: Callable[[int], int], a: int, n: int) -> disasm.Ins:
    """a番地からnバイトのデータの行(「DB 41 42 43 'ABC'」)。どのバイトも文字なら(終わりの
    00か0Dは除いて)文字も出す"""
    vals = [read((a + i) & 0xFFFF) for i in range(n)]
    text = " ".join(f"{v:02X}" for v in vals)
    body = vals[:-1] if n > 1 and vals[-1] in (0x00, 0x0D) else vals
    if all(printable(v) for v in body):
        text += " '" + "".join(chr(v) if printable(v) else "." for v in vals) + "'"
    return disasm.Ins(a, n, "DB", text, None)


def build(
    read: Callable[[int], int],
    *,
    in_ram: Callable[[int], bool],
    target_ok: Callable[[int], bool],
    regions: list[tuple[int, int]],
    entries: Iterable[int],
    executed: Iterable[int],
    marks: dict[int, str],
    ram_end: int,
) -> CodeMap:
    """見分けた結果を作る。regionsは推し量る範囲、entriesは流れをたどる入口(開始番地、
    CALLの番地、止める所)、executedは実行した番地、marksは自分で決めた指定(番地: "data"か
    "code")。指定のデータは、次の指定か実行した番地の手前まで(書いた範囲の外なら
    MARK_SPANバイトまで)"""
    cm = CodeMap(read)
    ran = sorted(a for a in executed if in_ram(a))
    stops = sorted(set(marks) | set(ran))
    for a, what in sorted(marks.items()):
        if what != "data" or not in_ram(a):
            continue
        end = next((hi for lo, hi in regions if lo <= a < hi), min(a + MARK_SPAN, ram_end))
        end = min([end] + [s for s in stops if s > a])
        cm._put_data(a, end, USER)
    for a in ran:
        if not cm.kind[a]:
            cm._put_ins(disasm.decode(read, a), EXEC)
    starts = [(a, USER) for a, what in marks.items() if what == "code"]
    starts += [(a, EXEC) for a in ran]
    starts += [(a, FLOW) for a in entries]
    # 後ろから取り出すので、確かなもの(自分で決めた命令、実行した命令)を後ろに置く
    cm.follow(reversed(starts), in_ram)
    for lo, hi in regions:
        cm.guess(lo, hi, target_ok)
    return cm
