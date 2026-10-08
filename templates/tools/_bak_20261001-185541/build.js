#!/usr/bin/env node
/* =============================================================================
   build.js —— 引擎入口：把「版式 JSON ＋ 品牌包 ＋ 文案」编译成整页 HTML
   -----------------------------------------------------------------------------
   这是本 skill 的心脏。一次运行做九件事：

     ① 读 brand/brand-pack.json        → 生成 brand/_skin.css（配色 + 字体覆写）
     ② 读 layout/*.json（N 个）        → 决定页数（页数 = 参考图张数）
     ③ 读 copy/issue.js（成稿文案）    → 烘进 HTML（正表记稿）供 ?copy=0 查看
     ④ 逐个 zone 渲染成绝对定位 DOM（**先过 kind / font 白名单校验**）
     ⑤ 生成 pageNN.html（每页一个静态文件，含叠图三态层）
     ⑥ 生成 copy/_data.js（window.MAGAZINE：copy / brandData / productData / total）
     ⑦ 生成 copy/slots.json（槽位清单：id 选择器 / 部件数 / 字数预算）
     ⑧ 硬断言 H1/H2：页数 = 参考图张数；每页 canvas = 该页参考图真实尺寸
     ⑨ 可选：--brief 出写作骨架 / --prune 清残留 / --seed 挂变体

   用法：
     node build.js                 # 全量编译
     node build.js --brief         # 额外输出 copy/_brief.md（字数预算）与 copy/_skeleton.js（可粘贴的文案骨架）
     node build.js --check         # 只体检不写文件（版式/品牌包/文案的接口一致性）
     node build.js --page 03       # 只编译某一页
     node build.js --prune         # 编译后顺带清理「删页后残留」的 pageNN.html / _shots/pageNN*.png
                                   #   （默认只列不删；加 --yes 才真删。只认「编号不在 layout/ 里的幽灵页」）
     node build.js --seed <slug>   # 启用版式变体（**默认关闭 = 严格保真**；一物一版才开）

   红线（违反即退出码非 0）：
     · 品牌包缺必填字段           · layout JSON 结构非法
     · 未知 kind / 未知字体角色    · 文案值个数 ≠ 占位符个数
     · 出现品牌包禁用清单里的词    · 页数 ≠ 参考图张数 / canvas ≠ 参考图真实尺寸
   ============================================================================= */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname);
const argv = process.argv.slice(2);
const BRIEF = argv.includes('--brief');
const CHECKONLY = argv.includes('--check');
const PRUNE = argv.includes('--prune');
const YES = argv.includes('--yes');          /* 与 --prune 搭配：不加则只列不删（dry-run） */
const onlyIdx = argv.indexOf('--page');
const ONLY = onlyIdx >= 0 ? argv[onlyIdx + 1] : null;
const seedIdx = argv.indexOf('--seed');
const SEED = seedIdx >= 0 ? (argv[seedIdx + 1] || null) : null;

const fail = [];
const warn = [];
const log = (...a) => console.log(...a);

/* ---------------------------------------------------------------- 工具 */
const readJSON = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const exists = (p) => { try { fs.accessSync(p); return true; } catch { return false; } };

/* 在沙箱里求值「window.__XXX = ...」型源文件（允许写注释，比 JSON 好维护） */
function loadSandbox(file, globalName) {
  if (!exists(file)) return null;
  const src = fs.readFileSync(file, 'utf8');
  const sandbox = { window: {}, console };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  try { vm.runInContext(src, sandbox, { filename: file }); }
  catch (e) { fail.push(`${path.basename(file)} 求值失败：${e.message}`); return null; }
  return sandbox.window[globalName] || null;
}

/* 颜色：令牌名 → var(--x)；字面色值原样 */
const TOKENS = new Set(['paper', 'paper-warm', 'paper-cream', 'paper-grey', 'ink', 'ink-2', 'ink-3',
  'ink-4', 'rule', 'rule-soft', 'accent', 'accent-soft', 'accent-deep', 'accent-wash',
  'sky', 'pink', 'pink-deep', 'ink-cool', 'warm-deep']);
const LITERALS = new Set(['none', 'transparent', 'currentColor', 'inherit']);
const col = (v) => {
  if (!v) return null;
  const s = String(v);
  if (LITERALS.has(s)) return s === 'none' ? 'transparent' : s;
  return TOKENS.has(s) ? `var(--${s})` : s;
};

/* 数值：允许数字（px）或带单位字符串 */
const px = (v) => (v == null ? null : (typeof v === 'number' ? v + 'px' : String(v)));

/* ================================================================ 白名单校验
   为什么要有：没有它的时候，`"kind":"textt"` 会静默掉进兜底分支画一个空 div，
   `"font":"song"` 会静默回退成继承字体 —— 都不报错，只有出图后肉眼看才发现。
   新增页 / 解析参考图时最容易踩这两个坑，所以升格成 fail。 */
const KINDS = new Set(['text', 'image', 'cutout', 'mask', 'rule', 'band', 'panel',
  'badge', 'torn', 'bubble', 'logo', 'label']);
/* 注意：layout 里写的是**连字符**版（script-fat / latin-ital）；
   brand-pack.json 的 fonts 段用的是驼峰版（scriptFat / latinItal），两者由 FMAP 映射。 */
const FONT_ROLES = new Set(['serif', 'sans', 'script', 'script-fat', 'latin', 'latin-ital']);
const PAPER_TONES = new Set(['warm', 'cream', 'grey', 'sky', 'pink']);
const isColorish = (v) => /^#|^rgb|^hsl/i.test(String(v));

