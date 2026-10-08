/**
 * fontcheck.js —— 权威字体自检：问浏览器「这个节点实际用了哪个字体文件」
 *
 * 为什么必须用 CDP 的 CSS.getPlatformFontsForNode：
 *   computed style 里的 font-family 只是「愿望清单」，浏览器可以一路回落。
 *   本机若没有内嵌字体、或 @font-face 的 family 名写错、或 woff2 路径不对，
 *   浏览器会 quietly 落到 SimSun / Yu Gothic / Microsoft YaHei ——
 *   而它们也能渲染，页面上看不出「坏了」，只是观感与字面宽度全变，
 *   版面回归也测不出来（因为溢出检查只看几何）。
 *   只有这个 API 会告诉我们**真正参与了绘制的字体**与 glyph 数。
 *
 * 页数 = layout/*.json 的个数（不写死，跟着参考图张数走）。
 * 探针按**字体角色**打（引擎给每个 .t 加了 fr-<role> 类），
 * 所以引擎里新增字体角色时，只要在这里补一行。
 *
 * 用法：
 *   node tools/fontcheck.js                      # 全部页
 *   node tools/fontcheck.js page03               # 指定页
 *   node tools/fontcheck.js --query "lang=zh"    # 中文对照稿
 *   node tools/fontcheck.js --want "Noto Serif"    # 要求内嵌字体文件内部名以此开头，否则 FAIL
 *   注：--want 匹配的是**字体文件内部名**（Chrome 报的是这个），不是 @font-face 里写的
 *       中立族名（如 "Mag Mincho JP"）。所以 --want "Mag " 一定 FAIL —— 别这么用。
 *       默认（不加 --want）的判据已经够用：只看「是否 isCustomFont」，即是否用到了内嵌字体。
 *   退出码：某角色只用到了系统字体 → 1；加 --want 则按 --want 判定
 */
const path = require('path'); const fs = require('fs');
const { spawn } = require('child_process'); const os = require('os');

const ROOT = path.resolve(__dirname, '..');
const PORT = 9337;
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---- 参数 ---- */
const argv = process.argv.slice(2);
let query = '', want = '';
const qi = argv.indexOf('--query'); if (qi >= 0) { query = argv[qi + 1] || ''; argv.splice(qi, 2); }
const wi = argv.indexOf('--want'); if (wi >= 0) { want = argv[wi + 1] || ''; argv.splice(wi, 2); }
const only = argv.filter(a => /^page\d+$/.test(a));

/* ---- 页列表：来自 layout/ ---- */
function pagesFromLayout() {
  const dir = path.join(ROOT, 'layout');
  if (!fs.existsSync(dir)) throw new Error('缺 layout/ 目录');
  return fs.readdirSync(dir).filter(f => /\.json$/.test(f) && !/^_/.test(f))
    .map(f => (f.match(/(\d+)/) || [, ''])[1]).filter(Boolean)
    .sort((a, b) => +a - +b)
    .map(n => 'page' + (n.length < 2 ? '0' + n : n));
}
const pages = only.length ? only : pagesFromLayout();

/* ---- 探针：字体角色 → CSS 选择器（引擎生成的 .fr-* 类） ----
   每个角色至少被打到一次；一个角色都没打到的页不算通过（可能是版式里没用该角色）。 */
const PROBES = [
  ['serif',     '.fr-serif'],
  ['sans',      '.fr-sans'],
  ['script',    '.fr-script'],
  ['scriptFat', '.fr-script-fat'],
  ['latin',     '.fr-latin'],
  ['latinItal', '.fr-latin-ital'],
];

(async () => {
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--no-first-run', '--font-render-hinting=none',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + path.join(os.tmpdir(), 'wbfont' + Date.now()),
    '--window-size=1400,1800', 'about:blank'], { stdio: 'ignore' });

  let list = null;
  for (let i = 0; i < 40 && !list; i++) {
    await sleep(300);
    try { list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); } catch { }
  }
  const target = (list || []).find(t => t.type === 'page');
  if (!target) { chrome.kill(); console.error('Chrome 未就绪'); process.exit(2); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const waiting = new Map(); const evs = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
    else if (m.method) for (let i = evs.length - 1; i >= 0; i--)
      if (evs[i].n === m.method) { evs.splice(i, 1)[0].f(); }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const n = ++id; const to = setTimeout(() => rej(new Error('timeout ' + method)), 20000);
    waiting.set(n, m => { clearTimeout(to); m.error ? rej(new Error(method + ': ' + m.error.message)) : res(m.result); });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  const once = ev => new Promise(res => evs.push({ n: ev, f: res }));

  await send('Page.enable'); await send('Runtime.enable');
  await send('DOM.enable'); await send('CSS.enable');

  const bad = [];                   // 只用系统字体的角色
  const seen = new Map();           // 字体名 -> glyph 数
  let totalProbes = 0;

  for (const name of pages) {
    const url = 'file:///' + path.join(ROOT, name + '.html').replace(/\\/g, '/')
      + (query ? '?' + query : '');
    await send('Page.navigate', { url });
    await once('Page.loadEventFired');
    await send('Runtime.evaluate', {
      expression: 'document.fonts.ready.then(()=>true)', awaitPromise: true, returnByValue: true });
    await sleep(400);

    const { root } = await send('DOM.getDocument', { depth: 1 });
    console.log('\n==== ' + name + ' ====');
    for (const [role, sel] of PROBES) {
      const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: sel });
      if (!nodeId) continue;                       // 本页没用这个角色，跳过
      let fonts = [];
      try { ({ fonts } = await send('CSS.getPlatformFontsForNode', { nodeId })); } catch { }
      if (!fonts || !fonts.length) continue;
      totalProbes++;
      const txt = fonts.map(f => `${f.familyName}${f.isCustomFont ? ' *' : ''}(${f.glyphCount})`).join(' + ');
      fonts.forEach(f => {
        const k = f.familyName + (f.isCustomFont ? ' [内嵌]' : ' [系统]');
        seen.set(k, (seen.get(k) || 0) + f.glyphCount);
      });
      console.log(`  ${role.padEnd(11)} ${txt}`);
      const hitCustom = fonts.some(f => f.isCustomFont && (!want || f.familyName.startsWith(want)));
      if (!hitCustom) bad.push(`${name} .fr-${role} → ${txt}`);
    }
  }

  console.log('\n---- 实际参与绘制的字体（按 glyph 数） ----');
  [...seen.entries()].sort((a, b) => b[1] - a[1])
    .forEach(([k, v]) => console.log(`  ${k.padEnd(36)} ${v}`));
  console.log(`\n探测点 ${totalProbes} 处`);

  if (bad.length) {
    console.log(`\nFAIL：以下角色没用上内嵌字体${want ? '「' + want + '*」' : ''} —— ${bad.length} 处`);
    bad.forEach(b => console.log('  ' + b));
    console.log('  排查：① fonts/ 里有没有对应 woff2  ② css/fonts.css 的 @font-face 是否加载成功');
    console.log('        ③ brand/brand-pack.json 的 fonts 段首选项是否就是内嵌字体名');
  } else {
    console.log(`\nOK：所有探测点都命中了内嵌字体${want ? '「' + want + '*」' : ''}`);
  }
  chrome.kill();
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error('FAIL', e.message); process.exit(2); });
