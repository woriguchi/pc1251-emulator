"""プログラムの置き場所(ライブラリ)とファイルの読み方

置き場所のディレクトリにファイルを置くと、F6の一覧に出てくる。

    *.bas  BASICのプログラム(テキスト)。PROモードでNEWしてから打ち込む
    *.hex  16進ダンプ。「番地 データ」の行で、RAMにそのまま書き込む
           (記事のダンプと同じ形。行末の「:チェックサム」は読み飛ばす。
           「;」から後ろはコメントなので、ニーモニックを書き添えておける)

同じ名前の.basと.hexがあれば1本のプログラムとしてまとめ、ダンプを書いて
からBASICを打ち込む。マシン語とそれを呼ぶBASICを組にしておける。

ファイルの中の「#」で始まる行はコメントで、次の書き方で指示を書ける。

    # title: 表示する名前
    # run: CALL &C300     実行するときにRUNモードで打つ文字列(既定はRUN)
    # hex: pcint.hex      先に書き込む16進ダンプ(同じ場所か置き場所から探す)

最後の書き方を使えば、1つのダンプ(たとえばPC-インタープリタ)を、
その上で動くいくつものBASICのプログラムから使える。
"""

import os
from dataclasses import dataclass, field

EXTS = (".bas", ".hex")


def library_dirs() -> list[str]:
    """一覧に使うディレクトリ。PC1251_PROGRAMS(:区切り)、~/.pc1251/programs、
    このリポジトリのprograms/の順"""
    dirs = [d for d in os.environ.get("PC1251_PROGRAMS", "").split(os.pathsep) if d]
    dirs.append(os.path.expanduser("~/.pc1251/programs"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(here, "programs"))
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
    errors: list[str] = field(default_factory=list)

    @property
    def kinds(self) -> str:
        return "+".join(k for k, ok in (("BASIC", self.basic), ("HEX", self.blocks)) if ok)

    @property
    def run_command(self) -> str:
        if self.run:
            return self.run
        return "RUN" if self.basic else ""

    @property
    def size(self) -> int:
        return sum(len(b) for _, b in self.blocks)


def _directive(line: str) -> tuple[str, str] | None:
    body = line.lstrip("#").strip()
    if ":" not in body:
        return None
    key, val = body.split(":", 1)
    key = key.strip().lower()
    if key in ("title", "run", "hex"):
        return key, val.strip()
    return None


def parse_hex(text: str, where: str = "") -> tuple[list[tuple[int, bytes]], list[str]]:
    """「C200 04F1F9...[:チェックサム]」の行を読む。番地だけの行や空行は飛ばす"""
    blocks: list[tuple[int, bytes]] = []
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()  # 「;」から後ろは行の途中でもコメント
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            addr = int(parts[0].rstrip(":"), 16)
            data = bytes.fromhex(parts[1].split(":")[0].replace(" ", ""))
        except ValueError:
            errors.append(f"{where}{n}行目を16進ダンプとして読めない: {line[:30]}")
            continue
        blocks.append((addr, data))
    return blocks, errors


def _add_hex(prog: Program, name: str, near: str) -> None:
    """# hex: で指定したダンプを探して書き込む分に足す"""
    for d in [near] + library_dirs():
        p = os.path.join(d, name)
        if os.path.exists(p):
            if p not in prog.paths:
                prog.paths.append(p)
                blocks, errors = parse_hex(open(p, encoding="utf-8").read(), name + " ")
                prog.blocks.extend(blocks)
                prog.errors.extend(errors)
            return
    prog.errors.append(f"# hex: {name}が見つからない")


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
            if d and d[0] == "hex":
                _add_hex(prog, d[1], os.path.dirname(path))
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
    return prog


def scan(dirs: list[str] | None = None) -> list[Program]:
    """置き場所にあるプログラムの一覧。同じ名前が複数の場所にあれば先の場所が勝つ"""
    seen: dict[str, str] = {}
    for d in dirs if dirs is not None else library_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            stem, ext = os.path.splitext(f)
            if ext.lower() in EXTS and not f.startswith(".") and stem not in seen:
                seen[stem] = os.path.join(d, f)
    return [load_program(p) for _, p in sorted(seen.items())]


def find(name: str) -> Program | None:
    """パスか、置き場所にあるプログラムの名前から探す"""
    if os.path.exists(name):
        return load_program(name)
    stem = os.path.splitext(os.path.basename(name))[0]
    for d in library_dirs():
        for ext in EXTS:
            p = os.path.join(d, stem + ext)
            if os.path.exists(p):
                return load_program(p)
    return None
