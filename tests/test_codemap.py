"""逆アセンブルの、命令とデータの見分け(DTCの表、流れのたどり、形からの推し量り、実行した番地、
自分で決めた指定)"""

from helpers import make_app

from sc61box import benchview, codemap, disasm, programs, workbench
from sc61box.machine import new_machine

# PTC 02,C020 / DTC / 表2行 / どれでもないとき / RTN
TABLE = bytes.fromhex("7A02C020 69 01C010 02C018 C01C 37".replace(" ", ""))


def reader(code: bytes, at: int = 0xC000):
    mem = bytearray(0x10000)
    mem[at : at + len(code)] = code
    return mem.__getitem__


def bench_with(blocks, start=None, model="1251"):
    m = new_machine(model, rom=False)
    b = workbench.Bench(m)
    b.load_blocks(blocks, start)
    return m, b


def test_dtc_table_rows():
    """PTCのhの数だけ「値,行き先」の行を読み、どれでもないときの行き先の行を足す"""
    rd = reader(TABLE)
    out = [(i.addr, i.line()) for _, i in zip(range(7), disasm.lines(rd, 0xC000), strict=False)]
    assert out == [
        (0xC000, "PTC 02,C020"),
        (0xC004, "DTC"),
        (0xC005, "DB 01,C0,10 ; →C010"),
        (0xC008, "DB 02,C0,18 ; →C018"),
        (0xC00B, "DB C0,1C ; ほかは→C01C"),
        (0xC00D, "RTN"),
        (0xC00E, "LII 00"),
    ]
    rows = disasm.table(rd, 0xC005, 2)
    assert [r.target for r in rows] == [0xC010, 0xC018, 0xC01C]


def test_dtc_finds_ptc_before():
    """DTCから読み始めても、すぐ手前のPTCから表の行の数がわかる。あいだに飛ぶ命令がなければ
    数命令離れていてもよい。PTCが見つからなければ、DTCのあとも命令として読む"""
    rd = reader(TABLE)
    sizes = [i.size for _, i in zip(range(4), disasm.lines(rd, 0xC004), strict=False)]
    assert sizes == [1, 3, 3, 2]
    rd = reader(bytes.fromhex("7A01C02002056905C010C01C"))  # PTCとDTCのあいだにLIA
    assert disasm.find_ptc(rd, 0xC006) == 1
    rd = reader(bytes.fromhex("7A01C0202C026905C010"))  # あいだにJR
    assert disasm.find_ptc(rd, 0xC006) is None
    rd = reader(bytes.fromhex("6905C010"))
    names = [i.name for _, i in zip(range(3), disasm.lines(rd, 0xC000), strict=False)]
    assert names == ["DTC", "DX", "INCJ"]


def test_dtc_table_in_disasm_and_dump():
    """作業欄の逆アセンブルと.hexの書き出しでも、表は「DB」の行になる。.hexは読み直せる"""
    m, b = bench_with([(0xC000, TABLE)])
    rows = b.disasm_from(0xC000, 6, 0xC000)
    assert [r.addr for r in rows] == [0xC000, 0xC004, 0xC005, 0xC008, 0xC00B, 0xC00D]
    text = b.dump_text(0xC000, 0xC00E)
    assert "C005 01 C0 10    ; DB 01,C0,10 ; →C010" in text
    assert "C00B C0 1C       ; DB C0,1C ; ほかは→C01C" in text
    blocks, errors = programs.parse_hex(text)
    assert not errors and b"".join(d for _a, d in blocks) == TABLE


def test_lc3_table():
    """LC-3(PC-1261)の4076番地のPTC 0F,4056とDTCの表(15行)"""
    prog = programs.load_program("programs/pc1261/lc3.hex")
    mem = bytearray(0x10000)
    for at, data in prog.blocks:
        mem[at : at + len(data)] = data
    rd = mem.__getitem__
    seq = [i for _, i in zip(range(20), disasm.lines(rd, 0x4076), strict=False)]
    assert seq[0].text() == "PTC 0F,4056" and seq[1].name == "DTC"
    assert all(i.name == "DB" and i.size == 3 for i in seq[2:17])
    assert seq[17].addr == 0x40A8 and seq[17].size == 2 and seq[17].note.startswith("ほかは")


