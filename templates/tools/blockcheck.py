# -*- coding: utf-8 -*-
"""
blockcheck.py —— 「照片块互相压」判据（产品图 / 细节图 / 色卡 / 白卡）

为什么单独一个脚本：overlap.py 查的是「浮层标签 ∩ 模特照」（会不会挡到脸），
这里查的是「照片块 ∩ 照片块」—— 产品图和细节图叠在一起、图压在说明上、
白卡里两张图挤成一坨。两类问题的判据不能用同一个阈值。

为什么要用「真实四角」而不是 getBoundingClientRect 的外接方框：
    版式里大量元素带 rotate（page02 的 .prodB 是 50°、.swatch 是 7°，
    page05 的 .p 各自 −8°~6°）。两个各转 ±8° 的矩形，外接方框可能大面积相交，
    实际着色像素却分得开 —— 拿方框判会假报。
    所以 labelrects.js 额外导出 quad（累积了自身与全部祖先旋转的四角），
    这里做凸四边形精确求交（Sutherland–Hodgman）。
    labelrects.js 里的 rot 字段、quad 字段就是为此加的。

判据：
    FAIL = 两个「照片块」的真实交叠面积 > --min（默认 2000px²），且两者不是父子
           （.c01 白卡包含 .p，属包含关系，不算互压）。
    退出码 = FAIL 数量，可直接串进交付前检查。

用法：
    python tools/blockcheck.py [--min 2000] [--page page02 page05] [--detail]
输出：
    终端清单；--sheet 时另出核对图 _shots/guard/_blocks.jpg
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
GUARD = os.path.join(SHOTS, "guard")


# ---------------------------------------------------------------- 几何

def signed_area(poly):
    """有向面积（shoelace）。y 轴向下，所以正 = 屏幕上的顺时针。"""
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def as_ccw(poly):
    """统一成 shoelace 有向面积为正的多边形。

    注意方向：y 轴向下，所以「有向面积为正」= 屏幕上的顺时针。
    _inside 的判据是 cross(b−a, p−a) >= 0，对「有向面积为正」的多边形才成立。
    这里曾经写成 signed_area < 0，结果把真相交算成了「分离」——
    page04 的 prodA∩prodC 明明压着 2 万多 px²，却被报成 0，
    反而在「外接框相交但真实分开」那一栏里露了马脚。判据本身也要被验证。
    """
    return poly if signed_area(poly) > 0 else list(reversed(poly))


def poly_area(poly):
    return abs(signed_area(poly)) if len(poly) >= 3 else 0.0


def _inside(p, a, b):
    """p 是否在有向边 a→b 的左侧（clipper 为 CCW 时等价于「在多边形内」）。"""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0


def _intersect(p1, p2, a, b):
    """线段 p1p2 与直线 ab 的交点。"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = a
    x4, y4 = b
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return p2
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def clip(subject, clipper):
    """Sutherland–Hodgman：凸多边形 subject 被凸 clipper 裁。"""
    clipper = as_ccw(clipper)
    out = as_ccw(subject)
    n = len(clipper)
    for i in range(n):
        if not out:
            break
        a, b = clipper[i], clipper[(i + 1) % n]
        inp = out
        out = []
        prev = inp[-1]
        for cur in inp:
            if _inside(cur, a, b):
                if not _inside(prev, a, b):
                    out.append(_intersect(prev, cur, a, b))
                out.append(cur)
            elif _inside(prev, a, b):
                out.append(_intersect(prev, cur, a, b))
            prev = cur
    return out


def bbox_of(quad):
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_inter(a, b):
    x0 = max(a["x"], b["x"])
    y0 = max(a["y"], b["y"])
    x1 = min(a["x"] + a["w"], b["x"] + b["w"])
    y1 = min(a["y"] + a["h"], b["y"] + b["h"])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float((x1 - x0) * (y1 - y0))


# ---------------------------------------------------------------- 内容包络

