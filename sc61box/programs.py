"""プログラムの置き場所(ライブラリ)とファイルの読み方

置き場所のディレクトリにファイルを置くと、プログラムの一覧に出る。

- 1つの機種だけで動くものは、その機種のフォルダ(pc1251/、pc1245/、pc1261/、pc1350/)に
  置く。RAMの範囲だけが違う機種(PC-1250・1255、PC-1260・1262)では、元の機種のフォルダ
  (pc1251/、pc1261/)のものも、書き込む番地がRAMに収まれば使える。
- いくつかの機種で動くものは直下に置き、「# model: 1251,1245」のように機種を書く。
- どの機種でも動くBASICは、直下に「# model:」なしで置く。直下で「# model:」のないものは、
  書き込む番地から動く機種を決める(Program.inferred)。

    programs/
        primes.bas         どの機種でも
        pcint.bas          # model: 1251,1245
        pc1251/break.bas   PC-1251用
        pc1245/break.bas   PC-1245用(同じ名前でもかまわない)

    *.bas  BASICのプログラム(テキスト)。PROモードでNEWしてから打ち込む
    *.hex  16進ダンプ。「番地 データ」の行をRAMにそのまま書く。行末の「:チェックサム」は
           読み飛ばし、「;」から後ろはコメント。YASM61860の「c000 : 12 34 … : 5a」も読める

同じ名前の.basと.hexは1本のプログラムにまとめ、ダンプを書いてからBASICを打ち込む。

「#」で始まる行はコメントで、次の指示を書ける。

    # title: 表示する名前
    # run: CALL &C300     実行するときにRUNモードで打つ文字列(既定はRUN)。いくつも書くと
                          上から順に打つ
    # mode: PRO           # run:の文字列をPROモードで打つ
    # help: 0で始まる     読み込んで動かし始めたときに画面の下に出す説明。いくつも書くと
                          行を重ねて出す
    # setup: EQU#43       NEWのあと、BASICの前にPROモードで打つ命令。あるときは、ダンプも
                          この命令のあとで書く(BASICの置き場所を動かしてマシン語を置く記事用)
    # hex: pcint.hex      先に書き込む16進ダンプ。1つのダンプをいくつものプログラムから使える
    # bin: code.bin &C300 先に書き込むマシン語のバイナリと置く番地(.binは番地を持たない。
                          PocketToolsのbin2wavの.binと同じ)
    # after: code.hex     実行の文字列を打ったあとで書き込むダンプ(BASICでDIMなどをしてから
                          マシン語を置く記事用)。「# after: code.bin &C300」も使える
    # data: C100-C17F     命令ではなくデータの範囲(逆アセンブルでDBの行にする)。「,」で区切って
                          いくつも書ける。終わりを書かずに「C100」とすると、そこからデータ
                          (次の指定か、実行した命令の手前まで)
    # model: 1251,1245    動く機種(「,」で区切る)。書かなければ置いたフォルダで決まる。
                          ほかの機種では一覧に出ず、開いても読み込まない
    # pad: dpup=8 a=SPC   ゲームパッドの割り当て(入力の名前=本体のキーの名前。gamepad.py)。
                          読み込むと、この割り当てになる
    # ram: 6800-7FFF     機種のRAMの終わりより上もRAMにする(終わりの番地まで広げる。ROMや
                          液晶RAMにかかる範囲は書けない)。読み込むと広がり、# ram: のない
                          プログラムを読み込むと機種のRAMに戻る
"""

import os
import re
from dataclasses import dataclass, field

from . import paths
from .i18n import tr
from .keytype import stored_len
from .machine import BASE_MODEL, MODELS, ram_span

EXTS = (".bas", ".hex")

# BASICのPOKEの番地(&のついた16進か、10進の数で書いたもの)
POKE_RE = re.compile(r"POKE\s*(&[0-9A-F]{1,4}|[0-9]{1,5})\b")


