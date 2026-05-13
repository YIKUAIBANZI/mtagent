"""v1.8 Trip Mode Router — 5 类规则路由 + hub_type / safety_margin 推断.

Spec §2 docs/superpowers/specs/2026-05-13-v18-trip-mode-router-and-geometry.md.
规则 fallback, LLM 优先 (Profiler 已抽 trip_mode 字段则跳过此 router).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from dianping.schemas import HubType, ParsedIntent, TripMode

# ---- 关键词字典 ----

LAYOVER_KEYWORDS = (
    "中转",
    "转机",
    "路过",
    "停留",
    "赶火车",
    "赶飞机",
    "赶车",
    "赶高铁",
    "高铁",
    "动车",
    "几小时后",
    "小时后要走",
)
TRANSIT_HUB_KEYWORDS = ("火车站", "高铁站", "机场", "动车站", "客运站")
EXPLORE_KEYWORDS = ("附近", "周边", "转转", "逛逛", "这边", "这里", "一带")
EAT_KEYWORDS = ("吃", "美食", "餐厅", "饭", "面", "粉", "小吃", "夜宵", "下午茶")
VISIT_KEYWORDS = ("看", "玩", "逛", "转转", "拍照", "景点", "打卡", "游览", "看看")

# hub_type 推断 (先匹配更具体的)
HUB_TYPE_RULES: list[tuple[tuple[str, ...], HubType]] = [
    (("高铁站", "动车站", "北站", "东站", "南站", "西站"), "highspeed"),
    (("机场", "国际机场"), "airport"),
    (("汽车站", "客运站", "长途"), "bus"),
    (("火车站", "站"), "train"),
]

# safety_margin (minutes) — Q5 拍板
HUB_SAFETY_MARGIN: dict[HubType, int] = {
    "train": 30,
    "highspeed": 30,
    "airport": 120,
    "bus": 20,
}

# 节假日 buffer (节假日 + holiday_buffer 分钟)
HOLIDAY_BUFFER_MIN = 45

# 2026 中国法定假日 (硬编码, 一年表足够)
HOLIDAYS_2026: set[date] = {
    # 元旦
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 1, 3),
    # 春节 (2/17-2/23)
    date(2026, 2, 17),
    date(2026, 2, 18),
    date(2026, 2, 19),
    date(2026, 2, 20),
    date(2026, 2, 21),
    date(2026, 2, 22),
    date(2026, 2, 23),
    # 清明 (4/4-4/6)
    date(2026, 4, 4),
    date(2026, 4, 5),
    date(2026, 4, 6),
    # 劳动 (5/1-5/5)
    date(2026, 5, 1),
    date(2026, 5, 2),
    date(2026, 5, 3),
    date(2026, 5, 4),
    date(2026, 5, 5),
    # 端午 (6/19-6/21)
    date(2026, 6, 19),
    date(2026, 6, 20),
    date(2026, 6, 21),
    # 中秋 + 国庆 (10/1-10/8)
    date(2026, 10, 1),
    date(2026, 10, 2),
    date(2026, 10, 3),
    date(2026, 10, 4),
    date(2026, 10, 5),
    date(2026, 10, 6),
    date(2026, 10, 7),
    date(2026, 10, 8),
}

# anchor_radius_km 默认值 (Q4 拍板, 冷启动后续覆盖)
DEFAULT_ANCHOR_RADIUS_KM = 4.0  # walk=2 / bike=4 / transit=6 中位


def is_chinese_holiday(d: date) -> bool:
    return d in HOLIDAYS_2026


def infer_hub_type(text: Optional[str]) -> Optional[HubType]:
    """从 start_location_text 推 hub_type. 没命中返 None."""
    if not text:
        return None
    for keywords, hub in HUB_TYPE_RULES:
        if any(k in text for k in keywords):
            return hub
    return None


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def route_trip_mode(intent: ParsedIntent, raw_text: str) -> TripMode:
    """5 类规则路由. Spec §2.1.

    优先级: multi_day → layover → anchor_explore → landmark_must (兜底).
    """
    # 1) 多日优先
    if (intent.days or 1) >= 2:
        return "multi_day"

    # 2) layover — keyword OR hub_type 命中
    is_layover = (
        _has_any(raw_text, LAYOVER_KEYWORDS)
        or infer_hub_type(intent.start_location_text) is not None
        or _has_any(intent.start_location_text or "", TRANSIT_HUB_KEYWORDS)
    )
    if is_layover:
        has_eat = _has_any(raw_text, EAT_KEYWORDS)
        has_visit = _has_any(raw_text, VISIT_KEYWORDS)
        if has_eat and not has_visit:
            return "layover_eat"
        if has_visit and not has_eat:
            return "layover_explore"
        return "layover_explore"

    # 3) anchor_explore: 有具体地点锚点
    if intent.start_location_text:
        return "anchor_explore"

    # 4) 兜底
    return "landmark_must"


def compute_safety_margin(
    hub_type: Optional[HubType], at_date: Optional[date] = None
) -> int:
    """基础 safety_margin + 节假日 buffer."""
    if hub_type is None:
        return 30
    base = HUB_SAFETY_MARGIN.get(hub_type, 30)
    if at_date and is_chinese_holiday(at_date):
        base += HOLIDAY_BUFFER_MIN
    return base
