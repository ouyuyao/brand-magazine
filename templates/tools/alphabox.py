# -*- coding: utf-8 -*-
"""
alphabox.py —— 扫出每张产品图的「真实内容区」，写 images/_alphabox.json

为什么需要：
    白底产品图（.cutout）四周留了大量透明边。实测内容占比差很多：
        product-white.png  内容只占宽度 55%
        detail-mesh.png    内容占宽度 55%
        bra-black.png      内容占宽度 76%
    所以「元素框相交」根本不能代表「两张图叠在一起」——
    page04 的 .prodA 与 .prodC 元素框交 2.6 万 px²，实际图各在框的一侧，
    完全分开。拿框当判据会一直假报，判据就没用了。

输出格式（比例，0..1，相对图片原始尺寸）：
    {
      "bra-black.png": {"x0": 0.133, "y0": 0.044, "x1": 0.895, "y1": 0.915},
      ...
    }

图片改动后要重跑本脚本（tools/blockcheck.py 会提示）。

用法：python tools/alphabox.py [--alpha 8]
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(ROOT, "images")
OUT = os.path.join(IMAGES, "_alphabox.json")


def main():
    thr = 8
    if "--alpha" in sys.argv:
        thr = int(sys.argv[sys.argv.index("--alpha") + 1])

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("需要 pillow 与 numpy")
        return 2

    boxes = {}
    files = sorted(f for f in os.listdir(IMAGES) if f.lower().endswith(".png"))
    for f in files:
        p = os.path.join(IMAGES, f)
        try:
            im = Image.open(p)
        except Exception as e:
            print("  跳过 %s（%s）" % (f, e))
            continue
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        a = np.array(im.split()[-1])
        mask = a > thr
        if not mask.any():
            print("  %-24s 全透明，跳过" % f)
            continue
        ys, xs = np.where(mask)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        boxes[f] = {
            "x0": round(x0 / im.width, 4), "y0": round(y0 / im.height, 4),
            "x1": round((x1 + 1) / im.width, 4), "y1": round((y1 + 1) / im.height, 4),
            "_px": [x0, y0, x1, y1], "_size": [im.width, im.height],
        }
        print("  %-24s %4d×%-5d 内容 %4d..%-5d × %4d..%-5d  占 %.0f%%×%.0f%%"
              % (f, im.width, im.height, x0, x1, y0, y1,
                 100 * (x1 - x0 + 1) / im.width, 100 * (y1 - y0 + 1) / im.height))

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(boxes, fp, ensure_ascii=False, indent=1)
    print("\n共 %d 张 -> images/_alphabox.json" % len(boxes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