function validateZone(z, pid, file, i) {
  const tag = (z && z.id) || ('zones[' + i + ']');
  const where = file.replace(/\.json$/, '') + ' ' + tag;
  if (!z || typeof z !== 'object') { fail.push(`${file} zones[${i}]：不是对象`); return; }
  const kind = z.kind || 'text';
  if (!KINDS.has(kind))
    fail.push(`${where}：未知 kind「${kind}」—— 白名单：${[...KINDS].join(' / ')}`);
  if (!z.box) fail.push(`${where}：缺 box`);
  else if (Array.isArray(z.box)) {
    if (z.box.length !== 4) fail.push(`${where}：box 必须是 [x,y,w,h] 四个数`);
    else if (z.box.some((n) => typeof n !== 'number')) fail.push(`${where}：box 必须全为数字`);
  }
  const s = z.style || {};
  if (s.font && !FONT_ROLES.has(s.font))
    fail.push(`${where}：未知字体角色「${s.font}」—— 白名单：${[...FONT_ROLES].join(' / ')}`);
  ['color', 'bg'].forEach((k) => {
    const v = s[k];
    if (v && !TOKENS.has(String(v)) && !LITERALS.has(String(v)) && !isColorish(v))
      warn.push(`${pid} ${tag}：style.${k}「${v}」既不是令牌也不是色值 —— 会被原样输出（很可能静默无效）`);
  });
  if (z.src && !/^https?:/.test(z.src) && !exists(path.join(ROOT, z.src)))
    warn.push(`${pid} ${tag}：图片不存在 → ${z.src}`);
  /* occlude：主体遮挡掩膜。不存在就不是「可选项缺失」，是「层叠关系做不出来」→ fail */
  if (z.occlude && !exists(path.join(ROOT, String(z.occlude))))
    fail.push(`${where}：occlude 掩膜不存在 → ${z.occlude}（先跑 tools/submask.py 生成）`);
  /* arc：只有文字类能用；几何参数必须是数 */
  if (z.arc) {
    if (!['text', 'badge', 'torn', 'bubble', 'label'].includes(kind))
      fail.push(`${where}：arc 只能用在文字类 zone 上（当前 kind=${kind}）`);
    ['cx', 'cy', 'r', 'mid', 'span', 'pad'].forEach((k) => {
      const v = z.arc[k];
      if (v != null && typeof v !== 'number')
        fail.push(`${where}：arc.${k} 必须是数（收到「${v}」）`);
    });
    if (z.arc.span != null && Math.abs(z.arc.span) > 350)
      warn.push(`${pid} ${tag}：arc.span=${z.arc.span}° 接近整圈，文字会自我重叠`);
  }
  /* occlude 与 arc 都只接受显式声明，不做默认值 —— 猜出来的层叠关系与弧线都是假的 */
}

/* 图像头解析（无依赖，不引第三方）：PNG 读 IHDR，JPEG 扫 SOF0/1/2/… 段。
   用来在编译期就把「canvas ≠ 参考图真实尺寸」拦下来，不必等 refcheck.py。 */
function imageSize(file) {
  let buf;
  try { buf = fs.readFileSync(file); } catch { return null; }
  if (buf.length > 24 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4E && buf[3] === 0x47)
    return [buf.readUInt32BE(16), buf.readUInt32BE(20)];          // PNG IHDR
  if (buf.length > 4 && buf[0] === 0xFF && buf[1] === 0xD8) {      // JPEG
    let o = 2;
    while (o + 9 < buf.length) {
      if (buf[o] !== 0xFF) { o++; continue; }
      const m = buf[o + 1];
      if (m === 0xD8 || m === 0x01 || (m >= 0xD0 && m <= 0xD7)) { o += 2; continue; }
      const len = buf.readUInt16BE(o + 2);
      if (m >= 0xC0 && m <= 0xCF && m !== 0xC4 && m !== 0xC8 && m !== 0xCC)
        return [buf.readUInt16BE(o + 7), buf.readUInt16BE(o + 5)];
      o += 2 + len;
    }
  }
  if (buf.length > 30 && buf.toString('ascii', 1, 4) === 'GIF')
    return [buf.readUInt16LE(6), buf.readUInt16LE(8)];
  if (buf.length > 30 && buf.toString('ascii', 12, 16) === 'VP8X')
    return [(buf[24] | (buf[25] << 8) | (buf[26] << 16)) + 1,
      (buf[27] | (buf[28] << 8) | (buf[29] << 16)) + 1];
  return null;
}




/* 文本模板：${1} ${2} … 是「直接文本节点」槽位；${brand} 等具名占位符是变量 */
function parts(tpl) {
  const m = String(tpl).match(/\$\{(\d+)\}/g) || [];
  return m.length ? Math.max(...m.map((s) => +s.replace(/\D/g, ''))) : 0;
}
function fillVars(s, V) {
  return String(s).replace(/\$\{([A-Za-z_]\w*)\}/g, (m, k) =>
    Object.prototype.hasOwnProperty.call(V, k) ? V[k] : m);
}
function bake(tpl, vals, V) {
  let out = String(tpl).replace(/\$\{(\d+)\}/g, (m, k) => {
    const v = vals[+k - 1];
    return v == null ? '' : String(v);
  });
  return fillVars(out, V);
}
/* 纯文本（去标签去占位符），用于字数统计与禁用词扫描 */
const plain = (s) => String(s).replace(/<[^>]*>/g, '').replace(/\$\{\d+\}/g, '').replace(/\s+/g, ' ').trim();

/* ================================================================ ① 品牌包 */
const PACK = path.join(ROOT, 'brand', 'brand-pack.json');
if (!exists(PACK)) { console.error('✗ 缺少 brand/brand-pack.json（品牌包）'); process.exit(2); }
const BP = readJSON(PACK);

const REQUIRED = ['brandId', 'name', 'defaultLang'];
REQUIRED.forEach((k) => { if (!BP[k]) fail.push(`品牌包缺必填字段：${k}`); });
if (BP.name && !(BP.name.native || BP.name.zh)) fail.push('品牌包 name 至少要给 native 或 zh');

const BRAND_VARS = {
  brand: (BP.defaultLang === 'jp')
    ? [BP.name && BP.name.native, BP.name && BP.name.kana].filter(Boolean).join(' ')
    : ((BP.name && (BP.name.zh || BP.name.native)) || ''),
  brandzh: (BP.name && (BP.name.zh || BP.name.native)) || '',
  brandro: (BP.name && BP.name.romaji) || '',
};

/* ================================================================ ② 产品事实 */
const PROD = loadSandbox(path.join(ROOT, 'copy', 'products', 'product.js'), '__PRODUCT') || {};
const PRODUCT_VARS = Object.assign({}, BRAND_VARS, PROD.vars || {});

/* ================================================================ ③ 文案成稿 */
const ISSUE = loadSandbox(path.join(ROOT, 'copy', 'issue.js'), '__ISSUE') || {};

