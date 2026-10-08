# -*- coding: utf-8 -*-
"""densitycheck.py —— 「画面密度 / 留白分布」判据（★用户第 5 点的机器化身）

它存在的理由
------------
用户第一句话是「文字大小太小了……使画面显得很空」。
在它之前，这条反馈在这套流程里**无法被证伪**：
成品出图 → 八套判据全绿 → 交付，没人量过「画面哪里是空的」。
于是「空」只能靠人眼看出来，而人眼只在被指出来之后才看见。

它把「空」变成可复现的数字：
  把参考图与成品各切 3×3（可调 4×4）宫格，逐格算局部梯度能量占比（见 tools/_dens.py），
  然后只报两类**单向**信号（参考忙、成品闲）：
    · 空档格 dead cell：参考 ≥ --ref-hot 而成品 ≤ --dead  —— 参考刊这里塞了东西，你这块什么都没有
    · 偏空格 gap  cell：参考 − 成品 > --gap

为什么是单向
------------
成品比参考**密**不算问题（我们是自己的产品目录，不是复刻同一本刊）。
只有「参考有、你没有」才是「显得空」。反向报会制造大量噪声，把人训练成无视告警。

用法
----
    python tools/densitycheck.py                     # 全部页，3×3
    python tools/densitycheck.py page01              # 指定页
    python tools/densitycheck.py --grid 4            # 4×4 更细
    python tools/densitycheck.py --gap 12 --dead 2   # 收紧/放宽
    python tools/densitycheck.py --json              # 只出 JSON
    python tools/densitycheck.py --plate             # 另出对照热力图

退出码：存在「空档格」→ 1；只有「偏空格」→ 0（告警）；全清 → 0。

★它是**告警级**判据，不是硬门禁：参考刊某格是「模特裙摆的褶皱」，你这里本来就
  没有那条裙摆——这类格不该判死。判死的是「整格近乎零墨迹」而参考格明显有内容。
  所以默认 --dead 2 卡得很死，只有真正的空地才会命中。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dens  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "assets", "ref")
SHOTS = os.path.join(ROOT, "_shots")
REPORT = os.path.join(SHOTS, "report")

# 版式（折算过 parent 的画布坐标）—— 用来算「这一格有没有被元素占据」。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lay  # noqa: E402

ZP = _lay.load_zone_pages(ROOT)


def argval(name, default=None):
    a = sys.argv[1:]
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith("--") else True
    return default


def pages():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _lay
    zp = _lay.load_zone_pages(ROOT)
    lay = os.path.join(ROOT, "layout")
    out = []
    for f in sorted(os.listdir(lay)):
        if not f.endswith(".json") or f.startswith("_") or f.startswith("^_"):
            continue
        d = "".join(ch for ch in f if ch.isdigit())
        pid = "page" + (d.zfill(2) if d else "00")
        rec = zp.get(pid)
        if rec:
            out.append((pid, rec.get("ref")))
    return out


def heat(a, b, path, title):
    """把参考/成品/差值三张宫格画成一张图，一眼看哪格空了。"""
    rows, cols = len(a), len(a[0])
    cw = ch = 58
    W = cols * cw * 3 + 80
    H = rows * ch + 40
    im = Image.new("RGB", (W, H), (246, 245, 243))
    dr = ImageDraw.Draw(im)
    for k, (lab, G) in enumerate((("参考", a), ("成品", b),
                                  ("差值(参考−成品)", [[a[r][c] - b[r][c] for c in range(cols)] for r in range(rows)]))):
        x0 = 20 + k * (cols * cw + 20)
        dr.text((x0, 8), lab, fill=(20, 20, 20))
        for r in range(rows):
            for c in range(cols):
                v = G[r][c]
                if k == 2:
                    t = max(0.0, v) / 25.0
                    col = (int(255), int(255 - min(1, t) * 200), int(255 - min(1, t) * 200))
                else:
                    t = min(1.0, v / 25.0)
                    col = (int(255 - t * 200), int(255 - t * 170), int(255 - t * 150))
                dr.rectangle([x0 + c * cw, 24 + r * ch, x0 + (c + 1) * cw - 3, 24 + (r + 1) * ch - 3], fill=col)
                dr.text((x0 + c * cw + 4, 28 + r * ch + 4), "%.0f" % v, fill=(20, 20, 20))
    dr.text((20, H - 12), title, fill=(60, 60, 60))
    im.save(path)
    return path


def main():
    only = next((a for a in sys.argv[1:] if a.startswith("page")), None)
    grid = int(argval("--grid", 3))
    gap = float(argval("--gap", 10))
    dead = float(argval("--dead", 2))
    ref_hot = float(argval("--ref-hot", 10))
    jsononly = "--json" in sys.argv
    plate = "--plate" in sys.argv
    cover_min = float(argval("--cover", 10))
    os.makedirs(REPORT, exist_ok=True)

    recs, dead_pages, gap_pages, skipped, flat_pages = [], [], [], [], []
    for pid, ref in pages():
        if only and pid != only:
            continue
        rp = os.path.join(REF, ref) if ref else None
        sp = os.path.join(SHOTS, pid + ".png")
        if not (rp and os.path.exists(rp)):
            skipped.append((pid, "参考图缺失")); continue
        if not os.path.exists(sp):
            skipped.append((pid, "成品未出图（先跑 node tools/shoot.js）")); continue
        R = _dens.grid_density(rp, grid, grid)
        S = _dens.grid_density(sp, grid, grid)
        # ★第二条证据：这格有没有被影像元素占据（见 _dens.zone_coverage 的 docstring）
        zp = ZP.get(pid) or {}
        cov = _dens.zone_coverage(zp.get("zones"), zp.get("canvas"), grid, grid)
        C = _dens.compare(R, S, gap, dead, ref_hot, cover=cov, cover_min=cover_min)
        recs.append({"page": pid, "ref": ref, "R": R, "S": S, "C": C})
        if C["dead_cells"]:
            dead_pages.append(pid)
        elif C["gap_cells"]:
            gap_pages.append(pid)
        # ★素材平坦格要**独立**记（与死格并存）：早期写成 elif 分支，
        #   结果一页只要有一个真死格，它的其余「素材平坦」格就全从报告里消失 ——
        #   报告看着干净，其实那一页的平坦格一个都没列。
        if C["flat_cells"]:
            flat_pages.append(pid)

    if jsononly:
        print(json.dumps({"grid": grid, "pages": recs}, ensure_ascii=False, indent=1))
        return 1 if dead_pages else 0

    print("画面密度判据（%d×%d 宫格，参考 ≥%.0f 且成品 ≤%.0f 记为「空档格」）" % (grid, grid, ref_hot, dead))
    print("─" * 96)
    print("  %-8s %-8s %-8s %s" % ("页", "参考均", "成品均", "最空的格（参考 → 成品，差）"))
    for r in recs:
        C = r["C"]
        worst = sorted(C["dead_cells"] + C["flat_cells"] + C["gap_cells"], key=lambda x: -x["d"])[:3]
        w = "  ".join("[%d,%d] %.1f→%.1f (%+.1f)%s" % (x["cell"][0], x["cell"][1], x["ref"], x["shot"], x["d"],
                                                      "素材平坦" if x in C["flat_cells"] else "")
                       for x in worst)
        if not w:
            w = "— 逐格都在参考的密度上"
        print("  %-8s %-8.2f %-8.2f %s" % (r["page"], C["ref_mean"], C["shot_mean"], w))
    print("─" * 96)
    if dead_pages:
        print("★ 存在**空档格**（参考刊该格塞了内容，成品该格既无内容也无元素）：%s" % "、".join(dead_pages))
        print("  处理方向：把该格所在的元素**放大 / 下移到该格**，或补一个该格该有的元素（角标、罫线、注记）。")
        print("  不要用「加一团装饰」填 —— 填的东西必须是参考刊那一格真的有的东西。")
    else:
        print("OK  无空档格（参考有内容而成品无元素占据的格）。")
    if flat_pages:
        print("· **素材平坦格**（告警级，不阻断）：%s" % "、".join(flat_pages))
        print("  含义：该格已被影像元素占满，但素材是**低对比商品图**（梯度能量天然低）——")
        print("  不是排版漏了东西。真要让该格「忙」起来只能换素材，不能靠加图案。")
    if gap_pages:
        print("· 偏空格（告警级，不阻断）：%s" % "、".join(gap_pages))
    for pid, why in skipped:
        print("· 跳过 %s：%s" % (pid, why))

    out = os.path.join(REPORT, "density.json")
    with open(out, "w", encoding="utf-8") as fp:
        json.dump({"_doc": "画面密度台账。dead=参考有成品无（且无元素占据）的格；"
                           "flat=素材平坦格（有元素占据但低对比）；gap=偏空格。",
                   "grid": grid, "gap": gap, "dead": dead, "ref_hot": ref_hot,
                   "cover_min": cover_min,
                   "pages": [{"page": r["page"], "ref_grid": r["R"]["grid"], "shot_grid": r["S"]["grid"],
                              "cover_grid": r["C"]["cover"],
                              "dead": r["C"]["dead_cells"], "flat": r["C"]["flat_cells"],
                              "gap": r["C"]["gap_cells"],
                              "ref_mean": r["C"]["ref_mean"], "shot_mean": r["C"]["shot_mean"]} for r in recs]},
                  fp, ensure_ascii=False, indent=1)
    print("台账 -> %s" % out)

    if plate:
        for r in recs:
            p = os.path.join(REPORT, "%s_density.png" % r["page"])
            heat(r["R"]["grid"], r["S"]["grid"], p, "%s  参考/成品/差值" % r["page"])
        print("对照热力图 -> %s/*_density.png" % REPORT)

    return 1 if dead_pages else 0


if __name__ == "__main__":
    sys.exit(main())
