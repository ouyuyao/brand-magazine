# -*- coding: utf-8 -*-
"""refdims.py —— 参考图解析「十二维台账」生成器 / 核对器

它存在的理由（第一版）
----------------------
用户点名的八个维度（颜色色调 / 文字排版 / 文字字体 / 文字颜色 / 标签元素 /
遮盖块 / 模特动作 / 重叠编排），此前只有「文字排版」被真量过（refscan 投影 + edgefit）。
其余七项**没有任何一步会报错**——没量就是没量，产物照样生成。
结果就是：成品看起来「没按参考图做」，而流程一路绿灯。

它存在的理由（第二版 · 本次扩维）
--------------------------------
八维跑起来之后，用户对着成品逐条点出**七处不符**，八套判据当时**全部退出码 0**。
复盘发现：那七点里有四点落在八维**根本没覆盖**的地方 ——

  第 1 点 背景色（参考天蓝 / 成品米灰）→ ①只量「中位亮度/饱和/亮部占比」，**不量四角基色**
  第 3 点 号码＋日文＋价格＋「円」    → ②只量「带缝 + 分栏」，**不量块内纵向结构，也不查货币写法**
  第 4 点 粉色弧排大字              → ④只统计字色令牌，**不记排列方式（弧/斜/竖）与弧度**
  第 6 点 白卡里的排版              → ⑥只登记「有个白卡」，**不登记卡内结构**
  第 7 点 模特居中偏左              → ⑦只登记「AI 生图提示词」，**不量主体位置**
  第 2 点 刊头被头遮                → **整条「遮挡关系」维度不存在**
  第 5 点 画面显得空                → **整条「画面密度」维度不存在**

所以本版把 8 维扩成 12 维：① 升级（+四角基色）、② 升级（+块内结构 +货币写法）、
④ 升级（+对比角色）、⑦ 升级（+主体位置），并新增 ⑨排列方式 / ⑩遮挡关系 /
⑪卡内排版 / ⑫画面密度。

分工
----
    能自动算的（①②④⑤⑥⑧⑨⑩⑪⑫）→ 直接给出参考侧与成品侧的实测值；
    不能自动算的（③字体真身 / ⑦参考侧主体位置）→ 输出「该去核对什么、去哪个文件核对」，
    并在台账里留 `manual` 字段。**留空即视为未核对**，`--check` 会点名。

用法
----
    python tools/refdims.py                  # 全部页，打印十二维摘要
    python tools/refdims.py page01           # 指定页
    python tools/refdims.py --write          # 写 _shots/report/refdims.json
    python tools/refdims.py --check          # 只做完整性核对（硬缺失 → 退出码 1）
    python tools/refdims.py --plate          # 另出参考/成品色板对照图
    python tools/refdims.py --bg             # 只打背景基色对照（第 1 点的判据）
    python tools/refdims.py --grid           # 出 ±0.05 刻度网格的参考/成品并排读图（第 7 点用）

人工读数落在 `assets/ref/_readings.json`（**机器不覆盖**），`--write` 时合并进台账 `ref_readings`。
`--write` 重写的是 `_shots/report/refdims.json` —— 读数若写在那里会被抹掉，所以必须分开存。

退出码：--check 模式下有硬缺失 → 1；否则 0。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dens  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "assets", "ref")
SCAN = os.path.join(REF, "_scan")
SHOTS = os.path.join(ROOT, "_shots")
REPORT = os.path.join(SHOTS, "report")

DIMS = ["color", "typo", "font", "inkcolor", "tags", "masks",
        "pose", "overlap", "arrange", "occlusion", "card", "density"]
DIM_CN = {
    "color": "① 颜色 / 色调（含四角基色）",
    "typo": "② 文字排版（结构线 + 块内结构 + 货币写法）",
    "font": "③ 文字字体",
    "inkcolor": "④ 文字颜色（含对比角色）",
    "tags": "⑤ 标签元素",
    "masks": "⑥ 遮盖块",
    "pose": "⑦ 模特动作 / 主体位置",
    "overlap": "⑧ 重叠编排（小模块不压主体）",
    "arrange": "⑨ 排列方式（横/竖/斜/弧 + 弧度）",
    "occlusion": "⑩ 遮挡关系（谁被主体挡住）",
    "card": "⑪ 卡内排版（角标/标题/重复行/罫线）",
    "density": "⑫ 画面密度（逐格留白，见 densitycheck.py）",
}
MANUAL_DIMS = ["font", "inkcolor", "tags", "masks", "pose", "overlap",
               "arrange", "occlusion", "card"]

# ★人工读数的**键名校验表**。为什么需要：
#   如果人把 "头心x" 写成 "头心X"、把 "触边率" 写成 "触边"，判据会**静默读不到** →
#   又退回「未核对」，而画面上一切正常、没有任何报错。
#   这正是本项目反复踩的那类坑（没量 ≠ 没错），所以键名必须被机器点名。
#   `需` = 判据依赖的键（缺了该维度算未完成）；其余为记录性键（缺了只提示）。
READING_TYPES = {"str": str, "num": (int, float), "list": list, "map": dict}

# ★页类型：参考图是**混编**的（封面人像、内页静物拼贴、三格美人图…），
#   而第 ⑦ 维（头心 x / 触边率）只对「单一主体」的页有定义。
#   机器能判的自动判（`classify_page`）；合成页上机器判不准
#   （实测 p02 静物拼贴被 rembg 判成跨度 0.95 的一整块）→ 允许**人工声明**。
#   声明了 → 该页不再要求填「头心 x」，也不报「未核对」硬缺失。
PAGE_KINDS = {
    "portrait": "单一主体（人像封面 / 单品特写）",
    "multi": "多主体（三格美人图 / 品类拼贴）→ 头心 x 无定义",
    "still": "无主体（静物陈列 / 纯文字页）→ 头心 x 无定义",
}

# 「无主体」这一类在本文件里的全部写法（none 为兼容早期读法）
NA_KINDS = ("still", "none")

# ★「成品页整页抠像」的**洞占比下限** —— 那是兜底通道，实测经常漏检：
#   page05 洞 0.6%（整块漏掉人）、page08 洞 4%（只抠到一角，却照样驱动了
#   「触边 R 参考 25%→成品 0%」这条判据）。**假读数驱动的假判据比没有判据更坏**：
#   它会让人去改一个其实没问题的地方。低于此值一律视为「没抠出来」，
#   宁可如实报无读数。正解是产出时生成掩膜（见 `shot_subject_mask` docstring）。
SHOT_PAGE_MIN = 8.0

READING_SCHEMA = {
    "pageKind": {"需": {"kind": "str"}, "可": {"依据": "str", "备注": "str"}},
    "color": {"需": {"参考刊背景基色": "str"}, "可": {"色相轴": "str", "备注": "str"}},
    "typo": {"需": {"参考刊号码块": "str"},
             "可": {"货币写法": "str", "结构线": "str", "备注": "str"}},
    "font": {"需": {"刊头": "str", "号码块": "str", "主文案": "str"},
             "可": {"小字": "str", "替代体": "str", "备注": "str"}},
    "inkcolor": {"需": {"对比角色": "str"},
                 "可": {"弧排字色": "str", "上下文案字色": "str", "目标比值": "num", "备注": "str"}},
    "tags": {"需": {"参考刊标签": "list"},
             "可": {"形状": "str", "压在什么上": "str", "备注": "str"}},
    "masks": {"需": {"参考刊遮盖块": "list"},
              "可": {"位置": "str", "备注": "str"}},
    "pose": {"需": {"头心x": "num", "触边率": "map"},
             "可": {"景别": "str", "朝向": "str", "视线": "str", "手势": "str",
                    "左侧净空": "num", "留白侧": "str", "依据": "str", "读图工具": "str", "备注": "str"}},
    "overlap": {"需": {"参考刊互压关系": "list"}, "可": {"备注": "str"}},
    "arrange": {"需": {"弧排实测": "str"}, "可": {"横排": "str", "整体倾角": "str", "备注": "str"}},
    "occlusion": {"需": {"被遮元素": "str"}, "可": {"谁压谁": "list", "备注": "str"}},
    "card": {"需": {"参考刊卡内结构": "str"},
             "可": {"列数": "num", "行数": "num", "角标": "str", "备注": "str"}},
    "density": {"需": {}, "可": {"参考刊留白区": "list", "备注": "str"}},
}
EDGES = ("L", "R", "T", "B")


def effective_schema(dim, dims):
    """★按**页类型**调整该维度的必填项 —— 「动态匹配」落到读数校验上的那一环。

    `pose` 的必填键（头心 x / 触边率）**只对「单一主体」的页成立**：
      · 静物拼贴页没有头 →「头心 x」是个不存在的量
      · 三格美人图有三个头 →「头心 x」没有唯一值
    对这两类页强行必填，用户只有两条路：**编一个数糊过去**，
    或者被一条永远清不掉的硬缺失卡住。两条都不是「核对」。

    所以：人工在 `_readings.json` 里声明了 `pageKind.kind` 之后，
    该页 `pose` 的必填降级为空（触边率仍可登记，作为参考信息）。
    没声明的页保持原样 —— 没声明就是没核对，不该被悄悄放过。
    """
    sch = READING_SCHEMA[dim]
    if dim != "pose":
        return sch
    k = ((dims.get("pageKind") or {}).get("kind") or "").strip()
    if k in ("still", "multi"):
        merged = dict(sch["需"])
        merged.update(sch["可"])
        return {"需": {}, "可": merged, "na": True, "kind": k}
    return sch


def check_readings(readings):
    """校验 `_readings.json` 的键名与类型。返回 (问题列表, 已核对页数)。

    问题分两类，都要点名：
      · 未知键 / 类型不符  → 写的人以为填了，机器其实读不到（静默失败）
      · 缺「需」键         → 该维度判据依赖的读数没填
    ★「需」键不是固定的：`effective_schema` 会按该页声明的**页类型**调整
      （静物页 / 多主体页不要求「头心 x」）。
    """
    probs = []
    pages_ok = 0
    for pid, dims in sorted(readings.items()):
        if not isinstance(dims, dict):
            probs.append("%s：该页读数不是对象" % pid)
            continue
        bad = 0
        pk = (dims.get("pageKind") or {}).get("kind")
        if pk and pk not in PAGE_KINDS:
            probs.append("%s.pageKind.kind=%s 未知（可用：%s）" % (pid, pk, "/".join(PAGE_KINDS)))
            bad += 1
        for dim, payload in dims.items():
            if dim not in READING_SCHEMA:
                probs.append("%s.%s：未知维度（可用：%s）" % (pid, dim, "/".join(READING_SCHEMA)))
                bad += 1
                continue
            if not isinstance(payload, dict):
                probs.append("%s.%s：应是对象" % (pid, dim))
                bad += 1
                continue
            sch = effective_schema(dim, dims)
            allowed = set(sch["需"]) | set(sch["可"])
            for k, v in payload.items():
                if k not in allowed:
                    probs.append("%s.%s.%s：未知键（易静默读不到）→ 可用 %s"
                                 % (pid, dim, k, "/".join(sorted(allowed))))
                    bad += 1
                    continue
                want = READING_TYPES[sch["需"].get(k) or sch["可"].get(k)]
                if not isinstance(v, want):
                    probs.append("%s.%s.%s：类型不符（要 %s，实为 %s）"
                                 % (pid, dim, k, (sch["需"].get(k) or sch["可"].get(k)),
                                    type(v).__name__))
                    bad += 1
            for k in sch["需"]:
                if k not in payload:
                    probs.append("%s.%s：缺「%s」（判据依赖它，缺了等于未核对）" % (pid, dim, k))
                    bad += 1
            if dim == "pose" and not sch.get("na"):
                if isinstance(payload.get("触边率"), dict):
                    for e in EDGES:
                        if e not in payload["触边率"]:
                            probs.append("%s.pose.触边率：缺边 %s" % (pid, e))
                            bad += 1
                hx = payload.get("头心x")
                if isinstance(hx, (int, float)) and not (0.0 <= hx <= 1.0):
                    probs.append("%s.pose.头心x=%.3f 越界（应是 0–1 的归一化 x）" % (pid, hx))
                    bad += 1
        if not bad:
            pages_ok += 1
    return probs, pages_ok

# 压照片的浅色令牌：这类字一旦落在人像上就必须有 shadow（否则看不见）
PHOTO_INK = ("paper", "paper-warm", "paper-cream", "paper-grey")


def _jsafe(o):
    """json.dump 的兜底：numpy 标量/数组一律转成 Python 原生类型。
    不写它会踩 `TypeError: Object of type float32 is not JSON serializable` ——
    `round(np.float32(x), 1)` 返回的仍是 np.float32。"""
    if isinstance(o, (np.floating,)):
        return round(float(o), 6)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def load_readings():
    """★人工读数的**持久层**：`assets/ref/_readings.json`（人写的，机器不覆盖）。

    为什么必须有它：`refdims.py --write` 重写整份 `_shots/report/refdims.json`，
    如果人工读数写在那里，下一次 --write 就被抹掉 —— 于是「manual 留空即未核对」
    这条纪律根本没有落地的位置，台账永远是空的，永远「看起来没核对」。
    所以把人工读数放在**另一个文件**里，`--write` 时合并进 ledger 的每个维度（键 `ref_readings`）。

    结构（按页 → 维度 → 任意字段）：
      { "page01": { "occlusion": {"被遮元素": "刊头「ら/た」两字被头顶遮掉约七成"},
                    "arrange":   {"弧排实测": "扫角约 56°，整体倾角约 -36°"},
                    "tags":      {"参考刊本页标签": "2 个：右上黑气泡角标、左侧期号块"} } }
    """
    p = os.path.join(REF, "_readings.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fp:
            d = json.load(fp)
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except Exception as e:
        print("⚠ assets/ref/_readings.json 读不动：%s" % e)
        return {}


def argval(name, default=None):
    a = sys.argv[1:]
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith("--") else True
    return default


def pages():
    """逐页版式 —— **坐标已折算 parent**（读 layout/_resolved.json，见 tools/_lay.py）。
    直读 layout/NN.json 时，白卡等高层的子元素会保留「相对父框」的小坐标，
    本脚本的 ⑤标签/⑥遮盖块/⑧重叠/⑪卡内排版 四列会全部算错位。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _lay
    zp = _lay.load_zone_pages(ROOT)
    lay = os.path.join(ROOT, "layout")
    out = []
    for f in sorted(os.listdir(lay)):
        if not f.endswith(".json") or f.startswith("_") or f.startswith("^_"):
            continue
        p = "".join(ch for ch in f if ch.isdigit())
        pid = "page" + (p.zfill(2) if p else "00")
        rec = zp.get(pid)
        if not rec:
            continue
        c = rec["canvas"]
        out.append({"_pid": pid, "_file": f, "ref": rec.get("ref"),
                    "canvas": {"w": c[0], "h": c[1]}, "zones": rec["zones"]})
    return out


