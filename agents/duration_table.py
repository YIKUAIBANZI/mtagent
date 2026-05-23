"""POI categories → base duration (分钟) + traveler 节奏倍率.

调用入口:
  duration_for(categories, traveler, poi_name="") → int (向上取整到 5)
"""

from __future__ import annotations

import math
from typing import Iterable

# 顺序敏感: 先匹配的优先 (具体优先于宽泛).
# 关键词匹配规则: keyword in category 子串命中即算.
_DURATION_RULES: list[tuple[tuple[str, ...], int]] = [
    (("博物馆", "美术馆", "展览"), 100),
    (("火锅", "烧烤"), 90),
    (("夜市", "步行街"), 80),
    (("中餐厅", "西餐厅", "餐厅", "餐饮服务"), 70),
    (("商场", "购物"), 60),
    (("公园", "广场"), 50),
    (("咖啡", "茶馆", "甜品"), 40),
    (("小吃", "快餐"), 30),
    (("喷泉", "雕塑", "标志"), 20),
    (("风景名胜", "景点", "5A", "4A"), 90),
]

_DEFAULT_BASE = 60

_TRAVELER_MULTIPLIER: dict[str, float] = {
    "情侣": 1.2,
    "亲子": 1.4,
    "银发": 1.3,
    "独行": 1.0,
    "商务": 0.7,
    "朋友": 1.1,
}


def base_duration_for(categories: Iterable[str], poi_name: str = "") -> int:
    """遍历 _DURATION_RULES 顺序; rule 的任一关键词被任一 category 字符串包含即命中.

    categories 顺序无关; rule 表自身顺序决定优先级 (博物馆 > 通用景点).
    全部 miss → _DEFAULT_BASE.
    poi_name 当前不参与匹配, 保留入参为后续扩展.
    """
    cats = [c for c in categories if c]
    for keywords, base in _DURATION_RULES:
        for kw in keywords:
            for cat in cats:
                if kw in cat:
                    return base
    return _DEFAULT_BASE


def duration_for(categories: Iterable[str], traveler: str, poi_name: str = "") -> int:
    """base × multiplier, 向上取整到 5 的倍数. 未知 traveler → 1.0."""
    base = base_duration_for(categories, poi_name)
    mult = _TRAVELER_MULTIPLIER.get(traveler, 1.0)
    return math.ceil(base * mult / 5) * 5
