"""v1.9.1 Phase B: promote_cache 单测.

覆盖:
- 阈值过滤: seen<min 跳过
- 幂等: 同 cache_key 第二次跑 skipped_already_promoted, 不重复写 mock_dianping
- cache 标记 promoted=true
- 无 enriched 跳过 (保守, 不污染本地)
- mock_dianping 已有同 openshopid 跳过 (dup_in_mock)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.promote_cache import promote_cache, _gen_openshopid


def _write_cache(p: Path, entries: dict) -> None:
    p.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_entry(
    *,
    name: str,
    lng: float,
    lat: float,
    city: str,
    seen_count: int,
    with_enriched: bool = True,
    promoted: bool = False,
) -> dict:
    entry = {
        "name": name,
        "lng": lng,
        "lat": lat,
        "city": city,
        "typecode": "050000",
        "categories": ["美食"],
        "source": "amap_around",
        "version": "v1.9.1",
        "seen_count": seen_count,
        "created_at": "2026-05-14T00:00:00+00:00",
        "last_seen": "2026-05-14T00:00:00+00:00",
    }
    if with_enriched:
        entry["enriched"] = {
            "poi_role": "meal",
            "planning_tags": ["food_quality"],
            "risk_tags": [],
            "city_zone": "test_zone",
            "manual_priority": 75,
            "min_stay_minutes": 45,
            "max_stay_minutes": 90,
        }
    if promoted:
        entry["promoted"] = True
    return entry


@pytest.fixture
def tmp_paths(tmp_path):
    cache = tmp_path / "poi_cache.json"
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    enriched = tmp_path / "poi_enriched_labels.json"
    return cache, mock_dir, enriched


def test_threshold_filter_skips_below_min_seen(tmp_paths):
    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "热门|113.95|22.54": _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=5
            ),
            "冷门|113.96|22.55": _make_entry(
                name="冷门", lng=113.96, lat=22.55, city="深圳", seen_count=4
            ),
        },
    )
    summary = promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    assert summary["深圳"]["promoted"] == 1
    assert summary["深圳"]["skipped_below_threshold"] == 1
    mock = json.loads((mock_dir / "深圳.json").read_text(encoding="utf-8"))
    assert len(mock) == 1
    assert mock[0]["name"] == "热门"


def test_idempotent_second_run_no_dup(tmp_paths):
    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "热门|113.95|22.54": _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=8
            ),
        },
    )
    promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    # 第二次跑
    summary2 = promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    assert summary2["深圳"]["promoted"] == 0
    assert summary2["深圳"]["skipped_already_promoted"] == 1
    mock = json.loads((mock_dir / "深圳.json").read_text(encoding="utf-8"))
    assert len(mock) == 1  # 没重复


def test_cache_entry_marked_promoted(tmp_paths):
    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "热门|113.95|22.54": _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=6
            ),
        },
    )
    promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    cache_after = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache_after["热门|113.95|22.54"]["promoted"] is True


def test_no_enriched_skipped(tmp_paths):
    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "未打|113.95|22.54": _make_entry(
                name="未打",
                lng=113.95,
                lat=22.54,
                city="深圳",
                seen_count=6,
                with_enriched=False,
            ),
        },
    )
    summary = promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    assert summary["深圳"]["promoted"] == 0
    assert summary["深圳"]["skipped_no_enriched"] == 1
    assert (
        not (mock_dir / "深圳.json").exists()
        or json.loads((mock_dir / "深圳.json").read_text(encoding="utf-8")) == []
    )


def test_dup_in_mock_skipped(tmp_paths):
    cache_path, mock_dir, enriched_path = tmp_paths
    key = "热门|113.95|22.54"
    oid = _gen_openshopid(key)
    # mock_dianping/深圳.json 已有同 openshopid 的 POI (模拟外部已晋升过)
    (mock_dir / "深圳.json").write_text(
        json.dumps(
            [
                {
                    "openshopid": oid,
                    "name": "热门",
                    "city": "深圳",
                    "longitude": 113.95,
                    "latitude": 22.54,
                    "categories": ["美食"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_cache(
        cache_path,
        {
            key: _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=10
            )
        },
    )
    summary = promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    assert summary["深圳"]["promoted"] == 0
    assert summary["深圳"]["skipped_dup_in_mock"] == 1
    # cache 标 promoted=true (防再算)
    cache_after = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache_after[key]["promoted"] is True
    # mock 没多出 POI
    mock = json.loads((mock_dir / "深圳.json").read_text(encoding="utf-8"))
    assert len(mock) == 1


def test_dry_run_does_not_write(tmp_paths):
    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "热门|113.95|22.54": _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=8
            )
        },
    )
    summary = promote_cache(
        min_seen_count=5,
        dry_run=True,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    assert summary["深圳"]["promoted"] == 1
    # 但 mock_dianping/{city}.json 不写
    assert not (mock_dir / "深圳.json").exists()
    # cache 也不改 (promoted flag 没写回)
    cache_after = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "promoted" not in cache_after["热门|113.95|22.54"]


def test_promoted_poi_passes_pydantic_validation(tmp_paths):
    """晋升进 mock_dianping 的 POI 必须能被 POI pydantic schema 解析 — 否则 test_full_mock_parse 会破."""
    from dianping.schemas import POI

    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "热门|113.95|22.54": _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=6
            )
        },
    )
    promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    mock = json.loads((mock_dir / "深圳.json").read_text(encoding="utf-8"))
    for raw in mock:
        POI.model_validate(raw)  # raise on fail


def test_enriched_label_schema_valid(tmp_paths):
    """晋升进 poi_enriched_labels.json 的 entry 必须能被 EnrichedLabel 解析."""
    from dianping.schemas import EnrichedLabel

    cache_path, mock_dir, enriched_path = tmp_paths
    _write_cache(
        cache_path,
        {
            "热门|113.95|22.54": _make_entry(
                name="热门", lng=113.95, lat=22.54, city="深圳", seen_count=6
            )
        },
    )
    promote_cache(
        min_seen_count=5,
        cache_path=cache_path,
        mock_dir=mock_dir,
        enriched_path=enriched_path,
    )
    enriched_all = json.loads(enriched_path.read_text(encoding="utf-8"))
    assert "深圳" in enriched_all
    for oid, en in enriched_all["深圳"].items():
        EnrichedLabel.model_validate(en)
