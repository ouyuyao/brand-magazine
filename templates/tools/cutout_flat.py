# -*- coding: utf-8 -*-
"""
cutout_flat.py —— 纯色平底产品图 → 透明 PNG（tools/cutout.py 的姊妹工具）

**怎么选：判据是「底有多平」，不是「底有多白」**

  tools/cutout.py 的前提是「背景近白 ≥238，且产品比背景暗」。
  电商供货图的底其实常见两类，选错工具会得到完全错的结果：

    (a) 近白 / 亮灰底，产品比底暗          → tools/cutout.py
    (b) 纯色灰底、标准差 ≈ 0，产品**跨在底色两侧**
        （边缘比底色暗、高光比底色亮）    → 本脚本

  (b) 型下「亮度阈值」这件事没有意义：底色 234、产品边缘 233、高光 255，
  产品同时在底色两侧。分离只能靠「底色绝对均匀 + 与画布边界连通」这个事实。

**先量再定参**：`python tools/cutout_flat.py --probe --src <图>`
  看输出的「底色唯一值个数」与「底色标准差」：≈1 / ≈0.0 → 就是 (b) 型。

口径（顺序不能颠倒）：
  ① 底色 = 边框一圈逐通道中位数
  ② 候选 = 色距 ≤ tol_bg。**绝不能放宽到抗锯齿范围** ——
     产品与底色可能只差 1–25 级，放宽会把产品本体（整条肩带）一起吃掉
  ③ 候选做 3×3 开运算：切断「恰好等于底色」的 1px 细通道。
     柔边里常藏着这样一条，不切断会在产品上咬出一个楔形缺口
  ④ 与画布边界连通的候选 = 背景，其余为产品
  ⑤ 只留最大连通块（去边缘浮点）+ 5×5 中值平滑（去阶梯锯齿）
  ⑥ 算色距**之前**先对图做轻高斯（--presmooth）。柔边处 JPEG 振铃会让
     像素在底色上下抖动（233/234/235 交替）→ 蒙版边界闪成一串大块
  ⑦ 内缩 choke 像素 → 羽化 → unpremultiply 去白边
     （边缘比底色暗时，混进底色会发白，故蒙版要落在真实边缘内侧）

自检：输出「内部封闭洞」应为 0，并出三底对照图。
     **深底是照妖镜** —— 任何把产品误判成半透明的错，在浅底上看不出来，
     一放到深底就现形。只看浅底会漏掉。

用法：
    python tools/cutout_flat.py --probe --src _work/src_clean/color-a.jpg
    python tools/cutout_flat.py --src _work/src_clean/color-a.jpg --out images/cut-01.png
    python tools/cutout_flat.py --src <图> --out images/cut-01.png --check _shots/probe/cut-01.jpg
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
import cv2
import numpy as np
import scipy.ndimage as nd

BGS = [(247, 244, 238), (26, 24, 21), (182, 191, 196)]     # 生成り纸 / 深墨 / 中灰（BGR）
BG_NAMES = ['生成り纸', '深墨', '中灰']


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def base_color(bgr):
    f = bgr.astype(np.float32)
    ring = np.concatenate([f[:3].reshape(-1, 3), f[-3:].reshape(-1, 3),
                           f[:, :3].reshape(-1, 3), f[:, -3:].reshape(-1, 3)])
    return np.median(ring, axis=0)


def probe(path):
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit('cannot read ' + path)
    g = bgr.astype(np.float32).mean(axis=2)
    h, w = g.shape
    k = 0.10
    corner = np.concatenate([g[:int(h * k), :int(w * k)].ravel(),
                             g[:int(h * k), -int(w * k):].ravel(),
                             g[-int(h * k):, :int(w * k)].ravel(),
                             g[-int(h * k):, -int(w * k):].ravel()])
    bg = base_color(bgr)
    d = np.abs(bgr.astype(np.float32) - bg).max(axis=2)
    print('%s  %dx%d' % (os.path.basename(path), w, h))
    print('  底色 = %s' % [round(float(v), 1) for v in bg])
    print('  四角灰度的唯一值个数 = %d   标准差 = %.3f'
          % (len(np.unique(corner)), float(corner.std())))
    print('  色距分位 = %s'
          % {q: round(float(np.percentile(d, q)), 1) for q in (50, 75, 90, 99)})
    flat = len(np.unique(corner)) <= 2 and corner.std() < 0.5
    print('  判定 → %s' % ('(b) 型：纯色平底，用本脚本' if flat else
                           '(a) 型：底不平，优先试 tools/cutout.py'))
    return flat


def cutout(src, dst, tol_bg=0.5, presmooth=2.0, choke=1, feather=0.8, smooth=5):
    bgr = cv2.imread(src, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit('cannot read ' + src)
    h, w = bgr.shape[:2]
    f = bgr.astype(np.float32)
    bg = base_color(bgr)

    fs = cv2.GaussianBlur(f, (0, 0), presmooth) if presmooth > 0 else f
    cand = (np.abs(fs - bg).max(axis=2) <= tol_bg).astype(np.uint8)          # ②
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))  # ③

    n, lab = cv2.connectedComponents(cand, connectivity=4)                   # ④
    border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist()) | \
             set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    outside = np.isin(lab, list(border)) if border else np.zeros((h, w), bool)
    prod = (~outside).astype(np.uint8)

    n2, lab2 = cv2.connectedComponents(prod, connectivity=8)                 # ⑤
    dropped = 0
    if n2 > 1:
        sizes = [(lab2 == k).sum() for k in range(1, n2)]
        dropped = int(sum(sizes) - max(sizes))
        prod = (lab2 == (1 + int(np.argmax(sizes)))).astype(np.uint8)
    if smooth >= 3:
        prod = (cv2.medianBlur(prod * 255, smooth) > 127).astype(np.uint8)
    holes = int((nd.binary_fill_holes(prod) & (~prod.astype(bool))).sum())

    if choke > 0:                                                            # ⑦
        prod = cv2.erode(prod, np.ones((3, 3), np.uint8), iterations=choke)
    a = cv2.GaussianBlur(prod.astype(np.float32) * 255.0, (0, 0), feather) if feather > 0 \
        else prod.astype(np.float32) * 255.0
    a = np.clip(a, 0, 255)

    af = np.clip(a / 255.0, 0, 1)[..., None]
    edge = (af > 0.03) & (af < 0.985)
    safe = np.where(af < 0.12, 1.0, af)
    out = np.clip(np.where(edge, (f - (1.0 - safe) * bg) / safe, f), 0, 255)

    cv2.imwrite(dst, np.dstack([out.astype(np.uint8), a.astype(np.uint8)]))
    cover = float((a > 128).mean() * 100)
    return (w, h), bg, cover, dropped, holes


def main():
    src = _arg('--src')
    do_probe = '--probe' in sys.argv
    if not src:
        raise SystemExit('用法：python tools/cutout_flat.py --src <图> [--out <png>] '
                         '[--check <jpg>] [--probe]')
    if do_probe and not _arg('--out'):
        probe(src)
        return

    dst = _arg('--out')
    if not dst:
        raise SystemExit('缺 --out')
    size, bg, cover, dropped, holes = cutout(
        src, dst,
        tol_bg=float(_arg('--tol', 0.5)),
        presmooth=float(_arg('--presmooth', 2.0)),
        choke=int(_arg('--choke', 1)),
        feather=float(_arg('--feather', 0.8)),
        smooth=int(_arg('--smooth', 5)))
    print('%-28s %s  底色=%s  实心 %.1f%%  弃浮点 %d  内部封闭洞 %d'
          % (os.path.basename(dst), '%dx%d' % size,
             [round(float(v), 1) for v in bg], cover, dropped, holes))
    if holes:
        print('  ★ 内部封闭洞 > 0：柔边里有「恰好等于底色」的通道没被切断。')
        print('    处置：降 --tol（0.5→0.2）或加 --presmooth（2.0→3.0），不要调上限。')

    chk = _arg('--check')
    if chk:
        r = cv2.imread(dst, cv2.IMREAD_UNCHANGED)
        al = (r[:, :, 3:4] / 255.0).astype(np.float32)
        tiles = []
        for base in BGS:
            b = np.full_like(r[:, :, :3], base, np.uint8)
            tiles.append((r[:, :, :3] * al + b * (1 - al)).astype(np.uint8))
        os.makedirs(os.path.dirname(os.path.abspath(chk)), exist_ok=True)
        cv2.imwrite(chk, np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 92])
        print('  三底对照（%s）→ %s' % (' / '.join(BG_NAMES), chk))
        print('  ★ 必须看深墨那一格：浅底看不出半透明误判。')


if __name__ == '__main__':
    main()