def states(b, lo, hi):
    """lo〜hi-1の行の頭ごとの(番地, 種類, わけ)"""
    cm = b.code_map()
    out = []
    for ins in b.lines_from(lo):
        if ins.addr >= hi:
            break
        out.append((ins.addr, *cm.state(ins.addr)))
    return out


def test_follow_flow():
    """条件つきのジャンプは両方の先、呼び出しは呼んだ先と戻ったあとをたどる。RTNと条件なしの
    ジャンプのあとはたどらず、そこの文字と埋め草はデータとみる"""
    # LIA 05 / JRZ C007 / CALL C00E / RTN / "HELLO",00 / JP C013 / FF FF / RTN
    flow = bytes.fromhex("0205 3804 78C00E 37 48454C4C4F00 79C013 FFFF 37".replace(" ", ""))
    _m, b = bench_with([(0xC000, flow)])
    assert states(b, 0xC000, 0xC000 + len(flow)) == [
        (0xC000, "head", "flow"),  # LIA 05
        (0xC002, "head", "flow"),  # JRZ C007
        (0xC004, "head", "flow"),  # CALL C00E
        (0xC007, "head", "flow"),  # RTN
        (0xC008, "data", "guessed"),  # "HELL"
        (0xC00C, "data", "guessed"),  # "O",00
        (0xC00E, "head", "flow"),  # JP C013
        (0xC011, "data", "guessed"),  # FF FF
        (0xC013, "head", "flow"),  # RTN
    ]


def test_flow_stops_at_empty_memory():
    """00かFFが続くところ(何も書いていないRAM)には、流れが着いても命令とみない"""
    _m, b = bench_with([(0xC000, bytes.fromhex("79C100"))])
    cm = b.code_map()
    assert cm.state(0xC000) == ("head", "flow") and cm.state(0xC100) == ("", "")


def test_guess_shapes():
    """どこからもたどれないところは形で推し量る。文字の並びと00・FFの並びはデータ、ない命令や
    RAMの外へ飛ぶ命令があればデータ、RTNで終わるきれいな命令の並びは、わからない命令"""
    code = bytes.fromhex(
        "37"  # C000 RTN(開始番地)
        "414243444546 00"  # C001 "ABCDEF",00
        "FFFFFFFF"  # C008 埋め草
        "0201 42 37"  # C00C LIA 01 / INCA / RTN(どこからも呼ばれない)
        "3C 79 12 34"  # C010 ない命令、JP 1234(RAMの外)
        "0203".replace(" ", "")  # C014
    )
    _m, b = bench_with([(0xC000, code)])
    cm = b.code_map()
    assert cm.state(0xC000) == ("head", "flow")
    assert [cm.state(a)[0] for a in range(0xC001, 0xC00C)] == ["data"] * 11
    assert cm.why[0xC001] == codemap.TEXT and cm.why[0xC008] == codemap.FILL
    assert cm.state(0xC00C) == ("head", "guessed") and cm.state(0xC00D) == ("body", "guessed")
    assert cm.state(0xC00F) == ("head", "guessed")
    assert cm.state(0xC010) == ("data", "guessed") and cm.why[0xC010] == codemap.JUNK
    assert cm.state(0xC011)[0] == cm.state(0xC014)[0] == "data"
    line = next(b.lines_from(0xC001))
    assert line.text() == "DB 41 42 43 44 'ABCD'"


