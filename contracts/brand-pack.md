# 品牌包契约 · brand-pack.json

> **这份文件是对外的。** 可以整份交给品牌侧（`brand-creation` / 任何品牌管家 skill）当作交付格式说明。
> 版本：`1.0` ｜ 建立：2026-09-30 ｜ 维护者：`brand-magazine`
>
> 只要按这份契约产出一个 `brand-pack.json`，杂志图引擎就能把**任意品牌**渲染出来，
> 不需要改任何一行 HTML/CSS/JS。

---

## 一、这份契约解决什么

一条硬边界：**引擎不许知道品牌，品牌不许知道版式。**

| 层 | 谁负责 | 产物 | 变更频率 |
|---|---|---|---|
| 品牌层 | 品牌管家（`yurutae-brand` 等） | `brand/brand-pack.json` | 低（定案级） |
| 版式层 | 本引擎（看参考图解析） | `layout/*.json` | 中（换参考图才动） |
| 产品层 | 你（供货方信息 + 肉眼可见） | `copy/products/product.js` | 高（一物一次） |
| 文案层 | 本引擎（品牌语气重写） | `copy/issue.js` | 高（一期一次） |

四层之间**只通过本契约与 layout JSON 两个接口说话**。所以：
换品牌 → 只换 `brand-pack.json`；换产品 → 只换 `product.js` 与 `issue.js`；换参考图 → 只换 `layout/`。

---

## 二、字段总表

`*` = 必填；其余缺省时用引擎出厂默认（`css/tokens.css`）。

| 字段 | 类型 | 用途 | 落到哪 |
|---|---|---|---|
| `brandId` * | string | 机器名（小写无空格），用于文件名与报告 | `_data.js` |
| `brandSkill` | string | 产出这份包的 skill 名（回指，便于追溯与同步） | 备注 |
| `defaultLang` * | `"jp"` \| `"zh"` | 正表记语言（通常 `jp`） | 页面默认语言 |
| `langs` | string[] | 允许的语言稿，默认 `["jp","zh"]` | 语言切换按钮 |
| `name` * | object | 品牌名四态，见 §3.1 | `${brand}` `${brandzh}` `${brandro}` |
| `signature` | object | 署名规范，见 §3.2 | 禁止越界署名 |
| `slogan` | object | 广告语 + **配平规则**，见 §3.3 | 合规层检查 |
| `tone` | object | 语气摘要与硬规则（给人看的，也供写文案时自查） | `references/02` |
| `forbidden` * | object | 禁用清单四组，见 §3.4 | `build.js` + `copycheck.js` 双层拦截 |
| `palette` | object | 配色，见 §3.5 | `brand/_skin.css` → CSS 变量 |
| `fonts` | object | 字体角色 → font-family，见 §3.6 | `brand/_skin.css` → `--font-*` |
| `fontMap` | array | 「原刊字体 → 替代字体」台账，见 §3.7 | `ASSETS.md` 记录用 |
| `visual` | object | 视觉约束上限，见 §3.8 | 写文案/调版式时的人读约束 |
| `price` | object | 价格口径与默认值，见 §3.9 | `${price}` 占位符 |
| `compliance` | object | 适用法规与红线，见 §3.10 | 合规层提示 |
| `meta` | object | `issue` / `updatedAt` 等自由登记 | 备注 |

---

## 三、逐字段规格

### 3.1 `name` — 品牌名四态

```json
{ "native": "由良妙", "kana": "ゆらたえ", "romaji": "YURUTAE", "zh": "由良妙" }
```

- `native` 或 `zh` **至少给一个**，否则引擎报错退出。
- `${brand}` 在正表记稿里 = `native + " " + kana`（有 kana 时）；在中文对照稿里 = `zh || native`。
- `${brandzh}` = `zh || native`；`${brandro}` = `romaji`。
- 日文品牌建议**全程平假名 slogan / 汉字或假名品牌名**按品牌定案，不要在这里二次创作。

### 3.2 `signature` — 署名

