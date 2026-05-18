"""5 城市 × 3 variant 路线质量基线.

每次 CI 跑一遍, 把 6 条规则的通过情况打入 tests/snapshots/route_quality_baseline.json.
当前阈值低 (>=3/6), 是为了让 bug 在快照里被看到, 而不是被测试隐藏.
修一条 rule 就把阈值升一格.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from agents.planner import Planner
from agents.planner_instant import load_city_pois_from_mock, plan_three_variants
from agents.route_validator import validate_day
from api.stub_llm import stub_planner_llm_stream
from dianping.client import DianpingClient
from dianping.schemas import ParsedIntent

_CITIES = ["深圳", "上海", "西安", "南昌", "北京"]
_MIN_SCORE = 3 / 6  # 初始阈值: 每个 variant 至少通过 3/6 规则
_SNAPSHOT = Path("tests/snapshots/route_quality_baseline.json")


class _StubAmap:
    def __init__(self):
        self._client = self

    async def get_transit_options(self, *, origin, dest, city, traveler_type):
        from dianping.schemas import TransitInfo

        opts = {
            m: TransitInfo(mode=m, minutes=15, distance_km=2.0, source="estimated")
            for m in ("drive", "walk", "transit", "bicycle")
        }
        return opts, "walk"

    async def aclose(self):
        pass


def _intent_for(city: str) -> ParsedIntent:
    return ParsedIntent(
        city=city,
        days=1,
        traveler_type="情侣",
        time_window="一日",
        interests=["拍照"],
        estimated_hours=10,
    )


@pytest.mark.skipif(
    not all(os.path.exists(f"data/mock_dianping/{c}.json") for c in _CITIES),
    reason="5 city mock data not present",
)
def test_route_quality_baseline_all_cities():
    snapshot: dict[str, dict] = {}
    failures: list[str] = []

    for city in _CITIES:
        pois = load_city_pois_from_mock(city)
        intent = _intent_for(city)
        client = DianpingClient()
        planner = Planner(client=client, llm_call_stream=stub_planner_llm_stream)
        amap = _StubAmap()
        variants = asyncio.run(
            plan_three_variants(intent=intent, planner=planner, amap=amap, pois=pois)
        )

        snapshot[city] = {}
        for vname, vp in variants.items():
            report = validate_day(vp.day_plan, intent)
            snapshot[city][vname] = {
                "stops": len(vp.day_plan.stops),
                "score": report.score,
                "passed": report.passed_count,
                "total": report.total,
                "failed_rules": [c.name for c in report.failed],
                "details": {c.name: c.detail for c in report.failed},
            }
            if report.score < _MIN_SCORE:
                failures.append(
                    f"{city}/{vname}: score={report.score:.2f} < {_MIN_SCORE:.2f}, "
                    f"failed={[c.name for c in report.failed]}"
                )

    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))

    assert not failures, "Route quality baseline regressions:\n" + "\n".join(failures)
