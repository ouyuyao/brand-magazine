# -*- coding: utf-8 -*-
"""submask.py —— 生成「主体遮挡掩膜」（供 layout 的 `occlude` 字段用）

它解决的是版式里的**层叠关系**，不是抠图：
    参考刊的封面常常把刊头艺术字放在模特**身后**——字被头部/身体挡住。
    这在 HTML 里不能靠 z-index 表达（出血照片是矩形的，压在上面的字永远看得见），
    要靠 CSS mask 把「主体所占的那一块」从字上挖掉。

掩膜规格（★约定，写死，不要反）
-------------------------------
    PNG，RGBA，尺寸 = 该页画布尺寸
    **不透明(α=255) = 保留**；**透明(α=0) = 挖掉**（即主体所占区域）

用法
----
    python tools/submask.py images/p01-hero.jpg images/p01-submask.png
        [--size 1280x1617]   # 输出尺寸，默认读原图；应与该页 canvas 一致
        [--feather 2]        # 边界羽化像素（默认 2，避免硬边）
        [--erode 0]          # 扩大挖洞范围：把主体掩膜外扩 N px（发丝/毛边用）
        [--shrink 0]         # 缩小挖洞范围：内缩 N px
        [--model u2net]      # rembg 模型
        [--tol 14]           # 平底连通域通道的底色容差
        [--force flat|rembg] # 强制走某条通道（默认自动挑可信的那条）
        [--check]            # 只报告掩膜质量（覆盖率 / 是否可信），不写文件

两条通道（与 subjectguard.py 同源）
----------------------------------
  rembg(u2net)        —— 人像/实拍图。本地已缓存模型，约 0.4s/张。
  flat 底色连通域      —— 白底/纯色平底产品图。rembg 在「白色产品压白色背景」上会失手。

**掩膜可信度 < 12% 会直接失败退出（退出码 1）**，不会静默写出一张没用的掩膜。
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBDIR = os.path.join(ROOT, "_work", "_submask")
MIN_CRED = 0.12


def argval(name, default=None):
    a = sys.argv[1:]
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith("--") else True
    return default


def flat_mask(a, tol):
    """与四角底色连通的区域 = 背景；其余 = 主体。"""
    h, w, _ = a.shape
    s = max(4, min(h, w) // 20)
    corners = np.concatenate([a[:s, :s].reshape(-1, 3), a[:s, -s:].reshape(-1, 3),
                              a[-s:, :s].reshape(-1, 3), a[-s:, -s:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    near = np.sqrt(((a - bg) ** 2).sum(axis=2)) < tol
    if near.mean() < 0.05 or near.mean() > 0.97:
        return None
    try:
        from scipy import ndimage
    except Exception:
        return None
    lab, n = ndimage.label(near)
    if n == 0:
        return None
    border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist()) | \
             set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    if not border:
        return None
    real_bg = np.isin(lab, list(border))
    subj = ~real_bg
    if subj.mean() < 0.03:
        return None
    return subj.astype(np.float32)


def rembg_mask(img, model):
    try:
        from rembg import remove, new_session
    except Exception as e:
        return None, "rembg 不可用（%s）" % type(e).__name__
    sess = new_session(model)
    a = np.asarray(remove(img.convert("RGB"), session=sess, only_mask=True)).astype(np.float32) / 255.0
    return a, "rembg:%s" % model


def dilate(m, r):
    if r < 1:
        return m
    r = int(r)
    k = 2 * r + 1
    pad = np.pad(m, ((r, r), (r, r)))
    out = np.zeros_like(m, dtype=np.float32)
    for i in range(k):
        for j in range(k):
            out = np.maximum(out, pad[i:i + m.shape[0], j:i + m.shape[1]])
    return out


def erode(m, r):
    if r < 1:
        return m
    r = int(r)
    k = 2 * r + 1
    pad = np.pad(m, ((r, r), (r, r)), constant_values=1.0)
    out = np.ones_like(m, dtype=np.float32)
    for i in range(k):
        for j in range(k):
            out = np.minimum(out, pad[i:i + m.shape[0], j:i + m.shape[1]])
    return out


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(pos) < 1:
        raise SystemExit(__doc__)
    src = pos[0] if os.path.isabs(pos[0]) else os.path.join(ROOT, pos[0])
    dst = pos[1] if len(pos) > 1 else None
    if dst and not os.path.isabs(dst):
        dst = os.path.join(ROOT, dst)

    size = argval("--size")
    feather = float(argval("--feather", 2))
    grow = int(argval("--erode", 0))
    shrink = int(argval("--shrink", 0))
    model = argval("--model", "u2net")
    tol = float(argval("--tol", 14))
    force = argval("--force", None)
    check_only = "--check" in sys.argv

    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.float32)

    cands = []
    if force in (None, "flat"):
        fm = flat_mask(a, tol)
        if fm is not None:
            cands.append(("flat底连通域", fm))
    if force in (None, "rembg"):
        rm, desc = rembg_mask(im, model)
        if rm is not None:
            cands.append((desc, rm))

    if not cands:
        print("✗ 两条通道都拿不到掩膜：%s" % src)
        return 1

    # 自动挑可信的：覆盖率 3%–85% 且不是整幅/全空
    best = None
    for desc, m in cands:
        cov = float((m > 0.5).mean())
        cred = 1.0 if 0.03 <= cov <= 0.85 else 0.5
        if best is None or cred > best[3]:
            best = (desc, m, cov, cred)
    desc, m, cov, cred = best

    if cred < 1.0 or cov < MIN_CRED:
        print("✗ 掩膜不可信：通道=%s 覆盖率=%.1f%%（要求 3%%–85%% 且 ≥ %.0f%%）"
              % (desc, cov * 100, MIN_CRED * 100))
        return 1

    if check_only:
        print("OK  通道=%s  主体覆盖 %.1f%%  尺寸 %dx%d" % (desc, cov * 100, im.width, im.height))
        return 0

    if not dst:
        raise SystemExit("✗ 缺少输出路径：python tools/submask.py <src> <dst.png>")

    if size:
        w, h = [int(v) for v in str(size).lower().split("x")]
    else:
        w, h = im.size

    m = (m > 0.5).astype(np.float32)
    if grow:
        m = dilate(m, grow)
    if shrink:
        m = erode(m, shrink)

    # 尺寸对齐（最近邻，保住硬边；羽化在后面做）
    mimg = Image.fromarray((m * 255).astype(np.uint8)).resize((w, h), Image.NEAREST)
    if feather > 0:
        mimg = mimg.filter(ImageFilter.GaussianBlur(feather))
    subj = np.asarray(mimg).astype(np.float32) / 255.0

    # ★ 掩膜 = 255 - 主体（不透明=保留，透明=挖掉）
    alpha = np.clip((1.0 - subj) * 255.0, 0, 255).astype(np.uint8)
    out = np.dstack([np.full_like(alpha, 255), np.full_like(alpha, 255),
                     np.full_like(alpha, 255), alpha])
    Image.fromarray(out, "RGBA").save(dst)
    print("OK  %s → %s" % (os.path.relpath(src, ROOT), os.path.relpath(dst, ROOT)))
    print("    通道=%s  主体覆盖 %.1f%%  输出 %dx%d  羽化 %.1fpx  erode %d  shrink %d"
          % (desc, cov * 100, w, h, feather, grow, shrink))
    print("    口径：不透明=保留，透明=挖掉（主体区域）→ 供 layout zone 的 \"occlude\" 字段引用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