```json
{ "primary": "下着の作家", "zh": "内衣作家", "noPlaceName": true,
  "note": "署名不附地名；法定表示栏写责任主体（表示者名），不写人格化署名。" }
```

- `primary` 是**唯一允许出现的创作者署名**。页面任何署名位只许用这一串。
- `noPlaceName: true` → 引擎把「地名 + 署名」的组合视为越界（`copycheck` 会拦）。
- **禁止真实艺人姓名与履历。** 这条不是可选项：参考刊里的人物栏一律改写成产品事实（尺寸/结构/面料/颜色）。

### 3.3 `slogan` — 广告语与配平

```json
{ "native": "すきなものは、すき。", "zh": "你喜欢，就够了。",
  "mustPair": ["からだの形は、からだが決める。", "好みに、正解はない。"],
  "note": "Slogan 出现时后必须紧跟一句「交回决定权」的句子。" }
```

- **配平规则（重要）**：`native` 一旦出现在页面上，其后 60 字内**必须**以 `mustPair` 里任一句开头。
  `copycheck` 的 D 组会实测渲染后正文，不配平 → FAIL。
- 为什么：品牌 slogan 是平假名软句，单独出现会被读成「讨好」；配一句把决定权交回读者的句子才成对。
- 不需要配平时给空数组 `[]`（= 关闭该项检查）。

### 3.4 `forbidden` — 禁用清单四组

```json
{
  "adjectives": ["究極","最高","奇跡","贅沢","極上","ふわふわ","高雅","亮眼"],
  "claims":     ["寄せ上げ","集中","補正","托高","育乳","肩こり軽減","ノンワイヤー","无钢圈"],
  "brands":     ["Victory Doopair","Rhodes","Goody International","mimi33"],
  "symbols":    ["♥","💕"]
}
```

| 组 | 拦什么 | 谁在拦 |
|---|---|---|
| `adjectives` | 空泛最高级 —— 景表法「優良誤認」高危区 | `build.js` 扫正表记稿 + `copycheck` 扫渲染后正文 |
| `claims` | 效果承诺 —— 内衣类「機能性表示」红线 | 同上 |
| `brands` | 未经品牌确认的第三方品牌 | 同上（含 `<title>` / `alt` / 注释） |
| `symbols` | 与品牌视觉冲突的符号 | 同上 |

> **两份清单都要有。** `build.js` 在编译期拦（改文案前就报错），`copycheck` 在渲染后拦
> （能抓到 JS 注入后拼接出来的词）。只留一份会漏。
>
> **不要删旧品牌检测词。** 即使本期已清干净，保留检测词是兜底——下次误粘贴时会立刻报错。

### 3.5 `palette` — 配色

键名固定，全部可选（缺省用 `tokens.css` 出厂值）：

| 键 | CSS 变量 | 语义 |
|---|---|---|
| `paper` | `--paper` | 主纸底 |
| `paperWarm` | `--paper-warm` | 生成り（米白） |
| `paperCream` | `--paper-cream` | 奶油纸 |
| `paperGrey` | `--paper-grey` | 灰纸 |
| `ink` / `ink2` / `ink3` / `ink4` | `--ink` … | 四级文字深浅 |
| `rule` / `ruleSoft` | `--rule` / `--rule-soft` | 罫线 |
| `accent` / `accentDeep` / `accentSoft` / `accentWash` | `--accent*` | 强调色四态 |

- 版式 JSON 里写**令牌名**（`"color": "ink-2"`、`"bg": "accent"`）就自动跟品牌包走；
  写**字面色值**（`"#ffffff"`）则该处与品牌包解耦（用于必须压在照片上的白字）。
- 出厂默认 `--accent` 是**中性墨色**（`#1a1815`），不是粉色——这样未换肤时也不会「自带一个不属于任何品牌的粉」。

### 3.6 `fonts` — 字体角色

六个角色，键名固定：

