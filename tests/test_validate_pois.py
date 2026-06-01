"""Tests for the five-city offline data validator."""

from __future__ import annotations

import json

from scripts.validate_pois import validate_pois


def _poi(openshopid: str, city: str, *, name: str = "景点") -> dict:
    return {
        "openshopid": openshopid,
        "name": name,
        "city": city,
        "latitude": 29.55 if city == "庐山" else 31.23,
        "longitude": 115.98 if city == "庐山" else 121.47,
        "categories": ["风景名胜"],
        "reviewTags": [{"tag": "排队较长", "hit": 10}],
        "ugcs": [{"content": "周末可能排队。"}],
    }


def _write_fixture(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    shanghai = _poi("mock_shanghai", "上海")
    lushan = _poi("amap_lushan", "庐山", name="三叠泉")
    (mock_dir / "上海.json").write_text(json.dumps([shanghai], ensure_ascii=False))
    (mock_dir / "庐山.json").write_text(json.dumps([lushan], ensure_ascii=False))
    (mock_dir / "index.json").write_text(json.dumps([shanghai, lushan], ensure_ascii=False))
    (mock_dir / "metadata.json").write_text(
        json.dumps(
            {
                "total_count": 2,
                "city_stats": {"上海": {"total": 1}, "庐山": {"total": 1}},
            },
            ensure_ascii=False,
        )
    )
    enriched_path = tmp_path / "poi_enriched_labels.json"
    enriched_path.write_text(
        json.dumps(
            {
                "上海": {"mock_shanghai": {"risk_tags": ["queue_heavy"]}},
                "庐山": {"amap_lushan": {"risk_tags": ["walk_heavy", "queue_heavy"]}},
            },
            ensure_ascii=False,
        )
    )
    signals_path = tmp_path / "poi_decision_signals.json"
    signals_path.write_text(
        json.dumps(
            {
                "mock_shanghai": {
                    "evidence": ["UGC 摘要：reviewTag「排队较长」"],
                    "fallback_poi_ids": [],
                }
            },
            ensure_ascii=False,
        )
    )
    return mock_dir, enriched_path, signals_path


def test_validate_pois_accepts_consistent_delivery_bundle(tmp_path):
    mock_dir, enriched_path, signals_path = _write_fixture(tmp_path)

    report = validate_pois(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        signals_path=signals_path,
        report_path=tmp_path / "validation_report.json",
        cities=["上海", "庐山"],
        min_lushan_pois=1,
    )

    assert report["valid"] is True
    assert report["errors"] == []
    assert report["cities"]["庐山"]["attach_rate"] == 1.0
    assert report["decision_signals"]["traceable_count"] == 1


def test_validate_pois_rejects_duplicate_ids_and_untraceable_evidence(tmp_path):
    mock_dir, enriched_path, signals_path = _write_fixture(tmp_path)
    lushan_path = mock_dir / "庐山.json"
    lushan = json.loads(lushan_path.read_text())
    lushan[0]["openshopid"] = "mock_shanghai"
    lushan_path.write_text(json.dumps(lushan, ensure_ascii=False))
    index = json.loads((mock_dir / "index.json").read_text())
    index[1]["openshopid"] = "mock_shanghai"
    (mock_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    signals_path.write_text(
        json.dumps(
            {
                "mock_shanghai": {
                    "evidence": ["UGC 摘要：评论「并不存在的原文」"],
                    "fallback_poi_ids": [],
                }
            },
            ensure_ascii=False,
        )
    )

    report = validate_pois(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        signals_path=signals_path,
        report_path=tmp_path / "validation_report.json",
        cities=["上海", "庐山"],
        min_lushan_pois=1,
    )

    assert report["valid"] is False
    assert any("duplicate openshopid" in error for error in report["errors"])
    assert any("untraceable evidence" in error for error in report["errors"])


def test_validate_pois_rejects_city_bounds_queue_and_price_contradictions(tmp_path):
    mock_dir, enriched_path, signals_path = _write_fixture(tmp_path)
    shanghai_path = mock_dir / "上海.json"
    shanghai = json.loads(shanghai_path.read_text())
    shanghai[0]["latitude"] = 29.0
    shanghai[0]["avgprice"] = 888
    shanghai[0]["reviewTags"].append({"tag": "性价比高", "hit": 8})
    shanghai_path.write_text(json.dumps(shanghai, ensure_ascii=False))
    index = json.loads((mock_dir / "index.json").read_text())
    index[0] = shanghai[0]
    (mock_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    enriched = json.loads(enriched_path.read_text())
    enriched["上海"]["mock_shanghai"]["risk_tags"] = []
    enriched_path.write_text(json.dumps(enriched, ensure_ascii=False))

    report = validate_pois(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        signals_path=signals_path,
        report_path=tmp_path / "validation_report.json",
        cities=["上海", "庐山"],
        min_lushan_pois=1,
    )

    assert report["valid"] is False
    assert any("outside 上海 bounds" in error for error in report["errors"])
    assert any("queue evidence without queue_heavy" in error for error in report["errors"])
    assert any("high price conflicts with value tag" in error for error in report["errors"])