def test_jump_outside_ram_is_data_without_rom():
    """ROMなしでは、名前のわかっているROMのルーチンの入口のほかのRAMの外へ飛ぶ命令はデータとみる。
    KEYSCAN(1F44)を呼ぶ並びは命令とみる"""
    code = bytes.fromhex("37781F443778123437")
    _m, b = bench_with([(0xC000, code)])
    cm = b.code_map()
    assert cm.state(0xC001) == ("head", "guessed")
    assert cm.state(0xC005) == ("data", "guessed")


def test_dtc_targets_are_entries():
    """DTCの表の行き先(どれでもないときも)と、PTCの戻り先は命令の入口になる"""
    code = bytes.fromhex("7A01C00C 69 01C00E C010 37 00 37 00 37 00 37".replace(" ", ""))
    # C000 PTC 01,C00C / C004 DTC / C005 表 / C00A RTN / C00B 00 / C00C RTN ...
    _m, b = bench_with([(0xC000, code)])
    cm = b.code_map()
    assert cm.state(0xC005) == ("data", "flow") and cm.why[0xC005] == codemap.TABLE
    for a in (0xC00C, 0xC00E, 0xC010):
        assert cm.state(a) == ("head", "flow")
    assert cm.state(0xC00A)[1] == "guessed"  # 表のすぐあとのRTNはどこからも来ない


def test_disasm_aligns_after_data():
    """データのあとの命令も、見分けた切れ目で出す(開始番地から読むと文字を命令として読み、
    切れ目がずれる)"""
    code = b"HELLO WORLD\x00" + bytes.fromhex("0201 10C500 37")
    _m, b = bench_with([(0xC000, code)], start=0xC00C)
    rows = b.disasm_from(0xC00E, 5, 0xC00E)
    assert [(r.addr, r.name) for r in rows] == [
        (0xC008, "DB"),
        (0xC00C, "LIA"),
        (0xC00E, "LIDP"),
        (0xC011, "RTN"),
        (0xC012, "LII"),  # 書いた範囲の外は、これまでどおり命令として読む
    ]
    assert b.ins_at(0xC00F) == 0xC00E and b.ins_at(0xC006) == 0xC004


def test_dump_text_table_and_string():
    """.hexの書き出しでは、データの行も「DB」の注釈になる。形(番地とバイト)は変わらず、
    読み直せる"""
    code = bytes.fromhex(
        "48454C4C4F00"  # C000 "HELLO",00
        "7A01C013 69 05C011 C013"  # C006 PTC 01,C013 / DTC / 表
        "37 0201 37".replace(" ", "")  # C010 RTN / C011 LIA 01 / C013 RTN
    )
    _m, b = bench_with([(0xC000, code)], start=0xC006)
    text = b.dump_text(0xC000, 0xC000 + len(code))
    assert text.splitlines() == [
        "C000 48 45 4C 4C ; DB 48 45 4C 4C 'HELL'",
        "C004 4F 00       ; DB 4F 00 'O.'",
        "C006 7A 01 C0 13 ; PTC 01,C013",
        "C00A 69          ; DTC",
        "C00B 05 C0 11    ; DB 05,C0,11 ; →C011",
        "C00E C0 13       ; DB C0,13 ; ほかは→C013",
        "C010 37          ; RTN",
        "C011 02 01       ; LIA 01",
        "C013 37          ; RTN",
    ]
    blocks, errors = programs.parse_hex(text)
    assert not errors and b"".join(d for _a, d in blocks) == code
    rows, skipped = workbench.parse_dump(text)
    assert not skipped and b"".join(d for _a, d, _t in rows) == code


# LIA C0 / PUSH / LIA 10 / PUSH / RTN(積んだC010へ飛ぶ) / … / C010: LIA 05 / RTN
PUSHJUMP = bytes.fromhex("02C0 34 0210 34 37".replace(" ", "")) + bytes(9) + bytes.fromhex("020537")


