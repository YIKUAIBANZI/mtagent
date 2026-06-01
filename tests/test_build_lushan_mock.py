"""Tests for the deterministic Lushan mock-data builder."""

from __future__ import annotations

import json

from scripts.build_lushan_mock import build_lushan_mock, transform_amap_poi


def _amap_poi(
    poi_id: str,
    name: str,
    *,
    location: str = "115.973108,29.522059",
    poi_type: str = "风景名胜;风景名胜;国家级景点",
) -> dict:
    return {
        "id": poi_id,
        "name": name,
        "type": poi_type,
        "address": "庐山风景名胜区内",
        "location": location,
        "adname": "庐山市",
        "tel": "0792-1234567",
        "biz_ext": {"opentime": "08:00-18:00"},
    }


def test_transform_amap_poi_preserves_real_location_and_adds_mountain_ugc():
    poi = transform_amap_poi(_amap_poi("B001", "三叠泉"), ordinal=0)

    assert poi["openshopid"] == "amap_B001"
    assert poi["city"] == "庐山"
    assert poi["name"] == "三叠泉"
    assert poi["longitude"] == 115.973108
    assert poi["latitude"] == 29.522059
    assert poi["categories"] == ["风景名胜", "风景名胜", "国家级景点"]
    assert any("爬坡" in ugc["content"] for ugc in poi["ugcs"])


def test_build_lushan_mock_deduplicates_and_rebuilds_five_city_index(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    for city in ["深圳", "上海", "北京", "西安", "南昌"]:
        (mock_dir / f"{city}.json").write_text(
            json.dumps(
                [
                    {
                        "openshopid": f"mock_{city}",
                        "city": city,
                        "categories": ["风景名胜"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    report = build_lushan_mock(
        raw_pois=[
            _amap_poi("B001", "三叠泉"),
            _amap_poi("B001", "三叠泉"),
            _amap_poi("B002", "庐山索道", poi_type="交通设施服务;交通服务相关"),
            _amap_poi("B003", "庐山站", location="115.878938,29.596473"),
        ],
        mock_dir=mock_dir,
        metadata_path=mock_dir / "metadata.json",
        index_path=mock_dir / "index.json",
        report_path=tmp_path / "lushan_build_report.json",
    )

    lushan = json.loads((mock_dir / "庐山.json").read_text(encoding="utf-8"))
    index = json.loads((mock_dir / "index.json").read_text(encoding="utf-8"))
    metadata = json.loads((mock_dir / "metadata.json").read_text(encoding="utf-8"))

    assert [poi["name"] for poi in lushan] == ["三叠泉", "庐山索道"]
    assert {poi["city"] for poi in index} == {"深圳", "上海", "北京", "西安", "庐山"}
    assert "南昌" not in metadata["city_stats"]
    assert report["raw_poi_count"] == 4
    assert report["accepted_poi_count"] == 2
    assert report["rejected_poi_count"] == 1
    assert report["duplicate_poi_count"] == 1
