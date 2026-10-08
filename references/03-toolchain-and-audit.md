# 03 · 工具链与判据

> 全套工具都在 `templates/tools/`。**共同原则：不靠肉眼，靠可复跑的脚本 + 退出码。**
> 一个判据如果不能给出「哪个元素、多少像素、超了多少」，它就不算判据，只能算印象。

---

## 一、工具全表

**解析阶段（Stage A，读参考图）**

| 脚本 | 干什么 | 用法 | 退出码 |
|---|---|---|---|
| `refscan.py` | **对参考图本身**做行/列边缘投影 → 候选带缝（`bandCuts`）、带内分栏（`columns`）、真实尺寸（`size`）；出叠线图与投影曲线 | `python tools/refscan.py [--ref p01.jpg] [--thresh .35] [--min-gap .02]` | 0 / 2 缺图 / 3 图过小或全白 |
| `refgrid.py` | 参考图的百分比坐标网 + 参考图↔成品叠图 + **差异热图** + 局部放大取证 | `python tools/refgrid.py p01.jpg [--shot page01] [--zoom 4 --crop x,y,w,h]` | 0 / 2 缺图 |
| `refcheck.py` | **硬断言**：H1 页数==参考图张数；H2 每页 canvas==参考图真实像素；H3 `ref` 非空存在 | `python tools/refcheck.py [--allow-missing-ref]` | **0 过 / 1 拦** / 2 缺 Pillow |
| `reffit.py` | **骨架吻合分**（告警级）：结构线召回 + 照片框 + 分块相似度 | `python tools/reffit.py [pageNN…] [--tol .015]` | 恒 0（除 IO 错 2） |
| `edgefit.py` | **参考结构线 ↔ layout 边框命中率**（告警级）：直接问「参考图的每条结构线，layout 的框线有没有落在它上面」。补 `reffit.py` 的盲区 —— 后者的 `plan` 分量走「空白谷」，看不见相邻区块之间的**边** | `python tools/edgefit.py [容差，默认 0.015]` | 恒 0 |
| `refdims.py` | **★十二维解析台账**（v2 起由八维扩来，见 `references/01 §二·附`）：①颜色/色调（**含四角背景基色**）②文字排版（**含块内纵向结构 + 货币写法**）③文字字体 ④文字颜色（**含对比角色**）⑤标签元素 ⑥遮盖块 ⑦模特动作（**含主体位置 + 四边接触率**）⑧重叠编排 ⑨**排列方式**（横/竖/斜/弧 + 弧度）⑩**遮挡关系** ⑪**卡内排版** ⑫**画面密度**。能算的给参考侧与成品侧实测值；不能算的（③字体真身、⑦参考侧主体位置、⑨⑩⑪参考侧）输出「去核对什么」并要求人工落字。`--check` 分「硬缺失（机器判）」与「待人工核对」两级，**manual 留空即未核对**。`--plate` 出色板 + 背景基色对照图；`--bg` 只看背景基色；**`--grid` 出 20×20 网格的参考/成品并排读图**（第 7 点的读图规程，见 `references/01 §9.2.2`）。
**人工读数落在 `assets/ref/_readings.json`**（与 `--write` 产物分开，否则每次 `--write` 都被抹掉），并按 `READING_SCHEMA` 校验键名与类型 —— **写错键名 = 写了但读不到**，`--check` 当场点名。
**⑦ 参考侧有污染闸门** `ref_mask_reliability()`：合成封面上 rembg 会把白卡并进主体（实测上半幅跨度 0.77、列投影无缺口、头心偏 0.2），一旦判定不可采信就改读人工读数。
**★`clean=True`（干净源：素材抠像 / `occlude` 掩膜）时闸门放宽到跨度 0.92 / 覆盖 0.85** —— 单张照片里根本没有「版面元素」，宽跨度只可能是构图本身（实测近景人像 0.678、0.706 被原 0.60 上限误判成污染，那两页的 ⑦ 因此**永远拿不到读数**）。
**★⑦ 的失败要拆因**（`frame_edges()` → `subj_verdict(frame=)`）：`cause=版面`（照片框本身缩在页内，把框拉到出血即可）／`cause=生图层`（框已出血，主体没填满画幅）。一律报「生图层」会让人去重生成照片，而真正的修法是改版面。
**★`shotKind`**（成品侧素材页类型，与参考侧 `pageKind` 对称）：素材侧没有人物主体时 ⑦ **没有定义** —— 判为不适用并单列进「**素材缺口**」清单（`_material_gap`），与「核对通过」是两行不同的话。 | `python tools/refdims.py [pageNN] [--write] [--check] [--plate] [--bg] [--grid]` | `--check` 有硬缺失 → 1 |
| `densitycheck.py` | **★画面密度 / 留白分布**（告警级，`_dens.py` 供算法）：「画面显得空」此前**没有任何一条判据能测**。把参考图与成品各切 3×3（可调 4×4）宫格，逐格算局部梯度能量占比，逐格对照，只报两类**单向**信号（参考忙、成品闲）：`dead cell`（参考 ≥ `--ref-hot` 且成品 ≤ `--dead`，**且该格元素覆盖率 < `--cover`**）与 `gap cell`（落差 > `--gap`）。**反向不报** —— 成品比参考密不是问题，报反向只会把人训练成无视告警。`--plate` 出逐格热力图。
**★第二条证据 `zone_coverage()`**：本项目素材是**淡彩商品图**（浅绿/浅紫文胸压浅灰底），局部梯度天然只有 0.9–2%，而参考刊那格是深色包袋 20–40% → 单靠梯度会把**被商品图完整占满**的格报成空档格，还建议「补一个该格该有的元素」—— 那条建议正是 Goodhart。故：梯度低 + 覆盖率 ≥ `--cover`（默认 10）→ **素材平坦格**（告警级，不阻断，含义是「低对比来自素材，不是排版漏了东西」）；覆盖也低 → 才是**空档格**（阻断级） | `python tools/densitycheck.py [pageNN] [--grid 3] [--gap 10] [--dead 2] [--cover 10] [--json] [--plate]` | 有空档格 → 1 / 只有偏空格或平坦格 → 0 |
| `_dens.py` | `densitycheck.py` 与 `refdims ⑫` **共用的同一份算法**（宫格梯度能量 + `zone_coverage` 元素覆盖率 + 逐格对照）。**⑫ 的两条入口必须同源** —— 曾出现 `densitycheck` 报「OK 无空档格」而 `refdims --check` 仍报 ⑫ 空档格（两套口径，报告自相矛盾）。不单独调用 | — | — |
| `_lay.py` | **解析后坐标读取层**：所有判据读 layout 一律走它（优先 `layout/_resolved.json`，回落读原文并打印警告）。**不这么做，带 `parent` 的页面（白卡内的子元素）会按「相对父框」的小坐标被算错位**，判据全假 | `_lay.load_zone_pages(ROOT)` / `box_px(b, W, H)` | — |
| `_cli.py` | **位置参数解析**：`_cli.positionals()` 只取**开头连续的非选项段**，遇第一个 `-` 开头 token 即停。★**不要用** `[a for a in sys.argv[1:] if not a.startswith("--")]` —— 它把**选项的值**也一并算成位置参数，后果分三档：① `herorecut.py a.jpg --mask-npy _work/x.npy` 里 `_work/x.npy` 落到 `dst` 上 → **PNG 覆盖 .npy 掩膜缓存**；② `--fit-touch "L=48,…"` 的值顶掉 `dst` → 工具自己打印的「复现命令」照着抄必然报错；③ `--out pages/x.png` 的值以 `page` 开头，被 `startswith("page")` 筛中当成页面筛选器 → **匹配不到任何页、判据静默空过**（最坏的一档：不报错、也没查）。本项目调用惯例是 `script.py <位置参数…> --选项…`，故「扫到第一个选项即停」无歧义，也不需要维护选项白名单 | `_cli.positionals()` | — |
| `_nest.py` | **把「绝对坐标的兄弟 zone」反算成 `parent` 嵌套**（⑪ 卡内排空的解药）。⑪ 判据靠 `parent` 字段判「卡里有没有排版」；而卡内元素写成同级绝对坐标时**画面上完全正确、肉眼看不出来**，判据只会报「空卡」。纯几何反算（`rel = [(ax−px)/pw, (ay−py)/ph, aw/pw, ah/ph]`），只改 `parent` 与 `box`，写回前自动备份到 `layout/_bak/`；父框带 `pad`/`border` 时**拒绝执行**（子坐标会偏移）。手算这个极易错位，而错位几个百分点在画面上仍然「看着对」 | `python tools/_nest.py layout/02.json blob-1 n1-pic n1-brand n1-p` ／ `python tools/_nest.py layout/03.json --group panel:child,child` | 0 / 1 |
| `herorecut.py` | **出血主体照的像素级重排版**（非生成式，纯像素运算）：取主体掩膜 → 平移 → **整片重铺背景基色** → alpha 合成；同一次运算吐对齐的遮挡掩膜。第 ①②⑦ 点（背景色/刊头被遮/主体偏左）在**素材层**的解法。
**★`--fit-touch "T=33,B=100,R=40"` 反解 scale/dx/dy**：让主体的四边接触率贴近参考刊读数，**硬约束与目标分离**（头部完整性 + 头心 x 锁死；越约束的解直接丢弃）—— 只优化接触率会解出 `scale=1.655` 四边全达标但**头已经没了**。搜索穷举后如实报残余，并给出「这是生图层、不是参数问题」的归属判断。
配套：`--head-x`（锁头心）、`--top-cut`（允许切发梢的比例）、`--pivot head\|bottom`（**缩放支点必须与搜索一致**，否则解出的参数与落地的画面不是同一张）。
**★已知边界**：`--fit-touch` 的扫描范围是 `scale ∈ [1.0, 2.2]`（**只放大**）。当参考刊的主体比本片**更小**（本片拍得比参考更近，正确解是缩小 + 下移）时，搜索表达不出来 —— 此时会报「无解」，而那句「无解」的措辞是「这张照片里没有能填满 X 的内容」，**不等于**「不存在可达的构图」。要区分这两种「无解」，把 `--check` 报的 before 四边与参考四边摆在一起看：若本片某条边**已经高于**参考（如 T 24% vs 参考 4%），那是「拍得太近」，属换画幅问题、不是搜索范围问题 | `python tools/herorecut.py <src> <dst> --dx F --dy F --scale F --pivot head --bg HEX\|--bg-from P --size WxH [--shrink N] [--feather N] [--emit-mask P] [--check] [--fit-touch "T=33,B=100,R=40"] [--head-x 0.35] [--top-cut 0.05]` | 0 / 1 |
| `subjectguard.py` | **实底小模块不许压模特/产品主体**（告警+硬拦分级）。掩膜＝rembg(u2net，本地已缓存，约 0.4s/张) → 腐蚀掉薄纱/肩带/发丝 → 只留躯干头部核心；白底产品图自动改走「四角底色连通域」通道（与 `cutout_flat.py` 同源）。**只判实底 kind**（badge/torn/bubble/panel/band 及带 `bg` 的文字），描边类与纯文字豁免。小模块 FAIL / 中模块 WARN / 大模块只报告。掩膜不可信且 `tools/subject.json` 未声明 → **报 SKIP，不报 OK**。**★底图是按 `z.src` 找的** —— 所以 `layout/_resolved.json` 必须保留 `src`。曾因 `build.js` 的字段白名单漏掉 `src`，判据的 `bases` 恒为空 → **9 页全部「无底图 → 本页不适用」，而合计仍报 `SKIP 0`**（空过且不自知；同一坑此前在 `refdims` 出现过一次，那次只修了 refdims）。修法：`build.js` 白名单补 `src`/`alt`，不适用页计入 `tot_skip` | `python tools/subjectguard.py [pageNN] [--erode 0.02] [--strict] [--detail] [--no-cache]` | 有 FAIL → 1 |
| `contrastcheck.py` | **文字压在照片上的对比度**（告警级）：用 layout 里声明的**字色令牌**（不是实测最暗像素——小字会被抗锯齿摊薄而误报）对实测**背景中位数**算 WCAG 对比度，另报 `spread`（底是否均匀）| `python tools/contrastcheck.py [pageNN…] [--body 4.5] [--big 3.0] [--bigsize 18] [--json]` | 恒 0 |
| `inkprobe.js`+`.html` | **字重墨迹探针**：数非白像素，判 `font-weight` 是否真生效 | `node tools/inkprobe.js` | 0 达标 / 1 不单调或增量不足 |
| `demo.js` | 出厂示例骨架的启用 / 关闭（示例隔离在 `_demo/`） | `node tools/demo.js [--enable\|--disable\|--status]` | 0 / 2 |
| `freeze.js` | **冻结导出**成独立专用 skill（自动生成 SKILL.md） | `node tools/freeze.js --name <slug> --out <dir> [--dry] [--ref-mode copy\|strip]` | 0 / 2 |