def test_executed_marks_heads():
    """実行した番地は、流れでたどれなくても確かな命令の頭になる。書き換えた番地の印は消える"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    b.load_blocks([(0xC000, PUSHJUMP)], 0xC000)
    assert b.code_map().state(0xC010) == ("head", "guessed")
    b.run()
    for _ in range(30):
        app.frame()
        if b.state == "edit":
            break
    assert b.state == "edit" and app.m.cpu.ram[2] == 0x05
    cm = b.code_map()
    assert cm.state(0xC000) == ("head", "executed") and cm.state(0xC010) == ("head", "executed")
    assert cm.state(0xC012) == ("head", "executed") and not b.executed[0xC001]
    b.write(0xC010, 0x02)
    assert not b.executed[0xC010] and b.executed[0xC012]
    app.close()


def test_step_marks_executed():
    """1命令ずつ進めても、実行した番地に印がつく"""
    m, b = bench_with([(0xC000, PUSHJUMP)], start=0xC000)
    b.step()  # 開始番地の前で止まる
    for _ in range(6):
        b.step()
    assert m.cpu.pc == 0xC012 and b.executed[0xC010] and not b.executed[0xC012]


def test_save_restore_codemap_inputs():
    """BASICのCALLの番地、実行した番地、自分で決めた指定は、状態と一緒に保存して戻せる"""
    m, b = bench_with([(0xC000, PUSHJUMP)], start=0xC000)
    b.calls = [0xC000, 0xC010]
    b.executed[0xC010] = b.executed[0xC012] = 1
    b.marks = {0xC003: "data", 0xC005: "code"}
    info = b.save()
    assert info["executed"] == [[0xC010, 0xC011], [0xC012, 0xC013]]
    other = workbench.Bench(m)
    other.restore(info)
    assert other.calls == [0xC000, 0xC010] and other.marks == b.marks
    assert other.executed == b.executed
    other.restore({"executed": "x", "marks": [[1, "bad"], ["x", "data"]], "calls": [-1, 5]})
    assert other.marks == {} and other.calls == [5] and not any(other.executed)


def test_user_marks_override():
    """自分で決めた指定は、流れと推し量りより先に効く。データの指定は次の指定の手前まで。
    指定を消せば推し量りに戻る"""
    # RTN / "ABCDEF" / LIA 01 / LIA 02 / RTN
    code = bytes.fromhex("37 414243444546 0201 0202 37".replace(" ", ""))
    _m, b = bench_with([(0xC000, code)])
    cm = b.code_map()
    assert cm.state(0xC001) == ("data", "guessed")
    assert b.set_mark(0xC001, "code") == "C001番地から命令にしました"
    cm = b.code_map()
    assert cm.state(0xC001) == ("head", "user") and cm.state(0xC002) == ("head", "flow")
    assert b.set_mark(0xC001, "code") == "いまの指定です"
    b.set_mark(0xC000, "data")
    cm = b.code_map()
    assert cm.state(0xC000) == ("data", "user") and cm.state(0xC001) == ("head", "user")
    kinds = [cm.state(a)[0] for a in range(0xC000, 0xC00C)]
    assert kinds == ["data"] + ["head"] * 6 + ["head", "body"] * 2 + ["head"]  # DECIからRTNまで
    b.set_mark(0xC001, None)
    b.set_mark(0xC000, None)
    b.set_start_at(0xC007)
    b.set_mark(0xC009, "data")  # 2つ目のLIAの頭から
    cm = b.code_map()
    assert cm.state(0xC007) == ("head", "flow")
    assert [cm.state(a) for a in range(0xC009, 0xC00C)] == [("data", "user")] * 3
    assert b.set_mark(0xC100, None) == "指定はありません"
    assert b.mark_refusal(0x1000, "data") == "RAMの外です"


def test_bench_menu_marks():
    """作業欄の右クリックのメニューで、その番地からデータ・命令にし、指定を消せる"""
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    b.load_blocks([(0xC000, bytes.fromhex("0201 0202 37"))], 0xC000)
    app.frame()
    hit = next(h for h in app.bench_view.hits if h[1] == "goto" and h[2] == 0xC002)
    app.bench_menu(hit[0].center)
    labels = [i.label for i in app.popup_items()]
    assert not app.popup_items()[labels.index("C002番地の指定を消す")].enabled
    app.popup_run(labels.index("C002番地からデータにする"))
    assert b.marks == {0xC002: "data"} and b.code_map().state(0xC002) == ("data", "user")
    app.bench_menu(hit[0].center)
    assert not app.popup_items()[labels.index("C002番地からデータにする")].enabled
    app.popup_run(labels.index("C002番地の指定を消す"))
    assert b.marks == {}
    app.close()


def test_user_code_mark_on_zeros():
    """自分で命令に決めた番地は、00が並んでいても命令にする"""
    _m, b = bench_with([(0xC000, bytes.fromhex("37" + "00" * 6 + "37"))])
    b.set_mark(0xC001, "code")
    cm = b.code_map()
    assert cm.state(0xC001) == ("head", "user") and cm.state(0xC003)[0] == "data"


def test_parse_data_directive():
    """# data: の値は「,」で区切った範囲か番地。終わりは含む(C100-C17FはC17Fまで)"""
    assert programs.parse_data("C100-C17F, &C200〜&C20F,C300") == (
        [(0xC100, 0xC180), (0xC200, 0xC210), (0xC300, None)],
        "",
    )
    assert programs.parse_data("C100-C0FF")[1] == "C100-C0FF"
    assert programs.parse_data("C100, XYZ")[1] == "XYZ"
    assert programs.data_line([(0xC100, 0xC180), (0xC200, 0xC201)]) == (
        "# data: C100-C17F, C200-C200\n"
    )
    assert programs.data_line([]) == ""


