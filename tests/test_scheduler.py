"""Unit tests for agents.scheduler — 贪心排程 + 餐点 anchor."""

from datetime import time
from types import SimpleNamespace

from agents.scheduler import (
    DAY_END_HARD_CAP,
    DAY_START_BY_TRAVELER,
    DINNER_ANCHOR,
    LUNCH_ANCHOR,
    schedule_day,
)


def _poi(name: str, categories: list[str]):
    """轻量 POI stub. scheduler 只读 .name / .categories."""
    return SimpleNamespace(name=name, categories=categories)


# --- happy path ---


def test_happy_couple_4stops_meals_in_anchor() -> None:
    """情侣 4 stop: 起点 10:00, 午餐 in [11:30,12:30], 晚餐 in [18:00,19:00]."""
    pois = [
        _poi("公园", ["公园"]),  # 50 × 1.2 = 60
        _poi("中餐厅", ["中餐厅"]),  # 70 × 1.2 = 84 → 85
        _poi("博物馆", ["博物馆"]),  # 100 × 1.2 = 120
        _poi("西餐厅", ["西餐厅"]),  # 70 × 1.2 = 85
    ]
    slots = ["上午景点", "午饭", "下午", "晚饭"]
    out = schedule_day(pois, slots, "情侣")
    assert out[0][0] == time(10, 0)
    assert LUNCH_ANCHOR[0] <= out[1][0] <= LUNCH_ANCHOR[1]
    assert DINNER_ANCHOR[0] <= out[3][0] <= DINNER_ANCHOR[1]


# --- 拖时压缩 ---


def test_morning_long_squeezes_prev_for_lunch() -> None:
    """情侣上午博物馆 120min: 起点 10:00 + 120 + 30 = 12:30 命中 anchor 上限, 不需压缩."""
    pois = [
        _poi("博物馆", ["博物馆"]),
        _poi("中餐厅", ["中餐厅"]),
    ]
    slots = ["上午景点", "午饭"]
    out = schedule_day(pois, slots, "情侣")
    assert out[1][0] <= LUNCH_ANCHOR[1]
    assert out[0][1] == 120


def test_morning_long_squeezes_prev_overshoot() -> None:
    """亲子博物馆 140min + 起点 8:30 = 11:00 + 140 + 30 = 13:40 > 12:30 → 压前 stop -25%."""
    pois = [
        _poi("博物馆", ["博物馆"]),
        _poi("中餐厅", ["中餐厅"]),
    ]
    slots = ["上午景点", "午饭"]
    out = schedule_day(pois, slots, "亲子")
    assert out[1][0] <= LUNCH_ANCHOR[1]
    assert 105 <= out[0][1] <= 140


# --- 早起 ---


def test_family_early_start_within_day_cap() -> None:
    """亲子起点 8:30; 4 stops 全 arrival 在 21:00 前."""
    pois = [
        _poi("公园", ["公园"]),
        _poi("餐厅", ["餐厅"]),
        _poi("博物馆", ["博物馆"]),
        _poi("晚饭", ["餐厅"]),
    ]
    slots = ["上午景点", "午饭", "下午", "晚饭"]
    out = schedule_day(pois, slots, "亲子")
    assert out[0][0] == DAY_START_BY_TRAVELER["亲子"]
    for arrival, _ in out:
        assert arrival <= DAY_END_HARD_CAP


# --- 商务 ---


def test_business_fast_pace_ends_early() -> None:
    """商务节奏: 末位 arrival < 18:00 (无晚饭 slot, 不触发 anchor)."""
    pois = [
        _poi("公园", ["公园"]),
        _poi("餐厅", ["餐厅"]),
        _poi("博物馆", ["博物馆"]),
        _poi("茶馆", ["茶馆"]),
    ]
    slots = ["上午景点", "午饭", "下午", "下午茶"]
    out = schedule_day(pois, slots, "商务")
    assert out[-1][0] < time(18, 0)


# --- 全 fallback ---


def test_all_fallback_pois_still_schedules() -> None:
    """全 fallback POI (空 categories) → 基础 60 × multiplier 仍能跑通."""
    pois = [
        _poi("X", []),
        _poi("Y", []),
        _poi("Z", []),
    ]
    slots = ["上午景点", "午饭", "下午"]
    out = schedule_day(pois, slots, "独行")
    assert len(out) == 3
    assert all(isinstance(a, time) for a, _ in out)
