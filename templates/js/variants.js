/* =========================================================================
   variants.js —— 版式变体引擎（品牌无关版）
   -------------------------------------------------------------------------
   为什么要有：同一套模板反复用，每套产出长得一模一样，一眼看出是「同一个模子」。
   这里让每次生成能抽一组微扰（页边母题 / 照片调色 / 标题字距 / 微旋转 / 相纸厚度 /
   分块次序），但**用一个 seed 完全复现** —— 同 seed 同结果，建议拿 SKU 名当 seed
   （天然「一物一版」）。

   与 yurutae 版的区别（本次泛化的三件事）：
     ① **删掉色板轴（palette）** —— 颜色属于品牌层（brand/brand-pack.json），
        变体引擎再定义一套 --accent 就等于越过品牌层，属越权。这里只用品牌 tokens。
     ② **不再靠页面私有类名猜**（`.hero` / `.polaroid` / `.prod` / `.row` …）。
        改成读 layout JSON 里显式声明的白名单：zone 上写 `"variant":["rotate","frame"]`
        → build.js 烘成 `data-variant-allow="rotate frame"`。**没声明的 zone 一律不动。**
     ③ **seed 为 null 时严格零扰动** —— 复刻优先；要变体必须显式给 seed。

   轴（全部由 seed 决定）：
     页面级  [data-motif]   页边母题   none / dots / rule / arc / band / corner
             [data-grade]   照片调色   none / warm / cool / film（只动 .z--image img）
             --v-track      标题字距微调（em）
     zone 级 rotate / frame / reorder —— 只作用于声明了白名单的 zone

   用法：
     page03.html                      → 原始复刻版（不变体；data-seed 为空且无 ?seed=）
     page03.html?seed=7               → 第 7 号变体
     page03.html?seed=ooo-carrot      → 字符串 seed
     page03.html?seed=random          → 随机抽一个并把 seed 写回网址（可分享）
     node build.js --seed ooo-carrot  → 把 seed 烘进 <html data-seed>（出图时直接生效）

   依赖：jQuery（本地 js/vendor/jquery-3.7.1.min.js）
   ========================================================================= */
