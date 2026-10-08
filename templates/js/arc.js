/* =========================================================================
   arc.js —— 弧排文字（文字沿圆弧排布）
   -------------------------------------------------------------------------
   为什么不在 build.js 里直接吐 SVG：
     弧上的文案来自文案引擎（copy/issue.js），build 时页里只有占位文本；
     而且切换语言（jp/zh）后必须能重排。所以做成**运行时增强**。

   ★关键设计：不新建文本节点，而是把 `.t` 里**已有的那个直接文本节点**
     appendChild 搬进 <textPath>。copy.js 缓存的就是同一个节点对象
     （`CACHE.map[sel] = nodes`），所以切语言时它改 nodeValue，弧上的字照样更新。
     若新建节点，切语言后弧排文字就会卡在第一次的内容上。

   版式侧写法（layout JSON）：
     { "id":"cover-arc", "kind":"text", "box":[...], "tpl":"${1}",
       "arc": { "cx":0.5, "cy":1.55, "r":0.62, "mid":-90, "face":"out", "span":null },
       "style": { "font":"script-fat", "size":56, "color":"accent" } }

   几何约定（★写死，不要反）
     cx, cy  圆心，**相对本框**的归一化坐标（可超出 0–1）；
             cy 为负 → 圆心在框上方 → 弧向下凸（笑脸 / 下垂弧）
             cy 大于 1 → 圆心在框下方 → 弧向上凸（拱形 / 彩虹弧）
     r      半径，**相对本框宽度**
     mid    弧中点角度（度）：0=右，90=下，-90=上，180=左
     span   可选：限定扫角（度）。null / 省略 → **按文字实际长度自动撑弧**
     pad    可选：自动撑弧时的余量倍数，默认 1.06

   ★方向自动判定（没有 face / dir 这类旋钮，就是为了不让人写出倒着的字）
     弧一旦定下来，能「从左读到右且字形朝上」的方向只有一个，引擎自己选：
       圆心在上（cy<0，下垂弧）→ 取 θ 递减方向 → 字形顶朝圆心（即朝上）
       圆心在下（cy>1，上拱弧）→ 取 θ 递增方向 → 字形顶背离圆心（即朝上）
     两种情况结果都是「左→右、正立」，不必也不该由人指定。

   自动撑弧为什么必要：
     <textPath> 超出路径长度的部分**不绘制**（Chrome 直接截断），
     所以「弧太短」会静默吃掉半句文案。这里先量字宽再定扫角，杜绝这种静默截断。
   ========================================================================= */
(function ($) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var DEG = Math.PI / 180;

  function directTextNode(el) {
    for (var n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && n.nodeValue.replace(/[\s\u3000]+/g, '') !== '') return n;
    }
    return null;
  }

  /* 用与被搬走前完全相同的排版样式量字宽 */
  function measure(text, cs) {
    var s = document.createElement('span');
    s.style.cssText = 'position:absolute;left:-99999px;top:0;visibility:hidden;white-space:pre;' +
      'font-family:' + cs.fontFamily + ';font-size:' + cs.fontSize + ';font-weight:' + cs.fontWeight +
      ';font-style:' + cs.fontStyle + ';letter-spacing:' + cs.letterSpacing +
      ';font-variant:' + cs.fontVariant;
    s.textContent = text;
    document.body.appendChild(s);
    var w = s.getBoundingClientRect().width;
    document.body.removeChild(s);
    return w;
  }

  function enhance(zEl) {
    var spec;
    try { spec = JSON.parse(zEl.getAttribute('data-arc') || '{}'); } catch (e) { return; }
    var t = null;
    for (var i = 0; i < zEl.children.length; i++) {
      if (zEl.children[i].classList.contains('t')) { t = zEl.children[i]; break; }
    }
    if (!t) return;

    var node = t.__arcNode || directTextNode(t);
    if (!node) return;
    var text = node.nodeValue;
    if (!text || !text.replace(/\s+/g, '')) return;

    var cs = getComputedStyle(t);
    var L = measure(text, cs);

    var W = zEl.clientWidth, H = zEl.clientHeight;
    if (!W || !H) return;
    var cx = (spec.cx == null ? 0.5 : spec.cx) * W;
    var cy = (spec.cy == null ? 1.0 : spec.cy) * H;
    var R = (spec.r == null ? 0.8 : spec.r) * W;
    var mid = (spec.mid == null ? -90 : spec.mid) * DEG;

    var half;
    if (spec.span) {
      half = Math.abs(spec.span) * DEG / 2;
    } else {
      var pad = spec.pad == null ? 1.06 : spec.pad;
      half = (L * pad / R) / 2;            // 弧长 = R·2·half
      half = Math.min(half, Math.PI * 0.98);
    }

    /* face:'out' → θ 递增（字形顶朝外）；face:'in' → θ 递减 */
    var tA = mid - half, tB = mid + half;
    function P(th) { return [cx + R * Math.cos(th), cy + R * Math.sin(th)]; }
    /* ★方向自动判定：始终取「从左读到右」的那一端为起点。
       配合同一方向下「字形顶朝上」的几何事实，结果恒为正立左→右文字。 */
    var t0, t1;
    if (P(tB)[0] >= P(tA)[0]) { t0 = tA; t1 = tB; } else { t0 = tB; t1 = tA; }
    var p0 = P(t0), p1 = P(t1);
    var large = (Math.abs(t1 - t0) > Math.PI) ? 1 : 0;
    var sweep = (t1 > t0) ? 1 : 0;
    var d = 'M ' + p0[0].toFixed(2) + ' ' + p0[1].toFixed(2) +
      ' A ' + R.toFixed(2) + ' ' + R.toFixed(2) + ' 0 ' + large + ' ' + sweep + ' ' +
      p1[0].toFixed(2) + ' ' + p1[1].toFixed(2);

    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'arc-svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', W);
    svg.setAttribute('height', H);
    svg.setAttribute('preserveAspectRatio', 'none');
    var defs = document.createElementNS(NS, 'defs');
    var path = document.createElementNS(NS, 'path');
    var pid = 'arcpath-' + zEl.id;
    path.setAttribute('id', pid);
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    defs.appendChild(path);
    var tx = document.createElementNS(NS, 'text');
    tx.setAttribute('dominant-baseline', spec.baseline || 'auto');
    var tp = document.createElementNS(NS, 'textPath');
    tp.setAttribute('href', '#' + pid);
    tp.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', '#' + pid);
    tp.setAttribute('startOffset', '50%');
    tp.setAttribute('text-anchor', 'middle');
    tp.appendChild(node);            // ★ 搬运原节点，不复制
    tx.appendChild(tp);
    svg.appendChild(defs);
    svg.appendChild(tx);

    var old = t.querySelector('.arc-svg');
    if (old) old.parentNode.removeChild(old);
    t.appendChild(svg);
    t.__arcNode = node;
    zEl.setAttribute('data-arc-done', '1');
    /* 供判据读：弧的实际几何 */
    zEl.setAttribute('data-arc-arc', [Math.round(R), Math.round(t0 / DEG), Math.round(t1 / DEG)].join(','));
  }

  function run() {
    var list = document.querySelectorAll('[data-arc]');
    for (var i = 0; i < list.length; i++) enhance(list[i]);
  }

  window.__arc = { run: run, count: function () { return document.querySelectorAll('[data-arc-done]').length; } };

  $(function () {
    run();
    /* copy.js 的 apply() 在它自己的 ready 里已经跑过（脚本顺序保证），
       这里再挂一次语言切换，保证 zh 稿也能重排。 */
    $(document).on('copy:lang', run);
  });
})(jQuery);
