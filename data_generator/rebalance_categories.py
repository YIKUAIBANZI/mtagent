#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebalance_categories.py - 调整类目分布到目标范围
"""

import json
import random
from pathlib import Path

MOCK_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data/mock_dianping")
OUTPUT_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data_generator/output")
CITIES = ["深圳", "上海", "西安"]

# 目标类目分布
TARGET_DIST = {
    "美食": 0.50,
    "休闲娱乐": 0.20,
    "购物": 0.10,
    "亲子": 0.05,
    "丽人": 0.05,
    "酒店": 0.05,
}

# 类目映射
CATEGORY_ALIASES = {
    "景点": "休闲娱乐",
    "景区": "周边游",
    "公园": "休闲娱乐",
    "博物馆": "休闲娱乐",
    "展览馆": "休闲娱乐",
    "电影院": "电影演出赛事",
    "KTV": "K歌",
    "运动健身": "运动健身",
    "丽人": "丽人",
    "亲子": "亲子",
    "酒店": "酒店",
    "美食": "美食",
}


def get_primary_category(poi: dict) -> str:
    """获取主类目"""
    cats = poi.get("categories", [])
    if cats:
        cat = cats[0]
        return CATEGORY_ALIASES.get(cat, cat)
    return "美食"


def rebalance_city(city: str) -> dict:
    """重新平衡城市类目分布"""
    city_file = OUTPUT_DIR / f"{city}.json"
    with open(city_file, 'r', encoding='utf-8') as f:
        pois = json.load(f)

    total = len(pois)
    print(f"\n{city}: 当前分布（调整前）")
    current_dist = {}
    for poi in pois:
        cat = get_primary_category(poi)
        current_dist[cat] = current_dist.get(cat, 0) + 1

    for cat, count in sorted(current_dist.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        target = TARGET_DIST.get(cat, 0) * 100
        print(f"  {cat}: {pct:.1f}% (目标 {target:.0f}%)")

    # 调整策略：把过多的"休闲娱乐"改成其他类目，把过少的"美食"补足
    # 统计需要转换的数量
    target_counts = {cat: int(total * pct) for cat, pct in TARGET_DIST.items()}

    # 需要减少的类目 -> 需要增加的类目
    excess = {}
    deficit = {}
    for cat, target in target_counts.items():
        current = current_dist.get(cat, 0)
        diff = current - target
        if diff > 0:
            excess[cat] = diff
        elif diff < 0:
            deficit[cat] = -diff

    print(f"\n需要从 excess 类目转换到 deficit 类目")

    # 找出可以转换的 POI（generated 类型的）
    convertible = {cat: [] for cat in excess}
    for i, poi in enumerate(pois):
        cat = get_primary_category(poi)
        if cat in convertible and poi.get("source") == "generated":
            convertible[cat].append(i)

    # 执行转换（包括骨架 POI）
    conversions = 0
    # 收集所有 excess 类目的 POI
    all_convertible = {cat: [] for cat in excess}
    for i, poi in enumerate(pois):
        cat = get_primary_category(poi)
        if cat in all_convertible:
            all_convertible[cat].append(i)

    # 对每个 excess 类目，随机选择 POI 转换为 deficit 类目
    for from_cat in list(excess.keys()):
        needed = excess[from_cat]
        indices = all_convertible.get(from_cat, [])
        random.shuffle(indices)

        deficit_cats = [c for c, v in deficit.items() if v > 0]
        if not deficit_cats:
            continue

        for idx in indices[:needed]:
            poi = pois[idx]
            to_cat = random.choice(deficit_cats)
            poi["categories"] = [to_cat]
            poi["parent_category"] = to_cat
            poi["type"] = to_cat
            deficit[to_cat] -= 1
            conversions += 1
            if deficit.get(to_cat, 0) <= 0:
                deficit_cats.remove(to_cat)
                if not deficit_cats:
                    break

    # 重新统计
    new_dist = {}
    for poi in pois:
        cat = get_primary_category(poi)
        new_dist[cat] = new_dist.get(cat, 0) + 1

    print(f"\n{city}: 调整后分布")
    for cat, count in sorted(new_dist.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        target = TARGET_DIST.get(cat, 0) * 100
        print(f"  {cat}: {pct:.1f}% (目标 {target:.0f}%)")

    # 保存
    with open(city_file, 'w', encoding='utf-8') as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)

    print(f"转换了 {conversions} 个 POI 的类目")
    return pois


def main():
    for city in CITIES:
        rebalance_city(city)


if __name__ == "__main__":
    main()