**渲染 / 审计阶段（Stage B）**

| 脚本 | 干什么 | 用法 | 退出码 |
|---|---|---|---|
| `build.js` | **引擎入口**：品牌包 + layout + 文案 → 整页 HTML + `slots.json` + `_data.js`。内含白名单校验与 H1/H2 硬断言 | `node build.js [--brief\|--check\|--page 03\|--prune [--yes]\|--seed <slug>]` | 0 通过 / 1 报错 |
| `shoot.js` | 精确出图（CDP，视口=画布尺寸） | `node tools/shoot.js [pageNN…] [--dsf 2] [--query "lang=zh"] [--tag zh] [--ui]` | 0 / 1 |
| `copycheck.js` | 文案五组 + 版面两组校验 | `node tools/copycheck.js [--lang zh\|--no-layout\|--json\|--hit 300]` | 0 全绿 / 1 有 FAIL |
| `fontcheck.js` | 问浏览器「实际用了哪个字体文件」 | `node tools/fontcheck.js [pageNN…] [--query "lang=zh"] [--want "Noto Serif"]` | 0 / 1 |
| `check-variant.js` | 变体引擎自检：无 seed 必须零扰动、同 seed 必须可复现 | `node tools/check-variant.js [--port 9411]` | 0 全过 / 1 有 FAIL / 2 |
| `prune.js` | 清理删页后残留的 `pageNN.html` / `_shots/pageNN*.png` | `node tools/prune.js [--yes]`（默认 dry-run） | 0 / 2 |
| `audit.js` | 量出每块的真实坐标/尺寸，算底部死白与纵向分布 | `node tools/audit.js [pageNN…] [--url-query "lang=zh"]` | 0 / 1（异常时） |
| `labelrects.js` | 导出「浮层标签 / 照片」的真实几何 → `_shots/_labels.json`。**★text 类（无背景色/无背景图/无边框）改用「墨迹框」**（所有后代文本节点 Range 的并集），有底色的 panel/tag/bubble/stamp 仍用元素框 —— zone 的 box 是**预留栏宽/行数**，文字没用满时拿元素框判「压脸」会**假 FAIL**（实测 page04「からだの形は、からだが決める。」墨迹 250×23 / 框 262×91，与 L-eye 假相交 4320px²）。每条标签带 `dbg` 字段记录「墨迹尺寸|元素框尺寸|是否用了墨迹」，可追溯。**★空数据即报错退出**（探针抛错时拒绝写出 `{}` —— 空 JSON 会让下游判据报「FAIL 0」的假绿） | `node tools/labelrects.js [pageNN…] [--url-query …]` | 0 / 1 |
| `check_faces.py` | 标签是否压到模特五官 | `python tools/check_faces.py [--strict]` | **FAIL 数**（0 才过） |
| `blockcheck.py` | 照片块是否互相压 | `python tools/blockcheck.py [--min 2000]` | **FAIL 数** |
| `alphabox.py` | 扫出产品图的真实内容区 → `images/_alphabox.json` | `python tools/alphabox.py [--alpha 8]` | 0 / 2 |
| `cutout.py` | 白底产品图 → 透明 PNG（纯 OpenCV） | `python tools/cutout.py`（改脚本里的路径） | —— |
| `cutout_flat.py` | **纯色平底**产品图 → 透明 PNG。先 `--probe` 判型：底色唯一值≈1 且标准差≈0 → 用本工具；否则回 `cutout.py`。`--check` 出生成り纸／深墨／中灰三底对照 | `python tools/cutout_flat.py --probe --src <图>` / `... --src <图> --out images/cut-01.png --check _shots/probe/cut-01.jpg` | `--probe` 恒 0 |
| `grid.py` | 给**已渲染的整页**叠 100px 坐标网（标定五官禁区用） | `python tools/grid.py page01` | —— |
| `probe.py` | 带坐标尺的局部放大裁切（读五官坐标 / 复核禁区框）。**★每次调用都写同一个 `_probe.jpg`，批量标定必须 `--out` 各自指定文件名，否则互相覆盖。****★`--zoom` 别用 1.0**：整页缩进屏幕后读不出「眼睛在第几行」，会整片读错坐标（踩过：把缩略图像素当画布坐标，裁了三次都裁到额头/耳朵）。用 1.5–2.5 倍裁五官区 | `python tools/probe.py page01:180,170,240,180 --zoom 2 --no-zones --out face_p01.jpg` | —— |
| `faces.py` | 肤色密度字符网格（辅助找人脸框） | `python tools/faces.py [pageNN] [--cell 64]` | —— |
| `faceguard.py` | 把照片区与标签逐块画框，出复核图 | `python tools/faceguard.py [pageNN]` | —— |
| `wmsheet.py` | 素材右下角对照拼图（目检第三方水印） | `python tools/wmsheet.py [--dir images] [--cols 6]` | 0 / 2 |
| `unwatermark.py` | 中值滤波差异法抹除水印（只动细笔画，不动产品轮廓） | `python tools/unwatermark.py <file> --win x0,y0,x1,y1 [--dry]` | 0 / 2 |
| `overlap.py` | 把所有「标签 ∩ 照片」的交叠区裁出来拼长图 | `python tools/overlap.py [--min 2000]` | —— |
| `preview.py` | 全部整页 → 一张总览图 | `python tools/preview.py [--tag zh] [--cell 500] [--cols 3]` | 0 / 2 |

