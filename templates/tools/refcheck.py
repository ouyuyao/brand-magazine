# -*- coding: utf-8 -*-
"""
refcheck.py —— 硬断言：页数 / 画布尺寸 必须与参考图一致（不符即阻断出图）

为什么必须硬拦（这是本引擎过去最大的漏洞）：
    过去「页数 = layout/ 里 *.json 的个数」——你给了 5 张参考图、只做了 2 页，
    **不会有任何东西报错**；canvas 填错也不会报错，而 canvas 一错，
    pageNN.html 里按 O 键的叠图比对从根上就是失真的（拉伸对齐），根本对不上。
    这两条不是「建议」，是可判定的事实，所以做成硬断言，不合格退出码非 0。

检查项：
    H1  页数 == 参考图张数
    H2  每页 canvas.w / canvas.h == 该页参考图的真实像素尺寸（严格相等）
    H3  每页必须有 ref 字段，且 assets/ref/<ref> 存在
    H4  （提示级）ref 字段与 assets/ref 下的实际文件名大小写 / 扩展名不一致

用法：
    python tools/refcheck.py
    python tools/refcheck.py --allow-missing-ref    # 调试用：跳过 H3（正式交付不要用）
输出：
    _shots/report/refcheck.json + 终端表格
退出码：
    0 全部通过        1 有硬失败（不要进下一步、不要出图）
    2 缺 Pillow / 读图失败
说明：
    若 assets/ref/_stripped 标记存在（由 freeze.js --ref-mode strip 写入），
    表示参考图已按需剥离 → H1/H2/H3 自动降级为 WARN 并跳过（冻结 skill 对外分享时用）。
依赖：只用 Pillow。
"""
import os
import re
import sys
import json

try:
    from PIL import Image
except ImportError:
    print("FAIL 缺 Pillow —— 请先 pip install pillow")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join(ROOT, "layout")
REF = os.path.join(ROOT, "assets", "ref")
REPORT = os.path.join(ROOT, "_shots", "report")
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

ALLOW_MISSING = "--allow-missing-ref" in sys.argv


def layout_pages():
    out = []
    if not os.path.isdir(LAYOUT):
        return out
    for f in sorted(os.listdir(LAYOUT)):
        if not f.endswith(".json") or f.startswith("_"):
            continue
        p = os.path.join(LAYOUT, f)
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            out.append({"file": f, "pid": None, "ref": None, "canvas": None, "error": "JSON 解析失败：%s" % e})
            continue
        num = re.sub(r"\D", "", str(d.get("id") or f))
        pid = ("page" + num.zfill(2)) if num else f
        out.append({"file": f, "pid": pid, "ref": d.get("ref"), "canvas": d.get("canvas"), "error": None})
    return out


def list_refs():
    if not os.path.isdir(REF):
        return []
    out = []
    for f in sorted(os.listdir(REF)):
        p = os.path.join(REF, f)
        if os.path.isdir(p) or f.startswith("_") or f.startswith("."):
            continue
        if f.lower().endswith(EXTS):
            out.append(f)
    return out


def size_of(p):
    try:
        with Image.open(p) as im:
            return im.size
    except Exception:
        return None