# LIA 01 / RTN / 8バイトの表 / LIA 02 / RTN(表のあとのコードはどこからもたどれない)
WITH_TABLE = bytes.fromhex("0201 37 0102030405060708 0202 37".replace(" ", ""))


def test_data_directive_round_trip(tmp_path, monkeypatch):
    """自分で決めたデータの範囲は、書き出した.hexの# data: に入り、読み込むと同じ範囲の
    データになる。範囲の終わりから先は推し量りに戻る"""
    monkeypatch.setenv("SC61BOX_PROGRAMS", str(tmp_path))
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    b.paste(_lines(0xC000, WITH_TABLE))
    b.set_mark(0xC003, "data")
    b.set_mark(0xC00B, "code")
    assert b.data_spans() == [(0xC003, 0xC00B)]
    app.bench_export()
    app.close()
    path = next(tmp_path.rglob("dump-*.hex"))
    text = path.read_text(encoding="utf-8")
    assert "# data: C003-C00A\n" in text
    prog = programs.load_program(str(path))
    assert prog.data == [(0xC003, 0xC00B)] and not prog.errors
    app = make_app(scale=0.5, frames=2, norom=True)
    b = app.bench
    app.open_program(prog)
    assert b.marks == {0xC003: "data", 0xC00B: "end"}
    cm = b.code_map()
    assert [cm.state(a)[0] for a in range(0xC003, 0xC00B)] == ["data"] * 8
    assert cm.state(0xC00B)[1] != "user"  # 範囲の先は推し量り
    assert b.data_spans() == [(0xC003, 0xC00B)]
    app.close()


def test_data_directive_with_rom(tmp_path):
    """ROMのある本体でも、読み込んだ# data: の範囲は、ダンプを書いたあとも残る"""
    (tmp_path / "t.hex").write_text(
        "# data: C003-C00A\n" + _lines(0xC000, WITH_TABLE), encoding="utf-8"
    )
    app = make_app(scale=0.5, frames=40)
    app.open_program(programs.load_program(str(tmp_path / "t.hex")))
    for _ in range(5):
        app.frame()
    assert app.bench.marks.get(0xC003) == "data" and app.bench.marks.get(0xC00B) == "end"
    app.close()