> ⚠️ **`grid.py` / `probe.py` 只作用于已经渲染出来的 `_shots/pageNN.png`，它们量不了参考图。**
> 要量参考图用 `refscan.py`（结构）与 `refgrid.py`（坐标网 + 叠图）。这一条曾经在文档里写反过。

**Chrome 路径**：所有 CDP 脚本用 `process.env.CHROME_PATH`，缺省 `C:\Program Files\Google\Chrome\Application\chrome.exe`。
换机时若 Chrome 在别处，设环境变量即可，不改脚本。

---

## 二、标准运行顺序（照这个顺序，不要跳）

### Stage A · 定制（在母版副本里做，只在换参考图 / 换品牌时跑一次）

```
⓪ 素材进场就先查水印（不要等出完图才发现）
   python tools/wmsheet.py         # 右下角对照拼图 → 人眼逐格看有没有第三方标识
   python tools/unwatermark.py …   # 有就抹（中值滤波差异法），抹完再跑一次 wmsheet 复核
   # 漏了这一步的代价：水印会随派生裁切一路带进成品，返工要重裁 + 重出全部页面

① 解析参考图（★这一步不跑，整个 skill 就退化成「换个产品套同一套版」）
   python tools/refscan.py         # 候选带缝 / 分栏 / 真实尺寸 → assets/ref/_scan/
   python tools/refgrid.py p01.jpg # 百分比网校正 → assets/ref/_grid/
   → 照读数写 layout/NN.json（见 references/01 §二）

② python tools/refcheck.py         # 【硬门禁】页数 = 参考图张数；canvas = 参考图尺寸
                                   #   ← 不过就不要往下走
③ node build.js                    # 编译
   node build.js --brief           #   （可选）出 copy/_brief.md 字数预算 + copy/_skeleton.js 空壳

④ node tools/copycheck.js          # 文案五组 + 版面两组；退出码必须 0
⑤ node tools/shoot.js              # 试排，出图
⑥ python tools/reffit.py           # 骨架吻合分（告警）；不过关回 ① 改 box
⑦ node tools/demo.js --enable      # （只有在看示例时才跑；正式工作不要）
⑧ node tools/freeze.js --name <slug> --out <skillsDir>   # 冻结成独立专用 skill
   → 在新目录里跑 refcheck + build + copycheck，三条退出码 0 = 自包含
```

