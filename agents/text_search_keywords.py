"""按 traveler_type 自动扩 amap text_search 类目关键词.

哈尔滨 demo 暴露: 用户 must_visit 只填地标, required_slots 又是 [],
text_search 池窄 → 三 variant 无差分材料. 这个模块按 traveler_type
注入 2-3 个高 ROI 类目词, 扩大候选池让 variant bias 真正发挥.

设计原则:
- 只加"主餐 + 1 个氛围品类", 不堆砌全品类避免 noise
- 商务保持极简 (出差节奏紧, 不要发散)
"""

from __future__ import annotations


TRAVELER_CATEGORY_HINTS: dict[str, list[str]] = {
    "情侣": ["咖啡", "西餐"],
    "家庭亲子": ["亲子餐厅", "冰激凌"],
    "银发": ["老字号", "茶馆"],
    "独行": ["书店", "咖啡"],
    "商务": [],
    "朋友团": ["火锅", "酒吧"],
}


def expand_keywords_for_traveler(traveler_type: str, existing: list[str]) -> list[str]:
    """把 traveler_type 对应的类目词追加到 existing, 去重.

    - traveler_type 不在字典时, 直接返回 existing 不变
    - 已存在的 keyword 不重复注入
    - 保持原 list 顺序, 新关键词追加到末尾
    """
    hints = TRAVELER_CATEGORY_HINTS.get(traveler_type, [])
    if not hints:
        return existing
    out = list(existing)
    for h in hints:
        if h not in out:
            out.append(h)
    return out
