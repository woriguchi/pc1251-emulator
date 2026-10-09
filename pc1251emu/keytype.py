"""文字列をPC-1251(とPC-1245)のキー操作に直す(貼り付けと自動入力用)"""

# 指数のE。テキストでは「[E]」か「€」と書く(PocketToolsと同じ)。打つときは1字にまとめる
EXP = "€"
EXP_SPELLINGS = ("[E]", "[e]")


def normalize(text: str) -> str:
    """指数のEの書き方を、打つための1字にそろえる"""
    for s in EXP_SPELLINGS:
        text = text.replace(s, EXP)
    return text


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
    EXP: "+",  # 指数のE(Expキー、中間コード4Bh)。英字のEとは別の字
}
# PC-1245は括弧が1と2の上にある(↓↑ではない)
SHIFTED_1245 = {**SHIFTED, "(": "1", ")": "2"}
PLAIN = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-*/=.")


def keys_for(text: str, model: str = "1251") -> list[list[str]]:
    """1文字ごとに押すキーの列。[["SHIFT"], ["I"]]のように、1打鍵ずつ並べる。"""
    shifted = SHIFTED_1245 if model == "1245" else SHIFTED
    out: list[list[str]] = []
    for ch in normalize(text):
        if ch.isascii():  # πを大文字にするとΠになって打てなくなるので、英字だけ大文字にする
            ch = ch.upper()
        if ch == "\n":
            out.append(["ENTER"])
        elif ch == " ":
            out.append(["SPC"])
        elif ch in PLAIN:
            out.append([ch])
        elif ch in shifted:
            out.append(["SHIFT"])
            out.append([shifted[ch]])
        # それ以外の文字はPC-1251のキーにないので捨てる
    return out


# 1行に打てるのは79字まで(行番号と空白も数える)。長い行は途中まで打ってENTERし、
# ▶を80回押して行末へ送ってから続きを打つ。直すときの入力欄も80字ぶんで、入った部分は
# 中間コード(命令は1字)で数えるので、2回目からはその長さを見積もって残りに収まるだけ打つ。
LINE_MAX = 79

# BASICの命令と関数の綴り(PC-1251のBASIC ROMの表から)。中間コードでは1字になる
KEYWORDS = sorted(
    """OUTSTAT RESTORE DEGREE INKEY$ INSTAT LPRINT RADIAN RANDOM RETURN RIGHT$ SETCOM
    AREAD CHAIN CLEAR CLOAD CSAVE DEBUG ERROR GOSUB INPUT LEFT$ LLIST MERGE PAUSE
    PRINT TROFF USING BEEP CALL CHR$ COM$ CONT DATA GOTO GRAD LIST MID$ NEXT PASS
    PEEK POKE READ STEP STOP STR$ THEN TRON WAIT ABS ACS AND ASC ASN ATN COS DEG
    DIM DMS END EXP FOR INT KEY LEN LET LOG MEM NEW NOT OFF REM RND ROM RUN SGN SIN
    SQR TAN VAL <= <> >= IF LN ON OR PI TO""".split(),
    key=len,
    reverse=True,
)


def stored_len(text: str) -> int:
    """打った行をROMが中間コードにしたときの長さの見積もり(行番号は数字+1字)"""
    num, _, body = text.strip().partition(" ")
    n = len(num) + 1
    i, quoted = 0, False
    while i < len(body):
        ch = body[i]
        if ch == '"':
            quoted = not quoted
        elif not quoted:
            if ch == " ":
                i += 1
                continue
            kw = next((k for k in KEYWORDS if body.startswith(k, i)), None)
            if kw:
                n += 1
                i += len(kw)
                continue
        n += 1
        i += 1
    return n


def _cuts(line: str) -> tuple[list[int], list[int]]:
    """切ってよい位置。1つ目は文字列の外の「:」のすぐ後ろ、2つ目はそれ以外に
    切ってもよい位置(文字列の外の空白・「;」・「,」のすぐ後ろ)"""
    good, other, quoted = [], [], False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == ":":
            good.append(i + 1)
        elif not quoted and ch in " ;,":
            other.append(i + 1)
    return good, other


def split_line(line: str) -> list[str]:
    """79字を超える行を、打てる大きさに切り分ける。なるべく「:」(文字列の外)の
    あとで切る。切れるところがなければ、残りをそのまま最後の1つにする"""
    if len(line) <= LINE_MAX:
        return [line]
    good, other = _cuts(line)
    parts, done = [], 0
    while len(line) - done > 0:
        room = LINE_MAX if done == 0 else LINE_MAX - 1 - stored_len(line[:done])
        if len(line) - done <= room:
            parts.append(line[done:])
            break
        fit = [c for c in good if done < c <= done + room]
        if not fit:  # 「:」で切れなければ、文の途中で切る(ROMは入力のときに文法を見ない)
            fit = [c for c in other if done < c <= done + room]
        if not fit:
            parts.append(line[done:])
            break
        parts.append(line[done : fit[-1]])
        done = fit[-1]
    return parts


# ---- 後ろに足すだけでは入らない行 ----
# 行を呼び出して直すときの欄も、行番号の桁と中身で79字まで。中身は、入っている部分は
# 中間コード(命令は1字)で、打ったばかりの部分は打った字で数え、あふれた分は行末から
# 捨てられる。行全体が上限ぎりぎりで後ろのほうに命令があると、命令の綴りを打った
# 時点であふれる。そこで実機で打つときと同じく、打つと縮む命令の綴りを先に前から
# 打ち、縮まない字(変数・数・記号・文字列)をあとから途中に挿入する。
#
# 呼び出した直後(▶を1回)はカーソルが中身の先頭にあり、▶1回で1字(命令も1字)進む。
# SHIFT+▶(INS)は1回で1字あけ、続けて打った字がそこに入る。


