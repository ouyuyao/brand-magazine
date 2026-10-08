# -*- coding: utf-8 -*-
"""edgefit —— 参考图结构线 ↔ layout 边框 的命中率（容差默认 ±1.5% 画布）。

reffit.py 的 plan 分量走的是「区块示意图的空白谷」，量不到「相邻区块的分界线」
（参考图里大量结构线是照片/色块的**边**，不是空白缝），所以对这套书页偏低。
这里直接把参考图的每条结构线拿去问 layout 的边框集合：命中率是「有没有按参考图
分区」最直白的读数。出血元素（treat=bleed）不参与——它的边界本就不受约束。
"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 与 reffit 同目录
from PIL import Image
import reffit as RF

# 用法：在项目根跑 —— python tools/edgefit.py [容差，默认 0.015]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.015
tot = hit = 0
# ★版式坐标统一走 _lay（读 build 期折算过 parent 的 layout/_resolved.json）：
#   直读 layout 原文时，白卡内的框会按「相对父框」的小坐标参与命中统计，
#   结果是「参考线明明排了却判未命中」——正是最容易被误读成"没按参考图做"的那种假阴性。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lay
_zp = _lay.load_zone_pages(ROOT)
print(f"{'page':7s} {'refY':>4s} {'hitY':>5s} {'refX':>4s} {'hitX':>5s}   未对上的线（及判定）")
for i in range(1, 10):
    pid = f"page{i:02d}"
    L = {'zones': (_zp.get(pid) or {}).get('zones', [])}
    if not L['zones']:
        continue
    ref = Image.open(os.path.join(ROOT, 'assets/ref', f"p{i:02d}.jpg")).convert('RGB')
    W0, H0 = ref.size
    sc = 900 / float(max(W0, H0))
    ry, rx = RF.lines_of(ref.resize((int(W0 * sc), int(H0 * sc)), RF.LANCZOS).convert('L'))
    ey, ex = set(), set()
    for z in L.get('zones', []):
        b = z.get('box')
        if not isinstance(b, list) or len(b) != 4: continue
        x, y, w, h = b
        if (z.get('kind') or 'text') == 'image' and (z.get('style') or {}).get('treat') == 'bleed': continue
        if w * h < 0.004: continue
        ey |= {round(y, 4), round(y + h, 4)}; ex |= {round(x, 4), round(x + w, 4)}
    def h_(lines, edges):
        m = [v for v in lines if not any(abs(v - e) <= TOL for e in edges)]
        return len(lines) - len(m), m
    a, my = h_(ry, ey); b, mx = h_(rx, ex)
    miss = [f"y{v:.3f}" for v in my] + [f"x{v:.3f}" for v in mx]
    print(f"{pid:7s} {len(ry):4d} {a:5d} {len(rx):4d} {b:5d}   {' '.join(miss) if miss else '—'}")
    tot += len(ry) + len(rx); hit += a + b
print(f"\n合计 参考结构线 {tot} 条，layout 边框命中 {hit} 条 → {hit/tot:.1%}（容差 ±{TOL:.1%} 画布）")