def fits(model: str, addrs: list[tuple[int, int]], ram_top: int | None = None) -> bool:
    """番地の範囲(始め, 終わりの次)がどれも、その機種のRAMか液晶のRAMに収まるか。ram_topは
    # ram: で広げたRAMの終わり"""
    m = MODELS[model]
    areas = [ram_span(m, ram_top), *m.lcd]
    return all(any(lo <= a and b <= hi for lo, hi in areas) for a, b in addrs)


def model_dir(model: str) -> str:
    """機種用のフォルダの名前(pc1251など)"""
    return "pc" + model


def folder_model(path: str) -> str:
    """ファイルが機種用のフォルダにあれば、その機種の名前。なければ空"""
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
    for name in MODELS:
        if folder == model_dir(name):
            return name
    return ""


def library_dirs() -> list[str]:
    """一覧に使うディレクトリ。SC61BOX_PROGRAMS(:区切り。前の名前のPC1251_PROGRAMSも)、
    データのフォルダのprograms(~/.sc61box/programs)、
    このリポジトリのprograms/、programs/private/(配布物には含まれない自分用の置き場所。あれば)の順"""
    dirs = [d for d in paths.env("PROGRAMS").split(os.pathsep) if d]
    dirs.append(os.path.join(paths.data_dir(), "programs"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(here, "programs"))
    dirs.append(os.path.join(here, "programs", "private"))
    out = []
    for d in dirs:
        d = os.path.abspath(d)
        if d not in out:
            out.append(d)
    return out


def user_dir() -> str:
    """ユーザーがファイルを置くところ(なければ作る)。作れなくても(同じ名前のファイルがある
    など)ここでは止まらずに場所を返す。そこへ書くところで失敗し、それぞれが知らせる"""
    env = [d for d in paths.env("PROGRAMS").split(os.pathsep) if d]
    d = os.path.abspath(env[0]) if env else os.path.join(paths.data_dir(), "programs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


@dataclass
class Program:
    name: str  # 拡張子を除いたファイル名
    paths: list[str] = field(default_factory=list)
    title: str = ""
    run: str = ""  # 実行するときに打つ文字列。# run:がいくつもあれば改行でつなぐ
    mode: str = ""  # # run:を打つモード。空ならRUN
    setup: str = ""  # NEWのあとに打つ命令。いくつもあれば改行でつなぐ
    help: str = ""  # 読み込んだあとに出す説明。いくつもあれば改行でつなぐ
    norom: str = ""  # ROMなしで読み込んだときに出す説明(# norom:)。いくつもあれば改行でつなぐ
    basic: str = ""  # 打ち込むBASICの行(コメントを除いたもの)
    blocks: list[tuple[int, bytes]] = field(default_factory=list)
    after: list[tuple[int, bytes]] = field(default_factory=list)  # # after: で、実行のあとに書く
    model: str = ""  # # model: の値。空ならどの機種でも
    # # pad: の値(ゲームパッドの割り当て)。行がなければNone、値のない行は何も割り当てない
    pad: str | None = None
    links: list[str] = field(
        default_factory=list
    )  # 「after: code.hex」など、ダンプの指示(書き出し用)
    # # data: の範囲(始め, 終わりの次)。終わりを書いていなければ(始め, None)
    data: list[tuple[int, int | None]] = field(default_factory=list)
    ram: tuple[int, int] | None = None  # # ram: の範囲(始め, 終わりの次)
    errors: list[str] = field(default_factory=list)

    @property
    def norom_ok(self) -> bool:
        """ROMなしで使えるか。マシン語のダンプがあり、# norom: offでないもの"""
        return bool(self.blocks or self.after) and self.norom.strip().lower() != "off"

    @property
    def models(self) -> list[str] | None:
        """動く機種。# model:やフォルダで決まっていなければ、番地から決める(inferred)。
        Noneはどの機種でも"""
        named = [m.strip() for m in self.model.replace(" ", ",").split(",") if m.strip()]
        return named or self.inferred

    @property
    def addresses(self) -> list[tuple[int, int]]:
        """書き込むダンプと、BASICのPOKEの番地の範囲(始め, 終わりの次)"""
        out = [(a, a + len(b)) for a, b in self.blocks + self.after if b]
        for m in POKE_RE.finditer(self.basic):
            t = m.group(1)
            a = int(t[1:], 16) if t.startswith("&") else int(t)
            out.append((a, a + 1))
        return out

    @property
    def ram_top(self) -> int | None:
        """# ram: で広げるRAMの終わり(含まない)。なければNone"""
        return self.ram[1] if self.ram else None

    @property
    def inferred(self) -> list[str] | None:
        """番地がRAMか液晶に収まる機種。番地がなければNone(どの機種でも)、収まる機種が
        なければ空。RAMの範囲だけが違う機種は元の機種に含める(runs_onがBASE_MODELで見る)"""
        addrs = self.addresses
        if not addrs:
            return None
        ok = [name for name in MODELS if fits(name, addrs, self.ram_top)]
        return [name for name in ok if BASE_MODEL.get(name) not in ok]

    def runs_on(self, model: str) -> bool:
        models = self.models
        if models is None or model in models:
            return True
        return BASE_MODEL.get(model) in models and self._fits_family(model)

    def fits(self, writable) -> bool:
        """機種を書いていないものが、いまの本体に書けるか。writable(番地)はMachine.writable。
        PC-1350のRAMカードのように、機種の既定のRAMの外でも書ける番地を見るため"""
        addrs = self.addresses
        if self.model or not addrs:
            return False
        return all(writable(a) for lo, hi in addrs for a in range(lo, hi))

    def _fits_family(self, model: str) -> bool:
        """元の機種用のものを、RAMの範囲が違う機種で使えるか。書き込む番地がRAMに収まり、
        BASICの置き場所が元の機種と違うときは、BASICが置かれる範囲(見積もり)にかからないこと
        (# setup:でBASICの置き場所を動かすものは見ない)"""
        addrs = self.addresses
        if not fits(model, addrs, self.ram_top):
            return False
        start = MODELS[model].prog_start
        if self.setup or start == MODELS[BASE_MODEL[model]].prog_start:
            return True
        end = start + 2 + sum(stored_len(ln) + 3 for ln in self.basic.splitlines() if ln.strip())
        return all(b <= start or a >= end for a, b in addrs)

    def label(self, model: str) -> str:
        """一覧に出す名前。この機種で動かないものには、動く機種を添える"""
        if self.runs_on(model):
            return self.title
        if not self.models:
            return tr("{title}(番地がどの機種のRAMにも収まらない)", title=self.title)
        models = tr("・").join(f"PC-{m}" for m in self.models)
        return tr("{title}({models}用)", title=self.title, models=models)

    @property
    def kinds(self) -> str:
        kinds = (("BASIC", self.basic), ("HEX", self.blocks or self.after))
        return "+".join(k for k, ok in kinds if ok)

    @property
    def run_command(self) -> str:
        if self.run:
            return self.run
        return "RUN" if self.basic else ""

    @property
    def size(self) -> int:
        return sum(len(b) for _, b in self.blocks + self.after)


def _directive(line: str) -> tuple[str, str] | None:
    body = line.lstrip("#").strip()
    if ":" not in body:
        return None
    key, val = body.split(":", 1)
    key = key.strip().lower()
    if key in (
        "title", "run", "hex", "bin", "after", "model", "mode", "setup", "help", "norom", "data",
        "pad", "ram",
    ):  # fmt: skip
        return key, val.strip()
    return None


DATA_RE = re.compile(r"&?([0-9A-Fa-f]{1,4})(?:\s*[-〜]\s*&?([0-9A-Fa-f]{1,4}))?")


def parse_data(text: str) -> tuple[list[tuple[int, int | None]], str]:
    """# data: の値(「C100-C17F, C200」)を読む。範囲は(始め, 終わりの次)、終わりのない
    番地は(番地, None)。読めない所があれば、その文字も返す(なければ空)"""
    spans: list[tuple[int, int | None]] = []
    for item in text.replace("、", ",").split(","):
        item = item.strip()
        if not item:
            continue
        hit = DATA_RE.fullmatch(item)
        if hit is None:
            return spans, item
        lo = int(hit[1], 16)
        hi = int(hit[2], 16) + 1 if hit[2] else None
        if hi is not None and hi <= lo:
            return spans, item
        spans.append((lo, hi))
    return spans, ""


def data_line(spans: list[tuple[int, int]]) -> str:
    """データの範囲(始め, 終わりの次)を# data: の行にする(なければ空)"""
    if not spans:
        return ""
    return "# data: " + ", ".join(f"{lo:04X}-{hi - 1:04X}" for lo, hi in spans) + "\n"


# YASM61860の16進ダンプの行(「c000 : 12 34 … : 5a」)。行の番地は8の倍数に切り下げてあり、
# 行の途中から始まるときは、手前を1バイトにつき3文字の空白で埋めている
YASM_LINE = re.compile(r"([0-9A-Fa-f]{4}) : (.*)")


def parse_hex(text: str, where: str = "") -> tuple[list[tuple[int, bytes]], list[str]]:
    """「C200 04F1F9...[:チェックサム]」の行を読む。番地だけの行や空行は飛ばす。
    「:」があれば、そのあとのチェックサム(バイトの和の下2桁)が合わない行や、16進表記2桁で
    ない行はエラーにする"""
    blocks: list[tuple[int, bytes]] = []
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        yasm = YASM_LINE.fullmatch(line)
        if yasm:
            head, body = yasm[1], yasm[2]
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            head, body = parts[0].rstrip(":"), parts[1]
        try:
            addr = int(head, 16)
            if yasm:
                pad = len(body) - len(body.lstrip(" "))
                if addr % 8 == 0 and pad % 3 == 0:
                    addr += pad // 3
            data_text, colon, total = body.partition(":")
            data = bytes.fromhex(data_text.replace(" ", ""))
        except ValueError:
            errors.append(
                tr("{where}{line}行目を16進ダンプとして読めない: {text}",
                   where=where, line=n, text=line[:30])
            )  # fmt: skip
            continue
        if addr + len(data) > 0x10000:
            errors.append(
                tr("{where}{line}行目の番地がFFFFを越える: {text}",
                   where=where, line=n, text=line[:30])
            )  # fmt: skip
            continue
        total = total.strip()
        if colon and not re.fullmatch(r"[0-9A-Fa-f]{2}", total):
            errors.append(
                tr("{where}{line}行目の「:」のあとがチェックサム(16進表記2桁)ではない: {text}",
                   where=where, line=n, text=line[:30])
            )  # fmt: skip
            continue
        if colon and sum(data) & 0xFF != int(total, 16):
            errors.append(
                tr("{where}{line}行目のチェックサムが合わない(計算すると{sum:02X}): {text}",
                   where=where, line=n, sum=sum(data) & 0xFF, text=line[:30])
            )  # fmt: skip
            continue
        blocks.append((addr, data))
    return blocks, errors


def parse_addr(text: str) -> int | None:
    """番地の書き方(&C300、0xC300、C300)を読む。番地でなければNone"""
    t = text.strip()
    for prefix in ("&", "0x", "0X", "$"):
        if t.startswith(prefix):
            t = t[len(prefix) :]
            break
    if not re.fullmatch(r"[0-9A-Fa-f]{1,4}", t):
        return None
    return int(t, 16)


def read_bin(path: str, addr: int, where: str = "") -> tuple[list[tuple[int, bytes]], list[str]]:
    """マシン語のバイナリ(.bin)を、番地addrから置くものとして読む"""
    try:
        data = open(path, "rb").read()
    except OSError as e:
        return [], [f"{where}{e}"]
    if not data:
        return [], [tr("{where}中身が空", where=where)]
    if addr + len(data) > 0x10000:
        why = tr("{where}&{addr:04X}から{n}バイトでは、&FFFFを越える",
                 where=where, addr=addr, n=len(data))  # fmt: skip
        return [], [why]
    return [(addr, data)], []


def _add_hex(prog: Program, spec: str, near: str, key: str = "hex") -> None:
    """# hex:・# bin:・# after:のダンプを読んで足す。同じフォルダ、置き場所の同じ機種の
    フォルダ、置き場所の直下の順に探す"""
    name, addr = spec, None
    parts = spec.rsplit(None, 1)
    if len(parts) == 2 and parse_addr(parts[1]) is not None:
        name, addr = parts[0], parse_addr(parts[1])
    is_bin = name.lower().endswith(".bin")
    if is_bin and addr is None:
        prog.errors.append(
            tr("# {key}: {name}に置く番地がない(例:# bin: {name} &C300)", key=key, name=name)
        )
        return
    sub = model_dir(folder_model(os.path.join(near, name)) or "-")
    places = [near] + [os.path.join(d, sub) for d in library_dirs()] + library_dirs()
    p = next((os.path.join(d, name) for d in places if os.path.exists(os.path.join(d, name))), None)
    if p is None:
        prog.errors.append(tr("# {key}: {name}が見つからない", key=key, name=name))
        return
    if p in prog.paths:
        return
    prog.paths.append(p)
    prog.links.append(f"{key}: {name}" + ("" if addr is None else f" &{addr:04X}"))
    if addr is not None and is_bin:
        blocks, errors = read_bin(p, addr, name + " ")
    else:
        try:
            text = open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as e:
            prog.errors.append(
                tr("# {key}: {name}を読めない({error})", key=key, name=name, error=e)
            )
            return
        blocks, errors = parse_hex(text, name + " ")
        # 使うダンプに書いた# data: の範囲も取り込む(ほかの指示は使う側で書く)
        for line in text.splitlines():
            d = _directive(line.strip()) if line.strip().startswith("#") else None
            if d and d[0] == "data":
                _add_data(prog, d[1], name)
            elif d and d[0] == "ram":
                _set_ram(prog, d[1], name)
    (prog.after if key == "after" else prog.blocks).extend(blocks)
    prog.errors.extend(errors)


def _add_data(prog: Program, value: str, file: str) -> None:
    """# data: の値を読んでprog.dataに足す。読めなければprog.errorsに足す"""
    spans, bad = parse_data(value)
    prog.data.extend(spans)
    if bad:
        prog.errors.append(tr("{file}: # data: の{text}が読めない", file=file, text=bad))


def _set_ram(prog: Program, value: str, file: str) -> None:
    """# ram: の値(「6800-7FFF」)を読んでprog.ramにする。読めなければprog.errorsに足す"""
    spans, bad = parse_data(value)
    hi = spans[0][1] if len(spans) == 1 else None
    if bad or hi is None:
        prog.errors.append(tr("{file}: # ram: の{text}が読めない(例:# ram: 6800-7FFF)",
                              file=file, text=value.strip()))  # fmt: skip
        return
    prog.ram = (spans[0][0], hi)


def _read_into(prog: Program, path: str) -> None:
    try:
        text = open(path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as e:
        prog.errors.append(f"{os.path.basename(path)}: {e}")
        return
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        if line.strip().startswith("#"):
            d = _directive(line.strip())
            if d and d[0] in ("hex", "bin", "after"):
                _add_hex(prog, d[1], os.path.dirname(path), d[0])
            elif d and d[0] == "data":
                _add_data(prog, d[1], os.path.basename(path))
            elif d and d[0] == "ram":
                _set_ram(prog, d[1], os.path.basename(path))
            elif d and d[0] == "pad":  # いくつもの行に分けて書ける
                prog.pad = d[1] if prog.pad is None else f"{prog.pad} {d[1]}".strip()
            elif d and d[0] in ("run", "setup", "help", "norom") and d[1]:
                old = getattr(prog, d[0])
                setattr(prog, d[0], old + "\n" + d[1] if old else d[1])
            elif d and not getattr(prog, d[0]):
                setattr(prog, d[0], d[1])
    if path.lower().endswith(".hex"):
        blocks, errors = parse_hex(text, os.path.basename(path) + " ")
        prog.blocks.extend(blocks)
        prog.errors.extend(errors)
    else:
        lines = [ln.rstrip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
        prog.basic += "".join(ln + "\n" for ln in lines)


def load_program(path: str) -> Program:
    """1本のプログラムを読む。同じ名前の.bas/.hexがあれば組にする"""
    base, _ext = os.path.splitext(os.path.abspath(path))
    prog = Program(name=os.path.basename(base))
    paths = [p for p in (base + ".hex", base + ".bas") if os.path.exists(p)]
    if not paths:  # 拡張子の違うテキスト(.txtなど)はBASICとして読む
        paths = [path]
    for p in paths:
        prog.paths.append(p)
        if p.lower().endswith(".hex"):
            prog.links.append(f"hex: {os.path.basename(p)}")
        _read_into(prog, p)
    prog.title = prog.title or prog.name
    prog.model = prog.model or folder_model(paths[0])
    return prog


def scan(dirs: list[str] | None = None) -> list[Program]:
    """置き場所(直下と機種のフォルダ)にあるプログラム。同じフォルダの同じ名前が
    いくつかの置き場所にあれば、先の置き場所のものを使う"""
    seen: dict[tuple[str, str], str] = {}
    for d in dirs if dirs is not None else library_dirs():
        for sub in [""] + [model_dir(m) for m in MODELS]:
            try:
                names = sorted(os.listdir(os.path.join(d, sub)))
            except OSError:
                continue
            for f in names:
                stem, ext = os.path.splitext(f)
                key = (stem, sub)
                if ext.lower() in EXTS and not f.startswith(".") and key not in seen:
                    seen[key] = os.path.join(d, sub, f)
    progs = [load_program(p) for _, p in sorted(seen.items())]
    # ほかのプログラムが# hex:・# after:で使うだけのダンプは出さない(同じ名前の.basがあれば出す)
    used = {os.path.realpath(x) for p in progs for x in p.paths[1:] if x.lower().endswith(".hex")}

    def shown(p: Program) -> bool:
        has_bas = any(x.lower().endswith(".bas") for x in p.paths)
        return bool(p.basic) or has_bas or os.path.realpath(p.paths[0]) not in used

    return [p for p in progs if shown(p)]


def find(name: str, model: str = "") -> Program | None:
    """パスか、置き場所にあるプログラムの名前から探す。modelのフォルダ、元の機種のフォルダ、
    直下、ほかの機種のフォルダの順に見る"""
    if os.path.exists(name):
        return load_program(name)
    stem = os.path.splitext(os.path.basename(name))[0]
    own = [model_dir(m) for m in (model, BASE_MODEL.get(model)) if m]
    subs = own + [""] + [model_dir(m) for m in MODELS if model_dir(m) not in own]
    for sub in subs:
        for d in library_dirs():
            for ext in EXTS:
                p = os.path.join(d, sub, stem + ext)
                if os.path.exists(p):
                    return load_program(p)
    return None


def for_model(items: list[Program], model: str, writable=None) -> list[Program]:
    """一覧に出すもの(この機種で動くもの)。同じ# title:のものがこの機種のフォルダにあれば、
    そちらだけを出す(機種ごとに作り分けたものを同じ名前で置ける)。writable(番地)があれば、
    いまの本体(RAMカードなど)に書けるものも出す(Program.fits)"""
    own_dirs = (model, BASE_MODEL.get(model))
    ok = [p for p in items if p.runs_on(model) or (writable and p.fits(writable))]
    own = {p.title for p in ok if folder_model(p.paths[0]) in own_dirs}
    return [p for p in ok if folder_model(p.paths[0]) in own_dirs or p.title not in own]
