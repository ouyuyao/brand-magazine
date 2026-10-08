# -*- coding: utf-8 -*-
"""
faces.py —— 人脸框标定辅助（把皮肤密度打成字符网格，供人工读出人脸框）

为什么不用现成的人脸检测：
  本机没有可用模型（无网络、无 haarcascade、无 insightface/onnx）。
  所以走「肤色密度字符网格 + 人工读数」这条路：网格是数字，可复核、可复现，
  不会像肉眼在整页图上"找"那样漏掉。

用法：
  python tools/faces.py            # 全部页
  python tools/faces.py page01     # 指定页
  python tools/faces.py --cell 64  # 网格边长（默认 64px）

输出：终端字符网格（0-9 = 该格内肤色像素占比 0-90%），
      以及每个连通块的外接矩形（候选人脸框，按面积排序）。
"""
import json, os, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")

CELL = 64
argv = sys.argv[1:]
ci = argv.index("--cell") if "--cell" in argv else -1
if ci >= 0:
    CELL = int(argv[ci + 1]); del argv[ci:ci + 2]
import _cli
only = [a for a in _cli.positionals() if a.startswith("page")]   # ★argv 里混着 --cell 的值，不能直接筛

# 肤色判据：RGB 规则 + YCbCr 规则同时成立（比单用一条稳）
def is_skin(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    if not (r > 95 and g > 40 and b > 20 and mx - mn > 15 and abs(r - g) > 15 and r > g and r > b):
        return False
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return 77 <= cb <= 127 and 133 <= cr <= 173


def analyse(name):
    src = os.path.join(SHOTS, name + ".png")
    if not os.path.exists(src):
        return None
    im = Image.open(src).convert("RGB")
    W, H = im.size
    small = im.resize((W // 4, H // 4))            # 降采样加速，判据在 1/4 尺寸上照样成立
    px = small.load()
    cols, rows = (W + CELL - 1) // CELL, (H + CELL - 1) // CELL
    dens = [[0.0] * cols for _ in range(rows)]
    for cy in range(rows):
        for cx in range(cols):
            x0, y0 = cx * CELL // 4, cy * CELL // 4
            x1, y1 = min(small.width, (cx + 1) * CELL // 4), min(small.height, (cy + 1) * CELL // 4)
            tot = hit = 0
            for y in range(y0, y1, 2):
                for x in range(x0, x1, 2):
                    tot += 1
                    if is_skin(*px[x, y]):
                        hit += 1
            dens[cy][cx] = hit / tot if tot else 0.0

    print("=== %s  %dx%d  cell=%d  grid=%dx%d" % (name, W, H, CELL, cols, rows))
    print("     " + "".join(str((cx * CELL) // 100 % 10) for cx in range(cols)) + "   (x/100)")
    for cy in range(rows):
        line = "".join("." if v < 0.15 else str(min(9, int(v * 10))) for v in dens[cy])
        print("%4d %s" % (cy * CELL, line))

    # 连通块（4 邻域，密度 ≥ 0.5 视为肤色格）
    seen = [[False] * cols for _ in range(rows)]
    comps = []
    for cy in range(rows):
        for cx in range(cols):
            if seen[cy][cx] or dens[cy][cx] < 0.5:
                continue
            stack, cells = [(cy, cx)], []
            seen[cy][cx] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and dens[ny][nx] >= 0.5:
                        seen[ny][nx] = True
                        stack.append((ny, nx))
            ys = [c[0] for c in cells]; xs = [c[1] for c in cells]
            comps.append((len(cells),
                          min(xs) * CELL, min(ys) * CELL,
                          (max(xs) + 1) * CELL, (max(ys) + 1) * CELL))
    comps.sort(reverse=True)
    for n, x0, y0, x1, y1 in comps[:6]:
        if n < 3:
            continue
        print("    候选块 %2d 格  x%d..%d y%d..%d  (%dx%d)" % (n, x0, x1, y0, y1, x1 - x0, y1 - y0))
    return comps


def main():
    names = only or ["page%02d" % i for i in range(1, 10)]
    for n in names:
        analyse(n)
        print()


if __name__ == "__main__":
    main()
