#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_rebalanced.py - 类目调整后的综合修复
1. dishs：美食类必须有 >= 3 道菜，非美食类清空 dishs
2. isBlackPearl：重置并重新计算（每城上限 30）
"""

import json
import random
from pathlib import Path

OUTPUT_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data_generator/output")
CITIES = ["深圳", "上海", "西安"]

DISH_POOL = [
    ("招牌脆皮烧鹅", 68, 1280),
    ("乳鸽皇", 42, 980),
    ("虾饺皇", 38, 850),
    ("流沙包", 28, 760),
    ("菠萝包", 12, 650),
    ("叉烧包", 18, 620),
    ("杨枝甘露", 32, 580),
    ("牛肉火锅", 98, 520),
    ("手切肥牛", 78, 480),
    ("毛肚", 48, 450),
    ("鹅肠", 42, 380),
    ("嫩滑牛肉", 58, 350),
    ("酸菜鱼", 68, 420),
    ("水煮鱼", 78, 380),
    ("回锅肉", 38, 320),
    ("麻婆豆腐", 28, 280),
    ("宫保鸡丁", 35, 260),
    ("红烧肉", 48, 240),
    ("糖醋里脊", 38, 220),
    ("蒜蓉蒸扇贝", 58, 200),
    ("白灼虾", 68, 190),
    ("清蒸鲈鱼", 72, 180),
    ("东坡肉", 58, 170),
    ("佛跳墙", 288, 150),
    ("寿司拼盘", 128, 140),
    ("刺身拼盘", 198, 130),
    ("天妇罗", 68, 120),
    ("拉面", 48, 110),
    ("炸鸡", 38, 100),
    ("港式奶茶", 22, 90),
    ("鱼丸粗面", 28, 80),
    ("双皮奶", 18, 70),
]


def fix_dishes(pois: list):
    """修复 dishs 字段"""
    fixed = 0
    for poi in pois:
        cat = poi.get("categories", [""])[0] if poi.get("categories") else "美食"
        if cat == "美食":
            if len(poi.get("dishs", [])) < 3:
                # 随机选 3-5 道菜
                num_dishes = random.randint(3, 5)
                selected = random.sample(DISH_POOL, min(num_dishes, len(DISH_POOL)))
                poi["dishs"] = [
                    {"dishName": name, "picUrl": "", "price": price, "recommendCount": rc}
                    for name, price, rc in selected
                ]
                fixed += 1
        else:
            # 非美食类清空 dishs
            poi["dishs"] = []
    return fixed


def fix_blackpearl(pois: list, city: str) -> int:
    """重置并重新计算黑珍珠，每城上限 30"""
    # 重置全部为 0
    for poi in pois:
        poi["isBlackPearl"] = 0

    # 找高端美食候选
    food_pois = [
        (p, p.get("avgprice", 0) * 0.5 + p.get("star", 0) * 2000 + p.get("reviewCount", 0) // 10 * 0.1)
        for p in pois
        if p.get("categories", [""])[0] == "美食"
    ]
    food_pois.sort(key=lambda x: x[1], reverse=True)

    bp_limit = 30
    bp_count = 0
    for poi, score in food_pois:
        if bp_count >= bp_limit:
            break
        price = poi.get("avgprice", 0)
        star = poi.get("star", 0)
        # 条件：人均 >= 300 或（人均 >= 200 且星级 >= 4.5）
        if price >= 300 or (price >= 200 and star >= 4.5):
            poi["isBlackPearl"] = 1
            poi["avgprice"] = max(price, random.randint(500, 2000))
            bp_count += 1

    return bp_count


def main():
    total_bp = 0
    for city in CITIES:
        city_file = OUTPUT_DIR / f"{city}.json"
        with open(city_file, 'r', encoding='utf-8') as f:
            pois = json.load(f)

        print(f"\n处理 {city}:")
        fixed_dishes = fix_dishes(pois)
        print(f"  修复 dishs: {fixed_dishes} 个 POI")

        bp_count = fix_blackpearl(pois, f"{city}")
        print(f"  黑珍珠: {bp_count} 个")
        total_bp += bp_count

        with open(city_file, 'w', encoding='utf-8') as f:
            json.dump(pois, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 共 {total_bp} 个黑珍珠")


if __name__ == "__main__":
    main()
