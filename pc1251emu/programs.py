"""プログラムの置き場所(ライブラリ)とファイルの読み方

置き場所のディレクトリにファイルを置くと、F6の一覧に出てくる。置き場所の直下に
置いたものはどの機種でも使え、pc1251/、pc1245/のフォルダに置いたものはその機種用になる。

    programs/
        primes.bas         どの機種でも
        pc1251/break.bas   PC-1251用
        pc1245/break.bas   PC-1245用(同じ名前でもかまわない)

    *.bas  BASICのプログラム(テキスト)。PROモードでNEWしてから打ち込む
    *.hex  16進ダンプ。「番地 データ」の行で、RAMにそのまま書き込む
           (記事のダンプと同じ形。行末の「:チェックサム」は読み飛ばす。
           「;」から後ろはコメントなので、ニーモニックを書き添えておける。
           YASM61860が出す「c000 : 12 34 … : 5a」の形も読める)

同じ名前の.basと.hexがあれば1本のプログラムとしてまとめ、ダンプを書いて
からBASICを打ち込む。マシン語とそれを呼ぶBASICを組にしておける。

ファイルの中の「#」で始まる行はコメントで、次の書き方で指示を書ける。

    # title: 表示する名前
    # run: CALL &C300     実行するときにRUNモードで打つ文字列(既定はRUN)
    # hex: pcint.hex      先に書き込む16進ダンプ(同じ場所か置き場所から探す)
    # bin: code.bin &C300 先に書き込むマシン語のバイナリのファイル名と、置く番地。
                          .binのファイルにはバイトが並んでいるだけで、置く番地は
                          書かれていないので、# bin:の行で指定する
                          (PocketToolsのbin2wavで使う.binと同じもの。YASM61860の-rは
                          番地0からの中身を書き出すので、YASMはダンプ(-d)を.hexにする)
    # after: code.hex     実行するときに打つ文字列を打ったあとで書き込むダンプ。
                          BASICの側でDIMなどをしてからマシン語を読み込む記事のため。
                          「# after: code.bin &C300」のように.binも使える
    # model: 1251         動く機種(いくつもあるときは「,」で区切る)。書かなければ
                          置いたフォルダで決まる(直下ならどの機種でも)。ほかの機種では
                          一覧に「(PC-1251用)」と出て、読み込まない

# hex: を使えば、1つのダンプ(たとえばPC-インタープリタ)を、
その上で動くいくつものBASICのプログラムから使える。
"""

import os
import re
from dataclasses import dataclass, field

from .machine import MODELS

EXTS = (".bas", ".hex")


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
    """一覧に使うディレクトリ。PC1251_PROGRAMS(:区切り)、~/.pc1251/programs、
    このリポジトリのprograms/、programs/private/(配布物には含まれない自分用の置き場所。あれば)の順"""
    dirs = [d for d in os.environ.get("PC1251_PROGRAMS", "").split(os.pathsep) if d]
    dirs.append(os.path.expanduser("~/.pc1251/programs"))
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
    """ユーザーがファイルを置くところ(なければ作る)"""
    env = [d for d in os.environ.get("PC1251_PROGRAMS", "").split(os.pathsep) if d]
    d = os.path.abspath(env[0]) if env else os.path.expanduser("~/.pc1251/programs")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class Program:
    name: str  # 拡張子を除いたファイル名
    paths: list[str] = field(default_factory=list)
    title: str = ""
    run: str = ""
    basic: str = ""  # 打ち込むBASICの行(コメントを除いたもの)
    blocks: list[tuple[int, bytes]] = field(default_factory=list)
    after: list[tuple[int, bytes]] = field(default_factory=list)  # # after: で、実行のあとに書く
    model: str = ""  # # model: の値。空ならどの機種でも
    bin_links: list[str] = field(default_factory=list)  # 「bin: code.bin &C300」など(書き出し用)
    errors: list[str] = field(default_factory=list)

    @property
    def models(self) -> list[str]:
        return [m.strip() for m in self.model.replace(" ", ",").split(",") if m.strip()]

    def runs_on(self, model: str) -> bool:
        return not self.models or model in self.models

    def label(self, model: str) -> str:
        """一覧に出す名前。この機種で動かないものには、動く機種を添える"""
        if self.runs_on(model):
            return self.title
        return self.title + "(" + "・".join(f"PC-{m}" for m in self.models) + "用)"

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
    if key in ("title", "run", "hex", "bin", "after", "model"):
        return key, val.strip()
    return None


