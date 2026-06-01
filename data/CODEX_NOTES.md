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
- 上海执行后：`queue_heavy=149`、`crowded_weekend=129`、`walk_heavy=65`；
  第二次执行 `changed_poi_count=0`，具备幂等性。
- 抽查证据写入 `data/ugc_risk_coverage.json`，例如
  `reviewTag:排队较长`、`reviewTag:人流较多`，没有把普通“适合散步”误标为
  `walk_heavy`。

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
