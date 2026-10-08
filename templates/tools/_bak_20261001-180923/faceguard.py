# -*- coding: utf-8 -*-
"""
faceguard.py —— 遮挡审计复核图

读 _shots/_labels.json（由 tools/labelrects.js 产出），在精确渲染的整页截图上
把「照片区」与「浮层标签」逐块画框，输出 _shots/guard/pageNN.png 与 3×3 总览。

设计意图：不要用肉眼在原始截图上"找"遮挡——人眼会漏。
把每一块的真实矩形画出来，遮挡一眼可见，且每个框都有编号可回到 JSON 核对。

用法：
  python tools/faceguard.py            # 全部页面
  python tools/faceguard.py page02     # 指定页
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
OUT = os.path.join(SHOTS, "guard")
os.makedirs(OUT, exist_ok=True)

# 颜色按「是否会挡住脸」的严重度排序
COLOR = {
    "bubble": (230, 30, 30),      # 解说气泡 —— 最常压脸
    "avatar": (200, 0, 150),      # 顾问头像（本身就是脸）
    "panel":  (20, 150, 60),      # 面板
    "step":   (0, 150, 160),      # 步骤格
    "tag":    (150, 80, 220),     # 字母标签
    "stamp":  (170, 0, 0),        # 印章
    "text":   (240, 140, 0),      # 普通文字块
    "photo-block": (90, 90, 90),
}
PHOTO = (30, 90, 240)


def font(size=15):
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_page(name, data):
    src = os.path.join(SHOTS, name + ".png")
    if not os.path.exists(src):
        return None
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    f = font(15)
    fsm = font(12)

    for p in data.get("photos", []):
        d.rectangle([p["x"], p["y"], p["x"] + p["w"], p["y"] + p["h"]], outline=PHOTO, width=3)
        d.text((p["x"] + 5, p["y"] + 5), "PHOTO " + p["src"], fill=PHOTO, font=fsm)

    for i, L in enumerate(data.get("labels", [])):
        c = COLOR.get(L["kind"], (120, 120, 120))
        d.rectangle([L["x"], L["y"], L["x"] + L["w"], L["y"] + L["h"]], outline=c, width=3)
        d.text((L["x"] + 4, max(0, L["y"] - 16)), "[%d]%s" % (i, L["kind"]), fill=c, font=fsm)

    d.text((8, 8), name, fill=(0, 0, 0), font=f)
    dst = os.path.join(OUT, name + ".png")
    im.save(dst)
    return im


def main():
    argv = [a for a in sys.argv[1:] if a.startswith("page")]
    with open(os.path.join(SHOTS, "_labels.json"), encoding="utf-8") as fp:
        labels = json.load(fp)
    keys = argv or sorted(labels.keys())

    ims = []
    for k in keys:
        im = draw_page(k, labels[k])
        if im is not None:
            ims.append((k, im))
            print("guard ->", k)

    if not argv and ims:
        cw, ch = 470, 601
        sheet = Image.new("RGB", (cw * 3, ch * 3), (222, 219, 215))
        for i, (k, im) in enumerate(ims):
            t = im.copy()
            t.thumbnail((cw - 10, ch - 10))
            sheet.paste(t, ((i % 3) * cw + (cw - t.width) // 2,
                            (i // 3) * ch + (ch - t.height) // 2))
        sheet.save(os.path.join(OUT, "_grid.jpg"), quality=92)
        print("grid ->", os.path.join(OUT, "_grid.jpg"))


if __name__ == "__main__":
    main()
