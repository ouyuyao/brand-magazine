# -*- coding: utf-8 -*-
"""
reffit.py —— 骨架吻合分（告警级判据：只提示，不阻断出图）

它回答一个问题：**成品页的分区骨架，到底和参考图对得上有多少？**

三项分量（都打印出来，便于定位问题）：

  ① 计划吻合 lineLayout（权重 .35）
     把参考图跑一遍行 / 列边缘投影（与 refscan.py 同一套算法），得到参考图的
     「结构线」——整页内容带之间的静默缝。再取 layout 里每个 zone 的四条边
     （按边长加权）当作「你的结构线」。逐条看：参考图的每条结构线，在你的
     layout 里 ±tol（默认画布宽 1.5%）内有没有对应的一条边。
     这是最直接回答「你有没有按参考图分区」的指标。

  ② 渲染吻合 lineRender（权重 .35）
     对**成品页本身**跑同一套投影，取它自己的结构线；同样逐条检查参考图的每条
     结构线在成品里有没有对应。这一路专治「计划对了但页面没照做」——
     只测 layout JSON 是测不出渲染跑偏的（例如素材错位、整页偏移）。

  ③ 照片框吻合 photoScore（权重 .15）
     只对 image / cutout / mask / logo 这些**矩形照片**算「四边在参考图边缘上
     的可覆盖率」（±tol 内有没有边缘）。照片的框在参考图里就是真实边缘，
     所以这条对照片成立；对文字框不成立（文字框本来就落在照片的平坦区上），
     这也是上一版判据失真的原因。没有照片框时退化为结构相似度。

  ④ 分块结构相似度 blockSim（权重 .15）
     6×6 分块灰度均值 → 1 − 平均绝对差/255。内容会被换成你的产品，
     所以它只是个弱旁证，不能单独用。

为什么是告警级、不是硬断言：
    「骨架级复刻」本就允许差异（尺寸随素材自适应、文字重写、颜色跟品牌）。
    真正该硬拦的是「页数」与「canvas 尺寸」—— 那两条在 refcheck.py 里已经硬拦。
    这里给分数 + 差异位置，让人判断「是差了，还是根本没按参考图做」。

用法：
    python tools/reffit.py                 # 全部页
    python tools/reffit.py page01          # 只算某一页
    python tools/reffit.py --tol 0.02      # 覆盖容差（占画布宽的比例）
输出：
    _shots/report/skeleton.json
    _shots/report/<page>_skeleton.png     三联图：参考图 | 成品 | 参考图边缘(青) + layout 框(红)
退出码：
    0 恒（除 IO 错 → 2）。这是刻意设计：告警不阻断。

标定（怎么读数）：
    · 上限已验：把参考图本身当作成品喂进来 → render 1.00、sim 1.00（检测器自洽）。
    · ≥ 0.80 正常；0.60–0.80 看第三联定位；< 0.60 基本可以认定「没按参考图做」。
    · render / plan 低而 sim 高，是最典型的「内容换了、骨架没跟上」——
      正是本引擎过去被反馈的那个毛病。
    · **N/A：参考图是照片主导时不出分**。投影法要求页面存在「内容带之间的静默缝」；
      出血人像 / 整幅产品照占满版面的页，参考图自己就取不到几条结构线（实测 p01
      只有 1 横 2 纵），此时任何分数都是噪声 —— 判据宁可不说话，也不叫狼来了。
      判据：参考图结构线合计 < MIN_REF_LINES(3) → 记 N/A，且不计入 min/max 汇总。

依赖：只用 Pillow（结构线部分复用 tools/refscan.py）。
"""
import os
import re
import sys
import json

try:
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
except ImportError:
    print("FAIL 缺 Pillow —— 请先 pip install pillow")
    sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refscan as R  # noqa: E402  （行/列投影与寻谷算法，与解析参考图时完全同一套）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join(ROOT, "layout")
REF = os.path.join(ROOT, "assets", "ref")
SHOTS = os.path.join(ROOT, "_shots")
REPORT = os.path.join(ROOT, "_shots", "report")

