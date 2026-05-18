# data

## 当前唯一主口径

给 mtagent 后续规划链路用的最终数据只有两类：

```text
data/poi_enriched_labels.json
data/user_profiles/{cookie_key}.json
```

## 各目录和文件定位

| 路径 | 定位 | 是否最终给 Planner |
|---|---|---|
| `data/poi_enriched_labels.json` | POI 结构化路线规划标签 | 是 |
| `data/user_profiles/{cookie_key}.json` | 用户历史偏好画像 | 是 |
| `data/mock_dianping/*.json` | mock POI 原料 | 否 |
| `data/real_sources/*.jsonl` | 高德 / 小红书真实来源证据层 | 否 |
| `data/poi_agent_label_tasks.jsonl` | 低级 Agent 标注任务 | 否 |
| `data/poi_agent_label_batches/*.jsonl` | 分批标注任务 | 否 |
| `data/poi_agent_labels.json` | 低级 Agent 回填结果 | 否 |
| `data/poi_agent_label_summary.json` | 标签校验统计 | 否 |
| `data/poi_labels.json` | 旧版兼容标签 | 否 |

`data/real_sources/merged_real_poi_candidates.jsonl` 不能直接替代 `data/poi_enriched_labels.json`。它只是把高德实体和小红书证据清洗到一起，下一步还要让 Agent 按 `poi_enriched_labels` schema 打标签。
