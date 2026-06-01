"""Tests for UGC-derived risk tag distillation."""

from __future__ import annotations

import json

from scripts.distill_ugc_risk_tags import distill_ugc_risk_tags, infer_ugc_risks


def _poi(openshopid: str, *, review_tags=None, ugcs=None) -> dict:
    return {
        "openshopid": openshopid,
        "name": openshopid,
        "city": "上海",
        "reviewTags": [{"tag": tag, "hit": 10} for tag in (review_tags or [])],
        "ugcs": [{"content": content} for content in (ugcs or [])],
    }


def test_infer_ugc_risks_requires_explicit_evidence():
    inferred = infer_ugc_risks(
        _poi(
            "mock_1",
            review_tags=["排队较长"],
            ugcs=["周末人多，建议错峰。", "山路爬坡不少，步行多。"],
        )
    )

    assert set(inferred) == {"queue_heavy", "crowded_weekend", "walk_heavy"}
    assert inferred["queue_heavy"] == ["reviewTag:排队较长"]
    assert inferred["crowded_weekend"] == ["ugc:周末人多，建议错峰。"]
    assert inferred["walk_heavy"] == ["ugc:山路爬坡不少，步行多。"]


def test_infer_ugc_risks_does_not_treat_normal_walk_as_walk_heavy():
    assert infer_ugc_risks(_poi("mock_1", ugcs=["适合周末来散步放松。"])) == {}


def test_infer_ugc_risks_accepts_colloquial_crowd_comment():
    assert infer_ugc_risks(_poi("mock_1", ugcs=["人稍微多了点，但景色真的不错。"])) == {
        "crowded_weekend": ["ugc:人稍微多了点，但景色真的不错。"]
    }


def test_distill_ugc_risk_tags_updates_labels_and_writes_report(tmp_path):
    mock_dir = tmp_path / "mock_dianping"
    mock_dir.mkdir()
    (mock_dir / "上海.json").write_text(
        json.dumps(
            [
                _poi("mock_queue", review_tags=["排队较长"]),
                _poi("mock_plain", ugcs=["环境很好，适合慢慢逛。"]),
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
                    "mock_queue": {"risk_tags": [], "label_sources": ["rules:v1"]},
                    "mock_plain": {"risk_tags": [], "label_sources": ["rules:v1"]},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "ugc_risk_coverage.json"

    report = distill_ugc_risk_tags(
        mock_dir=mock_dir,
        enriched_path=enriched_path,
        report_path=report_path,
        cities=["上海"],
    )

    labels = json.loads(enriched_path.read_text(encoding="utf-8"))
    queue_label = labels["上海"]["mock_queue"]
    assert queue_label["risk_tags"] == ["queue_heavy"]
    assert "agent:risk_from_ugc:v1" in queue_label["label_sources"]
    assert labels["上海"]["mock_plain"]["risk_tags"] == []
    assert report["cities"]["上海"]["risk_tags"]["queue_heavy"] == 1
    assert report["cities"]["上海"]["evidence_samples"]["queue_heavy"] == [
        {"openshopid": "mock_queue", "evidence": ["reviewTag:排队较长"]}
    ]