/* ================================================================ ④ 版式 JSON */
const LAY = path.join(ROOT, 'layout');
if (!exists(LAY)) { console.error('✗ 缺少 layout/ 目录（放参考图解析出来的版式 JSON）'); process.exit(2); }
const layoutFiles = fs.readdirSync(LAY).filter((f) => /\.json$/.test(f) && !/^_/.test(f)).sort();
if (!layoutFiles.length) { console.error('✗ layout/ 里没有版式 JSON（页数 = 参考图张数）'); process.exit(2); }

const PAGES = [];
for (const f of layoutFiles) {
  const L = readJSON(path.join(LAY, f));
  const num = (String(L.id || f).match(/(\d+)/) || [, ''])[1];
  if (!num) { fail.push(`${f}：文件名或 id 里找不到页码数字`); continue; }
  const pid = 'page' + (num.length < 2 ? '0' + num : num);
  PAGES.push({ pid, num: +num, file: f, L });
}
PAGES.sort((a, b) => a.num - b.num);
if (ONLY) { const k = PAGES.filter(p => p.pid === 'page' + ONLY.padStart(2, '0')); PAGES.length = 0; PAGES.push(...k); }

/* occlude 掩膜 → data URI（缓存 + 通道检查 + 体积闸）。
   ★为什么内联：见 renderZone 里 occlude 段的注释（file:// 下外链 mask 会被同源策略拒绝，
   表现为元素整块消失，且没有视觉提示）。 */
const _maskCache = new Map();
const MASK_DIMS = new Map();
function maskDataURI(src) {
  if (_maskCache.has(src)) return _maskCache.get(src);
  const p = path.join(ROOT, src);
  let uri = src;
  try {
    const buf = fs.readFileSync(p);
    const isPng = buf.length > 26 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4E;
    if (isPng) {
      const ct = buf[25];                       // IHDR color type：0/2/3 无 alpha，4/6 有
      if (ct !== 4 && ct !== 6)
        warn.push(`occlude 掩膜 ${src}：PNG 色彩类型 ${ct}（无 alpha 通道）→ 当 mask 用时整块不透明，等于没遮。请用 RGBA / gray+alpha 存`);
      const sz = imageSize(p);
      if (sz) MASK_DIMS.set(src, sz);
    } else {
      warn.push(`occlude 掩膜 ${src}：不是 PNG，内联时按 image/png 声明，可能不被识别`);
    }
    const b64 = buf.toString('base64');
    if (b64.length > 600 * 1024)
      warn.push(`occlude 掩膜 ${src}：内联后约 ${Math.round(b64.length / 1024)}KB，页面会明显变重（可先用锐化/减色压缩）`);
    uri = `data:image/png;base64,${b64}`;
  } catch (e) {
    fail.push(`occlude 掩膜读取失败：${src}（${e.message}）`);
  }
  _maskCache.set(src, uri);
  return uri;
}

/* ================================================================ 渲染一个 zone */
/* parent：子 zone 的 box 以父 zone 的 box 为坐标系（归一化到父框）。
   白卡里的「角标 / 款式图 / 编号 / 说明」用它 —— 卡一挪，卡里所有东西跟着走。
   ★坐标系约定：父框的 **padding box**（有 border/pad 时从 padding box 起算）。
     所以父框请勿设 pad / border，否则子坐标会整体偏移 border 宽度。
   ★子 zone 的 style.z 是**相对父的偏移**（父 z=4、子 z=1 → 实际 5），
     这样「卡整体换层」只需改卡一个数。 */
function resolveParents(zlist, pid, fail, warn) {
  const byId = new Map(zlist.map((z) => [z.id, z]));
  const done = new Set();
  const norm = (b) => (Array.isArray(b) ? b : [b.x, b.y, b.w, b.h]);
  function walk(z, depth) {
    if (!z.parent || done.has(z.id)) return;
    if (depth > 8) { fail.push(`${pid} ${z.id}：parent 嵌套过深（>8）或成环`); z.parent = null; return; }
    const p = byId.get(z.parent);
    if (!p) { fail.push(`${pid} ${z.id}：parent「${z.parent}」不存在`); z.parent = null; return; }
    walk(p, depth + 1);
    const pb = norm(p.box), zb = norm(z.box);
    z.box = [pb[0] + zb[0] * pb[2], pb[1] + zb[1] * pb[3], zb[2] * pb[2], zb[3] * pb[3]];
    const ps = p.style || {};
    if (ps.pad != null || ps.border) warn.push(`${pid} ${z.id}：父框「${p.id}」设了 pad/border，子坐标会从 padding box 起算（易偏移）`);
    z.style = z.style || {};
    const pz = ps.z == null ? 0 : Number(ps.z);
    z.style.z = pz + (z.style.z == null ? 1 : Number(z.style.z));
    done.add(z.id);
  }
  zlist.forEach((z) => walk(z, 0));
  return zlist;
}

