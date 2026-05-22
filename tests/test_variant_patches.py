"""compute_variant_patches: 比对 main vs variant 的 stops, 输出 diff list."""

from __future__ import annotations

from dianping.schemas import POI, Stop, TimeSlot
from datetime import time as _time

from agents.variant_patches import (
    compute_variant_patches,
)


def _mk_poi(openshopid: str, name: str = "店", city: str = "南昌") -> POI:
    return POI(
        openshopid=openshopid,
        name=name,
        city=city,
        latitude=28.7,
        longitude=115.85,
        categories=["美食"],
    )


def _mk_stop(openshopid: str, slot_name: str = "午饭") -> Stop:
    return Stop(
        poi=_mk_poi(openshopid),
        slot=TimeSlot(name=slot_name, start=_time(12, 0), end=_time(13, 0)),
        arrival_time=_time(12, 0),
        leave_time=_time(13, 0),
    )


def test_identical_stops_return_empty():
    main = [_mk_stop("A"), _mk_stop("B"), _mk_stop("C")]
    variant = [_mk_stop("A"), _mk_stop("B"), _mk_stop("C")]
    patches = compute_variant_patches(main, variant, "low_queue")
    assert patches == []


def test_single_stop_diff_produces_one_patch():
    main = [_mk_stop("A"), _mk_stop("B"), _mk_stop("C")]
    variant = [_mk_stop("A"), _mk_stop("B2"), _mk_stop("C")]
    patches = compute_variant_patches(main, variant, "low_queue")
    assert len(patches) == 1
    p = patches[0]
    assert p.stop_idx == 1
    assert p.from_endpoint.openshopid == "B"
    assert p.to_endpoint.openshopid == "B2"


def test_multi_stop_diff_preserves_order():
    main = [_mk_stop("A"), _mk_stop("B"), _mk_stop("C"), _mk_stop("D")]
    variant = [_mk_stop("A2"), _mk_stop("B"), _mk_stop("C2"), _mk_stop("D2")]
    patches = compute_variant_patches(main, variant, "interest_first")
    assert [p.stop_idx for p in patches] == [0, 2, 3]


def test_variant_shorter_truncates_to_min():
    main = [_mk_stop("A"), _mk_stop("B"), _mk_stop("C")]
    variant = [_mk_stop("A"), _mk_stop("B2")]  # 比 main 短 1
    patches = compute_variant_patches(main, variant, "low_queue")
    assert len(patches) == 1
    assert patches[0].stop_idx == 1


def test_variant_longer_ignores_extra():
    main = [_mk_stop("A"), _mk_stop("B")]
    variant = [_mk_stop("A"), _mk_stop("B2"), _mk_stop("EXTRA")]  # 比 main 长 1
    patches = compute_variant_patches(main, variant, "low_queue")
    assert len(patches) == 1
    assert patches[0].stop_idx == 1


def test_build_set_returns_none_on_empty_patches():
    main = [_mk_stop("A"), _mk_stop("B")]
    variant = [_mk_stop("A"), _mk_stop("B")]
    from agents.variant_patches import build_variant_patch_set

    result = build_variant_patch_set(main, variant, "low_queue")
    assert result is None


def test_build_set_returns_labeled_set_on_diff():
    from agents.variant_patches import build_variant_patch_set

    main = [_mk_stop("A"), _mk_stop("B")]
    variant = [_mk_stop("A"), _mk_stop("B2")]
    result = build_variant_patch_set(main, variant, "interest_first")
    assert result is not None
    assert result.kind == "interest_first"
    assert result.label == "兴趣优先"
    assert result.icon == "🌟"
    assert len(result.patches) == 1
