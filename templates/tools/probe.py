# -*- coding: utf-8 -*-
"""
probe.py —— 带坐标尺的局部放大裁切，用于人工标定 / 复核 faces.json 的禁区框

为什么需要它：
  整页 1366×1748 缩进屏幕只剩几百像素，读不出「眼睛到底在哪一行」。
  把争议区域裁出来、叠上 50px 坐标尺、再把禁区框（红）/ 外扩缓冲（橙）/
  实际浮层标签框（蓝）画上去，标定准不准就变成可读的数字，而不是印象。

坐标尺约定：所有标注都用「画布原始坐标」（1366×1748），不随 --zoom 变。
  这样从图上读到的数字可以直接抄进 faces.json。

用法：
  python tools/probe.py page04:400,540,860,900
  python tools/probe.py page04:400,540,860,900 --zoom 1.6
  python tools/probe.py page06:20,20,520,340 --no-zones      # 只看照片，不看框
  python tools/probe.py page04:0,0 --full                   # 整页 + 尺（等同 grid.py）

参数：
  pageNN:x,y,w,h   裁切区域（w/h 可省略 = 到画布右/下边）
  --zoom N         像素放大倍数（默认 1.0，即 1:1）
  --out NAME       输出文件名（追加序号，默认 _probe）
  --no-zones       不画禁区框
  --no-labels      不画浮层标签框
  --grid N         坐标尺间距（默认 50）

输出：_shots/guard/_probe*.jpg（多区域自动纵向拼接成一张）
"""
import json, os, re, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
GUARD = os.path.join(SHOTS, "guard")
os.makedirs(GUARD, exist_ok=True)

argv = sys.argv[1:]
specs = [a for a in argv if re.match(r"^page\d+:", a) or re.match(r"^page\d+$", a)]
zoom = float(argv[argv.index("--zoom") + 1]) if "--zoom" in argv else 1.0
grid = int(argv[argv.index("--grid") + 1]) if "--grid" in argv else 50
out_name = argv[argv.index("--out") + 1] if "--out" in argv else "_probe"
show_zones = "--no-zones" not in argv
show_labels = "--no-labels" not in argv
title_h = 26
pad_gap = 12


def fnt(s):
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, s)
            except Exception:
                pass
    return ImageFont.load_default()


def load_json(p, default):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


FACES = load_json(os.path.join(ROOT, "tools", "faces.json"), {"pages": {}, "pad": 40})
LABELS = load_json(os.path.join(SHOTS, "_labels.json"), {})


def parse(spec, W, H):
    if ":" not in spec:
        return spec, 0, 0, W, H, "%s (full)" % spec
    page, box = spec.split(":", 1)
    v = [int(t) for t in box.split(",") if t.strip()]
    while len(v) < 4:
        v.append(None)
    x, y = v[0] or 0, v[1] or 0
    w = v[2] if v[2] else W - x
    h = v[3] if v[3] else H - y
    return page, x, y, w, h, "%s  x%d y%d %dx%d  @%gx" % (page, x, y, w, h, zoom)


def crop(page, x, y, w, h, label):
    src = os.path.join(SHOTS, page + ".png")
    im = Image.open(src).convert("RGB")
    tile = im.crop((x, y, x + w, y + h))
    if zoom != 1.0:
        tile = tile.resize((int(tile.width * zoom), int(tile.height * zoom)), Image.LANCZOS)
    d = ImageDraw.Draw(tile)
    f = fnt(max(11, int(13 * min(zoom, 2))))
    fb = fnt(max(13, int(16 * min(zoom, 2))))

    step = max(1, int(grid * zoom))
    for gx in range((x // grid) * grid, x + w + 1, grid):
        px = (gx - x) * zoom
        if px < 0:
            continue
        d.line([(px, 0), (px, tile.height)], fill=(0, 200, 90), width=1)
        d.text((px + 2, 1), str(gx), fill=(0, 120, 40), font=f)
    for gy in range((y // grid) * grid, y + h + 1, grid):
        py = (gy - y) * zoom
        if py < 0:
            continue
        d.line([(0, py), (tile.width, py)], fill=(0, 200, 90), width=1)
        d.text((2, py + 2), str(gy), fill=(0, 120, 40), font=f)

    def rect(r, color, width=3, text=None):
        x0 = (r["x"] - x) * zoom
        y0 = (r["y"] - y) * zoom
        x1 = (r["x"] + r["w"] - x) * zoom
        y1 = (r["y"] + r["h"] - y) * zoom
        if x1 < 0 or y1 < 0 or x0 > tile.width or y0 > tile.height:
            return
        d.rectangle([x0, y0, x1, y1], outline=color, width=width)
        if text:
            d.text((x0 + 4, y0 + 3), text, fill=color, font=f)

    zones = [z for z in FACES["pages"].get(page, []) if z["w"] > 0 and z["h"] > 0]
    if show_zones:
        for z in zones:
            pd = FACES.get("pad", 40)
            rect({"x": z["x"] - pd, "y": z["y"] - pd, "w": z["w"] + 2 * pd, "h": z["h"] + 2 * pd},
                 (240, 150, 0), 2)
            rect(z, (230, 20, 20), 3, z["name"])
    if show_labels:
        for l in LABELS.get(page, {}).get("labels", []):
            rect(l, (20, 90, 230), 2, l.get("kind"))

    band = Image.new("RGB", (tile.width, title_h), (25, 25, 28))
    ImageDraw.Draw(band).text((6, 5), label, fill=(255, 235, 120), font=fb)
    out = Image.new("RGB", (tile.width, tile.height + title_h), (25, 25, 28))
    out.paste(band, (0, 0))
    out.paste(tile, (0, title_h))
    return out


def main():
    targets = specs or ["page01", "page02", "page03", "page04", "page05",
                        "page06", "page07", "page08", "page09"]
    tiles = []
    for s in targets:
        pg = s.split(":")[0]
        src = os.path.join(SHOTS, pg + ".png")
        if not os.path.exists(src):
            print("!! 缺图:", src)
            continue
        with Image.open(src) as t:
            W, H = t.size
        page, x, y, w, h, label = parse(s, W, H)
        x = max(0, x); y = max(0, y)
        w = min(w, W - x); h = min(h, H - y)
        tiles.append(crop(page, x, y, w, h, label))
    if not tiles:
        print("没有可裁的区域")
        return
    tw = max(t.width for t in tiles)
    th = sum(t.height for t in tiles) + pad_gap * (len(tiles) - 1)
    sheet = Image.new("RGB", (tw, th), (12, 12, 14))
    cy = 0
    for t in tiles:
        sheet.paste(t, (0, cy))
        cy += t.height + pad_gap
    # ★扩展名判断：原先写的是 `out_name if ext else out_name + ".jpg"` ——
    #   `ext` 恒为真（有兜底 ".jpg"），于是永远走第一支 → 默认名 `_probe` 不带扩展名
    #   → `sheet.save()` 抛 `ValueError: unknown file extension:`，**默认用法必崩**。
    #   判据必须写成「原文件名**本身**有没有扩展名」。
    ext = os.path.splitext(out_name)[1]
    path = os.path.join(GUARD, out_name if ext else out_name + ".jpg")
    sheet.save(path, quality=92)
    print("->", path, "%dx%d" % sheet.size)


if __name__ == "__main__":
    main()