function renderZoneInner(z, ctx, origin) {
  const { canvas, pid, copy, V } = ctx;
  const W = canvas.w, H = canvas.h;
  let box;
  if (Array.isArray(z.box)) box = [z.box[0] * W, z.box[1] * H, z.box[2] * W, z.box[3] * H];
  else box = [z.box.x, z.box.y, z.box.w, z.box.h];
  const cbox = box;                       // 画布坐标（occlude 掩膜对齐要用它）
  const ox = origin ? origin[0] : 0, oy = origin ? origin[1] : 0;   // 父框在画布上的原点
  const s = z.style || {};
  const st = [];
  st.push(`left:${Math.round((box[0] - ox) * 100) / 100}px`, `top:${Math.round((box[1] - oy) * 100) / 100}px`,
    `width:${Math.round(box[2] * 100) / 100}px`, `height:${Math.round(box[3] * 100) / 100}px`);
  if (s.z != null) st.push(`z-index:${s.z}`);
  if (s.rotate) st.push(`transform:rotate(${s.rotate}deg)`);
  if (s.opacity != null) st.push(`opacity:${s.opacity}`);
  const bg = col(s.bg); if (bg) st.push(`background:${bg}`);
  if (s.radius) st.push(`border-radius:${px(s.radius)}`);
  if (s.pad != null) st.push(`padding:${Array.isArray(s.pad) ? s.pad.map(px).join(' ') : px(s.pad)}`);
  if (s.border) st.push(`border:${s.border}`);

  /* ---- 主体遮挡（occlude）★「刊头艺术字被模特头部挡住」这类层叠关系的落地方式 ----
     出血照片是矩形的：把字放在照片上面，字永远看得见；放在下面，字永远看不见。
     要表达「谁挡住谁」，只能把**主体所占的那块**从字上挖掉 —— 用 CSS mask。
     掩膜 PNG 由 tools/herorecut.py --emit-mask 或 tools/submask.py 生成
     （不透明=保留，透明=挖掉）。
     mask-size 取**整幅画布**、mask-position 取本框在画布上的负偏移 → 掩膜按「画布坐标」对齐，
     与 zone 的 box 大小无关，同一张掩膜可以被任意多个 zone 共用。

     ★★ 必须内联成 data URI，不能写外链 url('images/xx.png')。
     原因：CSS mask 图像受同源策略约束，而本地直接打开页面时来源是 file://（null origin），
     外部 PNG 会被静默拒绝 —— 掩膜整块变透明，**元素 100% 消失**，且控制台不一定报错。
     这个失败模式没有任何视觉提示（字没了，看起来像"没排"），所以由引擎强制内联。 */
  if (z.occlude) {
    const src = String(z.occlude);
    const uri = maskDataURI(src);
    const mx = -(Math.round(cbox[0] * 100) / 100), my = -(Math.round(cbox[1] * 100) / 100);
    ['-webkit-', ''].forEach((pre) => {
      st.push(`${pre}mask-image:url('${uri}')`, `${pre}mask-repeat:no-repeat`,
        `${pre}mask-size:${W}px ${H}px`, `${pre}mask-position:${mx}px ${my}px`);
    });
  }

  const kind = z.kind || 'text';
  const cls = ['z', 'z--' + kind];
  if (z.mod) cls.push(...String(z.mod).split(/\s+/).filter(Boolean));
  /* 变体白名单：只有显式声明了 variant 的 zone 才会被 js/variants.js 扰动，
     避免变体引擎靠页面私有类名去猜（那是 yurutae 版写死 9 页的老毛病）。 */
  const vallow = (Array.isArray(z.variant) && z.variant.length)
    ? ` data-variant-allow="${z.variant.join(' ')}"` : '';

  /* --- 文本类：外层管几何，内层 .t 管排版（也是文案注入目标） --- */
  if (kind === 'text' || kind === 'badge' || kind === 'torn' || kind === 'bubble' || kind === 'label') {
    if (z.valign) { cls.push('has-valign'); st.push('display:flex', 'flex-direction:column',
      'justify-content:' + ({ top: 'flex-start', middle: 'center', bottom: 'flex-end' }[z.valign] || 'flex-start')); }
    const t = [];
    if (s.font) t.push('font-family:var(--font-' + s.font + ')');
    if (s.size) t.push(`font-size:${px(s.size)}`);
    if (s.weight) t.push(`font-weight:${s.weight}`);
    if (s.tracking != null) t.push(`letter-spacing:${s.tracking}em`);
    if (s.leading != null) t.push(`line-height:${s.leading}`);
    if (s.indent != null) t.push(`text-indent:${px(s.indent)}`);
    const c = col(s.color); if (c) t.push(`color:${c}`);
    if (s.align) t.push(`text-align:${s.align}`);
    if (s.writing === 'v') { cls.push('v'); if (s.upright) cls.push('v--upright'); }
    if (s.style) t.push(`font-style:${s.style}`);
    if (s.shadow) t.push(`text-shadow:${s.shadow}`);
    /* 弧排文字：几何在运行时算（js/arc.js），因为文字来自文案引擎、还要支持切语言重排。
       这里只把规格挂到 data-arc，并把 .t 里的文本节点留给 arc.js 搬进 <textPath>。 */
    if (z.arc) cls.push('is-arc');

    const tpl = z.tpl != null ? String(z.tpl) : '';
    const key = '#' + z.id + ' > .t';
    const entry = (copy || {})[key];
    const nReq = parts(tpl);
    let body;
    if (tpl) {
      if (entry) {
        const vals = Array.isArray(entry.jp) ? entry.jp : [entry.jp];
        if (vals.length !== nReq)
          fail.push(`${pid} ${key}：文案给 ${vals.length} 个值，版式有 ${nReq} 个文本节点`);
        body = bake(tpl, vals, V);
      } else {
        if (nReq > 0) warn.push(`${pid} ${key}（${plain(tpl).slice(0, 14) || z.id}）：还没写文案，暂用版式里的占位文本`);
        body = bake(tpl, new Array(nReq).fill(''), V);
      }
    } else body = '';
    return `<div class="${cls.join(' ')}" id="${z.id}"${vallow}` +
      `${z.arc ? ` data-arc='${JSON.stringify(z.arc).replace(/'/g, '&#39;')}'` : ''} style="${st.join(';')}">` +
      (body ? `<div class="t${s.font ? ' fr-' + s.font : ''}" style="${t.join(';')}">${body}</div>` : '') +
      `</div>`;
  }

  /* --- 图片类 --- */
  if (kind === 'image' || kind === 'cutout' || kind === 'mask' || kind === 'logo') {
    if (kind === 'mask') cls.push('is-' + (s.mask || 'circle'));
    if (kind === 'image' && s.treat) cls.push('is-' + s.treat);
    const alt = fillVars(z.alt || '', V);
    const src = z.src || '';
    return `<div class="${cls.join(' ')}" id="${z.id}"${vallow} style="${st.join(';')}">` +
      (src ? `<img src="${src}" alt="${alt}">` : '') + `</div>`;
  }

  /* --- 罫线 --- */
  if (kind === 'rule') {
    if (s.orient === 'v') cls.push('is-v');
    if (s.soft) cls.push('is-soft');
    if (s.weight) st.push('height:' + px(s.weight));
    return `<div class="${cls.join(' ')}" id="${z.id}"${vallow} style="${st.join(';')}"></div>`;
  }

  /* --- 色块 / 面板 / 底盘 --- */
  return `<div class="${cls.join(' ')}" id="${z.id}"${vallow} style="${st.join(';')}"></div>`;
}

