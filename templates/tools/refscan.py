# -*- coding: utf-8 -*-
"""
refscan.py —— 参考图投影分析：自动候选「分带切分点」与「带内分栏位置」

为什么需要它（这是本引擎过去最大的缺口）：
    过去 layout JSON 的 box 全靠「人肉看参考图估读」，而文档里点名的 grid.py /
    probe.py 只能作用于「已渲染的 _shots/pageNN.png」——**没有任何工具真的读过参考图**。
    于是「按参考图复刻」成了一句口号。

它做什么：
    对**参考图本身**做行 / 列边缘投影，找出「静默谷」（内容稀疏的水平缝隙），
    自动给出候选的：
      · bandCuts  —— 页面被横向切成几条带的切分点（百分比）
      · bands[i].colCuts —— 每条带内部再切列的候选分栏线（百分比）
    并画出可视化分析图，供人 / agent 核对候选对不对。

它的定位是「给起点」，不是「替代判断」：
    输出的 conf 只是「这条缝有多安静」的粗略可信度。
    **最终 box 由 agent 按候选写出，并在 HTML 里按 O 三态叠图验收。**

用法：
    python tools/refscan.py                     # 扫 assets/ref/ 下全部参考图
    python tools/refscan.py --ref p01.jpg       # 只扫一张
    python tools/refscan.py --thresh 0.35 --min-gap 0.02 --ds 900
输出：
    assets/ref/_scan/<name>.json       候选切分点（bands / bandCuts / columns / size）
    assets/ref/_scan/<name>.bands.png  原图 + 候选线叠加（可视化核对）
    assets/ref/_scan/<name>.profile.png 行 / 列投影曲线（看阈值取得对不对）
退出码：
    0 成功    2 缺 Pillow / 找不到参考图 / 读图失败
    3 所有图都过小（长边 < 200px）无法分析

依赖：只用 Pillow（不联网，不依赖 OpenCV / numpy）。
"""
import os
import sys
import json

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
except ImportError:
    print("FAIL 缺 Pillow —— 请先 pip install pillow")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "assets", "ref")
OUT = os.path.join(REF, "_scan")
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
BOX = getattr(Image, "Resampling", Image).BOX
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

MIN_EDGE = 200          # 长边小于这个值就没法分析
DEGENERATE = 1.0        # 行投影峰值低于这个值 = 近乎全白


