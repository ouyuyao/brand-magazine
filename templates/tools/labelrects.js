/**
 * labelrects.js —— 遮挡审计专用：把每页「浮层标签」与「照片」的真实几何导成 JSON
 *
 * 为什么需要它：截图上的坐标会被「適合視窗」缩放污染，肉眼估算不可靠。
 * 这里通过 Chrome DevTools Protocol 在页面里直接问 DOM 要 boundingClientRect，
 * 再按 .page 的缩放比换算回 1366×1748 画布坐标，得到可复核的数字。
 *
 * 输出：_shots/_labels.json
 *   {
 *     "page01": {
 *       "canvas": {"w":1366,"h":1748},
 *       "photos": [ {sel, x,y,w,h, src, natW,natH, fit, pos} ],
 *       "labels": [ {sel, kind, x,y,w,h, z, txt} ]
 *     }, ...
 *   }
 *
 * 用法：node tools/labelrects.js [page02 page07 ...] [--url-query "lang=zh"]
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const PORT = 9336;
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const argv = process.argv.slice(2);
let urlQuery = '';
const qi = argv.indexOf('--url-query');
if (qi >= 0) { urlQuery = argv[qi + 1] || ''; argv.splice(qi, 2); }
const only = argv.filter(a => /^page\d+$/.test(a));
/* 页数来自 layout/（不写死） */
const names = only.length ? only
  : require('fs').readdirSync(path.join(ROOT,'layout')).filter(f=>/\.json$/.test(f)&&!/^_/.test(f))
      .map(f=>(f.match(/(\d+)/)||[,''])[1]).filter(Boolean).sort((a,b)=>+a-+b)
      .map(n=>'page'+(n.length<2?'0'+n:n));

const pages = names.map(n => ({
  name: n,
  url: 'file:///' + path.join(ROOT, n + '.html').replace(/\\/g, '/') + (urlQuery ? '?' + urlQuery : ''),
}));

