"""Tests for canonical POI label alignment."""

from __future__ import annotations

import json

from scripts.build_canonical_pois import build_canonical_pois


def _poi(openshopid: str, name: str) -> dict:
    return {
        "openshopid": openshopid,
        "name": name,
        "city": "上海",
        "latitude": 31.23,
        "longitude": 121.47,
        "categories": ["风景名胜"],
        "reviewTags": [{"tag": "适合拍照", "hit": 10}],
        "ugcs": [{"content": "风景很美，值得专程来一趟。"}],
    }


def test_build_canonical_pois_repairs_missing_mock_ids_and_drops_orphans(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    (mock_dir / "上海.json").write_text(
        json.dumps(
            [_poi("mock_keep", "外滩"), _poi("mock_generate", "豫园")],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    enriched_path = tmp_path / "poi_enriched_labels.json"
    enriched_path.write_text(
        json.dumps(
            {
                "上海": {
                    "mock_keep": {
                        "poi_role": "city_essential",
                        "planning_tags": ["landmark"],
                        "risk_tags": [],
                    },
                    "B001_ORPHAN": {
                        "poi_role": "fallback",
                        "planning_tags": [],
                        "risk_tags": [],
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "canonical_coverage.json"

    report = build_canonical_pois(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        report_path=report_path,
    )

    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    assert set(enriched["上海"]) == {"mock_keep", "mock_generate"}
    assert enriched["上海"]["mock_keep"]["planning_tags"] == ["landmark"]
    assert "rules:v1" in enriched["上海"]["mock_generate"]["label_sources"]

    city_report = report["cities"]["上海"]
    assert city_report["mock_poi_count"] == 2
    assert city_report["attached_before"] == 1
    assert city_report["generated_missing"] == 1
    assert city_report["dropped_orphans"] == 1
    assert city_report["attached_after"] == 2
    assert city_report["attach_rate_after"] == 1.0
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_build_canonical_pois_rebuild_refreshes_existing_labels(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    poi = _poi("mock_food", "本帮菜馆")
    poi["categories"] = ["餐饮服务", "中餐厅"]
    (mock_dir / "上海.json").write_text(
        json.dumps([poi], ensure_ascii=False),
        encoding="utf-8",
    )
    enriched_path = tmp_path / "poi_enriched_labels.json"
    enriched_path.write_text(
        json.dumps(
            {
                "上海": {
                    "mock_food": {
                        "poi_role": "fallback",
                        "planning_tags": [],
                        "risk_tags": [],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_canonical_pois(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        report_path=tmp_path / "canonical_coverage.json",
        rebuild=True,
    )

    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    assert enriched["上海"]["mock_food"]["poi_role"] == "meal"
    assert "food" in enriched["上海"]["mock_food"]["planning_tags"]
    assert report["cities"]["上海"]["rebuilt_labels"] == 1


def test_build_canonical_pois_can_limit_delivery_cities(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    (mock_dir / "上海.json").write_text(
        json.dumps([_poi("mock_shanghai", "外滩")], ensure_ascii=False),
        encoding="utf-8",
    )
    (mock_dir / "南昌.json").write_text(
        json.dumps([_poi("mock_nanchang", "滕王阁")], ensure_ascii=False),
        encoding="utf-8",
    )
    enriched_path = tmp_path / "poi_enriched_labels.json"
    enriched_path.write_text(
        json.dumps({"南昌": {"mock_nanchang": {}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = build_canonical_pois(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        report_path=tmp_path / "canonical_coverage.json",
        cities=["上海"],
    )

    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    assert list(report["cities"]) == ["上海"]
    assert list(enriched) == ["上海"]
