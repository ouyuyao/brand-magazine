/**
 * copycheck.js —— 文案引擎 + 版面的校验器（退出码 0 才算过）
 *
 * 为什么必须跑真实 DOM：
 *   槽位是「按 id 定位」的，但「文案落到哪个元素上」「日文比中文长会不会把固定框挤爆」
 *   「有没有漏写、有没有残留」都只有在渲染后的页面里才看得见。
 *
 * 五组检查：
 *   A 接口层  每个文案选择器命中唯一 1 个元素；没有两个选择器撞同一个元素
 *   B 注入层  每个槽位的「值个数」==「直接文本节点个数」；jp / zh 都齐
 *   C 覆盖层  copy/slots.json 里每个槽位都被本期文案写到
 *   D 合规层  渲染后的正文里没有品牌包禁用词；Slogan 出现时必须「配平」
 *   E 版面层  ① 静态：文字分区之间的框不得互压（layout JSON 直接算，不需浏览器）
 *             ② 动态：渲染后每个文字区块不得溢出自己的框、不得跑出画布
 *
 * 用法：
 *   node tools/copycheck.js                # 全页 × jp/zh + 版面
 *   node tools/copycheck.js --lang zh      # 只看中文对照稿
 *   node tools/copycheck.js --no-layout    # 跳过版面层
 *   node tools/copycheck.js --json         # 只出 JSON
 *   退出码：全绿 0；有 FAIL 1
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const PORT = 9341;
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const LANG_ARG = argOf('--lang', null);
const LANGS = LANG_ARG ? [LANG_ARG] : ['jp', 'zh'];
const JSONONLY = argv.includes('--json');
const NO_LAYOUT = argv.includes('--no-layout');
const HIT = parseFloat(argOf('--hit', '200'));   // 文字互压的最小交叠面积（px²）
const ONLY = (argOf('--pages', '') || '').split(',').map((s) => s.trim()).filter(Boolean)
  .map((n) => (n.length < 2 ? '0' + n : n));      // --pages 01,02 → ['01','02']

/* 页列表来自 layout/ */
const LAY = path.join(ROOT, 'layout');
const layFiles = fs.readdirSync(LAY).filter((f) => /\.json$/.test(f) && !/^_/.test(f));
const PAGES = layFiles.map((f) => (f.match(/(\d+)/) || [, ''])[1]).filter(Boolean)
  .filter((n) => !ONLY.length || ONLY.includes(n.length < 2 ? '0' + n : n))
  .sort((a, b) => +a - +b).map((n) => 'page' + (n.length < 2 ? '0' + n : n));
const LAYOUTS = {};
/* ★优先读 layout/_resolved.json（build.js 编译期折算过 parent 的坐标）。
   直读 layout/NN.json 会把「父框内的相对坐标」当画布坐标，得出假的文字互压。 */
