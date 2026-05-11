"""Tests for DianpingClient persona_labels attachment."""

import json

import pytest

from dianping.client import DianpingClient
from dianping.schemas import POI


@pytest.fixture
def labels_file(tmp_path, monkeypatch):
    """Write a tmp poi_labels.json and point client to it via cwd."""
    data = {
        "西安": {
            "shop001": {
                "traveler_types": ["情侣"],
                "modifiers": {
                    "轻量体力": False,
                    "重文化": False,
                    "重美食": True,
                    "怕排队": True,
                },
            }
        }
    }
    (tmp_path / "data").mkdir()
    f = tmp_path / "data" / "poi_labels.json"
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return f


def test_load_labels_from_disk(labels_file):
    """Client loads labels file at construction."""
    c = DianpingClient(base_url="http://example", appkey="x", secret="y", session="z")
    assert "西安" in c._labels_cache
    assert "shop001" in c._labels_cache["西安"]


def test_load_labels_missing_file_returns_empty(monkeypatch, tmp_path):
    """Missing labels file → empty cache, no crash."""
    monkeypatch.chdir(tmp_path)  # No data/poi_labels.json here
    c = DianpingClient(base_url="http://example", appkey="x", secret="y", session="z")
    assert c._labels_cache == {}


def test_attach_labels_to_poi(labels_file):
    """_attach_labels() injects persona_labels into a POI matching openshopid."""
    c = DianpingClient(base_url="http://example", appkey="x", secret="y", session="z")
    poi = POI(
        openshopid="shop001", name="x", city="西安", latitude=34.0, longitude=108.0
    )
    c._attach_labels([poi], city="西安")
    assert poi.persona_labels is not None
    assert "情侣" in poi.persona_labels.traveler_types
    assert poi.persona_labels.modifiers["重美食"] is True
