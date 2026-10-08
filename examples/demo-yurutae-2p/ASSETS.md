# 素材台账 · 内衣 3 件套 · yurutae-ooo-01（2 页示例）

> 这是**填好的样例**。照这个格式把 `references/04-asset-ledger.md` 的模板填成你自己项目根的 `ASSETS.md`。
>
> - 品牌包：`brand/brand-pack.json`（brandId: `yurutae`）
> - 期号：`yurutae-ooo-01`
> - 页数：2（= 参考图张数）
> - 登记日期：2026-09-30

---

## 一、参考图（ref）—— 仅内部叠图比对，不随成品分发

| 文件 | 角色 | 来源 | 尺寸 | hash | 授权/合规 | 分发范围 | 登记日期 |
|---|---|---|---|---|---|---|---|
| assets/ref/p01.jpg | ref | 采集（女性杂志跨页） | 1366×1748 | `73ac124e937a` | 仅作版式参考；**未复制其中任何原始文字或图像** | 仅内部比对 | 2026-09-30 |
| assets/ref/p05.jpg | ref | 采集（女性杂志跨页） | 1366×1748 | `18d53ac59fa5` | 同上 | 仅内部比对 | 2026-09-30 |

> 交付时 `assets/ref/` 可整个不带。页面按 `O` 键才显示叠图层。

## 二、产品图与拍摄图

| 文件 | 角色 | 来源 | 尺寸 | hash | 授权/合规 | 分发范围 | 登记日期 |
|---|---|---|---|---|---|---|---|
| images/p01-hero.jpg | hero | 拍摄 | 1024×1406 | `86db07e76ea8` | 自有素材 | 成品内 | 2026-09-30 |
| images/step-1.jpg | step | 产品细节图 | 300×260 | `fd8e8e0ffd69` | 自有素材 | 成品内 | 2026-09-30 |
| images/step-2.jpg | step | 产品细节图 | 160×124 | `bd66eaf3962e` | 自有素材 | 成品内 | 2026-09-30 |
| images/step-3.jpg | step | 产品细节图 | 228×252 | `518da6a9c27c` | 自有素材 | 成品内 | 2026-09-30 |
| images/step-4.jpg | step | 产品细节图 | 230×150 | `ce6469aba95a` | 自有素材 | 成品内 | 2026-09-30 |
| images/p05-plate-a.jpg | plate | 产品图（抠底后压白底） | 1200×1200 | `912799deea9f` | 自有素材 | 成品内 | 2026-09-30 |
| images/p05-plate-b.jpg | plate | 产品图（抠底后压白底） | 1200×1200 | `2abd99a37437` | 自有素材 | 成品内 | 2026-09-30 |
| images/detail-cup.png | detail | 产品细节（上杯） | 300×260 | `4a50635b8afd` | 自有素材 | 成品内 | 2026-09-30 |
| images/detail-bow.png | detail | 产品细节（中桥） | 160×124 | `1e5aa92ff87a` | 自有素材 | 成品内 | 2026-09-30 |
| images/detail-strap.png | detail | 产品细节（肩带） | 228×252 | `f6d8935d1f53` | 自有素材 | 成品内 | 2026-09-30 |
| images/detail-wing.png | detail | 产品细节（侧翼） | 230×150 | `7512e23bf541` | 自有素材 | 成品内 | 2026-09-30 |
| images/detail-mesh.png | detail | 产品细节（网纱） | 238×184 | `699f329bf536` | 自有素材 | 成品内 | 2026-09-30 |

> **已知不足（如实记录）**：`step-2.jpg`（160×124）在版面里被放大到约 309×311，约 1.9 倍，
> 属轻微放大。其余 step 图放大约 1.0–1.4 倍，可接受。
> **下一步**：补拍/索取 ≥ 800px 的细节图替换。

## 三、AI 生成图

| 文件 | 角色 | 工具 | prompt 摘要 | 尺寸 | hash | 分发范围 | 登记日期 |
|---|---|---|---|---|---|---|---|
| （本次无） | | | | | | | |

> **AI 生成的事实必须在此备案。**
> 备案 ≠ 对外标识：本项目按品牌决定，页面上**不写**「AI 生成」字样；
> 但台账必须如实记录生成过程（**事实记录 ≠ 对外标识**）。

## 四、字体（fonts）

