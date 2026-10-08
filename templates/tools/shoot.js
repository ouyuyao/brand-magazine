/**
 * shoot.js —— 精确出图（CDP，无第三方依赖）
 *
 * 为什么不用 `chrome --screenshot`：那样会受「适合视窗」缩放影响
 * （实测 1366×1748 的画布被缩到 0.9216 倍、并偏移 83px），后期按坐标裁切必然错位。
 * 这里用 Emulation.setDeviceMetricsOverride 把视口精确设成**该页画布尺寸**，
 * 配合页面的 ?shot=1（1:1、无工具列），得到像素级准确的 PNG。
 *
 * 页数 = layout/*.json 的个数（不写死，跟着参考图张数走）。每页画布尺寸各按自己的
 * layout JSON 的 canvas —— 所以允许不同页用不同尺寸。
 *
 * 用法：
 *   node tools/shoot.js                    # 全部页 → _shots/pageNN.png
 *   node tools/shoot.js page02 page07      # 指定页
 *   node tools/shoot.js --dsf 2 page02     # 2 倍图（高清审查）
 *   node tools/shoot.js --query "lang=zh" --tag zh   # 中文对照稿
 *   node tools/shoot.js --ui page05        # 保留工具列
 */
const path = require('path'); const fs = require('fs');
const { spawn } = require('child_process'); const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, '_shots');
const PORT = 9335;
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* 页列表：来自 layout/*.json（去掉临时文件） */
function pagesFromLayout() {
  const dir = path.join(ROOT, 'layout');
  if (!fs.existsSync(dir)) throw new Error('缺 layout/ 目录（先写 layout JSON，页数 = 参考图张数）');
  return fs.readdirSync(dir).filter(f => /\.json$/.test(f) && !/^_/.test(f))
    .map(f => (f.match(/(\d+)/) || [, ''])[1]).filter(Boolean)
    .sort((a, b) => +a - +b)
    .map(n => 'page' + (n.length < 2 ? '0' + n : n));
}

const argv = process.argv.slice(2);
let dsf = 1, query = '', outDir = OUT, tag = '', ui = false;
const di = argv.indexOf('--dsf'); if (di >= 0) { dsf = +argv[di + 1] || 1; argv.splice(di, 2); }
const qi = argv.indexOf('--query'); if (qi >= 0) { query = argv[qi + 1] || ''; argv.splice(qi, 2); }
const oi = argv.indexOf('--out'); if (oi >= 0) { outDir = argv[oi + 1]; argv.splice(oi, 2); }
const ti = argv.indexOf('--tag'); if (ti >= 0) { tag = argv[ti + 1] || ''; argv.splice(ti, 2); }
const uiIdx = argv.indexOf('--ui'); if (uiIdx >= 0) { ui = true; argv.splice(uiIdx, 1); }
const only = argv.filter(a => /^page\d+$/.test(a) || a === 'index');
const pages = only.length ? only : ['index'].concat(pagesFromLayout());

const EXPR = `(() => {
  const pg = document.querySelector('.page');
  const wrap = document.querySelector('.stage-wrap');
  /* 先关 transition 再改 transform：否则会量到动画中间值 */
  if (wrap) { wrap.style.transition = 'none'; wrap.style.transform = 'none'; }
  window.scrollTo(0, 0);
  document.documentElement.style.margin = '0';
  document.body.style.margin = '0';
  const el = pg || document.querySelector('.stage');
  const rr = el.getBoundingClientRect();
  return { x: rr.left, y: rr.top, w: rr.width, h: rr.height,
           offset: [el.offsetWidth, el.offsetHeight] };
})()`;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--no-first-run', '--font-render-hinting=none',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + path.join(os.tmpdir(), 'wbshoot' + Date.now()),
    '--window-size=1400,1800', 'about:blank'], { stdio: 'ignore' });

  let list;
  for (let i = 0; i < 40; i++) {
    await sleep(300);
    try { list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      if (list.some(t => t.type === 'page')) break; } catch (e) { }
  }
  const target = (list || []).find(t => t.type === 'page');
  if (!target) { chrome.kill(); throw new Error('Chrome 未就绪'); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0; const pend = new Map(); const evs = [];
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = m => {
    const d = JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { const h = pend.get(d.id); pend.delete(d.id); h(d.result); }
    else if (d.method) for (let i = evs.length - 1; i >= 0; i--)
      if (evs[i].n === d.method) { evs.splice(i, 1)[0].f(); }
  };
  const send = (method, params = {}) => new Promise(r => {
    const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params }));
  });
  const once = (n, t = 15000) => new Promise((res, rej) => {
    const to = setTimeout(() => rej(new Error('timeout ' + n)), t);
    evs.push({ n, f: () => { clearTimeout(to); res(); } });
  });

  await send('Page.enable'); await send('Runtime.enable');

  const made = [];
  for (const name of pages) {
    const qs = [];
    if (!ui) qs.push('shot=1');
    if (query) qs.push(query);
    const url = 'file:///' + path.join(ROOT, name + '.html').replace(/\\/g, '/')
      + (qs.length ? '?' + qs.join('&') : '');
    await send('Page.navigate', { url });
    await once('Page.loadEventFired');
    /* 内嵌 CJK 明朝体单个 1.3MB，document.fonts.ready 之前截图会拿回落字体 */
    await send('Runtime.evaluate', {
      expression: 'document.fonts.ready.then(()=>true)', awaitPromise: true, returnByValue: true,
    });
    await sleep(700);

    const m = await send('Runtime.evaluate', { expression: EXPR, returnByValue: true });
    const v = (m.result.value && m.result.value.w) ? m.result.value : { x: 0, y: 0, w: 1366, h: 1748 };
    await send('Emulation.setDeviceMetricsOverride', {
      width: Math.round(v.w), height: Math.round(v.h), deviceScaleFactor: dsf, mobile: false,
    });
    await sleep(450);
    const shot = await send('Page.captureScreenshot',
      { format: 'png', captureBeyondViewport: false, fromSurface: true });
    const file = path.join(outDir, (name === 'index' ? 'idx' : name) + (tag ? '_' + tag : '') + '.png');
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    made.push(file);
    const st = fs.statSync(file);
    console.log(`${name.padEnd(8)} ${Math.round(v.w)}×${Math.round(v.h)} @${dsf}x  -> ${path.basename(file)}  ${(st.size / 1024).toFixed(0)}KB`);
  }
  send('Emulation.clearDeviceMetricsOverride').catch(() => { });
  ws.close(); chrome.kill();
  console.log(`\n共 ${made.length} 张 -> _shots/`);
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
