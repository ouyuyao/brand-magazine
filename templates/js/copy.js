/* =========================================================================
   copy.js —— 文案引擎（注入层）
   -------------------------------------------------------------------------
   做什么：
     把 copy/issue.js 里的成稿文案，按 copy/slots.json 的选择器写回页面。
     语言可在「正表记语言」（jp）与「中文对照」（zh）之间切换，不破坏版式。

   怎么用：
     page01.html                → 默认语言（MAGAZINE.defaultLang，通常 jp）
     page01.html?lang=zh        → 切中文对照
     page01.html?copy=0         → 关掉文案引擎，看 build 时烘进去的正表记原稿
     工具列「日本語 / 中文」按钮，或按 L 键切换。

   注入口径（与 copy/slots.json 一致）：
     · 只写「直接文本节点」，不动子元素（高亮 span、字母 b、<br> 全部保留）
     · 字符串 = 元素只有 1 个直接文本节点；数组 = 按文本节点顺序逐个赋值
     · 值个数与文本节点个数不符 → 该槽位跳过并记进报告，绝不猜

   依赖：jQuery（js/vendor/）、copy/_data.js 先加载
   ========================================================================= */
(function ($) {
  'use strict';

  var M = window.MAGAZINE || {};

  function param(name) {
    var m = new RegExp('[?&]' + name + '=([^&#]*)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : null;
  }
  function normLang(v) {
    if (!v) return M.defaultLang || 'jp';
    v = String(v).toLowerCase();
    if (v === 'ja' || v === 'jp' || v === 'japanese') return 'jp';
    if (v === 'zh' || v === 'cn' || v === 'zh-tw' || v === 'zh-hant' || v === 'zh-hans') return 'zh';
    return M.defaultLang || 'jp';
  }

  var LANG = normLang(param('lang') || (function () {
    try { return sessionStorage.getItem('mag.lang'); } catch (e) { return null; }
  })());
  var ENABLED = param('copy') !== '0';

  function pageKey() {
    var m = /page0?(\d+)\.html/i.exec(location.pathname);
    if (!m) return null;
    var n = m[1];
    return 'page' + (n.length < 2 ? '0' + n : n);
  }

  /* ---------------- 占位符 ----------------
     品牌变量由品牌包推导；产品变量一律来自 product.vars（品牌无关，键名自由）。 */
  function placeholderVars() {
    var B = M.brandData || window.BRAND || {};
    var P = M.productData || window.PRODUCT || {};
    var n = B.name || {};
    var nativeJoin = [n.native, n.kana].filter(Boolean).join(' ');
    var v = {
      brand:   (LANG === 'jp') ? nativeJoin : (n.native || n.zh || ''),
      brandzh: n.zh || n.native || '',
      brandro: n.romaji || ''
    };
    var extra = P.vars || {};
    Object.keys(extra).forEach(function (k) { v[k] = extra[k]; });
    return v;
  }
  function fill(str, V) {
    return String(str).replace(/\$\{([A-Za-z_]\w*)\}/g, function (m, k) {
      return Object.prototype.hasOwnProperty.call(V, k) ? V[k] : m;
    });
  }

  /* ---------------- 文本节点口径 ---------------- */
  function textNodes(el) {
    var out = [], n;
    for (n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && n.nodeValue.replace(/[\s\u3000]+/g, '') !== '') out.push(n);
    }
    return out;
  }

  /* ---------------- 解析 + 缓存 ---------------- */
  var CACHE = null;
  var REPORT = { lang: LANG, page: null, enabled: ENABLED, applied: 0, slots: 0, errors: [] };

  function resolveOnce(page, copy) {
    var map = {};
    Object.keys(copy).forEach(function (sel) {
      var els;
      try { els = page.querySelectorAll(sel); }
      catch (e) { REPORT.errors.push({ sel: sel, why: '选择器非法：' + e.message }); return; }
      if (els.length !== 1) {
        REPORT.errors.push({ sel: sel, why: '命中 ' + els.length + ' 个元素（应为 1）' });
        return;
      }
      var nodes = textNodes(els[0]);
      if (!nodes.length) { REPORT.errors.push({ sel: sel, why: '元素内没有可写的直接文本节点' }); return; }
      map[sel] = nodes;
    });
    return map;
  }

  /* ---------------- 注入 ---------------- */
  function apply() {
    REPORT.errors.length = 0;
    REPORT.applied = 0;
    REPORT.lang = LANG;

    /* lang / data-lang 一律要设，即使文案关闭：
       <html lang> 会改变中日文字体的回退族，字面宽度与行高都不同。 */
    document.documentElement.setAttribute('lang', LANG === 'jp' ? 'ja' : 'zh-Hant');
    document.documentElement.setAttribute('data-lang', ENABLED ? LANG : 'off');

    if (!ENABLED) return REPORT;

    var key = pageKey(); REPORT.page = key;
    if (!key) return REPORT;
    var page = document.querySelector('.page');
    if (!page) return REPORT;

    var copy = (M.copy || {})[key];
    if (!copy) { REPORT.errors.push({ sel: '(page)', why: 'copy/issue.js 里缺 ' + key }); return REPORT; }
    REPORT.slots = Object.keys(copy).length;

    if (!CACHE || CACHE.key !== key) CACHE = { key: key, map: resolveOnce(page, copy) };
    var map = CACHE.map, V = placeholderVars();

    Object.keys(copy).forEach(function (sel) {
      var nodes = map[sel];
      if (!nodes) return;
      var entry = copy[sel];
      var val = (entry[LANG] !== undefined) ? entry[LANG] : entry.jp;
      if (val === undefined || val === null) {
        REPORT.errors.push({ sel: sel, why: '缺 ' + LANG + ' 文案' }); return;
      }
      var vals = Array.isArray(val) ? val : [val];
      if (vals.length !== nodes.length) {
        REPORT.errors.push({ sel: sel, why: '值 ' + vals.length + ' 个 / 直接文本节点 ' + nodes.length + ' 个，数量不符' });
        return;
      }
      for (var i = 0; i < nodes.length; i++) nodes[i].nodeValue = fill(vals[i], V);
      REPORT.applied++;
    });

    document.documentElement.setAttribute('lang', LANG === 'jp' ? 'ja' : 'zh-Hant');
    document.documentElement.setAttribute('data-lang', LANG);
    if (REPORT.errors.length) {
      console.warn('[copy] ' + REPORT.errors.length + ' 个槽位没写成：', REPORT.errors);
    }
    return REPORT;
  }

  /* ---------------- 语言切换 ---------------- */
  function setLang(l, opt) {
    LANG = normLang(l);
    try { sessionStorage.setItem('mag.lang', LANG); } catch (e) { }
    if (!(opt && opt.noUrl)) {
      var q = location.search.replace(/^\?/, '').split('&').filter(function (s) {
        return s && !/^lang=/.test(s);
      });
      q.push('lang=' + LANG);
      try { history.replaceState(null, '', location.pathname + '?' + q.join('&') + location.hash); } catch (e) { }
    }
    apply();
    $('.tb-lang').text((M.label && M.label[LANG]) || LANG);
    $(document).trigger('copy:lang', [LANG]);
    return REPORT;
  }

  /* ---------------- 工具列按钮 ---------------- */
  function mountButton() {
    if (document.body.classList.contains('hide-ui')) return;
    var $tb = $('.toolbar');
    if (!$tb.length || $tb.find('.tb-lang').length) return;
    var $btn = $('<button class="tb-lang" type="button" title="切換文案語言（L）"></button>')
      .text((M.label && M.label[LANG]) || LANG);
    $tb.append($btn);
    $btn.on('click', function () { setLang(LANG === 'jp' ? 'zh' : 'jp'); });
  }

  /* ---------------- 对外接口（供出图工具 / copycheck 读） ---------------- */
  window.__copy = {
    report: REPORT,
    apply: apply,
    setLang: setLang,
    current: function () { return LANG; },
    issue: function () { return M.issue; }
  };

  $(function () {
    apply();
    mountButton();
    $(document).on('keydown', function (e) {
      if ($(e.target).is('[contenteditable="true"]')) return;
      if (e.key === 'l' || e.key === 'L') setLang(LANG === 'jp' ? 'zh' : 'jp');
    });
    console.log('[copy] issue=' + M.issue + ' lang=' + LANG +
      ' 已写 ' + REPORT.applied + '/' + REPORT.slots + ' 槽位' +
      (REPORT.errors.length ? '，' + REPORT.errors.length + ' 处未写' : ''));
  });

})(jQuery);
