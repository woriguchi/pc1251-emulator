"""画面に出す文の英語(i18n.trが引く表)。鍵は、tr()に渡す日本語の文そのもの

値が組のものは(1のときの形, ほかの形)で、trに渡すnの値で選ぶ。
"""

EN: dict[str, str | tuple[str, str]] = {
    # ---- 区切りと短い書き方 ----
    "、": ", ",
    "。": ". ",
    "・": ", ",
    "{lo:04X}〜{last:04X}": "{lo:04X}-{last:04X}",
    "{name}({what})": "{name} ({what})",
    "{note}({key})": "{note} ({key})",
    # ---- キーの説明 ----
    "パソコンのキーとポケコンのキーで違うもの(ほかのキーはそのまま打てます)": (
        "Keys that differ from the pocket computer (other keys type as they are)"
    ),
    "Tab: SHIFT   Option(WindowsはAlt): DEF   Delete: CL   Esc: BRK(電源が切れていればON)": (
        "Tab: SHIFT   Option (Alt on Windows): DEF   Delete: CL   Esc: BRK (ON when off)"
    ),
    "Backspace: 1字消す(◀とSHIFT+◀を押す)   \\(バックスラッシュ): ¥": (
        "Backspace: delete a character (◀ and SHIFT+◀)   \\ (backslash): ¥"
    ),
    "F1〜F4・{c}↑↓: モードスイッチ   F5・{c}R: 裏のRESETボタン": (
        "F1-F4, {c}↑↓: mode switch   F5, {c}R: RESET button on the back"
    ),
    "{c}K: 矢印キーを数字キーの8・2・4・6にする・戻す(テンキーの代わり)": (
        "{c}K: arrow keys press 8, 2, 4, 6 or not (for PCs without a keypad)"
    ),
    "エミュレータの操作は下の操作欄のメニューから(ショートカットはメニューに出ます)": (
        "Emulator commands are in the menus of the bar below (shortcuts are shown there)"
    ),
    "Tab: SHIFT   Option(WindowsはAlt): DEF   F8: カナ   Esc: BRK(電源が切れていればON)": (
        "Tab: SHIFT   Option (Alt on Windows): DEF   F8: カナ   Esc: BRK (ON when off)"
    ),
    "Delete: DEL   Insert: INS   Home: CLS   Backspace: 1字消す(◀とDELを押す)   \\: ¥": (
        "Delete: DEL   Insert: INS   Home: CLS   Backspace: delete a character (◀ and DEL)   \\: ¥"
    ),
    "F1・F2: MODEキーでRUN・PROにする   F3・F4・{c}↑↓: 電源スイッチ   F5・{c}R: RESET": (
        "F1, F2: RUN, PRO with the MODE key   F3, F4, {c}↑↓: power switch   F5, {c}R: RESET"
    ),
    "ROMなしの作業欄(右)": "Workbench without ROM (on the right)",
    "0〜9・A〜F: ダンプを書く   Enter: 次の行   Space: 番地からバイトへ   Tab: 番地を打って飛ぶ": (
        "0-9, A-F: write the dump   Enter: next line   Space: from address to bytes"
        "   Tab: type an address to jump"
    ),
    "{c}G: 実行・続ける   {s}{c}G: カーソルから実行   {c}.: 一時停止   Esc: 編集に戻る": (
        "{c}G: run, continue   {s}{c}G: run from the cursor   {c}.: pause   Esc: back to editing"
    ),
    "{c}J: 次の1命令だけ実行   {s}{c}J: CALLの呼び先を戻るまで実行   {c}B: 止める所": (
        "{c}J: step one instruction   {s}{c}J: step over a CALL   {c}B: breakpoint"
    ),
    "{c}V: 本のダンプリストや.hexを貼り付け   {c}Z: 取り消す   {s}{c}Z: やり直す": (
        "{c}V: paste a dump listing or .hex   {c}Z: undo   {s}{c}Z: redo"
    ),
    "PageUp・PageDown: 1画面   Home・End({c}←→): 行の頭・終わり   {c}↑↓: 開始番地・終わり": (
        "PageUp, PageDown: one screen   Home, End ({c}←→): start, end of line"
        "   {c}↑↓: start address, end"
    ),
    "{c}E: .hexに書き出す   {s}{c}E: ダンプリストの形(8バイト:チェックサム)で書き出す": (
        "{c}E: export to .hex   {s}{c}E: export as a dump list (8 bytes:checksum)"
    ),
    "範囲の行をクリック: 書き出す範囲を打つ   {c}O: プログラムの一覧(.hexのマシン語だけを使う)": (
        "Click the range line: type the export range"
        "   {c}O: program list (only the machine code of .hex files)"
    ),
    "実行中のキーは本体へ(Tab: SHIFT  Option: DEF  Delete: CL  Esc: BRK)": (
        "While running, keys go to the machine (Tab: SHIFT  Option: DEF  Delete: CL  Esc: BRK)"
    ),
    # ---- 操作欄 ----
    "プログラム": "Programs",
    "本体": "Machine",
    "表示・入力": "View & Input",
    "表示": "View",
    "一覧、書き出し、貼り付け(一覧は{c}O)": "List, export, paste (list: {c}O)",
    "状態の保存と復元、スイッチ、RESET": "Save and load state, switch, RESET",
    "キーの説明({c}/)、矢印キー・ゲームパッドの割り当て、液晶だけ、画面の画像、印字": (
        "Key help ({c}/), arrow keys, gamepad, LCD only, screenshot, printout"
    ),
    "止めている実行を続ける({c}P)": "Resume execution ({c}P)",
    "実行を再開": "Resume",
    "再開": "Resume",
    "CPUの実行を止める({c}P)。録画は止まりません": "Pause the CPU ({c}P). Recording goes on",
    "実行を一時停止": "Pause",
    "一時停止": "Pause",
    "実行の速さを選ぶ({c}Tで速く、{s}{c}Tで遅く)": "Choose the speed ({c}T faster, {s}{c}T slower)",
    "速さ {speed}": "Speed {speed}",
    "録画を始める({s}{c}R)": "Start recording ({s}{c}R)",
    "録画": "Record",
    "録画を止める({s}{c}R)か、一時停止する({s}{c}P)": (
        "Stop ({s}{c}R) or pause ({s}{c}P) the recording"
    ),
    "録画を一時停止中 {clock}": "Rec paused {clock}",
    "録画中 {clock}": "Recording {clock}",
    "{n}KBカード": "{n} KB card",
    "矢印→8246": "Arrows→8246",
    "テープ": "Tape",
    "実行を一時停止中({c}Pで再開)": "Paused ({c}P resumes)",
    # ---- メニュー ----
    "実行を再開する": "Resume execution",
    "実行を一時停止する": "Pause execution",
    "ダンプをファイル(.hex)に書き出す": "Export dump to file (.hex)",
    "ダンプリストの形で書き出す": "Export as dump list",
    "8バイト:チェックサムの行": "Lines of 8 bytes:checksum",
    "クリップボードからダンプを貼り付ける": "Paste dump from clipboard",
    "プログラムをファイルに書き出す": "Export program to file",
    "クリップボードから打ち込む": "Type in from clipboard",
    "プログラムの一覧…": "Program list…",
    "置き場所のフォルダを開く": "Open program folder",
    "ダンプの書き込みを取り消す": "Undo dump edit",
    "ダンプの書き込みをやり直す": "Redo dump edit",
    "読み込んだプログラムの説明": "Help for loaded program",
    "いまの状態を保存(どこでもセーブ)": "Save state",
    "保存した状態に戻す": "Load state",
    "{title}を読み込む前": "before loading {title}",
    "プログラムを読み込む前に戻す": "Undo program load",
    "スイッチ {name}": "Switch {name}",
    "RESETボタンを押す": "Press RESET button",
    "矢印キーを↑↓◀▶に戻す": "Arrow keys back to ↑↓◀▶",
    "矢印キーを8・2・4・6にする": "Arrow keys as 8, 2, 4, 6",
    "キーの説明": "Key help",
    "本体の絵を出す": "Show the calculator",
    "液晶だけのあいだは出せません": "Not available while showing only the LCD",
    "◀ 作業欄": "◀ Workbench",
    "作業欄 ▶": "Workbench ▶",
    "マシン語の作業欄をしまう({c}D)": "Hide the machine-code workbench ({c}D)",
    "マシン語の作業欄を出す({c}D)": "Show the machine-code workbench ({c}D)",
    "本体を出す": "Calculator",
    "本体の絵を出す(窓の大きさは固定に戻ります)": (
        "Show the calculator (the window size is fixed again)"
    ),
    "液晶だけにする(窓を広げられる)": "LCD only (window can be resized)",
    "本体の絵を出さず、液晶だけを見せる(窓の大きさを変えられる)": (
        "Show only the LCD without the calculator picture (the window can be resized)"
    ),
    "画面を画像で保存": "Save screenshot",
    "マシン語の作業欄をしまう": "Hide workbench",
    "マシン語の作業欄を出す": "Show workbench",
    "録画を再開する": "Resume recording",
    "録画を一時停止する": "Pause recording",
    "録画を止めて保存": "Stop and save recording",
    "印字の保存先を開く": "Open printout folder",
    "プリンタの紙をしまう": "Put the paper away",
    "まだ保存していません": "Not saved yet",
    "{when}に保存": "Saved {when}",
    "表示を日本語にしました": "Language: English",
    # 作業欄の右クリック
    "いまの開始番地です": "This is the start address",
    "{addr:04X}番地を開始番地にする": "Set {addr:04X} as start address",
    "実行中です": "Running",
    "{addr:04X}番地から実行する": "Run from {addr:04X}",
    "ROMなしでは使えない番地です": "Not usable without ROM",
    "{addr:04X}番地の止める所を外す": "Remove breakpoint at {addr:04X}",
    "{addr:04X}番地の止める所を置く": "Set breakpoint at {addr:04X}",
    # ---- 知らせ ----
    "メニューの「読み込む前に戻す」で元に戻せます": '"Undo program load" in the menu goes back',
    "{addr:04X}番地の止める所を置きました": "Breakpoint set at {addr:04X}",
    "{addr:04X}番地の止める所を外しました": "Breakpoint removed at {addr:04X}",
    "{addr:04X}番地はROMなしでは使えないので、止める所を置けません": (
        "{addr:04X} is not usable without ROM, so no breakpoint can go there"
    ),
    "{name}を読み込みません。{addr:04X}番地はRAMの外です": (
        "{name} not loaded: {addr:04X} is outside RAM"
    ),
    "{name}を読み込みません。# ram: の{lo:04X}-{hi:04X}はROMか液晶RAMにかかります": (
        "{name} not loaded: # ram: {lo:04X}-{hi:04X} overlaps ROM or LCD RAM"
    ),
    "ROMがないので、ROMなしでマシン語だけを動かします(右の作業欄)": (
        "No ROM found, so only machine code runs (workbench on the right)"
    ),
    "操作は下の操作欄のボタンから。キーの説明は{c}/": (
        "Use the buttons in the bar below. Key help: {c}/"
    ),
    "{name}が見つかりません": "{name} not found",
    "開始番地を{addr:04X}にしました": "Start address set to {addr:04X}",
    "実行中は打てません。{c}Aか右クリックで、カーソルの所を開始番地にできます": (
        "Cannot type while running. {c}A or right-click sets the start address at the cursor"
    ),
    "{name}を読み込みません。{why}": "{name} not loaded. {why}",
    "{name}はBASICとROMのルーチンを使うプログラムなので、ROMなしでは使えません": (
        "{name} uses BASIC and ROM routines, so it needs the ROM"
    ),
    "{name}はBASICのプログラムなので、ROMなしでは使えません": (
        "{name} is a BASIC program, so it needs the ROM"
    ),
    "{name}を読み込みました({n}バイト、開始番地{addr:04X})。{c}Gで実行": (
        "Loaded {name} ({n} byte, start address {addr:04X}). {c}G runs it",
        "Loaded {name} ({n} bytes, start address {addr:04X}). {c}G runs it",
    ),
    "貼り付けた文字にダンプの行がありません": "No dump lines in the pasted text",
    "{n}バイトを書きました": ("Wrote {n} byte", "Wrote {n} bytes"),
    "チェックサムが合わない行: {where}": "Checksum mismatch at {where}",
    "RAMの外の{n}バイトは書けません": (
        "{n} byte outside RAM not written",
        "{n} bytes outside RAM not written",
    ),
    "開始番地は{addr:04X}": "Start address {addr:04X}",
    "書き出すダンプがありません": "No dump to export",
    "{where}(マシン語の作業欄から書き出し)": "{where} (exported from the machine-code workbench)",
    "書き出せません: {error}": "Cannot export: {error}",
    "{name}を書き出しました({n}バイト)。置き場所: {folder}": (
        "Exported {name} ({n} byte). Folder: {folder}",
        "Exported {name} ({n} bytes). Folder: {folder}",
    ),
    "矢印キー → 数字キーの8・2・4・6": "Arrow keys → number keys 8, 2, 4, 6",
    "矢印キー → ↑↓◀▶": "Arrow keys → ↑↓◀▶",
    "読み込みをやめました(途中まで入っています)。{hint}": "Loading stopped (partly loaded). {hint}",
    "印字を保存できません: {error}": "Cannot save the printout: {error}",
    "印字を{path}に保存しました": "Printout saved to {path}",
    "実行を一時停止しました。{c}Pか操作欄の「実行を再開」で続けます": (
        'Paused. {c}P or "Resume" in the bar continues'
    ),
    "実行を再開しました": "Resumed",
    "実行していません。{c}Gで開始番地から実行します": (
        "Not running. {c}G runs from the start address"
    ),
    "読み込む前に戻せません: {error}": "Cannot undo the load: {error}",
    "{title}を読み込む前に戻しました": "Back to before loading {title}",
    "{program}なので、{model}では読み込みません": "{program}: not loaded on the {model}",
    "{name}を読み込みません。{line}行が長すぎて、打ち込むと欠けます(行番号と中身で79字まで)": (
        "{name} not loaded. Line {line} is too long to type in (79 characters with the line number)"
    ),
    "{name}を読み込みません。「{text}」の行が長すぎて、打ち込むと欠けます"
    "(行番号と中身で79字まで)": (
        '{name} not loaded. The line "{text}" is too long to type in'
        " (79 characters with the line number)"
    ),
    "{name}を読み込みません。BASICが{size}バイトで、RAMに入りません(使えるのは{room}バイト)": (
        "{name} not loaded. The BASIC is {size} bytes and does not fit in RAM ({room} bytes free)"
    ),
    "{name}: 中身がありません": "{name}: empty",
    "{name}を読み込みました({n}バイト)": ("Loaded {name} ({n} byte)", "Loaded {name} ({n} bytes)"),
    "{name}はRAMに入りきりませんでした({line}行から{n}行が入っていません)。"
    "実行と、そのあとの書き込みはやめました。{hint}": (
        "{name} did not fit in RAM ({n} line from line {line} missing)."
        " Run and later writes skipped. {hint}",
        "{name} did not fit in RAM ({n} lines from line {line} missing)."
        " Run and later writes skipped. {hint}",
    ),
    "{name}の{line}行が、思ったとおりに入りませんでした。実行と、そのあとの書き込みはやめました。"
    "{hint}": (
        "Line {line} of {name} did not go in as expected. Run and later writes skipped. {hint}"
    ),
    "{name}を読めません({error})": "Cannot read {name} ({error})",
    "テープ {name} をセットしました。CLOADかCLOAD Mで読み込みます": (
        "Tape {name} inserted. Load it with CLOAD or CLOAD M"
    ),
    "{name}は、.basに「# bin: 名前.bin &C300」と書いて読み込みます": (
        'To load {name}, write "# bin: name.bin &C300" in a .bas'
    ),
    "{name}を読めません": "Cannot read {name}",
    "打ち込みが終わってから書き出してください": "Export after typing in has finished",
    "書き出すプログラムがありません": "No program to export",
    "{path}に書き出しました": "Exported to {path}",
    "テープの音を書き出せません: {error}": "Cannot write the tape audio: {error}",
    "テープの音を{path}に書き出しました": "Tape audio written to {path}",
    "状態を保存できません: {error}": "Cannot save state: {error}",
    "状態を保存しました。{s}{c}Lで戻せます": "State saved. {s}{c}L loads it",
    "保存した状態がありません": "No saved state",
    "状態を読み込めません: {error}": "Cannot load state: {error}",
    "保存した状態に戻しました": "State loaded",
    "画面の画像を保存できません: {error}": "Cannot save the screenshot: {error}",
    "{path}に保存しました": "Saved to {path}",
    "録画を始められません: {error}": "Cannot start recording: {error}",
    "録画を始めました。止めて保存するときは、もう一度{s}{c}Rを押します": (
        "Recording. Press {s}{c}R again to stop and save"
    ),
    "録画を保存しています…": "Saving the recording…",
    "録画を保存できません: {error}": "Cannot save the recording: {error}",
    "録画を{path}に保存しました({n}秒)": (
        "Recording saved to {path} ({n} second)",
        "Recording saved to {path} ({n} seconds)",
    ),
    "録画を一時停止しました": "Recording paused",
    "録画を続けます": "Recording resumed",
    "録画を止めました: {error}": "Recording stopped: {error}",
    "{name}を読み込みました": "Loaded {name}",
    "テープが終わりました": "End of tape",
    "保存先(クリックで開く)": "Saved in (click to open)",
    "{name}を打ち込み中… {pct}%(Escでやめる)": "Typing in {name}… {pct}% (Esc stops)",
    "{name}を読み込み中… {pct}%(Escでやめる)": "Loading {name}… {pct}% (Esc stops)",
    "RAMを保存できません: {error}": "Cannot save RAM: {error}",
    "{title}({when}の書き出し)": "{title} (exported {when})",
    # ---- コマンド ----
    "SHARP PC-1251/PC-1245/PC-1261/PC-1350エミュレータ": (
        "SHARP PC-1251/PC-1245/PC-1261/PC-1350 emulator"
    ),
    "読み込むプログラム(.bas/.hexのパスか、置き場所にある名前)": (
        "Program to load (path to a .bas/.hex, or a name in the program folder)"
    ),
    "読み込んだあと実行する": "Run it after loading",
    "拡大率": "Window scale",
    "起動後にこのファイルの中身をキー入力する": "Type in the contents of this file after starting",
    "16進ダンプ(番地 データ)をRAMに書き込む": "Write a hex dump (address data) into RAM",
    "保存したRAMを読まず、終了時にも保存しない": (
        "Do not load the saved RAM, and do not save it on exit"
    ),
    "音を出さない": "No sound",
    "液晶の残像の強さ(0で残像なし)": "Strength of the LCD afterglow (0 for none)",
    "保存したRAMのBASICのプログラムを、このフォルダに.basで書き出して終わる": (
        "Export the BASIC program in the saved RAM to this folder as .bas and exit"
    ),
    "機種(1250、1251、1255、1245、1260、1261、1262、1350)。ROMはcpu-機種.romと"
    "bas-機種.rom(1250と1255は1251の、1260〜1262はどれも1260のROMを使う)": (
        "Model (1250, 1251, 1255, 1245, 1260, 1261, 1262, 1350). The ROMs are cpu-MODEL.rom"
        " and bas-MODEL.rom (1250 and 1255 use the 1251 ROM, 1260 to 1262 the 1260 ROM)"
    ),
    "PC-1350に差すRAMカードの大きさ(KB)。0、8、16": (
        "Size of the PC-1350 RAM card in KB: 0, 8 or 16"
    ),
    "PC-1350を輸出向けの配線で動かす(カナの代わりに英小文字、¥の代わりに\\)": (
        "Run the PC-1350 wired as the export model (lowercase instead of kana, \\ instead of ¥)"
    ),
    "矢印キーを数字キーの8・2・4・6として押す(⌘K/Ctrl+Kで切り替え)": (
        "Arrow keys press the number keys 8, 2, 4, 6 (toggle with ⌘K/Ctrl+K)"
    ),
    "カセットの音(wav)をセットする。CLOAD・CLOAD Mで読み込める": (
        "Insert cassette audio (wav) to load with CLOAD or CLOAD M"
    ),
    "保存した状態(⇧⌘Sで書いたもの)から始める": "Start from a saved state (written with ⇧⌘S)",
    "ROMを使わず、マシン語の作業欄で動かす(ROMがなければ自動でこうなる)": (
        "Run without the ROM, in the machine-code workbench (automatic when there is no ROM)"
    ),
    "画面の言語(jaかen)。なければSC61BOX_LANG、メニューで選んだもの、ロケールの順": (
        "Display language (ja or en). Otherwise SC61BOX_LANG, the menu choice, then the locale"
    ),
    "版を出して終わる": "Print the version and exit",
    "言語はjaかenです": "The language must be ja or en",
    "機種は{models}のどれかです": "The model must be one of {models}",
    "RAMカードの大きさは0、8、16のどれかです": "The RAM card size must be 0, 8 or 16",
    "{path}がありません": "{path} does not exist",
    # ---- 音、ROM、状態のファイル、録画 ----
    "SDL2のライブラリが見つかりません": "SDL2 library not found",
    "ミキサーが{freq}Hzで開かれました": "The mixer opened at {freq} Hz",
    "ミキサーを開けません": "Cannot open the mixer",
    "SDLのキューが使えないので、mixerで鳴らします({error})": (
        "SDL audio queue not available, using the mixer ({error})"
    ),
    "音を切ります({error})": "Sound off ({error})",
    "ROMのファイル{name}が見つかりません。実機から読み出した内部ROM(cpu-{model}.rom、"
    "8KB)とBASIC ROM(bas-{model}.rom、{kb}KB)をrom/に置くか、環境変数SC61BOX_ROMに"
    "置き場所を指定してください(READMEの「ROMの用意」)。": (
        "ROM file {name} not found. Put the internal ROM (cpu-{model}.rom, 8 KB) and the"
        " BASIC ROM (bas-{model}.rom, {kb} KB) read from a real machine in rom/, or set the"
        ' environment variable SC61BOX_ROM to their folder (see "Preparing the ROM" in the'
        " README)."
    ),
    "{path}は{have}バイトしかありません。{name}は{size}バイト({kb}KB)必要です。": (
        "{path} has only {have} bytes. {name} needs {size} bytes ({kb} KB)."
    ),
    "PC-1350はROMなしでは動かせません": "The PC-1350 cannot run without a ROM",
    "状態のファイルとして読めません": "Not a state file",
    "状態のファイルとして読めません({error})": "Not a state file ({error})",
    "ほかの機種(PC-{model})の状態です": "This is the state of another model (PC-{model})",
    "ROMが保存したときと違います": "The ROM is not the one used when saving",
    "メモリの大きさが違います": "The memory size differs",
    "本体の状態がありません": "No machine state",
    "本体の{name}がおかしい値です": "Bad value for machine {name}",
    "CPUの状態がありません": "No CPU state",
    "CPUの内部RAMの大きさが違います": "The CPU internal RAM size differs",
    "CPUの{name}がおかしい値です": "Bad value for CPU {name}",
    "ffmpegが見つかりません。ffmpegを入れてPATHに置くと録画できます": (
        "ffmpeg not found. Install ffmpeg on the PATH to record"
    ),
    "ffmpegが止まりました": "ffmpeg stopped",
    "絵の大きさが違います({size}バイト、{want}バイトのはず)": (
        "Wrong picture size ({size} bytes, expected {want})"
    ),
    "ffmpegが終了コード{code}で止まりました": "ffmpeg exited with code {code}",
    "動画を仕上げられませんでした": "Could not finish the video",
    # ---- プログラムの一覧とファイル ----
    "まだ何もありません。.basか.hexを置いてください": (
        "Nothing here yet. Put .bas or .hex files in the folder"
    ),
    "フォルダを開く(O)": "Open folder (O)",
    "フォルダ": "Folder",
    "読み直す(R)": "Reload (R)",
    "読み直す": "Reload",
    "閉じる(Esc)": "Close (Esc)",
    "閉じる": "Close",
    "読み込むだけ(Shift+Enter)": "Load only (Shift+Enter)",
    "読み込むだけ": "Load only",
    "読み込んで実行(Enter)": "Load and run (Enter)",
    "読み込んで実行": "Load and run",
    "名前で探す( / )": "Search by name ( / )",
    "合うものがありません(Escで探すのをやめる)": "No match (Esc ends the search)",
    "▲ 上にあと{n}本": "▲ {n} more above",
    "▼ 下にあと{n}本": "▼ {n} more below",
    "{where}(↑↓かホイールで)": "{where} (↑↓ or wheel)",
    "Escで探すのをやめる": "Esc ends the search",
    "どの機種でも": "any model",
    "{models}用": "for {models}",
    "読めない行あり": "unreadable lines",
    "{title}({models}用)": "{title} (for {models})",
    "{title}(番地がどの機種のRAMにも収まらない)": "{title} (addresses fit no model's RAM)",
    "{where}&{addr:04X}から{n}バイトでは、&FFFFを越える": (
        "{where}{n} byte from &{addr:04X} goes past &FFFF",
        "{where}{n} bytes from &{addr:04X} go past &FFFF",
    ),
    "# {key}: {name}が見つからない": "# {key}: {name} not found",
    "# {key}: {name}に置く番地がない(例:# bin: {name} &C300)": (
        "# {key}: no address for {name} (e.g. # bin: {name} &C300)"
    ),
    "{where}{line}行目の番地がFFFFを越える: {text}": "{where}line {line} goes past FFFF: {text}",
    "{where}中身が空": "{where}is empty",
    "{where}{line}行目を16進ダンプとして読めない: {text}": (
        "{where}line {line} is not a hex dump: {text}"
    ),
    "{where}{line}行目の「:」のあとがチェックサム(16進表記2桁)ではない: {text}": (
        "{where}line {line} has no 2-digit hex checksum after ':': {text}"
    ),
    "{where}{line}行目のチェックサムが合わない(計算すると{sum:02X}): {text}": (
        "{where}line {line} has a wrong checksum (should be {sum:02X}): {text}"
    ),
    "# {key}: {name}を読めない({error})": "# {key}: cannot read {name} ({error})",
    # ---- マシン語の作業欄 ----
    "編集中": "editing",
    "実行中": "running",
    "一時停止中": "paused",
    "マシン語の作業欄  {state}": "Machine-code workbench  {state}",
    "マシン語(ROMなし)  {state}": "Machine code (no ROM)  {state}",
    "キーは作業欄へ": "Keys go to the workbench",
    "キーは本体へ": "Keys go to the machine",
    "● 止める所": "● Breakpoint",
    "カーソルの命令({addr:04X}番地)に止める所を置く。置いてあれば外す({c}B)": (
        "Set a breakpoint at the instruction under the cursor ({addr:04X}), or remove it ({c}B)"
    ),
    "編集へ": "Edit",
    "実行を途中でやめて編集に戻る。書き換わったメモリはそのまま(Esc)": (
        "Stop running and go back to editing. Memory stays as it is (Esc)"
    ),
    "■ 一時停止": "■ Pause",
    "実行を、いまの命令の前で止める({c}.)": "Stop before the current instruction ({c}.)",
    "▶ 実行": "▶ Run",
    "開始番地{addr:04X}から実行する。RTNで戻れば終わり({c}G)": (
        "Run from the start address {addr:04X}. Ends at RTN ({c}G)"
    ),
    "1命令ずつ": "Step",
    "開始番地{addr:04X}の最初の命令の前で止める。そこから1命令ずつ進める({c}J)": (
        "Stop before the first instruction at {addr:04X}, then step one at a time ({c}J)"
    ),
    "{addr:04X}番地からは続けられないので、編集に戻る(Esc)": (
        "Cannot continue from {addr:04X}, so go back to editing (Esc)"
    ),
    "▶ 続ける": "▶ Continue",
    "{addr:04X}番地から続けて実行する({c}G)": "Continue running from {addr:04X} ({c}G)",
    "1命令": "Step",
    "次の命令「{ins}」({addr:04X}番地)だけを実行して止まる({c}J)": (
        'Run only the next instruction "{ins}" ({addr:04X}) and stop ({c}J)'
    ),
    "「{ins}」で{addr:04X}番地を呼び、RTNで戻ってくるまで実行して、次の命令で止まる({s}{c}J)": (
        'Call {addr:04X} with "{ins}", run until RTN returns, and stop at the next instruction'
        " ({s}{c}J)"
    ),
    "CALLごと": "Step over",
    "ROMなしでは使えない{addr:04X}番地で止まっています": (
        "Stopped at {addr:04X}, not usable without ROM"
    ),
    "開始番地": "Start",
    "(自動)": "(auto)",
    "(BASICで CALL &{addr:04X} と打って呼ぶ)": "(call it from BASIC with CALL &{addr:04X})",
    "実行の前に液晶を消す": "Clear LCD before run",
    "取り消す": "Undo",
    "やり直す": "Redo",
    "書き出すダンプはまだありません": "No dump to export yet",
    ".hexに書き出す {c}E": "Export .hex {c}E",
    "ダンプリスト": "Dump list",
    "範囲を指定する": "Set the range",
    "範囲(指定、合計{n}バイト) ": ("Range set, {n} byte: ", "Range set, {n} bytes: "),
    "範囲": "Range",
    "クリックすると、書き出す範囲を打てます": "Click to type the export range",
    (
        "始めと終わりの番地を16進表記4桁ずつ打つ  何も打たずにEnterで自動に戻す  "
        "{c}Vで貼り付け  Escでやめる"
    ): (
        "Type the first and last addresses, 4 hex digits each"
        "  Enter alone goes back to automatic  {c}V pastes  Esc cancels"
    ),
    "書き出す範囲を{where}にしました": "Export range set to {where}",
    "書き出す範囲を自動に戻しました": "Export range is automatic again",
    "終わりの番地が始めの番地より前です": "The last address is before the first",
    "貼り付けた文字は範囲ではありません(始めと終わりを16進表記の4桁で)": (
        "The pasted text is not a range (use two 4-digit hex addresses)"
    ),
    "実行中は範囲を打てません": "Cannot type the range while running",
    "自動に戻す": "Automatic",
    "番地は16進表記(0〜9、A〜F)で打ちます": "Type addresses in hex (0-9, A-F)",
    "範囲({places}か所、合計{n}バイト) ": (
        "{places} ranges, {n} byte: ",
        "{places} ranges, {n} bytes: ",
    ),
    "範囲(合計{n}バイト) ": ("Range, {n} byte: ", "Range, {n} bytes: "),
    "ほか{n}か所": "and {n} more",
    "{where}ほか{n}か所": "{where} and {n} more",
    "{where}({n}バイト)": ("{where} ({n} byte)", "{where} ({n} bytes)"),
    "逆アセンブル": "Disassembly",
    "(左の印をクリックで止める所)": "(click a dot for a breakpoint)",
    "開始": "start",
    "(ROMの中身なし)": "(no ROM contents)",
    "レジスタ": "Registers",
    "サイクル {n}": "Cycles {n}",
    "内部RAM": "Internal RAM",
    "(00〜0Bは I J A B XL XH YL YH K L M N)": "(00-0B: I J A B XL XH YL YH K L M N)",
    "(クリックで開く)": "(click to open)",
    "開始番地を16進表記4桁で打つ  {c}Vで貼り付け  Escでやめる": (
        "Type a 4-digit hex start address  {c}V pastes  Esc cancels"
    ),
    "作業欄をクリックすると、キーで作業欄のダンプを書けます": (
        "Click the workbench to write the dump with the keys"
    ),
    "16進表記で打つ  {c}.で一時停止  {c}Bで止める所  本体のクリックでキーは本体へ": (
        "Type hex  {c}. pause  {c}B breakpoint  Click the machine to send keys there"
    ),
    "{c}Gで続ける  {c}Jで次の1命令だけ実行  {s}{c}JでCALLごと": (
        "{c}G continue  {c}J step  {s}{c}J step over CALL"
    ),
    "実行中です。キーはPC-1251へ(EscはBRK)。{c}.で一時停止": (
        "Running. Keys go to the PC-1251 (Esc is BRK). {c}. pauses"
    ),
    "{c}Gで続ける  {c}Jで次の1命令だけ実行  Escで編集に戻る": (
        "{c}G continue  {c}J step  Esc back to editing"
    ),
    "番地を4桁打ってSpace。続けて8バイトを打ってEnter(本のダンプリストと同じ)": (
        "Type a 4-digit address and Space, then 8 bytes and Enter (as in a dump listing)"
    ),
    (
        "16進表記で打つ  Enterで次の行  Tabで番地を打って飛ぶ  {c}Gで実行  "
        "{c}Aでカーソルの所を開始番地に  {c}Vで貼り付け"
    ): (
        "Type hex  Enter next line  Tab jumps to a typed address  {c}G run"
        "  {c}A start address at cursor  {c}V paste"
    ),
    # 取り消しとやり直し
    "取り消せる書き込みはありません": "Nothing to undo",
    "やり直せる書き込みはありません": "Nothing to redo",
    "実行中は取り消せません": "Cannot undo while running",
    "実行中はやり直せません": "Cannot redo while running",
    "{addr:04X}番地を{old:02X}から{new:02X}にする": "Set {addr:04X} from {old:02X} to {new:02X}",
    "{addr:04X}番地を{new:02X}から{old:02X}に戻す": (
        "Set {addr:04X} back from {new:02X} to {old:02X}"
    ),
    "{what}を取り消す": "Undo {what}",
    "{what}をやり直す": "Redo {what}",
    "{what}を取り消しました": "Undid {what}",
    "{what}をやり直しました": "Redid {what}",
    "{addr:04X}番地の打ち込み": "typing at {addr:04X}",
    "貼り付け": "paste",
    "貼り付け({n}バイト)": ("paste ({n} byte)", "paste ({n} bytes)"),
    # 打ち込みと実行
    "実行中は書き換えられません": "Cannot edit while running",
    "行の終わりです。Enterで次の行へ": "End of line. Enter goes to the next line",
    "{addr:04X}番地はRAMの外なので書けません": "{addr:04X} is outside RAM and cannot be written",
    "{addr:04X}番地はRAMの外なので、ROMなしでは開始番地にできません": (
        "{addr:04X} is outside RAM, so without ROM it cannot be the start address"
    ),
    "{why}。{addr:04X}番地で一時停止しています": "{why}. Paused at {addr:04X}",
    "{why}。{addr:04X}番地から続けられます": "{why}. You can continue from {addr:04X}",
    "一時停止しました": "Paused",
    "実行を途中でやめて、編集に戻りました(メモリはそのまま)": (
        "Stopped running and went back to editing (memory unchanged)"
    ),
    "{addr:04X}番地の最初の命令の前で止まっています": (
        "Stopped before the first instruction at {addr:04X}"
    ),
    "CPUはキーかタイマを待って止まっています(HALT)。「続ける」で進みます": (
        'The CPU is waiting for a key or the timer (HALT). "Continue" goes on'
    ),
    "RTNで戻りました({n}サイクル、約{ms}ミリ秒)": (
        "Returned with RTN ({n} cycle, about {ms} ms)",
        "Returned with RTN ({n} cycles, about {ms} ms)",
    ),
    "呼び出しから戻りました": "Returned from the call",
    "止める所({addr:04X})で止まりました": "Stopped at the breakpoint at {addr:04X}",
    "{addr:04X}番地で止まりました": "Stopped at {addr:04X}",
    "ROMの{name}({addr:04X})へ飛んだので止めました。ROMなしでは使えません": (
        "Stopped: jumped to the ROM routine {name} ({addr:04X}), not usable without ROM"
    ),
    "RAMの外の{addr:04X}番地へ飛んだので止めました。ROMなしでは使えません": (
        "Stopped: jumped to {addr:04X} outside RAM, not usable without ROM"
    ),
    # ---- ROMのルーチンの働き(romsyms.ROUTINES_1251) ----
    "YのX乗": "Y to the power X",
    "SIN(角度の単位は液晶の記号のビットF83C・F83Dで決まる)": (
        "SIN (the angle unit is set by the LCD symbol bits F83C, F83D)"
    ),
    "DMS(C6BBのビット0を立てたまま戻る。BASICへ戻る前にFROUNDを呼ぶ)": (
        "DMS (returns with bit 0 of C6BB set; call FROUND before going back to BASIC)"
    ),
    "DEG(BASIC ROM。CALLで呼ぶ)": "DEG (BASIC ROM, use CALL)",
    "RND(BASIC ROM。CALLで呼ぶ。F8B0〜F8B7の乱数の種を書く)": (
        "RND (BASIC ROM, use CALL; writes the random seed at F8B0-F8B7)"
    ),
    "演算Xを10桁に丸める": "round X to 10 digits",
    "VAL(文字列の直後の1バイトに00を書く)": "VAL (writes 00 to the byte after the string)",
    "STR$(液晶RAMのF800〜F837を作業に使う)": "STR$ (uses the LCD RAM F800-F837 as work area)",
    "28・29番地の符号つき16ビット → 演算X": "signed 16 bits at 28, 29 → X",
    "28・29番地の符号なし16ビット → 演算X": "unsigned 16 bits at 28, 29 → X",
    "F2Iの範囲を−32768〜32767にする(続けてF2Iを呼ぶ)": (
        "set the F2I range to −32768 to 32767 (then call F2I)"
    ),
    "演算X → 28・29番地の16ビット(J_ONE)": "X → 16 bits at 28, 29 (J_ONE)",
    "キーを1回読む。キャリー1でAに本体の文字コード(押されているときJ_ONE)": (
        "read the keys once; when a key is down, carry 1 and its character code in A (J_ONE)"
    ),
    "キーを待つ。自動で電源が切れるまでの時間を戻す(J_ONE)": (
        "wait for a key, restarting the auto power-off time (J_ONE)"
    ),
    "キーを待つ。電源が切れるまでの時間を戻さない(J_ONE)": (
        "wait for a key, keeping the auto power-off time (J_ONE)"
    ),
    "液晶の表示をつける(Cポート←01)": "LCD on (port C ← 01)",
    "液晶の表示を消す(Cポート←00)": "LCD off (port C ← 00)",
    "2msのタイマのフラグを1回待つ": "wait for one 2 ms timer tick",
    "2msのタイマのフラグを2回待つ": "wait for two 2 ms timer ticks",
    "2msのタイマのフラグを3回待つ": "wait for three 2 ms timer ticks",
    "Aの文字の形の番地−1をXへ(J_ONE)": "glyph address of A, minus 1, into X (J_ONE)",
    # ---- 逆アセンブルの命令とデータ ----
    "ほかは→{addr:04X}": "else→{addr:04X}",
    "実行済みの命令": "Executed instruction",
    "ユーザ指定のデータ": "User-specified data",
    "ユーザ指定の命令": "User-specified code",
    "{addr:04X}番地からデータにする": "Mark data from {addr:04X}",
    "次の指定か、実行済みの命令の手前までデータ": (
        "Data up to the next mark or executed instruction"
    ),
    "{addr:04X}番地から命令にする": "Mark code from {addr:04X}",
    "ここから静的解析する": "Analyse the code from here",
    "{addr:04X}番地の指定を消す": "Clear the mark at {addr:04X}",
    "推定に戻す": "Back to guessing",
    "{addr:04X}番地からデータにしました": "Marked data from {addr:04X}",
    "{addr:04X}番地から命令にしました": "Marked code from {addr:04X}",
    "{addr:04X}番地の指定を消しました": "Cleared the mark at {addr:04X}",
    "指定はありません": "No mark here",
    "RAMの外です": "Outside RAM",
    "いまの指定です": "Already marked so",
    "{file}: # data: の{text}が読めない": "{file}: cannot read {text} in # data:",
    "{file}: # ram: の{text}が読めない(例:# ram: 6800-7FFF)": (
        "{file}: cannot read {text} in # ram: (e.g. # ram: 6800-7FFF)"
    ),
    "貼り付けた文字は番地ではありません(16進表記の4桁で)": (
        "The pasted text is not an address (use 4 hex digits)"
    ),
    "分岐と呼び出しをたどり、命令と判定": "Code found by following branches and calls",
    "DTCの表(行の数はPTCから)": "DTC table (row count from PTC)",
    "DTCの表(参照されていない)": "DTC table (unreferenced)",
    "参照されていないため不明": "Unreferenced, so unknown",
    "文字列と推定": "Guessed as text",
    "00・FFの連続と推定": "Guessed as a run of 00/FF",
    "未定義命令などを含むため、データと推定": (
        "Contains undefined opcodes or the like, so guessed as data"
    ),
    "RTNやジャンプで終わらないため、データと推定": (
        "Does not end in RTN or a jump, so guessed as data"
    ),
    "✓:実行済み　.:静的解析　?:推定　U:ユーザ指定": (
        "Marks at right  ✓: executed  .: static analysis  ?: guessed  U: user-specified"
    ),
    "データの置き場所を~/.sc61boxに移しました({old}はそこへのリンク)": (
        "Moved the data folder to ~/.sc61box ({old} now links to it)"
    ),
    # ---- ゲームパッド ----
    "ゲームパッドの割り当て…": "Gamepad mapping…",
    "{names}がつながっています": "{names} connected",
    "パッドはつながっていません": "No gamepad connected",
    "ゲームパッドの割り当て": "Gamepad mapping",
    "パッドがつながっていません(つなぐとここに出ます)": (
        "No gamepad connected (it appears here once connected)"
    ),
    "このプログラム用に保存": "Save for this program",
    "既定として保存": "Save as default",
    "初期設定に戻す": "Reset to factory mapping",
    "# pad: に戻す": "Back to # pad:",
    "# pad: の行をコピー": "Copy # pad: line",
    "いまの割り当て: {source}": "Current mapping: {source}",
    "{name}に割り当てるキーを、本体の絵でクリックするか、パソコンで打ちます。"
    "Deleteで割り当てを外し、Escでやめます": (
        "Click a key on the pocket computer or press one on your keyboard to map it to {name}. "
        "Delete clears the mapping, Esc cancels"
    ),
    "パッドのボタンを押すか、下の割り当てをクリックすると、その割り当てを変えられます": (
        "Press a gamepad button or click a mapping below to change it"
    ),
    "下の割り当てをクリックすると、その割り当てを変えられます": (
        "Click a mapping below to change it"
    ),
    "ボタンの名前はA・B・X・Yの位置の約束(SDL)で、パッドの印字と違うことがあります。"
    "印字と違うときは、割り当てたいボタンを実際に押して選んでください": (
        "Button names follow the SDL convention for the A/B/X/Y positions and may differ from "
        "the labels on your pad. If they do, press the button you want to map to select it"
    ),
    "対象: (プログラムを読み込んでいません)": "Target: (no program loaded)",
    "対象: {name}": "Target: {name}",
    "(変更あり、保存していません)": " (edited, not saved)",
    "{name}用に保存したもの": "saved for {name}",
    "{name}の# pad:": "# pad: of {name}",
    "# pad: の{text}が読めません": "Cannot read {text} in # pad:",
    "保存した既定": "saved default",
    "初期設定": "factory mapping",
    "# pad: の行をクリップボードにコピーしました": "Copied the # pad: line to the clipboard",
    "割り当てを保存できません: {error}": "Cannot save the mapping: {error}",
    "割り当てを{path}に保存しました": "Saved the mapping to {path}",
}
