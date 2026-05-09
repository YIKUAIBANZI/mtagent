#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate.py - 美团 Hackathon 模拟数据生成器 主入口

用法:
    python generate.py --city 深圳 --limit 50  # 小批量测试
    python generate.py --city 深圳 --limit 800  # 完整生成
"""

import argparse
import json
import os
import random
import re
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

# 内部模块
from load_skeleton import build_skeleton, load_xhs_corpus, CATEGORY_ENUMS, map_type_to_category
import schemas as SCH
from schemas import POSITIVE_TAGS, NEGATIVE_TAGS

# ============ 配置 ============
GEN_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data_generator")
OUTPUT_DIR = GEN_DIR / "output"
MOCK_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data/mock_dianping")
PROMPTS_DIR = GEN_DIR / "prompts"

# 城市商圈 anchor（POI 聚簇中心）
CITY_ANCHORS = {
    "深圳": [
        {"name": "福田CBD", "lat": 22.543, "lng": 114.060, "district": "福田区"},
        {"name": "华强北", "lat": 22.543, "lng": 114.086, "district": "福田区"},
        {"name": "海岸城", "lat": 22.527, "lng": 113.928, "district": "南山区"},
        {"name": "万象天地", "lat": 22.529, "lng": 113.938, "district": "南山区"},
        {"name": "华侨城", "lat": 22.534, "lng": 113.975, "district": "南山区"},
        {"name": "蛇口", "lat": 22.489, "lng": 113.917, "district": "南山区"},
        {"name": "东门老街", "lat": 22.544, "lng": 114.116, "district": "罗湖区"},
        {"name": "龙华壹方天地", "lat": 22.700, "lng": 114.050, "district": "龙华区"},
        {"name": "龙岗大运", "lat": 22.720, "lng": 114.250, "district": "龙岗区"},
        {"name": "宝安西乡", "lat": 22.560, "lng": 113.890, "district": "宝安区"},
    ],
    "上海": [
        {"name": "陆家嘴", "lat": 31.220, "lng": 121.540, "district": "浦东新区"},
        {"name": "南京路步行街", "lat": 31.230, "lng": 121.475, "district": "黄浦区"},
        {"name": "新天地", "lat": 31.220, "lng": 121.480, "district": "黄浦区"},
        {"name": "静安寺", "lat": 31.230, "lng": 121.455, "district": "静安区"},
        {"name": "徐家汇", "lat": 31.200, "lng": 121.430, "district": "徐汇区"},
        {"name": "五角场", "lat": 31.270, "lng": 121.520, "district": "杨浦区"},
        {"name": "豫园", "lat": 31.225, "lng": 121.490, "district": "黄浦区"},
        {"name": "武康路", "lat": 31.210, "lng": 121.435, "district": "长宁区"},
        {"name": "前滩太古里", "lat": 31.205, "lng": 121.505, "district": "浦东新区"},
        {"name": "田子坊", "lat": 31.215, "lng": 121.470, "district": "黄浦区"},
    ],
    "西安": [
        {"name": "大唐不夜城", "lat": 34.218, "lng": 108.955, "district": "雁塔区"},
        {"name": "钟楼", "lat": 34.260, "lng": 108.940, "district": "碑林区"},
        {"name": "回民街", "lat": 34.265, "lng": 108.945, "district": "莲湖区"},
        {"name": "大雁塔", "lat": 34.218, "lng": 108.960, "district": "雁塔区"},
        {"name": "永宁门", "lat": 34.235, "lng": 108.945, "district": "新城区"},
        {"name": "小寨赛格", "lat": 34.225, "lng": 108.945, "district": "雁塔区"},
        {"name": "高新万达", "lat": 34.240, "lng": 108.890, "district": "雁塔区"},
        {"name": "SKP", "lat": 34.248, "lng": 108.940, "district": "碑林区"},
        {"name": "曲江池", "lat": 34.200, "lng": 108.980, "district": "雁塔区"},
        {"name": "大悦城", "lat": 34.220, "lng": 108.950, "district": "雁塔区"},
    ],
}

# 商圈关键词（用于判断是否是商场）
MALL_KEYWORDS = ["广场", "中心", "天地", "万象", "大悦城", "万达", "SKP", "太古里", "来福士", "IFC", "环贸"]

# 连锁品牌（多分店时 name 一致，branch_name 不同）
CHAIN_BRANDS = [
    ("海底捞", "火锅", 150),
    ("星巴克", "咖啡", 40),
    ("太二酸菜鱼", "美食", 80),
    ("西贝莜面村", "美食", 90),
    ("喜茶", "茶饮", 50),
    ("奈雪的茶", "茶饮", 50),
    ("麦当劳", "快餐", 35),
    ("肯德基", "快餐", 35),
    ("绿茶餐厅", "美食", 60),
    ("外婆家", "美食", 55),
    ("绿茶", "美食", 60),
    ("鼎泰丰", "美食", 120),
    ("点都德", "粤菜", 80),
    ("广州酒家", "粤菜", 85),
    ("避风塘", "美食", 70),
    ("大龙燚", "火锅", 100),
    ("小龙坎", "火锅", 95),
    ("贤和庄", "火锅", 85),
    ("瑞幸咖啡", "咖啡", 28),
    ("喜家德", "饺子", 45),
]

# 黑珍珠餐厅名单（每城最多 30 个，人均 >= 500）
BLACK_PEARL_BRANDS = [
    "唐阁", "新荣记", "UV", "泰安门", "福和慧", "Jean-Georges",
    "8½ Otto e Mezzo Bombana", "L'Atelier de Joël Robuchon",
    "Haidilao", "海底捞",  # 高端店
]


# ============ LLM 调用 ============

def call_llm(prompt: str, model: str = "deepseek-chat") -> str:
    """
    调用 LLM 生成内容
    优先用 MiniMax-M2.7 跑前 50 条深圳 POI 做质量基准，
    后续批量用 DeepSeek-V4-Flash
    """
    import anthropic

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY", "")
    )

    # 模型映射
    model_map = {
        "minimax": "MiniMax-M2.7",
        "deepseek": "deepseek-chat",
        "kimi": "kimi-k2.6",
    }

    actual_model = model_map.get(model, model)

    try:
        response = client.messages.create(
            model=actual_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        print(f"[LLM 调用失败] {model}: {e}")
        return ""


# ============ 生成器核心 ============

def gen_openshopid() -> str:
    """生成 16 位 base64-like 唯一 ID"""
    return secrets.token_urlsafe(12)[:16]


def assign_district(poi: dict, city: str) -> str:
    """根据坐标分配行政区"""
    lat, lng = poi.get("lat", 0), poi.get("lng", 0)
    if not lat or not lng:
        return poi.get("district", "")

    anchors = CITY_ANCHORS.get(city, [])
    min_dist = float("inf")
    assigned = poi.get("district", "")

    for anchor in anchors:
        d = ((lat - anchor["lat"]) ** 2 + (lng - anchor["lng"]) ** 2) ** 0.5
        if d < min_dist:
            min_dist = d
            assigned = anchor["district"]

    return assigned


def assign_category(poi: dict) -> List[str]:
    """分配类目"""
    parent = poi.get("parent_category", "美食")
    if parent not in CATEGORY_ENUMS:
        parent = "美食"
    return [parent]


def gen_star(review_count: int, base_rating: float = None) -> float:
    """
    根据评论数生成星级
    评论多的店评分更稳定高分，冷门店有低分
    """
    if base_rating and base_rating > 0:
        # 有真实评分参考
        base = float(base_rating)
    elif review_count > 5000:
        base = random.choices(
            [4.0, 4.5, 5.0], weights=[0.2, 0.5, 0.3]
        )[0]
    elif review_count > 1000:
        base = random.choices(
            [3.5, 4.0, 4.5], weights=[0.2, 0.5, 0.3]
        )[0]
    elif review_count > 100:
        base = random.choices(
            [3.0, 3.5, 4.0, 4.5], weights=[0.2, 0.3, 0.35, 0.15]
        )[0]
    else:
        base = random.choices(
            [0.0, 3.0, 3.5, 4.0], weights=[0.1, 0.3, 0.4, 0.2]
        )[0]

    # 半星精度
    return round(base * 2) / 2


def gen_business_hour(category: str) -> str:
    """生成营业时间"""
    if category == "酒店":
        return "00:00-23:59"
    if category == "KTV":
        return "13:00-02:00"
    if category == "酒吧":
        return "18:00-02:00"
    if random.random() < 0.3:
        # 午休型
        return f"{random.choice(['09','10','11'])}:00-{random.choice(['14','15'])}:00, {random.choice(['17','18'])}:00-{random.choice(['21','22'])}:00"
    else:
        open_h = random.choice(["09", "10", "11"])
        close_h = random.choice(["21", "22", "23"])
        return f"{open_h}:00-{close_h}:00"


def gen_avgprice(category: str, star: float, is_black_pearl: bool = False) -> int:
    """生成人均消费"""
    if is_black_pearl:
        return random.randint(500, 2000)

    if category == "美食":
        if star >= 4.5:
            return random.randint(80, 400)
        elif star >= 4.0:
            return random.randint(50, 200)
        else:
            return random.randint(30, 100)
    elif category in ["咖啡", "茶饮"]:
        return random.randint(25, 80)
    elif category in ["KTV", "电影演出赛事", "休闲娱乐"]:
        return random.randint(80, 300)
    elif category == "酒店":
        return random.randint(200, 1500)
    elif category == "购物":
        return random.randint(50, 500)
    else:
        return random.randint(50, 200)


def gen_review_count(star: float, category: str) -> int:
    """生成评论数，和星级正相关"""
    if star >= 4.5:
        return random.randint(500, 30000)
    elif star >= 4.0:
        return random.randint(100, 5000)
    elif star >= 3.5:
        return random.randint(50, 1000)
    else:
        return random.randint(10, 500)


def gen_dishs(category: str, count: int = 3) -> List[Dict]:
    """生成推荐菜列表（餐饮类）"""
    if category != "美食":
        return []

    dish_pool = [
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
    ]

    selected = random.sample(dish_pool, min(count, len(dish_pool)))
    return [
        {
            "dishName": name,
            "picUrl": "",
            "price": price,
            "recommendCount": rc
        }
        for name, price, rc in selected
    ]


def gen_special(category: str) -> List[str]:
    """生成特色服务列表"""
    options = ["免费 WiFi", "可停车", "可包间", "可刷卡", "宠物友好",
               "无障碍", "提供婴儿椅", "可外带"]
    if category == "美食":
        return random.sample(options, random.randint(1, 3))
    elif category == "酒店":
        return ["可停车", "可刷卡", "免费 WiFi"]
    else:
        return random.sample(options, random.randint(0, 2))


def gen_telephone(city: str) -> str:
    """生成带区号的电话"""
    area_codes = {"深圳": "0755", "上海": "021", "西安": "029"}
    code = area_codes.get(city, "010")
    return f"{code}-{random.randint(2000, 9999):04d}-{random.randint(1000, 9999):04d}"


# ============ UGC 生成 ============

def load_style_reference(city: str, category: str) -> str:
    """加载真实小红书评论风格参考"""
    corpus = load_xhs_corpus(city)
    if not corpus:
        corpus = load_xhs_corpus("深圳")  # fallback

    # 按类目过滤
    cat_corpus = [n for n in corpus if category in n.get("title", "") or
                  category in n.get("body", "")]
    if len(cat_corpus) < 3:
        cat_corpus = corpus[:5]

    samples = []
    for note in cat_corpus[:3]:
        body = note.get("body", "")
        if len(body) > 100:
            samples.append(body[:500])

    return "\n\n".join(samples) if samples else "参考真实小红书口语化风格，用emoji和断句，像真人在说话。"


def gen_ugcs_for_poi(poi: dict, style_ref: str) -> List[Dict]:
    """为一个 POI 生成 UGC 评论列表"""
    star = poi.get("star", 4.0)
    category = poi.get("parent_category", "美食")
    name = poi.get("name", "")
    city = poi.get("city", "深圳")

    # 决定评分分布
    num_ugc = random.randint(5, 10)
    has_negative = random.random() < 0.3  # 30% 有负面

    # 评分分布
    if star >= 4.5:
        score_pool = [4.0, 4.5, 5.0, 5.0, 5.0, 4.5, 4.0, 3.5, 4.5, 5.0]
    elif star >= 4.0:
        score_pool = [3.5, 4.0, 4.0, 4.5, 4.0, 3.5, 4.5, 4.0, 4.0, 5.0]
    else:
        score_pool = [3.0, 3.5, 3.0, 4.0, 3.5, 3.0, 4.0, 3.0, 3.5, 4.0]

    ugcs = []
    negative_written = False

    for i in range(num_ugc):
        score = random.choice(score_pool)
        star_val = int(score)

        # 负面评论控制
        is_negative = (has_negative and not negative_written and random.random() < 0.4)
        if is_negative:
            score = random.choice([3.0, 3.5, 2.5])
            star_val = int(score)
            negative_written = True

        # 时间戳：过去 6 个月内
        days_ago = random.randint(1, 180)
        ts = int((time.time() - days_ago * 86400) * 1000)

        # 昵称
        nick = gen_nick(score, category, city)

        content = gen_ugc_content(score, category, name, city, is_negative)

        ugc = {
            "nick": nick,
            "userface": "",
            "ispithy": random.random() < 0.15,  # 15% 优质评论
            "score": score,
            "star": star_val,
            "content": content,
            "photos": [],
            "addtime": ts
        }
        ugcs.append(ugc)

    return ugcs


def gen_nick(score: float, category: str, city: str) -> str:
    """生成仿真用户昵称"""
    prefixes = [
        "深圳吃货", "周末探店", "本地土著", "南山小资", "福田上班族",
        "罗湖老街", "宝安居民", "龙华上班族", "罗湖街坊", "蛇口渔港",
        "上海小资", "魔都美食", "静安白领", "陆家嘴金融", "徐汇吃货",
        "广州土著", "天河上班族", "深圳老饕", "美食探险", "探店达人",
    ]
    suffixes = [
        "小分队", "日常", "日记", "打卡", "觅食", "寻味", "食记",
        "探店", "美食记", "真实测评", "踩雷日记", "种草机", "拔草了",
        "推荐", "不推荐", "回头客", "新客", "常驻", "游客",
    ]
    return random.choice(prefixes) + random.choice(suffixes)


UGC_TEMPLATES_NEGATIVE = [
    "等位等了{time}分钟，{complaint}，{other}，不会再来了。",
    "周末去人超多，{complaint}，{other}，性价比一般。",
    "说实话有点失望，{complaint}，{other}，{neutral}。",
    "排队排到崩溃，{time}分钟起步，{complaint}，{other}。",
    "风很大但真的一般，{complaint}，{other}，{neutral}。",
]

NEGATIVE_COMPLAINTS = [
    "上菜速度太慢", "分量有点小", "价格偏贵", "服务一般",
    "环境有点吵", "位置难找", "停车不方便", "菜量虚标",
    "油烟味大", "厕所老旧", "等位太久", "座位挤",
]

NEUTRAL_OBS = [
    "不会特别推荐", "可以试试但别抱太高期望", "中规中矩",
    "胜在位置方便", "适合路过顺便吃一下", "还行吧",
]


def gen_ugc_content(score: float, category: str, name: str, city: str, is_negative: bool) -> str:
    """生成 UGC 评论内容"""
    wait_times = ["30", "45", "1小时", "1.5小时", "20", "40"]
    time_used = random.choice(wait_times)

    if is_negative:
        template = random.choice(UGC_TEMPLATES_NEGATIVE)
        comp = random.choice(NEGATIVE_COMPLAINTS)
        other = random.choice(NEGATIVE_COMPLAINTS)
        neu = random.choice(NEUTRAL_OBS)
        content = template.format(time=time_used, complaint=comp, other=other, neutral=neu)

        # 负面评论用口语化断句
        parts = content.split("，")
        result = "".join([f"{p}\n" for p in parts if p])
        return f"周末去了{name}，\n{result}\n整体感觉{comp}，{other}。"

    else:
        # 正面评论
        if score >= 4.5:
            templates_pos = [
                f"{name}真的绝了！\n{gen_food_desc(category)}\n服务也超 nice，{gen_location_desc(city)}\n已经推荐给朋友了，下次还来！",
                f"救命🆘 {name}怎么这么好吃！\n{gen_food_desc(category)}\n{gen_environment_desc()}\n{city}难得的好店，强烈推荐！",
                f"不允许还有人不知道{name}！\n{gen_food_desc(category)}\n性价比绝了，{gen_service_desc()}\n周末人也不多，超级满意！",
            ]
        elif score >= 4.0:
            templates_pos = [
                f"{name}还不错～\n{gen_food_desc(category)}\n{gen_environment_desc()}\n{gen_service_desc()}，值得再来！",
                f"和朋友约在{name}，\n{gen_food_desc(category)}\n位置{city}中心城区，交通方便，\n{gen_service_desc()}，推荐！",
            ]
        else:
            templates_pos = [
                f"{name}中规中矩，\n{gen_food_desc(category)}\n{city}同类店很多，这家胜在{gen_location_desc(city)}。",
                f"路过{name}顺便试试，\n{gen_food_desc(category)}\n{gen_environment_desc()}，\n{gen_service_desc()}。",
            ]

        return random.choice(templates_pos)


def gen_food_desc(category: str) -> str:
    """生成食物描述"""
    descs = [
        "菜品很新鲜，{dish}绝了",
        "{dish}必点，味道超棒",
        "招牌{dish}名不虚传",
        "{dish}做得很有特色",
        "点的菜都没有踩雷",
        "食材能吃出很新鲜",
        "{dish}口感绝了",
    ]
    dishes = ["烧鹅", "乳鸽", "牛肉", "酸菜鱼", "火锅", "寿司", "刺身",
              "烤鱼", "烧烤", "小龙虾", "炸鸡", "意面", "披萨", "甜品"]
    d = random.choice(dishes)
    return random.choice(descs).format(dish=d)


def gen_environment_desc() -> str:
    """生成环境描述"""
    descs = [
        "装修很有氛围感，拍照超出片",
        "环境干净卫生，座位也舒服",
        "店内氛围不错，适合聊天",
        "装修风格独特，很安静",
        "空间宽敞，不拥挤",
        "灯光很柔和，拍照好看",
    ]
    return random.choice(descs)


def gen_service_desc() -> str:
    """生成服务描述"""
    descs = [
        "服务员态度很好",
        "上菜速度也挺快",
        "服务周到细心",
        "主动加水很勤快",
        "服务热情但不打扰",
    ]
    return random.choice(descs)


def gen_location_desc(city: str) -> str:
    """生成位置描述"""
    descs = [
        f"地铁直达超方便",
        f"停车方便有地下车库",
        f"位置很好找",
        f"周边商圈中心位置",
        f"离地铁口步行5分钟",
    ]
    return random.choice(descs)


# ============ reviewTags 生成 ============

def gen_review_tags(poi: dict) -> List[Dict]:
    """生成 reviewTags"""
    category = poi.get("parent_category", "美食")
    review_count = max(10, poi.get("reviewCount", 100))  # 至少 10 条
    star = poi.get("star", 4.0)

    # 选正面 tags
    num_positive = random.randint(8, 12)
    pos_tags = random.sample(POSITIVE_TAGS, min(num_positive, len(POSITIVE_TAGS)))

    # 选负面 tags（1-3 个）
    num_negative = random.randint(1, 3)
    neg_tags = random.sample(NEGATIVE_TAGS, min(num_negative, len(NEGATIVE_TAGS)))

    all_tags = pos_tags + neg_tags

    tags = []
    max_hit = max(5, int(review_count * random.uniform(0.25, 0.35)))

    for i, tag in enumerate(all_tags):
        if i == 0:
            hit = max_hit
        elif i < len(all_tags) - len(neg_tags):
            # 正面中等
            low = max(5, int(review_count * 0.05))
            high = max(low + 1, int(review_count * 0.15))
            hit = random.randint(low, high)
        else:
            # 负面
            hit = random.randint(5, max(5, min(50, int(review_count * 0.05))))

        tags.append({"tag": tag, "hit": hit})

    # 按 hit 降序排列
    tags.sort(key=lambda x: x["hit"], reverse=True)
    return tags


# ============ 主生成流程 ============

def generate_poi(poi: dict, city: str, idx: int) -> dict:
    """为一个骨架 POI 生成完整字段"""
    category = poi.get("parent_category", "美食")

    # star 和 reviewCount
    base_rating = poi.get("rating")
    review_count = gen_review_count(0, category) if not base_rating else gen_review_count(float(base_rating), category)
    if base_rating:
        review_count = max(review_count, int(base_rating * random.randint(50, 200)))

    star = gen_star(review_count, base_rating)

    # openstatus: 95% 为 1
    openstatus = random.choices([1, 0], weights=[0.95, 0.05])[0]

    # 高质量标志：15%
    highquality = 1 if random.random() < 0.15 else 0

    # avgprice 先随机生成
    avgprice = gen_avgprice(category, star)

    # isBlackPearl：只对高端餐饮（人均 >= 500 且 star >= 4.5），每城不超过 30 个
    # 这个逻辑在实际生成时通过 city_black_pearl_count 追踪
    # 生成时直接判断：随机 1% 的高星级美食 且 人均 >= 500
    is_black_pearl = 0
    if category == "美食" and star >= 4.5 and avgprice >= 500:
        if random.random() < 0.3:  # 控制总量
            is_black_pearl = 1
            # 黑珍珠餐厅价格上调
            avgprice = random.randint(500, 2000)

    # 生成 POI
    result = {
        "openshopid": gen_openshopid(),
        "openstatus": openstatus,
        "name": poi.get("name", ""),
        "branch_name": poi.get("branch_name", ""),
        "address": poi.get("address", ""),
        "city": city,
        "district": poi.get("district", ""),
        "latitude": poi.get("lat", 0),
        "longitude": poi.get("lng", 0),
        "categories": assign_category(poi),
        "star": star,
        "reviewCount": review_count,
        "avgprice": avgprice,
        "business_hour": gen_business_hour(category),
        "highquality": highquality,
        "isBlackPearl": is_black_pearl,
        "dishs": gen_dishs(category) if category == "美食" else [],
        "special": gen_special(category),
        "takeawayable": category == "美食" and random.random() < 0.7,
        "queueable": star >= 4.0 and random.random() < 0.4,
        "bookable": category in ["美食", "酒店", "宴会"] and random.random() < 0.3,
        "telephone": poi.get("telephone") or gen_telephone(city),
        "ugcs": [],
        "reviewTags": [],
        "headPic": "",
        "shopPics": [],
        "mShopInfoUrl": "",
        "appShopInfoUrl": "",
        "shopI18ns": [],
        "shopDesc": "",
    }

    return result


def enrich_poi_with_llm(poi: dict, style_ref: str, city: str) -> dict:
    """
    用 LLM 补充 ugcs 和 reviewTags
    （这里是简化版，真实场景需要批量调用 LLM）
    """
    # 用规则生成而非 LLM 调用（演示用）
    poi["ugcs"] = gen_ugcs_for_poi(poi, style_ref)
    poi["reviewTags"] = gen_review_tags(poi)

    # 差评要有具体细节
    for ugc in poi["ugcs"]:
        if ugc["score"] < 4.0:
            # 确保负面评论有具体细节
            content = ugc["content"]
            if "分钟" not in content and "等" not in content and "慢" not in content:
                # 加点具体细节
                ugc["content"] = content + "\n（等了大概40分钟才上菜）"

    return poi


def fill_to_800(skeleton: list, city: str, target: int = 800) -> list:
    """
    骨架不够 800 条时，用规则生成补充
    """
    existing = len(skeleton)
    if existing >= target:
        return skeleton[:target]

    # 从 amap 或规则生成补充
    while len(skeleton) < target:
        # 随机选一个商圈 anchor
        anchor = random.choice(CITY_ANCHORS.get(city, CITY_ANCHORS["深圳"]))

        # 生成一个虚拟 POI
        lat = anchor["lat"] + random.uniform(-0.01, 0.01)
        lng = anchor["lng"] + random.uniform(-0.01, 0.01)

        # 随机类目
        cat = random.choice(["美食", "美食", "美食", "休闲娱乐", "购物", "酒店", "丽人", "亲子"])
        district = anchor["district"]

        # 虚拟 POI 名字池（按类目）
        names_by_cat = {
            "美食": ["粤菜馆", "川菜馆", "湘菜馆", "火锅店", "烧烤摊", "日料店", "茶餐厅", "小吃店"],
            "休闲娱乐": ["棋牌室", "网吧", "健身房", "游泳池", "电影院", "KTV"],
            "购物": ["便利店", "超市", "服装店", "书店", "水果店"],
            "酒店": ["商务酒店", "快捷酒店", "民宿"],
            "丽人": ["美发店", "美容院", "美甲店"],
            "亲子": ["儿童乐园", "母婴店", "早教中心"],
        }
        name = random.choice(names_by_cat.get(cat, ["店铺"]))

        fake_poi = {
            "name": f"{anchor['name']}{name}",
            "branch_name": "",
            "lat": lat,
            "lng": lng,
            "district": district,
            "address": f"{district}{anchor['name']}附近",
            "city": city,
            "parent_category": cat,
            "type": cat,
            "telephone": "",
            "source": "generated",
        }
        skeleton.append(fake_poi)

    return skeleton


def generate_city(city: str, limit: int = 800, use_llm: bool = False) -> List[dict]:
    """
    生成一个城市的 POI 数据
    """
    print(f"\n{'='*60}")
    print(f"开始生成 {city} 数据（目标 {limit} 条）")
    print(f"{'='*60}")

    # 1. 构建骨架
    skeleton = build_skeleton(city)
    print(f"[{city}] 骨架 POI: {len(skeleton)} 条")

    # 2. 补充到 800 条
    skeleton = fill_to_800(skeleton, city, limit)
    print(f"[{city}] 填充后: {len(skeleton)} 条")

    # 3. 加载风格参考
    style_ref = load_style_reference(city, "美食")
    print(f"[{city}] 风格参考已加载")

    # 4. 逐条生成
    pois = []
    for i, poi in enumerate(skeleton):
        if i % 100 == 0:
            print(f"[{city}] 生成进度: {i}/{len(skeleton)}")

        # 生成基础字段
        p = generate_poi(poi, city, i)

        # 补充 UGC 和 reviewTags（规则版，不用 LLM 调用）
        p = enrich_poi_with_llm(p, style_ref, city)

        pois.append(p)

    print(f"[{city}] 生成完成: {len(pois)} 条")
    return pois


def save_output(pois: List[dict], city: str):
    """保存输出文件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    city_file = OUTPUT_DIR / f"{city}.json"
    with open(city_file, "w", encoding="utf-8") as f:
        json.dump(pois, f, ensure_ascii=False, indent=2)
    print(f"已保存: {city_file}")

    return city_file