def argval(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def fnt(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def list_refs(only=None):
    if not os.path.isdir(REF):
        return []
    out = []
    for f in sorted(os.listdir(REF)):
        p = os.path.join(REF, f)
        if os.path.isdir(p):
            continue
        if f.startswith("_") or f.startswith("."):
            continue
        if not f.lower().endswith(EXTS):
            continue
        if only and f != only:
            continue
        out.append(f)
    return out


def smooth(a, win):
    """一维滑动平均（用前缀和，O(n)）。"""
    n = len(a)
    if win < 2 or n < 3:
        return list(a)
    half = max(1, win // 2)
    ps = [0.0] * (n + 1)
    for i, v in enumerate(a):
        ps[i + 1] = ps[i] + v
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = (ps[hi] - ps[lo]) / (hi - lo)
    return out


def row_profile(gray):
    """逐行的水平边缘强度均值（越小 = 这一行越安静）。用一次像素位移 + 差分，纯 Pillow。"""
    W, H = gray.size
    if W < 3:
        return [0.0] * H
    a = gray.crop((1, 0, W, H))
    b = gray.crop((0, 0, W - 1, H))
    d = ImageChops.difference(a, b)
    return [float(v) for v in d.resize((1, H), BOX).tobytes()]


def band_col_profile(gray, y0, y1):
    """某条带内部的逐列垂直边缘强度均值。"""
    W, H = gray.size
    y0 = max(0, min(H - 1, int(round(y0))))
    y1 = max(0, min(H, int(round(y1))))
    if W < 3 or (y1 - y0) < 6:
        return []
    a = gray.crop((1, y0, W, y1))
    b = gray.crop((0, y0, W - 1, y1))
    d = ImageChops.difference(a, b)
    return [float(v) for v in d.resize((W - 1, 1), BOX).tobytes()]


def find_valleys(prof, thresh, min_gap_frac, lo_frac=0.0, hi_frac=1.0):
    """在投影曲线上找「静默谷」：连续低于阈值的区段，取其中心为候选切分点。

    返回 [(位置比例, conf)]，位置以 0–1 表示（相对整幅）。
    conf = 1 - 谷底 / 中位数，越接近 1 越安静。
    """
    n = len(prof)
    if n < 8:
        return []
    med = sorted(prof)[n // 2]
    if med <= 0.5:
        return []
    low = med * thresh
    minlen = max(2, int(min_gap_frac * n))
    cuts = []
    i = 0
    while i < n:
        if prof[i] < low:
            j = i
            while j < n and prof[j] < low:
                j += 1
            if (j - i) >= minlen:
                mid = (i + j) // 2
                pos = mid / float(n)
                conf = 1.0 - (prof[mid] / med)
                if lo_frac < pos < hi_frac:
                    cuts.append((pos, round(max(0.0, min(1.0, conf)), 3)))
            i = j
        else:
            i += 1
    return cuts


def draw_bands(src_rgb, band_cuts, bands, path):
    im = src_rgb.copy()
    d = ImageDraw.Draw(im, "RGBA")
    W, H = im.size
    f = fnt(max(13, W // 70))
    # 横切分线（青）
    for c, conf in band_cuts:
        y = int(round(c * H))
        d.line([(0, y), (W, y)], fill=(0, 190, 255, 235), width=3)
        d.rectangle([0, max(0, y - 24), 150, y], fill=(0, 190, 255, 210))
        d.text((8, max(2, y - 22)), "%.1f%%  c=%.2f" % (c * 100, conf), fill=(0, 0, 0, 255), font=f)
    # 带内分栏线（洋红）
    for b in bands:
        y0, y1 = int(round(b["y0"] * H)), int(round(b["y1"] * H))
        for it in b.get("colCuts", []):
            x = int(round(float(it["x"]) * W))
            d.line([(x, y0), (x, y1)], fill=(255, 0, 160, 225), width=2)
    im.save(path)
    return path


def draw_profile(rowp, colp, path, thresh):
    W, PH = 960, 240
    im = Image.new("RGB", (W, PH * 2 + 56), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = fnt(15)
    for k, (prof, title) in enumerate(([rowp, "row projection (horizontal bands)"],
                                       [colp, "column projection (columns)"])):
        top = 28 + k * (PH + 28)
        d.text((10, top - 20), title, fill=(60, 60, 60), font=f)
        d.rectangle([0, top, W - 1, top + PH], outline=(210, 210, 210))
        if not prof:
            continue
        mx = max(prof) or 1.0
        med = sorted(prof)[len(prof) // 2]
        thr = med * thresh
        yt = int(top + PH - min(1.0, thr / mx) * PH)
        d.line([(0, yt), (W, yt)], fill=(255, 0, 160), width=1)
        n = len(prof)
        pts = []
        for i, v in enumerate(prof):
            x = int(i * (W - 1) / max(1, n - 1))
            y = int(top + PH - min(1.0, v / mx) * PH)
            pts.append((x, y))
        d.line(pts, fill=(0, 90, 170), width=1)
    im.save(path)
    return path


def analyze(name, thresh, min_gap, ds):
    path = os.path.join(REF, name)
    try:
        src = Image.open(path)
        src.load()
    except Exception as e:
        return {"image": name, "error": "读取失败：%s" % e}, "read-error"
    W0, H0 = src.size
    if max(W0, H0) < MIN_EDGE:
        return {"image": name, "size": [W0, H0], "error": "长边 %d < %d，太小" % (max(W0, H0), MIN_EDGE)}, "too-small"

    rgb = src.convert("RGB")
    gray = rgb.convert("L")
    scale = 1.0
    if max(W0, H0) > ds:
        scale = ds / float(max(W0, H0))
    if scale < 1.0:
        small = gray.resize((max(3, int(W0 * scale)), max(3, int(H0 * scale))), LANCZOS)
    else:
        small = gray
    W, H = small.size

    hist = small.histogram()
    paper = max(range(128, 256), key=lambda k: hist[k])

    rowp_raw = row_profile(small)
    win = max(3, (int(0.006 * H) | 1))
    rowp = smooth(rowp_raw, win)

    degenerate = (max(rowp) if rowp else 0.0) < DEGENERATE
    band_cuts = []
    if not degenerate:
        band_cuts = find_valleys(rowp, thresh, min_gap, lo_frac=0.02, hi_frac=0.98)

    # 切分点去重（间距太近的合并）
    merged = []
    for c, conf in band_cuts:
        if merged and (c - merged[-1][0]) < min_gap * 1.5:
            if conf > merged[-1][1]:
                merged[-1] = (c, conf)
        else:
            merged.append((c, conf))
    band_cuts = merged

    bounds = [0.0] + [c for c, _ in band_cuts] + [1.0]
    bands = []
    for i in range(len(bounds) - 1):
        y0, y1 = bounds[i], bounds[i + 1]
        colp = band_col_profile(small, y0 * H, y1 * H)
        colwin = max(3, (int(0.006 * W) | 1))
        colp_s = smooth(colp, colwin) if colp else []
        cuts = find_valleys(colp_s, thresh, min_gap, lo_frac=0.01, hi_frac=0.99) if colp_s else []
        mid = (y0 + y1) / 2.0
        conf = 1.0
        idx = min(len(rowp) - 1, max(0, int(mid * H)))
        if rowp and rowp[idx] > 0:
            med = sorted(rowp)[len(rowp) // 2] or 1.0
            conf = round(max(0.0, min(1.0, 1.0 - rowp[idx] / med)), 3)
        bands.append({
            "i": i,
            "y0": round(y0, 4),
            "y1": round(y1, 4),
            "conf": conf,
            "colCuts": [{"x": c, "conf": cf} for c, cf in cuts],
        })

    os.makedirs(OUT, exist_ok=True)
    try:
        draw_bands(rgb, band_cuts, bands, os.path.join(OUT, name + ".bands.png"))
    except Exception as e:
        print("WARN 画 bands.png 失败：%s" % e)
    try:
        draw_profile(rowp, smooth(band_col_profile(small, 0, H), max(3, int(0.006 * W) | 1)),
                     os.path.join(OUT, name + ".profile.png"), thresh)
    except Exception as e:
        print("WARN 画 profile.png 失败：%s" % e)

    doc = ("候选仅供起手。bandCuts = 候选横向切分点，bands[].colCuts = 带内候选分栏线；"
           "conf 只是「这条缝有多安静」的粗略可信度。最终 box 由 agent 按候选写出，"
           "并在 pageNN.html 里按 O 三态叠图验收。")
    result = {
        "_doc": doc,
        "image": name,
        "size": [W0, H0],
        "analyzed": [W, H],
        "paperGray": paper,
        "degenerate": degenerate,
        "bandCuts": [{"y": c, "conf": cf} for c, cf in band_cuts],
        "bands": bands,
    }
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=1)
    return result, "ok"


def main():
    only = argval("--ref")
    thresh = float(argval("--thresh", "0.35"))
    min_gap = float(argval("--min-gap", "0.02"))
    ds = int(argval("--ds", "900"))

    refs = list_refs(only)
    if not refs:
        print("FAIL 未找到参考图：%s 下没有图片（Stage A 必须先放参考图）"
              % os.path.join("assets", "ref").replace("\\", "/"))
        sys.exit(2)

    ok = 0
    hard = 0
    for name in refs:
        res, status = analyze(name, thresh, min_gap, ds)
        if status == "ok":
            ok += 1
            bc = res["bandCuts"]
            print("%-24s %dx%d  候选切分点 %d 条  带 %d" %
                  (name, res["size"][0], res["size"][1], len(bc), len(res["bands"])))
            for c in bc:
                print("    y=%.1f%%  conf=%.2f" % (c["y"] * 100, c["conf"]))
            for b in res["bands"]:
                cols = [x["x"] for x in b["colCuts"]]
                if cols:
                    print("    band%d %.1f%%-%.1f%%  分栏 %s" % (
                        b["i"], b["y0"] * 100, b["y1"] * 100,
                        " ".join("%.1f%%" % (x * 100) for x in cols)))
            if res["degenerate"]:
                print("    WARN 图像近乎全白，无法分段：%s（已置 degenerate，请人工兜底）" % name)
        elif status == "too-small":
            hard += 1
            print("FAIL %s：%s" % (name, res.get("error")))
        else:
            print("FAIL %s：%s" % (name, res.get("error")))

    print("-> assets/ref/_scan/  (%d 张成功)" % ok)
    if ok == 0 and hard:
        sys.exit(3)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
