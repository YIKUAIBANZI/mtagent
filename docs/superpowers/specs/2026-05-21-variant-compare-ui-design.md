# Variant Compare UI · Design Spec

**Date:** 2026-05-21
**Status:** brainstorm 拍板，待 writing-plans 拆解实现计划
**Project:** mtagent (赛题 05 · AI 本地路线智能规划)
**Author:** 用户 + Claude (brainstorming session)

---

## 背景

赛题原文核心评分点包含 **"多方案对比交互设计"**（创新性 · 体验创新）。当前系统已在后端跑 3 个 variant（`main` / `low_queue` / `interest_first`），但前端只渲染 `main`，evaluator 看不到分流结果。

本 spec 目标：把现有 variant 资产以最小改动暴露成评委可感知的"AI 还想到这些"对比交互，复用 critic.findings SSE 协议路径与已有 variant labels（`api/routes.py:1410`）。

不涉及：新 variant 生成、地图 marker 散开、跨方案混搭、UserProfile 写回。

---

## 用户故事

> 评委输入"明天去南昌玩一天，情侣"，看到主行程流式生成完毕、Critic 复检建议出现后，主行程顶上多出两个 chip：`⏳ 少排队 (3)` 和 `🌟 兴趣优先 (2)`。点 `⏳ 少排队`，主行程对应的 3 个 stop 旁边亮起橙色 patch tag `→ 桂林米粉总店`、`→ ...`、`→ ...`，chip 旁边出现"应用此方案"按钮；点击后整张主行程在原位 swap 成 low_queue 方案，地图重画 polyline，顶上多出 toast `已应用 [少排队] · 撤销`。点撤销即回 main。

---

## 整体形态决策（brainstorm 拍板）

| 决策点 | 选定 | 备选 (已否决) |
|---|---|---|
| 主体呈现节奏 | B · 默认主流 + 收尾"换思路"小卡 | A 并行流同屏 / C 雏形卡先选 |
| 展开形态 | C · 主行程内联 Patch tag | A 整页 swap / B 双栏 diff |
| 分组逻辑 | A · 按方案绑定 (group toggle) | B cherry-pick / C 长按混合 |
| chip click 行为 | 2 步（高亮 → 应用） | 1 步直接 swap |
| 地图行为 | apply 后整张重画 polyline | 双线叠加 / 不动 |
| 撤销 UX | apply 后顶部常驻 toast 按钮 | inline 按钮 / 5s 后自动消 |

---

## 后端

### 新增模块 `agents/variant_patches.py`

纯函数，与 SSE 解耦：

```python
def compute_variant_patches(
    main_stops: list[Stop],
    variant_stops: list[Stop],
    variant_kind: Literal["low_queue", "interest_first"],
) -> list[Patch]:
    """逐 stop_idx 比对 poi_id；不同即生成一处 Patch。"""
```

**Patch 结构（pydantic）**：

```python
class Patch(BaseModel):
    stop_idx: int          # 主行程 stop 索引（0-based）
    from_: PatchEndpoint = Field(alias="from")  # pydantic 关键字规避；JSON 字段名 "from"
    to: PatchEndpoint      # 该 variant 该 stop 摘要 (poi_id, name, location, category)
    reason: str            # 简短理由，从 variant 该 stop 的 rationale.short 截前 1 句

    class Config:
        populate_by_name = True

class VariantPatchSet(BaseModel):
    kind: Literal["low_queue", "interest_first"]
    label: str          # 复用 routes.py:1410 中文标签
    icon: str           # ⏳ / 🌟
    patches: list[Patch]
```

**对齐策略**：若 variant_stops 长度与 main_stops 不一致，按较短长度截取并 log warning（hackathon scope 内 5 城测试 stop 数稳定）。

### SSE 接入 `api/routes.py`

在 `critic.findings` yield 之后、`planner.done` 之前新增一帧（不删任何老事件）：

```
event: planner.variant_patches
data: {"variants": [VariantPatchSet, ...]}
```

**Degrade 规则**：
- variant planner 抛异常 → 该 set 不入数组（已有 try/except 包络）
- patches 为空（与 main 完全一致）→ 该 set 不入数组
- 整个 variants 数组为空 → 不 yield 事件（前端按"没有 chip"处理）

### 测试 `tests/test_variant_patches.py`

| 用例 | 断言 |
|---|---|
| 两个 stops 数组完全一致 | 返回 `[]` |
| 仅 stop_idx=2 不同 | 返回 1 个 Patch，from/to/reason 字段齐 |
| 多 stop 差异（idx 0, 3, 5） | 返回 3 个 Patch，顺序按 stop_idx 升序 |
| variant 比 main 短 1 | 按 main 截短，patches 只比 min len 范围 |
| variant 比 main 长 1 | 同上，多出的 stop 不算 patch |

