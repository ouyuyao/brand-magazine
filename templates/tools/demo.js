#!/usr/bin/env node
/**
 * demo.js —— 出厂示例骨架的启用 / 关闭
 *
 * 为什么要有它：本引擎的页数由**参考图张数**决定。出厂时如果直接摆着
 * `layout/01.json` + `assets/ref/p01.jpg`，执行者一 `cp` 一 `build` 就得到
 * 「看起来像样」的两页图，于是**整段跳过「解析参考图」这一步**——这正是
 * brand-magazine 过去最大的毛病。所以示例被隔离进 `_demo/` 子目录
 * （`_` 开头 → build.js / copycheck.js / shoot.js / refcheck.py 一律不计入）。
 *
 * 于是全新副本直接 `node build.js` 会明确报错：
 *   ✗ layout/ 里没有版式 JSON（页数 = 参考图张数）
 * 想看示例必须显式跑本脚本 —— 不是默认行为。
 *
 * 用法：
 *   node tools/demo.js --enable     # 把 _demo/ 的示例复制回正式位（会警告）
 *   node tools/demo.js --disable    # 撤下示例（只删「与 _demo 逐字节相同」的文件）
 *   node tools/demo.js --status     # 只看当前状态
 * 退出码：0 正常 / 2 参数错或目录缺失
 */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const argv = process.argv.slice(2);
const ENABLE = argv.includes('--enable');
const DISABLE = argv.includes('--disable');
const STATUS = argv.includes('--status') || (!ENABLE && !DISABLE);

const LAY = path.join(ROOT, 'layout');
const REF = path.join(ROOT, 'assets', 'ref');
const LAY_D = path.join(LAY, '_demo');
const REF_D = path.join(REF, '_demo');

const fw = (p) => path.relative(ROOT, p).replace(/\\/g, '/');
const md5 = (p) => crypto.createHash('md5').update(fs.readFileSync(p)).digest('hex');

if (!fs.existsSync(LAY_D) || !fs.existsSync(REF_D)) {
  console.error('✗ 找不到 layout/_demo/ 或 assets/ref/_demo/ —— 这份副本没有出厂示例');
  process.exit(2);
}

/* 示例清单：{ 源, 正式位 } */
const ITEMS = [];
for (const d of [LAY_D, REF_D]) {
  const destDir = d === LAY_D ? LAY : REF;
  fs.readdirSync(d).filter((f) => !/^\./.test(f)).forEach((f) => {
    ITEMS.push({ src: path.join(d, f), dest: path.join(destDir, f), rel: fw(path.join(destDir, f)) });
  });
}

function state() {
  return ITEMS.map((it) => {
    if (!fs.existsSync(it.dest)) return { ...it, on: false, same: null };
    const same = md5(it.src) === md5(it.dest);
    return { ...it, on: true, same };
  });
}

if (STATUS) {
  const st = state();
  const on = st.filter((x) => x.on);
  console.log('示例状态：' + (on.length === 0 ? '未启用（正式位是空的）' : `已启用 ${on.length}/${st.length}`));
  st.forEach((x) => console.log(`  ${x.on ? (x.same ? '示例 ' : '★自有') : '未放 '} ${x.rel}` +
    (x.on && !x.same ? '   ← 这个文件与示例不同（像是你自己的参考图），--disable 不会删它' : '')));
  const own = fs.existsSync(LAY) ? fs.readdirSync(LAY).filter((f) => /\.json$/.test(f) && !/^_/.test(f)) : [];
  console.log('');
  console.log(own.length
    ? `layout/ 顶层有 ${own.length} 个版式 JSON：${own.sort().join(', ')} —— 可以 build`
    : 'layout/ 顶层没有版式 JSON —— 直接 node build.js 会报错（这是设计如此：先解析参考图）');
  process.exit(0);
}

if (ENABLE) {
  let n = 0;
  ITEMS.forEach((it) => {
    if (fs.existsSync(it.dest)) {
      console.log(`  keep  ${it.rel}（已存在，不覆盖）`);
      return;
    }
    fs.mkdirSync(path.dirname(it.dest), { recursive: true });
    fs.copyFileSync(it.src, it.dest);
    n++;
    console.log(`  copy  ${it.rel}`);
  });
  console.log('');
  console.log('⚠️  你正在看**出厂示例**（由良妙 2 页演示骨架），不是你的产出。');
  console.log('    真要出图请把自己的杂志/画册参考图放进 assets/ref/，');
  console.log('    然后按 references/01-skeleton-and-layout.md 用 refscan + refgrid 重新解析骨架，');
  console.log('    **不要照抄 _demo 里的 box**。');
  console.log('    已复制 ' + n + ' 个文件。');
  process.exit(0);
}

if (DISABLE) {
  let n = 0, kept = 0;
  ITEMS.forEach((it) => {
    if (!fs.existsSync(it.dest)) { console.log(`  -     ${it.rel}（本来就不在）`); return; }
    if (md5(it.src) !== md5(it.dest)) {
      kept++;
      console.log(`  keep  ${it.rel}   ← 与示例不同，判为你自己的文件，不删`);
      return;
    }
    fs.unlinkSync(it.dest);
    n++;
    console.log(`  rm    ${it.rel}`);
  });
  console.log('');
  console.log(`已撤下示例 ${n} 个文件${kept ? `，保留自有文件 ${kept} 个` : ''}。`);
  console.log('  现在 node build.js 会报「layout/ 里没有版式 JSON」—— 符合预期。');
  process.exit(0);
}