def main():
    pages = layout_pages()
    refs = list_refs()
    stripped = os.path.exists(os.path.join(REF, "_stripped"))

    fails = []
    warns = []
    rows = []

    print("=== refcheck：页数与画布尺寸必须与参考图一致 ===")
    print("layout/ 页数 %d   assets/ref/ 参考图 %d 张%s" %
          (len(pages), len(refs), "（已剥离标记存在）" if stripped else ""))

    if not pages:
        fails.append("H1 layout/ 里没有版式 JSON —— 还没解析参考图，无法出图")

    if stripped:
        warns.append("参考图已剥离（freeze --ref-mode strip）：H1/H2/H3 跳过")
    else:
        # H1
        if len(pages) != len(refs):
            if len(refs) > len(pages):
                extra = [f for f in refs if f not in [(p.get("ref") or "") for p in pages]]
                fails.append("H1 页数不符：layout/ 有 %d 个 JSON，assets/ref/ 有 %d 张参考图 —— "
                             "多余的参考图：%s（或缺少对应 layout）"
                             % (len(pages), len(refs), "、".join(extra) or "（按 ref 字段算）"))
            else:
                fails.append("H1 页数不符：layout/ 有 %d 个 JSON，assets/ref/ 只有 %d 张参考图 —— "
                             "有页没解析到参考图，或 ref 指向的文件不存在"
                             % (len(pages), len(refs)))

        # H2 / H3 / H4
        refmap = {}
        for f in refs:
            refmap[f.lower()] = f
            refmap[os.path.splitext(f)[0].lower()] = f

        for p in pages:
            row = {"pid": p["pid"], "file": p["file"], "ref": p["ref"], "canvas": p["canvas"], "ok": True}
            if p["error"]:
                fails.append("%s（layout/%s）：%s" % (p["pid"], p["file"], p["error"]))
                row["ok"] = False
                rows.append(row)
                continue

            if not p["ref"]:
                if ALLOW_MISSING:
                    warns.append("%s 缺 ref 字段（--allow-missing-ref 已跳过）" % p["pid"])
                else:
                    fails.append("H3 %s 缺 \"ref\" 字段 —— 每页必须有参考图，否则无法做骨架级复刻校验" % p["pid"])
                    row["ok"] = False
                rows.append(row)
                continue

            hit = refmap.get(str(p["ref"]).lower())
            if hit is None:
                fails.append("H3 %s 的 ref「%s」在 assets/ref/ 里找不到 —— "
                             "请把参考图放进 assets/ref/，或修正 ref 文件名" % (p["pid"], p["ref"]))
                row["ok"] = False
            else:
                if hit != p["ref"]:
                    warns.append("H4 %s 的 ref「%s」与实际文件名「%s」大小写或扩展名不一致"
                                 % (p["pid"], p["ref"], hit))
                real = size_of(os.path.join(REF, hit))
                row["real"] = list(real) if real else None
                if not real:
                    fails.append("H2 %s 的参考图 %s 读取失败（文件损坏？）" % (p["pid"], hit))
                    row["ok"] = False
                else:
                    cv = p["canvas"] or {}
                    cw, ch = cv.get("w"), cv.get("h")
                    if not cw or not ch:
                        fails.append("H2 %s 缺 canvas.w / canvas.h" % p["pid"])
                        row["ok"] = False
                    elif (cw, ch) != real:
                        fails.append("H2 %s canvas %dx%d ≠ 参考图 %s 实际 %dx%d（差 %+d×%+d）—— "
                                     "请把 canvas 改成参考图真实尺寸，或换回原始分辨率的参考图"
                                     % (p["pid"], cw, ch, hit, real[0], real[1], cw - real[0], ch - real[1]))
                        row["ok"] = False
            rows.append(row)

    # ---------- 输出 ----------
    os.makedirs(REPORT, exist_ok=True)
    with open(os.path.join(REPORT, "refcheck.json"), "w", encoding="utf-8") as fp:
        json.dump({"_doc": "硬断言结果。exit 1 = 不要进下一步、不要出图。",
                   "pages": rows, "refCount": len(refs), "fails": fails, "warns": warns},
                  fp, ensure_ascii=False, indent=1)

    print("")
    print("  页       参考图                 canvas        参考图实际      判定")
    print("  -------- ---------------------- -------------- --------------  ----")
    for r in rows:
        canvas = r.get("canvas") or {}
        cs = "%sx%s" % (canvas.get("w", "-"), canvas.get("h", "-"))
        rl = r.get("real")
        rs = "%dx%d" % (rl[0], rl[1]) if rl else "-"
        print("  %-8s %-22s %-14s %-14s  %s" % (r["pid"], str(r.get("ref") or "-"), cs, rs,
                                                "OK" if r.get("ok") else "FAIL"))
    print("")
    for w in warns:
        print("  WARN " + w)
    if fails:
        for f in fails:
            print("  FAIL " + f)
        print("")
        print("FAIL 合计 %d 项 —— 先修掉再 node build.js / shoot.js（不要出图）" % len(fails))
        sys.exit(1)

    if stripped:
        print("OK  %d 页版式就绪；参考图已剥离（freeze --ref-mode strip），"
              "H1/H2/H3 不适用 —— 骨架已固化在 layout/*.json。" % len(pages))
    else:
        print("OK  页数 %d == 参考图 %d 张；每页 canvas 与参考图真实尺寸一致。"
              % (len(pages), len(refs)))
    print("-> _shots/report/refcheck.json")
    sys.exit(0)


if __name__ == "__main__":
    main()