def test_bad_data_directive(tmp_path):
    (tmp_path / "t.hex").write_text("# data: C100-ZZ\nC000 37\n", encoding="utf-8")
    prog = programs.load_program(str(tmp_path / "t.hex"))
    assert prog.errors == ["t.hex: # data: のC100-ZZが読めない"]


def _lines(addr, data):
    return "".join(
        f"{addr + i:04X} {data[i : i + 8].hex().upper()}\n" for i in range(0, len(data), 8)
    )


def test_shared_hex_brings_data(tmp_path):
    """# hex: と# after: で使うダンプに書いた# data: の範囲も取り込む"""
    (tmp_path / "shared.hex").write_text("# data: C001-C004\nC000 37 02 01 02 02 37\n")
    (tmp_path / "more.hex").write_text("# data: C101\nC100 37 00\n")
    (tmp_path / "caller.bas").write_text(
        "# hex: shared.hex\n# after: more.hex\n10 CALL &C000\n", encoding="utf-8"
    )
    prog = programs.load_program(str(tmp_path / "caller.bas"))
    assert prog.data == [(0xC001, 0xC005), (0xC101, None)] and not prog.errors


def test_overlapping_data_ranges_merge():
    """重なる範囲と続いている範囲は1つにまとめる。範囲の中の番地だけの指定は捨てる"""
    _m, b = bench_with([(0xC000, b"\x37" * 0x30)])
    b.use_data([(0xC001, 0xC011), (0xC009, 0xC019), (0xC019, 0xC01C), (0xC00C, None)])
    assert b.prog_data == [(0xC001, 0xC01C)]
    assert b.marks == {0xC001: "data", 0xC01C: "end"}
    cm = b.code_map()
    assert all(cm.state(a) == ("data", "user") for a in range(0xC001, 0xC01C))
    assert b.data_spans() == [(0xC001, 0xC01C)]


def test_rewrite_through_mirror_forgets_executed():
    """ミラーの番地から実行した命令も、RAMの番地を書き換えれば「実行した」ではなくなる"""
    m, b = bench_with([(0xB800, bytes.fromhex("020137"))], start=0xB000)
    b.step()
    b.step()  # ミラーのB000でLIA 01を実行
    assert b.code_map().state(0xB800) == ("head", "executed")
    b.write(0xB800, 0x37)
    assert b.code_map().state(0xB800)[1] != "executed"
    b.abandon()
    b.step()
    b.step()
    b.paste("B800 02")  # 貼り付けでも
    assert b.code_map().state(0xB800)[1] != "executed"
    b.step()
    b.step()
    b.undo()  # 取り消しでも
    assert b.code_map().state(0xB800)[1] != "executed"


def test_table_note_follows_language():
    """DTCの表の添え書きは、言語を切り替えると切り替えた言語で出す"""
    from sc61box import i18n

    _m, b = bench_with([(0xC000, bytes.fromhex("7A00C00769C00737"))], start=0xC000)
    notes = [ins.note for ins in b.disasm_from(0xC000, 5, 0xC000) if ins.note]
    assert notes == ["ほかは→C007"]
    i18n.set_language("en")
    notes = [ins.note for ins in b.disasm_from(0xC000, 5, 0xC000) if ins.note]
    assert notes == ["else→C007"]


def test_loading_cuts_data_mark():
    """データの指定の途中に別のプログラムを読み込むと、指定は読み込んだ所の手前で切れ、
    読み込んだ命令はデータにならない"""
    m, b = bench_with([(0xC000, b"\x37" * 0x30)])
    b.set_mark(0xC001, "data")
    assert b.code_map().state(0xC010) == ("data", "user")
    b.load_blocks([(0xC010, bytes.fromhex("020137"))], 0xC010)
    cm = b.code_map()
    assert cm.state(0xC00F) == ("data", "user")
    assert cm.state(0xC010) == ("head", "flow") and cm.state(0xC012) == ("head", "flow")
    assert b.data_spans() == [(0xC001, 0xC010)]


