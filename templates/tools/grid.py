# -*- coding: utf-8 -*-
"""
grid.py —— 给精确渲染页叠 100px 坐标网，用于人工标定「人脸安全区」

本机没有可用的人脸检测模型（无网络、无 haarcascade、无 insightface）。
所以人脸框由人工在坐标网上标定，结果写进 faces.json，
后续用 check_faces.py 自动校验——标定只做一次，检查每次都能跑。

用法：python tools/grid.py page01 page08
输出：_shots/guard/grid_<page>.png
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
GUARD = os.path.join(SHOTS, "guard")


def fnt(s):
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, s)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    names = sys.argv[1:] or ["page01"]
    for n in names:
        src = os.path.join(SHOTS, n + ".png")
        im = Image.open(src).convert("RGB")
        d = ImageDraw.Draw(im)
        for x in range(0, im.width, 100):
            d.line([(x, 0), (x, im.height)], fill=(0, 200, 255), width=1)
            d.text((x + 3, 3), str(x), fill=(0, 120, 255), font=fnt(15))
        for y in range(0, im.height, 100):
            d.line([(0, y), (im.width, y)], fill=(0, 200, 255), width=1)
            d.text((3, y + 3), str(y), fill=(0, 120, 255), font=fnt(15))
        for x in range(0, im.width, 100):
            for y in range(0, im.height, 500):
                d.text((x + 3, y + 22), "%d,%d" % (x, y), fill=(255, 0, 160), font=fnt(13))
        im.save(os.path.join(GUARD, "grid_%s.png" % n))
        print("->", os.path.join(GUARD, "grid_%s.png" % n))


if __name__ == "__main__":
    main()
