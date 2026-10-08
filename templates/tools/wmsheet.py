# -*- coding: utf-8 -*-
"""
wmsheet.py —— 「右下角对照拼图」：把素材目录里每张图的右下角裁出来排成一张图，供**人眼**目检第三方水印。

为什么需要它：
    电商供货图几乎都带供货方水印（常见形态：产品右下方背景上的白色半透明艺术字）。
    它在整页成品图上小到看不见，但在素材上明明白白 —— 所以判据只能是「逐张看右下角」。

为什么不能只靠自动检测：
    按「比周围亮」找亮簇的检测器，会被**大面积白色产品**喂成一片假阳性
    （白色文胸下缘、白色背景、高光全都命中），噪声高到无法作判据。
    自动检测只用来缩小范围，最终判据永远是这张对照拼图。

用法：
    python tools/wmsheet.py                        # 默认扫 images/
    python tools/wmsheet.py --dir images --out _work/probe/_wm_all.jpg
    python tools/wmsheet.py --x 0.60 --y 0.78      # 改取样窗口（默认右下 40%x22%）
    python tools/wmsheet.py --cols 6 --w 320 --h 200

输出：一张拼图，每格下方标注文件名。
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw

EXT = (".jpg", ".jpeg", ".png", ".webp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="images")
    ap.add_argument("--out", default=os.path.join("_work", "probe", "_wm_all.jpg"))
    ap.add_argument("--x", type=float, default=0.60, help="取样窗口左边界（归一化）")
    ap.add_argument("--y", type=float, default=0.78, help="取样窗口上边界（归一化）")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--w", type=int, default=320, help="每格宽")
    ap.add_argument("--h", type=int, default=200, help="每格高")
    a = ap.parse_args()

    if not os.path.isdir(a.dir):
        print("找不到目录：%s" % a.dir)
        return 2

    files = sorted(f for f in os.listdir(a.dir) if f.lower().endswith(EXT))
    if not files:
        print("目录里没有图片：%s" % a.dir)
        return 2

    tiles = []
    for f in files:
        try:
            im = Image.open(os.path.join(a.dir, f)).convert("RGB")
        except Exception as e:
            print("跳过 %s（%s）" % (f, e))
            continue
        W, H = im.size
        c = im.crop((int(a.x * W), int(a.y * H), W, H))
        s = min(a.w / c.width, a.h / c.height)
        c = c.resize((max(1, round(c.width * s)), max(1, round(c.height * s))), Image.LANCZOS)
        tiles.append((f, c))

    if not tiles:
        print("没有可用图片")
        return 2

    CW = max(t[1].width for t in tiles)
    CH = max(t[1].height for t in tiles)
    rows = (len(tiles) + a.cols - 1) // a.cols
    sheet = Image.new("RGB", (a.cols * (CW + 8) + 8, rows * (CH + 26) + 8), (250, 250, 250))
    d = ImageDraw.Draw(sheet)
    for i, (f, c) in enumerate(tiles):
        r, cc = divmod(i, a.cols)
        x, y = 8 + cc * (CW + 8), 8 + r * (CH + 26)
        sheet.paste(c, (x, y))
        d.rectangle([x - 1, y - 1, x + CW, y + CH], outline=(200, 200, 200))
        d.text((x + 2, y + CH + 6), f, fill=(10, 10, 10))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    sheet.save(a.out, quality=90)
    print("%d 张 -> %s  %dx%d" % (len(tiles), a.out, sheet.width, sheet.height))
    print("→ 逐格目检：有没有和产品无关的「白色/浅色文字或标识」压在右下方。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