### Stage B · 出图（在冻结出的专用 skill 里做，每次换成品素材都跑）

```
① node build.js                    # 编译（默认保真；一物一版加 --seed <SKU名>）
② python tools/refcheck.py         # 【硬门禁】页数 / canvas 尺寸
③ node tools/copycheck.js          # 文案五组 + 版面两组；退出码必须 0
                                   #   ← 不过就不要进第 ④ 步
④ node tools/shoot.js              # 出图 → _shots/pageNN.png
⑤ node tools/labelrects.js         # 导出标签/照片几何
   python tools/check_faces.py     # FAIL 必须 0（标签不许压五官）
                                   #   ⚠️ 输出「禁区 0 块」= 空过、不是通过；有脸的页必须先标定 faces.json
   python tools/blockcheck.py      # FAIL 必须 0（照片块不许互压）
⑥ node tools/fontcheck.js          # 确认内嵌字体真的参与了绘制
   node tools/inkprobe.js          # 确认 font-weight 真的生效（字体文件对 ≠ 字重生效）
⑦ python tools/preview.py          # 总览拼图（目检版式有没有破）
   python tools/preview.py --tag zh
⑧ python tools/reffit.py           # 骨架吻合分（告警级，不阻断）
   python tools/edgefit.py          # 参考结构线 ↔ 边框命中率（更贴切的同级读数）
   python tools/contrastcheck.py    # 文字压在照片上的对比度（告警级）——
                                    #   有「字直接压在写真上」的页面才需要看
   python tools/densitycheck.py     # ★画面密度（空档格 → 退出码 1）——
                                    #   「画面显得空」只有这一条能量出来
   python tools/refdims.py --check  # ★十二维台账：硬缺失 → 退出码 1
                                    #   它才是「有没有按参考图做」的总账
⑨ node tools/prune.js              # 删页后清残留（默认 dry-run，确认了再加 --yes）
⑩ ★第 7 点（模特构图）的三步规程 —— 不要把「主体位置不对」当排版问题改：
   python tools/refdims.py pageNN --grid   # a) 出网格读图 → 人工读数写 _readings.json
   python tools/refdims.py pageNN --check  # b) 判据自动对表（头心 x ±0.06 / 触边率 ±15pp）
   python tools/herorecut.py <hero> --check --head-x <参考头心> \
       --fit-touch "T=..,B=..,R=.."        # c) 反解重裁；报「无解」= 回生图层重出，不是调参数
⑪ 逐页目检 _shots/pageNN.png       # 脚本查不出的东西只有眼睛能查：
                                   #   脸被浮层压住、构图裁到一半、取景落到空白处
```