/* 把子 zone 塞进父 zone 的 div 内（DOM 嵌套 → 子元素天然跟着父框走，
   也不怕父框以后改成 overflow:hidden 做裁切）。每个分支都恰好以 </div> 收尾，
   所以这里只替换**最后**那个闭合标签。 */
function renderZone(z, ctx, kidsById, origin) {
  const html = renderZoneInner(z, ctx, origin);
  const kids = kidsById && kidsById.get(z.id);
  if (!kids || !kids.length) return html;
  const W = ctx.canvas.w, H = ctx.canvas.h;
  const nb = Array.isArray(z.box) ? [z.box[0] * W, z.box[1] * H] : [z.box.x, z.box.y];
  const inner = kids.map((c) => renderZone(c, ctx, kidsById, nb)).join('\n        ');
  return html.replace(/<\/div>$/, `\n        ${inner}\n      </div>`);
}

/* ================================================================ 生成一页 HTML */
function buildPage(pid, L, copy) {
  const canvas = L.canvas || { w: 1366, h: 1748 };
  /* 叠图三态：成品 → 叠参考图 → 叠差异图（差异图由 tools/refgrid.py 生成） */
  const refBase = L.ref ? String(L.ref).replace(/\.[^.]+$/, '') : '';
  const ref = L.ref ? `assets/ref/${L.ref}` : '';
  const diff = refBase ? `assets/ref/_grid/${refBase}_diff.png` : '';
  const hasDiff = !!diff && exists(path.join(ROOT, diff));
  const zlist = resolveParents((L.zones || []).map((z) => Object.assign({}, z)), pid, fail, warn);
  const kidsById = new Map();
  const roots = [];
  for (const z of zlist) {
    if (z.parent) {
      if (!kidsById.has(z.parent)) kidsById.set(z.parent, []);
      kidsById.get(z.parent).push(z);
    } else roots.push(z);
  }
  const zctx = { canvas, pid, copy, V: PRODUCT_VARS };
  const zones = roots.map((z) => renderZone(z, zctx, kidsById)).join('\n      ');
  /* 掩膜尺寸必须等于画布 —— 差一点，「谁挡谁」就会整体错位（这正是"看起来差一点"的来源） */
  for (const z of zlist) {
    if (!z.occlude) continue;
    const sz = MASK_DIMS.get(String(z.occlude));
    if (sz && (sz[0] !== canvas.w || sz[1] !== canvas.h))
      fail.push(`${pid} ${z.id}：occlude 掩膜 ${z.occlude} 是 ${sz[0]}×${sz[1]}，画布是 ${canvas.w}×${canvas.h} → 遮挡会整体错位（请用 --size ${canvas.w}x${canvas.h} 重出掩膜）`);
  }
  const paperMods = ['page'];
  if (L.paper && L.paper.tone) paperMods.push('is-paper-' + L.paper.tone);
  if (L.paper && L.paper.grain) paperMods.push('paper-grain');

  const meta = L.meta || {};
  const title = fillVars(meta.title || (BP.name && BP.name.native) || '', PRODUCT_VARS);
  return `<!DOCTYPE html>
<html lang="ja" data-seed="${SEED || ''}">
<head>
<meta charset="utf-8">
<title>${title}${meta.page ? ' ｜ ' + meta.page : ''}</title>
<link rel="stylesheet" href="css/fonts.css">
<link rel="stylesheet" href="css/tokens.css">
<link rel="stylesheet" href="brand/_skin.css">
<link rel="stylesheet" href="css/typography.css">
<link rel="stylesheet" href="css/layout.css">
<link rel="stylesheet" href="css/variants.css">
<style>:root{--page-w:${canvas.w}px;--page-h:${canvas.h}px;}</style>
</head>
<body>
<div id="fitbox">
  <div class="stage-wrap">
    <div class="stage">
      <div class="${paperMods.join(' ')}">
        ${ref ? `<div class="ref-overlay ref-img" style="background-image:url('${ref}')"></div>` : ''}
        ${hasDiff ? `<div class="ref-overlay ref-diff" style="background-image:url('${diff}')"></div>` : ''}
      ${zones}
      </div>
    </div>
  </div>
</div>

<div class="toolbar">
  <button class="tb-prev" title="上一页（←）">←</button>
  <span class="pill-idx">${+pid.slice(4)} / ${PAGES.length}</span>
  <button class="tb-next" title="下一页（→）">→</button>
  <span class="sep"></span>
  <button class="tb-zoom-out" title="缩小（−）">−</button>
  <span class="zoomval">100%</span>
  <button class="tb-zoom-in" title="放大（＋）">＋</button>
  <button class="tb-fit" title="适合视窗（0）">适合</button>
  <button class="tb-100" title="原始尺寸">1:1</button>
  <span class="sep"></span>
  ${ref ? `<button class="tb-ref" title="叠图比对：参考图 → 差异图 → 关（O）${hasDiff ? '' : '；先跑 tools/refgrid.py 才有差异图'}">叠图</button>` : ''}
  <button class="tb-edit" title="直接改字（E）">改字</button>
  <a href="index.html" title="回到总览">总览</a>
</div>
<div class="hint">← → 翻页　+ − 缩放　O 叠图（参考图/差异）　E 改字　H 隐藏工具列</div>

<script src="js/vendor/jquery-3.7.1.min.js"></script>
<script src="copy/_data.js"></script>
<script src="js/copy.js"></script>
<script src="js/arc.js"></script>
<script src="js/variants.js"></script>
<script src="js/magazine.js"></script>
</body>
</html>
`;
}

