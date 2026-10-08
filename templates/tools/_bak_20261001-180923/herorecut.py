# -*- coding: utf-8 -*-
"""herorecut.py —— 出血主体照的「重排版 + 换背景」（非生成式）

解决的是参考刊解析里最容易被忽略的两件事：
    ① 背景基色（参考刊是淡蓝，成片却常常是素材自带的米灰）
    ⑦ 主体横向位置（参考刊模特偏左，成片常常居中偏右，被右上白卡压住脸/肩）

做法（全部是像素运算，不调用任何生成模型）：
    1. 取主体掩膜（rembg u2net；本地已缓存模型）
    2. 把主体按 --dx / --dy 平移（负值 = 向左/向上），可选 --scale 缩放
    3. 整幅背景**整片重铺**成参考刊量出来的基色（可给上/下两色做竖向渐变）
    4. 主体以掩膜为 alpha 合成回去，边缘按 --shrink 内缩以吃掉原底残边
    5. 同一次运算顺手吐出**与成图严格对齐**的遮挡掩膜（供 layout 的 occlude 用）

★为什么位移与掩膜必须由同一次运算产出：
    occlude 掩膜是「画布坐标」的，一旦位移量与掩膜分别生成，
    「刊头被头部挡住」的位置就会错开几个百分点 —— 那正是看起来"差一点"的来源。

用法
----
    python tools/herorecut.py images/p01-hero.jpg images/p01-hero.jpg \
        --dx -0.26 --bg-from assets/ref/p01.jpg --size 1280x1617 \
        --emit-mask images/p01-submask.png --check

参数
    --dx F      主体横向平移，画布宽的比例（负 = 左移）
    --dy F      纵向平移（负 = 上移）
    --scale F   主体缩放，绕主体 bbox 的底边中心
    --bg HEX    背景基色，如 #E4EBF6
    --bg-from P 从参考图 P 自动取基色（三只未被主体污染的角的中位色）
    --bg2 HEX   背景第二色（底部），给了就做竖向渐变
    --size WxH  输出尺寸，默认沿用原图
    --shrink N  主体掩膜内缩 N px（去掉原底残边），默认 2
    --feather N 合成边缘羽化 px，默认 1.2
    --emit-mask P  写出遮挡掩膜（不透明=保留，透明=挖掉主体 → 供 occlude）
    --mask-npy P   复用已有掩膜 npy（形状须与源图同）
    --check     只报告主体位移前后的横向范围与**四边接触率**，不写文件
    --fit-touch "T=33,B=100,R=40,L=48"
                ★反解 scale/dx/dy，使主体的四边接触率尽量贴近参考刊读数。
                指标与 refdims.py 的 occl_mask_geom 同口径（该边 3% 带内主体占比）。
                搜到的参数会覆盖 --dx/--dy/--scale，并在末尾打印可直接复现的命令行。
                用途：第 7 点（模特构图）在**还原层**的修复 ——
                参考刊头发切上边、礼服铺满底边与右边，成片若四边全不触，
                画幅四周就是一片平底；这只能用重裁解决，不能靠版面加元素掩盖。
    --tol N     浮点掩膜二值化阈值，默认 0.5
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def argval(name, default=None):
    a = sys.argv[1:]
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith("--") else True
    return default


def hex2rgb(s):
    s = str(s).lstrip("#")
    return np.array([int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)], np.float32)


def rgb2hex(c):
    return "#%02X%02X%02X" % tuple(np.clip(c, 0, 255).astype(int))


def base_color_from(path):
    """参考图的背景基色 = 三只角（左上/右上/左中）的中位色。
    为什么不用四角：封面常常有一角被主体的衣服/头发占掉（例如左下是裙摆），
    取中位能自动把那只被污染的角压下去。"""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = max(6, int(min(w, h) * 0.04))
    a = np.asarray(im).astype(np.float32)
    spots = [a[0:s, 0:s], a[0:s, -s:], a[int(h * 0.45):int(h * 0.45) + s, 0:s]]
    vals = np.array([np.median(x.reshape(-1, 3), axis=0) for x in spots])
    return np.median(vals, axis=0)


def subject_alpha(src, mask_npy=None, model="u2net"):
    if mask_npy:
        a = np.load(mask_npy)
        return a.astype(np.float32), "npy:%s" % os.path.basename(mask_npy)
    from rembg import remove, new_session
    sess = new_session(model)
    im = Image.open(src).convert("RGB")
    a = np.asarray(remove(im, session=sess, only_mask=True)).astype(np.float32) / 255.0
    return a, "rembg:%s" % model


def erode(m, r):
    """方形核腐蚀。分离式两趟：先横后纵，代价 O(2k) 而不是 O(k²)。
    边界补 1.0（=「画布外算作主体」）—— 否则贴边的身体会被腐蚀出一个假缺口。"""
    r = int(r)
    if r < 1:
        return m
    h, w = m.shape
    k = 2 * r + 1
    ph = np.pad(m, ((0, 0), (r, r)), constant_values=1.0)
    a = np.ones((h, w), np.float32)
    for i in range(k):
        a = np.minimum(a, ph[:, i:i + w])
    pv = np.pad(a, ((r, r), (0, 0)), constant_values=1.0)
    b = np.ones((h, w), np.float32)
    for i in range(k):
        b = np.minimum(b, pv[i:i + h, :])
    return b


def shift2d(arr, dx, dy, fill=0.0):
    """整数平移：目的 (x,y) ← 源 (x-dx, y-dy)。dx>0 → 内容右移。"""
    h, w = arr.shape[:2]
    dx, dy = int(round(dx)), int(round(dy))
    out = np.full_like(arr, fill) if arr.ndim == 2 else np.full(arr.shape, fill, np.float32)
    sx0, sx1 = max(0, -dx), min(w, w - dx)
    sy0, sy1 = max(0, -dy), min(h, h - dy)
    if sx1 <= sx0 or sy1 <= sy0:
        return out
    out[sy0 + dy:sy1 + dy, sx0 + dx:sx1 + dx] = arr[sy0:sy1, sx0:sx1]
    return out


def touch_rates(m, band=0.03):
    """★四边接触率 —— 与 tools/refdims.py 的 occl_mask_geom **同一口径**
    （该边 3% 宽带内「主体」所占百分比）。

    这是第 7 点唯一能量化的东西：参考刊的裙摆触右下边、头发切上边，
    成片若四边全不触，画幅四周就是一片平底 —— 那**不是排版层能修的**
    （拉长卡片、加装饰只是掩盖），必须回生图层：重裁 / 重排 / 重出。
    """
    h, w = m.shape
    eb, ebh = max(1, int(w * band)), max(1, int(h * band))
    return {"L": round(float(m[:, :eb].mean()) * 100, 1),
            "R": round(float(m[:, w - eb:].mean()) * 100, 1),
            "T": round(float(m[:ebh].mean()) * 100, 1),
            "B": round(float(m[h - ebh:].mean()) * 100, 1)}


def parse_targets(s):
    """`T=33,B=100,R=40` → {'T':33.0,'B':100.0,'R':40.0}"""
    out = {}
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        k = k.strip().upper()
        if k not in ("L", "R", "T", "B"):
            raise SystemExit("✗ --fit-touch 的键只能是 L/R/T/B，收到 %r" % k)
        out[k] = float(v)
    return out


def fit_touch(m, targets, sc_range=(1.0, 2.2), steps=17, tol_ok=12.0, shrink=0,
              head_x=None, head_x_tol=0.06, top_cut=0.05, head_keep=0.55, pivot="head"):
    """★反解 (scale, dx, dy)：让主体的四边接触率尽量贴近参考刊读数。

    为什么需要它：第 7 点的读数（头心 x / 四边接触率）本来靠人手动试参数去凑，
    试 20 遍也未必对得上。这里把它变成一次搜索 —— 只在**等比缩放 + 平移**（不变形）里找。

    ★★最重要的一条：接触率**单独做目标函数会被作弊**。
       实测：只优化 T/B/R，解出 scale=1.655，四条边全达标 —— 但画面上**头已经没了**
       （主体顶边跑到 −0.615，整个脸被裁在画幅之上）。
       接触率高 ≠ 构图对。所以必须配两道不可违反的硬约束：

         A. **头部完整性**：主体顶边不许高于 −top_cut，且头部带（y<0.35）里
            主体的覆盖不许低于 head_keep × 重排前的覆盖 —— 头可以被切发梢，不能被切掉。
         B. **头心 x 必须落在参考值 ± head_x_tol**（否则「居中偏左」白说了）。

       违反约束的解**直接丢弃**，不参与打分。约束与目标分离，才不会被目标牵着走。

    ★另三条纪律（也都是踩出来的）：
      1. **已经达标的边退出目标函数**（|当前−参考| ≤ tol_ok）——
         否则为了把 R 从 0 拉到 40 会把本来合格的 L 从 42 压到 24，修一条坏一条。
      2. **粗搜 + 全分辨率局部精修**：只在小掩膜（1/4 分辨率）上搜会偏 6pp。
      3. **评分必须带上 `--shrink` 的腐蚀**：main() 在评分之后还会 erode 一次，
         不预先把这步算进去，会出现「纸面达标、落地掉线」。

    ★pivot="head"：缩放绕**头顶**而不是 bbox 底边。
      绕底边放大会把头顶推出画幅；绕头顶放大，头待在原地、身体向下向外长 ——
      这才可能同时满足「头发切上边 + 身体填满右下」。

    ★冻结只是把某条边移出目标函数，**并不能保证它不退化**：放大主体本身就会
    把左带内容推出画幅。所以调用方必须**如实展示四条边 before→after**。

    返回 (score, scale, dx, dy, rates_full, targets_used, frozen, rejected)。
    """
    h, w = m.shape
    r0 = touch_rates(m)

    frozen = {k: r0[k] for k, t in targets.items() if abs(r0[k] - t) <= tol_ok}
    use = {k: t for k, t in targets.items() if k not in frozen}
    if not use:
        return 0.0, 1.0, 0.0, 0.0, r0, {}, frozen, 0

    rejected = [0]

    # ---- 统一在 1/ds 分辨率上搜（一次下采样，两阶段）----
    # 为什么不在 1/4 分辨率上粗搜：粗搜那一层的 shrink 会按**全分辨率像素**算，
    # 2px 在 1/4 分辨率上等于 8px，把掩膜侵蚀到「头部覆盖不足」→ 约束全部失败
    # → 报「无解」。这是个自己给自己设的假门槛。
    ds = 2
    sm = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize(
        (max(1, w // ds), max(1, h // ds)), Image.BILINEAR)).astype(np.float32) / 255.0
    sm = (sm > 0.5).astype(np.float32)
    shrink_s = max(0, int(round(shrink / float(ds))))
    sh, sw = sm.shape
    band_s = max(1, int(sh * 0.35))
    sys_, sxs = np.nonzero(sm)
    piv_x = (sxs.min() + sxs.max()) / 2.0
    piv_y = float(sys_.min()) if pivot == "head" else float(sys_.max())
    hy0_cover = float(sm[:band_s].mean()) if sm[:band_s].any() else 0.0

    def score_of(mm):
        """在 sm 分辨率上评分：返回 (score, rates)；违反硬约束 → (None, None)。"""
        if not mm.any():
            return None, None
        mm = (mm > 0.5).astype(np.float32)
        if shrink_s:
            mm = erode(mm, shrink_s)
        if not mm.any():
            return None, None
        yy, xx = np.nonzero(mm)
        if yy.min() / sh < -top_cut:                              # 约束 A-1 顶边不下沉
            rejected[0] += 1
            return None, None
        band = mm[:band_s]
        if not band.any() or float(band.mean()) < head_keep * hy0_cover:   # 约束 A-2 头部还在
            rejected[0] += 1
            return None, None
        if head_x is not None:                                     # 约束 B 头心 x
            ax = float(np.nonzero(band)[1].mean()) / sw
            if abs(ax - head_x) > head_x_tol:
                rejected[0] += 1
                return None, None
        rr = touch_rates(mm)
        return sum((rr[k] - t) ** 2 for k, t in use.items()), rr

    # 阶段一：粗搜（缩放 × 9×9 平移）
    scales = np.linspace(sc_range[0], sc_range[1], steps)
    cache = {round(float(s), 4): scale_about(sm, s, piv_x, piv_y) for s in scales}
    offs = np.linspace(-0.22, 0.22, 9)
    best = None
    for s in scales:
        base = cache[round(float(s), 4)]
        for dyq in offs:
            for dxq in offs:
                sc_, _ = score_of(shift2d(base, dxq * sw, dyq * sh))
                if sc_ is not None and (best is None or sc_ < best[0]):
                    best = (sc_, float(s), float(dxq), float(dyq))
    # 阶段二：细搜（±0.04 缩放 / ±0.04 平移）
    if best is not None:
        _, s0, dx0, dy0 = best
        fine = None
        for s in s0 + np.linspace(-0.04, 0.04, 5):
            if s <= 0.2:
                continue
            base = sm if abs(s - 1.0) < 1e-6 else scale_about(sm, s, piv_x, piv_y)
            for dyq in dy0 + np.linspace(-0.04, 0.04, 9):
                for dxq in dx0 + np.linspace(-0.02, 0.02, 5):
                    sc_, rr = score_of(shift2d(base, dxq * sw, dyq * sh))
                    if sc_ is not None and (fine is None or sc_ < fine[0]):
                        fine = (sc_, float(s), float(dxq), float(dyq), rr)
        if fine is not None:
            best = fine
    if best is None:
        return None, 1.0, 0.0, 0.0, r0, use, frozen, rejected[0]
    if len(best) == 4:
        return best[0], best[1], best[2], best[3], r0, use, frozen, rejected[0]
    return best[0], best[1], best[2], best[3], best[4], use, frozen, rejected[0]


def scale_about(arr, f, cx, cy):
    """绕 (cx,cy) 缩放；arr 可为 HxW 或 HxWxC。"""
    if abs(f - 1.0) < 1e-6:
        return arr
    h, w = arr.shape[:2]
    im = Image.fromarray(arr if arr.ndim == 2 else arr.astype(np.uint8))
    nw, nh = max(1, int(round(w * f))), max(1, int(round(h * f)))
    im = im.resize((nw, nh), Image.LANCZOS if arr.ndim == 3 else Image.BILINEAR)
    big = np.asarray(im).astype(np.float32)
    # 把缩放后的图按「(cx,cy) 处不动」放回原尺寸画布
    ox, oy = int(round(cx - cx * f)), int(round(cy - cy * f))
    out = np.zeros_like(arr, np.float32)
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(w, ox + nw), min(h, oy + nh)
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = big[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    return out


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pos:
        raise SystemExit(__doc__)
    src = pos[0] if os.path.isabs(pos[0]) else os.path.join(ROOT, pos[0])
    dst = pos[1] if len(pos) > 1 else None
    if dst and not os.path.isabs(dst):
        dst = os.path.join(ROOT, dst)

    dx = float(argval("--dx", 0))
    dy = float(argval("--dy", 0))
    sc = float(argval("--scale", 1.0))
    bg_hex = argval("--bg")
    bg_from = argval("--bg-from")
    bg2_hex = argval("--bg2")
    size = argval("--size")
    shrink = int(argval("--shrink", 2))
    feather = float(argval("--feather", 1.2))
    emit = argval("--emit-mask")
    mask_npy = argval("--mask-npy")
    tol = float(argval("--tol", 0.5))
    fit_touch_arg = argval("--fit-touch")
    head_x = argval("--head-x")
    head_x = float(head_x) if head_x is not None else None
    top_cut = float(argval("--top-cut", 0.05))
    pivot = str(argval("--pivot", "head"))
    if pivot not in ("head", "bottom"):
        raise SystemExit("✗ --pivot 只能是 head（绕头顶缩放）或 bottom（绕 bbox 底边缩放）")
    check_only = "--check" in sys.argv

    im = Image.open(src).convert("RGB")
    W, H = im.size
    if size:
        W, H = [int(v) for v in str(size).lower().split("x")]
        im = im.resize((W, H), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)

    alpha, desc = subject_alpha(src, mask_npy)
    if alpha.shape[:2] != (H, W):
        alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)).astype(np.float32) / 255.0

    m = (alpha > tol).astype(np.float32)
    ys, xs = np.nonzero(m)
    if not len(xs):
        print("✗ 掩膜为空 → 主体识别失败，不做任何写入")
        return 1
    head_h = int(0.25 * H)
    hy, hx = np.nonzero(m[:head_h])

    def span(mm, tag):
        y2, x2 = np.nonzero(mm)
        if not len(x2):
            return "%s 空" % tag
        return "%s x %.3f–%.3f" % (tag, x2.min() / W, x2.max() / W)

    print("源 %s  %dx%d  掩膜=%s  主体 %.1f%%" % (os.path.relpath(src, ROOT), W, H, desc, m.mean() * 100))
    print("  位移前  全页 %s   |  头部带(y<0.25) 中心 x %.3f  四边接触率 %s" %
          (span(m, ""), (hx.min() + hx.max()) / 2 / W, touch_rates(m)))

    # ---- ★按参考刊的触边率反解变换（第 7 点的还原层修复）----
    if fit_touch_arg:
        tgt = parse_targets(fit_touch_arg)
        r_before = touch_rates(m)
        print("  目标触边率 %s%s → 搜索等比缩放 + 平移（不变形，绕头顶）…"
              % (tgt, "  头心 x 锁定 %.2f" % head_x if head_x is not None else ""))
        score, s_fit, dx_fit, dy_fit, got, used, frozen, nrej = fit_touch(
            m, tgt, shrink=shrink, head_x=head_x, top_cut=top_cut, pivot=pivot)
        if score is None:
            print("  ✗ **无解**：在「头部完整（顶边不下沉超过 %.0f%%）+ 头心 x±0.06」的约束下，"
                  "没有一组 scale/dx/dy 能改善 %s。" % (top_cut * 100, "/".join(sorted(used))))
            print("     （搜索中丢弃了 %d 组越约束的解）" % nrej)
            print("     结论：**这不是参数问题** —— 这张照片里没有能填满%s的内容，"
                  "要回生图层重出（或换一张主体更满的画幅）。" % "/".join(sorted(used)))
            return 1
        if not used:
            print("  四条边都已经在 ±12pp 内达标，无需重排。")
            return 0
        if frozen:
            print("  已达标、退出优化（防止被别的边带坏）：%s"
                  % ", ".join("%s 参考%.0f%%/当前%.0f%%" % (k, tgt[k], frozen[k]) for k in sorted(frozen)))
        if nrej:
            print("  （搜索中丢弃 %d 组越约束的解：头部完整性 / 头心 x）" % nrej)
        print("  解出  scale=%.3f  dx=%+.3f  dy=%+.3f" % (s_fit, dx_fit, dy_fit))
        print("        ┌─ 四条边 before → after（★冻结 ≠ 不退化：放大主体会把内容推出画幅）")
        for k in ("L", "R", "T", "B"):
            if k in tgt:
                d = got[k] - r_before[k]
                flag = "　✓" if abs(got[k] - tgt[k]) <= 12 else "　★未达标"
                if abs(r_before[k] - tgt[k]) <= 12 and abs(d) > 12:
                    flag = "　★**反而弄坏了**（原本已达标）"
                print("        │ %s  参考 %5.0f%%   重排前 %5.0f%% → 重排后 %5.0f%%（%+.0fpp）%s"
                      % (k, tgt[k], r_before[k], got[k], d, flag))
        print("        └─ 取舍由人定：某条边填不满是**这张照片的物理约束**（参考刊靠裙摆铺左，"
              "本片没有那段裙摆），要彻底解决只能回图层重出，不是调参数。")
        sc, dx, dy = s_fit, dx_fit, dy_fit
        print("  复现命令（已覆盖命令行给的 dx/dy/scale）：")
        print("      python tools/herorecut.py %s %s --dx %.3f --dy %.3f --scale %.3f <背景/掩膜参数>"
              % (pos[0], pos[1] if len(pos) > 1 else "<dst>", dx, dy, sc))

    # ---- 主体平移 / 缩放 ----
    # ★缩放支点必须与 fit_touch 的搜索支点一致，否则「解出的参数」与「落地的画面」不是同一张：
    #   搜索按头顶缩放 → 头待在原地、身体向下向外长；应用却按 bbox 底边缩放 → 头顶被推出画幅。
    #   实测过一次：搜索预测 R 41%/T 35%，落地却是 R 0%/T 2%，两边完全对不上。
    dxp, dyp = dx * W, dy * H
    if abs(sc - 1.0) > 1e-6:
        bx0, bx1 = xs.min(), xs.max()
        piv_x = (bx0 + bx1) / 2
        piv_y = float(ys.min()) if pivot == "head" else float(ys.max())
        m = scale_about(m, sc, piv_x, piv_y)
        m = (m > 0.5).astype(np.float32)
        a = scale_about(a, sc, piv_x, piv_y)
    m = shift2d(m, dxp, dyp)
    # 主体像素同步平移：用位移后的掩膜当 alpha，像素本身也从同一偏移取
    a = shift2d(a, dxp, dyp)

    if shrink:
        m = erode(m, shrink)

    my, mx = np.nonzero(m)
    if not len(mx):
        print("✗ 位移后主体完全出画 → 请减小 |--dx|")
        return 1
    hy2, hx2 = np.nonzero(m[:head_h])
    r2 = touch_rates(m)
    print("  位移后  全页 %s   |  头部带 中心 x %.3f  四边接触率 %s" %
          (span(m, ""), (hx2.min() + hx2.max()) / 2 / W if len(hx2) else float("nan"), r2))
    if fit_touch_arg:
        tgt = parse_targets(fit_touch_arg)
        bad = ["%s 参考%.0f%%→实际%.0f%%" % (k, tgt[k], r2[k]) for k in sorted(tgt)
               if abs(r2[k] - tgt[k]) > 12]
        if not bad:
            print("        对表：全部在 ±12pp 内 OK")
        else:
            print("        对表：★仍有 %s" % "；".join(bad))
            print("        ★★结论：**这不是参数问题**。搜索已穷举 scale/dx/dy，"
                  "丢弃了 %d 组越约束（头部完整性 / 头心 x）的解，残余仍在。" % nrej)
            print("           这张照片里**没有**能填满 %s 的内容（参考刊靠裙摆铺满，本片是棚拍平底裁切）。"
                  % "/".join(sorted(tgt)))
            print("           要解决只能回**生图层**：重出（提示词写清背景基色 / 主体轴心 / 主体触边三件事）"
                  "或换一张主体更满的画幅。**不许用拉长卡片、加装饰去填** —— 那是掩盖。")

    if check_only:
        return 0
    if not dst:
        raise SystemExit("✗ 缺输出路径：python tools/herorecut.py <src> <dst> [选项]")

    # ---- 背景 ----
    if bg_hex:
        c0 = hex2rgb(bg_hex)
    elif bg_from:
        p = bg_from if os.path.isabs(bg_from) else os.path.join(ROOT, bg_from)
        c0 = base_color_from(p)
    else:
        c0 = np.array([255, 255, 255], np.float32)
    c1 = hex2rgb(bg2_hex) if bg2_hex else c0
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    bg = (c0[None, None, :] * (1 - t) + c1[None, None, :] * t)
    bg = np.repeat(bg, W, axis=1)

    # ---- 合成 ----
    al = m.copy()
    if feather > 0:
        al = np.asarray(Image.fromarray((al * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(feather))).astype(np.float32) / 255.0
    al = al[:, :, None]
    out = a * al + bg * (1 - al)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB").save(dst, quality=94, subsampling=0)

    lines = ["OK  %s → %s" % (os.path.relpath(src, ROOT), os.path.relpath(dst, ROOT)),
             "    背景基色 %s%s  尺寸 %dx%d  位移 dx=%.3f dy=%.3f scale=%.2f" % (
                 rgb2hex(c0), ("→" + rgb2hex(c1)) if bg2_hex else "", W, H, dx, dy, sc),
             "    主体 %.1f%%  头部带中心 x %.3f  内缩 %dpx 羽化 %.1fpx" % (
                 m.mean() * 100, (hx2.min() + hx2.max()) / 2 / W if len(hx2) else float("nan"), shrink, feather)]

    # ---- 遮挡掩膜（与成图严格同坐标）----
    if emit:
        ep = emit if os.path.isabs(emit) else os.path.join(ROOT, emit)
        keep = np.clip((1.0 - m) * 255.0, 0, 255).astype(np.uint8)
        if feather > 0:
            keep = np.asarray(Image.fromarray(keep).filter(ImageFilter.GaussianBlur(feather))).astype(np.uint8)
        rgba = np.dstack([np.full_like(keep, 255), np.full_like(keep, 255),
                          np.full_like(keep, 255), keep])
        Image.fromarray(rgba, "RGBA").save(ep)
        lines.append("    遮挡掩膜 → %s（不透明=保留，透明=挖掉主体）" % os.path.relpath(ep, ROOT))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