**为什么 ② 必须在 ③ 之前**：`refcheck` 是**硬门禁**，页数或画布尺寸不符时，
后面所有审计都在错误的基线上跑——文案溢出、五官禁区、照片互压的坐标全是对着错的画布算的。

**为什么 Stage B ⑤ 必须在 ④ 之后**：`labelrects.js` 读的是**渲染后**的 DOM 几何（含旋转、缩放、字号回落的真实结果）。
在出图之前它量不到东西。

**为什么 ③ 必须在 ④ 之前**：不要在错误的版式上出图再回头改文案——出图很慢，且改动后所有审计都要重跑。

---

## 三、判据的设计意图（为什么是这几个）

### 3.1 `copycheck.js` —— 五组检查

| 组 | 查什么 | 为什么非要查 |
|---|---|---|
| **A 接口层** | 每个文案选择器命中**唯一 1 个**元素；无两个选择器撞同一元素 | 选择器写错会静默失效（写到别的元素上），页面上看不出来 |
| **B 注入层** | 值个数 == 直接文本节点个数；jp / zh 都齐 | 数量不符 → 引擎「跳过不猜」，那个槽位会留着占位文字 |
| **C 覆盖层** | `slots.json` 里每个槽位都被本期文案写到 | 漏写会留下「原刊占位文本」——**这是合规事故**（原刊文字不许留） |
| **D 合规层** | 渲染后正文无 `forbidden` 词；Slogan 按 `mustPair` 配平 | JS 拼接出来的词只有渲染后才存在 |
| **E 版面层** | ① 静态：文字框互压（直接用 layout JSON 算）<br>② 动态：渲染后无溢出、无出画布 | 溢出 / 出画布 / 互压是「看得见但不一定注意到」的错误 |

**E① 为什么用 layout JSON 直接算，不走浏览器**：编译期就能查，不用起 Chrome，
所以改 layout 时能秒级反馈。阈值 `--hit`（默认 200px²）可调；
确有设计需要的互压，给那个 zone 加 `"overlapOK": true` 豁免（**要写进注释说明为什么**）。

**E② 溢出判定的关键前提**：
`.z--text > .t { height: 100%; }`（见 `css/layout.css`）。
没有这一条，`.t` 的高度是内容高度，`scrollHeight > clientHeight` 永远为假 → 溢出测不出来。
带 `valign` 的框用 `height: auto`（它靠 flex 居中，不能撑满）。
**这两行不要改。**

### 3.2 `check_faces.py` —— 只框五官，不框整张脸

- **两层判定**：`FAIL` = 与禁区相交面积 > `min_area`（默认 300px²，在 `faces.json` 里配）；
  `WARN` = 与禁区外扩 `pad`（默认 40px）的缓冲区相交。**退出码只由 FAIL 决定。**
- **为什么只框眼/鼻/口**：杂志版式本来就会让署名/标签压过发际、脸颊、下巴，那是设计语汇。
  真正不能碰的是五官。框太大 → 规则永远为假 → 判据失去意义。
- **圆按内切椭圆算**：`.stamp` 之类是 `border-radius:50% + rotate`，
  `getBoundingClientRect()` 给外接方框，真正着色的地方只占 ~78% 面积。
  按方框算会假报。所以 `labelrects.js` 输出 `rnd` 标记，`check_faces.py` 对内切椭圆做亚采样求交。
- **⚠️ `faces.json` 为空 = 判据没生效，不是判据通过。** 输出的 `禁区 0 块 / FAIL 0` 是「空过」。
  **凡页面里有模特脸的，必须标定。** 标定流程：
  ① `python tools/faces.py` 出肤色密度格网 → 定位候选人脸框（注意：**肤色块不是脸**，
  胸口/手臂/颈侧都会被标出来，别照抄）；
  ② 把候选框裁出来放大、叠网格读坐标（`_work/faces_probe.py` 是可直接复用的版本）；
  ③ **只框眼/鼻/口**，填进 `tools/faces.json` 的 `pages.<pageNN>`；
  ④ 跑 `check_faces.py`，并用 `_shots/guard/<page>_faces.png` **目检红框是否真的落在五官上**
  （框偏了 = 判据在保护错误的地方，且不会报错）。
  脸被图片框边缘裁掉一半时，只标**可见的那部分**五官。

