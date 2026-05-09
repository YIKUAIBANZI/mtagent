#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_skeleton.py - 加载骨架数据
深圳/上海/西安的真实 POI 骨架，用于生成器的输入
"""

import json
import glob
import random
from pathlib import Path

DATA_ROOT = Path("/Users/yikuaibanz1/Desktop/sth/travel-agent/data")
CLEANED_DIR = DATA_ROOT / "cleaned"
RAW_DIR = DATA_ROOT / "raw"

# 20 个一级类目枚举（大众点评）
CATEGORY_ENUMS = [
    "美食", "K歌", "购物", "电影演出赛事", "休闲娱乐",
    "周边游", "宴会", "运动健身", "丽人", "结婚",
    "酒店", "爱车", "亲子", "学习培训", "生活服务",
    "医疗健康", "家居", "宠物", "榛果民宿", "交通枢纽"
]

# 类目映射：将骨架数据的 type 字段映射到一级类目
CATEGORY_MAP = {
    "景点": "休闲娱乐",
    "景区": "周边游",
    "公园": "休闲娱乐",
    "博物馆": "休闲娱乐",
    "展览馆": "休闲娱乐",
    "美食": "美食",
    "餐厅": "美食",
    "小吃": "美食",
    "火锅": "美食",
    "烧烤": "美食",
    "川菜": "美食",
    "粤菜": "美食",
    "湘菜": "美食",
    "日本料理": "美食",
    "韩国料理": "美食",
    "西餐": "美食",
    "咖啡": "美食",
    "酒吧": "美食",
    "商场": "购物",
    "购物中心": "购物",
    "超市": "购物",
    "便利店": "购物",
    "电影院": "电影演出赛事",
    "KTV": "K歌",
    "健身房": "运动健身",
    "游泳馆": "运动健身",
    "体育馆": "运动健身",
    "酒店": "酒店",
    "民宿": "榛果民宿",
    "医院": "医疗健康",
    "药店": "医疗健康",
    "银行": "生活服务",
    "加油站": "爱车",
    "停车场": "爱车",
    "4S店": "爱车",
    "美容": "丽人",
    "美发": "丽人",
    "美甲": "丽人",
    "亲子": "亲子",
    "儿童乐园": "亲子",
    "教育": "学习培训",
    "培训": "学习培训",
    "宠物店": "宠物",
    "宠物医院": "宠物",
    "家居": "家居",
    "装修": "家居",
    "婚庆": "结婚",
    "婚纱": "结婚",
    "婚礼": "宴会",
    "宴会": "宴会",
    "其他": "生活服务",
}

# 深圳商圈 anchor
SHENZHEN_DISTRICTS = {
    "福田区": {"lat": 22.543, "lng": 114.060, "anchor": "福田CBD"},
    "罗湖区": {"lat": 22.544, "lng": 114.116, "anchor": "东门老街"},
    "南山区": {"lat": 22.530, "lng": 113.930, "anchor": "华侨城/万象天地"},
    "宝安区": {"lat": 22.560, "lng": 113.890, "anchor": "宝安西乡"},
    "龙岗区": {"lat": 22.720, "lng": 114.250, "anchor": "龙岗大运"},
    "龙华区": {"lat": 22.700, "lng": 114.050, "anchor": "龙华壹方天地"},
}

SHANGHAI_DISTRICTS = {
    "浦东新区": {"lat": 31.220, "lng": 121.540, "anchor": "陆家嘴"},
    "黄浦区": {"lat": 31.230, "lng": 121.490, "anchor": "南京路"},
    "静安区": {"lat": 31.230, "lng": 121.460, "anchor": "静安寺"},
    "徐汇区": {"lat": 31.200, "lng": 121.430, "anchor": "徐家汇"},
    "长宁区": {"lat": 31.220, "lng": 121.400, "anchor": "武康路"},
    "杨浦区": {"lat": 31.270, "lng": 121.520, "anchor": "五角场"},
}

XIAN_DISTRICTS = {
    "碑林区": {"lat": 34.250, "lng": 108.940, "anchor": "钟楼"},
    "莲湖区": {"lat": 34.260, "lng": 108.930, "anchor": "回民街"},
    "雁塔区": {"lat": 34.220, "lng": 108.950, "anchor": "大雁塔/大唐不夜城"},
    "新城区": {"lat": 34.270, "lng": 108.950, "anchor": "永宁门"},
    "长安区": {"lat": 34.160, "lng": 108.990, "anchor": "小寨赛格"},
}


def load_cleaned_pois(city: str) -> list:
    """加载 cleaned 目录下的城市 POI"""
    pattern = CLEANED_DIR / f"{city}_*.json"
    files = glob.glob(str(pattern))
    if not files:
        return []
    pois = []
    for f in files:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            if isinstance(data, list):
                pois.extend(data)
            else:
                pois.append(data)
    return pois


def load_amap_raw(city: str) -> list:
    """从 amap raw 补数据"""
    pattern = RAW_DIR / f"amap_{city}_*.json"
    files = glob.glob(str(pattern))
    pois = []
    for f in files:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            if isinstance(data, list):
                pois.extend(data)
            else:
                pois.append(data)
    return pois


def load_xhs_corpus(city: str = "深圳") -> list:
    """加载小红书语料，用于学习 UGC 文风"""
    pattern = RAW_DIR / f"xhs_{city}_*.json"
    files = glob.glob(str(pattern))
    notes = []
    for f in files:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            if isinstance(data, list):
                notes.extend(data)
    return notes


def map_type_to_category(poi_type: str) -> str:
    """将 POI type 映射到一级类目"""
    # 先精确匹配
    if poi_type in CATEGORY_MAP:
        return CATEGORY_MAP[poi_type]
    # 再模糊匹配
    for key, cat in CATEGORY_MAP.items():
        if key in poi_type or poi_type in key:
            return cat
    return "美食"  # 默认


def safe_float(val, default=0.0):
    """安全转换为 float，空值或无效值返回默认值"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def enrich_poi_from_skeleton(poi: dict, city: str) -> dict:
    """将骨架 POI 转换为生成器需要的格式"""
    name = poi.get("name", "")
    poi_type = poi.get("type", poi.get("poi_type", "其他"))

    # 从 poi_type 提取叶子类目
    if "poi_type" in poi and ";" in poi["poi_type"]:
        # 高德格式：购物服务;商场;普通商场
        parts = [p.strip() for p in poi["poi_type"].split(";")]
        leaf_category = parts[-1] if parts else poi_type
        parent_category = map_type_to_category(parts[0] if parts else poi_type)
    else:
        leaf_category = poi_type
        parent_category = map_type_to_category(poi_type)

    result = {
        "name": name,
        "branch_name": "",
        "type": poi_type,
        "leaf_category": leaf_category,
        "parent_category": parent_category,
        "lat": safe_float(poi.get("lat")),
        "lng": safe_float(poi.get("lng")),
        "district": poi.get("district", ""),
        "address": poi.get("address", poi.get("body", "")),
        "city": city,
        "rating": poi.get("rating"),
        "warnings": poi.get("warnings", ""),
        "telephone": poi.get("tel", ""),
    }
    return result


def build_skeleton(city: str) -> list:
    """
    构建城市的完整骨架数据池
    cleaned 数据不够 800 则从 amap raw 补
    """
    skeleton = []

    # 1. 加载 cleaned 数据
    cleaned = load_cleaned_pois(city)
    for poi in cleaned:
        enriched = enrich_poi_from_skeleton(poi, city)
        enriched["source"] = "cleaned"
        skeleton.append(enriched)

    # 2. cleaned 不够则从 amap raw 补
    if len(skeleton) < 800:
        amap = load_amap_raw(city)
        for poi in amap:
            enriched = enrich_poi_from_skeleton(poi, city)
            enriched["source"] = "amap"
            skeleton.append(enriched)

    print(f"[load_skeleton] {city}: cleaned={len(cleaned)}, total skeleton={len(skeleton)}")
    return skeleton


if __name__ == "__main__":
    sz = build_skeleton("深圳")
    print(f"深圳骨架: {len(sz)} 条")
    if sz:
        print(json.dumps(sz[0], ensure_ascii=False, indent=2))
