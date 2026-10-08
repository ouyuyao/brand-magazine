#!/usr/bin/env node
/* =============================================================================
   freeze.js —— 冻结导出：把当前工作目录打包成一个「独立专用 skill」
   -----------------------------------------------------------------------------
   为什么要它：Stage A 把参考图解析成 layout/*.json、把品牌包与产品事实落定之后，
   如果只在母版目录里出图，母版一升级、或者换个产品，整套版式就可能被带跑。
   freeze 把「这一册」的全部输入 + 引擎 + 解析好的版式**冻成一份自包含的 skill**：
     · 之后出图（Stage B）在那个目录里跑，与母版彻底解耦；
     · SKILL.md 由本脚本按实际文件自动生成（不是手抄），保证描述与磁盘一致。

   用法：
     node tools/freeze.js --name <slug> --out <skillsDir>
                          [--title "…"] [--ref-mode copy|strip] [--dry] [--src <母版 skill 根>]

     --src     母版 brand-magazine 根目录。解析顺序：参数 → 环境变量 MAGAZINE_SRC
               → ~/.workbuddy/skills/brand-magazine → 报错要求显式给。
     --ref-mode copy（默认）  保留 assets/ref/ 参考图；Stage B 的 refcheck 与 O 三态叠图仍可用。
                strip        剔除参考图并写 assets/ref/_stripped 标记；refcheck 的 H2/H3 自动降级，
                              适合对外分享（参考图有版权，不随成品分发）。
     --dry     只打印计划与总体积，不写任何文件。

   剔除清单见 SKIP 正则。退出码：0 正常 / 2 参数或环境不满足。
   ============================================================================= */
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const vm = require('vm');

/* ---------------------------------------------------------------- 参数 */
const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const DRY = argv.includes('--dry');
const NAME = (argOf('--name', '') || '').trim();
const OUT = (argOf('--out', '') || '').trim();
const TITLE = argOf('--title', null);
const REF_MODE = (argOf('--ref-mode', 'copy') || 'copy').trim();
const SRC_ARG = argOf('--src', null);

const die = (m) => { console.error('✗ ' + m); process.exit(2); };
if (!NAME) die('缺 --name <slug>（导出的 skill 目录名，建议小写连字符，如 ooo-lingerie-01）');
if (!/^[a-z0-9][a-z0-9._-]*$/.test(NAME)) die(`--name「${NAME}」不合法：只允许小写字母/数字/.-_，且不以符号开头`);
if (!OUT) die('缺 --out <skillsDir>（导出到哪个目录，会在其下建 <name>/）');
if (!['copy', 'strip'].includes(REF_MODE)) die(`--ref-mode 只能是 copy 或 strip（收到「${REF_MODE}」）`);

/* 母版 skill 根：参数 → 环境变量 → 用户级默认位置 → 报错 */
const SRC = (() => {
  const cands = [SRC_ARG, process.env.MAGAZINE_SRC,
    path.join(os.homedir(), '.workbuddy', 'skills', 'brand-magazine')].filter(Boolean);
  for (const c of cands) if (fs.existsSync(path.join(c, 'SKILL.md'))) return path.resolve(c);
  die('找不到母版 brand-magazine —— 用 --src 指定，或设环境变量 MAGAZINE_SRC');
  return null;
})();

const ROOT = path.resolve(__dirname, '..');           /* 当前工作目录（= templates 的副本） */
const DEST = path.join(path.resolve(OUT), NAME);
const fw = (p) => String(p).replace(/\\/g, '/');

/* ---------------------------------------------------------------- 健康检查 */
const warn = [];
if (!fs.existsSync(path.join(ROOT, 'build.js'))) die(`当前目录不像模板：缺 ${fw(path.join(ROOT, 'build.js'))}（请在 templates 副本里跑本脚本）`);
if (!fs.existsSync(path.join(ROOT, 'brand', 'brand-pack.json'))) die('缺 brand/brand-pack.json');
if (!fs.existsSync(path.join(ROOT, 'layout'))) die('缺 layout/');

