# -*- coding: utf-8 -*-
"""
refgrid.py —— 参考图百分比坐标网 / 参考图↔成品叠图 / 差异热图 / 局部放大取证

为什么需要它：
    「解析参考图」需要**可读的数**，不是靠眼睛估。本工具把百分比坐标网直接叠在
    参考图上（每 5% 细线、每 10% 粗线并标百分比），读数就能写进 layout 的 box；
    出图之后还能把成品与参考图叠起来、算出差异热图，用来判断「复刻到什么程度」。
    这是 pagNN.html 里按 O 键的「三态叠图」的数据来源。

用法：
    python tools/refgrid.py p01.jpg                      # 只出参考图百分比坐标网
    python tools/refgrid.py p01.jpg --shot page01        # 坐标网 + 叠图 + 差异热图
    python tools/refgrid.py page01                       # 也可以直接用页码（自动查 layout 的 ref）
    python tools/refgrid.py p01.jpg --zoom 4 --crop 0.04,0.56,0.30,0.14
                                                         # 局部放大 + 带页面百分比尺（字体识别取证用）
输出（都在 assets/ref/_grid/）：
    <name>_grid.png     参考图 + 百分比坐标网
    <name>_overlay.png  参考图 ↔ 成品 半透明叠图
    <name>_diff.png     差异热图（深蓝=一致，红=差异大）—— pageNN.html 的「叠差异图」用它
    <name>_zoom.png     局部放大 + 页面百分比尺
退出码：0 成功   2 缺 Pillow / 找不到参考图或成品
依赖：只用 Pillow（不联网）。
"""
import os
import re
import sys
import json

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter
except ImportError:
    print("FAIL 缺 Pillow —— 请先 pip install pillow")
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "assets", "ref")
SHOTS = os.path.join(ROOT, "_shots")
LAYOUT = os.path.join(ROOT, "layout")
OUT = os.path.join(REF, "_grid")
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