### 3.3 `blockcheck.py` —— 用真实四角，不用外接方框

- 版式里大量元素带 `rotate`。两个各转 ±8° 的矩形，**外接方框可能大面积相交，实际着色像素却分得开**。
  拿方框判必然假报 → 判据失效。
- 所以 `labelrects.js` 额外导出 `quad`（**累积了自身与全部祖先旋转**的四角），
  `blockcheck.py` 做**凸四边形精确求交**（Sutherland–Hodgman）。
- **父子关系不算互压**（`.c01` 白卡包含 `.p`，属包含关系）。
- **出血大图（`is-bleed`）不算互压**。它是**背景层**——封面／跨页天然会让白卡、色卡、标签压在它上面，
  那是版式语汇。`labelrects.js` 把这类元素单列为 `bleed-block`（不是 `photo-block`），
  `blockcheck` 因此不会把它算进组合。**没有这一条，每个带出血大图的封面都会假报 FAIL**，
  然后你会开始调 `--min` 把阈值抬到失效——那是把判据废掉，不是通过判据。
  判据只管「两张**并置**的照片是否互相压住」。
- 阈值 `--min`（默认 2000px²）——比 `check_faces` 的 300 大，
  因为「两张照片叠一起」比「标签碰到脸」需要更大的交叠才算问题。

### 3.4 `fontcheck.js` —— 唯一能证伪「字体其实回落了」的工具

- computed style 里的 `font-family` 只是**愿望清单**，浏览器可以一路回落。
  本机没有某个字体时，会 quietly 落到 SimSun / Yu Gothic —— **它们也能渲染，页面上看不出坏了**，
  只是字面宽度与顿挫全变，而版面回归测不出来（它只看几何）。
- 只有 `CSS.getPlatformFontsForNode` 会告诉你**真正参与绘制的字体**与 glyph 数。
- 判据：某个字体角色**只用到了系统字体** → FAIL。
  `--want` 匹配的是**字体文件内部名**（Chrome 报的），不是 `@font-face` 里的中立族名，
  所以别写 `--want "Mag "`（一定 FAIL）。默认判据已够用。
- **已知中文字形切换**：`<html lang>` 为 `ja` 时走 JP 字形，`zh-Hant` 时走 SC 字形。
  `js/copy.js` 一定会设这个属性（即使文案引擎被关掉），因为字形宽度会影响行高与溢出。

### 3.5 `refcheck` / `reffit` —— 复刻度判据的两级设计（★为什么要分两级）

复刻度不是「像不像」这种审美判断，它可以被拆成**事实判断**与**程度判断**两层：

| 级别 | 判据 | 内容 | 不达标时 |
|---|---|---|---|
| **硬断言** | `refcheck.py` H1 / H2 / H3 | 页数 == 参考图张数；每页 `canvas` == 该页参考图真实像素；`ref` 非空且文件存在 | **退出码 1，阻断**。不要出图，不要加容忍度 |
| **告警级** | `reffit.py` 吻合分 + `refgrid.py` 差异热图 | 结构线召回率 / 照片框贴合 / 分块相似度；差异图上有没有成片高热区 | 打印分数与**缺失的具体位置**，**不阻断** |

**为什么 H1/H2 必须硬拦**：

- 页数 ≠ 张数 → 有页没解析参考图，它一定是「凭空编出来的版」，交付时混在中间看不出来；
- `canvas` ≠ 参考图真实尺寸 → 叠图从一开始就是缩放后对拍，**你看到的「基本重合」是假的**。
  这一条曾经没有任何判据管，是最隐蔽的坑。

**H1/H2 在 `build.js` 里也有一份**（编译期就拦，与 `refcheck.py` 同口径），
所以 `node build.js` 与 `python tools/refcheck.py` 会给出同样的结论。
`assets/ref/_stripped` 标记存在时（`freeze.js --ref-mode strip` 写入）两条都自动降级。

**为什么吻合分不硬拦**：「骨架级复刻」本来就允许差异——尺寸随素材自适应、文字重写、
颜色跟品牌。硬拦一个连续量只会逼人调阈值，最后把判据废掉（`blockcheck` 那一节讲过同样的道理）。

**吻合分怎么读**：

```
WARN page05 骨架吻合分 0.49  = 0.35·计划 0.42 + 0.35·渲染 0.42 + 0.15·照片框 0.40 + 0.15·相似度 0.90
      渲染（成品页上的内容带） 缺这几条横缝：22.6%、62.0%
```

- 四项分量：**计划**（layout 的框 vs 参考图结构线）、**渲染**（成品页自己 vs 参考图结构线）、
  **照片框**（image/cutout/mask/logo 的四边是否贴在参考图边缘上）、**相似度**（6×6 分块灰度）。
- 「计划低而渲染高」= JSON 写对了但页面没照做（素材错位、整页偏移）；
  「渲染低而相似度高」= **内容换了、骨架没跟上** —— 正是本引擎过去被反馈的那个毛病。
