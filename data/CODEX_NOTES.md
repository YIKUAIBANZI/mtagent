# Codex 数据轨工作日志

## 数据流真相

- 即时规划入口 `agents/planner_instant.py::load_city_pois_from_mock` 读取
  `data/mock_dianping/{city}.json`，再用 `data/poi_enriched_labels.json[city]`
  按 `openshopid` 运行时 attach `EnrichedLabel`。
- HTTP client 路径 `dianping/client.py::_attach_labels` 使用相同的
  `city -> openshopid -> enriched` 关联方式。
- `data/poi_decision_signals.json` 独立按 `openshopid` 查询，由
  `agents/poi_decision_signals.py` 只读加载；不需要写入 POI schema。
- 2026-06-01 recon 发现：现有 mock POI 使用 `mock_<hex>` ID，而三城 enriched
  标签使用高德 `B...` ID。上海、深圳、西安 attach 交集均为 0，运行时标签实际
  命中率为 0%。数据轨会先修复 ID 对齐，再补密标签和决策信号。
- 当前 5 条 `poi_decision_signals` 的摘要无法逐条回溯到对应 mock UGC；上海
  mock UGC 还混入了“北京特色”等错误城市模板。数据轨会重建上海信号，并让
  `evidence` 可回溯到 POI 自身 `reviewTags` / `ugcs`。

## Task 2 进展

- 新增 `scripts/build_canonical_pois.py`，保持现有运行时 attach 合约，不新增
  第二份 canonical 运行时文件。
- 修复前上海、深圳、西安 attach 交集均为 0；执行规则重建后，上海 750/750、
  深圳 721/721、西安 712/712、北京 736/736、南昌 642/642 均可 attach。
- 旧 `scripts/label_pois.py` 只识别精确类目“美食”/“购物”，与 mock 中的
  “餐饮服务”/“中餐厅”/“购物服务”不兼容；已在数据脚本侧补齐高德类目兼容。
- 北京和南昌现阶段 `city_essential` 仍为空：北京会在数据轨补 landmark
  词表，南昌由庐山替代。

## Task 3 进展

- 新增 `scripts/distill_ugc_risk_tags.py`，只从 POI 自身 `reviewTags` / `ugcs`
  抽取风险，并在新增标签时写入 `agent:risk_from_ugc:v1` 来源。
- 上海执行后：`queue_heavy=149`、`crowded_weekend=157`、`walk_heavy=65`；
  第二次执行 `changed_poi_count=0`，具备幂等性。
- 抽查证据写入 `data/ugc_risk_coverage.json`，例如
  `reviewTag:排队较长`、`reviewTag:人流较多`，没有把普通“适合散步”误标为
  `walk_heavy`。

## Task 4 进展

- 新增 `scripts/build_decision_signals.py`，重建上海
  `data/poi_decision_signals.json`。旧 5 条不可回溯手写摘要已替换。
- 当前上海 signal `286` 条，`286/286` 均有可回溯 evidence；自动检查
  `trace_errors=0`。
- evidence 明确区分结构化点评聚合标签与评论文本，例如
  `UGC 摘要：reviewTag「排队较长」`、
  `UGC 摘要：评论「人稍微多了点，但景色真的不错。」`。
- 数据仍是赛题 mock UGC，不应对外表述为抓取到的真实大众点评原文；可准确描述为
  “从 POI 自身 mock UGC 与结构化点评标签离线蒸馏决策信号”。

## 给 Claude 的运行时接线事项

- 庐山数据落盘后，请把 `庐山` 接入以下运行时文件：
  - `dianping/mock_server.py` 的城市加载列表；
  - `api/stub_llm.py` 的 `_CITY_PAT`；
  - `agents/profiler.py` 的 `_FALLBACK_CITY_PAT`；
  - `agents/planner.py` 的 `_CITY_ANCHORS`，建议使用牯岭街、如琴湖、花径、
    含鄱口、三叠泉等景区锚点；
  - 如需实时天气，请在 `agents/weather.py::CITY_ADCODE` 增加庐山市 adcode。
- Codex 不修改上述文件，避免越过 `agents/`、`api/`、`dianping/schemas.py`
  ownership。

## Task 5 进展

- 新增 `scripts/build_lushan_mock.py`：从高德文本检索保存原始快照，
  POI 名称、地址、坐标使用真实高德记录；点评标签和 UGC 使用固定种子生成的
  赛题 mock，二者在脚本和报告里明确区分。
- 原始快照召回 `689` 条，地理范围、路线可用性、去重过滤后候选 `464` 条，
  最终按景点、索道、观景设施、住宿、餐饮优先级裁剪为 `360` 条。
- `data/mock_dianping/index.json` 和 `metadata.json` 已切换为五城交付索引：
  深圳、上海、北京、西安、庐山，共 `3279` 条。`南昌.json` 暂时保留为回滚
  文件，但不进入交付索引和 canonical 标签产物。
- canonical 五城重建后，庐山 `360/360` 可 attach；UGC 蒸馏得到
  `walk_heavy=317`、`queue_heavy=141`、`crowded_weekend=113`。
- 数据层直接 smoke 已通过：`load_city_pois_from_mock("庐山")` 加载 `360`
  条、attach `360` 条；`plan_three_variants` 三个 variant 均生成 `4` 个停靠点，
  `validate_day` 得分均为 `1.0`。
- 用户从自然语言进入庐山的完整 API 路径仍依赖上方 Claude 运行时接线事项。
