# -*- coding: utf-8 -*-
"""
overlap.py —— 遮挡审计：把所有「标签 ∩ 照片」的重叠区裁出来拼成一张复核图

做法：读 _shots/_labels.json，算出每个浮层标签与每个照片矩形的交集。
      交集面积超过阈值（默认 2000px²）的，从 _shots/guard/pageNN.png 上
      以 1:1 裁出「标签四周 + 交叠区」，拼成一张长图。
      这样「哪一块压在哪里」是可以量出来、并且能一眼看清楚的，不靠感觉。

用法：python tools/overlap.py [--min 2000]
输出：_shots/guard/_overlap.jpg
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
GUARD = os.path.join(SHOTS, "guard")

# 只有这些类别会「压脸」；step/panel 是版面主体，另行判断
HOT = {"bubble", "avatar", "text", "tag", "stamp", "photo-block"}


def load_font(size=16):
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def inter(a, b):
    x0 = max(a["x"], b["x"]); y0 = max(a["y"], b["y"])
    x1 = min(a["x"] + a["w"], b["x"] + b["w"]); y1 = min(a["y"] + a["h"], b["y"] + b["h"])
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "area": (x1 - x0) * (y1 - y0)}


def main():
    mn = 2000
    if "--min" in sys.argv:
        mn = int(sys.argv[sys.argv.index("--min") + 1])

    with open(os.path.join(SHOTS, "_labels.json"), encoding="utf-8") as fp:
        data = json.load(fp)

    tiles = []
    report = []
    for name in sorted(data):
        d = data[name]
        photos = d.get("photos", [])
        for i, L in enumerate(d.get("labels", [])):
            if L["kind"] not in HOT:
                continue
            best = None
            for p in photos:
                it = inter(L, p)
                if it and (best is None or it["area"] > best[1]["area"]):
                    best = (p, it)
            if not best or best[1]["area"] < mn:
                continue
            p, it = best
            report.append((name, i, L, p, it))
            src = os.path.join(GUARD, name + ".png")
            if not os.path.exists(src):
                continue
            im = Image.open(src).convert("RGB")
            pad = 150
            x0 = max(0, min(L["x"], it["x"]) - pad); y0 = max(0, min(L["y"], it["y"]) - pad)
            x1 = min(im.width, max(L["x"] + L["w"], it["x"] + it["w"]) + pad)
            y1 = min(im.height, max(L["y"] + L["h"], it["y"] + it["h"]) + pad)
            crop = im.crop((x0, y0, x1, y1))
            # 标出交叠区在裁剪图里的位置
            dd = ImageDraw.Draw(crop)
            dd.rectangle([it["x"] - x0, it["y"] - y0, it["x"] + it["w"] - x0, it["y"] + it["h"] - y0],
                         outline=(255, 0, 255), width=3)
            dd.text((6, 6), "%s [%d]%s  x%d y%d  overlap %dx%d=%d" %
                    (name, i, L["kind"], L["x"], L["y"], it["w"], it["h"], it["area"]),
                    fill=(255, 0, 255), font=load_font(15))
            tiles.append(crop)

    if not tiles:
        print("无重叠（阈值 %d）" % mn)
        return
    W = max(t.width for t in tiles)
    H = sum(t.height + 14 for t in tiles)
    sheet = Image.new("RGB", (W, H), (30, 30, 30))
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y)); y += t.height + 14
    out = os.path.join(GUARD, "_overlap.jpg")
    sheet.save(out, quality=90)
    print("重叠清单（%d 处，阈值 %d）：" % (len(report), mn))
    for name, i, L, p, it in report:
        print("  %s [%d]%-8s x%-5d y%-5d w%-4d h%-4d  ∩ %-16s 交叠 %dx%d = %d"
              % (name, i, L["kind"], L["x"], L["y"], L["w"], L["h"], p["src"],
                 it["w"], it["h"], it["area"]))
    print("->", out)


if __name__ == "__main__":
    main()
