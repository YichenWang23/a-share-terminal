# -*- coding: utf-8 -*-
"""生成股票系统图标：深蓝底 + 蜡烛图 + 鲸鱼尾 + 向上箭头。

输出：
    icon.ico                    6 尺寸（快捷方式用）
    icon-preview.png            256 预览
    static/icon.ico             网页 favicon
    static/icon-192.png         PWA
    static/icon-512.png         PWA

用法：python tools/make_icon.py
"""
import os
import sys

from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO = os.path.join(BASE, "icon.ico")
PREVIEW = os.path.join(BASE, "icon-preview.png")
STATIC = os.path.join(BASE, "static")

SIZE = 256
BG_TOP = (10, 22, 40)
BG_BOTTOM = (6, 14, 26)
BLUE = (58, 110, 220)
BLUE_LIGHT = (120, 170, 255)
RED = (235, 78, 78)
GREEN = (40, 170, 150)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def draw_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256.0
    for y in range(size):
        d.line([(0, y), (size, y)], fill=lerp(BG_TOP, BG_BOTTOM, y / max(1, size - 1)))
    img.putalpha(rounded_mask(size, int(48 * s)))

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([int(6 * s), int(6 * s), size - int(6 * s), size - int(6 * s)],
                        radius=int(42 * s), outline=(70, 96, 140, 170), width=max(1, int(3 * s)))
    for i in range(1, 4):
        y = int(size * (0.25 + i * 0.16))
        d.line([(int(26 * s), y), (size - int(26 * s), y)],
               fill=(40, 58, 88, 120), width=max(1, int(1.5 * s)))

    candles = [
        (0.22, 0.62, 0.74, 0.56, 0.80, GREEN),
        (0.38, 0.48, 0.60, 0.43, 0.66, RED),
        (0.54, 0.54, 0.66, 0.49, 0.72, GREEN),
        (0.70, 0.34, 0.46, 0.28, 0.52, RED),
        (0.84, 0.24, 0.36, 0.18, 0.42, RED),
    ]
    body_w = max(3, int(16 * s))
    for cx, bt, bb, wt, wb, color in candles:
        x = int(size * cx)
        d.line([(x, int(size * wt)), (x, int(size * wb))], fill=color, width=max(2, int(4 * s)))
        d.rounded_rectangle([x - body_w // 2, int(size * bt), x + body_w // 2, int(size * bb)],
                            radius=max(2, int(4 * s)), fill=color)

    pts = [(int(size * 0.16), int(size * 0.78)), (int(size * 0.34), int(size * 0.66)),
           (int(size * 0.52), int(size * 0.72)), (int(size * 0.72), int(size * 0.44)),
           (int(size * 0.88), int(size * 0.30))]
    d.line(pts, fill=BLUE_LIGHT + (230,), width=max(2, int(5 * s)), joint="curve")
    for p in pts[1:]:
        r = max(2, int(4 * s))
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=BLUE_LIGHT)
    tip = (int(size * 0.90), int(size * 0.24))
    d.polygon([tip, (tip[0] - int(20 * s), tip[1] + int(4 * s)),
               (tip[0] - int(6 * s), tip[1] + int(26 * s))], fill=BLUE_LIGHT)

    tx, ty = int(size * 0.24), int(size * 0.22)
    d.polygon([(tx, ty + int(26 * s)), (tx - int(20 * s), ty),
               (tx - int(10 * s), ty + int(14 * s)), (tx - int(2 * s), ty - int(2 * s)),
               (tx + int(6 * s), ty + int(14 * s)), (tx + int(16 * s), ty)], fill=BLUE)
    return img


def main():
    base = draw_icon(SIZE)
    base.save(PREVIEW)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(ICO, format="ICO", sizes=sizes)

    os.makedirs(STATIC, exist_ok=True)
    base.save(os.path.join(STATIC, "icon.ico"), format="ICO", sizes=sizes)
    base.resize((192, 192), Image.LANCZOS).save(os.path.join(STATIC, "icon-192.png"))
    base.resize((512, 512), Image.LANCZOS).save(os.path.join(STATIC, "icon-512.png"))

    for name in ("icon.ico", "icon-preview.png", "static/icon.ico",
                 "static/icon-192.png", "static/icon-512.png"):
        path = os.path.join(BASE, name.replace("/", os.sep))
        print("%-22s %6d 字节" % (name, os.path.getsize(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
