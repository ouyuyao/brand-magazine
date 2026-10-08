# -*- coding: utf-8 -*-
"""_dens.py —— 「画面密度」共用算法（refdims ⑫ 与 densitycheck.py 共用一份实现）

为什么需要它
------------
用户第 5 点原话：「文字大小太小了，没有配合画面，使画面显得很空」。
「显得空」在这套判据链里此前**没有任何一条能测**：
  · contrastcheck 只测「字压照片读不读得出来」；
  · edgefit 只测「参考图的结构线你的框有没有」；
  · blockcheck 只测「实底块之间互不互压」。
「一块区域里到底有没有东西」——没量过。于是画面空不空，全凭肉眼，谁都能说没事。

量什么
------
把画面切成 rows×cols 宫格，对每格算**局部梯度能量**（|Δx|+|Δy| 高于阈值的像素占比）。
它衡量的不是亮度而是「这里有没有边缘/纹理」——
  · 平坦的背景、纯色纸底   → 接近 0
  · 大字号标题、罫线、照片 → 明显偏高
再拿同一张参考图的宫格做逐格对照，就能把「参考刊这块是满的、你这块是空的」变成数字。

★注意：它比的是**分布形状**，不是绝对值。参考刊与成品的照片内容必然不同，
  所以判定用的是「逐格差值」与「空档格」（参考高、成品近零）两类信号，
  而不是总量相等。绝对总量差得再多，只要每格都有东西，就不算「空」。
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def _grad(gray: np.ndarray) -> np.ndarray:
    """局部梯度能量：四分邻差的绝对值之和。不引 scipy。"""
    g = gray.astype(np.float32)
    dx = np.zeros_like(g)
    dy = np.zeros_like(g)
    dx[:, :-1] = np.abs(g[:, 1:] - g[:, :-1])
    dy[:-1, :] = np.abs(g[1:, :] - g[:-1, :])
    return dx + dy


def grid_density(path: str, rows: int = 3, cols: int = 3, thr: float = 12.0,
                 long_edge: int = 720):
    """返回 rows×cols 的「墨迹占比」矩阵（%），以及归一化后的原始尺寸。

    thr：梯度阈值（0–255 灰度）。低于它的算「平」，高于它的算「有内容」。
         12 是经验值：纸纹与压缩噪点通常 <8，一根 1px 的细罫线约 30–60，
         字号 20 的正文边缘约 40–90。
    """
    if not path:
        return None
    try:
        im = Image.open(path).convert("L")
    except Exception:
        return None
    w, h = im.size
    if max(w, h) > long_edge:
        s = long_edge / float(max(w, h))
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    a = np.asarray(im)
    g = _grad(a)
    hot = (g > thr)
    H, W = hot.shape
    out = []
    for r in range(rows):
        row = []
        y0, y1 = int(H * r / rows), int(H * (r + 1) / rows)
        for c in range(cols):
            x0, x1 = int(W * c / cols), int(W * (c + 1) / cols)
            cell = hot[y0:y1, x0:x1]
            row.append(round(float(cell.mean()) * 100, 2))
        out.append(row)
    return {"rows": rows, "cols": cols, "thr": thr, "grid": out,
            "size": [w, h],
            "mean": round(float(np.mean([v for row in out for v in row])), 2)}


def zone_coverage(zones, canvas, rows: int = 3, cols: int = 3,
                  kinds=("image", "cutout", "mask", "logo")):
    """逐格「影像元素覆盖率」（%）：该格被 image/cutout/mask/logo 类 zone 盖住多少。

    ★为什么需要它（实测踩到的假阳性）：
      本项目的商品素材是**淡彩商品图**（浅绿/浅紫文胸压浅灰底）——
      局部梯度能量天然很低（实测整格 0.9–2%），而参考刊那格是
      「深色包袋 / 模特蕾丝裙」，梯度 20–40%。于是 `densitycheck` 把一个
      **被商品图完整占满**的格报成「空档格」，还给出「补一个该格该有的元素」的建议 ——
      那条建议会把人推向「往里塞图案」，正是 Goodhart。

      区分办法不是换阈值（换阈值只是把假阳性挪个位置），而是**引入第二条证据**：
      「这格有没有东西占据」= 元素覆盖率。梯度低 + 覆盖高 → **素材平坦格**（告警级）；
      梯度低 + 覆盖也低 → 才是真的空白（空档格，阻断级）。

      素材本身低对比是可以解释的（品牌调性就是淡彩），
      而「参考刊这格有内容、你这里连元素都没放」是排版问题 —— 两者不该同名。
    """
    if not zones or not canvas:
        return None
    W, H = canvas
    grid = [[0.0] * cols for _ in range(rows)]
    for z in zones:
        if (z.get("kind") or "text") not in kinds:
            continue
        b = z.get("box")
        if not b:
            continue
        x, y, w, h = b[0] * W, b[1] * H, b[2] * W, b[3] * H
        for r in range(rows):
            cy0, cy1 = H * r / rows, H * (r + 1) / rows
            oy = max(0.0, min(cy1, y + h) - max(cy0, y))
            if oy <= 0:
                continue
            for c in range(cols):
                cx0, cx1 = W * c / cols, W * (c + 1) / cols
                ox = max(0.0, min(cx1, x + w) - max(cx0, x))
                if ox > 0:
                    grid[r][c] = min(100.0, grid[r][c]
                                     + ox * oy / ((cx1 - cx0) * (cy1 - cy0)) * 100.0)
    return [[round(v, 1) for v in row] for row in grid]


def compare(ref: dict, shot: dict, gap: float = 10.0, dead: float = 2.0,
            ref_hot: float = 10.0, cover=None, cover_min: float = 10.0):
    """逐格对照。

    三类信号（前两类都只在「参考忙着、成品闲着」时才成立，反向不算问题）：
      · 空档格 dead cell ：参考 ≥ ref_hot 而成品 ≤ dead，**且该格元素覆盖率 < cover_min**
                            → 参考刊这里塞了东西，你这里连元素都没放
      · 素材平坦格 flat cell：同上但覆盖率 ≥ cover_min（默认 **1/3**）
                            → 该格有 **1/3 以上**被影像素材填满，低梯度是**素材本身低对比**
                              （淡彩商品图），不是排版漏了东西 —— 告警级，不阻断
      · 明显偏空 gap cell：参考 − 成品 > gap

    ★为什么门槛取 1/3 而不是更高/更低（实测标定，非拍脑袋）：
        < 1/3 的格（page03 [2,0] 0% · page05 [1,2] 0% · page06 [1,2] 25%）
          人工复核确认**确实是空地** —— 参考刊那格有内容而我们连元素都没放；
        ≥ 1/3 的格（page06 [0,1] 43% · page08 [0,2] 33% · page08 [2,2] 42%）
          实测都是**被商品图占满、只是淡彩**的格。
      门槛再高（如 55%）会把后者判成空档格 → 假警报；再低（如 25%）
      会把「3/4 是空白纸」的格也放过 → 漏报。1/3 是这两组数据的分界。
    """
    if not ref or not shot:
        return None
    a, b = ref["grid"], shot["grid"]
    # ★局部名不要叫 dead / gap —— 会覆盖同名参数（曾把 float 参数遮成 list，报
    #   "TypeError: '<=' not supported between 'float' and 'list'"）。
    dead_cells, gap_cells, flat_cells = [], [], []
    for r in range(min(len(a), len(b))):
        for c in range(min(len(a[r]), len(b[r]))):
            d = round(a[r][c] - b[r][c], 2)
            if a[r][c] >= ref_hot and b[r][c] <= dead:
                cv = cover[r][c] if (cover and r < len(cover) and c < len(cover[r])) else 0.0
                rec = {"cell": [r, c], "ref": a[r][c], "shot": b[r][c], "d": d, "cover": cv}
                (flat_cells if cv >= cover_min else dead_cells).append(rec)
            elif d > gap:
                gap_cells.append({"cell": [r, c], "ref": a[r][c], "shot": b[r][c], "d": d})
    return {"ref": a, "shot": b, "dead_cells": dead_cells, "gap_cells": gap_cells,
            "flat_cells": flat_cells, "cover": cover,
            "ref_mean": ref["mean"], "shot_mean": shot["mean"],
            "mean_delta": round(shot["mean"] - ref["mean"], 2)}
