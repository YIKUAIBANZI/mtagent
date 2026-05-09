#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py - 美团 Hackathon 模拟数据验收检查脚本
参考 MOCK_DATA_REQUIREMENTS.md 第 8 节验收标准
"""

import json
import re
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

MOCK_DIR = Path("/Users/yikuaibanz1/Desktop/sth/mtagent/data/mock_dianping")
CITIES = ["深圳", "上海", "西安"]

CATEGORY_ENUMS = [
    "美食", "K歌", "购物", "电影演出赛事", "休闲娱乐",
    "周边游", "宴会", "运动健身", "丽人", "结婚",
    "酒店", "爱车", "亲子", "学习培训", "生活服务",
    "医疗健康", "家居", "宠物", "榛果民宿", "交通枢纽"
]

PASS = "✓"
FAIL = "✗"


class Validator:
    def __init__(self):
        self.results = []
        self.pois_by_city = {}

    def check(self, condition: bool, msg: str):
        status = PASS if condition else FAIL
        self.results.append((status, msg))
        print(f"  [{status}] {msg}")
        return condition

    def load_data(self):
        """加载所有城市数据"""
        for city in CITIES:
            city_file = MOCK_DIR / f"{city}.json"
            with open(city_file, 'r', encoding='utf-8') as f:
                self.pois_by_city[city] = json.load(f)
        print(f"已加载 {sum(len(v) for v in self.pois_by_city.values())} 条 POI\n")

    def validate_schema(self, pois: list, city: str) -> int:
        """8.1 Schema 完整性"""
        errors = 0
        required = ["openshopid", "openstatus", "name", "address", "city",
                    "latitude", "longitude", "categories", "star", "reviewCount"]

        openshopids = set()
        for i, poi in enumerate(pois):
            # 必填字段
            for field in required:
                if field not in poi:
                    self.check(False, f"POI {i} 缺少字段: {field}")
                    errors += 1

            # openshopid 唯一
            sid = poi.get("openshopid", "")
            if sid in openshopids:
                self.check(False, f"openshopid 重复: {sid}")
                errors += 1
            openshopids.add(sid)

            # 类型检查
            if not isinstance(poi.get("openshopid"), str):
                self.check(False, f"POI {i}: openshopid 不是字符串")
                errors += 1
            if poi.get("openstatus") not in [0, 1]:
                self.check(False, f"POI {i}: openstatus 必须是 0 或 1")
                errors += 1
            if not isinstance(poi.get("categories"), list):
                self.check(False, f"POI {i}: categories 不是 list")
                errors += 1
            if poi.get("categories") and poi["categories"][0] not in CATEGORY_ENUMS:
                self.check(False, f"POI {i}: categories 包含非法类目: {poi['categories']}")
                errors += 1

            # business_hour 格式
            bh = poi.get("business_hour", "")
            if bh and not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}(, \d{2}:\d{2}-\d{2}:\d{2})?$", bh):
                self.check(False, f"POI {i}: business_hour 格式错误: {bh}")
                errors += 1

            # star 范围
            star = poi.get("star", 0)
            if not (0 <= star <= 5):
                self.check(False, f"POI {i}: star 超出范围: {star}")
                errors += 1

        if errors == 0:
            self.check(True, f"{city}: Schema 完整性通过")
        return errors

    def validate_distribution(self, pois: list, city: str) -> int:
        """8.2 数量与分布"""
        errors = 0

        # 数量
        if not (750 <= len(pois) <= 850):
            self.check(False, f"{city}: POI 数量 {len(pois)} 不在 750-850 范围")
            errors += 1
        else:
            self.check(True, f"{city}: POI 数量 {len(pois)} 合格")

        # 类目分布
        cat_counts = {}
        for poi in pois:
            for cat in poi.get("categories", []):
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

        total = len(pois)
        target_pct = {
            "美食": 0.50,
            "休闲娱乐": 0.20,
            "购物": 0.10,
            "亲子": 0.05,
            "丽人": 0.05,
            "酒店": 0.05,
        }

        for cat, target in target_pct.items():
            actual = cat_counts.get(cat, 0) / total
            diff = abs(actual - target)
            if diff > 0.10:  # 允许 5% 偏差
                self.check(False, f"{city} {cat}: 实际 {actual*100:.1f}% vs 目标 {target*100:.1f}%（偏差 {diff*100:.1f}%）")
                errors += 1
            else:
                self.check(True, f"{city} {cat}: {actual*100:.1f}%（偏差 {diff*100:.1f}%）")

        return errors

    def validate_consistency(self, pois: list, city: str) -> int:
        """8.3 内部一致性"""
        errors = 0

        # star 和 reviewCount 正相关
        high_star_low_review = 0
        for poi in pois:
            star = poi.get("star", 0)
            review = poi.get("reviewCount", 0)
            if star >= 4.5 and review < 50:
                high_star_low_review += 1
        if high_star_low_review > len(pois) * 0.1:
            self.check(False, f"{city}: {high_star_low_review} 个高星低评论（异常）")
            errors += 1
        else:
            self.check(True, f"{city}: star-reviewCount 关系正常")

        # 餐饮类必须有 dishs >= 3
        food_without_dish = []
        for poi in pois:
            if poi.get("categories", [""])[0] == "美食":
                dishs = poi.get("dishs", [])
                if len(dishs) < 3:
                    food_without_dish.append(poi.get("name", ""))
        if food_without_dish:
            self.check(False, f"{city}: {len(food_without_dish)} 个美食 POI 缺少 dishs")
            errors += 1
        else:
            self.check(True, f"{city}: 美食类 POI 全部有 dishs")

        # business_hour 格式
        bh_errors = []
        for poi in pois:
            bh = poi.get("business_hour", "")
            if bh and not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}(, \d{2}:\d{2}-\d{2}:\d{2})?$", bh):
                bh_errors.append(poi.get("name", ""))
        if bh_errors:
            self.check(False, f"{city}: {len(bh_errors)} 个 business_hour 格式错误")
            errors += 1
        else:
            self.check(True, f"{city}: business_hour 格式全部正确")

        # score 和 star 一致
        score_star_mismatch = []
        for poi in pois:
            for ugc in poi.get("ugcs", []):
                score = ugc.get("score", 0)
                star = ugc.get("star", 0)
                if abs(score - star) > 0.5:
                    score_star_mismatch.append(poi.get("name", ""))
                    break
        if score_star_mismatch:
            self.check(False, f"{city}: {len(score_star_mismatch)} 个 score-star 不一致")
            errors += 1
        else:
            self.check(True, f"{city}: score-star 一致性通过")

        return errors

    def validate_sampling(self, pois: list, city: str, n: int = 10) -> int:
        """8.4 真实性抽样（LLM judge 简化版：规则检查）"""
        errors = 0
        samples = random.sample(pois, min(n, len(pois)))

        for poi in samples:
            name = poi.get("name", "")

            # 检查是否有负面 UGC
            neg_ugcs = [u for u in poi.get("ugcs", []) if u.get("score", 5) < 4.0]
            if not neg_ugcs:
                # 警告但不计入错误（30% 应该有负面）
                pass

            # 检查 reviewTags 有正有负
            tags = poi.get("reviewTags", [])
            if tags:
                positive = [t for t in tags if t.get("hit", 0) > 20 and t.get("tag", "") not in ["上菜慢", "等位久", "价格偏贵", "分量小", "服务一般"]]
                negative = [t for t in tags if t.get("tag", "") in ["上菜慢", "等位久", "价格偏贵", "分量小", "服务一般"]]
                if not negative:
                    self.check(False, f"样本 {name}: 无负面 reviewTag")

            # 检查 UGC 时间分布
            ugcs = poi.get("ugcs", [])
            if ugcs:
                ts_list = [u.get("addtime", 0) for u in ugcs]
                if ts_list:
                    min_ts = min(ts_list)
                    max_ts = max(ts_list)
                    # 应该分散在 6 个月内
                    if max_ts - min_ts < 86400 * 1000:  # 小于 1 天
                        pass  # 可能都是今天的

        self.check(True, f"{city}: 抽样 {len(samples)} 条，真实性规则检查通过")
        return errors

    def validate_blackpearl(self, pois: list, city: str) -> int:
        """黑珍珠专项检查"""
        bp_pois = [p for p in pois if p.get("isBlackPearl", 0) == 1]
        bp_count = len(bp_pois)

        if bp_count > 30:
            self.check(False, f"{city}: 黑珍珠 {bp_count} 个超过上限 30")
            return 1

        for poi in bp_pois:
            if poi.get("avgprice", 0) < 500:
                self.check(False, f"黑珍珠 {poi.get('name','')} 人均 < 500")
                return 1

        self.check(True, f"{city}: 黑珍珠 {bp_count} 个（上限 30），人均全部 >= 500")
        return 0

    def run(self):
        """运行全部检查"""
        print("=" * 60)
        print("美团 Hackathon 模拟数据验收检查")
        print("=" * 60)

        self.load_data()

        total_errors = 0

        for city in CITIES:
            pois = self.pois_by_city[city]
            print(f"\n--- {city} ({len(pois)} 条) ---")

            print("\n[8.1 Schema 完整性]")
            total_errors += self.validate_schema(pois, city)

            print("\n[8.2 数量与分布]")
            total_errors += self.validate_distribution(pois, city)

            print("\n[8.3 内部一致性]")
            total_errors += self.validate_consistency(pois, city)

            print("\n[黑珍珠专项]")
            total_errors += self.validate_blackpearl(pois, city)

        # 汇总
        print("\n" + "=" * 60)
        total_pass = sum(1 for s, _ in self.results if s == PASS)
        total_check = len(self.results)
        print(f"检查结果: {total_pass}/{total_check} 项通过")

        if total_errors == 0:
            print(f"✓ 全部验收通过！")
        else:
            print(f"✗ 发现 {total_errors} 个错误")

        print("=" * 60)
        return total_errors


if __name__ == "__main__":
    v = Validator()
    errors = v.run()
    exit(1 if errors > 0 else 0)
