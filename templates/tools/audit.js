/**
 * audit.js —— 版式布局审计（无依赖，走 Chrome DevTools Protocol）
 *
 * 用途：把每页所有「绝对定位区块」的真实坐标、尺寸、底边位置量出来，
 *      用于判断内容是否被挤压在页面上半部、底部是否留出死白。
 *      纯靠肉眼看截图很容易误判，这个工具给的是可复核的数字。
 *
 * 用法：
 *   node tools/audit.js                     # 审计全部页面
 *   node tools/audit.js page02 page07       # 只审计指定页
 *   node tools/audit.js --url-query "lang=zh" # 带 query 审计（中文对照稿）
 *
 * 依赖：本机 Chrome。启动参数见 CHROME 常量。
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const PORT = 9333;
const CHROME = process.env.CHROME_PATH ||
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const DEAD_BOTTOM = 90;         // 底边留白超过这个值就视为「死白/上挤」

/* ---------- 参数 ---------- */
const argv = process.argv.slice(2);
let urlQuery = '';
const qi = argv.indexOf('--url-query');
if (qi >= 0) { urlQuery = argv[qi + 1] || ''; argv.splice(qi, 2); }
const only = argv.filter(a => /^page\d+$/.test(a) || a === 'index');

/* 页数来自 layout/（不写死：页数 = 参考图张数） */
const pages = (only.length ? only : ['index'].concat(require('fs').readdirSync(path.join(ROOT,'layout')).filter(f=>/\.json$/.test(f)&&!/^_/.test(f)).map(f=>(f.match(/(\d+)/)||[,''])[1]).filter(Boolean).sort((a,b)=>+a-+b).map(n=>'page'+(n.length<2?'0'+n:n))))
  .map(n => ({ name: n, url: 'file:///' + path.join(ROOT, n + '.html').replace(/\\/g, '/')
    + (urlQuery ? '?' + urlQuery : '') }));

/* ---------- 采集脚本（在页面里跑） ---------- */
const PROBE = `(() => {
  const page = document.querySelector('.page'); if (!page) return {error:'no .page'};
  const pr = page.getBoundingClientRect();
  const sx = pr.width / page.offsetWidth || 1;   // 若有 CSS 缩放
  const out = [];
  const seen = new Set();
  page.querySelectorAll('*').forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.position !== 'absolute' && cs.position !== 'fixed') return;
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    if (!el.offsetWidth && !el.offsetHeight) return;
    const r = el.getBoundingClientRect();
    if (r.width < 6 || r.height < 6) return;
    // 用「元素 + 左上位」做去重，避免同选择器多层命中
    const key = [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height),
                 (el.className||'').toString().slice(0,40)].join('|');
    if (seen.has(key)) return; seen.add(key);
    const cls = (el.className || '').toString().trim().split(/\\s+/).slice(0, 3).join('.');
    out.push({
      sel: el.tagName.toLowerCase() + (cls ? '.' + cls : ''),
      x: Math.round((r.left - pr.left) / sx),
      y: Math.round((r.top - pr.top) / sx),
      w: Math.round(r.width / sx),
      h: Math.round(r.height / sx),
      z: cs.zIndex,
      txt: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 26)
    });
  });
  out.sort((a, b) => (a.y + a.h) - (b.y + b.h));
  return { canvas: {w: page.offsetWidth, h: page.offsetHeight}, els: out };
})()`;