const RESOLVED = path.join(LAY, '_resolved.json');
if (fs.existsSync(RESOLVED)) {
  const d = JSON.parse(fs.readFileSync(RESOLVED, 'utf8'));
  Object.keys(d).forEach((pid) => {
    LAYOUTS[pid] = { canvas: { w: d[pid].canvas[0], h: d[pid].canvas[1] }, zones: d[pid].zones };
  });
} else {
  console.warn('⚠ 未找到 layout/_resolved.json —— 回落读 layout 原文（带 parent 的页面会算出假互压）。跑一次 node build.js 即可生成。');
  PAGES.forEach((pid) => {
    const f = layFiles.find((x) => (x.match(/(\d+)/) || [, ''])[1] === pid.slice(4).replace(/^0/, '') ||
      'page' + (x.match(/(\d+)/) || [, ''])[1] === pid);
    if (f) LAYOUTS[pid] = JSON.parse(fs.readFileSync(path.join(LAY, f), 'utf8'));
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------------ 审计表达式 */
const AUDIT = `(() => {
  const out = { page:null, lang:null, applied:0, slots:0,
                errors:[], unresolved:[], collisions:[], coverage:[], forbidden:[], slogan:null,
                rects:{} };
  const M = window.MAGAZINE || {};
  const R = (window.__copy && window.__copy.report) || {};
  out.lang = R.lang || null;
  out.applied = R.applied || 0;
  out.slots = R.slots || 0;
  out.errors = (R.errors || []).slice();

  const page = document.querySelector('.page');
  if (!page) return out;
  const m = /page0?(\\d+)/i.exec(location.pathname);
  if (!m) return out;
  const key = 'page' + (m[1].length < 2 ? '0' + m[1] : m[1]);
  out.page = key;
  const copy = (M.copy || {})[key] || {};

  /* A. 接口层 */
  const el2sels = new Map();
  Object.keys(copy).forEach(sel => {
    let els;
    try { els = page.querySelectorAll(sel); }
    catch (e) { out.unresolved.push({ sel: sel, why: '选择器非法' }); return; }
    if (els.length !== 1) { out.unresolved.push({ sel: sel, why: '命中 ' + els.length + ' 个' }); return; }
    const el = els[0];
    if (!el2sels.has(el)) el2sels.set(el, []);
    el2sels.get(el).push(sel);
  });
  el2sels.forEach((sels, el) => {
    if (sels.length > 1) out.collisions.push({
      sel: sels.join('  ＋  '), text: (el.textContent || '').replace(/\\s+/g,' ').trim().slice(0, 40) });
  });

  /* C. 覆盖层 */
  const SLOTS = window.__slots && window.__slots[key];
  if (SLOTS) SLOTS.forEach(s => {
    let el = null;
    try { const n = page.querySelectorAll(s.sel); el = n.length === 1 ? n[0] : null; } catch (e) {}
    if (!el) { out.coverage.push({ sel: s.sel, why: '槽位选择器解析失败', text: s.sample }); return; }
    if (!el2sels.has(el)) out.coverage.push({ sel: s.sel, why: '未被本期文案写到',
      text: (el.textContent || '').replace(/\\s+/g,' ').trim().slice(0, 36) });
  });

  /* D. 合规层（扫渲染后的正文） */
  const txt = (page.innerText || page.textContent || '');
  const BD = M.brandData || {};
  const FB = BD.forbidden || {};
  Object.keys(FB).forEach(k => (FB[k] || []).forEach(w => {
    const i = txt.indexOf(w);
    if (i >= 0) out.forbidden.push({ group: k, term: w,
      ctx: txt.slice(Math.max(0, i - 16), i + w.length + 16).replace(/\\s+/g,' ') });
  }));
  /* Slogan 配平：品牌包 slogan 段声明才查 */
  const SG = BD.slogan || {};
  if (SG.native) {
    const si = txt.indexOf(SG.native);
    if (si >= 0) {
      const after = txt.slice(si + SG.native.length, si + SG.native.length + 60).replace(/\\s+/g,'');
      const pair = (SG.mustPair || []);
      out.slogan = { found: true, after: after.slice(0, 30),
        paired: pair.length === 0 || pair.some(p => after.indexOf(p.replace(/\\s+/g,'')) === 0) };
    } else out.slogan = { found: false };
  }

  /* E②. 渲染后几何：溢出 / 出画布 */
  const pr = page.getBoundingClientRect();
  out.canvas = [Math.round(pr.width), Math.round(pr.height)];
  if (SLOTS) SLOTS.forEach(s => {
    let el = null;
    try { const n = page.querySelectorAll(s.sel); el = n.length === 1 ? n[0] : null; } catch (e) {}
    if (!el) return;
    const host = el.parentElement;                       // 外层：管几何
    const r = host.getBoundingClientRect();
    out.rects[s.id] = {
      x: r.left - pr.left, y: r.top - pr.top, w: r.width, h: r.height,
      sw: el.scrollWidth, sh: el.scrollHeight, cw: el.clientWidth, ch: el.clientHeight,
      text: (el.textContent || '').replace(/\\s+/g,' ').trim().slice(0, 30)
    };
  });

  /* E③. 文字 zone 的**墨迹范围**（不是容器框）
     ★为什么必须另量：layout 里的 box 是**容器**，宽高按行高与留白定，
       常常比字本身大一圈。拿容器跟别人的字比交叠，会报出「框碰了、字没碰」的假互压；
       反过来也会漏掉「字碰了、框没碰」的真问题。
       · 普通文字：Range 的包围盒 = 渲染后字墨的真实范围（已含 rotation 的结果，无需再算旋转）
       · 弧排文字：沿路径采样出「带形」，比外接矩形贴近得多（弧是斜的） */
  out.inks = {};
  if (SLOTS) SLOTS.forEach((s) => {
    let el = null;
    try { const n = page.querySelectorAll(s.sel); el = n.length === 1 ? n[0] : null; } catch (e) {}
    if (!el || el.closest('[data-arc-done]')) return;
    let bb; try {
      const rng = document.createRange(); rng.selectNodeContents(el);
      bb = rng.getBoundingClientRect();
    } catch (e) { return; }
    if (!bb || bb.width <= 0 || bb.height <= 0) return;
    out.inks[s.id] = { box: [bb.left - pr.left, bb.top - pr.top, bb.width, bb.height] };
  });
  page.querySelectorAll('[data-arc-done]').forEach((el) => {
    const svg = el.querySelector('.arc-svg');
    const path = svg && svg.querySelector('path');
    const tt = el.querySelector('.t');
    if (!path || !tt) return;
    /* 元素自带 transform（rotate 写在 style 上），getBoundingClientRect 给的是旋转后的 AABB，
       不能拿来当局部原点。正确做法：绕**元素中心**（中心在旋转下不变）把点映射过去。 */
    const r = el.getBoundingClientRect();
    let m; try { m = new DOMMatrix(getComputedStyle(el).transform); } catch (e) { m = null; }
    const a = m ? m.a : 1, mb = m ? m.b : 0, c = m ? m.c : 0, d = m ? m.d : 1;
    const cw = el.clientWidth, ch = el.clientHeight;
    const cx = r.left - pr.left + r.width / 2, cy = r.top - pr.top + r.height / 2;
    const map = (lx, ly) => {
      const dx = lx - cw / 2, dy = ly - ch / 2;
      return [cx + dx * a + dy * c, cy + dx * mb + dy * d];
    };
    /* 沿路径采样，取「带」而不是「外接矩形」：弧排字是一条斜带，
       外接矩形会把价格、徽章所在的空白也算进去 → 假互压。 */
    const fs = parseFloat(getComputedStyle(tt).fontSize) || 16;
    const up = fs * 0.84, dn = fs * 0.26;          // 基线上缘 / 下缘（含送り）
    const total = path.getTotalLength();
    const N = 48, A = [], B = [];
    for (let i = 0; i <= N; i++) {
      const len = total * i / N, e = 0.5;
      const p = path.getPointAtLength(len);
      const q = path.getPointAtLength(Math.min(total, len + e));
      const s = path.getPointAtLength(Math.max(0, len - e));
      let tx = q.x - s.x, ty = q.y - s.y;
      const L2 = Math.hypot(tx, ty) || 1; tx /= L2; ty /= L2;
      const nx = ty, ny = -tx;                      // 路径左侧 = 字形「上」（屏幕 y 向下）
      A.push(map(p.x + nx * up, p.y + ny * up));
      B.push(map(p.x - nx * dn, p.y - ny * dn));
    }
    /* 拆成 N 段凸四边形（Sutherland–Hodgman 要求两边都是凸的） */
    const polys = [];
    for (let i = 0; i < N; i++) polys.push([A[i], A[i + 1], B[i + 1], B[i]]);
    out.inks[el.id] = { polys: polys };
  });
  return out;
})()`;

/* ------------------------------------------------------------------ CDP */
function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pend = new Map();
    ws.onopen = () => resolve({
      send(m, p = {}) {
        return new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej });
          ws.send(JSON.stringify({ id: i, method: m, params: p })); });
      },
      close() { try { ws.close(); } catch (e) { } }
    });
    ws.onerror = () => reject(new Error('ws error'));
    ws.onmessage = (m) => { const d = JSON.parse(m.data);
      if (d.id && pend.has(d.id)) { const { res, rej } = pend.get(d.id); pend.delete(d.id);
        d.error ? rej(new Error(d.error.message)) : res(d.result); } };
  });
}
async function openChrome(port, tag) {
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
    '--remote-debugging-port=' + port, '--user-data-dir=' + path.join(os.tmpdir(), tag + '-' + Date.now()),
    '--window-size=1440,1810', 'about:blank'], { stdio: 'ignore' });
  let list;
  for (let i = 0; i < 40; i++) {
    await sleep(300);
    try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      if (list.some((x) => x.type === 'page')) break; } catch (e) { }
  }
  const t = (list || []).find((x) => x.type === 'page');
  if (!t) { chrome.kill(); throw new Error('Chrome 未就绪（端口 ' + port + '）'); }
  const cdp = await connect(t.webSocketDebuggerUrl);
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  return { cdp, kill: () => { try { cdp.close(); } catch (e) { } chrome.kill(); } };
}

