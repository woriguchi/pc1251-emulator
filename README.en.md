[日本語](README.md) | English

# SHARP PC-1251/PC-1245 emulator

An emulator for two Sharp pocket computers: the PC-1251 (1982) and the PC-1245 (1983). It executes the SC61860 CPU one instruction at a time and runs the machine's own internal ROM and BASIC ROM, so BASIC programs and machine code both work. You can press the keys and move the mode switch with the mouse. You choose the model when starting; without an option it runs as the PC-1251 (for the PC-1245 see [Running as a PC-1245](#running-as-a-pc-1245)).

![Switching on a PC-1251 and starting the machine-code bouncing ball with CALL &C000](images/demo-1251.gif)

![Switching on a PC-1245 and starting the machine-code dot-by-dot text scroller with CALL &C100](images/demo-1245.gif)

The user guide, starting from installation on macOS and Windows, is [`doc/manual.pdf`](doc/manual.pdf) (in Japanese).

## Installing

You need [uv](https://docs.astral.sh/uv/). uv fetches a suitable Python by itself.

```sh
git clone <URL of this repository>
cd pc1251-emulator
mkdir rom                            # put the ROM read from a real machine here (see below)
uv run pc1251                        # start
```

### Preparing the ROM

The ROM is Sharp's copyrighted work, so it is not in this repository. Read it out of a real machine and put it in `rom/` under these names. Only the files for the model you use are needed.

| File | Contents | Size |
| --- | --- | --- |
| `cpu-1251.rom` | PC-1251: the SC61860's internal ROM, `0000-1FFF` | 8192 bytes |
| `bas-1251.rom` | PC-1251: the BASIC ROM, `4000-7FFF` | 16384 bytes |
| `cpu-1245.rom` | PC-1245: the CPU's internal ROM, `0000-1FFF` | 8192 bytes |
| `bas-1245.rom` | PC-1245: the BASIC ROM, `4000-7FFF` | 16384 bytes |

For example, if you cloned into `~/src`, the files are `~/src/pc1251-emulator/rom/cpu-1251.rom` and `~/src/pc1251-emulator/rom/bas-1251.rom`.

yagshi's page "[Extracting ROM Data](https://www.oit.ac.jp/rd/labs/kobayashi-lab/~yagshi/old_web/misc/pocketcom/extrom.html)" (in Japanese) describes how to do it on a PC-1251. For the PC-1245, "[SHARP PC-1245/50/51/55 の使い方](https://ht-deko.com/pc1245/)" (ht-deko.com, in Japanese) gives a procedure with BASIC listings that saves the internal ROM 1 KB at a time and the BASIC ROM 4 KB at a time with `CSAVE M`. ROMs come in different versions, so only the file sizes are checked. To keep the ROM elsewhere, set the environment variable `PC1251_ROM` to that folder.

## Running

```sh
uv run pc1251 --scale 0.8            # smaller window
uv run pc1251 primes --run           # load the bundled primes.bas and run it
uv run pc1251 ~/prog/game.bas        # load a file by path
uv run pc1251 --fresh                # start without the saved RAM
uv run pc1251 --model 1245           # start as a PC-1245
uv run pc1251 --help                 # list the options
uv run pc1251 --version              # print the version (please include it in bug reports)
```

On exit the RAM is saved to `~/.pc1251/ram.bin` (`ram-1245.bin` for the PC-1245) and restored at the next start.

### Program files

Put `.bas` files (BASIC as plain text) or `.hex` files (hex dumps, one `address data` line after another) in `~/.pc1251/programs/`, and they appear in the program list (Cmd+O, or Ctrl+O on Windows). Enter (or a second click on the selected row) loads and runs the program; Shift+Enter only loads it. You can also drop a file onto the window.

A BASIC program typed in the emulator can be exported with Cmd+E (Ctrl+E on Windows) to `~/.pc1251/programs/` as `name-date.bas`. Machine code is not exported. `uv run pc1251 --export folder` exports from the saved RAM.

A `.bas` file is typed in at full speed after a `NEW` in PRO mode (write the exponent sign, typed with SHIFT+`+` and different from the letter E, as `[E]` or `€`, e.g. `1[E]-8`, as PocketTools does, and π as `π`); a `.hex` file is written straight into RAM, and anything after `;` on a line is a comment. Hex dumps written by the YASM61860 assembler (`c300 : 02 41 37 …`) can be used as `.hex` files as they are. Only 79 characters fit on one input line, so a longer line is typed as on the real machine: up to a break point (a `:` where possible), then `ENTER`, then ▶ to the end of the line and the rest. If appending would overflow the edit field (79 characters including the line number), the keywords are typed first and the rest is inserted afterwards with ▶ and SHIFT+▶ (INS), as one would on the real machine. A `.bas` and a `.hex` with the same name form one program: the dump is written first, then the BASIC is typed in.

Lines starting with `#` are comments; `# title: name in the list`, `# run: what to type to run it`, `# hex: a dump file to load first`, `# bin: a machine-code binary and its load address` (`# bin: code.bin &C300`) and `# after: a dump file to write after the run command is typed` are read as settings. A `.bin` file (the format PocketTools' `bin2wav` reads) holds only the machine-code bytes, not the address to load them at, so the `# bin:` line supplies the address, written as `&C300`, `0xC300` or `C300`. YASM61860's `-r` writes memory from address 0 (zero-filled up to the ORG), so for YASM61860 output use the dump (`-d`) as a `.hex` file instead; `# after: code.bin &C400` works too. `# after:` is for articles where the BASIC program reserves space with DIM before the machine code is loaded. A `.hex` that is only used through `# hex:` or `# after:` (with no `.bas` of the same name) is not listed on its own; its size is shown on the program that uses it. Files in a `pc1251/` or `pc1245/` folder inside a program folder are for that model; files directly in the program folder work on both. `# model: 1251` in the file does the same as the folder. A program for another model is listed with "(PC-1251用)" and is not loaded. If a program with the same `# title:` exists for the current model, only that one is listed, so a program written separately for each model can sit under the same name in both folders. `programs/` has eight samples: primes, a text animation, a display-during-calculation demo, a machine-code dot-by-dot text scroller, a machine-code bouncing ball, breakout, the PC-Interpreter and a mole-bashing game.

### Keys

Click the keys on screen with the mouse. Letters, digits, symbols, Enter, Space and the arrow keys on your own keyboard work as well.

| macOS | Windows | Machine |
| --- | --- | --- |
| Tab | Tab | SHIFT |
| Option | Alt | DEF |
| delete | Backspace | delete one character |
| fn+delete | Delete | CL |
| Esc | Esc | BRK (ON while the power is off) |
| Cmd+↑, Cmd+↓ | Ctrl+↑, Ctrl+↓ | move the mode switch up or down one step |
| Cmd+O | Ctrl+O | program list |
| Cmd+R | Ctrl+R | the RESET button on the back |
| Cmd+T, Shift+Cmd+T | Ctrl+T, Shift+Ctrl+T | faster / slower (½×, 1×, 2×, 4×, 8×; away from 1× the pitch of the sound changes too) |
| Cmd+E | Ctrl+E | export the BASIC program in memory to a .bas file |
| Cmd+S | Ctrl+S | save a screenshot |
| Shift+Cmd+R | Shift+Ctrl+R | start recording / stop and save the video |
| Cmd+/ | Ctrl+/ | key help |
| Cmd+V | Ctrl+V | type the clipboard text in |
| Cmd+K | Ctrl+K | make the arrow keys press 8, 2, 4, 6 on the keypad, or back |

On a PC without a numeric keypad, games that use 8, 2, 4 and 6 (up, down, left and right around 5) are easier with Cmd+K (Ctrl+K on Windows, or F7): the arrow keys then press those number keys. Press it again to switch back, or start with `--numpad`.

Shift+Cmd+R (Shift+Ctrl+R on Windows) starts recording; pressing it again stops and saves a 1280×720 MP4 video with sound, showing an enlarged LCD above the whole calculator, as `rec-<date>-<time>.mp4` in the program folder. The ffmpeg used to make the video comes with the imageio-ffmpeg library, which bundles it only for Windows, macOS and Linux (x86_64 and aarch64). Elsewhere the emulator still installs and runs, but recording needs an ffmpeg on the PATH; without one, the emulator says so at the bottom of the window instead of recording.

Right-click opens a menu with the same actions. Its first item opens the program list, so you can pick a sample and run it straight away. Turn off Japanese input before typing.

### Breakout

`programs/pc1251/break.hex` and `break.bas` are a sideways breakout game written in machine code. Move the paddle with ↑ and ↓, serve with Space, and knock bricks out of the wall creeping in from the right. At the start choose 1 (EASY, three-dot paddle) or 2 (NORMAL, two-dot paddle). Each level has one blinking brick; breaking it releases a second ball, and losing one of the two does not cost a life.

The PC-1245 version is `break.hex` and `break.bas` in `programs/pc1245/`; the list shows one "breakout" entry for whichever model is running. On the PC-1245 the playing field is 75 columns, the score is shown only after the game, and there is no blinking brick (there is not enough memory for it).

### PC-Interpreter and "Reading the PC-Interpreter"

The "PC-Interpreter" from the August 1986 issue of the Japanese magazine PiO (by [Fan_PC-1251](https://x.com/pio1986_10)) runs as well. `programs/pcint.hex` is the article's listing 1 and `programs/mogura.bas` is listing 2, a mole-bashing game; both are included with the author's permission.

Start the game from the program list, then hold down the number key (1–6) of the hole the mole pops out of.

[`doc/pcinterp.pdf`](doc/pcinterp.pdf) is "PC-インタープリタを読む" (Reading the PC-Interpreter, by origuchi), a booklet in Japanese that reads the program instruction by instruction.

### Cassette audio (wav)

Programs can be exchanged with a real machine as cassette audio (wav files).

- **Emulator to real machine**: type `CSAVE` or `CSAVE M` in RUN mode. The sound the ROM sends to the cassette port is written to the program folder (`~/.pc1251/programs`) as `tape-<date>-<time>.wav`. Play the wav into the real machine's cassette interface and type `CLOAD`/`CLOAD M` on the real machine. `BEEP` sounds are not written.
- **Real machine to emulator**: record the real machine's `CSAVE` as a wav, drop it onto the window (or start with `--tape file`) to insert it as a tape, then load it with `CLOAD`/`CLOAD M`.

Loading real-machine tapes into the emulator has been checked with recordings of the PC-1251 sample-program micro-cassette (20 programs published in [number42net/sharp-pc1251](https://github.com/number42net/sharp-pc1251)): all of them load with `CLOAD` without errors. Machine-code wavs made with PocketTools' `bin2wav` or YASM61860's `-w` (with `-old`) load with `CLOAD M`. The wavs the emulator writes decode correctly with PocketTools' `wav2bin`, but they have not been played into a real machine yet.

## Running as a PC-1245

With `--model 1245` the emulator starts as a PC-1245. The PC-1245 has the same case size as the PC-1250/1251 and the same SC61860 CPU, but a different ROM. Put its ROM in `rom/` as `cpu-1245.rom` and `bas-1245.rom` (see [Preparing the ROM](#preparing-the-rom)).

```sh
uv run pc1251 --model 1245
uv run pc1251 --model 1245 primes --run
```

The program list, exporting, shortcuts and running programs with DEF work as on the PC-1251. The differences are:

- The LCD has 16 characters. Anything written to the right of the 16th (LCD RAM `F867-F840`) is not visible, so some PC-1251 programs show only part of their display.
- The breakout sample loads its PC-1245 version (`programs/pc1245/`): a 75-column playing field, the score shown only after the game, and no blinking brick.
- RAM is 2 KB (`C000-C7FF`) and BASIC programs start at `C000`. 1486 bytes are free for programs (the value of `MEM`).
- The mode switch has three positions, PRO, RUN and OFF; there is no RSV. Cmd+↑↓ (Ctrl+↑↓) and the right-click menu move only between those three.
- On the A–= and Z–SPC rows, SHIFT followed by a key enters the BASIC keyword printed above it (INPUT, IF, THEN, …, PRINT, USING, …, CLOAD).
- Parentheses are SHIFT+1 and SHIFT+2 (↓ and ↑ on the PC-1251). Typing `(` or `)` on the PC keyboard is translated into these.
- RAM is saved to `~/.pc1251/ram-1245.bin` on exit, separately from the PC-1251's `ram.bin`.

The key positions are the same as on the PC-1251. Apart from DEG, which is visible in the photos, the positions of the LCD annunciators are estimates.

## How it works

| File | Contents |
| --- | --- |
| `pc1251emu/sc61860.py` | CPU core. The 256 opcodes are dispatched through a table of functions |
| `pc1251emu/machine.py` | memory, key matrix, timers, ports, LCD RAM, power |
| `pc1251emu/display.py` | drawing the case and the LCD |
| `pc1251emu/audio.py` | the piezo buzzer and its output (SDL audio queue) |
| `pc1251emu/app.py` | window, keyboard and mouse, automatic typing |
| `pc1251emu/programs.py` | the program folders and how .bas/.hex files are read |
| `pc1251emu/tape.py` | writing and reading cassette audio (wav) |
| `doc/manual.pdf` | the user guide (in Japanese) |

Instruction semantics follow MAME's SC61860 implementation, except for `56h` (READ), `LOOP` and `WAIT n`, which sources describe differently and where I followed how real programs use them, and `CUP`/`CDN` and the timer flags (`TEST 01`/`TEST 02`), which follow what the ROM's cassette routines need. For `CUP`/`CDN` and the timer flags I also checked against PockEmul and digihori's [PokecomGO](https://github.com/digihori/pokecom). The undocumented opcode `72h` (LIIH), which MAME treats as a one-byte no-op, is a two-byte instruction here, following utz82's instruction table; the COR version of "Hashire! Sekoiline" (PiO, April 1986) relies on it. The clock is 192 kHz.

The memory map is: internal ROM at `0000-1FFF`, BASIC ROM at `4000-7FFF`, RAM at `B800-C7FF` (`C000-C7FF` on the PC-1245) and LCD RAM at `F800-F87F`. The LCD RAM `F800-F8FF` also appears in every 256-byte block of `F900-FFFF`, and on the PC-1245 in `E800-EFFF` as well.

The mode switch is read with INB after setting bit 3 of port IB. Bit 0 means RSV, bit 1 PRO and bit 2 OFF; with none of them set the switch is at RUN. On OFF the ROM writes a marker into internal RAM `30h-37h` and powers itself off; if the marker is missing at the next power-on, it clears the program.

On port C, bit 0 turns the display on, bit 2 halts the CPU (a key or the 512 ms timer wakes it), bit 3 powers off and bits 4–6 drive the buzzer: `3` selects the built-in 4 kHz oscillator, and `5` and `4` set the output high and low.

The left 60 columns of the LCD are `F800-F83B` in order, and the right 60 are `F87B` down to `F840`. The annunciators are bits in `F83C-F83E`.

### Differences from the real machine

- Cassette input has been checked with recordings of real tapes (they load with `CLOAD`). The wavs the emulator writes have not been played into a real machine yet.
- The CE-125 printer is not emulated.
- Different ROM versions have not been checked.
- BASIC's `PEEK` can read the internal ROM here (the real CPU reads it only with the `DATA` instruction).

## Tests

```sh
uv run pytest -q tests
```

Tests that need the ROM are skipped when it isn't there. The PC-1245 tests (`tests/test_pc1245.py`) need `rom/cpu-1245.rom` and `rom/bas-1245.rom`.

## Acknowledgements

Thanks to [Yoshimine Horiuchi](https://x.com/yo6987), the author of [PokecomGO](https://github.com/digihori/pokecom), who pointed out that the PC-1245's LCD RAM also appears at `E800-EFFF`.

## Rights

The emulator's code and artwork are released under the MIT License ([LICENSE](LICENSE)).

SHARP is a trademark of Sharp Corporation. This is an unofficial emulator made by an individual and has no connection with Sharp Corporation.
