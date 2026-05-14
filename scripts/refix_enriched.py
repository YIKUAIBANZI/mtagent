"""v1.9 LLM 重打脏点 POI 的 EnrichedLabel.

读 data/generated/enriched_audit_report.json, 对每个标红 POI 调 qwen-plus,
patch 到 data/poi_enriched_labels.json.

支持:
- --dry-run    只打印不写文件
- --limit N    只处理前 N 个 (调试)
- --only-flag F 只处理含特定 flag 的脏点
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

PLANNING_TAGS_VOCAB = [
    "food_quality",
    "local_food",
    "snack_friendly",
    "coffee_friendly",
    "photo_friendly",
    "culture_friendly",
    "museum_friendly",
    "history_friendly",
    "shopping_friendly",
    "night_friendly",
    "family_friendly",
    "couple_friendly",
    "elderly_friendly",
    "solo_friendly",
    "business_friendly",
    "rest_friendly",
    "citywalk_friendly",
    "rainy_day_friendly",
    "transit_friendly",
    "low_budget_friendly",
    "premium_friendly",
    "landmark",
    "first_visit_friendly",
    "atmosphere",
    "lunch_friendly",
    "dinner_friendly",
    "rain_friendly",
]
RISK_TAGS_VOCAB = [
    "queue_heavy",
    "crowded_weekend",
    "walk_heavy",
    "far_from_anchor",
    "hard_to_find",
    "pricey",
    "reservation_needed",
    "unstable_opening",
    "weather_sensitive",
    "not_family_friendly",
    "not_elderly_friendly",
]
POI_ROLES = ["city_essential", "persona_preferred", "meal", "connector", "fallback"]


def build_refix_prompt(poi: dict, flags: list[str]) -> str:
    """拼装 LLM 重打 prompt."""
    review_tags_str = "\n".join(
        f"  - {rt['tag']} hit={rt['hit']}" for rt in (poi.get("reviewTags") or [])[:5]
    )
    return f"""你是本地路线规划专家. 给定 POI 信息, 当前 EnrichedLabel 被标红, 请重新生成正确的 label.

## POI 信息
- 名字: {poi.get("name")}
- 城市: {poi.get("city")}
- 当前 categories: {poi.get("categories")}
- star: {poi.get("star")}
- top reviewTags:
{review_tags_str or "  (无)"}

## 标红原因
{", ".join(flags)}

## 任务
1. 根据 name + reviewTags 判断真实的 categories (categories 错时给修正)
2. 选合适的 poi_role: {", ".join(POI_ROLES)}
3. 从词表选 planning_tags (≥ 2 个):
   {", ".join(PLANNING_TAGS_VOCAB)}
4. 从词表选 risk_tags (可空):
   {", ".join(RISK_TAGS_VOCAB)}
5. 推断 city_zone (区域名, 例 "万象天地 / 科技园" / "钟楼-鼓楼-城墙")
6. manual_priority 0-100, city_essential 通常 80+

## 输出严格 JSON
{{
  "fix_categories": ["景点", "历史文化"],
  "poi_role": "city_essential",
  "planning_tags": ["landmark", "culture_friendly", "photo_friendly"],
  "risk_tags": ["crowded_weekend"],
  "city_zone": "钟楼-鼓楼-城墙",
  "manual_priority": 95,
  "min_stay_minutes": 60,
  "max_stay_minutes": 180
}}

要求:
- 标签必须从词表选, 不能自造
- categories/name 矛盾时 (例如城墙=美食), 以 name + reviewTags 为准
"""


async def refix_poi(poi: dict, flags: list[str]) -> dict:
    """调 qwen-plus 重打 enriched label. 返回新 enriched dict."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        base_url=os.environ.get(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    prompt = build_refix_prompt(poi, flags)
    resp = await client.chat.completions.create(
        model=os.environ.get("QWEN_MODEL", "qwen-plus"),
        messages=[
            {
                "role": "system",
                "content": "你是路线规划数据校对专家. 严格按 JSON schema 输出.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )
    return json.loads(resp.choices[0].message.content or "{}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个 (调试)")
    parser.add_argument(
        "--only-flag",
        type=str,
        default="",
        help="只处理含此 flag 的脏点 (例 landmark_with_food)",
    )
    args = parser.parse_args()

    audit_path = Path("data/generated/enriched_audit_report.json")
    if not audit_path.exists():
        print("先跑 scripts/audit_enriched.py")
        return
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    enriched_path = Path("data/poi_enriched_labels.json")
    enriched_all = (
        json.loads(enriched_path.read_text(encoding="utf-8"))
        if enriched_path.exists()
        else {}
    )

    fix_count = 0
    fail_count = 0
    for city, result in audit.items():
        if "error" in result:
            continue
        for entry in result.get("report", []):
            if args.only_flag and args.only_flag not in entry["flags"]:
                continue
            if args.limit and fix_count >= args.limit:
                break
            oid = entry["openshopid"]
            poi_path = Path(f"data/mock_dianping/{city}.json")
            pois = json.loads(poi_path.read_text(encoding="utf-8"))
            poi = next((p for p in pois if p["openshopid"] == oid), None)
            if not poi:
                continue
            poi["city"] = city
            try:
                new_enriched = await refix_poi(poi, entry["flags"])
            except Exception as exc:
                print(f"FAIL {city} {oid}: {exc}")
                fail_count += 1
                continue

            if args.dry_run:
                print(f"DRY {city} {oid} {poi['name']}: {new_enriched}")
                fix_count += 1
                continue

            city_map = enriched_all.setdefault(city, {})
            existing = city_map.get(oid, {})
            existing.update(
                {
                    "poi_role": new_enriched.get(
                        "poi_role", existing.get("poi_role", "fallback")
                    ),
                    "planning_tags": new_enriched.get("planning_tags", []),
                    "risk_tags": new_enriched.get("risk_tags", []),
                    "city_zone": new_enriched.get("city_zone", ""),
                    "manual_priority": new_enriched.get("manual_priority", 0),
                    "min_stay_minutes": new_enriched.get("min_stay_minutes", 60),
                    "max_stay_minutes": new_enriched.get("max_stay_minutes", 120),
                }
            )
            city_map[oid] = existing
            fix_count += 1
            print(f"FIXED {city} {oid} {poi['name']}")

    if not args.dry_run:
        enriched_path.write_text(
            json.dumps(enriched_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nWrote {fix_count} fixes to {enriched_path} (fail={fail_count})")
    else:
        print(f"\nDRY: would write {fix_count} fixes (fail={fail_count})")


if __name__ == "__main__":
    asyncio.run(main())