/* ------------------------------------------------------------------ E① 静态：文字框互压 */
/* ★比的是**字的墨迹**，不是容器的框。
   两个坑，都踩过：
     ① 容器框按行高与留白定，常常比字本身大一圈 —— 拿它比会报「框碰了、字没碰」的假互压；
     ② 弧排 / 旋转大字的框是**松包围盒**，一个斜置 24° 的弧带，其轴对齐框能覆盖到
        价格、徽章的位置，报出来的数字（上万 px²）看着完全像真问题。
   所以：普通文字用渲染后 Range 的包围盒；弧排字用沿路径采样出的**带形**；
   两者都拿不到时才退回容器框（并叠上 rotation）。
   Sutherland–Hodgman 要求两边都是凸的，所以弧带被拆成 N 段凸四边形分别求交再相加。 */
function zonePolys(z, W, H, ink) {
  if (ink && ink.polys && ink.polys.length) return { polys: ink.polys, _ink: '带' };
  if (ink && ink.box && ink.box[2] > 0 && ink.box[3] > 0) {
    const x = ink.box[0], y = ink.box[1], w = ink.box[2], h = ink.box[3];
    return { polys: [[[x, y], [x + w, y], [x + w, y + h], [x, y + h]]], _ink: '字' };
  }
  const b = Array.isArray(z.box)
    ? { x: z.box[0] * W, y: z.box[1] * H, w: z.box[2] * W, h: z.box[3] * H }
    : { x: z.box.x, y: z.box.y, w: z.box.w, h: z.box.h };
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
  const deg = (z.style && z.style.rotate) || 0;
  const th = deg * Math.PI / 180, co = Math.cos(th), si = Math.sin(th);
  const pts = [[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]];
  return {
    polys: [deg ? pts.map(([x, y]) => {
      const dx = x - cx, dy = y - cy;
      return [cx + dx * co - dy * si, cy + dx * si + dy * co];
    }) : pts]
  };
}
function clipArea(A, B) {
  const cross = (a, b, p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
  let out = A;
  for (let i = 0; i < B.length && out.length; i++) {
    const a = B[i], b = B[(i + 1) % B.length], inp = out;
    out = [];
    for (let j = 0; j < inp.length; j++) {
      const p = inp[j], q = inp[(j + 1) % inp.length];
      const d1 = cross(a, b, p), d2 = cross(a, b, q);
      if (d1 >= 0) out.push(p);
      if ((d1 >= 0) !== (d2 >= 0)) {
        const t = d1 / (d1 - d2);
        out.push([p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]);
      }
    }
  }
  if (out.length < 3) return 0;
  let s = 0;
  for (let i = 0; i < out.length; i++) {
    const p = out[i], q = out[(i + 1) % out.length];
    s += p[0] * q[1] - q[0] * p[1];
  }
  return Math.abs(s) / 2;
}
function staticOverlap(INKS) {
  const probs = [];
  INKS = INKS || {};
  PAGES.forEach((pid) => {
    const L = LAYOUTS[pid]; if (!L) return;
    const W = (L.canvas && L.canvas.w) || 1366, H = (L.canvas && L.canvas.h) || 1748;
    /* ★返回**整个墨迹对象**（{box} 或 {polys}），不是其中的 polys 数组 ——
       zonePolys() 要按「弧带 → 字迹盒 → 容器框」三级回落，只给它数组会退化成容器框。 */
    const ink = (id) => (INKS[pid] && INKS[pid][id]) || null;
    const texts = (L.zones || []).filter((z) => ['text', 'badge', 'torn', 'bubble', 'label'].includes(z.kind || 'text')
      && z.box && !z.overlapOK);
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
      const A = zonePolys(texts[i], W, H, ink(texts[i].id));
      const B = zonePolys(texts[j], W, H, ink(texts[j].id));
      const span = (P) => {
        let x0 = Infinity, x1 = -Infinity;
        P.forEach((q) => q.forEach((p) => { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); }));
        return [x0, x1];
      };
      const [a0, a1] = span(A.polys), [b0, b1] = span(B.polys);
      if (a1 < b0 || b1 < a0) continue;                 // 快速排除
      let a = 0;
      for (const pa of A.polys) for (const pb of B.polys) a += clipArea(pa, pb);
      if (a > HIT) probs.push({ page: pid, tag: '版面',
        bad: [`文字互压：${texts[i].id}(${A._ink || '框'}迹) ∩ ${texts[j].id}(${B._ink || '框'}迹) ` +
          `${Math.round(a)}px²（阈值 ${HIT}，凸多边形求交）—— 改 layout 坐标，或给其中一个加 "overlapOK": true`] });
    }
  });
  return probs;
}