/* ---------- 简易 CDP 客户端 ---------- */
function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pend = new Map(); const evs = [];
    ws.onopen = () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id; pend.set(mid, { res, rej });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      once(name, timeout = 15000) {
        return new Promise((res, rej) => {
          const t = setTimeout(() => rej(new Error('timeout ' + name)), timeout);
          evs.push({ name, res: () => { clearTimeout(t); res(); } });
        });
      },
      close() { try { ws.close(); } catch (e) {} },
    });
    ws.onerror = e => reject(new Error('ws error'));
    ws.onmessage = m => {
      const d = JSON.parse(m.data);
      if (d.id && pend.has(d.id)) {
        const { res, rej } = pend.get(d.id); pend.delete(d.id);
        d.error ? rej(new Error(d.error.message)) : res(d.result);
      } else if (d.method) {
        for (let i = evs.length - 1; i >= 0; i--) {
          if (evs[i].name === d.method) { const h = evs.splice(i, 1)[0]; h.res(); }
        }
      }
    };
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------- 主流程 ---------- */
(async () => {
  const userDir = path.join(os.tmpdir(), 'wb-audit-profile-' + Date.now());
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + userDir,
    '--window-size=1440,1810', 'about:blank',
  ], { stdio: 'ignore' });

  let list;
  for (let i = 0; i < 40; i++) {
    await sleep(300);
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      list = await r.json();
      if (list.some(t => t.type === 'page')) break;
    } catch (e) { /* 还没起来 */ }
  }
  const target = (list || []).find(t => t.type === 'page');
  if (!target) { chrome.kill(); throw new Error('Chrome 未就绪'); }

  const cdp = await connect(target.webSocketDebuggerUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  const report = {};
  for (const p of pages) {
    await cdp.send('Page.navigate', { url: p.url });
    await cdp.once('Page.loadEventFired');
    await sleep(700);                       // 等字体 / 图片解码
    const r = await cdp.send('Runtime.evaluate',
      { expression: PROBE, returnByValue: true, awaitPromise: false });
    const v = r.result.value;
    if (!v || v.error) { console.log(`[${p.name}] ${v && v.error}`); continue; }
    report[p.name] = v;
  }

  /* ---- 输出 ---- */
  for (const [name, v] of Object.entries(report)) {
    const els = v.els.filter(e => e.w > 20 && e.h > 12);
    if (!els.length) { console.log(`${name}: 无绝对定位区块`); continue; }
    const bottom = Math.max(...els.map(e => e.y + e.h));
    // “有效内容底”＝排除三类元素后的最大底边：
    //   1) 页脚（页码 / 水印 / 注记）—— 本来就在底部
    //   2) 叠图比对层（ref-overlay）—— 满版且只在验收时出现
    //   3) 满版出血底图（高度 ≥ 画布 90%）—— 它撑满整页，不代表内容分布
    const full = v.canvas.h * 0.9;
    const main = els.filter(e => !/pageno|\.wm|foot|credit/i.test(e.sel)
      && !/ref-overlay/.test(e.sel) && e.h < full);
    const mainBottom = main.length ? Math.max(...main.map(e => e.y + e.h)) : bottom;
    const dead = v.canvas.h - mainBottom;    /* 逐页用自己的画布高，不写死 */
    const flag = dead > DEAD_BOTTOM ? '  ← 底部死白 ' + dead + 'px' : '';
    console.log(`\n=== ${name}  画布 ${v.canvas.w}×${v.canvas.h} | 内容底 ${mainBottom} | 底部留白 ${dead}px${flag}`);
    const seg = {};                                   // 每 200px 内容量
    els.forEach(e => { const k = Math.floor(e.y / 200) * 200; seg[k] = (seg[k] || 0) + 1; });
    console.log('    纵向分布(每200px区块数): ' +
      Array.from({ length: 9 }, (_, i) => `${i * 200}:${seg[i * 200] || 0}`).join(' '));
    els.filter(e => e.y + e.h > 1000).forEach(e =>
      console.log(`    y${String(e.y).padStart(4)}→${String(e.y + e.h).padStart(4)} h${String(e.h).padStart(4)} x${String(e.x).padStart(4)} w${String(e.w).padStart(4)}  ${e.sel}  ${e.txt}`));
  }
  fs.writeFileSync(path.join(ROOT, '_shots', '_audit.json'), JSON.stringify(report, null, 1));
  cdp.close(); chrome.kill();
  console.log('\n原始数据 -> _shots/_audit.json');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
