"""Sweep test: every POI in mock_dianping/*.json must parse 100%."""

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("city", ["深圳", "上海", "西安"])
def test_all_pois_parse(city):
    from dianping.schemas import POI

    path = Path(f"data/mock_dianping/{city}.json")
    with path.open(encoding="utf-8") as f:
        pois = json.load(f)

    failures: list[tuple[int, str]] = []
    for i, p in enumerate(pois):
        try:
            POI.model_validate(p)
        except Exception as exc:
            failures.append((i, str(exc)[:200]))

    if failures:
        msg = f"{len(failures)}/{len(pois)} POIs failed to parse in {city}.json:\n"
        msg += "\n".join(f"  idx={i}: {err}" for i, err in failures[:5])
        pytest.fail(msg)
