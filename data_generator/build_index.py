#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建索引文件 index.json 和 metadata.json
"""

import json
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data_generator/output")
MOCK_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data/mock_dianping")
MOCK_DIR.mkdir(parents=True, exist_ok=True)

CITIES = ["深圳", "上海", "西安"]

MALL_KEYWORDS = ["广场", "中心", "天地", "万象", "大悦城", "万达", "SKP", "太古里", "来福士", "IFC", "环贸", "海岸城", "壹方天地", "欢乐谷", "世界之窗", "民俗文化村"]


def build_index(pois: list, city: str) -> dict:
    """构建单城市索引"""
    index = {
        "by_category": {},
        "by_district": {},
        "by_mall": {},
        "by_keyword": {},
    }

    # 关键词池（用于 by_keyword）
    keyword_pool = [
        "火锅", "粤菜", "川菜", "湘菜", "日料", "西餐", "咖啡", "茶",
        "烤肉", "烧烤", "小龙虾", "海鲜", "自助餐", "快餐", "小吃",
        "景点", "公园", "博物馆", "展馆", "古迹", "历史",
        "购物", "商场", "超市", "便利店", "书店", "服装",
        "酒店", "民宿", "公寓", "客栈",
        "KTV", "电影院", "酒吧", "棋牌", "健身", "游泳", "SPA",
        "美容", "美发", "美甲", "化妆", "摄影",
        "亲子", "儿童", "乐园", "培训", "教育",
        "宠物", "动物", "医疗", "口腔", "眼科",
    ]

    for poi in pois:
        sid = poi["openshopid"]
        cats = poi.get("categories", [])
        name = poi.get("name", "")

        # by_category
        for cat in cats:
            if cat not in index["by_category"]:
                index["by_category"][cat] = []
            index["by_category"][cat].append(sid)

        # by_district
        district = poi.get("district", "")
        if district:
            if district not in index["by_district"]:
                index["by_district"][district] = []
            index["by_district"][district].append(sid)

        # by_mall
        if any(kw in name for kw in MALL_KEYWORDS):
            # 提取商场名（取第一个匹配的关键词附近的名词）
            mall_name = name
            if mall_name not in index["by_mall"]:
                index["by_mall"][mall_name] = []
            index["by_mall"][mall_name].append(sid)

        # by_keyword
        for kw in keyword_pool:
            if kw in name:
                if kw not in index["by_keyword"]:
                    index["by_keyword"][kw] = []
                index["by_keyword"][kw].append(sid)

    return index


def collect_stats(pois: list) -> dict:
    """收集城市统计信息"""
    cats = {}
    districts = {}
    total_review = 0
    total_price = 0
    food_count = 0
    black_pearl_count = 0

    for poi in pois:
        for cat in poi.get("categories", []):
            cats[cat] = cats.get(cat, 0) + 1
        district = poi.get("district", "")
        if district:
            districts[district] = districts.get(district, 0) + 1
        total_review += poi.get("reviewCount", 0)
        total_price += poi.get("avgprice", 0)
        if poi.get("categories", [''])[0] == "美食":
            food_count += 1
        black_pearl_count += poi.get("isBlackPearl", 0)

    return {
        "total": len(pois),
        "by_category": cats,
        "by_district": districts,
        "avg_review": total_review // len(pois) if pois else 0,
        "avg_price": total_price // len(pois) if pois else 0,
        "food_count": food_count,
        "black_pearl_count": black_pearl_count,
    }


def main():
    print("构建索引和元数据...")

    all_index = {}
    all_stats = {}

    for city in CITIES:
        print(f"\n处理 {city}...")
        city_file = OUTPUT_DIR / f"{city}.json"
        with open(city_file, 'r', encoding='utf-8') as f:
            pois = json.load(f)

        # 构建索引
        city_idx = build_index(pois, city)
        all_index[city] = city_idx

        # 收集统计
        all_stats[city] = collect_stats(pois)
        print(f"  总数: {all_stats[city]['total']}")
        print(f"  类目分布: {all_stats[city]['by_category']}")
        print(f"  黑珍珠: {all_stats[city]['black_pearl_count']}")

        # 复制到 mock_dianping
        mock_file = MOCK_DIR / f"{city}.json"
        with open(mock_file, 'w', encoding='utf-8') as f:
            json.dump(pois, f, ensure_ascii=False, indent=2)
        print(f"  已复制到: {mock_file}")

    # 保存 index.json
    index_file = MOCK_DIR / "index.json"
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(all_index, f, ensure_ascii=False, indent=2)
    print(f"\n索引已保存: {index_file}")

    # 保存 metadata.json
    total = sum(s["total"] for s in all_stats.values())
    metadata = {
        "generated_at": datetime.now().isoformat(),
        "total_count": total,
        "version": "v1",
        "source": "llm-mock-v1",
        "city_stats": all_stats,
        "categories_used": 20,
    }
    metadata_file = MOCK_DIR / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"元数据已保存: {metadata_file}")

    print(f"\n✓ 全部完成！")
    print(f"  目录: {MOCK_DIR}")
    print(f"  总 POI: {total} 条")


if __name__ == "__main__":
    main()