# YASM61860の16進ダンプの行。「c000 : 12 34 … : 5a」。行の番地は8の倍数に切り下げてあり、
# 書き始めが行の途中のときは、そこまでを1バイトにつき3文字の空白で埋めている
YASM_LINE = re.compile(r"([0-9A-Fa-f]{4}) : (.*)")


def parse_hex(text: str, where: str = "") -> tuple[list[tuple[int, bytes]], list[str]]:
    """「C200 04F1F9...[:チェックサム]」の行を読む。番地だけの行や空行は飛ばす"""
    blocks: list[tuple[int, bytes]] = []
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()  # 「;」から後ろは行の途中でもコメント
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
            data = bytes.fromhex(body.split(":")[0].replace(" ", ""))
        except ValueError:
            errors.append(f"{where}{n}行目を16進ダンプとして読めない: {line[:30]}")
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
        return [], [f"{where}中身が空"]
    if addr + len(data) > 0x10000:
        return [], [f"{where}&{addr:04X}から{len(data)}バイトでは、&FFFFを越える"]
    return [(addr, data)], []


def _add_hex(prog: Program, spec: str, near: str, key: str = "hex") -> None:
    """# hex:・# bin:・# after:で指定したダンプを探して書き込む分に足す。同じフォルダ、
    置き場所の同じ機種のフォルダ、置き場所の直下の順に探す。.binは後ろに番地を書く"""
    name, addr = spec, None
    parts = spec.rsplit(None, 1)
    if len(parts) == 2 and parse_addr(parts[1]) is not None:
        name, addr = parts[0], parse_addr(parts[1])
    is_bin = name.lower().endswith(".bin")
    if is_bin and addr is None:
        prog.errors.append(f"# {key}: {name}に置く番地がない(例:# bin: {name} &C300)")
        return
    sub = model_dir(folder_model(os.path.join(near, name)) or "-")
    places = [near] + [os.path.join(d, sub) for d in library_dirs()] + library_dirs()
    for d in places:
        p = os.path.join(d, name)
        if os.path.exists(p):
            if p not in prog.paths:
                prog.paths.append(p)
                if is_bin:
                    assert addr is not None
                    blocks, errors = read_bin(p, addr, name + " ")
                    prog.bin_links.append(f"{key}: {name} &{addr:04X}")
                else:
                    blocks, errors = parse_hex(open(p, encoding="utf-8").read(), name + " ")
                (prog.after if key == "after" else prog.blocks).extend(blocks)
                prog.errors.extend(errors)
            return
    prog.errors.append(f"# {key}: {name}が見つからない")


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
        _read_into(prog, p)
    prog.title = prog.title or prog.name
    prog.model = prog.model or folder_model(paths[0])
    return prog


def scan(dirs: list[str] | None = None) -> list[Program]:
    """置き場所(直下と機種用のフォルダ)にあるプログラムの一覧。同じフォルダの
    同じ名前が複数の置き場所にあれば、先の置き場所が勝つ"""
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
    # ほかのプログラムが# hex:・# after:で使うだけのダンプ(.hexだけのもの)は、一覧に出さない
    used = {os.path.realpath(x) for p in progs for x in p.paths[1:] if x.lower().endswith(".hex")}
    return [p for p in progs if p.basic or os.path.realpath(p.paths[0]) not in used]


def find(name: str, model: str = "") -> Program | None:
    """パスか、置き場所にあるプログラムの名前から探す。modelのフォルダ、直下、
    ほかの機種のフォルダの順に見る(ほかの機種用は、見つかっても読み込む側で断る)"""
    if os.path.exists(name):
        return load_program(name)
    stem = os.path.splitext(os.path.basename(name))[0]
    others = [model_dir(m) for m in MODELS if m != model]
    subs = ([model_dir(model)] if model else []) + [""] + others
    for sub in subs:
        for d in library_dirs():
            for ext in EXTS:
                p = os.path.join(d, sub, stem + ext)
                if os.path.exists(p):
                    return load_program(p)
    return None


def for_model(items: list[Program], model: str) -> list[Program]:
    """一覧に出すもの。この機種で動かないものは、同じ名前(title)でこの機種用が
    あれば外す(ブロック崩しのPC-1251用とPC-1245用など)"""
    here = {p.title for p in items if p.runs_on(model)}
    return [p for p in items if p.runs_on(model) or p.title not in here]
