"""Tests for deterministic, traceable POI decision signals."""

from __future__ import annotations

import json

from scripts.build_decision_signals import (
    build_signal,
    rebuild_decision_signals,
)


def _poi(openshopid: str, name: str, *, review_tags=None, ugcs=None, categories=None):
    return {
        "openshopid": openshopid,
        "name": name,
        "city": "上海",
        "categories": categories or ["餐饮服务", "中餐厅"],
        "reviewCount": 100,
        "reviewTags": [{"tag": tag, "hit": 10} for tag in (review_tags or [])],
        "ugcs": [{"content": content} for content in (ugcs or [])],
        "bookable": False,
    }


def test_build_signal_uses_traceable_review_tag_evidence():
    poi = _poi("mock_queue", "本帮菜馆", review_tags=["排队较长"])
    signal = build_signal(
        poi,
        label={"poi_role": "meal", "risk_tags": ["queue_heavy"]},
        fallback_poi_ids=["mock_quiet"],
    )

    assert signal["queue_risk"]["level"] == "high"
    assert signal["evidence"] == ["UGC 摘要：reviewTag「排队较长」"]
    assert signal["fallback_poi_ids"] == ["mock_quiet"]


def test_rebuild_decision_signals_writes_only_traceable_entries(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    (mock_dir / "上海.json").write_text(
        json.dumps(
            [
                _poi("mock_queue", "本帮菜馆", review_tags=["排队较长"]),
                _poi("mock_crowd", "外滩", review_tags=["人流较多"], categories=["风景名胜"]),
                _poi("mock_plain", "普通店", ugcs=["环境很好。"]),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    enriched_path = tmp_path / "poi_enriched_labels.json"
    enriched_path.write_text(
        json.dumps(
            {
                "上海": {
                    "mock_queue": {"poi_role": "meal", "risk_tags": ["queue_heavy"]},
                    "mock_crowd": {
                        "poi_role": "city_essential",
                        "risk_tags": ["crowded_weekend"],
                    },
                    "mock_plain": {"poi_role": "meal", "risk_tags": []},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    signals_path = tmp_path / "poi_decision_signals.json"
    report_path = tmp_path / "decision_signal_coverage.json"

    report = rebuild_decision_signals(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        signals_path=signals_path,
        report_path=report_path,
        city="上海",
    )

    signals = json.loads(signals_path.read_text(encoding="utf-8"))
    assert set(signals) == {"mock_queue", "mock_crowd"}
    assert signals["mock_crowd"]["queue_risk"]["label"] == "日落和节假日人流高"
    assert report["cities"]["上海"]["signal_count"] == 2
    assert report["cities"]["上海"]["traceable_evidence_count"] == 2