/* ================================================================ 索引页 */
function buildIndex() {
  const cards = PAGES.map((p) => {
    const m = p.L.meta || {};
    return `      <a class="idx-card" href="${p.pid}.html">
        <div class="thumb" style="background-image:url('_shots/${p.pid}.png')"></div>
        <div class="meta"><b>${p.pid}${m.page ? ' ｜ ' + m.page : ''}</b>
        <span>${m.note || ''}</span><em>${p.file}</em></div>
      </a>`;
  }).join('\n');
  return `<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>${(BP.name && BP.name.native) || 'Magazine'} ｜ 总览（${PAGES.length} 页）</title>
<link rel="stylesheet" href="css/fonts.css"><link rel="stylesheet" href="css/tokens.css">
<link rel="stylesheet" href="brand/_skin.css"><link rel="stylesheet" href="css/typography.css">
<link rel="stylesheet" href="css/layout.css">
<style>body{background:#e7e4df;padding:46px 30px 90px}
.idx-head{max-width:1180px;margin:0 auto 34px}
.idx-head h1{font-family:var(--font-serif);font-size:40px;margin:0 0 10px;letter-spacing:var(--ls-cn)}
.idx-head p{margin:0;color:#6f6862;font-size:14px;line-height:1.9}
.idx-grid{max-width:1180px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:26px}
.idx-card{background:#fff;border-radius:6px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 6px 20px rgba(50,40,32,.12);transition:transform .18s,box-shadow .18s}
.idx-card:hover{transform:translateY(-4px);box-shadow:0 14px 34px rgba(50,40,32,.2)}
.idx-card .thumb{aspect-ratio:auto;min-height:220px;background:#f3f1ee center/cover no-repeat}
.idx-card .meta{padding:14px 16px 18px}
.idx-card .meta b{font-family:var(--font-serif);font-size:19px;display:block;margin-bottom:6px;letter-spacing:.04em}
.idx-card .meta span{font-size:12.5px;color:#7b736b;line-height:1.6;display:block}
.idx-card .meta em{font-style:normal;font-size:11.5px;color:#a49b92;letter-spacing:.08em}
</style></head><body>
<div class="idx-head"><h1>${(BP.name && BP.name.native) || ''} ｜ 杂志图总览</h1>
<p>共 ${PAGES.length} 页（页数 = 参考图张数）。每页尺寸取自其参考图。点开任意页可翻页 / 缩放 / 叠图比对 / 改字。</p></div>
<div class="idx-grid">
${cards}
</div></body></html>
`;
}

/* ================================================================ 品牌换肤 CSS */
function buildSkin() {
  const p = BP.palette || {};
  const f = BP.fonts || {};
  const MAP = { paper: '--paper', paperWarm: '--paper-warm', paperCream: '--paper-cream', paperGrey: '--paper-grey',
    ink: '--ink', ink2: '--ink-2', ink3: '--ink-3', ink4: '--ink-4', rule: '--rule', ruleSoft: '--rule-soft',
    accent: '--accent', accentSoft: '--accent-soft', accentDeep: '--accent-deep', accentWash: '--accent-wash',
    /* 参考刊解析出来的「背景基色 / 强调粉 / 冷调与暖调对比墨」也走品牌令牌：
       这样换品牌仍然只换 brand-pack.json，版式里不出现写死的色值。 */
    sky: '--sky', pink: '--pink', pinkDeep: '--pink-deep',
    inkCool: '--ink-cool', warmDeep: '--warm-deep' };
  const FMAP = { serif: '--font-serif', sans: '--font-sans', script: '--font-script',
    scriptFat: '--font-script-fat', latin: '--font-latin', latinItal: '--font-latin-ital' };
  const lines = [];
  Object.keys(MAP).forEach((k) => { if (p[k]) lines.push(`  ${MAP[k]}: ${p[k]};`); });
  Object.keys(FMAP).forEach((k) => { if (f[k]) lines.push(`  ${FMAP[k]}: ${f[k]};`); });
  const v = BP.visual || {};
  if (v.maxWeight) lines.push(`  /* 品牌字重上限：${v.maxWeight}（版式里超过的字重应下调，见 references/02 */`);
  return `/* 由 build.js 生成 —— 请勿手改；改 brand/brand-pack.json 后重新 node build.js */
/* 品牌：${(BP.name && BP.name.native) || ''}${BP.name && BP.name.kana ? ' / ' + BP.name.kana : ''} — ${BP.brandId} */
:root {
${lines.join('\n')}
}
`;
}

/* ================================================================ 槽位 + 数据 */
function collectSlots() {
  const out = {};
  PAGES.forEach(({ pid, L }) => {
    const canvas = L.canvas || { w: 1366, h: 1748 };
    const arr = [];
    (L.zones || []).forEach((z) => {
      const isText = ['text', 'badge', 'torn', 'bubble', 'label'].includes(z.kind || 'text');
      if (!isText || z.tpl == null) return;
      const s = z.style || {};
      const budget = (() => {
        if (!Array.isArray(z.box)) return null;
        const w = z.box[2] * canvas.w - (Array.isArray(s.pad) ? s.pad[1] + s.pad[3] : (s.pad || 0) * 2);
        const size = s.size || 17;
        return { chars_per_line: Math.max(1, Math.floor(w / (size * (1 + (s.tracking || 0.06))))), size, width: Math.round(w) };
      })();
      arr.push({ sel: '#' + z.id + ' > .t', id: z.id, ntext: parts(z.tpl),
        sample: plain(z.tpl).slice(0, 24), budget });
    });
    out[pid] = arr;
  });
  return out;
}

/* ================================================================ 主流程 */
if (fail.length) { fail.forEach((f) => console.error('✗ ' + f)); process.exit(1); }

/* 版式结构体检：id 唯一 + canvas + 逐 zone 白名单（validateZone 见文件上方） */
PAGES.forEach(({ pid, L, file }) => {
  if (!L.canvas || !L.canvas.w || !L.canvas.h) fail.push(`${file}：缺 canvas.w / canvas.h`);
  if (L.paper && L.paper.tone && !PAPER_TONES.has(L.paper.tone))
    fail.push(`${file}：未知 paper.tone「${L.paper.tone}」—— 白名单：${[...PAPER_TONES].join(' / ')}`);
  if (!Array.isArray(L.zones) || !L.zones.length) fail.push(`${file}：zones 为空`);
  const ids = new Set();
  (L.zones || []).forEach((z, i) => {
    if (!z || !z.id) fail.push(`${file} zones[${i}]：缺 id`);
    else if (ids.has(z.id)) fail.push(`${file}：zone id 重复 → ${z.id}`);
    else ids.add(z.id);
    validateZone(z, pid, file, i);
  });
});

/* ---------------------------------------------------------------- 硬断言 H1 / H2
   为什么是「硬」：这两条不是审美判断，是「有没有真的按参考图做」的事实判断。
   H1  页数 == 参考图张数（页数 = 参考图张数）
   H2  canvas == 该页参考图的真实像素尺寸（canvas 必须逐页取各自参考图）
   —— 与 tools/refcheck.py 同口径，编译期就拦，避免出图后才发现整册错位。
   demo 骨架请放进 assets/ref/_demo/（`_` 开头 = 不计入），或放 _stripped 标记降级。 */
