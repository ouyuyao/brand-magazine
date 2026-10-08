# templates/ —— 引擎主体

> **这个目录是母版。** 使用时把**整个目录复制**到你的工作目录（`cp -r templates <工作目录>/magazine-<slug>`），
> 然后只改 `brand/` `layout/` `copy/` `images/` 四个地方。**不要直接改母版。**
>
> 完整流程见 `../SKILL.md`；技术规格见 `../references/`。

---

## 两段式流程（**别指望一分钟跑通**）

这个引擎分两段。**跳过 Stage A 就没意义**——那等于「换个产品套同一套版」。

### Stage A · 定制（跑一次；换参考图 / 换品牌时才重跑）

```bash
cp -r <skill>/templates ./magazine-<slug> && cd ./magazine-<slug>

# ① 解析参考图 —— ★ 这一步是本引擎存在的理由
python tools/refscan.py            # 候选带缝 / 带内分栏 / 参考图真实尺寸
python tools/refgrid.py p01.jpg    # 百分比坐标网校正（--shot page01 出差异热图）
#    → 照读数写 layout/NN.json（一张参考图 → 一个 JSON）

python tools/refcheck.py           # 硬门禁：页数 = 参考图张数；canvas = 参考图尺寸

# ② 品牌与内容
#    brand/brand-pack.json      换品牌只换这一个 JSON
#    copy/products/product.js   产品事实
node build.js --brief              # 出 copy/_brief.md（字数预算）+ copy/_skeleton.js（空壳）
#    → 照骨架写 copy/issue.js
node build.js && node tools/copycheck.js

# ③ 试排 2–3 页 + 打分
node tools/shoot.js
python tools/reffit.py             # 骨架吻合分 ≥ 0.80 为佳（告警级）

# ④ 冻结成独立专用 skill
node tools/freeze.js --name <slug> --out <skillsDir>
```

### Stage B · 出图（跑在冻结出的专用 skill 里）

```bash
node build.js                      # 默认保真；一物一版用 --seed <SKU名>
python tools/refcheck.py           # 硬门禁
node tools/copycheck.js            # 硬门禁（退出码必须 0）
node tools/shoot.js                # 出图 → _shots/pageNN.png
node tools/labelrects.js && python tools/check_faces.py && python tools/blockcheck.py
node tools/fontcheck.js && node tools/inkprobe.js
python tools/preview.py            # 总览；中文稿加 --tag zh
python tools/reffit.py             # 吻合分（告警）
```

---

## ⚠️ 直接 `node build.js` 会**故意报错**

```
✗ layout/ 里没有版式 JSON（页数 = 参考图张数）
```

这不是故障，是设计。出厂**不摆**现成的 `layout/*.json`：

- 示例骨架被隔离在 `layout/_demo/`，示例参考图在 `assets/ref/_demo/`
  （`_` 开头 → `build.js` / `copycheck.js` / `shoot.js` / `refcheck.py` 一律不计入）
- 想看示例：`node tools/demo.js --enable`（撤下用 `--disable`）

**为什么这么做**：以前出厂预置两份骨架 + 参考图，执行者 `cp` 完直接编译
就得到「看起来像样」的两页图，**全程零报错地跳过了「解析参考图」**。
现在跳不过去了。

> 那份示例的 `reffit` 吻合分只有 0.22 / 0.49 —— 它就是「照抄 box 而没解析」的代价的
> 量化证据。**换参考图必须用 refscan + refgrid 重新解析，不要照抄 `_demo` 里的 box。**

---

## 你要改的四个地方

| 目录 | 放什么 | 契约/约定 |
|---|---|---|
| `brand/brand-pack.json` | 品牌包（配色/字体/语气/禁用清单/署名/价格口径） | `../contracts/brand-pack.md` |
| `layout/*.json` | 版式骨架（**页数 = 文件个数 = 参考图张数**，`canvas` 必须等于该页参考图真实尺寸） | `../references/01-skeleton-and-layout.md` |
| `copy/products/product.js` | 产品事实（只写可见事实，每条带来源） | 文件内注释 |
| `copy/issue.js` | 成稿文案（逐槽位 `{ jp, zh }` 成对） | `../references/02-copy-and-compliance.md` |
| `images/` | 素材（**文件名固定**，见 `images/README.md`） | `images/README.md` |
| `assets/ref/` | 参考图（**必填**，Stage A 的输入；张数 = 页数） | `assets/README.md` |