/* 一期一目录：旧的多期残留会污染冻结出的 skill */
const ISSUES = path.join(ROOT, 'copy', 'issues');
if (fs.existsSync(ISSUES) && fs.readdirSync(ISSUES).filter((f) => !/^_/.test(f)).length)
  warn.push('copy/issues/ 里还有旧期文案 —— 冻结前请确认真的是「一期一目录」（本冻结只会带上当前 copy/issue.js）');
const layFiles = fs.readdirSync(path.join(ROOT, 'layout')).filter((f) => /\.json$/.test(f) && !/^_/.test(f)).sort();

/* ★ Stage A 守卫：_demo/ 是出厂示例，冻结时会被剔除；若顶层也没有真东西，
   冻出来的 skill 就是空壳（layout 空 → build 报错；assets/ref 空 → refcheck 拦）。
   这是「还没做 Stage A 就冻结」的典型误用，直接拦掉，别产出废品。 */
const topRefs = fs.existsSync(path.join(ROOT, 'assets', 'ref'))
  ? fs.readdirSync(path.join(ROOT, 'assets', 'ref')).filter((f) => /\.(png|jpe?g|webp|gif)$/i.test(f))
  : [];
if (!layFiles.length) {
  const onlyDemo = fs.existsSync(path.join(ROOT, 'layout', '_demo'));
  die('layout/ 顶层没有版式 JSON —— 还没做 Stage A 的 A3（解析参考图）。\n' +
    (onlyDemo ? '  （layout/_demo/ 里的是出厂示例，冻结时会被剔除，不能当产出）\n' : '') +
    '  先跑：python tools/refscan.py → refgrid.py → 写 layout/NN.json → python tools/refcheck.py');
}
if (!topRefs.length) {
  const onlyDemo = fs.existsSync(path.join(ROOT, 'assets', 'ref', '_demo'));
  die('assets/ref/ 顶层没有参考图 —— 还没做 Stage A 的 A3。\n' +
    (onlyDemo ? '  （assets/ref/_demo/ 里的是出厂示例，冻结时会被剔除）\n' : '') +
    '  把你的杂志/画册参考图放进 assets/ref/（原始分辨率），再跑 refscan.py');
}

const nums = layFiles.map((f) => {
  const m = f.match(/(\d+)/); return m ? +m[1] : NaN;
}).filter((n) => !isNaN(n)).sort((a, b) => a - b);
nums.forEach((n, i) => { if (i && n !== nums[i - 1] + 1) warn.push(`layout/ 页码不连续：…${nums[i - 1]} → ${n}（一期一目录通常应连续）`); });