def load_alphabox():
    p = os.path.join(ROOT, "images", "_alphabox.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def content_quad(L, ab):
    """把元素的真实四角收缩到「图片内容区」。

    白底产品图四周有大量透明边（product-white.png 内容只占宽度 55%），
    所以判「图压图」必须用内容区，用元素框会一直假报。
    做法：内容区在元素本地坐标里是 [x0·W, y0·H]..[x1·W, y1·H]，
    四角 = 中心 + Rot(θ)·(本地角 − 中心)。
    """
    import math
    quad = L.get("quad")
    if not quad:
        return None
    src = L.get("src") or ""
    box = ab.get(src)
    if not box:
        return quad                      # 无法查内容（模特照等），退回元素框
    W = L.get("iw") or 0
    H = L.get("ih") or 0
    if not W or not H:
        return quad
    # quad[0] 与 quad[2] 是对角，中点是旋转中心
    cx = (quad[0][0] + quad[2][0]) / 2.0
    cy = (quad[0][1] + quad[2][1]) / 2.0
    th = math.radians(L.get("rot") or 0.0)
    ct, st = math.cos(th), math.sin(th)
    u0, v0 = box["x0"] * W, box["y0"] * H
    u1, v1 = box["x1"] * W, box["y1"] * H
    out = []
    for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
        du, dv = u - W / 2.0, v - H / 2.0
        out.append((cx + du * ct - dv * st, cy + du * st + dv * ct))
    return out


# ---------------------------------------------------------------- 主流程

def main():
    argv = sys.argv[1:]
    mn = 2000.0
    if "--min" in argv:
        mn = float(argv[argv.index("--min") + 1])
    detail = "--detail" in argv
    import _cli
    # ★用 _cli.positionals()：argv 里混着 `--min` 的值等，直接筛 "page" 前缀会被污染
    pages = [a for a in _cli.positionals() if a.startswith("page")]

    src = os.path.join(SHOTS, "_labels.json")
    if not os.path.exists(src):
        print("缺少 _shots/_labels.json —— 先跑 node tools/labelrects.js")
        return 2
    with open(src, encoding="utf-8") as fp:
        data = json.load(fp)
    ab = load_alphabox()
    if not ab:
        print("提示：images/_alphabox.json 不存在，改跑元素框（会有假报）。"
              "先执行 python tools/alphabox.py\n")

    fails = []
    warns = []
    hidden = []          # 方框会假报、但真实内容分得开的组合

    for name in sorted(data):
        if pages and name not in pages:
            continue
        labels = data[name].get("labels", [])
        blocks = [(i, L) for i, L in enumerate(labels) if L.get("kind") == "photo-block"]
        for a in range(len(blocks)):
            for b in range(a + 1, len(blocks)):
                ia, A = blocks[a]
                ib, B = blocks[b]
                if ia in B.get("anc", []) or ib in A.get("anc", []):
                    continue                       # 父子包含（白卡包产品图）
                qa, qb = content_quad(A, ab), content_quad(B, ab)
                if not qa or not qb:
                    continue
                area = poly_area(clip(qa, qb))
                bb = bbox_inter(A, B)
                row = (name, A, B, area, bb)
                if bb > mn * 1.5 and area <= mn:
                    hidden.append(row)             # 元素框说重叠、图片内容不重叠
                elif area > mn:
                    fails.append(row)
                elif area > mn / 4:
                    warns.append(row)

    def show(rows):
        for name, A, B, area, bb in rows:
            print("  %-7s %-26s ∩ %-26s  內容 %8.0fpx²   元素框 %8.0fpx²"
                  % (name, A["sel"][:26], B["sel"][:26], area, bb))

    if fails:
        print("FAIL：照片块互相壓（內容交疊 > %.0fpx²）—— %d 處" % (mn, len(fails)))
        show(fails)
    if warns:
        print("\nWARN：輕微交疊（%.0f–%.0fpx²）—— %d 處" % (mn / 4, mn, len(warns)))
        show(warns)
    if hidden and detail:
        print("\n（以下組合元素框相交、圖片內容分開 —— 這正是不能拿框當判據的原因）")
        show(hidden)
    if not fails and not warns:
        print("照片块无交叠（阈值 %.0fpx²）" % mn)

    print("\n合计：FAIL %d / WARN %d" % (len(fails), len(warns)))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