## 你不要改的（都是自动生成的）

| 文件 | 谁生成 |
|---|---|
| `pageNN.html`、`index.html` | `build.js` |
| `brand/_skin.css` | `build.js`（读品牌包） |
| `copy/slots.json`、`copy/_data.js`、`copy/_brief.md`、`copy/_skeleton.js` | `build.js` |
| `images/_alphabox.json` | `tools/alphabox.py` |
| `assets/ref/_scan/`、`assets/ref/_grid/` | `tools/refscan.py`、`tools/refgrid.py` |
| `_shots/*`、`_shots/report/*` | `tools/shoot.js` / `refcheck.py` / `reffit.py` 等 |
| `preview-pages*.jpg` | `tools/preview.py` |

**改这些文件等于白改**（下次 build/shoot 会覆盖）。要改结果，改上游。

---

## 引擎结构

```
build.js                  ★引擎入口：品牌包 + layout + 文案 → 整页 HTML
                          （内含 kind/font 白名单校验 + H1/H2 硬断言 + --prune + --seed）
layout/NN.json            ★版式骨架（归一化坐标 [x,y,w,h]）
layout/_demo/             出厂示例骨架（_ 开头 → 引擎不计入）
layout/README.md          版式 JSON 的格式速查
brand/brand-pack.json     品牌包 → 自动生成 brand/_skin.css
copy/products/product.js  产品事实（提供 ${price} ${size} 等变量）
copy/issue.js             成稿文案（键 = "#<zone-id> > .t"）
css/
  fonts.css               @font-face（12 个 woff2，中立族名 Mag *）
  tokens.css              设计令牌出厂默认（纸色/墨色/字号级距/版面基准）
  typography.css          字体角色类 .fr-* ＋ 竖排 .v ＋ 行内强调
  layout.css              画布外壳 ＋ zone 原语 .z--* ＋ 叠图三态 ＋ 工具列
  variants.css            版式变体（母题/调色/相纸厚度；**不定义颜色**）
js/
  copy.js                 文案注入（只改直接文本节点）＋ 语言切换
  magazine.js             翻页 / 缩放 / 叠图三态 / 改字
  variants.js             版式变体引擎（seed → 可复现；seed 为空 = 零扰动）
  vendor/jquery-3.7.1.min.js
fonts/                    12 个 woff2（OFL，可随项目分发）
tools/                    31 个脚本 ＋ faces.json ＋ subject.json（见 ../references/03-toolchain-and-audit.md）
images/                   素材（README.md = 命名约定）
assets/ref/               参考图（含 _demo/ 示例；仅内部叠图比对，不随成品分发）
_shots/                   出图与审计产物（report/ = refcheck.json + skeleton.json + 三联图）
```

---

## 页面交互（人工复核）

| 按键 | 作用 |
|---|---|
| `←` `→` | 翻页 |
| `+` `−` | 缩放 |
| `0` | 适合视窗 |
| `O` | **叠图三态**：关 → 叠参考图 → 叠差异图（骨架级复刻的验收动作） |
| `V` | 换一版（随机变体 seed；只在用过 `--seed` 时才挂出按钮） |
| `E` | 直接改字（临时试文案，不改源文件） |
| `L` | 切 日本語 / 中文 对照 |
| `H` | 隐藏工具列 |

URL 参数：`?lang=jp` / `?lang=zh` 指定语言稿；`?copy=0` 关掉文案引擎看烘进去的原稿；
`?seed=<slug>` 启用版式变体；`?shot=1` 1:1 无工具列（`shoot.js` 用）。

---

## 环境依赖

| 依赖 | 用途 | 缺了怎么办 |
|---|---|---|
| Node.js ≥ 18 | `build.js`、`tools/*.js` | 装 Node |
| Google Chrome | 所有 CDP 脚本（出图/审计/字体自检） | 设 `CHROME_PATH` 环境变量指向你的 Chrome |
| Python 3 + Pillow | `check_faces.py` / `preview.py` / `grid.py` 等 | `pip install pillow` |
| Python 3 + OpenCV | `cutout.py` / `alphabox.py` | `pip install opencv-python numpy` |

**Chrome 路径**：默认 `C:\Program Files\Google\Chrome\Application\chrome.exe`，
可用环境变量 `CHROME_PATH` 覆盖，不必改脚本。