def argval(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def fnt(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def find_ref_file(name):
    """把 'p01' 或 'p01.jpg' 解析成真实文件路径。"""
    base = os.path.splitext(name)[0]
    for f in sorted(os.listdir(REF)):
        p = os.path.join(REF, f)
        if os.path.isdir(p) or f.startswith("_"):
            continue
        if not f.lower().endswith(EXTS):
            continue
        if f == name or os.path.splitext(f)[0] == base:
            return f, p
    return None, None


def ref_from_page(page):
    """pageNN → layout 里的 ref 字段。"""
    m = re.match(r"^page0*(\d+)$", page, re.I)
    if not m:
        return None
    want = int(m.group(1))
    if not os.path.isdir(LAYOUT):
        return None
    for f in sorted(os.listdir(LAYOUT)):
        if not f.endswith(".json") or f.startswith("_"):
            continue
        try:
            d = json.load(open(os.path.join(LAYOUT, f), encoding="utf-8"))
        except Exception:
            continue
        num = re.sub(r"\D", "", str(d.get("id") or f))
        if num and int(num) == want:
            return d.get("ref")
    return None


def heat_lut():
    """深蓝 → 青 → 黄 → 红 的 256 色查找表。"""
    stops = [(0.0, (8, 16, 72)), (0.25, (0, 110, 190)), (0.5, (0, 205, 205)),
             (0.75, (250, 215, 60)), (1.0, (235, 45, 45))]
    pal = []
    for i in range(256):
        t = i / 255.0
        for k in range(len(stops) - 1):
            a, ca = stops[k]
            b, cb = stops[k + 1]
            if a <= t <= b:
                u = (t - a) / (b - a) if b > a else 0.0
                pal.extend([int(ca[j] + (cb[j] - ca[j]) * u) for j in range(3)])
                break
    while len(pal) < 768:
        pal.extend([0, 0, 0])
    return pal


def to_heat(diff_L):
    """灰度差异图 → 热图 RGB（先按 P95 拉伸，避免个别像素拉爆）。"""
    hist = diff_L.histogram()
    tot = sum(hist) or 1
    acc = 0
    p95 = 255
    for k in range(256):
        acc += hist[k]
        if acc >= tot * 0.95:
            p95 = k
            break
    p95 = max(p95, 1)
    scaled = diff_L.point(lambda v: min(255, int(v * 255.0 / p95)))
    heat = Image.new("P", scaled.size)
    heat.putdata(list(scaled.tobytes()))
    heat.putpalette(heat_lut())
    return heat.convert("RGB")


def draw_grid(im):
    W, H = im.size
    d = ImageDraw.Draw(im, "RGBA")
    f = fnt(max(12, W // 95))
    for p in range(0, 101, 5):
        x = int(round(p / 100.0 * W))
        y = int(round(p / 100.0 * H))
        bold = (p % 10 == 0)
        fill = (255, 0, 140, 215) if bold else (255, 130, 195, 105)
        d.line([(x, 0), (x, H)], fill=fill, width=2 if bold else 1)
        d.line([(0, y), (W, y)], fill=fill, width=2 if bold else 1)
        if bold:
            d.text((x + 3, 3), str(p), fill=(185, 0, 90, 255), font=f)
            d.text((3, y + 3), str(p), fill=(185, 0, 90, 255), font=f)
    return im


def draw_zoom_ruler(im, x0, y0, w, h):
    """在放大图上画「页面百分比」尺（每 1% 一条细线并标数）。"""
    W, H = im.size
    d = ImageDraw.Draw(im, "RGBA")
    f = fnt(max(13, W // 60))
    for k in range(0, 101):
        fx = k / 100.0
        if x0 <= fx <= x0 + w:
            px = int((fx - x0) / w * W)
            d.line([(px, 0), (px, H)], fill=(0, 190, 255, 150), width=1)
            d.text((px + 2, 2), str(k), fill=(0, 80, 190, 255), font=f)
        fy = k / 100.0
        if y0 <= fy <= y0 + h:
            py = int((fy - y0) / h * H)
            d.line([(0, py), (W, py)], fill=(0, 190, 255, 150), width=1)
            d.text((3, py + 2), str(k), fill=(0, 80, 190, 255), font=f)
    return im


def main():
    import _cli
    args = _cli.positionals()     # ★只取开头的连续段，避免把 --shot/--crop 的值当成 target
    if not args:
        print("用法：python tools/refgrid.py <参考图文件名 或 pageNN> [--shot pageNN] [--zoom 4 --crop x,y,w,h]")
        sys.exit(2)
    target = args[0]
    shot = argval("--shot")
    zoom = float(argval("--zoom", "0"))
    crop = argval("--crop")

    if re.match(r"^page0*\d+$", target, re.I):
        refname = ref_from_page(target)
        if not refname:
            print("FAIL 在 layout/ 里找不到 %s 的 ref 字段" % target)
            sys.exit(2)
        shot = shot or target
    else:
        refname = target

    bare, path = find_ref_file(refname)
    if not path:
        print("FAIL 找不到参考图：assets/ref/%s" % refname)
        sys.exit(2)
    name = os.path.splitext(bare)[0]
    os.makedirs(OUT, exist_ok=True)

    ref = Image.open(path).convert("RGB")

    # ① 百分比坐标网
    g = draw_grid(ref.copy())
    g.save(os.path.join(OUT, name + "_grid.png"))
    print("-> assets/ref/_grid/%s_grid.png  (%dx%d)" % (name, g.width, g.height))

    # ② 叠图 + 差异热图
    if shot:
        sp = os.path.join(SHOTS, shot + ".png")
        if not os.path.exists(sp):
            print("WARN 找不到成品 %s —— 先跑 node tools/shoot.js（本次跳过叠图与差异图）"
                  % os.path.join("_shots", shot + ".png").replace("\\", "/"))
        else:
            sh = Image.open(sp).convert("RGB")
            if sh.size != ref.size:
                print("WARN 成品 %dx%d 与参考图 %dx%d 尺寸不同 —— 已按参考图尺寸缩放后再叠（"
                      "这也说明 canvas 与参考图不一致，refcheck.py 会拦）"
                      % (sh.width, sh.height, ref.width, ref.height))
                sh = sh.resize(ref.size, LANCZOS)
            Image.blend(ref, sh, 0.5).save(os.path.join(OUT, name + "_overlay.png"))
            r = max(1, int(0.004 * ref.width))
            ga = ref.convert("L").filter(ImageFilter.GaussianBlur(r))
            gb = sh.convert("L").filter(ImageFilter.GaussianBlur(r))
            diff = ImageChops.difference(ga, gb)
            to_heat(diff).save(os.path.join(OUT, name + "_diff.png"))
            print("-> assets/ref/_grid/%s_overlay.png" % name)
            print("-> assets/ref/_grid/%s_diff.png   （pageNN.html 按 O 的第三态用它）" % name)

    # ③ 局部放大 + 百分比尺（字体识别取证）
    if zoom > 0 and crop:
        try:
            x, y, w, h = [float(v) for v in crop.split(",")]
        except Exception:
            print("FAIL --crop 需要 x,y,w,h 四个 0–1 的小数")
            sys.exit(2)
        W, H = ref.size
        box = (int(x * W), int(y * H), min(W, int((x + w) * W)), min(H, int((y + h) * H)))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            print("FAIL --crop 区域太小")
            sys.exit(2)
        c = ref.crop(box)
        c = c.resize((max(8, int(c.width * zoom)), max(8, int(c.height * zoom))), LANCZOS)
        c = draw_zoom_ruler(c, x, y, w, h)
        c.save(os.path.join(OUT, name + "_zoom.png"))
        print("-> assets/ref/_grid/%s_zoom.png  (%dx%d, 放大 %.1fx)" % (name, c.width, c.height, zoom))

    print("完成。读数写进 layout/NN.json 的 box（归一化 [x,y,w,h]）。")


if __name__ == "__main__":
    main()
