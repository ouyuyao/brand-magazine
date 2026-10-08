/* =========================================================================
   magazine.js —— 雜誌頁縮放 / 翻頁 / 疊圖比對 / 文字編輯
   依賴：jQuery（本地 js/vendor/jquery-3.7.1.min.js）
   畫布尺寸自動讀取 theme.css 的 --page-w / --page-h，改 CSS 即可同步
   ========================================================================= */
(function ($) {
  'use strict';

  /* 總頁數由 build.js 依 layout/ 里的页数写进 copy/_data.js（MAGAZINE.total）。
     ★ 页数 = 参考图张数，不写死。 */
  var TOTAL = (window.MAGAZINE && window.MAGAZINE.total) || 1;
  var PW = 1366, PH = 1748;    // 會被 css/tokens.css 的 --page-w/--page-h 覆寫
  var fitScale = 1;            // 「適合視窗」算出來的倍率
  var userZoom = 1;            // 手動縮放倍率
  var fitMode  = true;         // true = 適合視窗；false = 手動
  /* ?shot=1 → 出圖模式：1:1、隱藏工具列與過場動畫。
     截圖／匯出用，避免「適合視窗」把頁面縮放成 0.92 倍導致量測與裁切失準。 */
  var SHOT = /[?&]shot=1(&|$)/.test(location.search);

  /* ---- 讀取 CSS 變數，讓 JS 跟 CSS 永遠同步 ---- */
  function readTokens() {
    var cs = getComputedStyle(document.documentElement);
    var w = parseFloat(cs.getPropertyValue('--page-w'));
    var h = parseFloat(cs.getPropertyValue('--page-h'));
    if (w) PW = w;
    if (h) PH = h;
  }

  function currentPage() {
    var m = /page0?(\d+)\.html/i.exec(location.pathname);
    return m ? parseInt(m[1], 10) : 0;
  }

  function calcFit() {
    var vw = $(window).width() - 64;
    var vh = $(window).height() - 104;
    fitScale = Math.min(vw / PW, vh / PH);
    if (fitScale > 1) fitScale = 1;   // 不超過原始尺寸
  }

  function render() {
    var s = fitMode ? fitScale : userZoom;
    var $wrap = $('.stage-wrap');
    if (!$wrap.length) return;
    $wrap.css({ transform: 'scale(' + s + ')', width: PW + 'px', height: PH + 'px' });
    $('#fitbox').css('height', (PH * s + 44) + 'px');
    $('.zoomval').text(Math.round(s * 100) + '%');
  }

  function relayout() { calcFit(); render(); }

  /* ---------------- 翻頁 ---------------- */
  function go(delta) {
    var p = currentPage();
    if (!p) return;
    var n = p + delta;
    if (n < 1 || n > TOTAL) return;
    location.href = 'page' + (n < 10 ? '0' + n : n) + '.html' + location.hash;
  }

  /* ---------------- 初始化 ---------------- */
  $(function () {
    readTokens();
    if (SHOT) {
      fitMode = false; userZoom = 1;
      $('body').addClass('hide-ui');
      $('.stage-wrap').css('transition', 'none');
      $('.toolbar, .hint').remove();      // 直接移除，避免任何殘影
    }
    calcFit();
    render();

    /* 工具列：翻頁 */
    $('.tb-prev').on('click', function () { go(-1); });
    $('.tb-next').on('click', function () { go(1); });

    /* 工具列：縮放 */
    $('.tb-zoom-in').on('click', function () {
      userZoom = Math.min(2.4, (fitMode ? fitScale : userZoom) + 0.1);
      fitMode = false; render();
    });
    $('.tb-zoom-out').on('click', function () {
      userZoom = Math.max(0.2, (fitMode ? fitScale : userZoom) - 0.1);
      fitMode = false; render();
    });
    $('.tb-fit').on('click', function () { fitMode = true; render(); });
    $('.tb-100').on('click', function () { fitMode = false; userZoom = 1; render(); });

    /* 工具列：疊圖比對（三態循環：關 → 參考圖 → 差異圖 → 關）
       差異圖只有跑過 tools/refgrid.py 才存在；不存在時自動退化成兩態。 */
    var HAS_DIFF = !!document.querySelector('.ref-diff');
    $('.tb-ref').on('click', function () {
      var $b = $(this), $body = $('body');
      var state = $body.hasClass('show-ref') ? 'ref' : ($body.hasClass('show-diff') ? 'diff' : 'off');
      var next = state === 'off' ? 'ref' : (state === 'ref' ? (HAS_DIFF ? 'diff' : 'off') : 'off');
      $body.removeClass('show-ref show-diff');
      if (next === 'ref') $body.addClass('show-ref');
      if (next === 'diff') $body.addClass('show-diff');
      $b.toggleClass('is-on', next !== 'off')
        .text(next === 'ref' ? '叠图·参考' : (next === 'diff' ? '叠图·差异' : '叠图'));
    });

    /* 工具列：文字可編輯（直接在頁面上改字，所見即所得） */
    $('.tb-edit').on('click', function () {
      var on = $('body').toggleClass('edit-text').hasClass('edit-text');
      $(this).toggleClass('is-on', on);
      $('.page').find('h1,h2,h3,p,span,li,div')
        .filter(function () { return $(this).children().length === 0 && $.trim($(this).text()) !== ''; })
        .attr('contenteditable', on ? 'true' : 'false');
      if (on) { $('.hint').text('文字編輯中：直接點文字改內容，改完按 E 或再點一次「改字」結束'); }
      else    { $('.hint').text('← → 翻頁　+ − 縮放　O 疊圖（參考圖/差異）　E 改字　H 隱藏工具列'); }
    });

    /* 監聽視窗變化 */
    var t = null;
    $(window).on('resize', function () {
      clearTimeout(t);
      t = setTimeout(relayout, 120);
    });

    /* 快捷鍵 */
    $(document).on('keydown', function (e) {
      if ($(e.target).is('[contenteditable="true"]')) return;
      switch (e.key) {
        case 'ArrowLeft':  go(-1); break;
        case 'ArrowRight': go(1);  break;
        case 'h': case 'H': $('body').toggleClass('hide-ui'); break;
        case 'o': case 'O': $('.tb-ref').trigger('click'); break;
        case 'e': case 'E': $('.tb-edit').trigger('click'); break;
        case '0': fitMode = true; render(); break;
        case '+': case '=': $('.tb-zoom-in').trigger('click'); break;
        case '-': case '_': $('.tb-zoom-out').trigger('click'); break;
      }
    });

    /* 顯示目前頁碼 */
    var p = currentPage();
    if (p) $('.pill-idx').text(p + ' / ' + TOTAL);
  });

})(jQuery);
