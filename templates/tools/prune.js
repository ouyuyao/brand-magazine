#!/usr/bin/env node
/**
 * prune.js —— 产物清理：删掉 layout/ 里已经不存在的页所留下的陈旧产物
 *
 * 为什么需要它：
 *   build.js 只会为「当前 layout/ 里存在的页」写 pageNN.html，**从不删除**已不存在的页。
 *   于是你把 9 页改成 3 页之后，旧的 page05.html / _shots/page05.png 会残留下来，
 *   而 tools/preview.py 是按 _shots/ 里的文件汇总的 —— 幽灵页会混进总览图，
 *   让人以为「还有第 5 页」。
 *
 * 安全设计（这条最重要）：
 *   · 只删**严格匹配** `^page\d+\.html$` 与 `^page\d+(_\w+)?\.png$` 的文件；
 *   · 只扫项目根、_shots/、_shots/guard/ 三个目录，**不递归进 images/ assets/ fonts/**；
 *   · 默认是 `--dry`（只列不删），要真删必须显式 `--yes`；
 *   · 任何不匹配该正则的文件一律不碰（素材、参考图、字体都安全）。
 *
 * 用法：
 *   node tools/prune.js            # 只列出将删什么（默认 dry-run）
 *   node tools/prune.js --yes      # 真删
 * 退出码：0 正常   2 缺 layout/
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const argv = process.argv.slice(2);
const YES = argv.includes('--yes');
const LAY = path.join(ROOT, 'layout');

if (!fs.existsSync(LAY)) {
  console.error('FAIL 缺 layout/ 目录 —— 无法判断哪些页还有效');
  process.exit(2);
}

/* 期望保留的页 id */
const pids = fs.readdirSync(LAY)
  .filter((f) => /\.json$/.test(f) && !/^_/.test(f))
  .map((f) => {
    let id = f;
    try { id = JSON.parse(fs.readFileSync(path.join(LAY, f), 'utf8')).id || f; } catch (e) { }
    const n = (String(id).match(/(\d+)/) || [, ''])[1];
    return n ? 'page' + (n.length < 2 ? '0' + n : n) : null;
  })
  .filter(Boolean)
  .sort();

const keep = new Set(pids);

const PAGE_HTML = /^page\d+\.html$/;
const PAGE_PNG = /^(page\d+)(_[A-Za-z0-9]+)?\.png$/;
const GUARD_PAGE = /(^|_)page(\d+)/;

const plan = [];

function scan(dir, test, apply) {
  if (!fs.existsSync(dir)) return;
  for (const f of fs.readdirSync(dir)) {
    const p = path.join(dir, f);
    let st;
    try { st = fs.statSync(p); } catch (e) { continue; }
    if (!st.isFile()) continue;
    if (!test(f)) continue;
    if (apply(f)) plan.push(p);
  }
}

/* ① 项目根：陈旧的 pageNN.html */
scan(ROOT, (f) => PAGE_HTML.test(f), (f) => !keep.has(f.replace(/\.html$/, '')));

/* ② _shots/：陈旧的 pageNN*.png（整页稿、中文稿都在内）。idx*.png 由 index.html 派生，不删。 */
scan(path.join(ROOT, '_shots'), (f) => PAGE_PNG.test(f), (f) => {
  const m = PAGE_PNG.exec(f);
  return m && !keep.has(m[1]);
});

/* ③ _shots/guard/：与已删页相关的标定 / 复核图 */
scan(path.join(ROOT, '_shots', 'guard'), () => true, (f) => {
  const m = GUARD_PAGE.exec(f);
  if (!m) return false;
  const n = m[2];
  const pid = 'page' + (n.length < 2 ? '0' + n : n);
  return !keep.has(pid);
});

const rm = (p) => { try { fs.unlinkSync(p); return true; } catch (e) { console.error('  ! 删除失败 ' + p + '：' + e.message); return false; } };

console.log(`保留页：${pids.join(', ') || '（无）'}`);
if (!plan.length) {
  console.log('OK  没有陈旧产物（layout/ 与磁盘上的 pageNN 一致）');
  process.exit(0);
}
let n = 0;
plan.forEach((p) => {
  const rel = path.relative(ROOT, p).replace(/\\/g, '/');
  if (YES) { if (rm(p)) { n++; console.log('rm   ' + rel); } }
  else console.log('would rm  ' + rel);
});
console.log(YES ? `已删除 ${n} 个文件。` : `将删除 ${plan.length} 个文件（这是 dry-run，加 --yes 才真删）。`);
process.exit(0);
