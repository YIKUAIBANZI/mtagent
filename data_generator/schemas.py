#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
schemas.py - POI 输出 schema 校验
参考大众点评开放平台字段契约
"""

from typing import List, Optional
from pydantic import BaseModel, Field

# 20 个一级类目枚举
CATEGORY_ENUMS = [
    "美食", "K歌", "购物", "电影演出赛事", "休闲娱乐",
    "周边游", "宴会", "运动健身", "丽人", "结婚",
    "酒店", "爱车", "亲子", "学习培训", "生活服务",
    "医疗健康", "家居", "宠物", "榛果民宿", "交通枢纽"
]

# 特色服务枚举
SPECIAL_ENUMS = [
    "免费 WiFi", "可停车", "可包间", "可刷卡", "宠物友好",
    "无障碍", "提供婴儿椅", "可外带"
]

# 正面 reviewTags 池
POSITIVE_TAGS = [
    "环境优雅", "服务好", "菜品精致", "性价比高", "氛围佳",
    "干净卫生", "食材新鲜", "出片漂亮", "适合约会", "适合聚会",
    "亲子友好", "老字号", "本地特色", "上菜快", "包厢私密", "交通方便"
]

# 负面 reviewTags 池
NEGATIVE_TAGS = [
    "上菜慢", "等位久", "价格偏贵", "分量小", "服务一般",
    "油烟大", "厕所老旧", "停车难", "位置难找", "菜量虚标"
]


class UGCItem(BaseModel):
    """单条 UGC 评论"""
    nick: str
    userface: str = ""
    ispithy: bool = False
    score: float = Field(ge=0.0, le=5.0)
    star: int = Field(ge=0, le=5)
    content: str
    photos: List[str] = []
    addtime: int  # 毫秒时间戳


class Dish(BaseModel):
    """推荐菜"""
    dishName: str
    picUrl: str = ""
    price: float = Field(ge=0)
    recommendCount: int = 0


class MallInfo(BaseModel):
    """商场扩展信息"""
    popularShops: List[str]  # 美食 POI openshopid 列表
    dzPopularShops: List[str]  # 到综 POI openshopid 列表
    discount: bool = True


class DealInfo(BaseModel):
    """团单优惠"""
    dealName: str
    originPrice: float
    discountPrice: float
    dealPicUrl: str = ""
    shopName: str
    type: int = 1  # 1=美食, 2=到综


class TakeawayInfo(BaseModel):
    """外卖信息"""
    tag: str
    longTag: str = ""
    url: str = ""
    mUrl: str = ""


class POISchema(BaseModel):
    """POI 完整 schema"""
    openshopid: str
    openstatus: int = Field(ge=0, le=1)
    name: str
    branch_name: str = ""
    address: str
    city: str
    latitude: float
    longitude: float
    categories: List[str]
    star: float = Field(ge=0.0, le=5.0)
    reviewCount: int = Field(ge=0)

    # 关键富字段
    avgprice: int = Field(ge=0)
    business_hour: str = ""
    highquality: int = Field(ge=0, le=1)
    isBlackPearl: int = Field(ge=0, le=1)
    dishs: List[Dish] = []
    special: List[str] = []
    takeawayable: bool = False
    queueable: bool = False
    bookable: bool = False
    telephone: str = ""

    # UGC
    ugcs: List[UGCItem] = []
    reviewTags: List[dict] = []

    # 商场扩展
    mallInfo: Optional[MallInfo] = None

    # 团单/外卖
    dealInfo: List[DealInfo] = []
    takeawayinfo: Optional[TakeawayInfo] = None

    # 不生成的字段（留空）
    headPic: str = ""
    shopPics: List[str] = []
    mShopInfoUrl: str = ""
    appShopInfoUrl: str = ""
    shopI18ns: List[str] = []
    shopDesc: str = ""

    class Config:
        extra = "allow"


def validate_category(categories: List[str]) -> bool:
    """验证一级类目在枚举内"""
    for cat in categories:
        if cat not in CATEGORY_ENUMS:
            return False
    return True


def validate_poi(poi: dict) -> tuple:
    """
    校验单个 POI，返回 (is_valid, error_msg)
    """
    required_fields = [
        "openshopid", "openstatus", "name", "address", "city",
        "latitude", "longitude", "categories", "star", "reviewCount"
    ]
    for field in required_fields:
        if field not in poi:
            return False, f"缺少必填字段: {field}"

    # 类型检查
    if not isinstance(poi.get("openshopid"), str):
        return False, "openshopid 必须是字符串"
    if poi.get("openstatus") not in [0, 1]:
        return False, "openstatus 必须是 0 或 1"
    if not isinstance(poi.get("categories"), list):
        return False, "categories 必须是 list"
    if not validate_category(poi.get("categories", [])):
        return False, f"categories 包含非法类目: {poi.get('categories')}"

    # business_hour 格式
    import re
    bh = poi.get("business_hour", "")
    if bh and not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}(, \d{2}:\d{2}-\d{2}:\d{2})?$", bh):
        return False, f"business_hour 格式错误: {bh}"

    # star 范围
    star = poi.get("star", 0)
    if not (0 <= star <= 5):
        return False, f"star 超出范围: {star}"

    return True, ""


if __name__ == "__main__":
    # 简单测试
    print("schemas.py 校验工具就绪")