| 角色 | CSS 变量 | 出厂字体 | 用在什么位置 |
|---|---|---|---|
| `serif` | `--font-serif` | Mag Mincho JP/SC（明朝・宋） | 标题、竖排句、正文名注 |
| `sans` | `--font-sans` | Mag Gothic JP（黑体） | 说明文、Step 小字、credits |
| `script` | `--font-script` | Mag Script Silk（细铜版手写） | 装饰性小字、Step 词 |
| `scriptFat` | `--font-script-fat` | Mag Script Ribbon（粗手写） | 需要清晰度的手写位 |
| `latin` | `--font-latin` | Mag Editorial（Didot 系） | 大写字标、页码 |
| `latinItal` | `--font-latin-ital` | Mag Editorial Italic | 斜体拉丁词 |

**要一套新字体怎么办**：把 woff2 放进 `fonts/`，在 `css/fonts.css` 加 `@font-face`，
再把 `brand-pack.json` 的 `fonts` 段指过去。**不要**直接改版式 JSON 里的角色名——
`"font": "serif"` 是角色，不是字体，版式不该知道字体。

### 3.7 `fontMap` — 字体替代台账

```json
{ "role": "serif", "from": "参考刊标题明朝体（商用版权字体）",
  "to": "Mag Mincho JP / SC（Noto Serif JP/SC）",
  "why": "相似点：同为高对比明朝，横细竖粗、字面宽度接近。差异：参考刊竖画收笔顿角更锐、假名曲线更紧；替代体顿角略圆、假名稍宽，故标题需靠 tracking 收一点。OFL 可商用，规避字体版权" }
```

**硬性口径（三条，缺一条这份台账就不算数）**：

1. **每条必须有 `why`，且 `why` 必须同时写「相似点」与「差异」** —— 只写相似点等于没写：
   「差异」才是执行者知道该往哪调（字距？字号？字重？）的唯一线索。
   出厂示例的两条反例：`"同为笔画如丝线的 copperplate 系"`（没写差异）不合格，
   已改写为「差异：替代体 x-height 偏小……需放大一级字号」。
2. **`fonts` 段里有几个角色，`fontMap` 就要有几条**。出厂六个角色 → 六条映射。
   漏条目的角色意味着「没人判定过它像不像」，而它照样会被渲染出来。
3. **`role` 写角色名（`serif`/`sans`/`script`/`scriptFat`/`latin`/`latinItal`，驼峰版，与 `fonts` 段一致）**，
   不是字体名。

**怎么填**：识别原刊字体的流程见 `references/05-font-identification.md`（六步：看衬线 →
看排向字距 → `refgrid --zoom --crop` 放大取证 → 对照 12 个内嵌字体选最相似 → 写台账 → 验证）。

**怎么验**（两步都要，缺一不可）：

```bash
node tools/fontcheck.js   # ① 证明「真的用了内嵌字体」而不是静默回落到 SimSun
node tools/inkprobe.js    # ② 证明「font-weight 真的生效」——字体文件对 ≠ 字重对
```

这份映射要抄进 `ASSETS.md` 与冻结产物的 `SKILL.md`（`freeze.js` 会自动生成该表）。

### 3.8 `visual` — 视觉约束上限

```json
{ "maxWeight": 500, "minWhitespace": 0.4, "badgesIconOnly": true,
  "banned": ["gradient","neon","large-color-block","countdown"],
  "photoRule": "拍布、拍缝线、拍结构；不拍「完美身材」。" }
```

- `maxWeight`：字重上限。**注意：出厂版式里多处用了 700/900。**
  这是已知冲突（见 `references/02` 第二节），启用严格模式时要逐条下调并重跑版面回归。
- `minWhitespace`：留白下限（占版心比例），给人读的约束。
- `badgesIconOnly: true` → 折扣/包邮等促销信息**只能图标化**，不许写进正文语句。
- `banned`：明令禁止的视觉手法。

### 3.9 `price` — 价格口径

```json
{ "currency": "¥", "defaultPrice": "¥1,950", "showWhenMissing": false }
```

- **用户未提供价格时一律用 `defaultPrice`。** 改价只动这一处（或产品层 `product.js` 的 `vars.price`）。
- `showWhenMissing: false` → 没价格就不显示价格位，不显示「¥0」或「价格待定」这类占位。