const REF_DIR = path.join(ROOT, 'assets', 'ref');
const REF_STRIPPED = exists(path.join(REF_DIR, '_stripped'));
const refImgs = exists(REF_DIR)
  ? fs.readdirSync(REF_DIR).filter((f) => /\.(png|jpe?g|webp|gif)$/i.test(f)).sort()
  : [];
if (REF_STRIPPED) {
  warn.push('assets/ref/_stripped 标记存在 → 跳过 H1/H2 硬断言（仅供无参考图的调试）');
} else {
  if (!refImgs.length)
    fail.push('assets/ref/ 里没有参考图 —— 本引擎的页数由参考图张数决定（H1）');
  else if (refImgs.length !== PAGES.length)
    fail.push(`H1 页数 ≠ 参考图张数：layout/ 有 ${PAGES.length} 个版式，assets/ref/ 有 ${refImgs.length} 张参考图` +
      `（demo 骨架放 assets/ref/_demo/）`);
  PAGES.forEach(({ pid, L, file }) => {
    if (!L.ref) { warn.push(`${file}：没写 ref —— 这一页不叠参考图，也不参与 H2 尺寸断言`); return; }
    const rp = path.join(REF_DIR, L.ref);
    if (!exists(rp)) { fail.push(`${file}：ref 指向的参考图不存在 → assets/ref/${L.ref}`); return; }
    const sz = imageSize(rp);
    const c = L.canvas || {};
    if (sz && (sz[0] !== c.w || sz[1] !== c.h))
      fail.push(`H2 ${pid}：canvas ${c.w}×${c.h} ≠ 参考图 ${L.ref} 真实尺寸 ${sz[0]}×${sz[1]}`);
    else if (!sz) warn.push(`${file}：读不出 ${L.ref} 的尺寸（格式不支持？）—— H2 未生效`);
  });
}

/* 文案与版式的接口一致性 + 禁用词 */
const FORB = BP.forbidden || {};

/* ------------------------------------------------------------------ 导出「解析后」版式
   ★为什么必须导出：layout/NN.json 里带 "parent" 的子 zone，box 是**相对父框**的归一化坐标。
     判据脚本若直读原文，会把「白卡里的第 4 行」当成「画布上的第 4 行」，
     算出假的文字互压 / 假的模块遮挡 / 假的结构线缺失 —— 而且它只会给出一个
     「看起来很像真问题」的数字，最难查。
     所以：编译期折算一次，落成 layout/_resolved.json，判据一律读它。
     回落行为：若该文件不存在（旧工程未重建），判据自行回落到原文（此时无 parent 时等价）。 */
const resolvedByPage = {};
PAGES.forEach(({ pid, L }) => {
  const c = L.canvas || { w: 1366, h: 1748 };
  const zl = resolveParents((L.zones || []).map((z) => Object.assign({}, z)), pid, fail, warn);
  resolvedByPage[pid] = {
    canvas: [c.w, c.h],
    ref: L.ref || null,
    zones: zl.map((z) => ({
      id: z.id, kind: z.kind || 'text', box: z.box, parent: z.parent || null,
      style: z.style || {}, occlude: z.occlude || null, arc: z.arc || null
    }))
  };
});
fs.writeFileSync(path.join(LAY, '_resolved.json'), JSON.stringify(resolvedByPage, null, 1));

const slotsByPage = collectSlots();
const copyAll = {};
PAGES.forEach(({ pid }) => {
  const c = ISSUE[pid] || {};
  copyAll[pid] = c;
  if (!Object.keys(c).length) warn.push(`${pid}：copy/issue.js 里还没有这一页的文案`);
  Object.keys(c).forEach((sel) => {
    const hit = (slotsByPage[pid] || []).find((s) => s.sel === sel);
    if (!hit) fail.push(`${pid}：文案槽位 ${sel} 在版式里不存在`);
    else {
      const e = c[sel];
      const n = Array.isArray(e.jp) ? e.jp.length : 1;
      if (n !== hit.ntext) fail.push(`${pid} ${sel}：文案 ${n} 个值 / 版式 ${hit.ntext} 个文本节点`);
    }
  });
});
/* 禁用词：对烘进去的正表记稿扫一遍 */
PAGES.forEach(({ pid, L }) => {
  const c = copyAll[pid] || {};
  (L.zones || []).forEach((z) => {
    if (z.tpl == null) return;
    const e = c['#' + z.id + ' > .t'];
    const t = e ? (Array.isArray(e.jp) ? e.jp.join(' ') : e.jp) : plain(z.tpl);
    Object.keys(FORB).forEach((g) => (FORB[g] || []).forEach((w) => {
      if (w && String(t).indexOf(w) >= 0) fail.push(`${pid} ${z.id}：正表记稿出现禁用词[${g}]「${w}」`);
    }));
  });
});

if (fail.length) { fail.forEach((f) => console.error('✗ ' + f)); process.exit(1); }

if (CHECKONLY) {
  log(`✓ 体检通过：${PAGES.length} 页 / ${PAGES.reduce((n, p) => n + (p.L.zones || []).length, 0)} 个分区 / ` +
    `${PAGES.reduce((n, p) => n + (slotsByPage[p.pid] || []).length, 0)} 个文案槽位`);
  warn.forEach((w) => log('  · ' + w));
  process.exit(0);
}

/* 写文件 */
PAGES.forEach(({ pid, L }) => {
  fs.writeFileSync(path.join(ROOT, pid + '.html'), buildPage(pid, L, copyAll[pid]));
});
fs.writeFileSync(path.join(ROOT, 'index.html'), buildIndex());
fs.writeFileSync(path.join(ROOT, 'brand', '_skin.css'), buildSkin());
fs.writeFileSync(path.join(ROOT, 'copy', 'slots.json'), JSON.stringify(slotsByPage, null, 1));

