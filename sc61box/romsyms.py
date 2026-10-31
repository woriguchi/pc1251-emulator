"""PC-1251・PC-1245のROMのルーチンの入口の名前

『シャープポケットコンピュータ機械語マニュアル』(工学社、1986年)169〜170ページの
入口の表と、ROMの解析で見つけたルーチン。番地はPC-1250/1251/1255(BASIC ROMのどの版でも)と
PC-1245で同じ。DEGとRNDは、版によらない入口(BASIC ROMのJPの表)の番地にした。

アセンブラ(tools/asm61860.py)に`--rom 1251`を付けると、ここの名前が使える。

    LIDP &C698      ; 変数A
    LP   FY
    LII  7
    MVWD            ; 演算Y ← A
    ...
    CAL  FADD       ; 演算X ← 演算Y + 演算X

演算X(内部RAMの20〜27番地)と演算Y(28〜2F番地)は、BASICの変数と同じ8バイトの数。
計算のルーチンは、エラーのときキャリーを1、内部RAMの14番地(ERRNO)を2にして戻る。

マニュアルの表と違うところ
- 減算は0B67(表の0B69は入口の途中で、負の数で答えが狂う)
- 表示ONは11E0(表の11EDはRTN)
- 2進→10進は0D42(符号つき)・0D3B(符号なし)。10E0は数→整数の範囲を決めるだけで、
  続けて1737(F2I)を呼ぶと、演算Xの数が28・29番地の16ビットになる
- キースキャン1F44は、Aにキーの番号ではなく本体の文字コードを返す

J_ONEのルーチンは、Jが1でないと正しく動かない(中でJを入れずにMVBを使う)。
BASICのCALLで入ったときJは1なので、Jを書き換えなければそのまま呼べる。
"""

# 名前と(番地, 働き)
ROUTINES_1251: dict[str, tuple[int, str]] = {
    # 2つの数の計算(演算Y 演算 演算X → 演算X)
    "FADD": (0x0B50, "Y+X"),
    "FSUB": (0x0B67, "Y−X"),
    "FMUL": (0x0B76, "Y×X"),
    "FDIV": (0x0B7F, "Y÷X"),
    "FPOW": (0x0B88, "YのX乗"),
    # 1つの数の関数(演算X → 演算X)
    "FSIN": (0x0B96, "SIN(角度の単位は液晶の記号のビットF83C・F83Dで決まる)"),
    "FCOS": (0x0B9C, "COS"),
    "FTAN": (0x0BA2, "TAN"),
    "FASN": (0x0BAF, "ASN"),
    "FACS": (0x0BB5, "ACS"),
    "FATN": (0x0BBB, "ATN"),
    "FEXP": (0x0BC1, "EXP"),
    "FLN": (0x0BC7, "LN"),
    "FLOG": (0x0BCD, "LOG"),
    "FSQR": (0x0B8F, "SQR"),
    "FABS": (0x0B26, "ABS"),
    "FSGN": (0x0B2B, "SGN"),
    "FINT": (0x0CDE, "INT"),
    "FDMS": (0x0A3A, "DMS(C6BBのビット0を立てたまま戻る。BASICへ戻る前にFROUNDを呼ぶ)"),
    "FDEG": (0x44E6, "DEG(BASIC ROM。CALLで呼ぶ)"),
    "FRND": (0x4018, "RND(BASIC ROM。CALLで呼ぶ。F8B0〜F8B7の乱数の種を書く)"),
    "FROUND": (0x0D01, "演算Xを10桁に丸める"),
    # 数の比較(演算Y 比較 演算X → 演算Xが1か0)
    "FEQ": (0x0C9F, "Y=X"),
    "FNE": (0x0CCC, "Y<>X"),
    "FLT": (0x0CAD, "Y<X"),
    "FGT": (0x0CA9, "Y>X"),
    "FLE": (0x0CB9, "Y<=X"),
    "FGE": (0x0CDA, "Y>=X"),
    # 文字列の比較(24〜27番地と2C〜2F番地にD0・番地・長さ)
    "SEQ": (0x0BE0, "Y=X(J_ONE)"),
    "SNE": (0x0BD7, "Y<>X(J_ONE)"),
    "SLT": (0x0C54, "Y<X"),
    "SGT": (0x0C56, "Y>X"),
    "SLE": (0x0C46, "Y<=X"),
    "SGE": (0x0C3D, "Y>=X"),
    # 文字列
    "FASC": (0x0F6A, "ASC"),
    "FVAL": (0x0F1C, "VAL(文字列の直後の1バイトに00を書く)"),
    "FCHRS": (0x0F8C, "CHR$(J_ONE)"),
    "FSTRS": (0x0EBE, "STR$(液晶RAMのF800〜F837を作業に使う)"),
    # 整数と数
    "I2F": (0x0D42, "28・29番地の符号つき16ビット → 演算X"),
    "U2F": (0x0D3B, "28・29番地の符号なし16ビット → 演算X"),
    "RANGE16": (0x10E0, "F2Iの範囲を−32768〜32767にする(続けてF2Iを呼ぶ)"),
    "F2I": (0x1737, "演算X → 28・29番地の16ビット(J_ONE)"),
    # キー、表示、時間、字の形
    "KEYSCAN": (0x1F44, "キーを1回読む。キャリー1でAに本体の文字コード(押されているときJ_ONE)"),
    "KEYWAIT": (0x1D17, "キーを待つ。自動で電源が切れるまでの時間を戻す(J_ONE)"),
    "KEYWAIT2": (0x1D23, "キーを待つ。電源が切れるまでの時間を戻さない(J_ONE)"),
    "DISPON": (0x11E0, "液晶の表示をつける(Cポート←01)"),
    "DISPOFF": (0x11E5, "液晶の表示を消す(Cポート←00)"),
    "WAIT2MS": (0x1113, "2msのタイマのフラグを1回待つ"),
    "WAIT4MS": (0x110F, "2msのタイマのフラグを2回待つ"),
    "WAIT6MS": (0x110B, "2msのタイマのフラグを3回待つ"),
    "GLYPH": (0x1FBC, "Aの文字の形の番地−1をXへ(J_ONE)"),
}

# 内部RAMの番地
RAM_1251: dict[str, tuple[int, str]] = {
    "FX": (0x20, "演算X(20〜27番地)"),
    "FY": (0x28, "演算Y(28〜2F番地)"),
    "ERRNO": (0x14, "エラーの番号"),
}

# Jが1でないと正しく動かないルーチン
J_ONE = {"SEQ", "SNE", "FCHRS", "F2I", "KEYSCAN", "KEYWAIT", "KEYWAIT2", "GLYPH"}

# BASIC ROMの版(7FFF番地のバイト)
VERSIONS = {
    0xF0: "PC-1250/1251/1255 F0版",
    0x00: "PC-1250/1251/1255 00版",
    0x03: "PC-1250/1251/1255 03版",
    0x01: "PC-1245",
}


def symbols(model: str = "1251") -> dict[str, int]:
    """アセンブラに渡す名前と値。modelは1251(1250・1255も同じ)か1245"""
    if model not in ("1245", "1250", "1251", "1255"):
        raise ValueError(f"ROMのルーチンの名前はPC-1245とPC-1250/1251/1255だけ: {model}")
    out = {name: a for name, (a, _) in ROUTINES_1251.items()}
    out.update({name: a for name, (a, _) in RAM_1251.items()})
    return out
