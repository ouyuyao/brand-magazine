#!/usr/bin/env node
/**
 * check-variant.js —— 变体引擎自检（无头 Chrome + CDP）
 *
 * 为什么需要：变体引擎最怕两种「静默失效」：
 *   ① seed 明明给了，页面却完全没变（选择器写错 / 脚本 404 / 白名单没生效）；
 *   ② seed 为 null 时页面却变了（越权扰动 —— 复刻就不保真了）。
 * 本脚本对 layout/ 里的每一页各跑三种状态：
 *   · 无 seed            → 期望 html[data-variant] 为空、无 .v-motif（严格保真）
 *   · ?seed=<固定串>     → 期望 data-motif 有值、.v-motif 存在、window.__variant 有值
 *   · ?seed=<固定串> 再跑 → 期望与上一次**完全一致**（可复现）
 * 三者全过才输出 PASS。
 *
 * 用法：node tools/check-variant.js [--port 9411] [--keep]
 * 退出码：0 全过   1 有 FAIL   2 起不了 Chrome / 缺 layout
 */
'use strict';
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const argv = process.argv.slice(2);
const portIdx = argv.indexOf('--port');
const PORT = portIdx >= 0 ? +argv[portIdx + 1] : 9411;
const CHROME = process.env.CHROME_PATH ||
  ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
   'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
   '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
   '/usr/bin/google-chrome', '/usr/bin/chromium'].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const LAY = path.join(ROOT, 'layout');
if (!fs.existsSync(LAY)) { console.error('FAIL 缺 layout/ 目录'); process.exit(2); }
const PAGES = fs.readdirSync(LAY)
  .filter((f) => /\.json$/.test(f) && !/^_/.test(f))
  .map((f) => {
    let id = f;
    try { id = JSON.parse(fs.readFileSync(path.join(LAY, f), 'utf8')).id || f; } catch (e) { }
    const n = (String(id).match(/(\d+)/) || [, ''])[1];
    return n ? 'page' + (n.length < 2 ? '0' + n : n) + '.html' : null;
  })
  .filter(Boolean)
  .filter((f) => fs.existsSync(path.join(ROOT, f)))
  .sort();
if (!PAGES.length) { console.error('FAIL layout/ 里的页还没有对应的 pageNN.html —— 先跑 node build.js'); process.exit(2); }
if (!CHROME) { console.error('FAIL 找不到 Chrome —— 设 CHROME_PATH 环境变量指向可执行文件'); process.exit(2); }

const PROBE = "(()=>{const b=document.querySelector('.tb-variant');"
  + "return {hasButton:!!b, label:b?b.textContent.trim():null, motif:!!document.querySelector('.v-motif'),"
  + "variant:document.documentElement.getAttribute('data-variant')||'',"
  + "attrs:['data-motif','data-frame','data-grade'].map(k=>k+'='+document.documentElement.getAttribute(k)).join(' '),"
  + "varInfo:window.__variant||null};})()";

(async () => {
  const c = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + path.join(os.tmpdir(), 'chkv' + Date.now()),
    '--window-size=1200,900', 'about:blank'], { stdio: 'ignore' });

  let list = null;
  for (let i = 0; i < 50; i++) {
    await sleep(300);
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      list = await r.json();
      if (list.some((t) => t.type === 'page')) break;
    } catch (e) { }
  }
  const t = list && list.find((x) => x.type === 'page');
  if (!t) { console.error('FAIL 起不了无头 Chrome'); try { c.kill(); } catch (e) { } process.exit(2); }

  const ws = new WebSocket(t.webSocketDebuggerUrl);
  let id = 0; const p = new Map();
  await new Promise((r) => { ws.onopen = r; });
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && p.has(d.id)) { p.get(d.id)(d.result); p.delete(d.id); } };
  const send = (m, q = {}) => new Promise((r) => { const i = ++id; p.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: q })); });
  await send('Page.enable'); await send('Runtime.enable');

  const SEED = 'check-seed-1';
  const vis = async (file, q) => {
    await send('Page.navigate', { url: 'file:///' + path.join(ROOT, file).replace(/\\/g, '/') + q });
    await sleep(1000);
    const r = await send('Runtime.evaluate', { expression: PROBE, returnByValue: true });
    return r.result.value || {};
  };

  let failed = 0;
  const say = (ok, msg) => { if (!ok) failed++; console.log((ok ? '  ok   ' : '  FAIL ') + msg); };

  for (const f of PAGES) {
    console.log(f);
    /* ① 无 seed → 严格保真 */
    const a = await vis(f, '');
    say(!a.variant && !a.motif, '无 seed：data-variant 为空且无 .v-motif（严格保真）' +
      (a.variant || a.motif ? ` ← 实际 variant="${a.variant}" motif=${a.motif}` : ''));

    /* ② 有 seed → 确实变了 */
    const b1 = await vis(f, '?seed=' + SEED);
    say(!!b1.variant && b1.motif && !!b1.varInfo,
      'seed=' + SEED + '：已扰动（' + (b1.attrs || '') + '）');
    say(!!b1.varInfo && b1.varInfo.seed === SEED, 'window.__variant.seed 正确');

    /* ③ 同 seed 再跑 → 完全可复现 */
    const b2 = await vis(f, '?seed=' + SEED);
    say(JSON.stringify(b1.varInfo) === JSON.stringify(b2.varInfo),
      '同 seed 两次结果一致（可复现）');
  }

  try { c.kill(); } catch (e) { }
  console.log(failed ? `\nFAIL 共 ${failed} 项未过` : '\nPASS 变体引擎自检全过');
  process.exit(failed ? 1 : 0);
})();
