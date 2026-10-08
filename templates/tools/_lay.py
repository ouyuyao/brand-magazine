# -*- coding: utf-8 -*-
"""_lay.py —— 版式读取（**解析后坐标**）

为什么需要这一层
----------------
layout/NN.json 里带 "parent" 的子 zone，其 box 是**相对父框**的归一化坐标
（白卡里的「角标 / 款式图 / 编号 / 说明」就是这么写的）。
build.js 在编译期把它折算成画布坐标，并导出 layout/_resolved.json。

判据脚本一律读这一份。直接读原文会把「卡里的第 4 行」当成「画布上的第 4 行」，
从而算出**假的文字互压 / 假的模块遮挡 / 假的结构线缺失** —— 数字看着像真问题，最难查。

用法
----
    import sys, os
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from _lay import load_zone_pages, box_px

    pages = load_zone_pages(ROOT)          # {"page01": {"canvas": (1280,1617), "zones": [...]}}
    x, y, w, h = box_px(z["box"], 1280, 1617)

回落：找不到 _resolved.json 时读 layout 原文（无 parent 时两者等价），并打印一次提醒。
"""
from __future__ import annotations

import json
import os
import re
import sys

_warned = [False]


def _pid_of(name, ident):
    s = str(ident or name)
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    n = m.group(1)
    return "page" + (n if len(n) > 1 else "0" + n)


def load_zone_pages(root):
    """→ {pid: {"canvas": (w,h), "ref": str|None, "zones": [zone, ...]}}（坐标已是画布坐标）"""
    p = os.path.join(root, "layout", "_resolved.json")
    out = {}
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        for pid, rec in d.items():
            c = rec.get("canvas") or [1366, 1748]
            out[pid] = {"canvas": (c[0], c[1]), "ref": rec.get("ref"),
                        "zones": rec.get("zones", [])}
        return out
    if not _warned[0]:
        sys.stderr.write("⚠ 未找到 layout/_resolved.json —— 回落读 layout 原文"
                         "（带 parent 的页面会算出假坐标）。跑一次 node build.js 即可生成。\n")
        _warned[0] = True
    lay = os.path.join(root, "layout")
    if not os.path.isdir(lay):
        return out
    for f in sorted(os.listdir(lay)):
        if not f.endswith(".json") or f.startswith("_"):
            continue
        d = json.load(open(os.path.join(lay, f), encoding="utf-8"))
        pid = _pid_of(f, d.get("id"))
        if not pid:
            continue
        c = d.get("canvas") or {}
        out[pid] = {"canvas": (c.get("w", 1366), c.get("h", 1748)), "ref": d.get("ref"),
                    "zones": d.get("zones", [])}
    return out


def boxes_of(pages, pid):
    """→ {zone_id: (x, y, w, h)} 画布像素"""
    rec = pages.get(pid)
    if not rec:
        return {}
    W, H = rec["canvas"]
    return {z["id"]: box_px(z["box"], W, H) for z in rec["zones"] if z.get("id") and z.get("box")}


def box_px(b, W, H):
    if isinstance(b, (list, tuple)):
        return (b[0] * W, b[1] * H, b[2] * W, b[3] * H)
    return (b["x"], b["y"], b["w"], b["h"])
