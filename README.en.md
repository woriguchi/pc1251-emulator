[日本語](README.md) | English

# SHARP PC-1251 emulator

An emulator for the Sharp PC-1251, a pocket computer from the early 1980s. It executes the SC61860 CPU one instruction at a time and runs the machine's own internal ROM and BASIC ROM, so BASIC programs and machine code both work. You can press the keys and move the mode switch with the mouse. The LCD and case are rendered from measured dimensions, with colours sampled from photos of the real machine.

![PC-1251](images/screen.png)

![Typing in BASIC and running it, then running a machine-code sine wave from the right-click menu](images/demo.gif)

The user guide, starting from installation on macOS and Windows, is [`doc/manual.pdf`](doc/manual.pdf) (in Japanese).

## Installing

You need [uv](https://docs.astral.sh/uv/). uv fetches a suitable Python by itself.

```sh
git clone <URL of this repository>
cd pc1251-emulator
mkdir rom                            # put the ROM read from your own machine here (see below)
uv run pc1251                        # start
```

### Preparing the ROM

The ROM is Sharp's copyrighted work, so it is not in this repository. Read it out of your own PC-1251 and put it in `rom/` under these names.

| File | Contents | Size |
| --- | --- | --- |
| `cpu-1251.rom` | the SC61860's internal ROM, `0000-1FFF` | 8192 bytes |
| `bas-1251.rom` | the BASIC ROM, `4000-7FFF` | 16384 bytes |

For example, if you cloned into `~/src`, the files are `~/src/pc1251-emulator/rom/cpu-1251.rom` and `~/src/pc1251-emulator/rom/bas-1251.rom`.

yagshi's page "[Extracting ROM Data](https://www.oit.ac.jp/rd/labs/kobayashi-lab/~yagshi/old_web/misc/pocketcom/extrom.html)" (in Japanese) describes how to do it on a PC-1251. ROMs come in different versions, so only the file sizes are checked. To keep the ROM elsewhere, set the environment variable `PC1251_ROM` to that folder.

## Running

```sh
uv run pc1251 --scale 0.8            # smaller window
uv run pc1251 primes --run           # load primes.bas from the program folder and run it
uv run pc1251 ~/prog/game.bas        # load a file by path
uv run pc1251 --fresh                # start without the saved RAM
uv run pc1251 --help                 # list the options
```

On exit the RAM is saved to `~/.pc1251/ram.bin` and restored at the next start.

### Program files

Put `.bas` files (BASIC as plain text) or `.hex` files (hex dumps, one `address data` line after another) in `~/.pc1251/programs/`, and they appear in the program list (Cmd+O, or Ctrl+O on Windows). Enter loads the selected program; Shift+Enter loads and runs it. You can also drop a file onto the window.

A BASIC program typed in the emulator can be exported with Cmd+E (Ctrl+E on Windows) to `~/.pc1251/programs/` as `name-date.bas`. Machine code is not exported. `uv run pc1251 --export folder` exports from the saved RAM.

A `.bas` file is typed in at full speed after a `NEW` in PRO mode; a `.hex` file is written straight into RAM, and anything after `;` on a line is a comment. A `.bas` and a `.hex` with the same name form one program: the dump is written first, then the BASIC is typed in.

Lines starting with `#` are comments; `# title: name in the list`, `# run: what to type to run it` and `# hex: a dump file to load first` are read as settings. `programs/` has nine samples: HELLO, BEEP, primes, a text animation, a display-during-calculation demo, a machine-code sine wave, breakout, the PC-Interpreter and a mole-bashing game.

### Keys

Click the keys on screen with the mouse. Letters, digits, symbols, Enter, Space and the arrow keys on your own keyboard work as well.

| macOS | Windows | PC-1251 |
| --- | --- | --- |
| Tab | Tab | SHIFT |
| Option | Alt | DEF |
| delete | Backspace | delete one character |
| fn+delete | Delete | CL |
| Esc | Esc | BRK (ON while the power is off) |
| Cmd+↑, Cmd+↓ | Ctrl+↑, Ctrl+↓ | move the mode switch up or down one step |
| Cmd+O | Ctrl+O | program list |
| Cmd+R | Ctrl+R | the RESET button on the back |
| Cmd+T | Ctrl+T | speed (1× or 4×) |
| Cmd+E | Ctrl+E | export the BASIC program in memory to a .bas file |
| Cmd+S | Ctrl+S | save a screenshot |
| Cmd+/ | Ctrl+/ | key help |
| Cmd+V | Ctrl+V | type the clipboard text in |

Right-click opens a menu with the same actions. Its first item lets you pick a sample and run it straight away. Turn off Japanese input before typing.

### Breakout

`programs/break.hex` and `break.bas` are a sideways breakout game written in machine code. Move the paddle with ↑ and ↓, serve with Space, and knock bricks out of the wall creeping in from the right. At the start choose 1 (EASY, three-dot paddle) or 2 (NORMAL, two-dot paddle).

### PC-Interpreter and "Reading the PC-Interpreter"

The "PC-Interpreter" from the August 1986 issue of the Japanese magazine PiO (by [Fan_PC-1251](https://x.com/pio1986_10)) runs as well. `programs/pcint.hex` is the article's listing 1 and `programs/mogura.bas` is listing 2, a mole-bashing game; both are included with the author's permission.

Start the game from the right-click menu, then hold down the number key (1–6) of the hole the mole pops out of.

[`doc/pcinterp.pdf`](doc/pcinterp.pdf) is "PC-インタープリタを読む" (Reading the PC-Interpreter, by origuchi), a booklet in Japanese that reads the program instruction by instruction.

## How it works

| File | Contents |
| --- | --- |
| `pc1251emu/sc61860.py` | CPU core. The 256 opcodes are dispatched through a table of functions |
| `pc1251emu/machine.py` | memory, key matrix, timers, ports, LCD RAM, power |
| `pc1251emu/display.py` | drawing the case and the LCD |
| `pc1251emu/audio.py` | the piezo buzzer |
| `pc1251emu/app.py` | window, keyboard and mouse, automatic typing |
| `pc1251emu/programs.py` | the program folders and how .bas/.hex files are read |
| `doc/manual.pdf` | the user guide (in Japanese) |

Instruction semantics follow MAME's SC61860 implementation, except for `56h` (READ), `LOOP` and `WAIT n`, which sources describe differently; for those I followed how real programs use them. The clock is 192 kHz.

The memory map is: internal ROM at `0000-1FFF`, BASIC ROM at `4000-7FFF`, RAM at `B800-C7FF` and LCD RAM at `F800-F87F`.

The mode switch is read with INB after setting bit 3 of port IB. Bit 0 means RSV, bit 1 PRO and bit 2 OFF; with none of them set the switch is at RUN. On OFF the ROM writes a marker into internal RAM `30h-37h` and powers itself off; if the marker is missing at the next power-on, it clears the program.

On port C, bit 0 turns the display on, bit 2 halts the CPU (a key or the 512 ms timer wakes it), bit 3 powers off and bits 4–6 drive the buzzer: `3` selects the built-in 4 kHz oscillator, and `5` and `4` set the output high and low.

The left 60 columns of the LCD are `F800-F83B` in order, and the right 60 are `F87B` down to `F840`. The annunciators are bits in `F83C-F83E`.

### Differences from the real machine

- Cassette I/O has not been verified. `CSAVE` makes a plausible sound, but a recording of it may not load on a real machine. Stop `CLOAD` with BRK (Esc).
- The CE-125 printer is not emulated.
- Different ROM versions have not been checked.
- BASIC's `PEEK` can read the internal ROM here (the real CPU reads it only with the `DATA` instruction).

## Tests

```sh
uv run pytest -q tests
```

Tests that need the ROM are skipped when it isn't there.

## Rights

The emulator's code and artwork are released under the MIT License ([LICENSE](LICENSE)).

SHARP is a trademark of Sharp Corporation. This is an unofficial emulator made by an individual and has no connection with Sharp Corporation.
