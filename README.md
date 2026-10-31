日本語 | [English](README.en.md)

<img src="images/sc61box-icon.png" width="96" alt="" align="right">

# sc61box: SHARP PC-1251/PC-1245/PC-1261/PC-1350エミュレータ

sc61boxは、SHARPのポケコンに使われたCPU SC61860のエミュレータです。PC-1251、PC-1245、PC-1261、PC-1350の内部ROMとBASIC ROMを、命令単位でそのまま走らせます。ROMがなくても、マシン語を打ち込んで動かせます。

<p>
<img src="images/demo-1251.gif" width="49%" alt="PC-1251で、マシン語の弾むボールを動かすところ">
<img src="images/demo-1245.gif" width="49%" alt="PC-1245で、マシン語の1ドットずつ流れる文字を動かすところ">
<img src="images/demo-1261.gif" width="49%" alt="PC-1261で、マシン語の2行にわたって弾むボールを動かすところ">
<img src="images/demo-1350.gif" width="49%" alt="PC-1350で、マシン語の液晶いっぱいに弾むボールを動かすところ">
</p>

使い方は、手引き[`doc/manual.pdf`](doc/manual.pdf)にインストール方法から順に書いてあります。

## インストールと起動

[uv](https://docs.astral.sh/uv/)を使います。Pythonはuvが用意します。

```sh
git clone https://github.com/woriguchi/sc61box.git
cd sc61box
mkdir rom          # 実機から読み出したROMを置く(下を参照)
uv run sc61box     # 起動
```

ROMはシャープの著作物なので、このリポジトリには入れていません。実機から読み出したものを、次の名前で`rom/`に置きます。使う機種のぶんだけあれば動きます。

| 機種 | ファイル |
| --- | --- |
| PC-1251(PC-1250、PC-1255も) | `cpu-1251.rom`(8KB)、`bas-1251.rom`(16KB) |
| PC-1245 | `cpu-1245.rom`(8KB)、`bas-1245.rom`(16KB) |
| PC-1261(PC-1260、PC-1262も) | `cpu-1260.rom`(8KB)、`bas-1260.rom`(32KB) |
| PC-1350 | `cpu-1350.rom`(8KB)、`bas-1350.rom`(32KB) |

ROMの読み出し方は、手引きの「ROMを用意する」の節にあります。ROMがないときは、マシン語の作業欄で動きます(PC-1350はROMがないと起動できません)。

### 前の名前(pc1251-emulator)で使っていた場合

`git pull`で新しい版にでき、起動のコマンドは`uv run sc61box`です。データのフォルダ(`~/.pc1251`)は初めて起動したときに`~/.sc61box`へ移します。環境変数は`SC61BOX_ROM`などの名前になりましたが、前の`PC1251_ROM`なども読みます。

## 動かし方

```sh
uv run sc61box --model 1261    # 機種を選ぶ(1250、1251、1255、1245、1260、1261、1262、1350)
uv run sc61box primes --run    # 見本のプログラムを読み込んで実行する
uv run sc61box --norom         # ROMを使わず、マシン語の作業欄で動かす
uv run sc61box --lang en       # 画面を英語にする
uv run sc61box --help          # オプションの一覧
```

エミュレータの操作は、本体の絵の下の操作欄のボタンから行います。パソコンのキーと本体のキーの対応は、Cmd+/(WindowsはCtrl+/)で出る説明で確かめられます。終了するとRAMを保存し、次に起動したときに戻します。

次のこともできます。使い方は手引きにあります。

- BASICのテキスト(`.bas`)や16進ダンプ(`.hex`)を、プログラムの一覧から読み込む。打ち込んだプログラムをファイルに書き出す
- マシン語を1命令ずつ実行して、レジスタとメモリの変化を見る(マシン語の作業欄)
- 状態を保存して、あとでそこから続ける(どこでもセーブ)。遊んでいるところを動画に録る
- プリンタに印字する。カセットの音(wav)で実機とプログラムをやり取りする
- ゲームパッドでキーを押す。本体の絵を隠して、液晶だけを大きく見せる

## 見本のプログラム

`programs/`に、BASICとマシン語の見本(弾むボール、ブロック崩しなど)があります。PiO 1986年8月号の「PC-インタープリタ」([Fan_PC-1251](https://x.com/pio1986_10)氏作)と、そのもぐらたたきは、作者の了解を得て収めています。[`doc/pcinterp.pdf`](doc/pcinterp.pdf)は、PC-インタープリタを1命令ずつ解説した小冊子『PC-インタープリタを読む』(おりぐち)です。PC-1261用には、COR氏のコンパイラLC-3(ポケコン・ジャーナル1989年6月号)と、その見本を入れてあります。

## アセンブラ

`tools/asm61860.py`は、SC61860のソース(`.asm`)を組んで、このエミュレータで読める`.hex`を書き出すアセンブラです。書き方の一覧はファイルの先頭にあります。

```sh
uv run python tools/asm61860.py vline.asm vline.hex
```

## 開発について

このエミュレータの作成にはAnthropicのClaudeを利用しています。

## 謝辞

このエミュレータは、次のエミュレータの実装を参考にして作りました。作者の方々にお礼申し上げます。

- [MAME](https://github.com/mamedev/mame)
- [PockEmul](https://github.com/paulie-g/PockEmul)
- [PokecomGO](https://github.com/digihori/pokecom)
- [Pokecom GO Plus](https://github.com/digihori/pokecom-go-plus)

## 権利について

このエミュレータのコードと絵はMITライセンスで公開します([LICENSE](LICENSE))。ただし、`programs/pc1261/`の`lc3.hex`(コンパイラLC-3)と、`lc3-`で始まる見本のうち記事のソース(`lc3-hello`、`lc3-move`、`lc3-chars`)は、LC-3の作者のCOR氏(GitHubではhiroog氏)の作品で、MITライセンスには含まれません。作者は、2018年1月3日の[ブログの記事](https://wlog.flatlib.jp/archive/1/2018-1-3)に「LC-3 の配布に関しては自由に行っていただいて構いません。ダンプリスト、バイナリ等、任意に掲載していただいて結構です。」と書いていて、それに従って同梱しています。コンパイラは[hiroog/LC3_Compiler](https://github.com/hiroog/LC3_Compiler)の`LC-3.bin`を元にしました。

SHARPはシャープ株式会社の商標です。このエミュレータは個人が作った非公式のもので、シャープ株式会社とは関係ありません。