def build_index(pois: List[dict], city: str) -> dict:
    """构建索引文件"""
    index = {
        "by_category": {},
        "by_district": {},
        "by_mall": {},
        "by_keyword": {},
    }

    for poi in pois:
        # by_category
        for cat in poi.get("categories", []):
            if cat not in index["by_category"]:
                index["by_category"][cat] = []
            index["by_category"][cat].append(poi["openshopid"])

        # by_district
        district = poi.get("district", "")
        if district:
            if district not in index["by_district"]:
                index["by_district"][district] = []
            index["by_district"][district].append(poi["openshopid"])

        # by_mall
        name = poi.get("name", "")
        if any(kw in name for kw in MALL_KEYWORDS):
            if "by_mall" not in index:
                index["by_mall"] = {}
            if name not in index["by_mall"]:
                index["by_mall"][name] = []
            index["by_mall"][name].append(poi["openshopid"])

        # by_keyword（简单按类目关键词分）
        keywords = ["火锅", "粤菜", "川菜", "湘菜", "日料", "西餐", "咖啡", "茶"]
        for kw in keywords:
            if kw in name:
                if kw not in index["by_keyword"]:
                    index["by_keyword"][kw] = []
                index["by_keyword"][kw].append(poi["openshopid"])

    return index


def run_validate(pois: List[dict], city: str):
    """运行 schema 校验"""
    from schemas import validate_poi

    errors = []
    for i, poi in enumerate(pois):
        valid, msg = validate_poi(poi)
        if not valid:
            errors.append(f"POI {i} ({poi.get('name', '')}): {msg}")

    if errors:
        print(f"\n[{city}] 校验发现 {len(errors)} 个问题:")
        for e in errors[:10]:
            print(f"  - {e}")
    else:
        print(f"\n[{city}] 校验通过 ✓")


# ============ 主入口 ============

def main():
    parser = argparse.ArgumentParser(description="美团 Hackathon 模拟数据生成器")
    parser.add_argument("--city", choices=["深圳", "上海", "西安"], default="深圳",
                        help="城市")
    parser.add_argument("--limit", type=int, default=50, help="生成数量（默认50条测试）")
    parser.add_argument("--llm", action="store_true", help="使用 LLM 生成 UGC（慢但质量高）")
    parser.add_argument("--model", default="deepseek", choices=["minimax", "deepseek", "kimi"],
                        help="LLM 模型")
    args = parser.parse_args()

    print(f"配置: city={args.city}, limit={args.limit}, use_llm={args.llm}, model={args.model}")

    # 生成
    pois = generate_city(args.city, args.limit, use_llm=args.llm)

    # 保存
    city_file = save_output(pois, args.city)

    # 校验
    run_validate(pois, args.city)

    print(f"\n✓ {args.city} 生成完成: {city_file}")
    print(f"  共 {len(pois)} 条 POI")

    return pois


if __name__ == "__main__":
    pois = main()
