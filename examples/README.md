# examples/ —— 真实产出样张

这里的图是**引擎的实际输出**，不是示意图。用来看「成品应该长什么样」，
也用来在你自己的产出「感觉不对」时做对照。

---

## demo-yurutae-2p/ —— 2 页示例

| 项 | 值 |
|---|---|
| 品牌包 | `brand/brand-pack.json`（brandId: `yurutae`，由良妙 ゆらたえ） |
| 产品 | 内衣 3 件套 |
| 参考图 | 2 张（`assets/ref/p01.jpg`、`assets/ref/p05.jpg`） |
| 页数 | **2**（= 参考图张数） |
| 画布 | 1366 × 1748（逐页取自各自参考图） |
| 版式 | page01 = 出血人像 ＋ 竖排句 ＋ Step 四格；page05 = NEWS 双栏 ＋ 撕纸标签 ＋ 细节圆 ＋ 实底双照 |
| 品牌语气 | 主语是物、不写体感、不写效果承诺；全页无真实人名、无第三方品牌 |

### 文件

| 文件 | 说明 |
|---|---|
| `page01.png` / `page05.png` | 正表记稿（日文）整页图，1366×1748 |
| `page01_zh.png` / `page05_zh.png` | 中文对照稿（同版式，文案换中文） |
| `preview-pages.jpg` | 正表记稿总览拼图 |
| `preview-pages_zh.jpg` | 中文对照稿总览拼图 |
| `ASSETS.md` | 本次的素材台账（**填好的样例**，照它填你自己的） |

### 这次运行的全部判据结果

```
node build.js              → 2 页 / 45 个文案槽位
node tools/copycheck.js    → 4 次文案校验（jp+zh × 2 页）+ 2 组版面检查，全部通过（退出码 0）
node tools/shoot.js        → page01.png / page05.png，均 1366×1748
node tools/labelrects.js   → page01 照片 5 / 标签 22；page05 照片 2 / 标签 35
python tools/check_faces.py → FAIL 0  WARN 0
python tools/blockcheck.py  → FAIL 0  WARN 0
node tools/fontcheck.js     → 7 个探测点全部命中内嵌字体（Noto Serif JP / Noto Sans JP / Playfair Display / Cormorant Garamond）
python tools/preview.py     → preview-pages.jpg（2 页）
```

### 复现方式

```bash
cp -r ../templates ./repro && cd ./repro
node build.js && node tools/copycheck.js
node tools/shoot.js && python tools/preview.py
```

`templates/` 里带的示例素材就是产出这些图的那一批，所以**开箱即可复现**。

---

## 看图时注意什么

1. **page01 的骨架**：出血人像占上 65%，四个特大白字编号「1 2 3 4」压在人像下缘，
   Step 词用拉丁斜体白字，四格等比排在下方，每格「图 → 粗黑小标 → 细黑说明」。
   —— 这是「骨架级复刻」的样子：分区比例与层级跟参考图，内容全是自己的。
2. **page05 的骨架**：三段式刊头（明朝大字 + 小字）＋ 撕纸大标 ＋ 5 个细节圆 ＋ 两张实底照
   ＋ NEWS 双栏 ＋ 八块引线标注 ＋ 页脚。
3. **文字样式**：明朝体走 serif 角色、说明文走 sans、编号与 Step 走 latin 系列、
   手写体走 script —— 原刊的字体用不了（版权）时，用**气质同族**的替代字体，
   替代理由逐条写在 `ASSETS.md` 的「字体替代映射」里。
4. **颜色**：纸底与强调色来自品牌包 `palette`，不是参考图的颜色。
   —— 这就是「气质跟原刊、颜色跟品牌」的分工。

---

## 加自己的样张

产出一套满意的图后，复制到 `examples/<你自己的目录名>/`，
并把那一轮的 `ASSETS.md` 一起放进来。**样张是给未来自己看的说明书。**