BOX = getattr(Image, "Resampling", Image).BOX
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

WORK = 900            # 工作分辨率（长边）
GOOD = 0.80           # 吻合分 ≥ 此值 = OK
FAIR = 0.60           # ≥ 此值 = 尚可；低于此值 = 版式可能没按参考图解析
MIN_AREA = 0.004      # 小于画布 0.4% 的 zone 不参与结构线（太小，噪声大）
MIN_REF_LINES = 1     # 两个方向合计一条结构线都取不到 → 判据不适用（记 N/A）
WEAK_REF_LINES = 5    # 少于这么多条 → 证据弱（照出分，但不参与「连续偏低」告警）
W_PLAN, W_RENDER, W_PHOTO, W_SIM = 0.35, 0.35, 0.15, 0.15


def argval(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def fnt(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def percentile(hist, frac):
    tot = sum(hist) or 1
    acc = 0
    for k in range(256):
        acc += hist[k]
        if acc >= tot * frac:
            return k
    return 255


def edge_bin(gray):
    e = gray.filter(ImageFilter.FIND_EDGES)
    thr = max(6, percentile(e.histogram(), 0.90))
    return e.point(lambda v: 255 if v >= thr else 0)


def cover_h(eb, x0, x1, y, tol):
    W, H = eb.size
    x0 = max(0, min(W - 1, int(x0)))
    x1 = max(x0 + 1, min(W, int(x1)))
    lo = max(0, int(y) - tol)
    hi = min(H, int(y) + tol + 1)
    if hi <= lo:
        return 0.0
    col = eb.crop((x0, lo, x1, hi)).resize((x1 - x0, 1), BOX).tobytes()
    return sum(1 for v in col if v > 0) / float(x1 - x0)


def cover_v(eb, y0, y1, x, tol):
    W, H = eb.size
    y0 = max(0, min(H - 1, int(y0)))
    y1 = max(y0 + 1, min(H, int(y1)))
    lo = max(0, int(x) - tol)
    hi = min(W, int(x) + tol + 1)
    if hi <= lo:
        return 0.0
    row = eb.crop((lo, y0, hi, y1)).resize((1, y1 - y0), BOX).tobytes()
    return sum(1 for v in row if v > 0) / float(y1 - y0)


def block_sim(a_gray, b_gray, n=6):
    A = list(a_gray.resize((n, n), BOX).tobytes())
    B = list(b_gray.resize((n, n), BOX).tobytes())
    mad = sum(abs(A[i] - B[i]) for i in range(len(A))) / float(len(A))
    return round(max(0.0, 1.0 - mad / 255.0), 4)


def axis_score(ref_lines, lay_edges, tol):
    """单轴打分。该轴一条参考线都没有 → 返回 None（**不适用**），不按满分计。

    ★ 这里是个容易踩的坑：早先 line_score 对空参考线返回 1.0（"没有要求 = 全满足"），
      于是一个只有纵缝可量的页面，横轴会被白送 1.00 把总分抬起来。改为 None，
      由调用方只对**可量的轴**求平均。"""
    if not ref_lines:
        return None, []
    return line_score(ref_lines, lay_edges, tol)


def combine(vals):
    """对可量的轴求平均；全不可量 → None。"""
    vs = [v for v in vals if v is not None]
    return round(sum(vs) / len(vs), 4) if vs else None


def r4(v):
    """None 安全的 round。"""
    return round(v, 4) if isinstance(v, (int, float)) else None


def line_score(ref_lines, lay_edges, tol):
    """参考图的每条结构线，在 layout 的边集合里 ±tol 内有没有对应的。"""
    if not ref_lines:
        return 1.0, []
    N = 2000
    occ = bytearray(N)
    r = max(1, int(tol * N))
    for pos, _wt in lay_edges:
        c = int(pos * N)
        for i in range(max(0, c - r), min(N, c + r + 1)):
            occ[i] = 1
    hit, miss = 0, []
    for v in ref_lines:
        c = min(N - 1, max(0, int(v * N)))
        if occ[c]:
            hit += 1
        else:
            miss.append(round(v, 4))
    return hit / float(len(ref_lines)), miss


def schematic(L, size):
    """把 layout 画成一张区块示意图（白底 + 灰块），再用与参考图完全相同的投影算法
    取它的结构线。这样「计划」与「渲染」是同源可比的 —— 用「每个 zone 的两条边」
    当结构线会太宽松（24 个框 = 48 条边，任何一条参考缝都能被盖住，plan 恒 ≈ 1）。
    出血元素不画（它的边界本就不受约束）。"""
    wr, wh = size
    im = Image.new("L", (wr, wh), 255)
    d = ImageDraw.Draw(im)
    W0, H0 = L.get("_canvas") or (wr, wh)
    sc = wr / float(W0)
    for z in (L.get("zones") or []):
        b = z.get("box")
        if not is_box(b):
            continue
        kind = z.get("kind") or "text"
        st = z.get("style") or {}
        if kind == "image" and st.get("treat") == "bleed":
            continue
        x, y, w, h = box_px(b, W0, H0)
        v = 165 if kind in ("image", "cutout", "mask", "logo") else 215
        d.rectangle([x * sc, y * sc, (x + w) * sc, (y + h) * sc], fill=v)
    return im


def lines_of(gray_like):
    """跑一遍行 / 列投影 + 寻谷，返回 (横缝列表, 纵缝列表)。"""
    wr, wh = gray_like.size
    rowp = R.smooth(R.row_profile(gray_like), max(3, (int(0.006 * wh) | 1)))
    ys = [c for c, _ in R.find_valleys(rowp, 0.35, 0.02, 0.02, 0.98)]
    colp = R.smooth(R.band_col_profile(gray_like, 0, wh), max(3, (int(0.006 * wr) | 1)))
    xs = [c for c, _ in R.find_valleys(colp, 0.35, 0.02, 0.01, 0.99)]
    return ys, xs


def lines_of_cover(gray_like, ink_thr=235, dip=0.42, min_gap_frac=0.012):
    """成品页专用的结构线：以「墨迹覆盖率曲线的下潜谷」当缝。

    为什么需要第二条路：find_valleys 用的是**相对**阈值（< 0.35 × 中位数）。
    扫描页整幅都有纸纹噪声（实测参考图 边缘中位数 5.8–6.8），边缘投影里
    「内容带 vs 空白带」的落差足够大，谷找得到；而本引擎出的是**干净的数字稿**
    （纸底 #f7f4ee 平坦、字细），整幅同处噪声地板（实测中位数 1.0–2.0），
    空白带掉不到中位数的 35% 以下 → 一条谷都找不到 → 渲染侧恒为 0.00。
    那是检测器看不见，不是版式没对上。所以这里换一个与噪声无关的度量：
    把页面二值化成「有墨 / 无墨」，看每一行 / 每一列被墨迹覆盖的比例，
    覆盖率的下潜谷就是内容带之间的空白 —— 与 gutter_lines() 同源，
    只是喂给它的是真实成品页而不是示意图。
    """
    ink = gray_like.point(lambda v: 255 if v < ink_thr else 0)
    wr, wh = ink.size
    rowcov = [v / 255.0 for v in ink.resize((1, wh), BOX).tobytes()]
    colcov = [v / 255.0 for v in ink.resize((wr, 1), BOX).tobytes()]
    return dip_lines(rowcov, dip=dip, min_gap_frac=min_gap_frac), \
        dip_lines(colcov, dip=dip, min_gap_frac=min_gap_frac)


def _runs_below(prof, min_gap_frac, rel):
    """找出「低于峰值 rel 倍」的连续区段，返回其中心位置（0–1）。"""
    n = len(prof)
    if n < 8:
        return []
    mx = max(prof) or 0.0
    if mx <= 0.0:
        return []
    thr = mx * rel
    minlen = max(2, int(min_gap_frac * n))
    out = []
    i = 0
    while i < n:
        if prof[i] <= thr:
            j = i
            while j < n and prof[j] <= thr:
                j += 1
            if (j - i) >= minlen:
                out.append(((i + j) / 2.0) / n)
            i = j
        else:
            i += 1
    return out


def dip_lines(cov, win_frac=0.02, dip=0.42, min_gap_frac=0.012):
    """在**覆盖率曲线**上找「明显下潜的局部谷」= 内容带之间的缝。

    为什么不用「低于峰值的固定比例」（_runs_below）：那条要求覆盖率掉到峰值的
    18% 以下才算缝，实测太钝 —— 只要有一条细长的元素（旋转标签、署名行）横跨
    带边界，覆盖率就掉不下去，缝就整个漏掉（page05 的三个带边界 22.6/62.0/95.8
    就是这样被漏的）。改成「相对峰值下潜 dip 比例」后，只要该行明显比版面主体空
    就算缝。**多找出几条线不会误判**：line_score 是「参考图的每条线有没有被盖住」
    的召回率，多余的候选线不参与扣分。
    """
    n = len(cov)
    if n < 8:
        return []
    w = max(3, (int(win_frac * n) | 1))
    sm = R.smooth(cov, w)
    mx = max(sm) or 0.0
    if mx <= 0.0:
        return []
    thr = mx * (1.0 - dip)
    minlen = max(2, int(min_gap_frac * n))
    out = []
    i = 0
    while i < n:
        if sm[i] <= thr:
            j = i
            while j < n and sm[j] <= thr:
                j += 1
            if (j - i) >= minlen:
                k = min(range(i, j), key=lambda t: sm[t])
                out.append((k + 0.5) / n)
            i = j
        else:
            i += 1
    return out


def gutter_lines(schematic_img, min_gap_frac=0.012, dip=0.42):
    """从**区块示意图**取结构线：覆盖率曲线上的下潜谷 = 空白带。

    为什么不能对示意图用边缘投影（lines_of）：示意图是实心灰块，块内部**没有纹理**，
    边缘投影会把块内部误判成「安静区」；而且整图静默值中位数近 0，寻谷直接放弃。
    对示意正确的检测器是「这一行有多少比例被块覆盖」——下潜 = 空白带。
    """
    wr, wh = schematic_img.size
    ink = schematic_img.point(lambda v: 255 if v < 250 else 0)
    rowcov = [v / 255.0 for v in ink.resize((1, wh), BOX).tobytes()]
    colcov = [v / 255.0 for v in ink.resize((wr, 1), BOX).tobytes()]
    return dip_lines(rowcov, dip=dip, min_gap_frac=min_gap_frac), \
        dip_lines(colcov, dip=dip, min_gap_frac=min_gap_frac)


def is_box(b):
    if isinstance(b, list) and len(b) == 4:
        return all(isinstance(v, (int, float)) for v in b)
    if isinstance(b, dict):
        return all(k in b for k in ("x", "y", "w", "h"))
    return False


def box_px(b, cw, ch):
    if isinstance(b, list):
        return b[0] * cw, b[1] * ch, b[2] * cw, b[3] * ch
    return b["x"], b["y"], b["w"], b["h"]


def tri_panel(ref_rgb, shot_rgb, eb, zones, path):
    W0, H0 = ref_rgb.size
    pw = 380
    ph = max(120, int(round(pw * H0 / float(W0))))
    r = ref_rgb.resize((pw, ph), LANCZOS)
    s = shot_rgb.resize((pw, ph), LANCZOS)
    base = Image.blend(s.convert("L").convert("RGB"), Image.new("RGB", (pw, ph), (255, 255, 255)), 0.45)
    m = eb.resize((pw, ph), BOX).point(lambda v: 255 if v > 0 else 0)
    ov = Image.composite(Image.new("RGB", (pw, ph), (0, 190, 220)), base, m)
    d = ImageDraw.Draw(ov)
    for z in zones:
        b = z.get("box")
        if not is_box(b):
            continue
        x, y, w, h = b
        d.rectangle([x * pw, y * ph, (x + w) * pw, (y + h) * ph], outline=(230, 20, 20), width=1)
    gap = 12
    sheet = Image.new("RGB", (pw * 3 + gap * 2, ph + 30), (255, 255, 255))
    for i, im in enumerate((r, s, ov)):
        sheet.paste(im, (i * (pw + gap), 24))
    dd = ImageDraw.Draw(sheet)
    f = fnt(15)
    for i, t in enumerate(("参考图 reference", "成品 output", "参考图边缘(青) vs layout 框(红)")):
        dd.text((i * (pw + gap) + 6, 5), t, fill=(50, 50, 50), font=f)
    sheet.save(path)
    return path


def find_ref_file(refname):
    if not os.path.isdir(REF):
        return None
    for f in sorted(os.listdir(REF)):
        if os.path.isdir(os.path.join(REF, f)) or f.startswith("_"):
            continue
        if f == refname or os.path.splitext(f)[0] == os.path.splitext(refname)[0]:
            return os.path.join(REF, f)
    return None


def pages():
    out = []
    if not os.path.isdir(LAYOUT):
        return out
    for f in sorted(os.listdir(LAYOUT)):
        if not f.endswith(".json") or f.startswith("_"):
            continue
        try:
            d = json.load(open(os.path.join(LAYOUT, f), encoding="utf-8"))
        except Exception:
            continue
        num = re.sub(r"\D", "", str(d.get("id") or f))
        if num:
            out.append(("page" + num.zfill(2), d))
    import _cli
    # ★只取开头的连续段：否则 `--out pages/x.png` 的值以 "page" 开头，
    #   会被当成页面筛选器 → 匹配不到任何页 → 判据静默空过。
    want = _cli.positionals()
    return [p for p in out if p[0] in want] if want else out


def main():
    tol = float(argval("--tol", "0.015"))
    os.makedirs(REPORT, exist_ok=True)
    out = {"_doc": "骨架吻合分（告警级）。score = %.2f·计划吻合 + %.2f·渲染吻合 + %.2f·照片框 + %.2f·结构相似度；"
                   "≥ %.2f = OK，%.2f–%.2f = 尚可，< %.2f = 版式可能没按参考图解析。"
                   "score 为 null = 判据不适用（参考图照片主导，投影取不到结构线）。"
           % (W_PLAN, W_RENDER, W_PHOTO, W_SIM, GOOD, FAIR, GOOD, FAIR),
           "tolFrac": tol, "weights": {"plan": W_PLAN, "render": W_RENDER, "photo": W_PHOTO, "sim": W_SIM},
           "minRefLines": MIN_REF_LINES,
           "pages": {}}

    plist = pages()
    if not plist:
        print("WARN layout/ 里没有可分析的页")
        sys.exit(0)

    scores = []
    for pid, L in plist:
        refname = L.get("ref")
        if not refname:
            print("WARN %s 缺 ref 字段 —— 跳过" % pid)
            continue
        refp = find_ref_file(refname)
        if not refp:
            print("WARN %s 的参考图 %s 不在 assets/ref/ —— 跳过" % (pid, refname))
            continue
        shotp = os.path.join(SHOTS, pid + ".png")
        if not os.path.exists(shotp):
            print("WARN %s 还没有成品（先跑 node tools/shoot.js）—— 跳过" % pid)
            continue

        ref = Image.open(refp).convert("RGB")
        shot = Image.open(shotp).convert("RGB")
        if shot.size != ref.size:
            shot = shot.resize(ref.size, LANCZOS)
        W0, H0 = ref.size
        sc = WORK / float(max(W0, H0))
        wr, wh = max(8, int(W0 * sc)), max(8, int(H0 * sc))
        ref_s = ref.resize((wr, wh), LANCZOS)
        shot_s = shot.resize((wr, wh), LANCZOS)
        gray_s = ref_s.convert("L")
        shot_gray = shot_s.convert("L")
        eb = edge_bin(gray_s)
        tolpx = max(2, int(round(tol * wr)))

        # ---- 参考图结构线（与 refscan 同一套算法） ----
        ref_y, ref_x = lines_of(gray_s)

        # ---- 不适用守卫：照片主导的参考图取不到结构线，此时出分就是噪声 ----
        if len(ref_y) + len(ref_x) < MIN_REF_LINES:
            out["pages"][pid] = {
                "ref": os.path.basename(refp), "canvas": [W0, H0], "score": None,
                "na": True, "refLinesY": [round(v, 4) for v in ref_y],
                "refLinesX": [round(v, 4) for v in ref_x],
                "why": "参考图是照片主导（结构线仅 %d 条 < %d）—— 投影法不适用"
                       % (len(ref_y) + len(ref_x), MIN_REF_LINES),
            }
            try:
                tri_panel(ref, shot, eb, L.get("zones") or [],
                          os.path.join(REPORT, pid + "_skeleton.png"))
            except Exception as e:
                print("WARN 画 %s_skeleton.png 失败：%s" % (pid, e))
            print("N/A  %s 参考图是照片主导（结构线仅 %d 条）—— 投影法取不到骨架，不出分。"
                  % (pid, len(ref_y) + len(ref_x)))
            print("     这不是「没按参考图做」，而是「这张参考图量不出来」；"
                  "请看 _shots/report/%s_skeleton.png 第三联人工判断。" % pid)
            continue

        weak = (len(ref_y) + len(ref_x)) < WEAK_REF_LINES

        # ---- 成品页自己的结构线（这一路专治「计划对了但页面没照做」） ----
        out_y, out_x = lines_of(shot_gray)
        render_src = "edge"
        if not out_y and not out_x:
            oy, ox = lines_of_cover(shot_gray)
            if oy or ox:
                out_y, out_x, render_src = oy, ox, "cover"
                print("  · %s 边缘投影取不到缝（干净数字稿）→ 已退回「墨迹覆盖率谷」检测" % pid)

        # ---- layout 计划的结构线（从区块示意图取：覆盖率谷 = 空白带） ----
        L["_canvas"] = (W0, H0)
        plan_y, plan_x = gutter_lines(schematic(L, (wr, wh)))

        # ---- 照片框（只收 image/cutout/mask/logo） ----
        photo_z = []
        for z in (L.get("zones") or []):
            b = z.get("box")
            if not is_box(b):
                continue
            x, y, w, h = box_px(b, W0, H0)
            area = (w * h) / float(W0 * H0)
            kind = z.get("kind") or "text"
            st = z.get("style") or {}
            if kind == "image" and st.get("treat") == "bleed":
                continue                             # 出血元素不受边界约束
            if kind in ("image", "cutout", "mask", "logo") and area >= MIN_AREA:
                photo_z.append((z.get("id"), x, y, w, h, area))

        pY, missY = axis_score(ref_y, [(v, 1.0) for v in plan_y], tol)
        pX, missX = axis_score(ref_x, [(v, 1.0) for v in plan_x], tol)
        plan = combine([pY, pX]) or 0.0

        renY, missRY = axis_score(ref_y, [(v, 1.0) for v in out_y], tol)
        renX, missRX = axis_score(ref_x, [(v, 1.0) for v in out_x], tol)
        render = combine([renY, renX]) or 0.0

        # ---- 照片框：四边在参考图边缘上的可覆盖率 ----
        py = px_ = 0.0
        if photo_z:
            for _id, x, y, w, h, area in photo_z:
                cs = [cover_h(eb, x * sc, (x + w) * sc, y * sc, tolpx),
                      cover_h(eb, x * sc, (x + w) * sc, (y + h) * sc, tolpx),
                      cover_v(eb, y * sc, (y + h) * sc, x * sc, tolpx),
                      cover_v(eb, y * sc, (y + h) * sc, (x + w) * sc, tolpx)]
                py += area * (sum(cs) / 4.0)
                px_ += area
            photo = round(py / px_, 4) if px_ else 0.0
        else:
            photo = None

        sim = block_sim(gray_s, shot_gray)
        photo_term = photo if photo is not None else sim
        score = round(W_PLAN * plan + W_RENDER * render + W_PHOTO * photo_term + W_SIM * sim, 4)

        out["pages"][pid] = {
            "ref": os.path.basename(refp), "canvas": [W0, H0], "score": score,
            "weak": weak, "refLineCount": len(ref_y) + len(ref_x),
            "plan": plan, "planY": r4(pY), "planX": r4(pX),
            "render": render, "renderY": r4(renY), "renderX": r4(renX), "renderSrc": render_src,
            "photo": photo, "sim": sim,
            "refLinesY": [round(v, 4) for v in ref_y], "refLinesX": [round(v, 4) for v in ref_x],
            "planLinesY": [round(v, 4) for v in plan_y], "planLinesX": [round(v, 4) for v in plan_x],
            "outLinesY": [round(v, 4) for v in out_y], "outLinesX": [round(v, 4) for v in out_x],
            "missedPlanY": missY, "missedPlanX": missX,
            "missedRenderY": missRY, "missedRenderX": missRX,
            "photoZones": [p[0] for p in photo_z],
        }
        if not weak:
            scores.append(score)

        try:
            tri_panel(ref, shot, eb, L.get("zones") or [], os.path.join(REPORT, pid + "_skeleton.png"))
        except Exception as e:
            print("WARN 画 %s_skeleton.png 失败：%s" % (pid, e))

        tag = "OK  " if score >= GOOD else ("弱  " if weak else "WARN")
        print("%s %s 骨架吻合分 %.2f%s  = %.2f·计划 %.2f + %.2f·渲染 %.2f + %.2f·%s + %.2f·相似度 %.2f"
              % (tag, pid, score,
                 "（参考图结构线仅 %d 条，证据弱）" % (len(ref_y) + len(ref_x)) if weak else "",
                 W_PLAN, plan, W_RENDER, render, W_PHOTO,
                 ("照片框 %.2f" % photo) if photo is not None else "相似度 %.2f" % sim,
                 W_SIM, sim))
        if score < GOOD and not weak:
            if plan < render:
                my, mx, who = missY, missX, "计划（layout 的框）"
            else:
                my, mx, who = missRY, missRX, "渲染（成品页上的内容带）"
            if my:
                print("      %s 缺这几条横缝：%s" % (who, "、".join("%.1f%%" % (v * 100) for v in my)))
            if mx:
                print("      %s 缺这几条纵缝：%s" % (who, "、".join("%.1f%%" % (v * 100) for v in mx)))
            if score < FAIR:
                print("      → 分数偏低：版式可能没有按参考图做。请看 "
                      "_shots/report/%s_skeleton.png 的第三联（青=参考图边缘，红=你的框）" % pid)

    with open(os.path.join(REPORT, "skeleton.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)

    if scores:
        na = sum(1 for v in out["pages"].values() if v.get("na"))
        wk = sum(1 for v in out["pages"].values() if v.get("weak"))
        extra = []
        if wk:
            extra.append("%d 页证据弱（参考图结构线不足 %d 条，出分但不计入告警）" % (wk, WEAK_REF_LINES))
        if na:
            extra.append("%d 页 N/A（量不出）" % na)
        print("")
        print("合计 %d 页计较；最低 %.2f / 最高 %.2f%s。报告 -> _shots/report/skeleton.json"
              % (len(scores), min(scores), max(scores),
                 "；另有 " + "；".join(extra) if extra else ""))
        if min(scores) < FAIR:
            print("提示：吻合分是告警级、不阻断出图；但连续偏低说明「解析参考图」这步没做扎实。")
    else:
        print("")
        print("没有可计较的页（全部 N/A 或证据弱）—— 请人工看 "
              "_shots/report/*_skeleton.png 第三联：青=参考图边缘，红=你的框。")
    sys.exit(0)


if __name__ == "__main__":
    main()