def test_confirming_default_start_updates_map():
    """まだ決めていない開始番地と同じ番地に決めても、そこから流れをたどり直す"""
    _m, b = bench_with([(0xC000, bytes.fromhex("0201 0202 37"))])
    b.start_by = ""  # 読み込みで決まった開始番地を、まだ決めていないものに戻す
    assert b.code_map().state(0xC000)[1] == "guessed"
    b.set_start_at(0xC000)
    assert b.code_map().state(0xC000) == ("head", "flow")


def test_unterminated_code_reason():
    """命令としては読めてもRTNかジャンプで終わらない並びはデータとし、そのわけを分ける"""
    # RTN / 0000×4(埋め草) / LIA 01 / LIB 02(終わりなし)
    _m, b = bench_with([(0xC000, bytes.fromhex("37 00000000 0201 0302".replace(" ", "")))])
    b.start_by = ""
    cm = b.code_map()
    assert cm.state(0xC005) == ("data", "guessed") and cm.why[0xC005] == codemap.NOEND
    assert "終わらない" in benchview.why_text(cm, 0xC005)


def test_after_keeps_own_data_range(tmp_path):
    """# after: で後から書くダンプが、いま読み込んでいるプログラムの# data: の範囲を切らない"""
    (tmp_path / "late.hex").write_text(_lines(0xC010, b"\x37" * 0x10), encoding="utf-8")
    (tmp_path / "t.hex").write_text(
        "# data: C001-C01F\n# after: late.hex\n" + _lines(0xC000, b"\x37" * 0x10),
        encoding="utf-8",
    )
    app = make_app(scale=0.5, frames=40)
    app.open_program(programs.load_program(str(tmp_path / "t.hex")))
    for _ in range(200):
        app.frame()
        if not app.typer.busy:
            break
    for _ in range(5):
        app.frame()
    b = app.bench
    assert app.m.mem[0xC01F] == 0x37
    assert b.marks.get(0xC001) == "data" and 0xC010 not in b.marks
    assert b.data_spans() == [(0xC001, 0xC020)]
    app.close()


def test_load_through_mirror_cuts_data_mark():
    """ミラーの番地へ読み込んでも、RAMの番地にあるデータの指定を切る"""
    _m, b = bench_with([(0xB800, b"\x37" * 0x30)])
    b.set_mark(0xB801, "data")
    b.load_blocks([(0xB010, bytes.fromhex("020137"))], 0xB810)
    assert b.marks == {0xB801: "data", 0xB810: "end"}
    cm = b.code_map()
    assert cm.state(0xB80F) == ("data", "user") and cm.state(0xB810) == ("head", "flow")
    b.use_data([(0xB020, 0xB028)])  # # data: をミラーの番地で書いても、RAMの番地に置く
    assert b.marks.get(0xB820) == "data" and b.marks.get(0xB828) == "end"


def test_data_range_across_mirror_edge():
    """ミラーの境をまたぐ# data: の範囲は、RAMの番地のひと続きごとに分けて置く(PC-1251の
    B7FC〜B803は、BFFC〜BFFFとB800〜B803)"""
    _m, b = bench_with([(0xB800, b"\x37" * 0x10), (0xBFF0, b"\x37" * 0x10)])
    b.use_data([(0xB7FC, 0xB804)])
    assert sorted(b.prog_data) == [(0xB800, 0xB804), (0xBFFC, 0xC000)]
    cm = b.code_map()
    assert all(cm.state(a) == ("data", "user") for a in [*range(0xB800, 0xB804),
                                                          *range(0xBFFC, 0xC000)])  # fmt: skip
    assert cm.state(0xB804)[1] != "user"
