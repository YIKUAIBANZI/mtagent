"""Variant patches: 比对 main vs alternative variant 的 stops, 产出 diff.

被 _run_variants 流末调用, 输出给前端做 inline patch tag。纯函数, 无 IO。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dianping.schemas import Stop

VariantKind = Literal["low_queue", "interest_first"]

_VARIANT_LABEL: dict[VariantKind, tuple[str, str]] = {
    "low_queue": ("少排队", "⏳"),
    "interest_first": ("兴趣优先", "🌟"),
}


class PatchEndpoint(BaseModel):
    """Patch 两端的 POI 摘要 (前端渲染用)。"""

    openshopid: str
    name: str
    latitude: float = 0.0
    longitude: float = 0.0
    categories: list[str] = Field(default_factory=list)


class VariantPatch(BaseModel):
    """单个 stop_idx 的替换建议。"""

    model_config = ConfigDict(populate_by_name=True)

    stop_idx: int
    from_endpoint: PatchEndpoint = Field(alias="from")
    to_endpoint: PatchEndpoint = Field(alias="to")
    reason: str = ""


class VariantPatchSet(BaseModel):
    """一个 variant 对 main 的全部 diff。"""

    kind: VariantKind
    label: str
    icon: str
    patches: list[VariantPatch] = Field(default_factory=list)


def _stop_to_endpoint(stop: Stop) -> PatchEndpoint:
    return PatchEndpoint(
        openshopid=stop.poi.openshopid,
        name=stop.poi.name,
        latitude=stop.poi.latitude,
        longitude=stop.poi.longitude,
        categories=list(stop.poi.categories),
    )


def compute_variant_patches(
    main_stops: list[Stop],
    variant_stops: list[Stop],
    variant_kind: VariantKind,
) -> list[VariantPatch]:
    """逐 stop_idx 比对 openshopid; 不同即生成 1 个 VariantPatch.

    长度不一致时按较短长度截取（多出部分不计入 patches）。
    """
    n = min(len(main_stops), len(variant_stops))
    out: list[VariantPatch] = []
    for idx in range(n):
        m = main_stops[idx]
        v = variant_stops[idx]
        if m.poi.openshopid == v.poi.openshopid:
            continue
        out.append(
            VariantPatch(
                stop_idx=idx,
                from_endpoint=_stop_to_endpoint(m),
                to_endpoint=_stop_to_endpoint(v),
            )
        )
    return out


def build_variant_patch_set(
    main_stops: list[Stop],
    variant_stops: list[Stop],
    variant_kind: VariantKind,
) -> VariantPatchSet | None:
    """包装函数: 计算 patches, 若空则返回 None (degrade)。"""
    patches = compute_variant_patches(main_stops, variant_stops, variant_kind)
    if not patches:
        return None
    label, icon = _VARIANT_LABEL[variant_kind]
    return VariantPatchSet(
        kind=variant_kind,
        label=label,
        icon=icon,
        patches=patches,
    )