- 三种非正常读数，**不代表「没按参考图做」**：
  - `弱` = 参考图结构线少于 5 条（照片主导页），照出分但不计入「连续偏低」告警；
  - `N/A` = 一条结构线都取不到，直接不出分；
  - 这两种情况请人工看 `_shots/report/<page>_skeleton.png` 的**第三联**（青 = 参考图边缘，红 = 你的框）。

### 3.6 `inkprobe.js` —— 唯一能证伪「字重其实没生效」的工具

`fontcheck.js` 回答的是「用了哪个字体**文件**」；它答不了「`font-weight:700` 有没有真的变粗」——
可变字体（variable font）在权重轴上没有变化时，两个权重会渲染成一样粗细，
而 `fontcheck` 只会说「命中了内嵌字体」，一切正常。

`inkprobe.js` 的做法很直接：用 canvas 把同一串字按不同 `font-weight` 画出来，
数**非白像素占比**（墨量）。

- 判据：同族 `ink%` 必须随字重**单调不减**，且 `ink(700) − ink(400) ≥ DELTA_MIN`（默认 0.5 个百分点）。
- 实测基线（`Mag Mincho JP` 400/700/900）：`9.63% → 14.91% → 17.45%`；`Mag Mincho SC`：`6.47% → 9.85% → 11.67%`。
- 阈值写成常量，**改品牌字体后先跑一次看基线，再决定要不要调**。

---

## 四、故障处置（照着查）

| 症状 | 最可能的原因 | 怎么修 |
|---|---|---|
| `build.js` 退出 1：「文案给 N 个值，版式有 M 个文本节点」 | `tpl` 里 `${n}` 个数与 `issue.js` 数组长度不符 | 数 `tpl` 里的 `${}`，或检查 `<b>`/`<span>` 是不是把文本包进了子元素 |
| `build.js` 退出 1：「正表记稿出现禁用词」 | 文案里用了 `forbidden` 里的词 | 改写；**不要**去删 `forbidden` 里的词 |
| `build.js` 提示「图片不存在 → images/xxx.jpg」 | 素材还没放，或文件名不符 | 按 `images/README.md` 的固定名放进去 |
| `copycheck` FAIL「选择器命中 0/2 个元素」 | zone id 改了但文案键没同步 | 同步 `copy/slots.json`（重跑 `build.js`）与 `issue.js` 的键 |
| `copycheck` FAIL「漏写槽位」 | `issue.js` 缺这个槽位 | 补上；**漏写会留下原刊占位文本** |
| `copycheck` FAIL「两个选择器撞同一元素」 | 两个 zone 共用 `.t`，或选择器写得过宽 | 改成 `#<id> > .t` 的精确形态 |
| `copycheck` FAIL「纵向溢出：内容 112px > 框 96px」 | 框高不够，或字数超预算 | 改 `layout` 的 `box[3]`，或按 `--brief` 的字数预算缩文案 |
| `copycheck` FAIL「文字框互压」 | 两个文字 zone 的 box 相交 > `--hit` | 挪坐标；确属设计需要则加 `"overlapOK": true` |
| `check_faces` FAIL | 标签压到五官 | 挪标签或让照片让位；**或标示定不准**（换了模特图没重标） |
| `check_faces` 一直假报 | 换了模特图但 `faces.json` 还是旧坐标 | 按 `faces.json` 的 `_doc` 重标：`grid.py` → `probe.py` → 填坐标 |
| `blockcheck` FAIL | 两张照片真的叠了 | 改 box；**或没跑 `alphabox.py`** |
| `blockcheck` 一直假报 | 透明边界未登记 | `python tools/alphabox.py` |
| `fontcheck` FAIL | `@font-face` 没加载 / `fonts/` 缺文件 / 品牌包 fonts 段首选项写错 | 三处查（工具的 FAIL 提示里已列出） |
| `shoot.js` 出的图比预期小/偏移 | 用了 `chrome --screenshot` 而不是 `shoot.js` | **只能用 `shoot.js`**（见下） |
| `copycheck` 报「请求 lang=zh，页面实际渲染 lang=jp」 | 页面 lang 没被切 | 检查 `js/copy.js` 是否加载、`_data.js` 是否在它之前 |
| `preview.py` 报「_shots/ 里没有找到整页渲染」 | 还没出图 | 先 `node tools/shoot.js` |
| `build.js` 退出 2：「layout/ 里没有版式 JSON（页数 = 参考图张数）」 | **出厂状态就是这样**（示例隔离在 `_demo/`） | 放自己的参考图并解析（`references/01` §二）；只是想看示例就跑 `node tools/demo.js --enable` |
| `build.js` 退出 1：「未知 kind「xxx」」 | `kind` 写成不在白名单里的值 | 照 `references/01` §四 的 12 个 kind 改。**以前会静默画一个空 div，现在会拦** |
| `build.js` 退出 1：「未知字体角色「xxx」」 | `style.font` 写错，或写了字体名而不是角色名 | 只能写 `serif`/`sans`/`script`/`script-fat`/`latin`/`latin-ital` |
| `build.js` 退出 1：「H1 页数 ≠ 参考图张数」 | `layout/*.json` 个数与 `assets/ref/` 顶层图张数不一致 | 补/删一个；示例参照图放 `assets/ref/_demo/` |
| `build.js` 退出 1：「H2 canvas ≠ 参考图真实尺寸」 | `canvas` 抄错了，或换了参考图没改 canvas | 改成参考图真实像素（`refscan` 的 `size` 字段直接给） |
| `refcheck.py` 退出 1（同上两条） | 与 build 同源 | 同上。**不要加容忍度** |
| `refcheck.py` 输出 `WARN 参考图已剥离` | 这是 `freeze --ref-mode strip` 的产物 | 正常；若要恢复叠图，用 `--ref-mode copy` 重新冻结 |
| `reffit.py` 输出 `弱` / `N/A` | 参考图是照片主导，投影取不到结构线 | 正常，不是「没按参考图做」；人工看第三联 |
| `reffit.py` 吻合分低且指名「缺这几条横缝 22.6%、62.0%」 | 版式的带边界没落在参考图的缝上 | 照数字改 `box` 的 `y`/`h`；**先确认自己是照 refscan 读数写的**，不是估的 |
| `inkprobe.js` 退出 1「字重不单调 / 增量不足」 | 该字体在权重轴上没有变化 | 换字体，或把该字重的用法改掉（多半是「标称 bold 实际不变粗」） |
| `check-variant.js` FAIL「无 seed 却已扰动」 | 变体引擎在 seed 为空时也动了页面 | **这是保真性破坏**，必须修 `js/variants.js` 的 seed 判断 |
| `check-variant.js` FAIL「同 seed 两次不一致」 | 用了 `Math.random()` 而非 seed 派生的伪随机 | 检查 `mulberry32` 的接法 |
| `demo.js` 报「找不到 layout/_demo/」 | 这份副本没有出厂示例（已被 `--disable` 或从冻结产物里剔除） | 正常，不影响正式工作 |
| `freeze.js` 报「找不到母版 brand-magazine」 | 母版不在默认位置 | 用 `--src <母版根>` 或设环境变量 `MAGAZINE_SRC` |
| `prune.js` / `build.js --prune` 列出想删的文件 | 默认是 dry-run | 确认清单没问题再加 `--yes` |

