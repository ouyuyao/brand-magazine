# -*- coding: utf-8 -*-
"""
preview.py —— 把 _shots/ 里的整页渲染拼成一张总览图（人工复核用）

为什么需要：逐页打开 N 个 PNG 太慢，缩到一张图上才能一眼看出
「有没有哪页明显破了」（错位、空白、文字溢出、标签压图）。
注意它只用于"看版式"，读小字请用 tools/probe.py 的带尺裁切。

页列表 = _shots/page*.png（由 shoot.js 按 layout/ 生成，不写死页数）。
各页画布尺寸可以不同 —— 这里逐页按自己的长宽比缩放后就位。

用法：
  python tools/preview.py                       # 正表记稿 -> preview-pages.jpg
  python tools/preview.py --tag zh              # 中文对照稿 -> preview-pages_zh.jpg
  python tools/preview.py --cell 500            # 每页宽度（默认 455）
  python tools/preview.py --cols 3 --out x.jpg
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")

argv = sys.argv[1:]
tag = argv[argv.index("--tag") + 1] if "--tag" in argv else ""
cell = int(argv[argv.index("--cell") + 1]) if "--cell" in argv else 455
cols = int(argv[argv.index("--cols") + 1]) if "--cols" in argv else 3
out = argv[argv.index("--out") + 1] if "--out" in argv else (
    "preview-pages%s.jpg" % ("_" + tag if tag else ""))

import glob, re
# 严格匹配，避免「正表记稿」把中文对照稿（pageNN_zh.png）也收进来。
#   无 --tag  -> 只收 pageNN.png
#   有 --tag  -> 只收 pageNN_<tag>.png
core = re.compile(r"^page\d+$" if not tag else r"^page\d+_" + re.escape(tag) + r"$")
files = []
for f in sorted(glob.glob(os.path.join(SHOTS, "page*.png"))):
    b = os.path.basename(f)
    if b.startswith("_"):
        continue
    name = b[:-4]
    if not core.match(name):
        continue
    files.append((name, f))
if not files:
    print("!! _shots/ 里没有找到整页渲染，先跑 node tools/shoot.js")
    sys.exit(2)
files.sort(key=lambda t: int(re.search(r"\d+", t[0]).group()))


def fnt(s):
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, s)
            except Exception:
                pass
    return ImageFont.load_default()


label_h = 22
# 各行高度取「所有页里最高的那个长宽比」，这样页面尺寸不一致时也不会互相挤压
_ratios = []
for _n, _f in files:
    _w, _h = Image.open(_f).size
    _ratios.append(_h / _w)
ratio = max(_ratios)
cw = cell
ch = int(cell * ratio)
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cw * cols, (ch + label_h) * rows), (210, 206, 200))
d = ImageDraw.Draw(sheet)
for i, (name, f) in enumerate(files):
    im = Image.open(f).convert("RGB")
    osz = im.size
    im.thumbnail((cw - 8, ch - 8))
    x = (i % cols) * cw + (cw - im.width) // 2
    y = (i // cols) * (ch + label_h) + label_h + (ch - label_h - im.height) // 2
    sheet.paste(im, (x, y))
    d.text(((i % cols) * cw + 6, (i // cols) * (ch + label_h) + 4),
           "%s  %dx%d" % (name, osz[0], osz[1]), fill=(40, 40, 45), font=fnt(15))

path = os.path.join(ROOT, out)
sheet.save(path, quality=88)
print("->", path, "%dx%d  %d 页" % (sheet.width, sheet.height, len(files)))