/* ------------------------------------------------------------------ 主流程 */
(async () => {
  const slotsRaw = fs.readFileSync(path.join(ROOT, 'copy', 'slots.json'), 'utf8');
  const results = [];
  if (PAGES.length) {
    const c1 = await openChrome(PORT, 'wb-copycheck');
    await c1.cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: 'window.__slots = ' + slotsRaw + ';' });
    await c1.cdp.send('Emulation.setDeviceMetricsOverride',
      { width: 1440, height: 1810, deviceScaleFactor: 1, mobile: false });
    for (const lang of LANGS) for (const p of PAGES) {
      await c1.cdp.send('Page.navigate',
        { url: 'file:///' + path.join(ROOT, p + '.html').replace(/\\/g, '/') + '?lang=' + lang });
      await sleep(900);
      const r = await c1.cdp.send('Runtime.evaluate', { expression: AUDIT, returnByValue: true });
      const v = r.result.value || { page: p, fatal: '审计表达式无返回' };
      v.asked = lang; v.lang = v.lang || lang;
      results.push(v);
    }
    c1.kill();
  }

  /* 弧排/斜置字的墨迹盒：同一页会跑 jp / zh 两遍，取第一遍即可 */
  const INKS = {};
  results.forEach((r) => { if (r.page && r.inks) INKS[r.page] = Object.assign(INKS[r.page] || {}, r.inks); });
  const layout = NO_LAYOUT ? [] : staticOverlap(INKS);
  const report = { langs: LANGS, pages: results, layout: layout, fails: [], ok: false };

  const NEUTRAL = /^[A-Za-z0-9\u2460-\u2468\s\u30fb\/\-+\u00d7\u2665\u2014\u2013.()（）]+$/;
  results.forEach((r) => {
    const bad = new Set();
    if (r.fatal) bad.add(r.fatal);
    if (r.asked !== r.lang) bad.add(`请求 lang=${r.asked}，页面实际渲染 lang=${r.lang}`);
    (r.errors || []).forEach((e) => bad.add(`注入失败 ${e.sel} → ${e.why}`));
    (r.unresolved || []).forEach((e) => bad.add(`选择器 ${e.sel} → ${e.why}`));
    (r.collisions || []).forEach((e) => bad.add(`两个选择器撞同一元素：${e.sel}（${e.text}）`));
    (r.coverage || []).forEach((e) => { if (NEUTRAL.test(e.text || '')) return;
      bad.add(`漏写槽位 ${e.sel} → ${e.why}：${e.text}`); });
    (r.forbidden || []).forEach((e) => bad.add(`禁用词[${e.group}]「${e.term}」→ …${e.ctx}…`));
    if (r.slogan && r.slogan.found && !r.slogan.paired)
      bad.add(`Slogan 未配平 →「…${r.slogan.after}」`);
    /* E② 溢出 / 出画布 */
    if (r.canvas) {
      Object.keys(r.rects || {}).forEach((id) => {
        const q = r.rects[id], why = [];
        if (q.sh > q.ch + 2) why.push(`纵向溢出：内容 ${q.sh}px > 框 ${q.ch}px`);
        if (q.sw > q.cw + 2) why.push(`横向溢出：内容 ${q.sw}px > 框 ${q.cw}px`);
        const outside = q.x < -0.5 || q.y < -0.5 || q.x + q.w > r.canvas[0] + 0.5 || q.y + q.h > r.canvas[1] + 0.5;
        if (outside) why.push(`出画布：x${Math.round(q.x)} y${Math.round(q.y)} ${Math.round(q.w)}×${Math.round(q.h)}（画布 ${r.canvas[0]}×${r.canvas[1]}）`);
        if (why.length) bad.add(`版面 ${id}：${why.join('；')}｜「${q.text}」`);
      });
    }
    r.bad = [...bad];
    if (r.bad.length) report.fails.push({ page: r.page, tag: r.lang, bad: r.bad });
  });
  layout.forEach((l) => report.fails.push(l));
  report.ok = report.fails.length === 0;

  if (JSONONLY) { console.log(JSON.stringify(report, null, 1)); process.exit(report.ok ? 0 : 1); }

  console.log(`文案校验  ${LANGS.join(' + ')}`);
  console.log('─'.repeat(90));
  results.forEach((r) => {
    const ok = (r.bad || []).length === 0;
    const stray = (r.coverage || []).filter((e) => !NEUTRAL.test(e.text || '')).length;
    console.log(`${ok ? ' OK ' : 'FAIL'}  ${r.page} [${r.lang}]  写入 ${String(r.applied).padStart(3)}/${String(r.slots).padEnd(3)} 槽位` +
      `   漏写 ${stray}   禁用词 ${(r.forbidden || []).length}`);
  });
  if (!NO_LAYOUT) {
    console.log('─'.repeat(90));
    const byPage = {};
    layout.forEach((l) => { byPage[l.page] = (byPage[l.page] || 0) + l.bad.length; });
    PAGES.forEach((p) => console.log(`${byPage[p] ? 'FAIL' : ' OK '}  ${p} [版面]  ${byPage[p] ? byPage[p] + ' 处文字框互压' : '文字框无互压'}`));
  }
  if (report.fails.length) {
    console.log('\n' + '─'.repeat(90));
    report.fails.forEach((f) => {
      console.log(`\n【${f.page} · ${f.tag}】${f.bad.length} 项`);
      f.bad.slice(0, 20).forEach((b) => console.log('   · ' + b));
      if (f.bad.length > 20) console.log(`   … 另有 ${f.bad.length - 20} 项`);
    });
  }
  console.log('\n' + '─'.repeat(90));
  console.log(report.ok
    ? `${results.length} 次文案校验 + ${layout.length} 组版面检查，全部通过。`
    : `${report.fails.length} 组有问题。`);
  process.exit(report.ok ? 0 : 1);
})().catch((e) => { console.error('FAIL', e.message); process.exit(1); });
