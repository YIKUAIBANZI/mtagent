"""v1.7.2 天气感知 — 高德天气 API.

接口: https://restapi.amap.com/v3/weather/weatherInfo?key=X&city=<adcode>
city 必须传 adcode (行政区代码), 不接受中文名.

输出: hint ∈ {rainy, stormy, snowy, hot, cold, normal, unknown}
被 Profiler 注入到 ParsedIntent, 被 candidate_pool.score_poi 用于 weather_penalty.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

# 城市 adcode (mtagent v1 只支持三城)
CITY_ADCODE: dict[str, str] = {
    "深圳": "440300",
    "上海": "310000",
    "西安": "610100",
}


def classify_weather(weather_str: str, temp_c: Optional[int]) -> str:
    """Classify 高德 weather 描述 + 温度 → 内部 hint.

    规则保守: 雨/雪/暴风都视为不利户外, 极端温度 (>=35 或 <=5) 也归类.
    雷暴包含暴雨 / 大暴雨字眼 → stormy (更狠的 penalty).
    """
    w = (weather_str or "").strip()

    # 暴风/雷电类先判 (更强 hint)
    if any(k in w for k in ("暴雨", "大暴雨", "特大暴雨", "雷暴", "冰雹", "雷阵雨")):
        return "stormy"
    if any(k in w for k in ("小雪", "中雪", "大雪", "暴雪", "雪", "雨雪")):
        return "snowy"
    if any(k in w for k in ("雨", "阵雨", "毛毛雨")):
        return "rainy"

    # 极端温度
    if temp_c is not None:
        if temp_c >= 35:
            return "hot"
        if temp_c <= 5:
            return "cold"

    return "normal"


async def fetch_weather(
    city: str,
    amap_key: Optional[str] = None,
    timeout: float = 3.0,
) -> dict:
    """Fetch live weather for `city`. Returns dict with hint / raw / temp_c.

    Always returns a dict (never raises). On failure: hint='unknown', raw=None.
    """
    key = amap_key or os.environ.get("AMAP_KEY", "")
    out = {"hint": "unknown", "raw": None, "temp_c": None}
    if not key:
        return out
    adcode = CITY_ADCODE.get(city)
    if not adcode:
        return out
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                "https://restapi.amap.com/v3/weather/weatherInfo",
                params={"key": key, "city": adcode, "extensions": "base"},
            )
            data = resp.json()
            lives = data.get("lives") or []
            if not lives:
                return out
            live = lives[0]
            raw = live.get("weather", "")
            try:
                temp_c = int(live.get("temperature") or 0) or None
            except (TypeError, ValueError):
                temp_c = None
            return {
                "hint": classify_weather(raw, temp_c),
                "raw": raw,
                "temp_c": temp_c,
            }
    except Exception:
        return out


# Weather → score_poi penalty/bonus rules (applied in candidate_pool.score_poi).
# 公开常量, 便于测试.
WEATHER_PENALTY_RULES = {
    "stormy": {
        "walk_heavy_penalty": -50,  # 户外大景点严重 -
        "landmark_outdoor_penalty": -30,
        "rain_friendly_bonus": 30,
    },
    "rainy": {
        "walk_heavy_penalty": -30,
        "landmark_outdoor_penalty": -15,
        "rain_friendly_bonus": 20,
    },
    "snowy": {
        "walk_heavy_penalty": -25,
        "landmark_outdoor_penalty": -10,
        "rain_friendly_bonus": 15,
    },
    "hot": {
        "walk_heavy_penalty": -20,
        "landmark_outdoor_penalty": -10,
        "rain_friendly_bonus": 10,  # 室内凉快也 OK
    },
    "cold": {
        "walk_heavy_penalty": -15,
        "landmark_outdoor_penalty": -5,
        "rain_friendly_bonus": 10,
    },
    "normal": {},
    "unknown": {},
}
