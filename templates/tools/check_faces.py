# -*- coding: utf-8 -*-
"""
check_faces.py —— 人脸遮挡检查（需求 A「不要让任何标签遮挡模特人脸」的可复跑判据）

规则：
  浮层标签的**着色形状**，不得与「眼・鼻・口」禁区相交。
  禁区表见 tools/faces.json（人工用 tools/probe.py 带尺裁切标定，标定只做一次）。
  两层判定：
    FAIL  与禁区相交面积 > min_area（默认 300px²）        ← 真的盖住了五官，必须改
    WARN  与禁区外扩 pad（默认 40px）的缓冲区相交 > min_area  ← 贴脸了，人工看一眼

  退出码只由 FAIL 决定；WARN 是提示，除非 --strict。

为什么不能用肉眼：人眼在整页图上"找"遮挡会漏，且每次出图都要重看。
这里把「标签形状」与「五官矩形」都变成数字，相交面积一算就知道，
并且会把禁区画到 1:1 渲染图上，输出 _shots/guard/_faces.jpg 供人工确认标定是否还对。

为什么圆按椭圆算：.stamp 是 border-radius:50% + rotate(-8deg)。
  getBoundingClientRect() 给的是外接方框（199×199），但真正着色的是内切圆（176×176）。
  按方框算会把 45% 的"没有像素的地方"算成交叠，page04 因此一度假报 19701px²。
  所以 labelrects.js 会输出 rnd 标记，这里对内切椭圆做亚采样求交。

数据来源：_shots/_labels.json（tools/labelrects.js 产出，含每块标签的 kind / 矩形 / rnd）。

用法：
  python tools/check_faces.py            # 全部页 + 核对图
  python tools/check_faces.py page08     # 指定页
  python tools/check_faces.py --strict   # WARN 也算失败
  python tools/check_faces.py --detail   # 每页列出全部命中（默认只列前 8 条）
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
GUARD = os.path.join(SHOTS, "guard")
os.makedirs(GUARD, exist_ok=True)

# 这些 kind 才算「浮层标签」；photo-block 是照片本身（例如顾问头像），
# 它压到脸是版面安排，不是文案造成的，不在这里判。
LABEL_KINDS = {"bubble", "avatar", "panel", "step", "tag", "stamp", "text"}
PAGES = ["page%02d" % i for i in range(1, 10)]

# 底图占画布超过这个比例，就认为「本页大概率有主体」，此时禁区为空 = 判据空转
BIG_PHOTO_FRAC = 0.25


def big_photo(k, L):
    """该页是否有「大底图」（≥25% 画布）。有 → 禁区不该为空。
    ★坐标一律走 _lay.load_zone_pages（读 build 期折算过 parent 的 _resolved.json）；
      直读 layout 原文时，带 parent 的底图会算成「相对父框」的小框，判据就哑了。"""
    try:
        import _lay
    except Exception:
        return False
    zones = (_lay.load_zone_pages(ROOT).get(k) or {}).get("zones", [])
    for z in zones:
        b = z.get("box")
        if not b or z.get("kind", "text") != "image" or not z.get("src"):
            continue
        if b[2] * b[3] >= BIG_PHOTO_FRAC:
            return True
    return False


def font(size):
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def overlap(l, z, step=2.0):
    """标签的着色形状与禁区的交叠面积。

    矩形标签 = 矩形交；rnd 标签（border-radius:50%）= 内切椭圆与矩形的交（2px 亚采样）。
    椭圆的横纵径取 l['rw']/l['rh']（元素未旋转的布局尺寸），而不是 l['w']/l['h'] ——
    后者是 getBoundingClientRect() 的外接方框，对旋转过的圆会虚胖 45%。
    先做方框粗判，不相交直接返回 0 —— 绝大多数组合走这条快路。
    """
    ix0 = max(l["x"], z["x"]); iy0 = max(l["y"], z["y"])
    ix1 = min(l["x"] + l["w"], z["x"] + z["w"]); iy1 = min(l["y"] + l["h"], z["y"] + z["h"])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    if not l.get("rnd"):
        return float((ix1 - ix0) * (iy1 - iy0))
    cx = l["x"] + l["w"] / 2.0; cy = l["y"] + l["h"] / 2.0
    rx = (l.get("rw") or l["w"]) / 2.0
    ry = (l.get("rh") or l["h"]) / 2.0
    # 采样范围 = 椭圆外接框 ∩ 禁区
    sx0 = max(ix0, cx - rx); sx1 = min(ix1, cx + rx)
    sy0 = max(iy0, cy - ry); sy1 = min(iy1, cy + ry)
    if sx1 <= sx0 or sy1 <= sy0:
        return 0.0
    n = 0
    y = sy0 + step / 2.0
    while y < sy1:
        x = sx0 + step / 2.0
        while x < sx1:
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                n += 1
            x += step
        y += step
    return n * step * step


def grow(r, pad):
    return {"x": r["x"] - pad, "y": r["y"] - pad, "w": r["w"] + 2 * pad, "h": r["h"] + 2 * pad}


def main():
    argv = sys.argv[1:]
    strict = "--strict" in argv
    detail = "--detail" in argv
    import _cli
    # ★用 _cli.positionals()：argv 里混着选项的值，直接筛 "page" 前缀会被污染
    only = [a for a in _cli.positionals() if a.startswith("page")]

    with open(os.path.join(ROOT, "tools", "faces.json"), encoding="utf-8") as fp:
        F = json.load(fp)
    lpath = os.path.join(SHOTS, "_labels.json")
    if not os.path.exists(lpath):
        print("!! 缺少 %s —— 先跑：node tools/labelrects.js" % lpath)
        sys.exit(2)
    with open(lpath, encoding="utf-8") as fp:
        L = json.load(fp)

    pad, minA = F.get("pad", 40), F.get("min_area", 300)
    keys = only or [p for p in PAGES if p in L]
    rows, nfail, nwarn = [], 0, 0

    for k in keys:
        zones = [z for z in F["pages"].get(k, []) if z["w"] > 0 and z["h"] > 0]
        labels = [l for l in L[k].get("labels", []) if l.get("kind") in LABEL_KINDS]
        # ★ 空转检测：页面有大底图却没标五官禁区 → 判据其实什么都没查，不许静默变绿
        vac = (not zones) and big_photo(k, L)
        hits = []
        for z in zones:
            for l in labels:
                a = overlap(l, z)
                if a > minA:
                    hits.append(("FAIL", z["name"], l, a, a))
                else:
                    b = overlap(l, grow(z, pad))
                    if b > minA:
                        hits.append(("WARN", z["name"], l, b, a))
        if vac:
            hits.append(("VACUUM", "五官禁区未标定", None, 0, 0))
        hits.sort(key=lambda t: -t[3])
        fails = [h for h in hits if h[0] == "FAIL"]
        warns = [h for h in hits if h[0] in ("WARN", "VACUUM")]
        nfail += len(fails)
        nwarn += len(warns)
        flag = "FAIL" if fails else ("WARN" if warns else " OK ")
        print("%s  %s  禁区 %d 块 / 标签 %d 块   FAIL %d  WARN %d%s"
              % (flag, k, len(zones), len(labels), len(fails), len(warns),
                 "   ← 禁区未标定，本判据空转（不是通过）" if vac else ""))
        for lv, zn, l, area, raw in (hits if detail else hits[:6]):
            if l is None:
                print("        %-6s %s  ←该页底图占画布 ≥25%% 却没有模特，或者忘了标："
                      "跑 grid.py/probe.py 标定后填 tools/faces.json" % (lv, zn))
                continue
            print("        %-4s %s  ←标签[%s] x%d y%d %dx%d  相交 %dpx²%s"
                  % (lv, zn, l.get("kind"), l["x"], l["y"], l["w"], l["h"], int(area),
                     "  (圆按内切椭圆)" if l.get("rnd") else ""))
        rows.append((k, zones, labels))

    # 核对图：把禁区（红=Fail 判定区、橙=WARN 缓冲）画到 1:1 渲染图上
    CW, CH = 455, 582
    sheet = Image.new("RGB", (CW * 3, CH * 3), (225, 222, 218))
    for i, (k, zones, labels) in enumerate(rows):
        src = os.path.join(SHOTS, k + ".png")
        if not os.path.exists(src):
            continue
        im = Image.open(src).convert("RGB")
        d = ImageDraw.Draw(im)
        f = font(22)
        for z in zones:
            zb = grow(z, pad)
            d.rectangle([zb["x"], zb["y"], zb["x"] + zb["w"], zb["y"] + zb["h"]],
                        outline=(240, 150, 0), width=3)
            d.rectangle([z["x"], z["y"], z["x"] + z["w"], z["y"] + z["h"]], outline=(230, 20, 20), width=4)
            d.text((z["x"] + 6, z["y"] + 6), z["name"], fill=(230, 20, 20), font=f)
        for l in labels:
            if l.get("rnd"):
                cx = l["x"] + l["w"] / 2.0; cy = l["y"] + l["h"] / 2.0
                rx = (l.get("rw") or l["w"]) / 2.0
                ry = (l.get("rh") or l["h"]) / 2.0
                d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=(20, 90, 230), width=3)
            else:
                d.rectangle([l["x"], l["y"], l["x"] + l["w"], l["y"] + l["h"]],
                            outline=(20, 90, 230), width=3)
        im.save(os.path.join(GUARD, k + "_faces.png"))
        t = im.copy()
        t.thumbnail((CW - 10, CH - 10))
        sheet.paste(t, ((i % 3) * CW + (CW - t.width) // 2, (i // 3) * CH + (CH - t.height) // 2))

    out = os.path.join(GUARD, "_faces.jpg")
    sheet.save(out, quality=90)
    print("\n核对图 -> %s（红框=禁区，橙框=WARN 缓冲，蓝框=浮层标签）" % out)
    print("合计：FAIL %d  WARN %d" % (nfail, nwarn))
    bad = nfail + (nwarn if strict else 0)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