| 文件 | 字体名 | 授权 | 商用 | 用途 |
|---|---|---|---|---|
| fonts/noto-serif-jp-japanese-400/700/900-normal.woff2 | Noto Serif JP | OFL | ✔ | 明朝体（日文稿） |
| fonts/noto-serif-sc-chinese-simplified-400/700/900-normal.woff2 | Noto Serif SC | OFL | ✔ | 明朝体（中文稿字形） |
| fonts/noto-sans-jp-japanese-400/700-normal.woff2 | Noto Sans JP | OFL | ✔ | 黑体（说明文） |
| fonts/pinyon-script-latin-400-normal.woff2 | Pinyon Script | OFL | ✔ | 细铜版手写 |
| fonts/great-vibes-latin-400-normal.woff2 | Great Vibes | OFL | ✔ | 粗手写 |
| fonts/playfair-display-latin-400-normal.woff2 | Playfair Display | OFL | ✔ | 拉丁字标（Didot 系） |
| fonts/cormorant-garamond-latin-400-italic.woff2 | Cormorant Garamond Italic | OFL | ✔ | 拉丁斜体 |

> 全部 OFL，**可随项目分发**。字体文件随包带走 → 出图稳定、换机不变形。
> `node tools/fontcheck.js` 已确认 7 个探测点**全部命中内嵌字体**（无系统回退）。

## 五、字体替代映射（「尽量保留原刊文字样式」的凭据）

来源：品牌包 `fontMap`。

| 角色 | 原刊字体 | 替代字体 | 相似点 | 差异 | 为什么可接受 |
|---|---|---|---|---|---|
| serif | 参考刊标题明朝体（商用版权字体） | Noto Serif JP / SC（中立族名 `Mag Mincho JP/SC`） | 同为高对比明朝体，字面宽度接近，顿挫方向一致 | 顿挫略钝、字面稍宽 | OFL 可商用，规避字体版权；版式字号已按替代品字面宽度回归过 |
| script | 参考刊 copperplate 细手写 | Pinyon Script（`Mag Script Silk`） | 同为笔画如丝线的 copperplate 系，倾斜角接近 | 连笔更规整 | 同族气质；细线在小字号下清晰度够 |
| scriptFat | 参考刊装饰性粗手写 | Great Vibes（`Mag Script Ribbon`） | 笔画丰满、对比强 | 起笔装饰更多 | 浅底上仍清晰；细线体会看不清 |
| latin | 参考刊大写字标（Didot 系） | Playfair Display（`Mag Editorial`） | 同为高对比 Didot 系衬线，大写字标观感一致 | x-height 略高 | 大写字标（Step / NEWS / 页码）级别下差异不可辨 |
| latinItal | 参考刊斜体字标 | Cormorant Garamond Italic | 同为高对比斜体衬线 | 字面更窄 | 只用于 `Step` 一词，观感一致 |

## 六、合规声明

| 项 | 状态 |
|---|---|
| 页面署名 | 仅品牌包 `signature.primary`（`下着の作家` / 中文稿 `内衣作家`）；**页面无任何真实人名** |
| 第三方品牌 | 仅品牌侧提供的品牌（由良妙 / YURUTAE）；`forbidden.brands` 保留旧品牌检测词供编译期兜底 |
| 价格 | ¥1,950（默认值，用户未提供） |
| 效果承诺词 | 已通过 `forbidden.claims` **编译期 + 渲染后**双层拦截，命中 0 |
| 产地表述 | **未确认 → 不写**（页面无「日本製」等字样） |
| 促销标签 | 无 |
| 参考刊原文 | 已全部重写为品牌语气；`copycheck` C 组确认无漏写槽位（**漏写会留下原刊占位文本**） |
| **待人工过目** | 涉及**署名、表示者名、景表法边界**的最终判断，须由**日本行政書士／弁理士**过一遍 |

## 七、复核清单

- [x] 每个素材都登记了来源与 hash
- [x] 参考图标注为「仅内部比对」，不随成品分发
- [x] 无 AI 生成图（本次）
- [x] 字体授权与商用性已确认（全部 OFL）
- [x] `fontMap` 的每条都有「相似点 + 差异」
- [x] 无真实人名、无未确认第三方品牌
- [x] 促销信息无（无可图标化项）
- [x] 价格与产品信息一致（默认 ¥1,950）
- [x] `step-2.jpg` 分辨率不足已如实记录

## 八、本次判据结果（可复跑）

```
node build.js               → 2 页 / 45 个槽位
node tools/copycheck.js     → 4 次文案校验 + 2 组版面检查，全部通过（退出码 0）
node tools/labelrects.js    → page01 照片 5 / 标签 22；page05 照片 2 / 标签 35
python tools/check_faces.py → 合计 FAIL 0 / WARN 0
python tools/blockcheck.py  → 合计 FAIL 0 / WARN 0
node tools/fontcheck.js     → 7 个探测点全部命中内嵌字体（退出码 0）
python tools/preview.py     → preview-pages.jpg（2 页）
```