# ---------------------------------------------------------------- ① 颜色 / 色调
def palette(path, n=200, k=6):
    if not path or not os.path.exists(path):
        return None
    im = Image.open(path).convert("RGB")
    im.thumbnail((n, n))
    a = np.asarray(im).astype(np.float32) / 255.0
    flat = a.reshape(-1, 3)
    # HSV（不引 skimage，避免额外依赖）
    mx = flat.max(1)
    mn = flat.min(1)
    d = mx - mn
    v = mx
    s = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0.0)
    r, g, b = flat[:, 0], flat[:, 1], flat[:, 2]
    h = np.zeros_like(mx)
    nz = d > 1e-6
    idx = nz & (mx == r)
    h[idx] = ((g[idx] - b[idx]) / d[idx]) % 6
    idx = nz & (mx == g)
    h[idx] = (b[idx] - r[idx]) / d[idx] + 2
    idx = nz & (mx == b)
    h[idx] = (r[idx] - g[idx]) / d[idx] + 4
    h = (h * 60) % 360

    out = {
        "median_value": round(float(np.median(v)) * 255, 0),
        "median_sat": round(float(np.median(s)), 3),
        "bright_share": round(float((v > 0.85).mean()) * 100, 1),
        "low_sat_share": round(float((s < 0.10).mean()) * 100, 1),
    }
    m = s > 0.10
    if m.sum() > 50:
        hist, edges = np.histogram(h[m], bins=36, range=(0, 360), weights=s[m])
        out["dominant_hue"] = int(edges[int(np.argmax(hist))])
    else:
        out["dominant_hue"] = None
    # 量化色板（必须 clip：纯白像素 1.0×16 = 16 会溢出成第 17 档 → 生成 7 位色值）
    q = np.clip((flat * 16).astype(np.int32), 0, 15)
    key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    u, c = np.unique(key, return_counts=True)
    order = np.argsort(-c)
    top = []
    for i in order[:64]:
        frac = float(c[i]) / flat.shape[0]
        if frac < 0.004 or len(top) >= k:
            break
        kk = int(u[i])
        px = np.array([(kk // 256 + 0.5) / 16, ((kk // 16) % 16 + 0.5) / 16, (kk % 16 + 0.5) / 16])
        top.append({"hex": "#%02X%02X%02X" % tuple((px * 255).astype(int)), "share": round(frac * 100, 1)})
    out["plate"] = top
    return out


def _hsv1(rgb):
    r, g, b = [v / 255.0 for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    sat = 0.0 if mx <= 0 else d / mx
    if d < 1e-6:
        hue = None
    elif mx == r:
        hue = int((((g - b) / d) % 6) * 60)
    elif mx == g:
        hue = int((((b - r) / d) + 2) * 60)
    else:
        hue = int((((r - g) / d) + 4) * 60)
    return hue, sat, mx


def bg_base(path, corner_w=0.10, corner_h=0.07, tol=34.0):
    """★背景基色：四角取样 → 丢掉被主体/白卡污染的角 → 取余下的中位色。

    为什么不能只看「中位亮度/饱和」：参考刊的米灰与天蓝，中位亮度可以只差 3，
    但一个是暖灰（R>B）、一个是冷蓝（B>R）——**方向反了**。
    所以这里给出的是**有符号的冷暖轴 R−B**，它就是「跑没跑偏」本身。

    tol：某角与四角中位的欧氏距离超过它，视为被主体/卡片污染，剔除。
    """
    if not path or not os.path.exists(path):
        return None
    im = Image.open(path).convert("RGB")
    w, h = im.size
    a = np.asarray(im).astype(np.float32)
    pw, ph = max(8, int(w * corner_w)), max(8, int(h * corner_h))
    corners = {"TL": (0, 0), "TR": (w - pw, 0), "BL": (0, h - ph), "BR": (w - pw, h - ph)}
    vals, raw = {}, {}
    for k, (x0, y0) in corners.items():
        p = a[y0:y0 + ph, x0:x0 + pw].reshape(-1, 3)
        v = np.median(p, 0)
        vals[k] = v
        raw[k] = "#%02X%02X%02X" % tuple(int(round(t)) for t in v)
    stack = np.stack(list(vals.values()))
    med = np.median(stack, 0)
    keep = {k: v for k, v in vals.items() if np.linalg.norm(v - med) <= tol}
    if len(keep) < 2:
        keep = vals
    base = np.median(np.stack(list(keep.values())), 0)
    hue, sat, val = _hsv1(base)
    rb = float(base[0] - base[2])
    return {
        "hex": "#%02X%02X%02X" % tuple(int(round(t)) for t in base),
        "corners": raw,
        "kept": sorted(keep.keys()),
        "r_minus_b": round(rb, 1),                 # ★有符号冷暖轴：>0 暖，<0 冷
        "tone": "cool" if rb < -6 else ("warm" if rb > 6 else "neutral"),
        "hue": hue, "sat": round(sat, 3), "val": round(val * 255, 0),
        "y_minus_b": round(float(base[1] - base[2]), 1),
    }


def bg_delta(rc, sc, tol_rb=10.0, tol_hue=22):
    """参考 vs 成品的背景基色差。第 1 点的机器化身。"""
    if not rc or not sc:
        return None
    d_rb = round(sc["r_minus_b"] - rc["r_minus_b"], 1)
    dh = None
    if rc["hue"] is not None and sc["hue"] is not None:
        dh = abs(sc["hue"] - rc["hue"])
        dh = min(dh, 360 - dh)
    bad = (abs(d_rb) > tol_rb) or (dh is not None and dh > tol_hue
                                  and rc["sat"] > 0.03 and sc["sat"] > 0.03)
    return {"d_rb": d_rb, "d_hue": dh, "ok": not bad,
            "why": ("冷暖轴 %+.1f（参考 %s / 成品 %s）" % (d_rb, rc["tone"], sc["tone"]))
                   + ("" if dh is None else "，色相差 %s°" % dh)}


# ---------------------------------------------------------------- ② 文字排版
def typo(page, L):
    j = os.path.join(SCAN, (L.get("ref") or "") + ".json")
    ref_lines = {"bandCuts": [], "colCuts": []}
    if os.path.exists(j):
        with open(j, encoding="utf-8") as fp:
            S = json.load(fp)
        ref_lines["bandCuts"] = [round(b["y"], 4) for b in S.get("bandCuts", [])]
        c = set()
        for b in S.get("bands", []):
            for cc in b.get("colCuts", []):
                c.add(round(cc["x"], 4))
        ref_lines["colCuts"] = sorted(c)
    cw, ch = L["canvas"]["w"], L["canvas"]["h"]
    xs, ys = set([0.0, 1.0]), set([0.0, 1.0])
    for z in L["zones"]:
        b = z["box"]
        xs.add(round(b[0], 4)); xs.add(round(b[0] + b[2], 4))
        ys.add(round(b[1], 4)); ys.add(round(b[1] + b[3], 4))
    tol = 0.015
    hitY = sum(1 for y in ref_lines["bandCuts"] if any(abs(y - e) <= tol for e in ys))
    hitX = sum(1 for x in ref_lines["colCuts"] if any(abs(x - e) <= tol for e in xs))
    return {"ref_bandCuts": ref_lines["bandCuts"], "ref_colCuts": ref_lines["colCuts"],
            "hitY": hitY, "ofY": len(ref_lines["bandCuts"]),
            "hitX": hitX, "ofX": len(ref_lines["colCuts"]), "tol": tol,
            "stack_blocks": stack_blocks(L), "currency": currency(L)}


def stack_blocks(L, x_overlap=0.6, gap=0.045, min_rows=3):
    """★「块内纵向结构」——第 3 点（粗体号码 + 日文词 + 价格）的机器化身。

    结构线（带缝/分栏）量的是**页级分区**，量不到**一个文字块内部有几行、行距多密、
    字号怎么递减**。而参考刊最典型的刊头块恰恰是「特大号码 / 中号词 / 小号标签 /
    中号价格」这样一根**纵向字号链**——它在这套判据里此前完全不存在。

    做法：把所有文字类 zone 按「横向重叠 ≥ x_overlap」聚类，再在每簇里按 y 串成链
    （相邻纵向间隙 ≤ gap），留下 ≥ min_rows 行的链，报出每行的字号与「首/末字号比」。
    """
    txt = [z for z in L["zones"]
           if z.get("kind", "text") in ("text", "torn", "bubble", "badge", "label")
           and (z.get("style") or {}).get("size")]
    used, chains = set(), []
    for i, z in enumerate(txt):
        if i in used:
            continue
        grp = [i]
        a = z["box"]
        for k, w in enumerate(txt):
            if k <= i or k in used:
                continue
            b = w["box"]
            ov = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
            if ov / max(1e-6, min(a[2], b[2])) >= x_overlap:
                grp.append(k)
        rows = sorted((txt[k] for k in grp), key=lambda q: q["box"][1])
        run = [rows[0]]
        for r in rows[1:]:
            prev = run[-1]["box"]
            if r["box"][1] - (prev[1] + prev[3]) <= gap:
                run.append(r)
            else:
                if len(run) >= min_rows:
                    chains.append(run)
                run = [r]
        if len(run) >= min_rows:
            chains.append(run)
        used |= set(grp)
    out = []
    for c in chains:
        sz = [(z.get("style") or {}).get("size") for z in c]
        out.append({"ids": [z["id"] for z in c], "sizes": sz,
                    "y0": round(c[0]["box"][1], 3), "y1": round(c[-1]["box"][1] + c[-1]["box"][3], 3),
                    "ratio": round(max(sz) / max(1e-6, min(sz)), 1),
                    "roles": [(z.get("style") or {}).get("font") for z in c]})
    out.sort(key=lambda d: -d["ratio"])
    return out


CUR_OK = ("円",)
CUR_BAD = ("￥", "¥", "元", "RMB", "CNY")


def _strip_js_comment(line):
    """去注释。**必须做成状态机**，不能只看行首：
    规范文档里会明目张胆地写「不写 ¥1,988」——那是反面示例；
    而行尾续写的块注释（第二行起不以 * 开头）用「行首判断」是漏的，
    会把反面示例当成真用法报出来。这里只保留**字符串字面量里**的内容。

    返回「去掉注释后仍留在代码里的文本」（含字符串内容）。
    """
    out, i, n = [], 0, len(line)
    q = None
    while i < n:
        c = line[i]
        if q:                                   # 在字符串里
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(line[i + 1]); i += 2; continue
            if c == q:
                q = None
            i += 1; continue
        if c in "'\"`":
            q = c; out.append(c); i += 1; continue
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if c == "/" and i + 1 < n and line[i + 1] == "*":
            j = line.find("*/", i + 2)
            if j < 0:
                break
            i = j + 2; continue
        out.append(c); i += 1
    return "".join(out)


def _scan_currency_texts(L):
    """货币写法要查两个地方，漏一个就等于没查：
       ① layout 的 tpl（版式里写死的字）；
       ② **copy/ 下的文案源** —— 价格字符串其实住在 copy/products/*.js 的 vars 里，
          layout 里只有 `${price}` 这个占位符。只扫 layout 会永远读到「0 个円」，
          然后给出一个漂亮的假绿（第一版就是这么漏掉的）。"""
    items = [("layout", z["id"], (z.get("tpl") or "") + " " + (z.get("alt") or ""))
             for z in L["zones"]]
    cdir = os.path.join(ROOT, "copy")
    for dp, dns, fns in os.walk(cdir):
        dns[:] = [d for d in dns if not d.startswith("_")]
        for fn in sorted(fns):
            if not fn.endswith(".js"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            try:
                with open(p, encoding="utf-8") as fp:
                    lines = fp.read().splitlines()
            except Exception:
                continue
            in_block = False
            for i, line in enumerate(lines, 1):
                s = line
                if in_block:                        # 跨行块注释
                    j = s.find("*/")
                    if j < 0:
                        continue
                    s = s[j + 2:]; in_block = False
                if s.count("/*") > s.count("*/"):
                    in_block = True
                code = _strip_js_comment(s)
                if not code.strip():
                    continue
                if "'" not in code and '"' not in code and "`" not in code:
                    continue
                items.append(("copy", "%s:%d" % (rel, i), code))
    return items


def currency(L):
    """★货币写法 —— 第 3 点后半（「只用了￥代替円」）的机器化身。

    日本站价格一律写「1,988円」。出现 `¥ / ￥` 是硬失败：
    它既是**排版**问题（符号与日文基线不齐），也是**受众**问题（日本买家读「円」）。
    """
    bad, n_ok, n_scan = [], 0, 0
    for where, tag, txt in _scan_currency_texts(L):
        if not txt.strip():
            continue
        n_scan += 1
        hitb = [c for c in CUR_BAD if c in txt]
        if hitb:
            bad.append({"where": where, "id": tag, "found": hitb, "text": txt.strip()[:60]})
        elif any(c in txt for c in CUR_OK):
            n_ok += 1
    return {"ok": n_ok, "bad": bad, "n_ok": n_ok, "n_bad": len(bad), "n_scanned": n_scan}



# ---------------------------------------------------------------- ③④ 字体 / 字色
def font_and_ink(L):
    roles, tokens, sizes, photo = {}, {}, [], []
    for z in L["zones"]:
        st = z.get("style") or {}
        if z.get("kind", "text") not in ("text",):
            continue
        r = st.get("font")
        if r:
            roles[r] = roles.get(r, 0) + 1
        c = st.get("color")
        if c:
            tokens[c] = tokens.get(c, 0) + 1
            if c in PHOTO_INK:
                photo.append({"id": z["id"], "color": c, "size": st.get("size"),
                              "shadow": bool(st.get("shadow")), "z": st.get("z")})
        if st.get("size"):
            sizes.append(st["size"])
    roles_sorted = dict(sorted(roles.items(), key=lambda kv: -kv[1]))
    tokens_sorted = dict(sorted(tokens.items(), key=lambda kv: -kv[1]))
    return {"roles": roles_sorted, "ink_tokens": tokens_sorted,
            "size_min": min(sizes) if sizes else None, "size_max": max(sizes) if sizes else None,
            "n_text": len(sizes),
            # ★对比角色（第 5 点）：暗底亮字 or 亮底暗字，以及「压照片的浅色字有没有 shadow」
            "contrast_role": "亮底暗字" if not photo else "含亮色压照片字（需 shadow）",
            "photo_ink_zones": photo}


def fontmap_state():
    p = os.path.join(ROOT, "brand", "brand-pack.json")
    if not os.path.exists(p):
        return {"ok": False, "why": "缺 brand/brand-pack.json"}
    with open(p, encoding="utf-8") as fp:
        D = json.load(fp)
    fm = D.get("fontMap") or []
    roles = D.get("fonts") or {}
    need = len(roles) if isinstance(roles, dict) else 0
    bad = [m.get("role") for m in fm if not (m.get("why") and ("相似" in m["why"] and "差异" in m["why"]))]
    return {"ok": bool(fm) and len(fm) == need and not bad,
            "count": len(fm), "need": need, "缺相似点/差异的条目": bad}


# ---------------------------------------------------------------- ⑤⑥ 标签 / 遮盖块
def tags_and_masks(L):
    tags, masks = [], []
    for z in L["zones"]:
        k = z.get("kind", "text")
        b = z["box"]
        item = {"id": z["id"], "kind": k, "box": [round(v, 4) for v in b],
                "frac": round(b[2] * b[3] * 100, 2)}
        if k in ("badge", "torn", "bubble", "label", "logo"):
            tags.append(item)
        if k in ("panel", "mask", "band") or (k == "text" and ((z.get("style") or {}).get("bg"))):
            masks.append(item)
    return tags, masks


# ---------------------------------------------------------------- ⑦ 模特动作 / 主体位置
def pose_record():
    p = os.path.join(ROOT, "ASSETS.md")
    hits = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fp:
            for line in fp:
                if ("ImageGen" in line or "生成" in line) and ("|" in line):
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    if len(cells) >= 5 and cells[0].endswith(".png"):
                        hits.append({"file": cells[0], "channel": cells[2],
                                     "prompt": cells[3], "src": cells[4]})
    return hits


def occl_mask_of(L):
    """页面声明的遮挡掩膜路径（layout zone 的 occlude）。没有就返回 None。"""
    for z in L["zones"]:
        if z.get("occlude"):
            p = os.path.join(ROOT, z["occlude"])
            if os.path.exists(p):
                return p
    return None


def hole_geom(hole, band=0.35, tag=None):
    """从一个「主体 = True」的布尔图算出几何台账。

    ★抽出来是因为**两个来源**要用同一套读法，而它们的极性相反：
      · `occlude` 掩膜 —— CSS mask 语义：**低 alpha = 挖空 = 主体**
      · 页面照片素材的抠像 —— rembg 语义：**高 alpha = 主体**
    极性不同、几何口径必须相同，否则两边的触边率没法对表。
    """
    if hole is None or not hole.any():
        return None
    h, w = hole.shape
    ys, xs = np.where(hole)
    y1 = int(h * band)
    top = hole[:y1]
    head = None
    if top.any():
        ty, tx = np.where(top)
        head = {"x": round(float(tx.mean()) / w, 3),
                "bbox": [round(float(tx.min()) / w, 3), round(float(ty.min()) / h, 3),
                         round(float(tx.max()) / w, 3), round(float(ty.max()) / h, 3)],
                "pct_in_band": round(float(top.mean()) * 100, 1)}
    # ★四边接触率：主体在四条边 3% 宽带里占了多少。
    #   这是「主体有没有填满画幅」的机器读数，也是「画面为什么显得空」的根因所在：
    #   参考刊的裙摆触右下边，成品若右侧接触率 0，右边就是一片平底 —— 那是**生图层**的事，
    #   靠版面加元素去填是掩盖，不是修复。
    eb = max(1, int(w * 0.03))
    ebh = max(1, int(h * 0.03))
    edges = {"L": round(float(hole[:, :eb].mean()) * 100, 1),
             "R": round(float(hole[:, w - eb:].mean()) * 100, 1),
             "T": round(float(hole[:ebh].mean()) * 100, 1),
             "B": round(float(hole[h - ebh:].mean()) * 100, 1)}
    out = {"hole_bbox": [round(float(xs.min()) / w, 3), round(float(ys.min()) / h, 3),
                         round(float(xs.max()) / w, 3), round(float(ys.max()) / h, 3)],
           "hole_pct": round(float(hole.mean()) * 100, 1),
           "edge_touch": edges, "head": head}
    if tag:
        out["mask"] = tag
    return out


def classify_page(hole, band=0.35, min_pct=1.5, seg_gap=0.03, seg_min=0.08):
    """★这一页是**哪一类主体结构**？—— 由判据自己判，不硬编码页号。

    为什么必须判：品牌包给的参考图是**混编**的（本项目这 9 张就是如此）——
    封面是「人像 + 右上白卡」，p02 是**静物拼贴页**（包、鞋，根本没有主体），
    p09 是**三格美人图**（并排三个头）。第 ⑦ 维的口径
    （头部带 = 上 35%、头心 x、四边接触率）**只对「单一主体」的页成立**。
    不判类型就套上去，会逼着一页没有主体的静物图去填「头心 x」——
    那不是「核对」，是**编读数**；而 schema 一旦这么要求，用户只有两条路：
    编一个数糊过去，或者被一条永远清不掉的硬缺失卡住。

    判定全部从掩膜读出来，与页号、与参考图文件名都无关：

      still    : 主体占比 < min_pct        → 抠像没分出前景/背景（静物拼贴、纯文字页）
      multi    : 上半幅主体的列投影有 ≥2 段 → 多主体页（三格美人图），单个「头心 x」无定义
      portrait : 其余                       → 一个大主体，第 ⑦ 维的正式适用对象

    ★三套词汇（`PAGE_KINDS` / 本函数 / `NA_KINDS`）必须一致 ——
      早期这里返回 `single`/`none` 而 `PAGE_KINDS` 用 `portrait`/`still`，
      人工声明 `still` 之后判据**读不到**、照旧报「未核对」：
      又是一个「写了但读不到」的静默失败。

    返回 {"kind", "pct", "why", "segs"}；`kind` 被 `subj_verdict` 与 `check_readings` 消费。
    """
    if hole is None or not hole.any():
        return {"kind": "still", "pct": 0.0, "segs": [],
                "why": "抠像未分出主体（全图判为同一层）—— 静物拼贴 / 纯文字页，"
                       "第 ⑦ 维（头心 x / 触边率）**不适用**"}
    h, w = hole.shape
    pct = float(hole.mean()) * 100
    if pct < min_pct:
        return {"kind": "still", "pct": round(pct, 1), "segs": [],
                "why": "主体占比 %.1f%% < %.1f%% —— 抠像没分出前景，"
                       "第 ⑦ 维（头心 x / 触边率）**不适用**" % (pct, min_pct)}
    # ---- 多主体判定：**连通域**优先，列投影只作补充 ----
    # 为什么不能只靠列投影：三格照片常常**首尾无缝**
    # （本项目 page09 的三格 box 是 0.045+0.314=0.359=下一格起点，正好相接），
    # 列投影会连成一整段 → 把 multi 误判成 portrait → 再被「跨度 > 0.6」的闸门拦掉，
    # 一组本来正确的读数就白丢了。
    multi_segs = []
    try:
        from scipy import ndimage as ndi
        lab, n = ndi.label(hole)
        if n > 1:
            sizes = np.bincount(lab.ravel())
            total = float(sizes[1:].sum()) or 1.0
            big = [i for i in range(1, n + 1) if sizes[i] >= 0.06 * total]
            if len(big) >= 2:
                for i in big[:6]:
                    _, xs = np.where(lab == i)
                    multi_segs.append({"x0": round(float(xs.min()) / w, 3),
                                       "x1": round(float(xs.max()) / w, 3),
                                       "mass": round(float(sizes[i]) / total, 3)})
    except Exception:
        multi_segs = []
    if len(multi_segs) >= 2:
        multi_segs.sort(key=lambda q: q["x0"])
        return {"kind": "multi", "pct": round(pct, 1), "segs": multi_segs,
                "why": "%d 块互不相连的主体（%s）—— 多主体页，单个「头心 x」无定义，"
                       "第 ⑦ 维应改判**每格各自的位置**"
                       % (len(multi_segs),
                          "、".join("x%.2f–%.2f" % (q["x0"], q["x1"]) for q in multi_segs))}

    # ---- 补充：上半幅列投影分段（连通域漏网时用，如同一块里横向排了两列）----
    top = hole[:int(h * band)]
    cov = top.mean(0) if top.any() else np.zeros(w, np.float32)
    on = cov >= 0.05
    runs, s = [], None
    for x in range(w):
        if on[x] and s is None:
            s = x
        if (not on[x] or x == w - 1) and s is not None:
            runs.append([s, x if not on[x] else x + 1])
            s = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < seg_gap * w:
            merged[-1][1] = r[1]
        else:
            merged.append(r[:])
    mass = float(cov.sum()) or 1.0
    segs = [{"x0": round(a / w, 3), "x1": round(b / w, 3), "w": round((b - a) / w, 3),
             "mass": round(float(cov[a:b].sum()) / mass, 3)}
            for a, b in merged if float(cov[a:b].sum()) / mass >= seg_min]
    if len(segs) >= 2:
        return {"kind": "multi", "pct": round(pct, 1), "segs": segs,
                "why": "上半幅有 %d 段互不相连的主体（%s）—— 多主体页，"
                       "单个「头心 x」无定义，第 ⑦ 维应改判**每格各自的位置**"
                       % (len(segs), "、".join("x%.2f–%.2f" % (s["x0"], s["x1"]) for s in segs))}
    return {"kind": "portrait", "pct": round(pct, 1), "segs": segs,
            "why": "上半幅单段主体 —— 第 ⑦ 维适用（头心 x / 四边接触率）"}


def occl_mask_geom(path, thr=40, band=0.35):
    """★遮挡掩膜的**正确读法**：低 alpha = 把文字挖掉的地方。

    踩过的坑：一开始把「alpha 高」当成主体，于是把「可见区」读成了「人」，
    算出来的头心 0.559，而真值是 0.335 —— 差了一倍还看不出错。
    `occlude` 的语义是 **CSS mask**：alpha 高 = 保留，alpha 低 = 挖空。
    所以「主体轮廓」= **洞**（alpha ≤ thr 的连通区）。几何口径见 `hole_geom`。
    """
    if not path or not os.path.exists(path):
        return None
    a = np.asarray(Image.open(path).convert("RGBA"))
    hole = a[..., -1].astype(np.float32) <= thr
    g = hole_geom(hole, band, tag=os.path.relpath(path, ROOT).replace("\\", "/"))
    if g:
        g["kind"] = classify_page(hole, band)      # ★这一页适不适用第 ⑦ 维，由它自己说
    return g



SUBREF = os.path.join(ROOT, "_work", "_submask")


def ref_subject_mask(refimg, pid, model="u2net"):
    """★参考刊的**主体掩膜** —— 第 7 点（模特构图）的机器化身。

    为什么不能用 dark_blob 凑：参考封面有刊头大字 + 白卡内黑字，
    暗块法会把「头发 + 卡内黑字 + 红色提示字」连成一片，
    量出的头心是这些黑东西的**混合重心**（实测 0.551），不是模特的头（真值约 0.35）。
    差 20 个百分点、方向还相反 —— 于是「参考刊主体居中偏左」这条
    永远只能靠肉眼说，说不成判据。

    所以参考图**也必须跑一次 rembg**，拿到与成品同一口径（同一模型、同一极性）的
    主体轮廓，两边的 头心 x / 四边接触率 才能逐项对表。

    掩膜极性同 submask.py：不透明=保留、透明=主体 → 正合 occl_mask_geom 的读法。
    结果缓存在 `_work/_submask/<pid>-ref.png`，参考图没改就不重算。
    """
    if not refimg or not os.path.exists(refimg):
        return None
    os.makedirs(SUBREF, exist_ok=True)
    dst = os.path.join(SUBREF, "%s-ref.png" % pid)
    try:
        fresh = os.path.getmtime(dst) >= os.path.getmtime(refimg)
    except OSError:
        fresh = False
    if not fresh:
        try:
            from rembg import remove, new_session
        except Exception:
            return None
        try:
            im = Image.open(refimg).convert("RGB")
            sess = new_session(model)
            m = np.asarray(remove(im, session=sess, only_mask=True)).astype(np.float32) / 255.0
        except Exception:
            return None
        cov = float((m > 0.5).mean())
        if not (0.03 <= cov <= 0.92):       # 参考封面上半是「人 + 大片礼服」，占比会偏高
            return None
        alpha = np.clip((1.0 - (m > 0.5).astype(np.float32)) * 255.0, 0, 255).astype(np.uint8)
        Image.fromarray(np.dstack([np.full_like(alpha, 255)] * 3 + [alpha]), "RGBA").save(dst)
    return dst


ASSETMASK = os.path.join(SUBREF, "asset")


def asset_hole(src, model="u2net"):
    """对一张**素材照片**抠像，返回 bool（主体=True）或 None。带缓存。"""
    p = src if os.path.isabs(src) else os.path.join(ROOT, src)
    if not os.path.exists(p):
        return None
    os.makedirs(ASSETMASK, exist_ok=True)
    try:
        key = hashlib.sha1(("%s|%d" % (src, os.path.getmtime(p))).encode("utf-8")).hexdigest()[:16]
    except OSError:
        return None
    cache = os.path.join(ASSETMASK, key + ".npz")
    if os.path.exists(cache):
        try:
            return np.load(cache)["m"]
        except Exception:
            pass
    try:
        from rembg import remove, new_session
        sess = new_session(model)
        m = np.asarray(remove(Image.open(p).convert("RGB"), session=sess,
                              only_mask=True)).astype(np.float32) / 255.0
    except Exception:
        return None
    b = m > 0.5
    if b.mean() > 0.995 or b.mean() < 0.002:
        return None
    np.savez_compressed(cache, m=b)
    return b


def shot_subject_from_assets(L, cw, ch, model="u2net"):
    """★成品侧主体轮廓（**首选通道**）：从 layout 里真实的照片素材抠像，再按 box 映射回画布。

    为什么这条比「整页跑 rembg」可靠：素材是**单张照片**，抠像模型对它的准确率
    远高于一整页图文混排。实测整页跑在 page05 漏掉整个人（洞 0.6%）、
    page08 只抠到 4% —— 却照样驱动了「触边 R 参考 25%→成品 0%」这条判据，
    **假读数驱动的假判据**，比没有判据更坏。素材侧实测：page05 的
    `images/p05-photo.jpg` 一抠就是完整人形。

    代价是要复现 `object-fit`。`css/layout.css` 里 `.z--image img` 默认
    **`object-fit: cover`**（居中裁切），`is-contain` 时 contain ——
    都是 CSS 标准行为，可**精确复现**，不是「近似」。映射公式（cover）：
        s = max(pw/iw, ph/ih)；缩放后居中裁切的偏移 o = (i·s − p)/2；
        画布上 zone 内 (u,v) ← 素材的 ((u+oₓ)/s, (v+o_y)/s)

    返回 (画布布尔图, 每张素材的登记) 或 (None, [])。
    """
    # ★必须去**原始** `layout/NN.json` 取 `src`：`pages()` 返回的 zone 是
    #   `_lay` 精简过的，**不含 src**（那是给坐标类判据用的）。
    #   早期版本直接吃 `pages()` 的结果 → 永远找不到 image zone →
    #   整条素材通道**一次都没生效**，而输出上只看到「无读数」，不报错。
    #   box 仍用折算后的（父框解析过的），按 zone id 对上。
    rawz = []
    rawf = os.path.join(ROOT, "layout", str(L.get("_file") or ""))
    if os.path.exists(rawf):
        try:
            with open(rawf, encoding="utf-8") as f:
                rawz = json.load(f).get("zones") or []
        except Exception:
            rawz = []
    folded = {z.get("id"): z for z in L["zones"]}
    zones = []
    for z in (rawz or L["zones"]):
        if z.get("kind") != "image" or not (z.get("src") or z.get("img")):
            continue
        zz = dict(z)
        if z.get("id") in folded:
            zz["box"] = folded[z["id"]]["box"]          # 用折算过 parent 的坐标
        zones.append(zz)
    if not zones:
        return None, []
    agg = np.zeros((ch, cw), bool)
    used = []
    for z in zones:
        src = z.get("src") or z.get("img")
        am = asset_hole(src, model)
        if am is None or not am.any():
            continue
        ih, iw = am.shape
        x, y, bw, bh = z["box"]
        px0, py0 = int(round(x * cw)), int(round(y * ch))
        pw, ph = max(1, int(round(bw * cw))), max(1, int(round(bh * ch)))
        treat = ((z.get("style") or {}).get("treat") or "cover")
        s = (min(pw / iw, ph / ih) if treat == "contain" else max(pw / iw, ph / ih))
        ox, oy = (iw * s - pw) / 2.0, (ih * s - ph) / 2.0
        ix = np.clip(((np.arange(pw) + ox) / s).astype(int), 0, iw - 1)
        iy = np.clip(((np.arange(ph) + oy) / s).astype(int), 0, ih - 1)
        sub = am[iy][:, ix]
        x1, y1 = min(cw, px0 + pw), min(ch, py0 + ph)
        if x1 <= px0 or y1 <= py0:
            continue
        agg[py0:y1, px0:x1] |= sub[:y1 - py0, :x1 - px0]
        used.append({"zone": z["id"], "src": src, "treat": treat,
                     "box": [round(v, 3) for v in z["box"]],
                     "asset_cover": round(float(am.mean()) * 100, 1),
                     "on_canvas": round(float(sub.mean()) * 100, 1)})
    if not agg.any():
        return None, []
    return agg, used


def shot_subject_mask(shot, pid, model="u2net"):
    """★成品页的**主体掩膜**：对 `_shots/<pid>.png` 整页跑一次 rembg。

    ★为什么不能只靠 `occlude`：`occlude` 是**版面原语**，只有
      「刊头字被模特头挡住」这一个场景需要它。静物页、无遮挡的人像页根本没有 ——
      而第 ⑦ 维（主体位置 / 触边率）**每页都需要**。
      把两者绑在一起的结果是：没有 occlude 的页永远拿不到成品侧读数，
      判据只能永久报「未核对」。实测 p05 参考侧已量出**可信**读数
      （触边 L0 R0 T0 B3，跨度 0.28），成品侧却因为「本页无 occlude」卡死 ——
      **判据把自己锁死了**。

    ★★**实测局限（重要）**：对**排版成品页**整页跑 rembg **经常失效** ——
      它是显著性检测，在一整页图文混排上会漏掉主体。本项目实测：
        page05 洞 0.6%（左侧人像整块漏掉）· page02 洞 43%（把拼贴单品当主体，跨度 0.62 会被拦）
        page09 洞 22.6%（三格并成一块，跨度 0.92 被拦）
      所以它只是**兜底通道**：有 `occlude` 掩膜就用 occlude；没有才试它，
      过不了可靠性闸门就如实报「无读数」，**不硬凑一个数出来**。

    ★**正解（尚未落地，见 references/03 待办）**：主体掩膜应该在**产出时**生成 ——
      `herorecut.py --emit-mask <P>` 重裁照片时同步吐掩膜，登记进 layout
      （如 `"subjectMask": "images/p05-submask.png"`），refdims 优先读它。
      那样成品侧读数与素材同源、不含 `object-fit` 近似，p01 现有的 occlude 也复用它。

    极性同 `ref_subject_mask`：前景处 alpha=0（=「洞」= 主体），供 `occl_mask_geom` 读。
    结果缓存在 `_work/_submask/<pid>-shot.png`，成品页没改就不重算。
    """
    if not shot or not os.path.exists(shot):
        return None
    os.makedirs(SUBREF, exist_ok=True)
    dst = os.path.join(SUBREF, "%s-shot.png" % pid)
    try:
        fresh = os.path.getmtime(dst) >= os.path.getmtime(shot)
    except OSError:
        fresh = False
    if not fresh:
        try:
            from rembg import remove, new_session
        except Exception:
            return None
        try:
            sess = new_session(model)
            m = np.asarray(remove(Image.open(shot).convert("RGB"), session=sess,
                                  only_mask=True)).astype(np.float32) / 255.0
        except Exception:
            return None
        cov = float((m > 0.5).mean())
        if not (0.005 <= cov <= 0.995):
            return None
        alpha = np.clip((1.0 - (m > 0.5).astype(np.float32)) * 255.0, 0, 255).astype(np.uint8)
        Image.fromarray(np.dstack([np.full_like(alpha, 255)] * 3 + [alpha]), "RGBA").save(dst)
    return dst


def ref_mask_reliability(geom, span_max=0.60, cover_max=0.60, clean=False):
    """★参考封面是**合成页**：rembg 会把版面元素（白卡 / 刊头大字 / 提示条）并进「主体」。

    实测 p01：人 + 右上白卡连成**一个连通域**，上半幅水平跨度 0.203–0.968（0.77），
    列投影**没有缺口**可切 → 头心算出 0.581，而真值约 0.38。差 0.2 且看不出错。
    这类「量出来是错的、但不报错」的读数，比没有读数更危险。

    所以给自动读数一道**污染闸门**：
      上半幅跨度 > span_max（人不可能横跨 0.6 以上）  或
      上半幅洞占比 > cover_max（上半幅几乎全被填满 → 一定混进了版面块）
    → 判定「不可采信」，该页第 7 点改用**网格图人工读数**，并由判据强制对表。
    """
    if not geom or not geom.get("head"):
        return {"ok": False, "why": "掩膜无上半幅内容"}
    h = geom["head"]
    # ★多主体页（三格美人图 / 品类拼贴）上半幅**横跨整幅是正常的** ——
    #   不该拿「单主体页混进了版面块」的跨度上限去拦它。
    #   ★但**只对「干净的抠像」放宽**（`clean=True`，即素材抠像 / occlude 掩膜 ——
    #   源图是单张照片或产出时生成的掩膜）。参考图与成品页都是**合成页**，
    #   跨度大很可能真的混进了版面块：实测 page09 参考图 rembg 给出的
    #   触边 L88 R61 B100 就是「三格 + 文字」糊成一片的产物，
    #   拿它去对表会得出「成品侧三条边全不达标」的假结论。
    if clean and (geom.get("kind") or {}).get("kind") == "multi":
        span_max, cover_max = 1.01, 0.88
    span = round(h["bbox"][2] - h["bbox"][0], 3)
    cover = h["pct_in_band"] / 100.0
    why = []
    if span > span_max:
        why.append("上半幅跨度 %.2f > %.2f（版面元素被并入主体）" % (span, span_max))
    if cover > cover_max:
        why.append("上半幅覆盖率 %.0f%% > %.0f%%（上半幅几乎填满）" % (cover * 100, cover_max * 100))
    return {"ok": not why, "span": span, "cover": round(cover, 3),
            "why": "；".join(why) or "上半幅只有一个人形，未混进版面块"}


def subj_verdict(ref, shot, manual=None, dx_tol=0.06, touch_tol=15.0,
                 ref_kind=None, shot_kind=None):
    """第 7 点的判据：参考刊触到的边，成品也必须触到；头心 x 不许跑偏超过 dx_tol。

    参考侧优先用**掩膜读数**；掩膜被判「不可采信」（合成页污染）时，
    改用 `_readings.json` 里的**人工读数**（网格图读出来的），并标注来源。
    ★两边读数都缺 → 返回 None（未核对），由 --check 点名，而不是给个假绿。

    ★★**适用性闸门**（这一条是「动态匹配」的关键）：
    参考图是**混编**的 —— 封面是人像 + 白卡，内页有静物拼贴页、三格美人图。
    「头心 x」只对**单一主体**的页有定义。不判类型就套口径的后果是：
    给一张「包和鞋」的静物图要求填「头心 x」—— 那不是核对，是**逼人编读数**；
    用户只有两条路：编个数糊过去，或者被一条永远清不掉的硬缺失卡住。

      kind == none  → 该页**不适用**第 ⑦ 维（返回 applicable=False，不计缺失）
      kind == multi → 有几个头就有几个 x → 只对表**触边率**，head_dx 不进判据
      kind == single→ 原逻辑（头心 x + 四边接触率）

    ★不触边**不是排版层能修的** —— 那是照片里主体没填满画幅 / 没裁到位，
    要回生图层重出或重裁，**不许靠拉长卡片、加装饰去填**（那是掩盖）。
    """
    kind = (ref_kind or {}).get("kind") or "portrait"
    skind = (shot_kind or {}).get("kind") or "portrait"
    out = {"applicable": True, "ref_from": None, "ref_head_x": None,
           "verdict": [], "edges": [], "layer": "生图层",
           "ref_kind": kind, "shot_kind": skind}

    # ---- 适用性闸门：本页没有「单一主体」这回事 ----
    if kind in NA_KINDS or skind in NA_KINDS:
        out.update({"applicable": False, "ok": True, "layer": None, "head_dx": None,
                    "na": "本页无单一主体 → 第 ⑦ 维不适用"
                          "（不是缺失，是这一维在本页没有定义）",
                    "why": "参考侧 %s ｜ 成品侧 %s"
                           % ((ref_kind or {}).get("why", "—"),
                              (shot_kind or {}).get("why", "—"))})
        return out
    multi = (kind == "multi") or (skind == "multi")

    if ref and ref.get("head"):
        out["ref_head_x"] = ref["head"]["x"]
        out["ref_edges"] = ref["edge_touch"]
        out["ref_from"] = "mask"
    m = manual or {}
    if m.get("头心x") is not None:
        out["ref_head_x"] = float(m["头心x"])
        out["ref_from"] = "manual"
        if m.get("依据"):
            out["ref_why"] = m["依据"]
    if m.get("触边率"):
        out["ref_edges"] = {k: float(m["触边率"].get(k, 0)) for k in "LRTB"}
        if out["ref_from"] is None:
            out["ref_from"] = "manual"

    if multi:
        # 多主体页：「头心 x」无定义（三个头就有三个 x）→ 只保留触边率对照
        out["na"] = "多主体页：头心 x 无定义，只对表四边接触率（主体有没有填满画幅）"
        out["head_dx"] = None
        # ★但「无定义」不等于「随便过」：要有东西可对表才算核对过。
        #   早期漏了这一步，参考侧一个读数都没有（ref_from=None）却报 OK —— 假绿。
        if not out.get("ref_edges") or not shot:
            return None
    else:
        if out["ref_head_x"] is None or not shot or not shot.get("head"):
            return None
        shot_x = shot["head"]["x"]
        out["shot_head_x"] = shot_x
        out["head_dx"] = round(shot_x - out["ref_head_x"], 3)
        if abs(out["head_dx"]) > dx_tol:
            out["verdict"].append("头心 x：参考 %.3f(%s) / 成品 %.3f（差 %+.3f，容差 %.2f）"
                                  % (out["ref_head_x"], out["ref_from"], shot_x,
                                     out["head_dx"], dx_tol))

    if out.get("ref_edges") and shot:
        for k in ("L", "R", "T", "B"):
            a, b = out["ref_edges"][k], shot["edge_touch"][k]
            d = round(b - a, 1)
            if abs(d) > touch_tol:
                out["edges"].append({"edge": k, "ref": a, "shot": b, "d": d})
    out["ok"] = not out["verdict"] and not out["edges"]
    if out["ok"]:
        out["layer"] = None
    return out


def norm_subject(geom=None, manual=None):
    """把「掩膜读数」与「人工读数」归一到同一形状，供台账并排存。"""
    out = {}
    if geom:
        out["from_mask"] = {"hole_bbox": geom.get("hole_bbox"), "hole_pct": geom.get("hole_pct"),
                            "edge_touch": geom.get("edge_touch"), "head": geom.get("head")}
    if manual:
        out["from_manual"] = manual
    return out or None


def make_grid_pair(pid, L, outdir, cell=20):
    """★第 7 点的**辅助读图**：参考 / 成品 并排打 20×20 网格 + 四边 3% 带 + 头带线。

    「头心 x 0.38」这种数，靠肉眼说只能吵；打上格子就是「数第几格」。
    左侧标 x 刻度（每 2 格一次），四边 3% 带涂成半透明淡红 ——
    那正是**触边率**量取的那一条，读到多少一目了然。
    """
    import PIL.ImageDraw as D
    refimg = os.path.join(REF, L.get("ref", "")) if L.get("ref") else None
    shot = os.path.join(SHOTS, pid + ".png")
    if not (refimg and os.path.exists(refimg) and os.path.exists(shot)):
        return None
    a = Image.open(refimg).convert("RGB")
    b = Image.open(shot).convert("RGB")
    W, H = 640, 809
    a = a.resize((W, H), Image.LANCZOS)
    b = b.resize((W, H), Image.LANCZOS)
    sheet = Image.new("RGB", (W * 2 + 60, H + 34), (250, 249, 246))
    dr = D.Draw(sheet)
    for i, (im, lab) in enumerate(((a, "参考 %s" % L.get("ref")), (b, "成品 %s.png" % pid))):
        x0 = 20 + i * (W + 20)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        do = D.Draw(ov)
        for k in range(1, cell):
            xx, yy = W * k / cell, H * k / cell
            strong = (k % 5 == 0)
            do.line([(xx, 0), (xx, H)], fill=(255, 0, 0, 90 if strong else 34),
                    width=2 if strong else 1)
            do.line([(0, yy), (W, yy)], fill=(255, 0, 0, 90 if strong else 34),
                    width=2 if strong else 1)
        eb, ebh = W * 0.03, H * 0.03
        for box in ((0, 0, W, ebh), (0, H - ebh, W, H), (0, 0, eb, H), (W - eb, 0, W, H)):
            do.rectangle(box, fill=(0, 120, 255, 46))
        do.line([(0, H * 0.35), (W, H * 0.35)], fill=(0, 180, 90, 190), width=3)   # 头带下界
        out = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        sheet.paste(out, (x0, 28))
        do2 = D.Draw(sheet)
        for k in range(0, cell + 1, 2):
            do2.text((x0 + W * k / cell + 2, 8), "%.2f" % (k / cell), fill=(180, 0, 0))
            do2.text((x0 + 2, 28 + H * k / cell + 2), "%.2f" % (k / cell), fill=(0, 110, 60))
        dr.text((x0 + 2, H + 30 - 16), lab, fill=(30, 30, 30))
    p = os.path.join(outdir, "%s_refgrid.png" % pid)
    sheet.save(p)
    return p


def dark_blob(path, band=(0.02, 0.45), dark=150, minfrac=0.004):
    """无掩膜时的退路：上半幅最大暗块（头发）的重心。参考封面有刊头与卡内文字时会连片，
    所以**参考侧不自动采信**——只作为人工读图时的辅助读数打印出来。"""
    if not path or not os.path.exists(path):
        return None
    try:
        from scipy import ndimage as ndi
    except Exception:
        return None
    im = Image.open(path).convert("L")
    w, h = im.size
    a = np.asarray(im)
    m = (a < dark).astype(np.uint8)
    m[:int(h * band[0])] = 0
    m[int(h * band[1]):] = 0
    m = ndi.binary_closing(m, np.ones((5, 5)))
    lab, n = ndi.label(m)
    if n < 1:
        return None
    sizes = ndi.sum(np.ones_like(lab), lab, range(1, n + 1))
    k = int(np.argmax(sizes)) + 1
    if sizes[k - 1] < minfrac * w * h:
        return None
    ys, xs = np.where(lab == k)
    return {"x": round(float(xs.mean()) / w, 3), "y": round(float(ys.mean()) / h, 3),
            "span": [round(float(xs.min()) / w, 3), round(float(xs.max()) / w, 3)],
            "area_pct": round(float(sizes[k - 1]) / (w * h) * 100, 2)}


# ---------------------------------------------------------------- ⑨ 排列方式
def arrange(L):
    """★第 4 点：④ 只记「字体角色 + 字色令牌」，**不记怎么排**。
    参考刊那个粉字是「沿弧线斜排」，成品只是「平摆一句」——颜色字体全对，气质全错。
    这里把每个可见大字的排列方式落成机器可读的字段。"""
    rows = []
    for z in L["zones"]:
        k = z.get("kind", "text")
        if k not in ("text", "torn", "bubble", "badge", "label"):
            continue
        st = z.get("style") or {}
        size = st.get("size") or 0
        mode = "横排"
        if st.get("writing") == "v":
            mode = "竖排"
        if st.get("rotate"):
            mode = "斜排"
        if z.get("arc"):
            mode = "弧排"
        if size < 18 and mode == "横排":
            continue
        it = {"id": z["id"], "mode": mode, "size": size,
              "font": st.get("font"), "color": st.get("color")}
        if st.get("rotate"):
            it["rotate"] = st["rotate"]
        if z.get("arc"):
            a = z["arc"]
            it["arc"] = {"cx": a.get("cx"), "cy": a.get("cy"), "r": a.get("r"), "mid": a.get("mid")}
        rows.append(it)
    cnt = {}
    for r in rows:
        cnt[r["mode"]] = cnt.get(r["mode"], 0) + 1
    return {"zones": rows, "mode_counts": cnt,
            "arc_any": any(r["mode"] == "弧排" for r in rows),
            "rot_any": any(r["mode"] == "斜排" for r in rows),
            "manual": "参考图侧需人工登记：本页那些**大字号**元素各自怎么排（横/竖/斜/弧），"
                      "弧排要记弧度（大致扫角）与倾角；再与上面的 mode 逐条对照。"
                      "留空 = 未核对。"}


# ---------------------------------------------------------------- ⑩ 遮挡关系
def occlusion(L):
    """★第 2 点：参考图刊头被模特头部遮挡。这套原语此前**不存在**——
    于是「刊头被头挡」这件事在流程里既做不出来，也不会被发现，成品只能写出一个裸露的字母。

    机器能判的：① 本页声明了几条 occlude、每条挖出来的**洞**在哪（= 主体轮廓）；
    ② 参考侧若要判「该不该遮」，必须人工登记 —— 因为「参考刊这张封面遮没遮」
             只有看图才知道，机器猜不出来。
    ③ 附一份**待问清单**：本页哪些大字正压在出血人像上。看到这张清单，
        人就知道该去参考图上回答「这些字参考刊是怎么处理的」。
    """
    decl = []
    for z in L["zones"]:
        if z.get("occlude"):
            decl.append({"id": z["id"], "mask": z["occlude"],
                         "mask_geom": occl_mask_geom(os.path.join(ROOT, z["occlude"]))})
    hero = [z for z in L["zones"] if z.get("kind") == "image"
            and ((z.get("style") or {}).get("treat") == "bleed")]
    ask = []
    if hero:
        hb = hero[0]["box"]
        for z in L["zones"]:
            st = z.get("style") or {}
            if z.get("kind", "text") != "text" or (st.get("size") or 0) < 48 or z.get("occlude"):
                continue
            b = z["box"]
            ov = (max(0.0, min(hb[0] + hb[2], b[0] + b[2]) - max(hb[0], b[0]))
                  * max(0.0, min(hb[1] + hb[3], b[1] + b[3]) - max(hb[1], b[1])))
            self_a = max(1e-6, b[2] * b[3])
            if ov / self_a >= 0.25:
                ask.append({"id": z["id"], "size": st.get("size"),
                            "overlap_of_self": round(ov / self_a, 2),
                            "shadow": bool(st.get("shadow")), "color": st.get("color"),
                            "dark_ink": st.get("color") not in PHOTO_INK})
    return {"declared": decl, "n_declared": len(decl),
            # 压着人像的特大字：**待问清单**，不是失败。参考侧登记完才知道该不该遮。
            "bigtext_on_hero_ask": ask,
            "manual": "参考图侧需人工登记：本页**哪个元素被主体挡住**（刊头？价格？）、"
                      "被挡掉大概几成、是「整字消失」还是「只切一角」。"
                      "登记后与 declared 的 mask_geom.hole 对照："
                      "参考遮了而 declared 为空 → 第 2 点那类漏；"
                      "declared 里洞的位置与参考被遮元素的位置对不上 → 遮挡位置错。留空 = 未核对。"}


# ---------------------------------------------------------------- ⑪ 卡内排版
def card_structure(L, tol=0.012):
    """★第 6 点：⑥ 只登记「这里有个 panel」，卡**里面**怎么排的没有任何记录——
    于是最容易变成「2×2 生硬排列」。这里把卡内结构拆成：角标 / 标题 / 重复行 / 罫线 / 注记。"""
    out = []
    for p in L["zones"]:
        if p.get("kind") != "panel":
            continue
        kids = [z for z in L["zones"] if z.get("parent") == p["id"]]
        if not kids:
            out.append({"id": p["id"], "n_children": 0, "why": "★空卡：panel 没有任何 parent 子元素",
                        "rows": 0, "rules": 0, "tag": False})
            continue
        kk = {}
        for z in kids:
            kk[z.get("kind", "text")] = kk.get(z.get("kind", "text"), 0) + 1
        rules = kk.get("rule", 0)
        tag = any(z.get("kind") in ("bubble", "badge", "torn") for z in kids)
        # 重复行：等高、kind 相同、y 等距 ≥2 次
        groups = {}
        for z in kids:
            b = z["box"]
            if z.get("kind") == "rule":
                continue
            key = (z.get("kind", "text"), round(b[3], 3))
            groups.setdefault(key, []).append(b)
        reps = []
        for (kd, hgt), arr in groups.items():
            if len(arr) < 2:
                continue
            arr = sorted(arr, key=lambda b: b[1])
            steps = [round(arr[i + 1][1] - arr[i][1], 3) for i in range(len(arr) - 1)]
            if steps and (max(steps) - min(steps)) <= 0.01:
                reps.append({"kind": kd, "n": len(arr), "step": steps[0],
                             "y": [round(a[1], 3) for a in arr]})
        out.append({"id": p["id"], "box": [round(v, 4) for v in p["box"]],
                    "n_children": len(kids), "kinds": kk,
                    "rows": max([r["n"] for r in reps], default=0),
                    "repeated_rows": reps, "rules": rules, "tag": tag,
                    "has_title": any((z.get("style") or {}).get("size", 0) >= 14 for z in kids),
                    "has_note": any((z.get("style") or {}).get("size", 0) <= 10 for z in kids)})
    return {"panels": out, "n_panels": len(out),
            "manual": "参考图侧需人工登记：卡内结构 = 角标？标题几行？重复行几行（编号+名称+罫线）？"
                      "有无底注？再与上面的 repeated_rows / rules / tag 对照。留空 = 未核对。"}


# ---------------------------------------------------------------- ⑫ 画面密度
def density(refimg, shot):
    R = _dens.grid_density(refimg, 3, 3)
    S = _dens.grid_density(shot, 3, 3)
    C = _dens.compare(R, S)
    if not C:
        return None
    return {"ref_grid": C["ref"], "shot_grid": C["shot"],
            "dead_cells": C["dead_cells"], "gap_cells": C["gap_cells"],
            "ref_mean": C["ref_mean"], "shot_mean": C["shot_mean"],
            "manual": "对照方式：python tools/densitycheck.py --plate（出逐格热力图）。"
                      "dead_cells 非空 = 参考刊某格有内容而你这格几乎空白。"}


# ---------------------------------------------------------------- 主流程
def main():
    only = next((a for a in sys.argv[1:] if a.startswith("page")), None)
    write = "--write" in sys.argv
    check = "--check" in sys.argv
    plate = "--plate" in sys.argv
    bgonly = "--bg" in sys.argv
    grid = "--grid" in sys.argv
    os.makedirs(REPORT, exist_ok=True)

    fm = fontmap_state()
    pose = pose_record()
    readings = load_readings()      # ★人工读数持久层（assets/ref/_readings.json），--write 不覆盖它
    ledger, missing = {}, []

    for L in pages():
        pid = L["_pid"]
        if only and pid != only:
            continue
        cw, ch = L["canvas"]["w"], L["canvas"]["h"]
        refimg = os.path.join(REF, L.get("ref", "")) if L.get("ref") else None
        shot = os.path.join(SHOTS, pid + ".png")
        tags, masks = tags_and_masks(L)
        fi = font_and_ink(L)
        rc, sc = bg_base(refimg), bg_base(shot)
        bgd = bg_delta(rc, sc)
        arr = arrange(L)
        occ = occlusion(L)
        card = card_structure(L)
        den = density(refimg, shot)
        mpath = occl_mask_of(L)
        rmask = ref_subject_mask(refimg, pid)
        rsub = occl_mask_geom(rmask) if rmask else None
        ssub = occl_mask_geom(mpath) if mpath else None      # ⑩ 遮挡关系用（那是它的本职）
        # ★第 ⑦ 维的**成品侧读数**：`occlude` 优先（它是产出时的真实掩膜），
        #   不可用就退到「对成品页整页跑 rembg」—— 与参考侧**同口径**。
        #   这一步把第 ⑦ 维从「本页有没有 occlude」上解耦：
        #   静物页、无遮挡的人像页从此也能拿到成品侧读数，不必永久卡在「未核对」。
        ssubj, ssrc = ssub, ("occlude" if ssub else None)
        if ssubj is None or not ref_mask_reliability(ssubj, clean=True)["ok"]:
            # ① 首选：**素材抠像 + box 映射**（素材是单张照片，抠像可靠；
            #    映射按 CSS 的 object-fit 精确复现，不是近似）
            _hole, _used = shot_subject_from_assets(L, cw, ch)
            _c1 = hole_geom(_hole) if _hole is not None else None
            if _c1:
                _c1["kind"] = classify_page(_hole)
                _c1["assets"] = _used
            if _c1 and ref_mask_reliability(_c1, clean=True)["ok"]:
                ssubj, ssrc = _c1, "assets"
            else:
                # ② 兜底：成品页整页抠像 —— 实测常漏检，故加「洞占比」下限
                _sm = shot_subject_mask(shot, pid)
                _c2 = occl_mask_geom(_sm) if _sm else None
                if (_c2 and ref_mask_reliability(_c2)["ok"]
                        and _c2["hole_pct"] >= SHOT_PAGE_MIN):
                    ssubj, ssrc = _c2, "shot-page"
        # ★页类型（参考侧 / 成品侧各自判）：第 ⑦ 维不是每页都适用 ——
        #   静物拼贴页没有「头心 x」，三格美人图有三个头。
        #   缺掩膜时给 unknown（≠ still）：不擅自判「不适用」，仍要求人工读数。
        rkind = (rsub or {}).get("kind") or {
            "kind": "unknown", "why": "参考侧无掩膜（rembg 未分出主体或占比越界）"}
        skind = (ssubj or {}).get("kind")
        # ★人工声明的页类型**优先于**机器判定：合成页上机器判不准
        #   （实测 p02 静物拼贴被 rembg 判成跨度 0.95 的一整块 → 闸门判「不可采信」）。
        #   一个本该「不适用」的页若被机器判成 single，就会去要不存在的「头心 x」。
        man_pk = ((readings.get(pid) or {}).get("pageKind") or {}).get("kind")
        if man_pk in PAGE_KINDS:
            rkind = {"kind": man_pk, "src": "manual",
                     "why": "人工声明：%s" % PAGE_KINDS[man_pk]}
        rrel = ref_mask_reliability(rsub)
        rmanual = (readings.get(pid) or {}).get("pose")
        # 参考侧读数优先级：人工读数 > 可信的掩膜读数 > 无（未核对）
        ruse = rsub if rrel["ok"] else None
        subj = {"ref_from_mask": rsub,
                "page_kind": {"ref": rkind, "shot": skind},
                "ref_mask_reliable": rrel,
                "ref_manual": rmanual,
                "shot_from_occl_mask": ssub,
                "shot_subject": ssubj,
                "shot_subject_src": ssrc,
                "verdict": subj_verdict(ruse, ssubj, rmanual,
                                        ref_kind=rkind, shot_kind=skind),
                "norm": norm_subject(ruse, rmanual),
                "shot_dark_blob": dark_blob(shot),
                "manual": "参考封面是**合成页**，rembg 会把右上白卡并进主体（实测上半幅跨度 0.77、"
                          "列投影无缺口）→ 自动读数不可采信时，第 7 点改用**网格人工读数**："
                          "先看 _shots/report/<page>_refgrid.png（20×20 网格 + 四边 3%% 带 + 头带线），"
                          "把 `_readings.json` → <page>.pose 的 `头心x` 与 `触边率` 填上。"
                          "判据按 |Δ头心 x| ≤ 0.06、|Δ触边率| ≤ 15pp 自动对表；"
                          "★超了是**生图层**问题（照片里主体没填满画幅），"
                          "要回生图层重出或重裁，**不许靠拉长卡片、加装饰去填**（那是掩盖）。"}
        d = {
            "ref": L.get("ref"), "canvas": [cw, ch],
            "color": {"ref": palette(refimg), "shot": palette(shot),
                      "bg_ref": rc, "bg_shot": sc, "bg_delta": bgd},
            "typo": typo(pid, L),
            "font": {"roles": fi["roles"], "fontMap": fm,
                     "manual": "核对方式：node tools/fontcheck.js（证明真的用了内嵌字体）"
                               " + references/05 六步（证明替代体与参考刊同族）。二者缺一即未核对。"},
            "inkcolor": {"tokens": fi["ink_tokens"], "contrast_role": fi["contrast_role"],
                         "photo_ink_zones": fi["photo_ink_zones"],
                         "size_range": [fi["size_min"], fi["size_max"]],
                         "manual": "核对方式：python tools/contrastcheck.py（文字压照片读不读得出来）。"
                                   "另需人工登记参考刊本页的对比角色（亮底暗字 / 暗底亮字）与目标比值。"},
            "tags": {"zones": tags, "n": len(tags),
                     "manual": "参考图侧需人工登记：参考刊本页可见的标签元素（徽章/撕纸/序号块）各几个、"
                               "什么形状、压在什么上。本键留空 = 未核对。"},
            "masks": {"zones": masks, "n": len(masks),
                      "manual": "参考图侧需人工登记：遮盖块（白卡/色带/半透明面板）的位置与参考刊是否一致。"},
            "pose": {"records": pose, "subject": subj,
                     "manual": "参考图侧需人工登记：景别（近景/中景/全身）、朝向（正/侧/背）、视线、"
                               "手势、遮挡道具、**主体轴心 x**。再与生图提示词逐项对照；"
                               "不一致就是重做生图，不是改文案。"},
            "overlap": {"manual": "核对方式：python tools/subjectguard.py（实底小模块不许压主体）"
                                  " + python tools/check_faces.py（标签不许压五官；禁区为空会报 VACUUM）"},
            "arrange": arr,
            "occlusion": occ,
            "card": card,
            "density": den,
        }
        # ★把人工读数合并进对应维度（键 ref_readings），紧邻机器读数可逐条对表。
        #   放在 ledger[pid] = d 之前 —— 否则 --write 落盘时读数丢了。
        rd = readings.get(pid) or {}
        for k, v in rd.items():
            if k in d and isinstance(d[k], dict):
                d[k]["ref_readings"] = v
        d["_readings_filled"] = sorted(k for k in rd if k in d)
        # ★不适用 ≠ 留空：静物页 / 多主体页没有「单一主体」，第 ⑦ 维的 pose 不进待办清单
        _na = {"pose"} if rkind.get("kind") in ("still", "multi") else set()
        d["_readings_na"] = sorted(_na)
        d["_readings_empty"] = [k for k in MANUAL_DIMS
                                if k not in _na and not (d.get(k) or {}).get("ref_readings")]
        ledger[pid] = d

        # ---------------- 硬缺失（机器能判） ----------------
        miss = []
        if d["color"]["ref"] is None or d["color"]["shot"] is None:
            miss.append("① 缺参考图或成品图")
        if bgd and not bgd["ok"]:
            miss.append("① 背景基色跑偏：%s（参考 %s / 成品 %s）"
                        % (bgd["why"], rc["hex"], sc["hex"]))
        if d["typo"]["ofY"] == 0 and d["typo"]["ofX"] == 0:
            miss.append("② refscan 无任何读数 → 解析可能没跑")
        if d["typo"]["currency"]["n_bad"]:
            miss.append("② 货币写法：出现 %s（日本站一律写「円」）—— %s"
                        % ("/".join(sorted({c for x in d["typo"]["currency"]["bad"] for c in x["found"]})),
                           "; ".join("%s %s" % (x["id"], x["text"][:40]) for x in d["typo"]["currency"]["bad"][:4])))
        if not fm["ok"]:
            miss.append("③ fontMap 不完整：%d 条 / 需 %d 条，缺相似点或差异：%s"
                        % (fm["count"], fm["need"], fm["缺相似点/差异的条目"]))
        nophoto = [x["id"] for x in fi["photo_ink_zones"] if not x["shadow"]]
        if nophoto:
            miss.append("④ 压照片的浅色字没给 shadow（看不见）：%s" % ", ".join(nophoto))
        for x in card["panels"]:
            if x["n_children"] == 0:
                miss.append("⑪ panel %s 是空卡（无 parent 子元素）→ 第 6 点那类「卡里没排版」" % x["id"])
        if den and den["dead_cells"]:
            cells = ", ".join("[%d,%d] %.1f→%.1f" % (c["cell"][0], c["cell"][1], c["ref"], c["shot"])
                              for c in den["dead_cells"][:4])
            miss.append("⑫ 画面空档格 %d 个：%s" % (len(den["dead_cells"]), cells))
        if not d["pose"]["records"]:
            miss.append("⑦ ASSETS.md 无 AI 生成登记 → 模特图来源不明")
        v = subj["verdict"]
        if v and not v["ok"]:
            bits = []
            if v["head_dx"] is not None and abs(v["head_dx"]) > 0.06:
                bits.append("头心 x 差 %+.3f（参考源 %s）" % (v["head_dx"], v["ref_from"]))
            for e in v["edges"]:
                bits.append("触边 %s 参考 %.0f%%→成品 %.0f%%" % (e["edge"], e["ref"], e["shot"]))
            miss.append("⑦ 主体构图跑偏（−>生图层，不许版面掩盖）：%s" % "；".join(bits))
        elif v is None:
            if rkind.get("kind") in NA_KINDS:
                pass          # ★不适用 ≠ 缺失：静物页根本没有「头心 x」这回事
            else:
                miss.append("⑦ 主体构图**未核对**：参考侧既无可信掩膜读数也无人工读数 → "
                            "开 _shots/report/%s_refgrid.png 读图，把 头心x / 触边率 填进 "
                            "assets/ref/_readings.json 的 %s.pose" % (pid, pid))
        if refimg and rsub is None:
            miss.append("⑦ 参考图主体掩膜取不到 → 请检查 rembg（第 7 点将只能人工读数）")

        d["_missing"] = miss
        d["_todo"] = [DIM_CN[k] for k in MANUAL_DIMS]
        if miss:
            missing.append((pid, miss))
        if grid:
            gp = make_grid_pair(pid, L, REPORT)
            if gp:
                print("读图网格 -> %s" % os.path.relpath(gp, ROOT))

        # ---------------- 控制台摘要 ----------------
        if bgonly:
            rc, sc = d["color"]["bg_ref"], d["color"]["bg_shot"]
            if rc and sc:
                print("%s  ref=%s  背景基色 参考 %s %-8s R−B%+5.1f  |  成品 %s %-8s R−B%+5.1f  [%s]  %s"
                      % (pid, L.get("ref"), rc["hex"], rc["tone"], rc["r_minus_b"],
                         sc["hex"], sc["tone"], sc["r_minus_b"],
                         "OK" if (bgd and bgd["ok"]) else "★跑偏", bgd["why"] if bgd else ""))
            else:
                print("%s  缺参考图或成品图（先 node tools/shoot.js）" % pid)
            continue
        print("=" * 92)
        print("%s  ref=%s  canvas=%dx%d" % (pid, L.get("ref"), cw, ch))
        if rc and sc:
            pr, ps = d["color"]["ref"], d["color"]["shot"]
            print("  ① 颜色/色调   整体 参考:亮度%.0f 饱和%.2f 轴%-4s 亮部%.0f%%  |  成品:亮度%.0f 饱和%.2f 轴%-4s 亮部%.0f%%"
                  % (pr["median_value"], pr["median_sat"],
                     pr["dominant_hue"] if pr["dominant_hue"] is not None else "—", pr["bright_share"],
                     ps["median_value"], ps["median_sat"],
                     ps["dominant_hue"] if ps["dominant_hue"] is not None else "—", ps["bright_share"]))
            flag = " OK " if (bgd and bgd["ok"]) else "★跑偏"
            print("        ★背景基色  参考 %s %-8s R−B%+5.1f  |  成品 %s %-8s R−B%+5.1f   [%s]"
                  % (rc["hex"], rc["tone"], rc["r_minus_b"], sc["hex"], sc["tone"], sc["r_minus_b"], flag))
            print("                   四角 参考 %s  成品 %s"
                  % (rc["corners"], sc["corners"]))
        t = d["typo"]
        print("  ② 文字排版   参考结构线 横%d条/竖%d条 → layout 命中 横%d/竖%d（±%.1f%%画布）"
              % (t["ofY"], t["ofX"], t["hitY"], t["hitX"], t["tol"] * 100))
        for b in t["stack_blocks"][:2]:
            print("        块内结构 y%.3f–%.3f  首/末字号比 %.1f×  %s"
                  % (b["y0"], b["y1"], b["ratio"], b["ids"]))
        cur = t["currency"]
        if cur["n_bad"]:
            print("        货币写法  ★出现 %s：" % "/".join(sorted({c for x in cur["bad"] for c in x["found"]})))
            for x in cur["bad"][:6]:
                print("                   %s %s  「%s」" % (x["where"], x["id"], x["text"]))
        else:
            print("        货币写法   「円」%d 处（扫 %d 条文本，layout + copy/）OK" % (cur["n_ok"], cur["n_scanned"]))
        print("  ③ 文字字体   角色 %s | fontMap %s"
              % (d["font"]["roles"], "完整 %d/%d" % (fm["count"], fm["need"]) if fm["ok"] else "★不完整"))
        print("  ④ 文字颜色   令牌 %s | 对比角色 %s" % (d["inkcolor"]["tokens"], d["inkcolor"]["contrast_role"]))
        print("  ⑤ 标签元素   %d 个 %s" % (len(tags), [x["id"] for x in tags][:8]))
        print("  ⑥ 遮盖块     %d 个 %s" % (len(masks), [(x["id"], "%s%%" % x["frac"]) for x in masks][:6]))
        sg = subj["shot_subject"]
        ssrc = subj.get("shot_subject_src")
        print("  ⑦ 模特动作   生图登记 %d 条 | 成品侧主体（%s）：bbox %s 洞 %.0f%%  触边 L%.0f R%.0f T%.0f B%.0f"
              % (len(pose), {"occlude": "来源 occlude 掩膜",
                              "assets": "来源 素材抠像 + box 映射",
                              "shot-page": "来源 成品页整页抠像（兜底，低置信）"}
                 .get(ssrc, "无读数"),
                 sg["hole_bbox"] if sg else "—", sg["hole_pct"] if sg else 0,
                 sg["edge_touch"]["L"] if sg else 0, sg["edge_touch"]["R"] if sg else 0,
                 sg["edge_touch"]["T"] if sg else 0, sg["edge_touch"]["B"] if sg else 0))
        if rsub:
            tag = "可信" if rrel["ok"] else "★不可采信"
            kk = (rsub.get("kind") or {}).get("kind", "?")
            print("        参考刊主体（rembg 跑参考图）  [%s] 类型 %s  触边 L%.0f R%.0f T%.0f B%.0f  上半幅跨度 %.2f"
                  % (tag, PAGE_KINDS.get(kk, kk).split("（")[0],
                     rsub["edge_touch"]["L"], rsub["edge_touch"]["R"],
                     rsub["edge_touch"]["T"], rsub["edge_touch"]["B"], rrel.get("span") or 0))
            if not rrel["ok"]:
                print("                   %s" % rrel["why"])
                print("                   → 参考头条号改用网格人工读数：_shots/report/%s_refgrid.png" % pid)
        if rmanual:
            print("        参考刊主体（人工读数）  头心 x %s  触边 %s"
                  % (rmanual.get("头心x"), rmanual.get("触边率")))
        if v:
            if not v.get("applicable", True):
                print("        ★构图对照  N/A —— %s" % v.get("na"))
                print("                    %s" % v.get("why", ""))
                print("                    （不适用 ≠ 缺失；该页没有「单一主体」这回事，"
                      "不需要也不应该填「头心 x」）")
            elif v["ok"]:
                print("        ★构图对照  OK（参考源 %s；头心差 %s；四边接触率全部在 ±%.0fpp 内）"
                      % (v["ref_from"], ("%+.3f" % v["head_dx"]) if v["head_dx"] is not None else "—", 15.0))
                if v.get("na"):
                    print("                    %s" % v["na"])
            else:
                if v.get("na"):
                    print("        ★构图对照  %s" % v["na"])
                for w in v["verdict"]:
                    print("        ★构图对照  %s" % w)
                for e in v["edges"]:
                    print("        ★构图对照  边 %s：参考 %.0f%% → 成品 %.0f%%（差 %+.0fpp）→ %s"
                          % (e["edge"], e["ref"], e["shot"], e["d"], v["layer"]))
        else:
            print("        ★构图对照  **未核对** —— 开 _shots/report/%s_refgrid.png 读图后填 _readings.json" % pid)
        if sg and sg.get("head"):
            h = sg["head"]
            print("        头部带 x%.3f–%.3f（轴心 %.3f，占带 %.0f%%）"
                  % (h["bbox"][0], h["bbox"][2], h["x"], h["pct_in_band"]))
        if not sg and (v is None or v.get("applicable", True)):
            print("        （成品侧抠像没分出主体 → 第 ⑦ 维只能靠人工读数；"
                  "参考侧读数见上，登记写 _readings.json）")
        print("  ⑧ 重叠编排   台账 == 两个判据（见 overlap.manual）")
        print("  ⑨ 排列方式   %s%s" % (arr["mode_counts"],
              "　弧排:" + ", ".join("%s(r=%s,mid=%s)" % (r["id"], r["arc"]["r"], r["arc"]["mid"])
                                    for r in arr["zones"] if r["mode"] == "弧排") if arr["arc_any"] else ""))
        print("  ⑩ 遮挡关系   声明 %d 条 %s%s" % (occ["n_declared"], [x["id"] for x in occ["declared"]],
              ("　待问（压着人像的特大字）：" + ", ".join(x["id"] for x in occ["bigtext_on_hero_ask"]))
              if occ["bigtext_on_hero_ask"] else ""))
        for x in occ["declared"]:
            g = x.get("mask_geom") or {}
            h = g.get("head") or {}
            if h:
                print("        掩膜 %s：挖出的头部带 x%.3f–%.3f（轴心 %.3f，占带 %.0f%%）"
                      % (os.path.basename(x["mask"]), h["bbox"][0], h["bbox"][2], h["x"], h["pct_in_band"]))
            elif g:
                print("        掩膜 %s：洞 %s（占画面 %.0f%%）"
                      % (os.path.basename(x["mask"]), g["hole_bbox"], g["hole_pct"]))
        for c in card["panels"]:
            print("  ⑪ 卡内排版   %s 子元素 %d（行 %d / 罫线 %d / 角标 %s）%s"
                  % (c["id"], c["n_children"], c["rows"], c["rules"], c["tag"],
                     "  ★空卡" if c["n_children"] == 0 else ""))
        if den:
            print("  ⑫ 画面密度   参考均 %.1f / 成品均 %.1f   空档格 %d 个 %s"
                  % (den["ref_mean"], den["shot_mean"], len(den["dead_cells"]),
                     ["[%d,%d]" % (c["cell"][0], c["cell"][1]) for c in den["dead_cells"][:4]]))
        if miss:
            print("  ★ 硬缺失：" + "；".join(miss))

    if write:
        out = os.path.join(REPORT, "refdims.json")
        with open(out, "w", encoding="utf-8") as fp:
            json.dump({"_doc": "十二维解析台账。manual 键留空 = 该维度未人工核对。"
                               "硬缺失在 _missing 里，由 --check 汇总。",
                       "dims": DIM_CN, "pages": ledger}, fp, ensure_ascii=False, indent=1,
                      default=_jsafe)
        print("\n台账 -> %s" % out)

    if plate:
        make_plate(ledger)

    if check:
        print("\n" + "=" * 92)
        if missing:
            print("★ 十二维台账存在**硬缺失**，共 %d 页：" % len(missing))
            for pid, miss in missing:
                print("   %s" % pid)
                for m in miss:
                    print("      · %s" % m)
        else:
            print("十二维台账无硬缺失。")

        # ★人工读数分两栏：已落字（台账里有 ref_readings）/ 留空未核对（只是文档里一句话不算数）
        rprobs, rok = check_readings(readings)
        n_filled = sum(1 for d in ledger.values() if d["_readings_filled"])
        print("\n人工读数（assets/ref/_readings.json）：%d/%d 页已落字，%d 页通过键名校验"
              % (n_filled, len(ledger), rok))
        if rprobs:
            print("  ★读数文件问题 %d 条（键名/类型不合法 = 写了但读不到）：" % len(rprobs))
            for p in rprobs[:12]:
                print("      · %s" % p)
            if len(rprobs) > 12:
                print("      …共 %d 条" % len(rprobs))
        for pid, d in ledger.items():
            filled, empty = d["_readings_filled"], d["_readings_empty"]
            mark = "OK" if not empty else "★待填 %d 项" % len(empty)
            print("   %s  [%s]  已填 %s"
                  % (pid, mark, ", ".join(DIM_CN[k].split("（")[0] for k in filled) or "—"))
            for k in empty:
                print("        ☐ %s" % DIM_CN[k])
        if not ledger:
            for k in MANUAL_DIMS:
                print("   ☐ %s" % DIM_CN[k])
        return 1 if (missing or rprobs) else 0
    return 0


def make_plate(ledger):
    """参考 / 成品 色板对照图：左参考右成品，上原图下色板条 + 背景基色块。"""
    rows = []
    for pid, d in ledger.items():
        if not (d["color"]["ref"] and d["color"]["shot"]):
            continue
        rows.append((pid, d))
    if not rows:
        return
    W, H = 320, 404
    band = 44
    sheet = Image.new("RGB", (W * 2 + 60, (H + band + 46) * len(rows) + 20), (244, 242, 239))
    dr = ImageDraw.Draw(sheet)
    y = 10
    for pid, d in rows:
        for cx, key, lab in ((10, "ref", "参考"), (W + 50, "shot", "成品")):
            src = os.path.join(REF, d["ref"]) if key == "ref" else os.path.join(SHOTS, pid + ".png")
            im = Image.open(src).convert("RGB")
            im.thumbnail((W, H))
            sheet.paste(im, (cx, y))
            bg = d["color"]["bg_" + key]
            dr.text((cx + 2, y + H + 2), "%s %s 亮度%.0f 亮部%.0f%%  基色 %s %s R−B%+.1f" % (
                pid, lab, d["color"][key]["median_value"], d["color"][key]["bright_share"],
                bg["hex"], bg["tone"], bg["r_minus_b"]), fill=(30, 30, 30))
            bx = cx
            for p in d["color"][key]["plate"]:
                col = tuple(int(p["hex"][i:i + 2], 16) for i in (1, 3, 5))
                dr.rectangle([bx, y + H + 20, bx + int(W * p["share"] / 100 * 1.6), y + H + 20 + band - 16], fill=col)
                bx += int(W * p["share"] / 100 * 1.6) + 2
            # 背景基色块
            col = tuple(int(bg["hex"][i:i + 2], 16) for i in (1, 3, 5))
            dr.rectangle([cx, y + H + 24 + band - 16, cx + 40, y + H + 24 + band - 16 + 18],
                         fill=col, outline=(90, 90, 90))
        y += H + band + 46
    out = os.path.join(SHOTS, "report", "_palette_compare.png")
    sheet.save(out)
    print("色板 + 背景基色对照 -> %s" % out)


if __name__ == "__main__":
    sys.exit(main())