### 出图为什么必须是 `shoot.js`

`chrome --screenshot` 会受「适合视窗」缩放影响——实测 1366×1748 的画布被缩到 **0.9216 倍**并偏移 **83px**。
后期若按坐标裁切/叠图必然错位。
`shoot.js` 用 `Emulation.setDeviceMetricsOverride` 把视口**精确设成该页画布尺寸**，
配合页面的 `?shot=1`（1:1、无工具列），得到像素级准确的 PNG。

另外 `shoot.js` 在量尺寸前会**先关掉 transition 再清 transform**——
否则会量到动画中间值（同样的坑：先出图后才发现位置不对）。

---

## 五、页面交互（人工复核用）

| 按键 | 作用 |
|---|---|
| `←` `→` | 翻页 |
| `+` `−` | 缩放 |
| `0` | 适合视窗 |
| `O` | **叠图三态循环**：关 → 叠参考图（multiply 半透明）→ 叠差异图（screen 发光）—— 骨架级复刻的验收动作 |
| `V` | 换一版（随机抽一个变体 seed；只在用过 `--seed` 时才挂出这个按钮） |
| `E` | 直接改字（临时试文案，**不改源文件**） |
| `L` | 切 日本語 / 中文 对照 |
| `H` | 隐藏工具列 |

三种叠图的读法：**叠参考图**看分区边界对不对得上；**叠差异图**看哪里漏排了
（成片高热区 = 真偏差，零散亮点 = 材质差异，可忽略）。
差异图由 `python tools/refgrid.py <ref> --shot <pageNN>` 生成；**没跑过就只有两态**。

URL 参数：

| 参数 | 作用 |
|---|---|
| `?lang=jp` / `?lang=zh` | 指定语言稿 |
| `?copy=0` | **关掉文案引擎**，看 build 时烘进去的正表记原稿（用来判断「是文案问题还是版式问题」） |
| `?seed=<slug>` | 启用版式变体（同 seed 同结果；建议直接写 SKU 名） |
| `?shot=1` | 1:1、无工具列（`shoot.js` 用） |

---

## 六、加页 / 减页 / 换画布

因为所有工具都从 `layout/*.json` 读页列表，所以：

| 要做什么 | 怎么做 |
|---|---|
| 加一页 | 放一个新的 `layout/NN.json` → 重跑 ②–⑥。**不用改任何脚本。** |
| 减一页 | 删掉对应的 `layout/NN.json`（或改名以 `_` 开头，build 会跳过） |
| 某页换画布尺寸 | 只改那一页的 `canvas.w` / `canvas.h`。其余页不受影响。 |
| 换参考图 | 换 `assets/ref/` 的图 + 更新 `layout` 的 `ref` 字段，然后**用 `refscan.py` 重新解析 box**（不要照抄旧的） |

**临时文件**：`layout/` 里 `_` 开头的 JSON 会被跳过，可以放草稿。
**示例隔离**：`layout/_demo/` 与 `assets/ref/_demo/` 同样以 `_` 开头，所以
`build.js` / `copycheck.js` / `shoot.js` / `refcheck.py` / `reffit.py` 一律不计入。
启用/撤下用 `node tools/demo.js --enable|--disable`。

---

## 七、交付前检查（一条命令跑完）

```bash
node build.js && \
python tools/refcheck.py && \
node tools/copycheck.js && \
node tools/shoot.js && \
node tools/labelrects.js && \
python tools/check_faces.py && \
python tools/blockcheck.py && \
node tools/fontcheck.js && \
node tools/inkprobe.js && \
python tools/preview.py && \
python tools/reffit.py
```

`&&` 链会在第一个非 0 退出码处停下。**跑通这一条，就是可以交付的状态。**
（`reffit.py` 恒退出 0，放最后；它的分数是给自己看的，不阻断交付。）
