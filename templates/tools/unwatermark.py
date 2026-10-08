# -*- coding: utf-8 -*-
"""
unwatermark.py —— 抹除素材上的第三方水印／供货方品牌字（中值滤波差异法）。

为什么用这个方法，而不是「涂白」或「整块模糊」：
    供货方水印通常是**白色半透明艺术字**，位置压在「产品轮廓 + 背景」的交界上。
    · 涂白 → 白块直接暴露；整块高斯模糊 → 产品下缘弧线被抹平。
    · 中值滤波（MedianFilter）对**细笔画**敏感、对**大结构边缘**几乎无损：
      文字笔宽通常 3~8px，被中值吃掉；而产品下缘、布料褶皱是几十~几百 px 的大结构，保留。
    · 所以判据是「原像素比中值亮 thr 以上」→ 只有白色笔画命中，产品边缘不动。

局限（必须人眼收尾）：
    若水印压在**白色产品**上（笔画与产品同色），亮度差判据会失灵。
    所以抹完**必须**用 `tools/wmsheet.py` 再出一张对照拼图目检。

用法：
    # 1) 先出对照拼图，人眼定位水印在哪几块
    python tools/wmsheet.py --dir images

    # 2) 按「归一化窗口」抹除；可多窗口、可多文件
    python tools/unwatermark.py images/color-01.jpg --win 0.56,0.83,0.82,0.96
    python tools/unwatermark.py images/colors-grid.jpg \
        --win 0.27,0.395,0.40,0.47 --win 0.77,0.395,0.90,0.47 \
        --win 0.27,0.875,0.40,0.95 --win 0.77,0.875,0.90,0.95 \
        --med 15 --thr 2.2

    # 3) 抹完再出一张对照拼图确认
    python tools/wmsheet.py --dir images

参数：
    --win x0,y0,x1,y1   归一化窗口（可重复）。给得比水印略大一圈即可。
    --med               中值滤波核边长（默认 11；字大的用 15）
    --thr               亮度差阈值（默认 2.5；抹不干净就降到 2.0，误伤产品就升到 3.0）
    --pad               窗口外扩像素（默认 8）
    --out               输出路径（默认原地覆盖）
    --dry               只报告命中像素数，不写文件（先用它确认窗口是否打中水印）

安全：覆盖前自动把原文件备份到 <同目录>/_before_unwatermark/。
"""
import argparse
import os
import shutil
import sys

import numpy as np
from PIL import Image, ImageFilter

BACKUP = "_before_unwatermark"


def parse_wins(items):
    wins = []
    for s in items:
        parts = [float(v) for v in s.replace(" ", "").split(",")]
        if len(parts) != 4:
            raise ValueError("窗口格式应为 x0,y0,x1,y1：%s" % s)
        wins.append(tuple(parts))
    return wins


def erase(im, windows, med=11, thr=2.5, pad=8, dry=False, verbose=True):
    W, H = im.size
    a = np.asarray(im).astype(np.int16)
    out = a.copy()
    total = 0
    for (x0, y0, x1, y1) in windows:
        bx = (max(0, int(x0 * W) - pad), max(0, int(y0 * H) - pad),
              min(W, int(x1 * W) + pad), min(H, int(y1 * H) + pad))
        reg = im.crop(bx)
        r = np.asarray(reg).astype(np.int16)
        med_img = reg.filter(ImageFilter.MedianFilter(med))
        m = r - np.asarray(med_img).astype(np.int16)
        mask = m.mean(axis=2) > thr
        # 膨胀 1px，清掉笔画边缘的残留
        g = mask.copy()
        g[1:, :] |= mask[:-1, :]; g[:-1, :] |= mask[1:, :]
        g[:, 1:] |= mask[:, :-1]; g[:, :-1] |= mask[:, 1:]
        n = int(mask.sum())
        total += n
        if verbose:
            print("    窗口 (%.3f,%.3f,%.3f,%.3f)  框 %s  命中 %d px"
                  % (x0, y0, x1, y1, bx, n))
        if not dry:
            res = np.where(g[..., None], np.asarray(med_img).astype(np.int16), r).astype(np.uint8)
            out[bx[1]:bx[3], bx[0]:bx[2]] = res
    if dry:
        return None, total
    return Image.fromarray(out.astype(np.uint8)), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--win", action="append", required=True, help="归一化窗口 x0,y0,x1,y1，可重复")
    ap.add_argument("--med", type=int, default=11)
    ap.add_argument("--thr", type=float, default=2.5)
    ap.add_argument("--pad", type=int, default=8)
    ap.add_argument("--out")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    wins = parse_wins(a.win)
    grand = 0
    for f in a.files:
        if not os.path.exists(f):
            print("找不到：%s" % f)
            continue
        im = Image.open(f).convert("RGB")
        print("  %s  %dx%d" % (f, im.width, im.height))
        res, n = erase(im, wins, a.med, a.thr, a.pad, a.dry)
        grand += n
        if a.dry or res is None:
            continue
        out_path = a.out or f
        if os.path.abspath(out_path) == os.path.abspath(f):
            bk = os.path.join(os.path.dirname(f), BACKUP)
            os.makedirs(bk, exist_ok=True)
            shutil.copy2(f, os.path.join(bk, os.path.basename(f)))
        res.save(out_path, quality=94, subsampling=1)
        print("    -> %s" % out_path)

    print("\n合计命中 %d px" % grand)
    if grand == 0:
        print("⚠️ 一处都没命中 —— 窗口没打中，或水印是浅灰（不是亮于背景）。检查 --win。")
    else:
        print("→ 现在必须跑 python tools/wmsheet.py 出一张对照拼图，人眼确认抹干净、且产品轮廓没被动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
