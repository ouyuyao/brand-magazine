# -*- coding: utf-8 -*-
"""
白底产品图 -> 透明 PNG 抠图
思路（不依赖 AI 模型，纯 OpenCV）：
  1. 找出「与图像边界连通的近白像素」= 真正的背景（产品悬空在中央，不会连到边界）
  2. 背景 -> alpha = 0
  3. 阴影/网纱等浅色过渡像素 -> alpha 按亮度连续映射（保留柔和投影，且不依赖底色）
  4. RGB 做 unpremultiply 去白边（halo），让边缘不发白
  5. alpha 轻微羽化抗锯齿
"""
import cv2
import numpy as np
import os
import sys


def cutout(src, dst, white_th=238, blur=0.8, unwhite=True):
    im = cv2.imread(src, cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit("cannot read " + src)
    h, w = im.shape[:2]
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # --- 1. 与边界连通的近白区域 = 背景 ---
    bg_cand = (g >= white_th).astype(np.uint8)
    n, lab = cv2.connectedComponents(bg_cand, connectivity=4)
    border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist()) | \
             set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    outside = np.isin(lab, list(border)) if border else np.zeros((h, w), bool)

    # --- 2. alpha：背景（含原图投影）一律剔除，投影改由 CSS drop-shadow 生成 ---
    a = np.full((h, w), 255.0, np.float32)
    a[outside] = 0.0

    if blur > 0:
        a = cv2.GaussianBlur(a, (0, 0), blur)
    a = np.clip(a, 0, 255)

    # --- 4. 去白边：白底合成反解 ---
    out = im.astype(np.float32)
    if unwhite:
        af = np.clip(a / 255.0, 0, 1)[..., None]
        # 仅对半透明区域（边缘/纱）反解，实心区不动，避免过度加饱和
        edge = ((af > 0.03) & (af < 0.985))
        safe = np.where(af < 0.12, 1.0, af)
        rec = (out - (1.0 - safe) * 255.0) / safe
        out = np.where(edge, rec, out)
        out = np.clip(out, 0, 255)

    rgba = np.dstack([out.astype(np.uint8), a.astype(np.uint8)])
    cv2.imwrite(dst, rgba)
    ys, xs = np.where(a > 8)
    bb = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None
    return (w, h), bb, float((a > 8).mean() * 100)


def checker(size, sq=16):
    c = np.zeros((size[1], size[0], 3), np.uint8)
    for y in range(0, size[1], sq):
        for x in range(0, size[0], sq):
            v = 215 if ((x // sq + y // sq) % 2 == 0) else 250
            c[y:y + sq, x:x + sq] = v
    return c


if __name__ == "__main__":
    D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    IMG = os.path.join(D, "images")
    PREV = os.path.join(D, "_shots")
    os.makedirs(PREV, exist_ok=True)

    tiles = []
    for c in ["pink", "white", "black"]:
        s = os.path.join(IMG, "_flat", "product-%s-flat.png" % c)
        d = os.path.join(IMG, "product-%s.png" % c)
        size, bb, cov = cutout(s, d)
        print("%-6s %s  cover=%.1f%%  bbox=%s" % (c, size, cov, bb))
        r = cv2.imread(d, cv2.IMREAD_UNCHANGED)
        al = (r[:, :, 3:4] / 255.0).astype(np.float32)
        for base, name in [((239, 234, 226), "paper"), ((72, 68, 64), "dark")]:
            bg = np.full_like(r[:, :, :3], base, np.uint8)
            comp = (r[:, :, :3] * al + bg * (1 - al)).astype(np.uint8)
            tiles.append(cv2.resize(comp, (330, 330)))

    sheet = np.hstack(tiles)
    cv2.imwrite(os.path.join(PREV, "_cut-check.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("check -> _shots/_cut-check.jpg")