/* ---------------------------------------------------------------- 剔除清单 */
const SKIP = [
  { re: /^_shots\//, why: '出图产物（Stage B 现场生成）' },
  { re: /^assets\/ref\/_grid\//, why: '叠图/差异图产物' },
  { re: /^assets\/ref\/_scan\//, why: '投影分析产物' },
  { re: /^assets\/ref\/_stripped$/, why: '旧标记，重新按模式决定' },
  { re: /^images\/_before_unwatermark\//, why: '原素材备份' },
  { re: /^images\/_flat\//, why: '中间产物' },
  { re: /^images\/_alphabox\.json$/, why: '标定产物（Stage B 重跑 alphabox.py 生成）' },
  { re: /^preview-pages.*\.jpe?g$/i, why: '总览图产物' },
  { re: /^copy\/slots\.json$/, why: 'build 生成的快照' },
  { re: /^copy\/_data\.js$/, why: 'build 生成的数据' },
  { re: /^copy\/_brief\.md$/, why: 'build 生成的骨架' },
  { re: /^copy\/_skeleton\.js$/, why: 'build 生成的骨架' },
  { re: /^layout\/_demo\//, why: '出厂示例骨架' },
  { re: /^assets\/ref\/_demo\//, why: '出厂示例参考图' },
  { re: /(^|\/)\.git(\/|$)/, why: '版本库' },
  { re: /(^|\/)node_modules(\/|$)/, why: '依赖目录' },
  { re: /(^|\/)desktop\.ini$/i, why: '系统文件' },
  { re: /(^|\/)thumbs\.db$/i, why: '系统文件' },
  { re: /\.(tmp|bak|log|swp)$/i, why: '临时文件' },
  { re: /(^|\/)\.DS_Store$/, why: '系统文件' },
  { re: /(^|\/)__pycache__(\/|$)/, why: 'Python 缓存' },
];
function skipWhy(rel) {
  for (const s of SKIP) if (s.re.test(rel)) return s.why;
  return null;
}

/* ---------------------------------------------------------------- 变量采集 */
const readJSON = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
function loadSandbox(file, g) {
  if (!fs.existsSync(file)) return null;
  const sb = { window: {}, console }; sb.globalThis = sb; vm.createContext(sb);
  try { vm.runInContext(fs.readFileSync(file, 'utf8'), sb, { filename: file }); } catch (e) { return null; }
  return sb.window[g] || null;
}
const BP = readJSON(path.join(ROOT, 'brand', 'brand-pack.json'));
const PROD = loadSandbox(path.join(ROOT, 'copy', 'products', 'product.js'), '__PRODUCT') || {};

const PAGES = layFiles.map((f) => {
  const L = readJSON(path.join(ROOT, 'layout', f));
  const m = (String(L.id || f).match(/(\d+)/) || [, ''])[1];
  return { file: f, L, pid: m ? 'page' + (m.length < 2 ? '0' + m : m) : f };
});
const REF_DIR = path.join(ROOT, 'assets', 'ref');
const REFS = fs.existsSync(REF_DIR) ? fs.readdirSync(REF_DIR).filter((f) => /\.(png|jpe?g|webp|gif)$/i.test(f)).sort() : [];

const nm = BP.name || {};
const sig = BP.signature || {};
const price = (BP.price && BP.price.defaultPrice) || (PROD.price && PROD.price.default) || '—';
const tone = BP.tone || {};
const comp = BP.compliance || {};
const fb = BP.forbidden || {};
const fbCount = Object.keys(fb).reduce((n, k) => n + (fb[k] || []).length, 0);
const prodTitle = (PROD.title && (PROD.title.jp || PROD.title.zh)) || '（未填写 copy/products/product.js）';

const createdAt = (() => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
})();

/* ---------------------------------------------------------------- SKILL.md 模板 */
function skillMd() {
  const title = TITLE || `${nm.native || BP.brandId}｜${prodTitle}`;
  const fontRows = (BP.fontMap || []).map((r) =>
    `| \`${r.role}\` | ${r.from || '—'} | ${r.to || '—'} | ${r.why || '—'} |`).join('\n') ||
    '| — | — | — | fontMap 为空 —— Stage A 的 A4 还没做 |';
  const refRows = PAGES.map((p, i) =>
    `| ${p.pid} | \`layout/${p.file}\` | \`assets/ref/${p.L.ref || '（未写 ref）'}\` | ` +
    `${(p.L.canvas && p.L.canvas.w) || '?'}×${(p.L.canvas && p.L.canvas.h) || '?'} | ${(p.L.zones || []).length} |`).join('\n');
  const ruleRows = (comp.rules || []).map((r, i) => `${i + 1}. ${r}`).join('\n');
  const toneRows = (tone.rules || []).map((r) => `- ${r}`).join('\n');

  return `---
name: ${NAME}
description: 「${nm.native || BP.brandId}」品牌的定制化杂志套图引擎（由 brand-magazine 在 ${createdAt} 冻结）。
  已经按用户提供的 ${PAGES.length} 张参考图解析好版式骨架，产品为「${prodTitle}」。
  输入成品素材 → 产出与参考图同骨架的杂志套图。触发词：${NAME}、${nm.native || BP.brandId} 杂志图、出套图。
agent_created: true
---

# ${title}

> **本 skill 是冻结产物，不是手写文档。** 由 \`node tools/freeze.js\` 于 ${createdAt} 从母版
> \`brand-magazine\` 生成；SKILL.md 里的一切数值都读自磁盘上的 \`brand/brand-pack.json\`、
> \`copy/products/product.js\`、\`layout/*.json\`、\`assets/ref/\`。改这几个文件后重新跑一遍会更新本文。

## 一、来历（为什么直接出图就行）

母版 \`brand-magazine\` 是「参考图 → 版式」的**解析器**；本 skill 是那次解析的**结果**。
Stage A 已经做完的事，在这里不需要重做：

- ${PAGES.length} 张参考图已逐页解析成 \`layout/*.json\`（页数 = 参考图张数，一对一）；
- 每页 \`canvas\` 已对齐该页参考图的**真实像素尺寸**（\`refcheck.py\` 会硬拦不一致）；
- 品牌包（配色 / 字体 / 禁用词 / 合规规则）已落定在 \`brand/brand-pack.json\`；
- 45 个文案槽位已由 \`build.js --brief\` 列全，成稿在 \`copy/issue.js\`。

**换产品不碰 HTML；换品牌只换一个 JSON。** 所有工具都从 \`layout/\` 动态读页列表。

## 二、输入 / 输出

| | 内容 |
|---|---|
| 输入 | \`images/\` 成品图（白底图 / 场景图 / 细节图）；\`copy/issue.js\` 文案（jp + zh 成对）；\`copy/products/product.js\` 产品事实 |
| 输出 | \`pageNN.html\`（每页一个静态文件，几何与字号全 inline）＋ \`_shots/pageNN.png\`（${PAGES.length} 页，尺寸见下表）＋ 总览 \`index.html\` |

## 三、目录结构

\`\`\`
${NAME}/
  SKILL.md                  ← 本文件（自动生成）
  references/               ← 00–05（工作流 / 版式 / 文案 / 工具链 / 台账 / 字体识别）+ 00-project.md（本项目事实）
  contracts/brand-pack.md   ← 品牌包字段契约
  templates/                ← 引擎本体（build.js · css/ · js/ · fonts/ · tools/ · layout/ · brand/ · copy/ · images/ · assets/）
\`\`\`

## 四、Stage B 出图流程（照顺序跑，门禁不过不要往下走）

\`\`\`bash
node build.js                     # ① 编译。默认保真；要「一物一版」用 --seed <SKU名>
python tools/refcheck.py          # ② 【硬门禁】页数 = 参考图张数；canvas = 参考图真实尺寸
node tools/copycheck.js           # ③ 【硬门禁】文案 jp/zh 成对齐全、无溢出、无禁用词
node tools/shoot.js               # ④ 出图（CDP 精确截图，只能用这个，别用 chrome --screenshot）
node tools/labelrects.js          # ⑤ 位置标定
python tools/check_faces.py       # ⑥ 人脸遮挡（FAIL 必须为 0）
python tools/blockcheck.py        # ⑦ 照片互压（FAIL 必须为 0）
node tools/fontcheck.js           # ⑧ 字体命中
node tools/inkprobe.js            # ⑨ 字重墨迹探针（证明 font-weight 真的生效）
python tools/preview.py           # ⑩ 总览；中文稿加 --tag zh
python tools/reffit.py            # ⑪ 骨架吻合分（≥0.85 为佳；告警级，不阻断）
\`\`\`

**三条硬门禁**：② ③ 必须退出码 0；⑥ ⑦ 的 FAIL 必须为 0。任一条不过，**不要出图**。

## 五、版式台账（页数 = 参考图张数）

| 页 | 版式 | 参考图 | 画布 | 分区数 |
|---|---|---|---|---|
${refRows}

> 参考图仅作内部叠图比对（预览页按 \`O\` 键：关 → 参考图 → 差异图），**不随成品分发**。

## 六、硬规则（从品牌包注入，逐条不可违）

### 6.1 合规（${(comp.regimes || []).join(' · ') || '—'}）

${ruleRows || '（品牌包 compliance.rules 为空 —— Stage A 需补）'}

${comp.escalate ? `> ⚠️ ${comp.escalate}` : ''}

### 6.2 禁用词（共 ${fbCount} 条，\`copycheck.js\` 会扫渲染后的正文）

${Object.keys(fb).map((k) => `- **${k}**：${(fb[k] || []).join('・')}`).join('\n') || '（无）'}

### 6.3 语气

> ${tone.summary || '（品牌包 tone.summary 为空）'}

${toneRows}

### 6.4 价格

**${price}**（品牌包 \`price.defaultPrice\`）。用户在产品信息里给实际价时改
\`copy/products/product.js\` 的 \`vars.price\` 与品牌包 \`price.defaultPrice\`，两处同步。

### 6.5 视觉

- 字重上限 **${(BP.visual && BP.visual.maxWeight) || '—'}**；最小留白 ${(BP.visual && BP.visual.minWhitespace) || '—'}
- 禁用：${((BP.visual && BP.visual.banned) || []).join(' / ') || '—'}
- 署名：\`${sig.primary || '—'}\`${sig.noPlaceName ? '（不附地名）' : ''}
- 摄影：${(BP.visual && BP.visual.photoRule) || '—'}
- ${(BP.visual && BP.visual.badgesIconOnly) ? '促销 / 属性信息**一律图标化**，不写成长句。' : ''}

## 七、字体替代台账（每条都写明相似点与差异）

| 角色 | 原刊字体 | 替代字体 | 为什么可以替代 |
|---|---|---|---|
${fontRows}

识别流程见 \`references/05-font-identification.md\`；验证用 \`node tools/fontcheck.js\` + \`node tools/inkprobe.js\`。

## 八、参考图版权

${REF_MODE === 'copy'
      ? '本 skill **保留了参考图**（`--ref-mode copy`），供出图前的叠图比对使用 —— 仅限内部，**不要随成品分发**。要对外分享本 skill，请用 `--ref-mode strip` 重新冻结。'
      : '本 skill **已剔除参考图**（`--ref-mode strip`），`assets/ref/_stripped` 标记存在，`refcheck.py` 的尺寸断言自动降级。版式骨架已固化在 `layout/*.json` 里，出图不需要参考图。'}

---

## 附：本 skill 不做的事

- 不重新解析参考图（那是母版 Stage A 的活；换参考图请回母版重做 A3）。
- 不调用任何联网 / 扣积分的生图通道。
- 不自动判断「该不该加折扣 badge」—— 产品信息里没有的一律不加。
`;
}

/* ---------------------------------------------------------------- 项目事实（references/00-project.md） */
function projectMd() {
  const refRows = PAGES.map((p) => `| ${p.pid} | \`${p.L.ref || '—'}\` | ${(p.L.canvas && p.L.canvas.w) || '?'}×${(p.L.canvas && p.L.canvas.h) || '?'} | ${(p.L.zones || []).length} |`)
    .join('\n');
  return `# 本项目事实（自动生成，请勿手改 —— 由 freeze.js 于 ${createdAt} 从磁盘读出）

## 品牌

| 项 | 值 |
|---|---|
| brandId | \`${BP.brandId || '—'}\` |
| 名称 | ${nm.native || '—'}${nm.kana ? ' / ' + nm.kana : ''}${nm.romaji ? ' / ' + nm.romaji : ''} |
| 品牌 skill | \`${BP.brandSkill || '—'}\` |
| 默认语言 | \`${BP.defaultLang || '—'}\`（支持 ${(BP.langs || []).join(' / ')}） |
| 署名 | ${sig.primary || '—'}${sig.zh ? '（' + sig.zh + '）' : ''} |
| Slogan | ${(BP.slogan && BP.slogan.native) || '—'}${(BP.slogan && BP.slogan.zh) ? '（' + BP.slogan.zh + '）' : ''} |
| 字重上限 | ${(BP.visual && BP.visual.maxWeight) || '—'} |

## 产品

| 项 | 值 |
|---|---|
| slug | \`${PROD.slug || '—'}\` |
| 标题（jp） | ${(PROD.title && PROD.title.jp) || '—'} |
| 标题（zh） | ${(PROD.title && PROD.title.zh) || '—'} |
| 价格 | ${price} |
| 可见事实条数 | facts ${(PROD.facts || []).length} · visible ${(PROD.visible || []).length} |
| 尺码 | ${(PROD.sizes || []).map((s) => s.size).join(' / ') || '—'} |

## 版式（页数 = 参考图张数 = ${PAGES.length}）

| 页 | 参考图 | 画布 | 分区数 |
|---|---|---|---|
${refRows}

## 素材台账

成品素材逐项登记在 \`ASSETS.md\`（在 skill 根目录）；每新增 / 替换素材必须登记一行。
`;
}

/* ---------------------------------------------------------------- 递归复制 */
const plan = [];      /* { src, rel, size } */
const skipped = [];   /* { rel, why } */
let nSymlink = 0;

function walk(dir, rel) {
  let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return; }
  for (const e of ents) {
    const abs = path.join(dir, e.name);
    const r = rel ? rel + '/' + e.name : e.name;
    if (e.isSymbolicLink()) { nSymlink++; skipped.push({ rel: r, why: '符号链接（不跟随，避免把外部内容带进 skill）' }); continue; }
    if (e.isDirectory()) {
      const why = skipWhy(r + '/');
      if (why) { skipped.push({ rel: r + '/', why }); continue; }
      walk(abs, r);
    } else if (e.isFile()) {
      const why = skipWhy(r);
      if (why) { skipped.push({ rel: r, why }); continue; }
      /* --ref-mode strip：剔除参考图本体（标记由主流程写） */
      if (REF_MODE === 'strip' && /^assets\/ref\/[^/]+\.(png|jpe?g|webp|gif)$/i.test(r)) {
        skipped.push({ rel: r, why: '--ref-mode strip：参考图不随 skill 分发' }); continue;
      }
      let size = 0; try { size = fs.statSync(abs).size; } catch (e) { }
      plan.push({ src: abs, rel: r, size });
    }
  }
}
walk(ROOT, '');

const human = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : (b > 1024 ? (b / 1024).toFixed(0) + ' KB' : b + ' B');
const totalBytes = plan.reduce((n, p) => n + p.size, 0);

/* 母版要一起带上的文档 */
const SRC_REF_DIR = path.join(SRC, 'references');
const REF_DOCS = fs.existsSync(SRC_REF_DIR)
  ? fs.readdirSync(SRC_REF_DIR).filter((f) => /^\d\d-.*\.md$/.test(f)).sort()
  : [];
const HAS_CONTRACT = fs.existsSync(path.join(SRC, 'contracts', 'brand-pack.md'));
for (const f of REF_DOCS) plan.push({ src: path.join(SRC_REF_DIR, f), rel: '../references/' + f, size: 0 });
if (HAS_CONTRACT) {
  const p = path.join(SRC, 'contracts', 'brand-pack.md');
  plan.push({ src: p, rel: '../contracts/brand-pack.md', size: fs.statSync(p).size });
}

/* ---------------------------------------------------------------- 输出 */
console.log(`母版：${fw(SRC)}`);
console.log(`工作目录：${fw(ROOT)}`);
console.log(`导出到：${fw(DEST)}${DRY ? '   （--dry：只打印，不写文件）' : ''}`);
console.log(`参考图模式：${REF_MODE}　页数：${PAGES.length}　产品：${prodTitle}`);
console.log('');

if (DRY) {
  plan.forEach((p) => console.log(`  copy  ${p.rel.replace(/^\.\.\//, '(母版) ')}`));
  skipped.forEach((s) => console.log(`  skip  ${s.rel}   ← ${s.why}`));
  console.log('');
  console.log(`计划：copy ${plan.length} 个文件（${human(totalBytes)}）· skip ${skipped.length} 项 · 符号链接 ${nSymlink}`);
  console.log('SKILL.md / references/00-project.md 将自动生成（内容见模板）。');
  warn.forEach((w) => console.log('WARN  ' + w));
  process.exit(0);
}

/* 真写：先建目录，再逐文件复制 */
fs.mkdirSync(DEST, { recursive: true });
let nCopy = 0;
for (const p of plan) {
  const dest = path.join(DEST, p.rel.startsWith('../') ? p.rel.slice(3) : path.join('templates', p.rel));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(p.src, dest);
  nCopy++;
  console.log(`  copy  ${p.rel.replace(/^\.\.\//, '(母版) ')}`);
}
skipped.forEach((s) => console.log(`  skip  ${s.rel}   ← ${s.why}`));

/* strip 模式写标记（refcheck.py 见到它就把 H2/H3 降级为 WARN） */
if (REF_MODE === 'strip') {
  fs.mkdirSync(path.join(DEST, 'templates', 'assets', 'ref'), { recursive: true });
  fs.writeFileSync(path.join(DEST, 'templates', 'assets', 'ref', '_stripped'),
    `由 tools/freeze.js --ref-mode strip 于 ${createdAt} 生成。\n` +
    `参考图未随本 skill 分发；refcheck.py 的页数/尺寸硬断言据此降级为 WARN。\n`, 'utf8');
}

/* 自动生成的两份文档 */
fs.mkdirSync(path.join(DEST, 'references'), { recursive: true });
fs.writeFileSync(path.join(DEST, 'references', '00-project.md'), projectMd(), 'utf8');
fs.writeFileSync(path.join(DEST, 'SKILL.md'), skillMd(), 'utf8');

/* 素材台账骨架 —— 已存在则不覆盖 */
const ledger = path.join(DEST, 'ASSETS.md');
if (!fs.existsSync(ledger)) {
  fs.writeFileSync(ledger, `# 素材台账 —— ${nm.native || BP.brandId}｜${prodTitle}

> 每新增 / 替换一个素材必须在下面登记一行。来源列写清「自摄 / 供货方 / 生成」。
> 参考图（\`assets/ref/\`）仅内部叠图用，**不随成品分发**。

| 文件 | 用途 | 来源 | 尺寸 | 备注 |
|---|---|---|---|---|
| images/… | | | | |

## 生成图说明

（若有 AI 生成素材，在此据实记录：工具 / 日期 / 用途。事实记录 ≠ 对外标识。）
`, 'utf8');
  console.log('  new   ASSETS.md（台账骨架）');
}

console.log('');
console.log(`✓ 冻结完成：${fw(DEST)}`);
console.log(`  · 文件 ${nCopy} 个 · 参考图模式 ${REF_MODE}`);
console.log(`  · SKILL.md（自动生成）· references/${REF_DOCS.length + 1} 份 · contracts/`);
console.log(`  · 下一步（Stage A8 门禁③）：在新目录里跑`);
console.log(`      cd "${fw(DEST)}/templates" && python tools/refcheck.py && node build.js && node tools/copycheck.js`);
console.log(`    三条都要退出码 0，才说明这份 skill 自包含。`);
warn.forEach((w) => console.log('WARN  ' + w));
process.exit(0);
