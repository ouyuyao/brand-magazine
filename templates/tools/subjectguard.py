# -*- coding: utf-8 -*-
"""subjectguard.py —— 「小模块不许遮挡模特/产品主体」的可复跑判据

为什么需要它
------------
既有判据只覆盖两类遮挡：
    check_faces.py  标签压**五官**（且禁区表为空时会「0 禁区 → 全绿」地空转）
    blockcheck.py   照片块**互压**
第三类、也是版式里最高频翻车的一类没人管：
    **实底小模块（撕纸标 / 徽章 / 白卡小片 / 气泡）盖住了模特躯干或产品主体。**
它不压五官 → check_faces 抓不到；它也不是照片互压 → blockcheck 抓不到。

口径（照参考刊的实际做法定）
----------------------------
1. **只判「实底」模块**：`badge` / `torn` / `bubble` / `panel` / `band`，
   以及显式带底色（`style.bg` ≠ none）的 `text`。
   —— 纯文字压照片**不算遮挡**，那正是杂志语汇（参考刊的斜置大标就压在人身上）；
   文字压照片的**可读性**交给 `contrastcheck.py`。
2. **排除描边类**（`mod: is-outline`）与**透明底**：它们是空的，没盖住任何东西。
3. **排除被更大同族模块完全包含的 zone**：色卡小图在白色附录卡里，那是卡片在压人，
   不该把卡片里的每个小图各判一次。
4. 分级：小模块（≤3% 画布）**FAIL**、中等（3–8%）**WARN**、大模块（>8%）**只报告**
   —— 出血巨字、斜置大标、附录大卡本来就是设计主体，参考刊同样压人；
   它们是否可接受，由 layout 的 `refdims.overlap` 显式声明。

主体掩膜怎么来
--------------
优先 rembg（本地已缓存 u2net，约 0.4s/张）：alpha → 阈值 → 腐蚀掉细结构
（薄纱 / 肩带 / 发丝）→ 只留最大连通块，剩下的才是「躯干 / 头」这类厚实主体。
腐蚀半径按**该图自身短边**取比例，随图大小自适应。
渲染结果缓存到 `_work/_submask/`。

无 rembg 时降级读人工声明框 `tools/subject.json`（标定方式与 faces.json 完全一致：
`grid.py` 叠网 → `probe.py` 带尺读数）。**声明框为空 → 报 SKIP，绝不报 OK。**

用法
----
    python tools/subjectguard.py                  # 全部页
    python tools/subjectguard.py page01           # 指定页
    python tools/subjectguard.py --erode 0.03     # 腐蚀半径（占该图短边，默认 0.02）
    python tools/subjectguard.py --min-frac 0.005 # 相交 / 主体核心 的 FAIL 下限
    python tools/subjectguard.py --strict         # WARN 也算失败
    python tools/subjectguard.py --detail         # 列出全部命中
    python tools/subjectguard.py --no-cache       # 强制重算掩膜

退出码：有 FAIL → 1，否则 0。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "_shots", "guard")
SUBDIR = os.path.join(ROOT, "_work", "_submask")

# 会被判「遮挡」的实底 kind
SOLID_KINDS = {"badge", "torn", "bubble", "panel", "band"}
# 底图类
BASE_KINDS = {"image"}

SMALL_FRAC = 0.030
MEDIUM_FRAC = 0.080
MIN_AREA_PX = 400.0
MIN_FRAC_OF_CORE = 0.005


def argval(name, default=None):
    a = sys.argv[1:]
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith("--") else True
    return default


def pages():
    """逐页版式 —— **坐标已折算 parent**（读 layout/_resolved.json，见 tools/_lay.py）。
    直读 layout/NN.json 时，白卡里的模块会保留「相对父框」的小坐标，
    遮挡判定会把它们当成画布左上角的小方块 —— 于是漏判真正的越界。"""
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


def erode(m, r):
    """分离式方形核腐蚀。r < 1 时原样返回。"""
    if r < 1:
        return m.astype(np.float32)
    m = m.astype(np.float32)
    k = 2 * int(r) + 1
    padx = np.pad(m, ((0, 0), (r, r)), mode="constant", constant_values=0.0)
    a = np.full_like(m, 1.0)
    for i in range(k):
        a = np.minimum(a, padx[:, i:i + m.shape[1]])
    pady = np.pad(a, ((r, r), (0, 0)), mode="constant", constant_values=0.0)
    b = np.full_like(a, 1.0)
    for i in range(k):
        b = np.minimum(b, pady[i:i + a.shape[0], :])
    return b


def largest_cc(mask):
    try:
        from scipy import ndimage
        lab, n = ndimage.label(mask)
        if n == 0:
            return mask
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        return lab == (int(np.argmax(sizes)) + 1)
    except Exception:
        return mask


def is_solid(z):
    """这个 zone 是否算「实底模块」。"""
    kind = z.get("kind", "text")
    st = z.get("style") or {}
    if kind in SOLID_KINDS:
        mod = z.get("mod", "") or ""
        if "outline" in mod:          # 描边框：空的，不遮挡
            return False
        if st.get("bg") in ("none", "transparent"):
            return False
        return True
    if kind == "text":
        bg = st.get("bg")
        return bool(bg) and bg not in ("none", "transparent")
    return False


def box_px(b, cw, ch):
    return (b[0] * cw, b[1] * ch, b[2] * cw, b[3] * ch)


def alpha_of(src_rel, cache_key, use_cache=True, model="u2net"):
    os.makedirs(SUBDIR, exist_ok=True)
    cpath = os.path.join(SUBDIR, cache_key + ".npy")
    if use_cache and os.path.exists(cpath):
        return np.load(cpath), "rembg:%s(缓存)" % model
    try:
        from rembg import remove, new_session
        sess = new_session(model)
        im = Image.open(os.path.join(ROOT, src_rel)).convert("RGB")
        a = np.asarray(remove(im, session=sess, only_mask=True)).astype(np.float32) / 255.0
        np.save(cpath, a)
        return a, "rembg:%s" % model
    except Exception as e:
        return None, "rembg 不可用（%s）" % type(e).__name__


def flat_mask(src_rel, tol=14.0):
    """近白底 / 纯色平底产品图的主体掩膜。

    与 tools/cutout_flat.py 同一思路：**不是**用亮度阈值，而是
    「与四角底色连通的区域 = 背景」，其余（含产品内部封闭洞）= 主体。
    这样白色产品压在白色背景上也能分出来 —— rembg 在这类图上会失手。

    返回 0/1 float 数组，失败返回 None。
    """
    try:
        im = Image.open(os.path.join(ROOT, src_rel)).convert("RGB")
    except Exception:
        return None
    a = np.asarray(im).astype(np.float32)
    h, w, _ = a.shape
    s = max(4, min(h, w) // 20)
    corners = np.concatenate([
        a[:s, :s].reshape(-1, 3), a[:s, -s:].reshape(-1, 3),
        a[-s:, :s].reshape(-1, 3), a[-s:, -s:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    near_bg = np.sqrt(((a - bg) ** 2).sum(axis=2)) < tol
    if near_bg.mean() < 0.05 or near_bg.mean() > 0.95:
        return None
    try:
        from scipy import ndimage
        lab, n = ndimage.label(near_bg)
        if n == 0:
            return None
        border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist()) | \
                 set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
        border.discard(0)
        if not border:
            return None
        real_bg = np.isin(lab, list(border))
    except Exception:
        return None
    subj = ~real_bg
    if subj.mean() < 0.03:
        return None
    return subj.astype(np.float32)


def main():
    import _cli
    # ★用 _cli.positionals()：避免选项的值被当成页面筛选器 → 匹配不到任何页 → 静默空过
    only = next((a for a in _cli.positionals() if a.startswith("page")), None)
    erode_frac = float(argval("--erode", 0.02))
    strict = "--strict" in sys.argv
    detail = "--detail" in sys.argv
    use_cache = "--no-cache" not in sys.argv
    model = argval("--model", "u2net")
    min_frac_core = float(argval("--min-frac", MIN_FRAC_OF_CORE))

    spath = os.path.join(ROOT, "tools", "subject.json")
    decl = {}
    if os.path.exists(spath):
        with open(spath, encoding="utf-8") as fp:
            decl = json.load(fp).get("pages", {})

    os.makedirs(GUARD, exist_ok=True)
    print("页      主体源                核心占比   实底块  命中  WARN  FAIL  判定")
    print("-" * 88)

    tot_f = tot_w = tot_skip = 0
    allrows = []
    for L in pages():
        pid = L["_pid"]
        if only and pid != only:
            continue
        cw, ch = L["canvas"]["w"], L["canvas"]["h"]
        zs = [z for z in L["zones"] if z.get("box")]
        bases = [z for z in zs if z.get("kind", "text") in BASE_KINDS and z.get("src")]
        if not bases:
            # ★必须计入 SKIP：原来只打印一句就 continue，tot_skip 仍是 0 ——
            #   9 页全部没跑，合计却报「SKIP 0」，**空过且不自知**。
            #   （底图取不到的直接原因曾是 build.js 的白名单漏掉 src，见 build.js 注释。）
            print("%-7s （无底图 → 本页不适用）" % pid)
            tot_skip += 1
            continue

        # 主体核心掩膜 = 各底图核心的并集
        core = np.zeros((ch, cw), bool)
        srcs = []
        for z in bases:
            b = box_px(z["box"], cw, ch)
            bw, bh = max(1, int(round(b[2]))), max(1, int(round(b[3])))
            r = max(1, int(round(erode_frac * min(bw, bh))))

            # 两条掩膜通道：rembg（人像/实拍）→ 近白底连通域（白底产品图）
            cands = []
            a_rem, d_rem = alpha_of(z["src"], pid + "_" + os.path.basename(z["src"]), use_cache, model)
            if a_rem is not None:
                cands.append((d_rem, a_rem))
            fm = flat_mask(z["src"])
            if fm is not None:
                cands.append(("flat底连通域", fm))

            best = None
            for desc, arr in cands:
                arr = np.asarray(Image.fromarray((arr * 255).astype(np.uint8)).resize(
                    (bw, bh), Image.BILINEAR)).astype(np.float32) / 255.0
                c = largest_cc(erode((arr > 0.5).astype(np.float32), r)) > 0.5
                cred_i = c.sum() / float(bw * bh)
                if cred_i >= 0.12:
                    best = (desc, arr, c, cred_i)
                    break
                if best is None or cred_i > best[3]:
                    best = (desc, arr, c, cred_i)
            if best is None:
                srcs.append("无可用掩膜")
                continue
            desc, arr, c, cred_i = best
            srcs.append("%s%.0f%%" % (desc, cred_i * 100))
            x0, y0 = int(max(0, round(b[0]))), int(max(0, round(b[1])))
            x1, y1 = int(min(cw, x0 + bw)), int(min(ch, y0 + bh))
            if x1 > x0 and y1 > y0:
                core[y0:y1, x0:x1] |= c[:y1 - y0, :x1 - x0]

        sdesc = srcs[0] if len(set(srcs)) == 1 else ("混合×%d" % len(srcs))
        core_px = int(core.sum())
        base_area = sum(max(1, int(round(box_px(z["box"], cw, ch)[2]))) *
                        max(1, int(round(box_px(z["box"], cw, ch)[3]))) for z in bases)
        cred = core_px / float(max(1, base_area))
        if core_px == 0 or cred < 0.12:
            boxes = decl.get(pid, [])
            if boxes:
                core = np.zeros((ch, cw), bool)
                for bx in boxes:
                    core[bx["y"]:bx["y"] + bx["h"], bx["x"]:bx["x"] + bx["w"]] = True
                core_px = int(core.sum())
                sdesc = "声明框×%d" % len(boxes)
                cred = core_px / float(max(1, base_area))
            else:
                print("%-7s %-20s  —— 掩膜不可信（核心仅占底图 %.1f%%）且 subject.json 未声明 → SKIP（**不等于通过**）"
                      % (pid, sdesc, cred * 100))
                tot_skip += 1
                allrows.append((pid, sdesc, "SKIP", [], 0))
                continue

        solids = [z for z in zs if is_solid(z)]
        # 排除被更大实底模块完全包含者（嵌套不重复判）
        def contained(z, others):
            b = box_px(z["box"], cw, ch)
            for o in others:
                if o is z or not is_solid(o):
                    continue
                ob = box_px(o["box"], cw, ch)
                if ob[2] * ob[3] > b[2] * b[3] * 1.05 and \
                   ob[0] <= b[0] + 1 and ob[1] <= b[1] + 1 and \
                   ob[0] + ob[2] >= b[0] + b[2] - 1 and ob[1] + ob[3] >= b[1] + b[3] - 1:
                    return True
            return False

        hits = []
        for z in solids:
            if contained(z, zs):
                continue
            b = box_px(z["box"], cw, ch)
            frac = (b[2] * b[3]) / float(cw * ch)
            tier = "小" if frac <= SMALL_FRAC else ("中" if frac <= MEDIUM_FRAC else "大")
            x0, y0 = int(max(0, round(b[0]))), int(max(0, round(b[1])))
            x1, y1 = int(min(cw, round(b[0] + b[2]))), int(min(ch, round(b[1] + b[3])))
            if x1 <= x0 or y1 <= y0:
                continue
            inter = int(core[y0:y1, x0:x1].sum())
            if inter <= 0:
                continue
            cov = inter / float(core_px)
            hit_core = core[y0:y1, x0:x1]
            cover_of_box = inter / float(max(1, (x1 - x0) * (y1 - y0)))
            hits.append({
                "zone": z["id"], "kind": z.get("kind", "text"), "tier": tier,
                "frac": round(frac, 4), "inter": inter,
                "cover_core_pct": round(cov * 100, 3),
                "cover_box_pct": round(cover_of_box * 100, 1),
                "ok": inter <= max(MIN_AREA_PX, core_px * min_frac_core),
            })

        fail = [h for h in hits if h["tier"] == "小" and not h["ok"]]
        warn = [h for h in hits if h["tier"] == "中" and not h["ok"]]
        # 大模块（出血巨字 / 斜置大标 / 附录大卡）本来就压人 → 只进 --detail 报告，不计 WARN
        tot_f += len(fail)
        tot_w += len(warn)
        verdict = "FAIL" if fail else ("WARN" if warn else "OK")
        print("%-7s %-20s %7.1f%%   %5d  %4d  %4d  %4d  %s" % (
            pid, sdesc, core_px / float(cw * ch) * 100, len(solids), len(hits), len(warn), len(fail), verdict))
        allrows.append((pid, sdesc, verdict, hits, len(fail)))

        # 核对图
        shot = os.path.join(ROOT, "_shots", pid + ".png")
        if os.path.exists(shot):
            im = Image.open(shot).convert("RGB")
        else:
            im = Image.new("RGB", (cw, ch), "white")
        ov = np.asarray(im).astype(np.float32).copy()
        ov[core] = ov[core] * 0.35 + np.array([40, 190, 90]) * 0.65
        im2 = Image.fromarray(ov.astype(np.uint8))
        d = ImageDraw.Draw(im2)
        for h in hits:
            z = next(x for x in zs if x["id"] == h["zone"])
            b = box_px(z["box"], cw, ch)
            col = (230, 40, 40) if (h["tier"] == "小" and not h["ok"]) else (
                (240, 150, 30) if not h["ok"] else (110, 110, 110))
            d.rectangle([b[0], b[1], b[0] + b[2], b[1] + b[3]], outline=col, width=3)
            d.text((b[0] + 5, b[1] + 5), "%s[%s] %.2f%%" % (h["zone"], h["tier"], h["cover_core_pct"]), fill=col)
        im2.save(os.path.join(GUARD, pid + "_subject.png"))

    print("-" * 88)
    if tot_skip:
        print("SKIP %d 页 —— 既无掩膜也无声明框：**SKIP ≠ 通过**，补 tools/subject.json 或装 rembg" % tot_skip)
    print("合计：FAIL %d  WARN %d  SKIP %d" % (tot_f, tot_w, tot_skip))
    if detail:
        for pid, sdesc, verdict, hits, nf in allrows:
            if hits:
                print("\n[%s] %s" % (pid, sdesc))
                for h in sorted(hits, key=lambda x: -x["cover_core_pct"]):
                    print("   %-12s %-6s %-2s 框占画布 %5.2f%%  压主体 %5.2f%%  框内被主体占 %5.1f%%  相交 %6dpx²  %s" % (
                        h["zone"], h["kind"], h["tier"], h["frac"] * 100, h["cover_core_pct"],
                        h["cover_box_pct"], h["inter"], "OK" if h["ok"] else "★ 超限"))
    print("\n核对图 -> %s/<page>_subject.png（绿=主体核心；红=小模块越界，橙=中/大模块越界）" % GUARD)
    return 1 if (tot_f or (strict and (tot_w or tot_skip))) else 0


if __name__ == "__main__":
    sys.exit(main())
