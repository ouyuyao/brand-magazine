#!/usr/bin/env node
/**
 * inkprobe.js —— 字重墨迹探针：判定 font-weight 到底有没有真的生效
 *
 * 为什么需要它（弥补 fontcheck.js 的盲区）：
 *   fontcheck.js 用 CSS.getPlatformFontsForNode 只能证明「这个节点用了哪个字体文件」，
 *   它证明不了「字重生效」——因为字体文件内部的命名（例如 Noto 的 CJK 分片叫
 *   ExtraLight / Thin）跟实际字重无关。唯一可靠的判据是**量笔画**：
 *   同字号、同字符串渲染，数非白像素占比；字重越大，墨迹必须越粗。
 *
 * 它还顺带解决本引擎一条长期悬而未决的事：
 *   品牌包 visual.maxWeight 往往是 500，而出厂版式里散落着 700 / 900。
 *   有了本探针，「700 与 400 差多少墨」第一次变成可量化的数，不再是感觉。
 *
 * 用法：
 *   node tools/inkprobe.js                 # 量全部角色 × 字重，带自动判据，退出码 0/1
 *   node tools/inkprobe.js --json          # 只输出 JSON（供别的脚本消费）
 *   node tools/inkprobe.js --delta 0.8     # 覆盖「700 相对 400 至少要粗多少个百分点」阈值
 *
 * 判据：
 *   · 同一内嵌族，墨迹必须随字重单调不减；
 *   · 400 → 700 的增量必须 ≥ DELTA_MIN（默认 0.5 个百分点）。
 *   任一不满足 → 打印 FAIL 并以退出码 1 结束。
 *
 * 依赖：Node ≥ 18（内置 fetch / WebSocket）、本机 Chrome。
 *       Chrome 路径可用环境变量 CHROME_PATH 覆盖。
 */
'use strict';
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const argv = process.argv.slice(2);
const AS_JSON = argv.includes('--json');
const di = argv.indexOf('--delta');
const DELTA_MIN = di >= 0 ? parseFloat(argv[di + 1]) : 0.5;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 字符串按字形覆盖分三组，避免手写体/拉丁体缺字导致量到的是回退字形 */
const TXT = { jp: '日本語明朝体見本', sc: '中文宋体样本', la: 'Step NEWS' };

/* 用例：f=字体族（引擎中立名，来自 css/fonts.css）、w=字重、t=测试串、style、label */
const CASES = [
  { f: '"Mag Mincho JP"', w: 400, t: TXT.jp, label: 'Mag Mincho JP 400（明朝·正文字重基准）' },
  { f: '"Mag Mincho JP"', w: 700, t: TXT.jp, label: 'Mag Mincho JP 700' },
  { f: '"Mag Mincho JP"', w: 900, t: TXT.jp, label: 'Mag Mincho JP 900' },
  { f: '"Mag Mincho SC"', w: 400, t: TXT.sc, label: 'Mag Mincho SC 400（中文稿字形）' },
  { f: '"Mag Mincho SC"', w: 700, t: TXT.sc, label: 'Mag Mincho SC 700' },
  { f: '"Mag Mincho SC"', w: 900, t: TXT.sc, label: 'Mag Mincho SC 900' },
  { f: '"Mag Gothic JP"', w: 400, t: TXT.jp, label: 'Mag Gothic JP 400（黑体·内文）' },
  { f: '"Mag Gothic JP"', w: 700, t: TXT.jp, label: 'Mag Gothic JP 700' },
  { f: '"Mag Script Silk"', w: 400, t: TXT.la, label: 'Mag Script Silk 400（细手写）' },
  { f: '"Mag Script Ribbon"', w: 400, t: TXT.la, label: 'Mag Script Ribbon 400（粗手写）' },
  { f: '"Mag Editorial"', w: 400, t: TXT.la, label: 'Mag Editorial 400（拉丁衬线）' },
  { f: '"Mag Editorial Italic"', w: 400, t: TXT.la, style: 'italic', label: 'Mag Editorial Italic 400（拉丁斜体）' },
  { f: 'SimSun', w: 400, t: TXT.sc, ctl: true, label: '对照：SimSun（系统宋体，旧字体栈的落点）' },
  { f: '"Yu Mincho"', w: 400, t: TXT.jp, ctl: true, label: '对照：Yu Mincho（本机应无 → 落到回退）' },
  { f: '"MS Mincho"', w: 400, t: TXT.jp, ctl: true, label: '对照：MS Mincho（本机应无 → 落到回退）' },
];

/* 需要满足「随字重单调不减 + 400→700 增量达标」的族与阶梯 */
const LADDERS = [
  { f: '"Mag Mincho JP"', steps: [400, 700, 900] },
  { f: '"Mag Mincho SC"', steps: [400, 700, 900] },
  { f: '"Mag Gothic JP"', steps: [400, 700] },
];

function specOf(c) { return (c.style ? c.style + ' ' : '') + c.w + ' 100px ' + c.f; }

