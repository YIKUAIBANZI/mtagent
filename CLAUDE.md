# CLAUDE.md — mtagent (美团 Hackathon 赛题 05)

## 项目目标
美团 2026 AI Hackathon 赛题 05「现在就出发 · AI 本地路线智能规划」，截止 2026-06-07。

## 数据基础
赛题方明确无数据，**全部为 LLM 模拟**——`data/mock_dianping/` 含 2400 条 POI（深圳/上海/西安各 800），完全符合大众点评开放平台字段契约。

## 架构（v0）
三层端口适配器：
- `agents/` — Profiler / Planner / Critic / Adjuster（v0 Critic + Adjuster 是 stub）
- `agents/tools.py` — 工具层（search / batch / cluster / day_template / business_hour）
- `dianping/` — 数据契约层（schemas / auth / client / mock_server）

Mock server 独立进程在 port 9192，client 默认指向它，**改一行 BASE_URL env 切真接口**。

## 启动
```bash
# 终端 1: mock server
uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192

# 终端 2: 主 app（v1 加 SSE 路由后才需要，v0 直接跑测试即可）
PYTHONPATH=. pytest tests/ -v
```

## 关键设计决策
见 `docs/superpowers/specs/2026-05-08-mtagent-v0-backend-design.md` 第 12 节。

## 不做的（v0 范围外）
- SSE 流式路由（v1）
- 前端 plan_stack.html 改造（v1）
- Critic ReAct 真实工具调用（v2）
- Adjuster 单天重排（v3）
- 反馈闭环 + cookie profile（v3）

## travel-agent 复用的代码
- `agents/cluster_pois.py`（Anchor & Orbit 聚类）
- `agents/ranker.py`（按 traveler_type 排序）
- `agents/mapper.py`（高德地图链接生成）

需小幅适配字段名（`type` → `categories`，`rating` → `star`）。
