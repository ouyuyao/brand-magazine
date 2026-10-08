# -*- coding: utf-8 -*-
"""_nest.py —— 把「绝对坐标的兄弟 zone」改写成「父子嵌套」（⑪ 卡内排版 的解药）

背景：`card_structure()`（refdims ⑪）判「空卡」的依据是
      `z.parent == panel.id`。layout 里如果把卡内的图/标题/说明写成
      **绝对坐标的兄弟 zone**，画面上完全正确，但机器读不到「卡里有排版」→
      报 `★空卡（无 parent 子元素）`。这是「没量 ≠ 没错」的又一例。

本脚本做纯几何换算（与 build.js `resolveParents` 相反方向）：
    rel = [(ax - px) / pw, (ay - py) / ph, aw / pw, ah / ph]

用法：
    python tools/_nest.py layout/02.json blob-1 n1-pic n1-brand n1-p
    （可多组： --group panel:child,child --group ...）

只改 `parent` 与 `box` 两个字段，其余原样；写回前先备份到 layout/_bak/。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm(b):
    return list(b) if isinstance(b, list) else [b["x"], b["y"], b["w"], b["h"]]


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    lay = args[0]
    path = lay if os.path.isabs(lay) else os.path.join(ROOT, lay)
    groups = []
    i = 1
    while i < len(args):
        if args[i] == "--group":
            pid, kids = args[i + 1].split(":")
            groups.append((pid, [k for k in kids.split(",") if k]))
            i += 2
        else:
            pid = args[i]
            kids = args[i + 1:]
            groups.append((pid, kids))
            break
    with open(path, encoding="utf-8") as f:
        L = json.load(f)
    by = {z["id"]: z for z in L["zones"]}
    bak = os.path.join(ROOT, "layout", "_bak")
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(path, os.path.join(bak, os.path.basename(path)))

    for pid, kids in groups:
        p = by.get(pid)
        if not p:
            raise SystemExit("✗ 没有 panel %s" % pid)
        pb = norm(p["box"])
        pw = pb[2] if isinstance(p["box"], list) else pb[2]
        ph = pb[3] if isinstance(p["box"], list) else pb[3]
        # 父框若设了 pad/border，子坐标要从 padding box 起算 → 拒绝，免得静默偏移
        ps = p.setdefault("style", {})
        if ps.get("pad") is not None or ps.get("border"):
            raise SystemExit("✗ 父框 %s 设了 pad/border，子坐标会偏移；先去掉再嵌套" % pid)
        for k in kids:
            z = by.get(k)
            if not z:
                raise SystemExit("✗ 没有子 zone %s" % k)
            zb = norm(z["box"])
            rel = [round((zb[0] - pb[0]) / pw, 4), round((zb[1] - pb[1]) / ph, 4),
                   round(zb[2] / pw, 4), round(zb[3] / ph, 4)]
            print("  %-12s -> parent=%-8s abs%s  rel%s" % (k, pid, [round(v, 4) for v in zb], rel))
            z["parent"] = pid
            z["box"] = rel
    with open(path, "w", encoding="utf-8") as f:
        json.dump(L, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("✓ 写回 %s（备份 layout/_bak/%s）" % (lay, os.path.basename(path)))


if __name__ == "__main__":
    main()
