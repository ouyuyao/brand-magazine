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


def compare(ref: dict, shot: dict, gap: float = 10.0, dead: float = 2.0,
            ref_hot: float = 10.0):
    """逐格对照。

    两类信号（两者都只在「参考忙着、成品闲着」时才成立，反向不算问题）：
      · 空档格 dead cell ：参考 ≥ ref_hot 而成品 ≤ dead  → 参考刊这里塞了东西，你这里是空的
      · 明显偏空 gap cell：参考 − 成品 > gap            → 密度差得离谱
    """
    if not ref or not shot:
        return None
    a, b = ref["grid"], shot["grid"]
    # ★局部名不要叫 dead / gap —— 会覆盖同名参数（曾把 float 参数遮成 list，报
    #   "TypeError: '<=' not supported between 'float' and 'list'"）。
    dead_cells, gap_cells = [], []
    for r in range(min(len(a), len(b))):
        for c in range(min(len(a[r]), len(b[r]))):
            d = round(a[r][c] - b[r][c], 2)
            if a[r][c] >= ref_hot and b[r][c] <= dead:
                dead_cells.append({"cell": [r, c], "ref": a[r][c], "shot": b[r][c], "d": d})
            elif d > gap:
                gap_cells.append({"cell": [r, c], "ref": a[r][c], "shot": b[r][c], "d": d})
    return {"ref": a, "shot": b, "dead_cells": dead_cells, "gap_cells": gap_cells,
            "ref_mean": ref["mean"], "shot_mean": shot["mean"],
            "mean_delta": round(shot["mean"] - ref["mean"], 2)}