### 测试 `tests/test_routes_sse_variant_patches.py`

| 用例 | 断言 |
|---|---|
| 3 variant 全成功且互不同 | SSE 流末出现 1 帧 `planner.variant_patches`, `len(variants)==2` |
| `low_queue` 与 main 一致 | 该 set 不入数组, `len(variants)==1` |
| 全部 variant 与 main 一致 | 不 yield 此事件，下游不报错 |
| variant 异常被 catch | 该 set 不入数组，事件正常 yield |

---

## 前端

文件：`web/plan_stack.html`

### 新增 UI 元素

```html
<!-- 顶栏 chat 区下方，行程区上方 -->
<div id="variantChips" class="variant-chips" hidden>
  <!-- 动态插入 -->
</div>

<!-- 每个 stop 卡片右上角 inline 渲染 -->
<span class="patch-tag" data-variant="low_queue" data-stop-idx="2">
  → 桂林米粉总店
</span>

<!-- 顶部 toast (apply 后渲染) -->
<div id="variantToast" class="variant-toast" hidden>
  已应用 [少排队] · <button onclick="undoVariant()">撤销</button>
</div>
```

### 状态机（JS）

```
state: { mode: "idle"|"highlighted"|"applied", activeKind: null|str, baseStops: null|array }

事件:
- SSE planner.variant_patches → 缓存 variantPatchSets, 渲染 chips, hidden=false
- chip click (kind X):
    if mode == "idle" → highlight(X), mode="highlighted", activeKind=X
    elif mode == "highlighted" && activeKind == X → 取消高亮, mode="idle"
    elif mode == "highlighted" && activeKind != X → 切换高亮到 X
    elif mode == "applied" → 撤销当前 + highlight(X)
- "应用此方案" click → swap stops + redraw map + show toast, mode="applied"
- "撤销" click → restore baseStops + redraw map + hide toast, mode="idle"
- trip.started SSE → reset 全部 state, hide chips/toast
```

### 关键不变量

- `baseStops` 在第一次 apply 前用 `structuredClone(currentStops)` 锁定
- patch tag DOM 用 `data-variant` 属性绑 CSS（橙=low_queue, 绿=interest_first）
- toast 是 fixed top；apply 后立即出，撤销前不消失
- highlighted 模式下，非当前 variant 的 patch tag opacity 0.3

### CSS（追加）

- `.variant-chips` flex row gap 8px, padding 8px
- `.chip` button-like, default bg dim, active state bg 高亮色 + outline
- `.chip-count` 小字体 dim 显示括号数
- `.patch-tag` inline-block, padding 2px 6px, border-radius 4px, font-size 11px
- `.variant-toast` fixed top:8px right:8px

---

## 不在本 spec 范围

- marker <200m 扇形偏移（评估为 P3）
- cherry-pick 跨 variant 混搭（拍板 group 绑定）
- variant 选定后写入 cookie / UserProfile
- 地图双线对比
- 单个 patch 独立 apply（拍板 group 全有全无）

---

## 验收清单

- [ ] 后端 `compute_variant_patches` 5 测试全过
- [ ] 后端 SSE 4 测试全过
- [ ] 现有 406 测试 baseline 不破
- [ ] 本地浏览器 5 城跑通：南昌 / 西安 / 北京 / 上海 / 深圳，每城点开 chip → highlight → apply → 撤销 流程顺
- [ ] 哈尔滨（amap 路径）也能出 chip（验非 5 城内置数据集时仍走通）
- [ ] 移动 4G 真实通路：profile chip / stop rationale / critic findings / variant chips 串行无 trip 间泄漏
- [ ] commit 推 origin + VPS systemctl restart + journalctl 无 traceback

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| `compute_variant_patches` 在 variant rationale 缺失时 reason 字段空字符串 | 默认 fallback "AI 认为更适合此风格"，不阻塞 |
| 前端 baseStops clone 深度不够导致撤销失败 | 用 `structuredClone`（modern browser ✅）+ 测一遍 |
| SSE 新事件被旧前端忽略不报错 | 前端 case default 不抛；后端 SSE event name 唯一不冲突 |
| variant planner 卡顿拖慢主流 done | 现状已是 3 variant 并行内 `asyncio.gather`，本 spec 不改 planner 并发，patches 计算是纯函数 ms 级 |
| 全部 variants 失败 → 前端无 chip | 评委体验 = 退化到现状，无 regression |

回滚：一个 feature flag `VARIANT_COMPARE_UI` 默认 on，关掉后前端 chips 不显示、后端不 yield 事件，其余链路不动。
