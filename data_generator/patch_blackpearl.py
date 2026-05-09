#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_blackpearl.py - 为高端餐饮设置黑珍珠标记（不改 POI 名字）
"""

import json
import random
from pathlib import Path

MOCK_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data/mock_dianping")
OUTPUT_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data_generator/output")
CITIES = ["深圳", "上海", "西安"]

# 高端关键词（用于识别可能是高端餐饮的 POI）
HIGH_END_KEYWORDS = [
    "海鲜", "火锅", "牛排", "日料", "会席", "怀石",
    "粤菜", "本帮菜", "私房菜", "铁板烧", "omakase",
    "寿司", "刺身", "烧烤", "烤肉", "大餐", "盛宴",
    "酒家", "公馆", "轩", "楼", "阁", "府", "记", "园",
]


def patch_city(city: str) -> int:
    """为高端美食设置黑珍珠标记"""
    city_file = OUTPUT_DIR / f"{city}.json"
    with open(city_file, 'r', encoding='utf-8') as f:
        pois = json.load(f)

    bp_limit = 30

    # 找美食类 POI，按高端程度排序
    food_pois = [
        p for p in pois
        if p.get("categories", [""])[0] == "美食" and p.get("isBlackPearl", 0) == 0
    ]

    # 计算高端得分：高价 * 0.4 + 高星 * 0.3 + 高评论 * 0.2 + 关键词 * 0.1
    scored = []
    for p in food_pois:
        price = p.get("avgprice", 0)
        star = p.get("star", 0)
        review = p.get("reviewCount", 0)
        name = p.get("name", "")

        keyword_bonus = 1 if any(kw in name for kw in HIGH_END_KEYWORDS) else 0
        score = price * 0.4 + star * 2000 + (review // 10) * 0.2 + keyword_bonus * 1000
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    bp_count = 0
    for score, poi in scored:
        if bp_count >= bp_limit:
            break

        price = poi.get("avgprice", 0)
        star = poi.get("star", 0)

        # 条件：人均 >= 300 或（人均 >= 200 且星级 >= 4.5）
        if price >= 300 or (price >= 200 and star >= 4.5):
            poi["isBlackPearl"] = 1
            poi["avgprice"] = max(price, random.randint(500, 2000))
            bp_count += 1

    print(f"{city}: 黑珍珠 {bp_count} 个")

    # 保存
    with open(city_file, 'w', encoding='utf-8') as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)

    return bp_count


def main():
    print("设置黑珍珠标记...")
    total_bp = 0
    for city in CITIES:
        count = patch_city(city)
        total_bp += count

    print(f"\n✓ 总计黑珍珠: {total_bp} 个")


if __name__ == "__main__":
    main()