/* ---------------------------------------------------------------- CDP */
async function withChrome(fn) {
  let launched = null;
  for (let k = 0; k < 8 && !launched; k++) {
    const port = 9402 + k;
    const userDir = path.join(os.tmpdir(), 'wb-ink-' + Date.now() + '-' + k);
    const proc = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
      '--no-first-run', '--font-render-hinting=none',
      '--remote-debugging-port=' + port, '--user-data-dir=' + userDir,
      '--window-size=1100,400', 'about:blank'], { stdio: 'ignore' });
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      if (proc.exitCode !== null) break;         // spawn 失败（找不到 Chrome）
      try {
        const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const t = list.find((x) => x.type === 'page');
        if (t) { launched = { proc, port, target: t }; break; }
      } catch (e) { /* 还没起来 */ }
    }
    if (!launched) { try { proc.kill(); } catch (e) { } }
  }
  if (!launched) throw new Error('Chrome 启动失败 —— 设 CHROME_PATH 指向你的 chrome.exe');

  const { proc, target } = launched;
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const waiting = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const n = ++id;
    const to = setTimeout(() => rej(new Error('timeout ' + method)), 30000);
    waiting.set(n, (m) => {
      clearTimeout(to);
      m.error ? rej(new Error(method + ': ' + m.error.message)) : res(m.result);
    });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  const once = (ev) => new Promise((res) => {
    const h = (e) => { const m = JSON.parse(e.data); if (m.method === ev) { ws.removeEventListener('message', h); res(m); } };
    ws.addEventListener('message', h);
  });
  try { return await fn({ send, once }); }
  finally { try { ws.close(); } catch (e) { } try { proc.kill(); } catch (e) { } }
}

/* ---------------------------------------------------------------- 主流程 */
(async () => {
  const rows = await withChrome(async ({ send, once }) => {
    await send('Page.enable');
    await send('Runtime.enable');
    const url = 'file:///' + path.join(ROOT, 'tools', 'inkprobe.html').replace(/\\/g, '/');
    await send('Page.navigate', { url });
    await once('Page.loadEventFired');
    await send('Runtime.evaluate', { expression: 'window.__inkReady', awaitPromise: true, returnByValue: true });

    // 先把每个用例的字体规格显式加载，否则 canvas 会静默用回退字形
    const loads = CASES.map((c) => `window.__load(${JSON.stringify(specOf(c))})`).join(',');
    await send('Runtime.evaluate', {
      expression: `(async()=>{ await Promise.all([${loads}]); await document.fonts.ready; return true; })()`,
      awaitPromise: true, returnByValue: true,
    });
    await sleep(400);

    const out = [];
    for (const c of CASES) {
      const { result } = await send('Runtime.evaluate', {
        expression: `JSON.stringify(window.__ink(${JSON.stringify(c.f)}, ${c.w}, ${JSON.stringify(c.t)}, ${JSON.stringify(c.style || '')}))`,
        returnByValue: true,
      });
      const r = JSON.parse(result.value);
      out.push({ family: c.f, weight: c.w, ratio: r.ratio, span: r.span, ctl: !!c.ctl, label: c.label });
    }
    return out;
  });

  const fails = [];
  const byKey = {};
  rows.forEach((r) => { byKey[r.family + '@' + r.weight] = r; });
  LADDERS.forEach(({ f, steps }) => {
    let prev = null;
    steps.forEach((w) => {
      const r = byKey[f + '@' + w];
      if (!r) { fails.push(`${f}：缺 ${w} 档测量`); return; }
      if (prev != null && r.ratio < prev - 0.05)
        fails.push(`${f}：${w} 的墨迹 ${r.ratio}% 低于前一档 ${prev}% —— 字重没有随权重变粗`);
      prev = r.ratio;
    });
    const a = byKey[f + '@400'], b = byKey[f + '@700'];
    if (a && b && (b.ratio - a.ratio) < DELTA_MIN)
      fails.push(`${f}：700 与 400 的墨迹只差 ${(b.ratio - a.ratio).toFixed(2)} 个百分点（要求 ≥ ${DELTA_MIN}）—— 这一族的粗体大概率没生效`);
  });

  if (AS_JSON) {
    console.log(JSON.stringify({ deltaMin: DELTA_MIN, rows, fails }, null, 1));
  } else {
    console.log('说明：同字号 100px 下，「非白像素占比」= 墨迹%。数值越大 = 笔画越粗。');
    console.log('');
    console.log('  墨迹%   字面宽  font-weight  用例');
    console.log('  ------  -------  -----------  ' + '-'.repeat(46));
    rows.forEach((r) => {
      console.log(`  ${String(r.ratio).padStart(5)}%  ${String(r.span).padStart(6)}   ${String(r.weight).padStart(7)}      ${r.label}`);
    });
    console.log('');
    const mags = rows.filter((r) => r.family.replace(/"/g, '').indexOf('Mag ') === 0);
    console.log(`  内嵌字体 ${mags.length} 档测完；阈值 DELTA_MIN=${DELTA_MIN}（400→700 的墨迹增量下限）`);
    if (fails.length) {
      console.log('');
      fails.forEach((f) => console.log('  FAIL ' + f));
      console.log(`FAIL 合计 ${fails.length} 项 —— 字重可能没生效，或字体档位缺失。`);
    } else {
      console.log('  OK  字重随权重单调变粗，且 400→700 增量达标。');
    }
  }
  process.exit(fails.length ? 1 : 0);
})().catch((e) => {
  console.error('FAIL ' + e.message);
  process.exit(2);
});
