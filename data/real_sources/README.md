# real_sources

真实来源 POI 数据的第一版清洗产物。

注意：这里的数据是“真实来源证据层”，不是 mtagent Planner 的最终输入。

最终给 mtagent 后续规划链路用的 POI 文件仍然是：

```text
data/poi_enriched_labels.json
```

本目录里的文件要先经过 Agent 标注 / 合并，变成 `poi_enriched_labels` 同构结构后，才算真正进入路线规划数据底座。

## 输入来源

- `xhsoutdata2/data/real_sources/amap_poi_{城市}.jsonl`: 高德 POI 实体、坐标、评分、营业时间等。
- `xhsoutdata/xhs_notes.jsonl`: 小红书攻略正文，用于补充路线顺序、推荐理由、风险提示和语义信号。

## 当前产物

- `amap_poi_深圳.jsonl`, `amap_poi_上海.jsonl`, `amap_poi_西安.jsonl`: 三城高德 POI 实体层，已标准化到 mtagent 的 `data/real_sources` 下；这是原料，不是最终 Planner 输入。
- `xhs_city_guides.jsonl`: 三城小红书攻略正文和抽取出的候选地名。
- `merged_real_poi_candidates.jsonl`: 934 条高德 POI 候选全集，符合 `real_poi_candidate:v1`。
- `merged_real_poi_candidates_xhs_only.jsonl`: 19 条同时有高德实体和小红书攻略证据的高置信 POI，优先交给后续 Agent 打标签；这仍然不是最终 Planner 输入。
- `unmatched_xhs_mentions.json`: 小红书攻略提到但当前高德池未可靠匹配到的地名，下一轮应优先用高德 API 补查。
- `real_poi_merge_summary.json`: 每城数量、匹配数量、类目分布和未匹配地名摘要。

## 重新生成

```bash
PYTHONPATH=. python3 scripts/merge_real_poi_sources.py
```

脚本只做离线合并，不调用高德或小红书接口。
