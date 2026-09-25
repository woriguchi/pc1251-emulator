"""筐体と液晶の描画

筐体の絵と寸法は、以前に作った画面シミュレータで実機の写真から実測したものを
持ってきた。このモジュールは絵を読み込むだけで、あちらのコードは使わない。

液晶は次の点を実機に似せた。

* 点灯ドットは黒でなく濃い青紫。消灯しているドットも薄く見える。
* 反射型の液晶なので、ドットの影が奥の反射板に落ち、右下へずれて見える。
* 応答が遅い(点灯より消灯が遅い)ので、動くものは尾を引く。
* Cポートのビット0で表示を切ると、液晶全体が消える(BASICの実行中など)。
"""

import json
import math
import os

import pygame
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

with open(os.path.join(ASSETS, "keys.json")) as _f:
    _KEYS = json.load(_f)
IMG_W = 1425
BODY_H = _KEYS["top"]  # 液晶部の高さ。その下がキーボード
IMG_H = _KEYS["height"]
KEY_RECTS = {k: tuple(v) for k, v in _KEYS["keys"].items()}
MARGIN = 28  # 本体のまわりの机の幅
OUT_W, OUT_H = IMG_W + 2 * MARGIN, IMG_H + 2 * MARGIN
CORNER_R = 8  # 本体の角の丸み。実機の角はほとんど直角に近い
CELLS, CW, H = 24, 5, 7
W = CELLS * CW  # 120列
DOT, PITCH = 5, 7
PHYS_W = CELLS * (CW + 1) - 1
MAT_W = PHYS_W * PITCH - 1
MAT_H = H * PITCH - 1
MAT_X, MAT_Y = 156, 149  # tools/body_art.pyと同じ値
ANN_Y, ANN_H = 119, 18

DOT_INK = (28, 36, 64)
SHADOW_INK = (40, 48, 44)
OFF_ALPHA = 30  # 消灯ドットの見え方
ON_ALPHA = 238
SHADOW_ALPHA = 60  # 反射板に落ちる影の濃さ(点灯時)
SHADOW_DX, SHADOW_DY = 2, 2  # 影のずれ(px)
LEVELS = 8
TAU_RISE_MS = 33.0
TAU_FALL_MS = 86.0