const data = `/* 由 build.js 生成 —— 勿手改 */
window.MAGAZINE = ${JSON.stringify({
  issue: (BP.brandId || 'issue'),
  defaultLang: BP.defaultLang || 'jp',
  total: PAGES.length,
  pages: PAGES.map((p) => p.pid),
  label: { jp: '日本語', zh: '中文' },
  copy: copyAll,
  brandData: { name: BP.name || {}, forbidden: FORB, signature: BP.signature || {}, slogan: BP.slogan || {} },
  productData: PROD,
  meta: BP.meta || {}
}, null, 1)};
`;
fs.writeFileSync(path.join(ROOT, 'copy', '_data.js'), data);

if (BRIEF) {
  const L = ['# 文案骨架（字数预算）', '',
    `> 由 build.js --brief 生成。写 copy/issue.js 时按此填。`,
    `> **部件数 = 0 的行是「结构标签」**（Step / 数字序号等），已由版式直接烘进 HTML，不要写文案。`, ''];
  PAGES.forEach(({ pid }) => {
    L.push(`## ${pid}`, '', '| 槽位（写进 copy/issue.js 的键） | 部件数 | 每行字数 | 字号 | 原占位文本 |', '|---|---|---|---|---|');
    (slotsByPage[pid] || []).forEach((s) => {
      L.push(`| \`${s.sel}\` | ${s.ntext} | ${s.budget ? s.budget.chars_per_line : '-'} | ${s.budget ? s.budget.size : '-'} | ${s.sample} |`);
    });
    L.push('');
  });
  fs.writeFileSync(path.join(ROOT, 'copy', '_brief.md'), L.join('\n'));
  log('-> copy/_brief.md');

  /* _skeleton.js：可直接粘贴成 copy/issue.js 的空壳。
     ntext=1 → { jp:'', zh:'' }；ntext>1 → 长度为 ntext 的数组（个数必须等于版式里 ${n} 的个数）。
     ★ ntext=0 的槽位（Step / 1 / 2 … 这类结构标签）**不能写成空值** ——
       它们没有 ${n} 可填，写成 {jp:''} 会变成「1 个值 vs 0 个文本节点」而 fail。
       这里只以注释列出，让作者知道它们存在。 */
  const S = ['/* 由 build.js --brief 生成 —— 不是成稿，是骨架。',
    '   把每个槽位重写成 { jp, zh } 成对文案后覆盖 copy/issue.js，再跑 node tools/copycheck.js。',
    '   注释里的「预算」= 每行可容纳字数：写长了会把固定框挤爆（copycheck 版面层会拦）。',
    '   ★ 本文件里出现的选择器才是「可写槽位」；ntext=0 的结构标签（Step / 数字序号）',
    '     已由版式直接烘进 HTML，**不要**给它们写文案。 */',
    'window.__ISSUE = {'];
  let nWritable = 0, nStruct = 0;
  PAGES.forEach(({ pid }) => {
    S.push('', `  /* ═══════════ ${pid} ═══════════ */`, `  ${pid}: {`);
    (slotsByPage[pid] || []).forEach((s) => {
      const sel = JSON.stringify(s.sel);
      if (s.ntext === 0) {
        nStruct++;
        S.push(`    /* [结构标签·不用写] ${sel} —— 版式直接烘入：「${(s.sample || '').replace(/\*\//g, '*\\/')}」 */`);
        return;
      }
      nWritable++;
      S.push(`    /* ntext=${s.ntext} · 预算 ${s.budget ? s.budget.chars_per_line : '-'} 字/行 · ${s.sample || s.id} */`);
      if (s.ntext > 1) {
        const a = () => '[' + Array(s.ntext).fill("''").join(', ') + ']';
        S.push(`    ${sel}: { jp: ${a()}, zh: ${a()} },`);
      } else {
        S.push(`    ${sel}: { jp: '', zh: '' },`);
      }
    });
    S.push('  },');
  });
  S.push('};', '');
  fs.writeFileSync(path.join(ROOT, 'copy', '_skeleton.js'), S.join('\n'));
  log(`-> copy/_skeleton.js（可写槽位 ${nWritable} 个；结构标签 ${nStruct} 个已注明）`);
}

/* ---------------------------------------------------------------- --prune
   只删「编号已经不在 layout/ 里的幽灵页」—— pageNN.html 与 _shots/pageNN*.png。
   绝不碰当前页、素材、参考图、字体。默认只列不删；加 --yes 才真删（与 tools/prune.js 同规）。 */
if (PRUNE) {
  const alive = new Set(PAGES.map((p) => p.pid));
  const PAGE_HTML = /^page(\d+)\.html$/;
  const PAGE_PNG = /^(page\d+)(_[A-Za-z0-9]+)?\.png$/;
  const ghosts = [];
  const scanDir = (dir, test, pick) => {
    if (!exists(dir)) return;
    fs.readdirSync(dir).forEach((f) => {
      const p = path.join(dir, f);
      let st; try { st = fs.statSync(p); } catch { return; }
      if (!st.isFile() || !test(f)) return;
      const pid = pick(f);
      if (pid && !alive.has(pid)) ghosts.push(p);
    });
  };
  scanDir(ROOT, (f) => PAGE_HTML.test(f), (f) => 'page' + PAGE_HTML.exec(f)[1]);
  scanDir(path.join(ROOT, '_shots'), (f) => PAGE_PNG.test(f), (f) => PAGE_PNG.exec(f)[1]);

  if (!ghosts.length) log('  · prune：没有陈旧产物');
  else {
    let n = 0;
    ghosts.forEach((p) => {
      const rel = path.relative(ROOT, p).replace(/\\/g, '/');
      if (YES) { try { fs.unlinkSync(p); n++; log('    rm   ' + rel); }
                 catch (e) { log('    ! 删除失败 ' + rel + '：' + e.message); } }
      else log('    would rm  ' + rel);
    });
    log(YES ? `  · prune：已删除 ${n} 个陈旧文件` : `  · prune：将删除 ${ghosts.length} 个（dry-run，加 --yes 才真删）`);
  }
}

log(`✓ 编译完成：${PAGES.length} 页 → ` + PAGES.map((p) => p.pid).join(', '));
log(`  · 品牌：${(BP.name && BP.name.native) || ''}（${BP.brandId}）  字体与配色已写入 brand/_skin.css`);
log(`  · 槽位：${PAGES.reduce((n, p) => n + (slotsByPage[p.pid] || []).length, 0)} 个 → copy/slots.json`);
if (warn.length) { log('  · 提示'); warn.forEach((w) => log('    · ' + w)); }
