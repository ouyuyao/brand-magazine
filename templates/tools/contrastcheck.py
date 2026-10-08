# -*- coding: utf-8 -*-
"""
contrastcheck.py —— 「文字压在照片上读不读得出来」（告警级，恒退出 0）

为什么需要它：
    现有的几套判据都不查这件事 ——
      copycheck  查槽位数量与禁用词
      check_faces查标签是否压住五官
      blockcheck 查照片块是否互压
      inkprobe   查字重（同一字号下的墨迹粗细）
    「这段字压在浅色皮肤／薄纱上还看得清吗」是另一个问题，**没人查**。
    封面／跨页那种「文字直接压在写真上」的版面，最容易在这里翻车：
    站位全对、字重全对，但灰字压在中间调的皮肤上就是读不出来。

口径（关键：用**声明色**而不是实测最暗像素）：
    小字号（尤其 9–11px）在渲染时被抗锯齿摊薄，实测最暗像素会比字色浅很多，
    直接量实测值会把「白底上的深灰小字」误报成对比度不足。
    所以本脚本取 layout 里 `style.color` 的**令牌值**当字色，
    只把**背景**交给实测 —— 背景才是照片真正决定的那一半。

    背景用框内灰度的**中位数**（＝文字实际落座的那层底色）。
    另外报 `spread` = p90−p10：
      spread 小 → 底是平的，这一个对比度就够说明问题；
      spread 大 → 框里混进了与文字无关的明暗（例如同一行横跨浅墙与深发），
                  这时按中位数判，并把 spread 标出来提醒人工看叠图。

    初版曾直接取 p10 与 p90 里「对字色更差的那一侧」当背景，结果把
    「框内恰好有一块深发/阴影、而文字其实落在浅处」的情况全判成不足
    （实测出现 1.01–1.4 的假低值）。**判据必须落在文字真正坐着的那层底上。**

    ★声明了 `occlude` 的块跳过本判据（标 SKIP，不静默）：
      它的框是被主体有意盖住的一大半，框内中位色是「头发/皮肤」而不是字的底，
      算出来的比值（实测 1.03）量的是「字 vs 遮挡物」——而遮挡物的意义恰恰是**不该**看见。
      这类块的规矩在 ⑩ 遮挡关系（掩膜的洞里该不该有字）与 check_faces（不许压五官）。
      跳过必须**有原则、写进输出**，否则就是「报不出来就当没问题」的老毛病。

用法：
    python tools/contrastcheck.py
    python tools/contrastcheck.py [page01 page03] [--body 4.5] [--big 3.0] [--bigsize 18]
    python tools/contrastcheck.py --json        # 机器可读
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEXT_KINDS = {'text', 'badge', 'torn', 'bubble', 'label'}


def load_tokens():
    """css/tokens.css → brand/_skin.css（后者覆盖前者）。"""
    tok = {}
    for p in (os.path.join(ROOT, 'css', 'tokens.css'),
              os.path.join(ROOT, 'brand', '_skin.css')):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding='utf-8').read()
        for name, val in re.findall(r'--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})', txt):
            tok[name] = val
    return tok


def _lin(v):
    v = v / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def hex2lum(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def grey2lum(v):
    """灰度值（0–255）→ 相对亮度。"""
    return _lin(float(v))


def ratio(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    def opt(n, d):
        return float(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d

    need_body, need_big = opt('--body', 4.5), opt('--big', 3.0)
    bigsize, as_json = opt('--bigsize', 18), '--json' in sys.argv

    from PIL import Image
    import numpy as np

    tok = load_tokens()
    if not tok:
        raise SystemExit('读不到 css/tokens.css 的令牌')
    pages = args or ['page%02d' % i for i in range(1, 99)
                     if os.path.exists(os.path.join(ROOT, '_shots', 'page%02d.png' % i))]
    if not pages:
        raise SystemExit('_shots/ 下没有 pageNN.png，先跑 tools/shoot.js')

    rows, worst = [], []
    # ★版式坐标统一走 _lay（读 build 期折算过 parent 的 layout/_resolved.json）：
    #   直读 layout 原文时，白卡内的文字会按「相对父框」的小坐标取样，判据全错位。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _lay
    zone_pages = _lay.load_zone_pages(ROOT)
    for pid in pages:
        shot = os.path.join(ROOT, '_shots', pid + '.png')
        if not (os.path.exists(shot) and pid in zone_pages):
            continue
        im = np.asarray(Image.open(shot).convert('L'), dtype=float)
        H, W = im.shape
        for z in zone_pages[pid]['zones']:
            if (z.get('kind') or 'text') not in TEXT_KINDS:
                continue
            st, box = z.get('style') or {}, z.get('box')
            if not isinstance(box, list) or len(box) != 4:
                continue
            col = tok.get(str(st.get('color', 'ink')), '#1a1815')
            size = float(st.get('size', 12))
            x, y, w, h = box
            b = im[max(0, int(y * H)):int((y + h) * H), max(0, int(x * W)):int((x + w) * W)]
            if b.size < 64:
                continue
            # ★声明了 occlude 的块**不按底的对比度判**：
            #   它的框是被主体有意盖住的一大半，框内的中位色是「头发/皮肤」，不是字的底。
            #   拿它算比值，量到的是「字与遮挡物」的关系 —— 而遮挡物的意义恰恰是**不该**看见。
            #   这类块的判据在 ⑩ 遮挡关系（掩膜的洞里该不该有字）与 check_faces（不许压五官）。
            #   报出来但标 SKIP，不做进 fail 计数，也不静默跳过。
            if z.get('occlude'):
                rows.append({'page': pid, 'zone': z['id'], 'size': size, 'need': None,
                             'contrast': None, 'spread': float(np.percentile(b, 90) - np.percentile(b, 10)),
                             'ok': True, 'mixed': False, 'skip': 'occluded'})
                continue
            li = hex2lum(col)
            p10, p90 = np.percentile(b, 10), np.percentile(b, 90)
            c = ratio(li, grey2lum(np.median(b)))          # 典型：文字落座的那层底
            spread = float(p90 - p10)
            need = need_big if size >= bigsize else need_body
            rows.append({'page': pid, 'zone': z['id'], 'size': size, 'need': need,
                         'contrast': round(c, 2), 'spread': round(spread, 1),
                         'ok': c >= need, 'mixed': spread > 60})
            if c < need:
                worst.append(rows[-1])

    if as_json:
        print(json.dumps({'rows': rows, 'fail': len(worst)}, ensure_ascii=False, indent=1))
        return

    print('%-7s %-14s %6s %7s %6s %8s   %s'
          % ('page', 'zone', 'size', 'contrast', 'spread', 'need', '判定'))
    for r in rows:
        if r.get('skip') == 'occluded':
            print('%-7s %-14s %6.1f %7s %6.1f %8s   SKIP 声明了 occlude（框被主体有意盖住）'
                  % (r['page'], r['zone'], r['size'], '—', r['spread'], '—'))
            continue
        mark = 'OK' if r['ok'] else '★ 不足'
        if r['mixed']:
            # ★spread 大 = 框里混进了与文字无关的明暗（同一行横跨浅墙与深发/皮肤）。
            #  这时那个「不足」是**混合底色算出来的伪值**，不是字真的看不见 ——
            #  参考刊自己的粉字也是压在脸颊上的（④ 对比角色的既定做法）。
            #  所以标成「待人工」而不是「不足」：直接判不足会把人引去无谓地加深字色，
            #  而加深之后压在浅底那头反而变糟。判据要能说出「我这次量不准」。
            mark = '低值(底不匀→人工对叠图)' if not r['ok'] else 'OK(底不匀→人工对叠图)'
        print('%-7s %-14s %6.1f %7.2f %6.1f %8.1f   %s'
              % (r['page'], r['zone'], r['size'], r['contrast'], r['spread'],
                 r['need'], mark))
    n_skip = sum(1 for r in rows if r.get('skip'))
    n_mixed = sum(1 for r in rows if r.get('mixed') and not r.get('skip'))
    n_clear = sum(1 for r in rows if not r.get('ok') and not r.get('mixed') and not r.get('skip'))
    print('\n合计 %d 项（另 %d 项因 occlude 跳过）：**明确不足 %d 项**、'
          '底不匀待人工 %d 项（阈值：正文 %.1f / ≥%gpx 大字 %.1f；spread>60 视为底不匀）'
          % (len(rows) - n_skip, n_skip, n_clear, n_mixed, need_body, bigsize, need_big))
    if n_clear:
        print('★ 明确不足 %d 项（底是平的，这个读数可信）：' % n_clear)
        for r in rows:
            if not r.get('ok') and not r.get('mixed') and not r.get('skip'):
                print('   %s  %s  %.2f < %.1f' % (r['page'], r['zone'], r['contrast'], r['need']))
    if n_mixed:
        print('★ 底不匀 %d 项：读数受「同一行横跨浅底与深底」污染，**不要直接照着加深** ——'
              '加深后压在浅底那头会更糟。逐条对参考刊的叠图看。' % n_mixed)
    if worst:
        print('★ 提醒：本判据是**告警级**，不阻断出图。')
        print('  杂志封面脚注压在写真上时，做到正文 4.5 常常不现实 ——')
        print('  先看它是不是**功能性信息**（价格注释／尺寸／法务注记）：是，就必须处理；')
        print('  纯装饰性的刊头小字，可以按参考刊的惯例留在 3.0 上下。')


if __name__ == '__main__':
    main()