def phys_x(x: int) -> int:
    return (x // CW) * (CW + 1) + (x % CW)


def _surface(img: Image.Image) -> pygame.Surface:
    mode = img.mode if img.mode in ("RGB", "RGBA") else "RGBA"
    img = img.convert(mode)
    s = pygame.image.frombytes(img.tobytes(), img.size, mode)
    return s.convert_alpha() if mode == "RGBA" else s.convert()


class Panel:
    def __init__(self):
        self.body = Image.open(os.path.join(ASSETS, "body_top.png")).convert("RGB")
        with open(os.path.join(ASSETS, "switch_box.txt")) as f:
            self.sw_xy = tuple(int(v) for v in f.read().split())
        self.switch = {
            m: _surface(Image.open(os.path.join(ASSETS, f"switch_{m}.png")))
            for m in ("RUN", "PRO", "RSV", "OFF")
        }
        self.out = pygame.Surface((OUT_W, OUT_H))
        self.out.blit(_surface(self._desk()), (0, 0))
        self.rim = _surface(self._rim())
        self.canvas = pygame.Surface((IMG_W, IMG_H))
        self.canvas.blit(_surface(self.body), (0, 0))
        kb_up = Image.open(os.path.join(ASSETS, "keyboard_up.png")).convert("RGB")
        kb_down = Image.open(os.path.join(ASSETS, "keyboard_down.png")).convert("RGB")
        self.canvas.blit(_surface(kb_up), (0, BODY_H))
        self.key_up = {}
        self.key_down = {}
        for name, (x0, y0, x1, y1) in KEY_RECTS.items():
            box = (x0, y0 - BODY_H, x1, y1 - BODY_H)
            self.key_up[name] = _surface(kb_up.crop(box))
            self.key_down[name] = _surface(kb_down.crop(box))
        self.shown_down: set[str] = set()
        self.glass = _surface(self._glass())
        self.ann_bg = _surface(self.body.crop((MAT_X, ANN_Y, MAT_X + MAT_W, ANN_Y + ANN_H)))
        self.dots = [self._dot(k) for k in range(LEVELS)]
        self.shadows = [self._shadow(k) for k in range(LEVELS)]
        self.symbols = {}
        with open(os.path.join(ASSETS, "symbols.txt")) as f:
            for line in f:
                name, x = line.split()
                mask = Image.open(os.path.join(ASSETS, f"sym_{name}.png")).convert("L")
                imgs = []
                for k in range(LEVELS):
                    a = int(ON_ALPHA * k / (LEVELS - 1))
                    im = Image.new("RGBA", mask.size, DOT_INK + (0,))
                    im.putalpha(mask.point(lambda v, a=a: v * a // 255))
                    imgs.append(_surface(im))
                self.symbols[name] = (int(x), imgs)
        self.level = [[0.0] * W for _ in range(H)]
        self.sym_level = {n: 0.0 for n in self.symbols}
        self.set_fps(30)

    def set_fps(self, fps: float, persist: float = 1.0) -> None:
        dt = 1000.0 / fps
        if persist <= 0:
            self.rise = self.fall = 1.0
        else:
            self.rise = 1.0 - math.exp(-dt / (TAU_RISE_MS * persist))
            self.fall = 1.0 - math.exp(-dt / (TAU_FALL_MS * persist))

    # ---- 下ごしらえ ----
    def _desk(self) -> Image.Image:
        """机の上に置いた本体の影"""
        im = Image.new("RGB", (OUT_W, OUT_H), (46, 47, 50))
        d = ImageDraw.Draw(im)
        for y in range(OUT_H):
            t = y / (OUT_H - 1)
            d.line(
                [(0, y), (OUT_W, y)], fill=(int(58 - 16 * t), int(59 - 16 * t), int(63 - 16 * t))
            )
        sh = Image.new("L", (OUT_W, OUT_H), 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            [MARGIN + 4, MARGIN + 10, MARGIN + IMG_W + 4, MARGIN + IMG_H + 12],
            radius=CORNER_R,
            fill=200,
        )
        sh = sh.filter(ImageFilter.GaussianBlur(11))
        im.paste(Image.new("RGB", im.size, (8, 8, 10)), (0, 0), sh)
        return im

    def _rim(self) -> Image.Image:
        """本体の角の外側(机の色)と、縁の面取りの光と影。毎フレーム本体の上に重ねる"""
        desk = self._desk().crop((MARGIN, MARGIN, MARGIN + IMG_W, MARGIN + IMG_H)).convert("RGBA")
        inside = Image.new("L", (IMG_W, IMG_H), 0)
        ImageDraw.Draw(inside).rounded_rectangle(
            [0, 0, IMG_W - 1, IMG_H - 1], radius=CORNER_R, fill=255
        )
        out = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
        out.paste(desk, (0, 0), ImageChops.invert(inside))
        # 面取り: 上と左は光を返し、下と右は落ちる
        edge = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
        ed = ImageDraw.Draw(edge)
        ed.rounded_rectangle(
            [0, 0, IMG_W - 1, IMG_H - 1], radius=CORNER_R, outline=(250, 250, 248, 120), width=1
        )
        ed.rounded_rectangle(
            [1, 1, IMG_W - 2, IMG_H - 2], radius=CORNER_R - 1, outline=(255, 255, 255, 40), width=1
        )
        low = Image.linear_gradient("L").resize((IMG_W, IMG_H))  # 下ほど濃い影
        dark = Image.new("RGBA", (IMG_W, IMG_H), (0, 0, 0, 0))
        ImageDraw.Draw(dark).rounded_rectangle(
            [0, 0, IMG_W - 1, IMG_H - 1], radius=CORNER_R, outline=(60, 60, 58, 170), width=2
        )
        dark.putalpha(ImageChops.multiply(dark.getchannel("A"), low))
        edge = Image.alpha_composite(edge, dark)
        edge.putalpha(ImageChops.multiply(edge.getchannel("A"), inside))
        return Image.alpha_composite(out, edge)

    def _glass(self) -> Image.Image:
        box = (MAT_X - 4, MAT_Y - 4, MAT_X + MAT_W + 4, MAT_Y + MAT_H + 4)
        im = self.body.crop(box).convert("RGBA")
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for y in range(H):
            for x in range(W):
                px = 4 + phys_x(x) * PITCH
                py = 4 + y * PITCH
                d.rectangle([px, py, px + DOT - 1, py + DOT - 1], fill=DOT_INK + (OFF_ALPHA,))
        return Image.alpha_composite(im, ov).convert("RGB")

    def _dot(self, k: int) -> pygame.Surface:
        a = int(OFF_ALPHA + (ON_ALPHA - OFF_ALPHA) * k / (LEVELS - 1))
        im = Image.new("RGBA", (DOT, DOT), DOT_INK + (a,))
        # 角はわずかに丸い
        for x, y in ((0, 0), (DOT - 1, 0), (0, DOT - 1), (DOT - 1, DOT - 1)):
            im.putpixel((x, y), DOT_INK + (int(a * 0.55),))
        return _surface(im)

    def _shadow(self, k: int) -> pygame.Surface:
        a = int(SHADOW_ALPHA * k / (LEVELS - 1))
        size = DOT + 6
        m = Image.new("L", (size, size), 0)
        ImageDraw.Draw(m).rectangle([3, 3, 3 + DOT - 1, 3 + DOT - 1], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(1.1)).point(lambda v: v * a // 255)
        im = Image.new("RGBA", (size, size), SHADOW_INK + (0,))
        im.putalpha(m)
        return _surface(im)

    # ---- 1フレーム ----
    def key_at(self, x: float, y: float) -> str | None:
        for name, (x0, y0, x1, y1) in KEY_RECTS.items():
            if x0 <= x < x1 and y0 <= y < y1:
                return name
        return None

    def draw(
        self,
        columns: list[int],
        symbols: set[str],
        on: bool,
        mode: str,
        pressed: set[str] | frozenset[str] = frozenset(),
    ) -> pygame.Surface:
        dst = self.canvas
        dst.blit(self.switch[mode], self.sw_xy)
        pressed = {k for k in pressed if k in KEY_RECTS}
        if pressed != self.shown_down:  # 押されているキーだけ沈んだ絵にする
            for k in self.shown_down - pressed:
                dst.blit(self.key_up[k], KEY_RECTS[k][:2])
            for k in pressed - self.shown_down:
                dst.blit(self.key_down[k], KEY_RECTS[k][:2])
            self.shown_down = pressed
        dst.blit(self.glass, (MAT_X - 4, MAT_Y - 4))
        rise, fall = self.rise, self.fall
        top = LEVELS - 1
        level = self.level
        todo = []
        for y in range(H):
            lrow = level[y]
            bit = 1 << y
            py = MAT_Y + y * PITCH
            for x in range(W):
                v = lrow[x]
                if on and columns[x] & bit:
                    v += (1.0 - v) * rise
                else:
                    v -= v * fall
                    if v < 0.004:
                        v = 0.0
                lrow[x] = v
                k = int(v * top + 0.5)
                if k:
                    todo.append((MAT_X + phys_x(x) * PITCH, py, k))
        sh = self.shadows
        for px, py, k in todo:  # 影を先に、ドットを後に重ねる
            dst.blit(sh[k], (px - 3 + SHADOW_DX, py - 3 + SHADOW_DY))
        dots = self.dots
        for px, py, k in todo:
            dst.blit(dots[k], (px, py))

        dst.blit(self.ann_bg, (MAT_X, ANN_Y))
        for name, (x, imgs) in self.symbols.items():
            v = self.sym_level[name]
            if on and name in symbols:
                v += (1.0 - v) * rise
            else:
                v -= v * fall
            self.sym_level[name] = v
            k = int(v * top + 0.5)
            if k:
                dst.blit(imgs[k], (MAT_X + x, ANN_Y))
        self.out.blit(dst, (MARGIN, MARGIN))
        self.out.blit(self.rim, (MARGIN, MARGIN))
        return self.out
