"""遊んでいるところを動画(MP4、音つき)に録る

上に液晶を拡大して置き、その下に本体全体を並べた1280×720の動画にする。フレームごとに
本体の絵(display.Panelの絵、原寸)をffmpegに渡し、切り抜きと拡大、重ね合わせは
ffmpegのフィルタで行う。ffmpegはPATHにあるもの、なければimageio-ffmpegのものを使う。

音は、鳴らす音とは別に、Cポートの書き換えの記録から作り直す(audio.Buzzer)。
フレームの数は音のサンプルの数に合わせ(1470サンプルで1フレーム)、エミュレータが1フレームで
多めに進んだときは同じ絵を続けて書く。
"""

import os
import queue
import shutil
import subprocess
import threading
import wave

from PIL import Image, ImageDraw, ImageFont

from . import display
from .audio import RATE
from .i18n import tr

W, H = 1280, 720
FPS = 30
SPF = RATE // FPS  # 1フレームぶんのサンプル
BG = (22, 23, 26)
LCD_W = 1240  # 液晶を拡大した幅
LCD_TOP = 78
# PC-1251の本体の絵(display.Panelの絵)の中で、液晶と表示記号を囲む枠
LCD_BOX = (
    display.MARGIN + display.MAT_X - 18,
    display.MARGIN + display.ANN_Y - 8,
    display.MARGIN + display.MAT_X + display.MAT_W + 18,
    display.MARGIN + display.MAT_Y + display.MAT_H + 16,
)
FONTS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def ffmpeg_exe() -> str:
    """使うffmpeg。PATHになければimageio-ffmpegに入っているもの。どちらもなければOSError
    (imageio-ffmpegがffmpegを含むのはWindows、macOS、Linuxのx86_64とaarch64だけ)"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as e:
        raise OSError(tr("ffmpegが見つかりません。ffmpegを入れてPATHに置くと録画できます")) from e


def _font(size: int):
    for path in FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=0)
            except OSError:
                continue
    return None


def header_image(path: str, title: str, sub: str) -> None:
    """動画の地(背景と、左上の題名)を画像にする"""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    big, small = _font(30), _font(18)
    if big is not None and small is not None:
        d.text((40, 22), title, font=big, fill=(235, 235, 230))
        tw = d.textlength(title, font=big)
        d.text((40 + tw + 18, 34), sub, font=small, fill=(150, 152, 158))
    img.save(path)


def layout(lcd_box=LCD_BOX) -> tuple[int, int, int]:
    """拡大した液晶の高さ、本体を置く高さの位置、本体の高さ"""
    x0, y0, x1, y1 = lcd_box
    lcd_h = round((y1 - y0) * LCD_W / (x1 - x0) / 2) * 2
    top = LCD_TOP + lcd_h + 14
    body_h = (H - 20 - top) // 2 * 2
    return lcd_h, top, body_h


class Recorder:
    """録画。add()をフレームごとに呼び、close()で動画を仕上げる"""

    def __init__(
        self,
        path: str,
        title: str,
        sub: str,
        size: tuple[int, int] = (display.OUT_W, display.OUT_H),
        lcd_box: tuple[int, int, int, int] = LCD_BOX,
    ) -> None:
        """sizeは渡す本体の絵の大きさ、lcd_boxはその中で拡大して見せる液晶の範囲"""
        self.exe = ffmpeg_exe()  # 途中のファイルを作る前に確かめる
        self.path = path
        self.work = path + ".tmp"
        os.makedirs(self.work, exist_ok=True)
        self.video = os.path.join(self.work, "v.mp4")
        self.audio = os.path.join(self.work, "a.wav")
        header = os.path.join(self.work, "header.png")
        header_image(header, title, sub)
        x0, y0, x1, y1 = lcd_box
        lcd_h, top, body_h = layout(lcd_box)
        self.frame_bytes = size[0] * size[1] * 3
        graph = (
            f"[0:v]split[a][b];"
            f"[a]crop={x1 - x0}:{y1 - y0}:{x0}:{y0},scale={LCD_W}:{lcd_h}:flags=lanczos[lcd];"
            f"[b]scale=-2:{body_h}:flags=lanczos[body];"
            f"[1:v][lcd]overlay={(W - LCD_W) // 2}:{LCD_TOP}:shortest=1[t];"
            f"[t][body]overlay=(W-w)/2:{top}:shortest=1,format=yuv420p[v]"
        )
        self.proc = subprocess.Popen(
            [
                self.exe, "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-",
                "-loop", "1", "-framerate", str(FPS), "-i", header,
                "-filter_complex", graph, "-map", "[v]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                self.video,
            ],
            stdin=subprocess.PIPE,
        )  # fmt: skip
        self.wav = wave.open(self.audio, "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)
        self.samples = 0
        self.frames = 0  # ffmpegに渡したフレームの数
        self.error = ""
        # パイプへの書き込みでフレームが止まらないよう、別のスレッドで書く
        self.q: queue.Queue[bytes | None] = queue.Queue(maxsize=FPS * 3)
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _write(self) -> None:
        stdin = self.proc.stdin
        assert stdin is not None
        while (frame := self.q.get()) is not None:
            if self.error:
                continue
            try:
                stdin.write(frame)
            except (BrokenPipeError, OSError) as e:
                self.error = str(e) or tr("ffmpegが止まりました")

    @property
    def seconds(self) -> float:
        return self.samples / RATE

    def add(self, picture: bytes, pcm: bytes) -> None:
        """1フレームぶん。pictureは本体の絵(RGB、原寸)、pcmはそのあいだの音(16ビット)"""
        if len(picture) != self.frame_bytes:
            raise ValueError(
                tr("絵の大きさが違います({size}バイト、{want}バイトのはず)",
                   size=len(picture), want=self.frame_bytes)
            )  # fmt: skip
        self.wav.writeframes(pcm)
        self.samples += len(pcm) // 2
        while self.frames < self.samples // SPF:
            self.q.put(picture)
            self.frames += 1

    def close(self) -> str:
        """録画を終えて動画を仕上げ、できたファイルのパスを返す。失敗したら例外"""
        self.q.put(None)
        self.thread.join()
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        code = self.proc.wait()
        self.wav.close()
        if self.error or code != 0:
            shutil.rmtree(self.work, ignore_errors=True)
            raise OSError(self.error or tr("ffmpegが終了コード{code}で止まりました", code=code))
        done = subprocess.run(
            [
                self.exe, "-y", "-loglevel", "error", "-i", self.video, "-i", self.audio,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                "-movflags", "+faststart", self.path,
            ],
            capture_output=True, text=True,
        )  # fmt: skip
        shutil.rmtree(self.work, ignore_errors=True)
        if done.returncode != 0:
            raise OSError(done.stderr.strip() or tr("動画を仕上げられませんでした"))
        return self.path

    def abort(self) -> None:
        """録画をやめて、途中のファイルを消す"""
        self.q.put(None)
        self.thread.join()
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait()
        self.wav.close()
        shutil.rmtree(self.work, ignore_errors=True)