/* 在页面里跑：分出「照片」与「标签」两类 */
const PROBE = `(() => {
  const page = document.querySelector('.page'); if (!page) return {error:'no .page'};
  const pr = page.getBoundingClientRect();
  const sx = pr.width / page.offsetWidth || 1;
  const toCanvas = r => ({
    x: Math.round((r.left - pr.left) / sx), y: Math.round((r.top - pr.top) / sx),
    w: Math.round(r.width / sx),           h: Math.round(r.height / sx)
  });
  const clsOf = el => (el.className || '').toString().trim().split(/\\s+/).filter(Boolean).slice(0, 3).join('.');
  const selOf = el => el.tagName.toLowerCase() + (clsOf(el) ? '.' + clsOf(el) : '');
  const vis = el => {
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity > 0.02;
  };

  /* ---- 1. 照片：任何渲染出来的 <img>，带上 object-fit 信息 ---- */
  const photos = [];
  page.querySelectorAll('img').forEach(img => {
    if (!vis(img)) return;
    const r = img.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return;      // 太小的当图标，不算照片
    const src = (img.getAttribute('src') || '').split('/').pop();
    if (/^(bra|panty|detail|product)-/.test(src)) return;   // 白底产品图不属于「模特照」
    const cs = getComputedStyle(img);
    photos.push(Object.assign({
      sel: selOf(img), src: src,
      natW: img.naturalWidth, natH: img.naturalHeight,
      fit: cs.objectFit, pos: cs.objectPosition,
      parent: selOf(img.parentElement)
    }, toCanvas(r)));
  });

  /* ---- 2. 标签：会影响观感的浮层（文字块 / 头像 / 面板 / 步骤格） ---- */
  const labels = [];
  const els = [];                                  // 与 labels 同序，用于算父子包含关系
  const photoRectKeys = new Set(photos.map(p => [p.x, p.y, p.w, p.h].join(',')));

  /* 元素自身 + 全部祖先的 rotate 累積角。
     getComputedStyle(el).transform 只看得到「自己那一層」，
     而 .c01 轉 −1.6°、裡面的 .p 自己再轉 6° —— 只讀自身會少算 1.6°。 */
  const accumTheta = el => {
    let A = new DOMMatrix();
    for (let n = el; n && n !== page; n = n.parentElement) {
      const t = getComputedStyle(n).transform;
      if (t && t !== 'none') A = new DOMMatrix(t).multiply(A);
    }
    return Math.atan2(A.b, A.a);
  };

  page.querySelectorAll('*').forEach(el => {
    if (el.tagName === 'IMG') return;
    const cs = getComputedStyle(el);
    if (cs.position !== 'absolute' && cs.position !== 'fixed') return;
    if (!vis(el)) return;
    const rBox0 = el.getBoundingClientRect();
    // 满版叠图层（比对用）不算
    if (/ref-overlay/.test(clsOf(el))) return;
    // 纯照片容器（内部有照片且自身无文字）不算标签
    const txt = (el.textContent || '').replace(/\\s+/g, ' ').trim();
    const hasPhoto = !!el.querySelector('img');
    const cls = clsOf(el);
    const isPhotoBox = hasPhoto && !txt && /hero|heroA|heroB|hero2|polaroid|ph|faces|avatar/.test(cls);
    if (isPhotoBox) return;
    if (!txt && !hasPhoto) return;                 // 纯装饰（细线/色块）单独看，这里不列
    let kind = 'text';
    if (/avatar/.test(cls)) kind = 'avatar';       // 头像（本身就是一张脸）
    else if (/bubble/.test(cls)) kind = 'bubble';
    else if (/stepgrid|step__/.test(cls)) kind = 'step';
    else if (/panel|fitpanel/.test(cls)) kind = 'panel';
    else if (/tag\\b/.test(cls)) kind = 'tag';
    else if (/stamp/.test(cls)) kind = 'stamp';
    else if (/credits|v-note|\\bv\\b|cap|caps|names|byline|lede|headline|annoy|news|fam|profile|meta|vlab|script|useit|howto|others|title|body|bigname|hashtag|answer|edit|role/.test(cls)) kind = 'text';
    /* 出血大圖（is-bleed）是「背景層」。雜誌封面／跨頁天然會讓浮層卡片、標籤、色卡壓在它上面，
       那是版式語彙、不是「照片互壓」。單列一類，blockcheck 就不會把它算進互壓組合
       （它只取 kind === 'photo-block'）。 */
    else if (hasPhoto) kind = /is-bleed/.test(cls) ? 'bleed-block' : 'photo-block';

    /* ★★text 类改用「墨迹框」（2026-10-01）。
       为什么：zone 的 box 是**预留栏宽**，文字左对齐时右侧留一大片空白。
       实测 page04「からだの形は、からだが決める。」元素框 262 宽、墨迹仅约 180 →
       框与 L-eye 禁区相交 1564px²、与 R-eye 缓冲相交 1060px² → check_faces 假 FAIL，
       而视觉上文字离眼睛还有 60px 空档。
       规则：**只有「无背景色 + 无背景图 + 无边框」的文字**才用墨迹 ——
       有底色的标签（panel / tag / bubble / stamp）本身就是可见色块，
       必须继续用元素框，那才是真实着色范围（改错方向会从「假报」变成「漏报」）。
       取法 = 所有后代文本节点 Range 的并集（只改直接文本节点的是文案引擎，
       但 <b>/<i> 之类的行内元素也在墨迹里，必须一并算）。 */
    const bgFlat = (cs.backgroundColor || 'transparent').replace(/ /g, '');
    /* ★ slice(-3) 不是 slice(-2)：rgba(0,0,0,0) 的末三位才是 ',0)'。
       写成 -2 得到 '0)'，判据恒假 → 整段墨迹逻辑静默不生效（本工具踩过这一次）。
       ⚠️ 本段在**模板字符串**内：注释里不许出现反引号与「美元大括号」 ——
       反引号会终止字符串，美元大括号会触发插值，两者都让整个脚本 SyntaxError。 */
    const noFill = (bgFlat === 'transparent' || bgFlat.slice(-3) === ',0)')
      && (cs.backgroundImage || 'none') === 'none'
      && ['borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth']
        .every(function (k) { return (parseFloat(cs[k]) || 0) === 0; });
    let usedInk = false;
    let inkDbg = 'n/a';
    let r = rBox0;
    if (kind === 'text' && noFill) {
      const rng = document.createRange();
      let bb = null;
      (function walk(n) {
        for (let i = 0; i < n.childNodes.length; i++) {
          const ch = n.childNodes[i];
          if (ch.nodeType === 3) {
            if (!(ch.textContent || '').trim()) continue;
            rng.selectNodeContents(ch);
            const q = rng.getBoundingClientRect();
            if (q.width > 0 && q.height > 0) {
              bb = bb ? { l: Math.min(bb.l, q.left), t: Math.min(bb.t, q.top),
                          r: Math.max(bb.r, q.right), b: Math.max(bb.b, q.bottom) }
                      : { l: q.left, t: q.top, r: q.right, b: q.bottom };
            }
          } else if (ch.nodeType === 1) { walk(ch); }
        }
      })(el);
      inkDbg = bb ? (Math.round((bb.r - bb.l) / sx) + 'x' + Math.round((bb.b - bb.t) / sx)) : 'null';
      /* 墨迹在**任一维**明显小于元素框（< 85%）就切换 —— 差一点点没必要换，
         换来换去会让 iw/ih、quad 的口径在同一批数据里不一致。
         ★必须两维都判：zone 的 box 既可能「横向留栏宽」（右对齐/左对齐的短句），
         也可能「纵向留行数」（预留了 3 行位置而只写了 1 行）。
         实测 page04「からだの形は、からだが決める。」墨迹 250x23 / 元素框 262x91 ——
         宽度几乎撑满（只差 5%），**只有高度露馅**；只比宽度就会漏掉它。 */
      if (bb && ((bb.r - bb.l) < rBox0.width * 0.85 || (bb.b - bb.t) < rBox0.height * 0.85)) {
        r = new DOMRect(bb.l, bb.t, bb.r - bb.l, bb.b - bb.t);
        usedInk = true;
      }
    }
    inkDbg = kind + '|ink=' + inkDbg + '|box=' + Math.round(rBox0.width / sx)
      + 'x' + Math.round(rBox0.height / sx) + '|used=' + usedInk;
    if (r.width < 16 || r.height < 12) return;
    const c = toCanvas(r);
    /* 只有「正方 + 圆角 ≥ 半宽」的元件，着色形状才是圆（.stamp / .avatar）。
       不能只看 border-radius 的数值：.bubble 用的是 --r-pill(999px)，
       parseFloat 出来是 999，会被误判成椭圆；.bubble 其实是胶囊形，
       按方框算才保守（宁可多报，不可漏报）。
       也不能直接比较百分比与像素：.stamp 是 50%，parseFloat 得 50，
       与半宽 88 不同量纲，本来会被判成"不是圆"。
       rw/rh 取 offsetWidth/Height（不受 transform:rotate 影响）—— 那才是真正着色的直径。 */
    const dia = Math.min(el.offsetWidth, el.offsetHeight);
    const square = Math.abs(el.offsetWidth - el.offsetHeight) <= 2;
    const brRaw = cs.borderTopLeftRadius || '0px';
    const brPct = /%\s*$/.test(brRaw) ? parseFloat(brRaw) : null;
    const isRound = square && (brPct === null
      ? (parseFloat(brRaw) || 0) >= dia / 2 - 1
      : brPct >= 50);
    /* 旋轉元素的「真實四角」（畫布座標）。
       getBoundingClientRect() 只給外接方框：兩個各轉 ±8° 的矩形可能 bbox 相交、
       實際著色像素卻分開 —— 拿方框判「圖壓圖」會假報（和當初 person zone 圈太大
       導致印章假報 19701px² 是同一類錯）。
       純 rotate/scale 不改變元素中心，所以
         四角 = bbox 中心 + Rot(θ)·(±W/2, ±H/2)
       W/H 取 offsetWidth/Height（未變換座標系 = 畫布單位，不要再 /sx）。 */
    const th = accumTheta(el);
    /* 用了墨迹框的元素，四角必须按墨迹尺寸算（r.width 是屏幕像素，除 sx 回画布单位）；
       其余仍用 offsetWidth/Height（未变换坐标系 = 画布单位，且不受 rotate 影响）。 */
    const hw = (usedInk ? r.width / sx : el.offsetWidth) / 2;
    const hh = (usedInk ? r.height / sx : el.offsetHeight) / 2;
    const cx = (r.left + r.width / 2 - pr.left) / sx;
    const cy = (r.top + r.height / 2 - pr.top) / sx;
    const ct = Math.cos(th), st = Math.sin(th);
    const rd = v => Math.round(v * 10) / 10;
    const quad = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]].map(function (p) {
      return [rd(cx + p[0] * ct - p[1] * st), rd(cy + p[0] * st + p[1] * ct)];
    });

    /* 圖片內容包絡用：元素內第一張圖的檔名，以及元素的「未變換尺寸」。
       為什麼需要：白底產品圖四周有大量透明留白，product-white.png 的實際內容
       只佔畫面寬度的 55%。拿「元素框」判兩張圖有沒有互壓會假報 ——
       page04 的 .prodA 與 .prodC 框相交 2.6 萬 px²，圖的內容卻各在框的一側。
       內容比例由 tools/alphabox.py 掃 alpha 通道預先算好，存在 images/_alphabox.json。 */
    const firstImg = el.querySelector('img');

    labels.push(Object.assign({ sel: selOf(el), kind: kind, z: cs.zIndex,
      txt: txt.slice(0, 34) }, c, {
      rnd: isRound ? 1 : 0,
      /* offsetWidth 已经在 .page 的未变换坐标系里 = 画布单位，不要再 /sx：
         /sx 会把 176 的圆算成 180，凭空多出 4.5% 面积（试过，page04 因此多报 3652→3255px²） */
      rw: isRound ? Math.round(dia) : 0,
      rh: isRound ? Math.round(dia) : 0,
      rot: rd(th * 180 / Math.PI),
      quad: quad,
      dbg: inkDbg,
      iw: usedInk ? Math.round(r.width / sx) : el.offsetWidth,
      ih: usedInk ? Math.round(r.height / sx) : el.offsetHeight,
      src: firstImg ? (firstImg.getAttribute('src') || '').split('/').pop() : '',
    }));
    els.push(el);
  });

  /* 父子包含标记：.c01 這種「白卡容器」本身也是 photo-block，它包住 .p，
     不能算成「兩張圖互壓」。這裡記錄每個標籤的祖先索引。 */
  labels.forEach(function (L, i) {
    L.anc = [];
    for (let j = 0; j < els.length; j++) if (j !== i && els[j].contains(els[i])) L.anc.push(j);
  });

  return { canvas: { w: page.offsetWidth, h: page.offsetHeight }, photos: photos, labels: labels };
})()`;

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pend = new Map();
    ws.onopen = () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id; pend.set(mid, { res, rej });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      close() { try { ws.close(); } catch (e) {} },
    });
    ws.onerror = () => reject(new Error('ws error'));
    ws.onmessage = m => {
      const d = JSON.parse(m.data);
      if (d.id && pend.has(d.id)) {
        const { res, rej } = pend.get(d.id); pend.delete(d.id);
        d.error ? rej(new Error(d.error.message)) : res(d.result);
      }
    };
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const userDir = path.join(os.tmpdir(), 'wb-labels-' + Date.now());
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + userDir,
    '--window-size=1440,1810', 'about:blank',
  ], { stdio: 'ignore' });

  let list;
  for (let i = 0; i < 40; i++) {
    await sleep(300);
    try {
      list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      if (list.some(t => t.type === 'page')) break;
    } catch (e) { /* 未就绪 */ }
  }
  const target = (list || []).find(t => t.type === 'page');
  if (!target) { chrome.kill(); throw new Error('Chrome 未就绪'); }

  const cdp = await connect(target.webSocketDebuggerUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: 1440, height: 1810, deviceScaleFactor: 1, mobile: false });

  const out = {};
  const failed = [];
  for (const p of pages) {
    await cdp.send('Page.navigate', { url: p.url });
    await sleep(900);
    const r = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true });
    const v = r.result.value;
    if (!v || v.error) {
      failed.push(p.name);
      console.error(`✗ [${p.name}] PROBE 未返回数据：${(v && v.error) || 'undefined'}`
        + ' —— 页面里的探针抛错了（常见：模板字符串里混进了反引号/美元大括号，或变量作用域越界）');
      continue;
    }
    out[p.name] = v;
    console.log(`${p.name.padEnd(8)} 画布 ${v.canvas.w}×${v.canvas.h}  照片 ${v.photos.length}  标签 ${v.labels.length}`);
  }
  /* ★空数据必须**报错退出**，不能写出去。
     踩过：探针在页面里抛 SyntaxError → evaluate 返回 undefined → 旧版只 console.log 后 continue，
     照样把 {} 写进 _labels.json → check_faces / blockcheck 遍历不到任何页，输出「FAIL 0」——
     而那是**假绿**（空过），比报错危险得多。 */
  if (failed.length || !Object.keys(out).length) {
    cdp.close(); chrome.kill();
    console.error(`\n★ 标签几何导出失败：${failed.length || pages.length} 页无数据`
      + (failed.length ? `（${failed.join(', ')}）` : ''));
    console.error('  已拒绝写出 _shots/_labels.json —— 空数据会让下游判据报「FAIL 0」（假绿）。');
    process.exit(1);
  }
  fs.mkdirSync(path.join(ROOT, '_shots'), { recursive: true });
  fs.writeFileSync(path.join(ROOT, '_shots', '_labels.json'), JSON.stringify(out, null, 1));
  cdp.close(); chrome.kill();
  console.log('\n-> _shots/_labels.json');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
