"""キー操作を順に打つ(ファイルや貼り付けの打ち込み、パソコンのキーボード)"""

from collections.abc import Callable

from .keytype import keys_for, keys_for_program
from .machine import CLOCK, PC1251


def _lf(text: str) -> str:
    """改行をLFにそろえる"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


class Typer:
    """キー操作の列を、決まった時間ずつ押して順に届ける。時間はエミュレータのサイクルで数える。

    列の要素は同時に押すキーの名前のリストで、次の印も入る。
    "@MODE:PRO"(スイッチを動かす)、"@IDLE"(ROMが入力待ちに戻るまで待つ)、"@CALL:…"と
    "@WRITE:…"(前の打鍵が終わったところで関数を呼ぶ、ダンプを書く)。
    パソコンのキーボードで押されたキーは、ROMが入力を待っているあいだは印LIVEと押した時刻を
    つけて同じ列に入り、押し続けているあいだは離されるまで押しておく(速く打っても取りこぼさない
    ように1つずつ届ける)。プログラムが動いているあいだは列に入れず、押されたときにすぐ押し、
    離されたときに離す(ゲームの同時押しがそのまま伝わる)。
    """

    DOWN = CLOCK * 70 // 1000
    UP = CLOCK * 60 // 1000
    AFTER_ENTER = CLOCK * 450 // 1000
    MODE_WAIT = CLOCK * 300 // 1000  # スイッチを動かしたあとROMが気づくまで

    LIVE = "@LIVE"
    # パソコンのキーを押しておく時間と次までの間。ROMは離したあと40msほどキーのない時間が
    # ないと次を取りこぼすので、1打鍵に0.1秒かける
    LIVE_DOWN = CLOCK * 50 // 1000
    LIVE_UP = CLOCK * 50 // 1000
    LIVE_MAX_WAIT = CLOCK * 600 // 1000  # これより長く順番を待ったキーは捨てる
    # ROMが入力待ちで止まってからこの時間がたつまでは、パソコンのキーを列に入れて1つずつ届ける
    # (1打鍵を受けたROMが次の入力待ちに戻るまでのあいだに押したキーも、列に入れる)
    WAIT_SPAN = CLOCK * 300 // 1000
    # 列を通さずにすぐ押したキー(動いているプログラムが読むキー)を、押し始めから最低これだけは
    # 押しておく。指で押した時間をそのまま本体に伝え、短すぎてプログラムのキー読みの間隔から
    # 漏れるものだけを補う(長くすると、ゲームで短く押しても自機が止まらなくなる)
    DIRECT_MIN = CLOCK * 25 // 1000

    def __init__(self, machine: PC1251, on_mode=None):
        self.m = machine
        if machine.model.lines == 2 or machine.model.family == "1350":
            # PC-1261などとPC-1350のROMは、押して離すまでが短いと1つおきに取りこぼし、
            # 表示が流れるところでは離している時間も長く要る
            self.DOWN = CLOCK * 100 // 1000
            self.UP = CLOCK * 120 // 1000
            self.LIVE_DOWN = CLOCK * 80 // 1000
            self.LIVE_UP = CLOCK * 120 // 1000
            self.MODE_WAIT = CLOCK * 700 // 1000
        self.mode_key = machine.model.family == "1350"  # RUNとPROをMODEキーで切り替える機種
        if self.mode_key:
            self.UP = CLOCK * 150 // 1000
            self.LIVE_UP = CLOCK * 150 // 1000
        self.on_mode = on_mode  # スイッチを動かす関数
        # 「@WRITE:…」のダンプを書く関数(なければ本体のRAMにそのまま書く)。アプリは作業欄の
        # 書いた範囲の記録も合わせて更新する関数にする
        self.on_write: Callable[[list[tuple[int, bytes]]], None] | None = None
        self.queue: list[list[str]] = []
        self.writes: dict[str, list[tuple[int, bytes]]] = {}
        self.calls: dict[str, Callable[[], object]] = {}
        self.cur: list[str] | None = None
        self.until = 0
        self.phase = 0  # 0: 押している、1: 離して待っている、2: 離されるまで押している
        self.physical: set[str] = set()  # パソコンのキーボードで押されている本体のキー
        # 本体のキーごとに、それを押しているパソコンのキー(↑と8のように、2つのキーが同じ
        # 本体のキーになることがある。最後の1つが離されたときに本体のキーを離す)
        self.sources: dict[str, set[object]] = {}
        self.mouse_keys: set[str] = set()  # マウスで押している本体のキー
        self.live = False
        self.quick = False
        self.rush = False  # いまのパソコンのキーは、ROMの入力待ちに届けたもの(速く回してよい)
        self.ready_at = 0  # ENTERのあと、ROMが入力待ちに戻っていれば次を打ってよいサイクル
        self.stamp = ""
        self.direct: dict[str, int] = {}  # 列を通さずに押しているキーと、押し始めたサイクル
        self.direct_off: dict[str, int] = {}  # 離されたが、まだ押しておくキーと離すサイクル
        self.wait_seen = 0  # ROMが入力待ちで止まっているのを最後に見たサイクル

    def press_live(self, name: str, source: object = None) -> None:
        """パソコンのキー(source。キーコードなど)が押され、本体のキーnameになった"""
        self.sources.setdefault(name, set()).add(source)
        if name in self.physical:
            return
        self.physical.add(name)
        c = self.m.cpu.cycles
        if self._direct(c):
            self.direct[name] = c
            self.direct_off.pop(name, None)
            self.m.held.add(name)
        else:
            self.queue.append([self.LIVE, str(c), name])

    def _direct(self, c: int) -> bool:
        """パソコンのキーを列に入れずにすぐ押してよいか。ファイルなどの打ち込みの途中と、
        ROMが入力待ちで止まっている(止まってからWAIT_SPANたっていない)ときは列に入れる"""
        if self.queue or (self.cur is not None and not self.live):
            return False
        if self.m.halted:
            self.wait_seen = c
        return c - self.wait_seen > self.WAIT_SPAN

    def add_live_keys(self, keys: list[list[str]]) -> None:
        """パソコンで打った記号やBackspaceを直した打鍵を足す。1文字ぶんの打鍵には
        同じ時刻をつけ、まとめて扱う"""
        stamp = str(self.m.cpu.cycles)
        self.queue.extend([self.LIVE, stamp, *k] for k in keys)

    def release_live(self, name: str, source: object = None) -> None:
        """パソコンのキー(source)が離された。同じ本体のキーをほかのパソコンのキーがまだ押して
        いれば、本体のキーは押したままにする。すぐ押したキーは、押し始めからDIRECT_MINたつまでは
        押しておく"""
        held_by = self.sources.get(name, set())
        held_by.discard(source)
        if held_by:
            return
        self.sources.pop(name, None)
        if name not in self.physical:
            return
        self.physical.discard(name)
        start = self.direct.get(name)
        if start is not None:
            if self.m.cpu.cycles - start >= self.DIRECT_MIN:
                self._lift(name)
            else:
                self.direct_off[name] = start + self.DIRECT_MIN

    def release_physical(self) -> None:
        """パソコンのキーがすべて離された(ほかのウィンドウに移ったときなど)"""
        self.physical.clear()
        self.sources.clear()
        for name in list(self.direct):
            self._lift(name)

    def press_mouse(self, name: str) -> None:
        """本体のキーをマウスで押した(列を通さず、すぐ押す)"""
        self.mouse_keys.add(name)
        self.m.held.add(name)

    def release_mouse(self, name: str) -> None:
        """マウスを離した。パソコンのキーボードで同じキーを押していれば、押したままにする"""
        self.mouse_keys.discard(name)
        if not self._kept(name):
            self.m.held.discard(name)

    def _kept(self, name: str) -> bool:
        """本体のキーnameを、マウス、すぐ押したパソコンのキー、列から押しているもののどれかが
        まだ押しているか"""
        if name in self.mouse_keys or name in self.direct:
            return True
        return self.cur is not None and name in self.cur and self.phase != 1

    def _lift(self, name: str) -> None:
        """すぐ押したキーを離す(マウスや列から押しているものと重なっていれば、それは残す)"""
        self.direct.pop(name, None)
        self.direct_off.pop(name, None)
        if not self._kept(name):
            self.m.held.discard(name)

    @property
    def rushing(self) -> bool:
        """パソコンのキーの打鍵を、ROMが入力を待っているところへ届けている最中か。そのあいだは
        エミュレータを速く回して、1打鍵にかかる時間(ROMがキーを読み取る待ち)を縮めてよい。
        ENTERのあとの待ち(RUNならプログラムが動き出す)と、押し続けているあいだ(ROMが
        キーの繰り返しを数える)は含めない。プログラムの実行中に押したキーも含めない"""
        if self.cur is not None:
            if not (self.live and self.rush):
                return False
            return self.phase == 0 or (self.phase == 1 and self.cur not in (["ENTER"], ["MODE"]))
        return bool(self.queue) and self.queue[0][:1] == [self.LIVE] and self.m.halted

    @property
    def scripted(self) -> bool:
        """ファイルや貼り付けの打ち込みの途中か(パソコンのキーは含めない)"""
        if self.cur is not None and not self.live:
            return True
        return any(e[:1] != [self.LIVE] for e in self.queue)

    def add_text(self, text: str) -> None:
        self.queue.extend(keys_for(_lf(text), self.m.model.name))

    def add_program(self, text: str) -> None:
        """BASICの行を打つ。79字を超える行は分けて打つ(keytype.keys_for_program)"""
        self.queue.extend(keys_for_program(_lf(text), self.m.model.name))

    def add_keys(self, keys: list[list[str]]) -> None:
        self.queue.extend(keys)

    def add_mode(self, mode: str) -> None:
        self.queue.append([f"@MODE:{mode}"])

    def add_idle(self) -> None:
        """ROMが入力待ちに戻るまで(最長1分)、次の打鍵を待つ"""
        self.queue.append(["@IDLE"])

    def add_call(self, fn) -> None:
        """前の打鍵が終わったところで、fn()を呼ぶ"""
        self.queue.append(self.call(fn))

    def call(self, fn) -> list[str]:
        """fn()を呼ぶ1つの打鍵の代わり(列の途中に入れるとき用)"""
        key = f"@CALL:{len(self.calls)}:{id(fn)}"
        self.calls[key] = fn
        return [key]

    def add_write(self, blocks: list[tuple[int, bytes]]) -> None:
        """前の打鍵が終わったところで、ダンプをRAMに書き込む"""
        key = f"@WRITE:{len(self.writes)}:{id(blocks)}"
        self.writes[key] = blocks
        self.queue.append([key])

    def clear(self) -> None:
        """打ちかけのものを捨て、押しているキーを離す"""
        if self.cur:
            self.m.held.difference_update(set(self.cur) - self.mouse_keys)
        for name in list(self.direct):
            self._lift(name)
        self.queue.clear()
        self.cur = None
        self.phase = 0
        self.live = False

    def restored(self) -> None:
        """本体の状態を戻したあと(CPUのサイクルが過去や先へ飛ぶ)に、打ちかけのものを捨て、
        サイクルで覚えている時刻を戻した本体に合わせる。ROMが入力を待って止まっている状態なら
        キーを列で届け、プログラムが動いている状態ならすぐ押す"""
        self.clear()
        c = self.m.cpu.cycles
        self.wait_seen = c if self.m.halted else c - self.WAIT_SPAN - 1
        self.until = self.ready_at = c

    @property
    def busy(self) -> bool:
        return bool(self.queue) or self.cur is not None

    def step(self) -> None:
        c = self.m.cpu.cycles
        if self.m.halted:
            self.wait_seen = c
        for name, at in list(self.direct_off.items()):
            if c >= at:
                self._lift(name)
        if self.cur == ["@IDLE"]:
            if self.m.halted or c >= self.until:
                self.cur = None
        elif self.cur is None:
            if self.queue:
                self._next(c)
        elif self.phase == 2:
            if not set(self.cur) <= self.physical or self.queue:
                self._release(c)
        elif c >= self.until or (self.phase == 1 and self._ready(c)):
            if self.phase == 1:
                self.cur = None
            elif self.live and set(self.cur) <= self.physical and not self.queue:
                self.phase = 2  # まだ押されているので、離されるまで押しておく
            else:
                self._release(c)

    def _next(self, c: int) -> None:
        self.cur = cur = self.queue.pop(0)
        tag = cur[0] if cur else ""
        if tag == "@IDLE":
            self.until = c + CLOCK * 60
        elif tag.startswith("@CALL:"):
            self.cur = None
            fn = self.calls.pop(tag, None)
            if fn is not None:
                fn()
        elif tag.startswith("@WRITE:"):
            blocks = self.writes.pop(tag, [])
            if self.on_write is not None:
                self.on_write(blocks)
            else:
                for addr, data in blocks:
                    for i, b in enumerate(data):
                        self.m.write(addr + i, b)
            self.until = c
            self.phase = 1
        elif tag.startswith("@MODE:"):
            self._switch(tag[6:], c)
        else:
            self._press(c)

    def _switch(self, mode: str, c: int) -> None:
        if self.mode_key and mode in ("RUN", "PRO"):
            # MODEキーで切り替える。いまのモードは液晶の記号で見る
            now = "PRO" if "PRO" in self.m.symbols() else "RUN"
            self.cur = ["MODE"] if now != mode else None
            if self.cur:
                self._press(c)
            return
        if self.mode_key and self.on_mode:
            self.on_mode(mode)
            self.cur = None
            return
        self.live = False
        if self.on_mode:
            self.on_mode(mode)
        else:
            self.m.mode = mode
        self.until = c + self.MODE_WAIT
        self.phase = 1

    def _press(self, c: int) -> None:
        assert self.cur is not None
        if self.cur[:1] == [self.LIVE]:
            stamp = self.cur[1]
            self.cur = self.cur[2:]
            late = c - int(stamp) > self.LIVE_MAX_WAIT
            if stamp != self.stamp and late and not set(self.cur) <= self.physical:
                # 待ちすぎた打鍵は、同じ文字の残りの打鍵ごと捨てる
                while self.queue and self.queue[0][:2] == [self.LIVE, stamp]:
                    self.queue.pop(0)
                self.cur = None
                return
            self.stamp = stamp  # 1文字の途中の打鍵は、遅れていても最後まで押す
            self.live = True
        else:
            self.live = False
        # パソコンのキーそのものは短く押す。記号などを直した打鍵は打ち込みと同じ長さにする
        self.quick = self.live and set(self.cur) <= self.physical
        # ROMが入力を待って止まっているところへ届けるキーだけを速く回す(プログラムの
        # INKEY$などで読まれるキーは、実行中なので速くしない)
        self.rush = self.live and self.m.halted
        self.m.held.update(self.cur)
        self.until = c + (self.LIVE_DOWN if self.quick else self.DOWN)
        self.phase = 0

    def _ready(self, c: int) -> bool:
        """パソコンのキーのENTERのあと、ROMが入力待ちに戻ったか(次のキーを待たせない)"""
        return self.live and self.rush and c >= self.ready_at and self.m.halted

    def _release(self, c: int) -> None:
        assert self.cur is not None
        self.m.held.difference_update(self.cur)
        self.m.held.update(self.direct)
        self.m.held.update(self.mouse_keys)
        if self.cur in (["ENTER"], ["MODE"]):
            self.until = c + self.AFTER_ENTER
            self.ready_at = c + self.LIVE_UP
        else:
            self.until = c + (self.LIVE_UP if self.quick else self.UP)
        self.phase = 1