### 3.10 `compliance` — 法规与红线

```json
{ "regimes": ["景品表示法","家庭用品品質表示法","薬機法","特定商取引法"],
  "rules": ["产品信息里没有的标签，一个字都不加。", "地缘来源 ≠ 材料来源，不得混用。",
            "促销信息一律图标化。", "署名不附地名。"],
  "escalate": "涉及署名、表示者名、景表法边界的最终判断，须由日本行政書士／弁理士过一遍。" }
```

`escalate` 是对交接方的**如实声明**：本引擎保证「清单内的词不出现」，
**不保证**「清单外的表达一定合法」。涉及署名 / 表示者名 / 景表法边界的最终判断要人工过一遍。

---

## 四、最小可用品牌包

只想先跑通引擎，给这四个字段就够：

```json
{
  "brandId": "demo",
  "defaultLang": "jp",
  "name": { "native": "テスト商店", "romaji": "TEST" },
  "forbidden": { "adjectives": [], "claims": [], "brands": [], "symbols": [] }
}
```

其余字段缺省 → 用 `css/tokens.css` 的出厂默认（中性墨色 + 内嵌明朝体/黑体）。
**跑得起来，只是没有品牌辨识度。**

---

## 五、把品牌包交给引擎

```
<工作目录>/brand/brand-pack.json     ← 这份文件放这里
node build.js                        ← 引擎读它 → 写 brand/_skin.css
```

- `brand/_skin.css` **由 `build.js` 生成，请勿手改**（下次 build 会覆盖）。
- 改品牌 → 改 `brand-pack.json` → 重跑 `node build.js`。
- 引擎也会在编译期做**契约体检**：缺 `brandId`/`name`/`defaultLang`、`name` 四态全空、
  禁用词命中，一律退出码非 0，不写文件。

---

## 六、校验清单（引擎侧自动执行）

| # | 检查 | 在哪 |
|---|---|---|
| 1 | 必填字段 `brandId` / `name` / `defaultLang` 齐全 | `build.js` 编译期 |
| 2 | `name` 至少给 `native` 或 `zh` | `build.js` 编译期 |
| 3 | 正表记稿无 `forbidden` 四组词 | `build.js` 编译期 |
| 4 | 渲染后正文无 `forbidden` 四组词（含 JS 拼接结果） | `copycheck.js` D 组 |
| 5 | `slogan.native` 出现时按 `mustPair` 配平 | `copycheck.js` D 组 |
| 6 | 字体角色真身是内嵌字体，不是系统回退（SimSun 等） | `tools/fontcheck.js` |
| 7 | **字重真的生效**（同族墨量随字重单调、400→700 增量 ≥ 0.5pt） | `tools/inkprobe.js` |
| 8 | 版式里出现的 `kind` / `style.font` 都在白名单内 | `build.js` 编译期（`validateZone`） |
| 9 | 页数 = 参考图张数；每页 `canvas` = 参考图真实尺寸 | `build.js` 编译期 ＋ `tools/refcheck.py` |

> 6 与 7 是两件事：6 答「用了哪个字体文件」，7 答「粗体到底有没有变粗」。
> 只跑 6 会让「标称 bold 但实际不变粗」的情况静默通过。

---

## 七、版本与变更

- 契约版本 **1.0**。破坏性变更（改名/删字段/改语义）→ 升 minor 并在此记录。
- 引擎侧兼容策略：**未知字段忽略不报错**（前向兼容），已知字段缺失按 §三 的缺省处理。
- 变更记录：

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0 | 2026-09-30 | 初版。四层解耦接口定型；`fontMap` 与 `slogan.mustPair` 为本次新增。 |
| 1.1 | 2026-09-30 | §3.7 加硬性口径三条（`why` 必须同写相似点与差异；`fontMap` 条数 == `fonts` 角色数；`role` 用驼峰角色名）＋ 两步验证（`fontcheck` ＋ `inkprobe`）；§六 校验清单补 7/8/9 条。 |