(function ($) {
  'use strict';

  var MOTIFS = ['none', 'dots', 'rule', 'arc', 'band', 'corner'];
  var FRAMES = ['normal', 'thin', 'wide'];
  var GRADES = ['none', 'warm', 'cool', 'film'];

  /* ---------------- 种子 → 乱数（mulberry32，可复现） ---------------- */
  function hashSeed(str) {
    var h = 2166136261 >>> 0;                       /* FNV-1a */
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function pick(rnd, arr) { return arr[Math.floor(rnd() * arr.length) % arr.length]; }
  function range(rnd, lo, hi) { return lo + rnd() * (hi - lo); }

  /* ---------------- seed 来源：?seed= 优先，其次 build 时烘的 <html data-seed> ---------------- */
  function readSeed() {
    var m = /[?&]seed=([^&#]*)/.exec(location.search);
    if (m) {
      var raw = decodeURIComponent(m[1] || '');
      if (raw === 'random') {
        raw = String(Math.floor(Math.random() * 9000) + 100);   /* 100–9099 */
        var u = location.pathname + location.search.replace(/([?&])seed=random/, '$1seed=' + raw) + location.hash;
        try { history.replaceState(null, '', u); } catch (e) { }
      }
      return raw || null;
    }
    var baked = document.documentElement.getAttribute('data-seed');
    return baked || null;             /* build.js --seed <slug> 写进来的 */
  }

  /* ---------------- 微旋转：保留原角度，只加小扰动 ---------------- */
  function jitterRotate(el, deltaDeg) {
    var t = getComputedStyle(el).transform, base = 0;
    if (t && t !== 'none') {
      var m = t.match(/matrix\(([^)]+)\)/);
      if (m) {
        var p = m[1].split(',').map(parseFloat);
        base = Math.atan2(p[1], p[0]) * 180 / Math.PI;      /* 既有角度 */
      }
    }
    el.style.transform = 'rotate(' + (base + deltaDeg).toFixed(2) + 'deg)';
  }

  /* ---------------- 白名单：只取显式声明该轴的 zone ---------------- */
  function allow(axis) { return $('[data-variant-allow~="' + axis + '"]'); }

  /* ---------------- 主流程 ---------------- */
  function apply(seedRaw) {
    var rnd = mulberry32(hashSeed(seedRaw));
    var motif = pick(rnd, MOTIFS);
    var frame = pick(rnd, FRAMES);
    var grade = pick(rnd, GRADES);
    var track = range(rnd, -0.012, 0.022);          /* 标题字距扰动（em） */
    var rotJit = range(rnd, -1.5, 1.5);             /* 微旋转 */
    var framing = rnd() > 0.5;                      /* 是否重取景 */
    var reverseRow = rnd() > 0.55;                  /* 分块是否反序 */

    var html = document.documentElement;
    html.setAttribute('data-variant', seedRaw);
    html.setAttribute('data-motif', motif);
    html.setAttribute('data-frame', frame);
    html.setAttribute('data-grade', grade);
    html.style.setProperty('--v-track', track.toFixed(4) + 'em');

    var $page = $('.page');
    $page.attr('data-motif', motif).attr('data-frame', frame);
    /* 一定 append（不能 prepend）：.v-motif 若插成第一个子元素，会让 .page 下所有 div 的
       :nth-of-type 位次 +1，槽位选择器（#id > .t 之外那些 nth 写法）就会整体错位。
       插在最后只影响 :last-of-type（没人用），且 .v-motif 自身 z-index:1 不受插入位置影响。 */
    if (!$page.find('.v-motif').length) $page.append('<div class="v-motif"></div>');

    /* 重取景：只动显式声明 framing 的图片框，且不动已经指定了 object-position 的 */
    if (framing) {
      allow('framing').find('img').each(function () {
        var cs = getComputedStyle(this);
        if (cs.objectPosition !== '50% 50%') return;
        this.style.objectPosition = Math.round(range(rnd, 32, 68)) + '% center';
      });
    }

    /* 微旋转：只动显式声明 rotate 的 zone，幅度 ±1.5° */
    if (Math.abs(rotJit) > 0.25) {
      allow('rotate').each(function () { jitterRotate(this, rotJit); });
    }

    /* 分块反序：只动显式声明 reorder 的容器（子元素整体倒序，配对的图文一起搬，不会张冠李戴） */
    if (reverseRow) {
      allow('reorder').each(function () {
        var $p = $(this), kids = $p.children().get();
        if (kids.length > 1) $p.append(kids.reverse());
      });
    }

    return { seed: seedRaw, motif: motif, frame: frame, grade: grade,
             track: +track.toFixed(4), rotJit: +rotJit.toFixed(2),
             framing: framing, reverseRow: reverseRow };
  }

  /* ---------------- 工具列按钮 ---------------- */
  function mountButton(info) {
    if (document.body.classList.contains('hide-ui')) return;
    var $tb = $('.toolbar');
    if (!$tb.length) return;
    var $ref = $tb.find('.tb-ref');
    var $btn = $('<button class="tb-variant">换一版</button>');
    if (info) $btn.append('<span class="seedcode">#' + info.seed + '</span>');
    $ref.length ? $btn.insertBefore($ref) : $tb.append($btn);

    $btn.on('click', function () {
      var n = String(Math.floor(Math.random() * 9000) + 100);
      var u = location.pathname + (location.search ? location.search + '&' : '?') + 'seed=' + n;
      location.replace(u + location.hash);
    });
    /* 右键 = 复制「这一版」的链接，方便把某个变体固定下来 */
    $btn.on('contextmenu', function (e) {
      e.preventDefault();
      var url = location.href;
      try {
        navigator.clipboard.writeText(url);
        var $b = $(this);
        $b.append('<span class="seedcode">已复制</span>');
        setTimeout(function () { $b.find('.seedcode').last().remove(); }, 1200);
      } catch (err) { window.prompt('复制这一版的链接：', url); }
    });
  }

  $(function () {
    var seed = readSeed();
    var info = null;
    if (seed) {                    /* ★ seed 为 null 时严格零扰动 —— 复刻优先 */
      info = apply(seed);
      window.__variant = info;     /* 供出图工具读取 */
      console.log('[variants]', JSON.stringify(info));
    }
    mountButton(info);

    $(document).on('keydown', function (e) {
      if ($(e.target).is('[contenteditable="true"]')) return;
      if (e.key === 'v' || e.key === 'V') $('.tb-variant').trigger('click');
    });
  });

})(jQuery);
