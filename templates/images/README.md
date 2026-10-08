# images/ —— 素材命名约定

> **唯一权威是 `layout/*.json` 里的 `"src"` 字段。** 本文件说明的是**建议的命名规律**
> 与本示例套用的固定名，方便复用与替换。
>
> 换产品时：**按 `src` 里的同名文件替换掉**，页面 HTML 一行都不用改；
> 缺哪个文件，`build.js` 会提示「图片不存在」，那一块渲染成空白（不报错、不崩版）。

---

## 一、命名规律（推荐）

```
<页号>-<角色>[-<变体>].<ext>
```

| 角色 | 含义 | 常见 ext | 建议尺寸 |
|---|---|---|---|
| `hero` | 主视觉出血大图（占半页以上） | jpg | 长边 ≥ 1600 |
| `plate` | 实底照片（整块矩形、带框或无框） | jpg | 长边 ≥ 1200 |
| `model` | 模特/人物拍摄图 | jpg | 竖版为主 |
| `step` | 步骤小图（Step 四格那种） | jpg | ≥ 800 |
| `detail` | 细节特写（圆形裁切用，**越接近方形越好**） | png | ≥ 800，方形 |
| `cutout` | 抠底单品（透明 PNG，无框压在版面上） | png | ≥ 1200 |
| `gen` | AI 生成图 | jpg | 按画布 |
| `info` | 供货方产品信息图（**产品事实的唯一来源**） | png | 不限 |

变体后缀按需加：颜色（`-white` / `-black`）、角度（`-side` / `-back`）、
序号（`-01` / `-02`）。

---

## 二、本示例（2 页）用的固定名

跑通示例需要这些文件（**已经在目录里**，替换即可）：

### page01（出血人像 + Step 四格）

| 文件 | 角色 | 内容 |
|---|---|---|
| `p01-hero.jpg` | hero | 主视觉出血图，**画面下缘要留给 Step 四格**（下缘会被压住） |
| `step-1.jpg` ~ `step-4.jpg` | step | 四个步骤小图，等比 |

### page05（NEWS 双栏 + 细节圆 + 实底照）

| 文件 | 角色 | 内容 |
|---|---|---|
| `p05-plate-a.jpg` / `p05-plate-b.jpg` | plate | 两张实底照 |
| `detail-cup.png` | detail | 上杯 |
| `detail-bow.png` | detail | 中桥（蝴蝶结） |
| `detail-strap.png` | detail | 肩带（调节扣） |
| `detail-wing.png` | detail | 侧翼 |
| `detail-mesh.png` | detail | 网纱质地 |

> `detail-*.png` 会被**圆形裁切**（`kind: "mask"` + `mask: "circle"`），
> 所以**主体要居中、四角留白**，否则裁完只剩一半。

---

## 三、抠图与透明边界（用 cutout 时必做）

白底产品图抠成透明 PNG：

```bash
python tools/cutout.py           # 改脚本里的输入/输出路径，批量处理
```

**然后必做**：

```bash
python tools/alphabox.py         # → images/_alphabox.json（每张图的真实内容区比例）
```

**为什么必做**：白底抠图四周留着大量透明边，实测内容占比从 55% 到 76% 不等。
「元素框相交」根本不代表「两张图叠在一起」。
`tools/blockcheck.py`（照片互压审计）依赖 `_alphabox.json`；不生成会**一直假报**。
图片改动后要重跑 `alphabox.py`（`blockcheck.py` 会提示）。

---

## 四、生成物（不用手放）

| 文件 | 由谁产生 |
|---|---|
| `_alphabox.json` | `python tools/alphabox.py` |
| `_flat/*.png` | 抠图中间产物（可留可删） |

---

## 五、人脸禁区（放了模特图就要管）

`tools/faces.json` 里的是**本示例图**人工标定的五官框。
**一旦换了模特图，旧坐标就失效**——`tools/check_faces.py` 会给出错误结论。

重标流程（标定只做一次，之后每次出图自动检查）：

```bash
python tools/grid.py pageNN                                  # 叠 100px 坐标网，先看位置
python tools/probe.py pageNN:x,y,w,h --zoom 6.5 --no-zones   # 带尺放大，读出五官坐标
# → 把 {name,x,y,w,h} 填进 tools/faces.json；读数记在 _calib 里备查
```

**没有模特脸的页**（纯产品页）→ 该页保持空数组 `[]`（= 无禁区，不会误报）。

---

## 六、素材台账

每一张素材的**来源、尺寸、hash、授权/合规、分发范围**都要登记进项目根的 `ASSETS.md`。
模板见 `../references/04-asset-ledger.md`。

**三条硬规则**：
1. 参考图**不随成品分发**（只用于叠图比对）。
2. **AI 生成必须备案**（备案 ≠ 对外标识；本项目按品牌决定在页面上不写「AI 生成」）。
3. **未确认的就不写**（产地、纤维混用率、洗濯记号、表示者名）。