def _units(body: str) -> list[str]:
    """行の中身を、ROMが中間コードにするときの区切りに分ける(命令の綴り、1字、
    文字列ひとまとまり、REMから行末まで)。文字列の外の空白は区切りなので捨てる"""
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == " ":
            i += 1
            continue
        if ch == '"':
            j = body.find('"', i + 1)
            j = len(body) - 1 if j < 0 else j
            out.append(body[i : j + 1])
            i = j + 1
            continue
        kw = next((k for k in KEYWORDS if body.startswith(k, i)), None)
        if kw == "REM":  # REMのあとは打ったとおりに入る
            out.append(body[i:])
            break
        if kw:
            out.append(kw)
            i += len(kw)
            continue
        out.append(ch)
        i += 1
    return out


def _stored(unit: str) -> int:
    """区切り1つが中間コードで何字になるか"""
    if unit.startswith("REM"):
        return 1 + len(unit) - 3
    return 1 if unit in KEYWORDS else len(unit)


def _join(units: list[str]) -> str:
    """区切りを続けて打つ文字列にする。続けると別の命令に読まれるときは空白をはさむ"""
    text = "".join(units)
    return text if _units(text) == units else " ".join(units)


def insert_plan(line: str) -> list[tuple[int | None, str]] | None:
    """長い行を、命令を先に打ってから残りを挿入する手順にする。(位置, 打つ字)の列で、
    最初は行番号つきで新しく打つ(位置None)。2つ目からの位置は、中身の何字目の前に
    入れるか(行末に足すときは中身の字数)。どう打っても入らないときはNone"""
    num, _, body = line.strip().partition(" ")
    units = _units(body)
    cap = LINE_MAX - len(num)  # 中身に使える字数
    if not num.isdigit() or not units or sum(_stored(u) for u in units) > cap:
        return None
    shrink = [len(u) > _stored(u) for u in units]  # 打つと縮むもの(命令の綴り)
    steps: list[tuple[int | None, str]] = []
    done: set[int] = set()
    now = 0  # 入っている中身の字数(中間コード)

    def put(idx: list[int], pos: int | None) -> bool:
        nonlocal now
        text = _join([units[k] for k in idx])
        extra = 1 if not steps else 0  # 新しく打つときは行番号のあとの空白も数える
        if now + len(text) + extra > cap:
            return False
        steps.append((None if not steps else pos, text))
        now += sum(_stored(units[k]) for k in idx)
        done.update(idx)
        return True

    # 1. 命令の綴りを前から(行末に足していく)。入るだけまとめて打つ
    piece: list[int] = []
    for k in [k for k, s in enumerate(shrink) if s]:
        text = _join([units[x] for x in piece + [k]])
        if piece and now + len(text) + (0 if steps else 1) > cap:
            if not put(piece, now):
                return None
            piece = []
        piece.append(k)
    if piece and not put(piece, now):
        return None
    # 2. 縮まない字のひと続きを、左から順に入るべき位置へ挿入する
    k = 0
    while k < len(units):
        if k in done:
            k += 1
            continue
        run = [k]
        while run[-1] + 1 < len(units) and run[-1] + 1 not in done:
            run.append(run[-1] + 1)
        pos = sum(_stored(units[x]) for x in done if x < k)
        if not put(run, pos):
            return None
        k = run[-1] + 1
    return steps


def _append_fits(line: str, parts: list[str]) -> bool:
    """後ろに足していく打ち方(split_line)で、どの回も欄からあふれないか"""
    num = line.strip().partition(" ")[0]
    if len(parts[0]) > LINE_MAX:
        return False
    done = parts[0]
    for part in parts[1:]:
        body = done.strip().partition(" ")[2]
        if len(num) + sum(_stored(u) for u in _units(body)) + len(part) > LINE_MAX:
            return False
        done += part
    return True


def keys_for_program(text: str, model: str = "1251") -> list[list[str]]:
    """BASICのプログラムを打ち込む打鍵。長い行は分けて、2つ目からは打ったばかりの
    行を直す形で後ろに足す。それではあふれる行は、命令を先に打ってから残りを挿入する"""
    out: list[list[str]] = []
    for line in normalize(text).split("\n"):
        if not line.strip():
            continue
        line = "".join(ch.upper() if ch.isascii() else ch for ch in line)
        parts = split_line(line)
        plan = None if _append_fits(line, parts) else insert_plan(line)
        if plan is None:
            first, *rest = parts
            out.extend(keys_for(first + "\n", model))
            for part in rest:
                out.extend([["RIGHT"]] * (LINE_MAX + 1))
                out.extend(keys_for(part + "\n", model))
            continue
        num = line.strip().partition(" ")[0]
        for pos, piece in plan:
            if pos is None:
                out.extend(keys_for(f"{num} {piece}\n", model))
                continue
            # ▶1回で呼び出し(カーソルは中身の先頭)、pos回進めて、字数だけINSであけて打つ
            out.extend([["RIGHT"]] * (1 + pos))
            out.extend([["SHIFT"], ["RIGHT"]] * len(piece))
            out.extend(keys_for(piece + "\n", model))
    return out
