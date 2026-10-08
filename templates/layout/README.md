# layout/ —— 版式骨架（Stage A 的产出）

**这个目录里有多少个 `*.json`，这本杂志就有多少页。** 页数 = 参考图张数 = `assets/ref/` 顶层图的张数。
`_` 开头的文件与子目录一律被跳过（`build.js` / `copycheck.js` / `shoot.js` / `refcheck.py` / `reffit.py` 同口径）。

---

## 现在这里是空的，这是**故意的**

```
layout/
  README.md     ← 你在这里
  _demo/        ← 出厂示例骨架（01.json / 05.json），引擎不计入
```

顶层没有版式 JSON 时：

```bash
$ node build.js
✗ layout/ 里没有版式 JSON（页数 = 参考图张数）        # 退出码 2
```

**这不是故障，是设计。** 这个引擎的存在理由是「把你的参考图的排版复现出来」。
出厂预置现成骨架会让人一路 `cp` → `build` → `shoot` 拿到「看起来像样」的图，
**全程零报错地跳过解析参考图**——那正是它过去的毛病。

想看示例：`node tools/demo.js --enable`（撤下：`--disable`；查状态：`--status`）。

---

## 新增一页：三步

```bash
# ① 把参考图放进 assets/ref/（一张图 = 一页，原始分辨率，别用缩过的小图）
#    文件名随意，但要写进 layout 的 ref 字段

# ② 让工具先读它 —— 不要用眼睛估
python tools/refscan.py                 # → assets/ref/_scan/<name>.json  + .bands.png / .profile.png
python tools/refgrid.py <ref>           # → assets/ref/_grid/<name>_grid.png（百分比坐标网）
python tools/refgrid.py <ref> --shot pageNN   # 编译后再跑，出 _diff.png（O 键第三态）

# ③ 照读数写 layout/NN.json
python tools/refcheck.py                # 硬门禁：页数 / canvas 尺寸，退出码必须 0
node build.js && node tools/copycheck.js
node tools/shoot.js && python tools/reffit.py   # 吻合分 ≥ 0.80 为佳
```

`refscan` 会直接给你带缝与分栏的读数，例如：

```
p05.jpg                 1366x1748  候选切分点 3 条
    y=22.6%  conf=0.78
    y=62.0%  conf=0.78
    y=95.8%  conf=0.80
    band0 0.0%-22.6%  分栏 4.6% 11.8% 44.3% 90.5% 97.3%
```

`box` 的 `y` 就写 `0.226` / `0.620` / `0.958`。**照抄读数，不要估。**

---

## 格式速查

```jsonc
{
  "_": "自由注释。^_ 开头的文件 build 会跳过（可放草稿）。",
  "id": "page05",                        // 页码从 id 或文件名提取
  "ref": "p05.jpg",                      // 参考图文件名（放 assets/ref/）
  "canvas": { "w": 1366, "h": 1748 },    // ★ 必须等于该页参考图的真实像素尺寸
  "paper": { "tone": "warm", "grain": true },
  "meta":  { "title": "细节 NEWS", "page": "P46", "note": "NEWS 双栏 ＋ 撕纸标签" },
  "zones": [ /* 见 references/01-skeleton-and-layout.md §四 */ ]
}
```

| 字段 | 要点 |
|---|---|
| `canvas` | **必须逐页取各自参考图的真实尺寸**（`refscan` 的 `size` 字段）。抄错 → `build.js` 与 `refcheck.py` 双双退出码 1 |
| `ref` | 有它才有叠图三态与 H2 尺寸断言；仅内部比对，不随成品分发 |
| `paper.tone` | 只能是 `warm` / `cream` / `grey`（写别的 build 直接 fail） |
| `zones[].kind` | 白名单 12 个：`text` `image` `cutout` `mask` `rule` `band` `panel` `badge` `torn` `bubble` `logo` `label` |
| `zones[].style.font` | 只写**角色**：`serif` `sans` `script` `script-fat` `latin` `latin-ital`（不是字体名） |
| `zones[].box` | 归一化 `[x, y, w, h]`，全 0–1 的小数，相对本页 canvas |
| `zones[].variant` | 可选：`["rotate","frame","framing","reorder"]` —— 允许变体引擎扰动本框（默认不动） |

**改版式不用碰 CSS**；**换品牌只换 `brand/brand-pack.json`**。颜色写令牌名（`ink` / `accent`…），
只有「必须压在照片上的白字」才写字面色值。

---

## 增 / 删 / 换

| 要做什么 | 怎么做 |
|---|---|
| 加一页 | 放一个新的 `NN.json` → 重跑 `refcheck` → `build` → `copycheck` → `shoot`。**不用改任何脚本。** |
| 减一页 | 删掉（或改名以 `_` 开头）→ `node tools/prune.js` 清掉残留的 `pageNN.html` / `_shots/pageNN*.png` |
| 某页换画布 | 只改那一页的 `canvas`；其余页不受影响 |
| 换参考图 | 换图 + 更新 `ref` 字段，然后**用 `refscan.py` 重新解析 box**（不要照抄旧的） |

> 增删页后一定要跑 `node tools/prune.js`（默认 dry-run）：`build.js` 只会写当前页，
> **从不删除**已不存在的页，旧的 `page05.html` / `_shots/page05.png` 会残留下来，
> 而 `preview.py` 是按 `_shots/` 汇总的 —— 幽灵页会混进总览图。

---

## 一期一目录

一个 `layout/` 只放**一册**的版式。混两册会让 `refcheck` 的「页数 = 参考图张数」判据失效，
`preview.py` 的总览也会串。要出第二册 → 重新 `cp -r templates`，或从冻结产物再复制一份。

`freeze.js` 会在检测到 `copy/issues/` 非空或页码不连续时给出 WARN。
