"""AI semantic labeling for high-value POIs.

Reads poi_ai_label_tasks.jsonl, analyzes UGC content with rule-based
semantic heuristics, and writes data/poi_ai_labels.json.

This is Stage 2 of the labeling pipeline. It focuses on tags that rules
can't reliably judge from structured fields alone:
  - photo_friendly: verify from UGC mentions of 拍照/出片/景色
  - night_friendly: verify from UGC mentions of 夜景/晚上
  - quiet: re-evaluate (rule version was over-broad)
  - walk_heavy: check from UGC mentions of 走路累/地方大
  - queue_heavy: cross-validate with UGC mentions
  - family_friendly / senior_friendly / solo_friendly: from UGC context
  - poi_role corrections: when UGC clearly contradicts rule label
  - suggested_slots adjustments
  - planning_tags and risk_tags removals when UGC contradicts rule tags
"""

import json
import re
from collections import Counter
from pathlib import Path

TASKS_PATH = Path("data/poi_ai_label_tasks.jsonl")
OUTPUT_PATH = Path("data/poi_ai_labels.json")

# Minimum confidence to emit a label (spec §5: < 0.6 skip)
MIN_CONFIDENCE = 0.6

# Valid planning_tags and risk_tags (from spec §3.2)
VALID_PLANNING_TAGS = {
    "photo_friendly", "food_quality", "culture_friendly", "family_friendly",
    "couple_friendly", "group_friendly", "business_friendly", "quiet",
    "atmosphere", "good_value", "transit_friendly", "rain_friendly",
    "night_friendly", "rest_friendly", "shopping_friendly",
    "first_visit_friendly", "landmark", "food", "private_room",
    "senior_friendly", "pet_friendly", "premium_food", "good_service",
    "fast_service", "solo_friendly",
}

VALID_RISK_TAGS = {
    "queue_heavy", "slow_service", "pricey", "hard_to_find", "parking_hard",
    "facility_old", "smoky", "small_portion", "service_average",
    "portion_mismatch", "reservation_recommended", "walk_heavy",
    "crowded_weekend",
}

VALID_ROLES = {"city_essential", "persona_preferred", "meal", "connector", "fallback"}
SLOT_ORDER = ["morning", "lunch", "afternoon", "afternoon_tea", "dinner", "evening"]


def ordered_slots(slots: list[str]) -> list[str]:
    """Return unique slots in canonical day order for reproducible output."""
    seen = set()
    unique = []
    for slot in slots:
        if slot in seen:
            continue
        seen.add(slot)
        unique.append(slot)
    order = {slot: idx for idx, slot in enumerate(SLOT_ORDER)}
    return sorted(unique, key=lambda slot: (order.get(slot, len(order)), slot))


def analyze_ugc(ugc_texts: list[str], task: dict) -> dict:
    """Analyze UGC excerpts and structured fields to produce AI labels."""
    blob = "\n".join(ugc_texts)
    rule_label = task.get("rule_label", {})
    categories = set(task.get("categories", []))
    tags = {t["tag"] for t in task.get("reviewTags", [])}
    special = set(task.get("special", []))
    name = task.get("name", "")
    address = task.get("address", "")
    review_count = task.get("reviewCount", 0)
    star = task.get("star", 0)

    result = {
        "planning_tags_add": [],
        "planning_tags_remove": [],
        "risk_tags_add": [],
        "risk_tags_remove": [],
        "poi_role": None,
        "suggested_slots": None,
        "min_stay_minutes": None,
        "max_stay_minutes": None,
        "confidence": 0.0,
        "ai_notes": "",
    }

    changes = []
    confidence_sum = 0.0
    confidence_count = 0

    # === 1. photo_friendly: verify or remove ===
    has_photo_rule = "photo_friendly" in rule_label.get("planning_tags", [])
    photo_ugc_hits = re.findall(r"拍照|出片|打卡|随手拍|美照|绝美|壮观|震撼", blob)
    has_photo_tag = "出片漂亮" in tags
    if has_photo_rule and not has_photo_tag and len(photo_ugc_hits) < 2:
        # Rule tagged it (from "好看" in desc or other source) but UGC doesn't support
        result["planning_tags_remove"].append("photo_friendly")
        changes.append("移除photo_friendly:UGC无拍照/出片证据")
        confidence_sum += 0.75
        confidence_count += 1
    elif not has_photo_rule and (has_photo_tag or len(photo_ugc_hits) >= 3):
        result["planning_tags_add"].append("photo_friendly")
        changes.append("新增photo_friendly:UGC多次提到拍照/出片")
        confidence_sum += 0.7
        confidence_count += 1

    # === 2. quiet: re-evaluate from UGC ===
    has_quiet_rule = "quiet" in rule_label.get("planning_tags", [])
    quiet_positive = len(re.findall(r"安静|静谧|清幽|宁静|清净|僻静", blob))
    quiet_negative = len(re.findall(r"吵|嘈杂|喧闹|拥挤|人挤人|人山人海", blob))
    has_quiet_tag = "环境优雅" in tags
    if has_quiet_rule and quiet_negative > quiet_positive and quiet_negative >= 2:
        result["planning_tags_remove"].append("quiet")
        changes.append("移除quiet:UGC多次提到吵闹/拥挤")
        confidence_sum += 0.72
        confidence_count += 1
    elif has_quiet_rule and not has_quiet_tag and quiet_positive < 1:
        # Quiet was only from UGC regex, no reviewTag support, no UGC evidence
        result["planning_tags_remove"].append("quiet")
        changes.append("移除quiet:无reviewTag支持且UGC无安静证据")
        confidence_sum += 0.65
        confidence_count += 1

    # === 3. night_friendly: from UGC ===
    has_night_rule = "night_friendly" in rule_label.get("planning_tags", [])
    night_ugc = len(re.findall(r"夜景|夜色|灯|霓虹|晚上去|晚上来|夜游|夜间|夜生活", blob))
    if not has_night_rule and night_ugc >= 2:
        result["planning_tags_add"].append("night_friendly")
        changes.append("新增night_friendly:UGC提到夜景/灯光")
        confidence_sum += 0.7
        confidence_count += 1

    # === 4. rain_friendly: from UGC ===
    has_rain_rule = "rain_friendly" in rule_label.get("planning_tags", [])
    rain_ugc = len(re.findall(r"室内|不受天气|下雨也能|雨天|空调", blob))
    is_indoor = "室内" in blob or "商场" in categories
    if not has_rain_rule and (is_indoor and rain_ugc >= 1):
        result["planning_tags_add"].append("rain_friendly")
        changes.append("新增rain_friendly:室内场所")
        confidence_sum += 0.7
        confidence_count += 1

    # === 5. walk_heavy: from UGC ===
    has_walk_rule = "walk_heavy" in rule_label.get("risk_tags", [])
    walk_ugc = len(re.findall(r"走路|逛完.*累|腿.*酸|脚.*疼|走.*久|地方.*大|爬|台阶|坡", blob))
    if not has_walk_rule and walk_ugc >= 3:
        result["risk_tags_add"].append("walk_heavy")
        changes.append("新增walk_heavy:UGC提到走路累/地方大")
        confidence_sum += 0.72
        confidence_count += 1

    # === 6. queue_heavy: cross-validate ===
    has_queue_rule = "queue_heavy" in rule_label.get("risk_tags", [])
    queue_ugc = len(re.findall(r"排队|等位|等.*久|队伍|取号|等了", blob))
    has_queue_tag = "等位久" in tags
    if has_queue_rule and not has_queue_tag and queue_ugc < 2:
        # Only from rule's UGC regex, not strongly supported
        result["risk_tags_remove"].append("queue_heavy")
        changes.append("移除queue_heavy:无reviewTag支持,UGC排队证据弱")
        confidence_sum += 0.65
        confidence_count += 1
    elif not has_queue_rule and (has_queue_tag or queue_ugc >= 4):
        result["risk_tags_add"].append("queue_heavy")
        changes.append("新增queue_heavy:UGC多次提到排队")
        confidence_sum += 0.7
        confidence_count += 1

    # === 7. family_friendly: from UGC ===
    has_family_rule = "family_friendly" in rule_label.get("planning_tags", [])
    family_ugc = len(re.findall(r"带娃|带小孩|带孩子|亲子|宝宝|小朋友|儿童|亲子区|游乐", blob))
    has_family_tag = "亲子友好" in tags
    if not has_family_rule and family_ugc >= 2:
        result["planning_tags_add"].append("family_friendly")
        changes.append("新增family_friendly:UGC提到带娃/亲子")
        confidence_sum += 0.75
        confidence_count += 1

    # === 8. senior_friendly: from UGC ===
    senior_ugc = len(re.findall(r"老人|长辈|老年人|无障碍|轮椅|电梯", blob))
    if senior_ugc >= 2:
        result["planning_tags_add"].append("senior_friendly")
        changes.append("新增senior_friendly:UGC提到老人/无障碍")
        confidence_sum += 0.7
        confidence_count += 1

    # === 9. solo_friendly: from UGC ===
    solo_ugc = len(re.findall(r"一个人|独自|独行|单人|独自来|自己来", blob))
    if solo_ugc >= 2:
        result["planning_tags_add"].append("solo_friendly")
        changes.append("新增solo_friendly:UGC提到一个人来")
        confidence_sum += 0.68
        confidence_count += 1

    # === 10. rest_friendly: verify from UGC ===
    has_rest_rule = "rest_friendly" in rule_label.get("planning_tags", [])
    rest_ugc = len(re.findall(r"休息|歇脚|坐一坐|歇一会儿|坐下来", blob))
    if has_rest_rule and rest_ugc < 1 and "免费 WiFi" not in special:
        # Was from UGC "聊天" or "休息" regex, not supported by actual evidence
        result["planning_tags_remove"].append("rest_friendly")
        changes.append("移除rest_friendly:UGC无休息/歇脚证据且无WiFi")
        confidence_sum += 0.6
        confidence_count += 1

    # === 11. crowded_weekend: verify ===
    has_crowded = "crowded_weekend" in rule_label.get("risk_tags", [])
    crowded_ugc = len(re.findall(r"人多|拥挤|爆满|人挤人|周末.*人|高峰", blob))
    if has_crowded and crowded_ugc < 2 and review_count < 2000:
        result["risk_tags_remove"].append("crowded_weekend")
        changes.append("移除crowded_weekend:UGC人挤人证据不足")
        confidence_sum += 0.6
        confidence_count += 1

    # === 12. poi_role correction ===
    current_role = rule_label.get("poi_role", "")
    # If UGC strongly suggests a different role
    is_food_heavy = len(re.findall(r"菜品|味道|好吃|点菜|上菜|菜品|口味|主厨|招牌菜", blob)) >= 4
    is_sight_heavy = len(re.findall(r"景色|风景|拍照|打卡|壮观|景点|游览|逛|历史|文化|建筑", blob)) >= 4
    if current_role == "persona_preferred" and is_food_heavy and not is_sight_heavy:
        if "美食" in categories:
            result["poi_role"] = "meal"
            changes.append("poi_role修正:persona_preferred→meal(UGC以美食描述为主)")
            confidence_sum += 0.7
            confidence_count += 1
    elif current_role == "connector" and is_sight_heavy and not is_food_heavy:
        if review_count >= 500:
            result["poi_role"] = "persona_preferred"
            changes.append("poi_role修正:connector→persona_preferred(UGC以景点描述为主)")
            confidence_sum += 0.65
            confidence_count += 1

    # === 13. suggested_slots adjustment ===
    current_slots = rule_label.get("suggested_slots", [])
    if result["poi_role"] == "meal" and "lunch" not in current_slots:
        result["suggested_slots"] = ordered_slots(current_slots + ["lunch", "dinner"])
        changes.append("suggested_slots修正:修正为meal时段")
    elif "night_friendly" in (set(result["planning_tags_add"]) | set(rule_label.get("planning_tags", []))):
        if "evening" not in current_slots:
            result["suggested_slots"] = ordered_slots(current_slots + ["evening"])
            changes.append("suggested_slots修正:增加evening(有night_friendly)")
    elif "solo_friendly" in result["planning_tags_add"] and "afternoon" not in current_slots:
        result["suggested_slots"] = ordered_slots(current_slots + ["afternoon"])
        changes.append("suggested_slots修正:增加afternoon(适合独行)")

    # === 14. stay minutes adjustment ===
    if is_sight_heavy and not is_food_heavy:
        current_max = rule_label.get("max_stay_minutes", 120)
        if current_max < 150:
            result["max_stay_minutes"] = 150
            changes.append("max_stay修正:景点型UGC→增加游览时间")
            confidence_sum += 0.6
            confidence_count += 1

    # Calculate overall confidence
    if confidence_count > 0:
        result["confidence"] = round(confidence_sum / confidence_count, 2)
    else:
        result["confidence"] = 0.0

    result["ai_notes"] = "; ".join(changes) if changes else "规则标签合理，无需修正。"

    return result


def main() -> None:
    tasks = []
    for line in TASKS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(json.loads(line))

    output: dict[str, dict[str, dict]] = {}
    stats = {
        "total_tasks": len(tasks),
        "labeled": 0,
        "skipped_low_confidence": 0,
        "total_additions": 0,
        "total_removals": 0,
        "role_corrections": 0,
    }

    for task in tasks:
        city = task["city"]
        shop_id = task["openshopid"]

        if city not in output:
            output[city] = {}

        analysis = analyze_ugc(task.get("ugc_excerpt", []), task)

        # Skip if no changes and low confidence
        if analysis["confidence"] < MIN_CONFIDENCE:
            stats["skipped_low_confidence"] += 1
            continue

        # Build the label override
        label = {}
        if analysis["planning_tags_add"]:
            label["planning_tags"] = analysis["planning_tags_add"]
            stats["total_additions"] += len(analysis["planning_tags_add"])
        if analysis["planning_tags_remove"]:
            label["planning_tags_remove"] = analysis["planning_tags_remove"]
            stats["total_removals"] += len(analysis["planning_tags_remove"])
        if analysis["risk_tags_add"]:
            label["risk_tags"] = analysis["risk_tags_add"]
            stats["total_additions"] += len(analysis["risk_tags_add"])
        if analysis["risk_tags_remove"]:
            label["risk_tags_remove"] = analysis["risk_tags_remove"]
            stats["total_removals"] += len(analysis["risk_tags_remove"])
        if analysis["poi_role"]:
            label["poi_role"] = analysis["poi_role"]
            stats["role_corrections"] += 1
        if analysis["suggested_slots"]:
            label["suggested_slots"] = analysis["suggested_slots"]
        if analysis["min_stay_minutes"]:
            label["min_stay_minutes"] = analysis["min_stay_minutes"]
        if analysis["max_stay_minutes"]:
            label["max_stay_minutes"] = analysis["max_stay_minutes"]
        label["confidence"] = analysis["confidence"]
        label["ai_notes"] = analysis["ai_notes"]

        output[city][shop_id] = label
        stats["labeled"] += 1

    # Write output
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"AI 补标完成:")
    print(f"  总任务数: {stats['total_tasks']}")
    print(f"  实际补标: {stats['labeled']}")
    print(f"  跳过(低置信度): {stats['skipped_low_confidence']}")
    print(f"  标签新增: {stats['total_additions']}")
    print(f"  标签移除: {stats['total_removals']}")
    print(f"  poi_role修正: {stats['role_corrections']}")

    # Per-city breakdown
    for city in output:
        print(f"\n  [{city}] {len(output[city])} POIs 补标")
        add_tags = Counter()
        rm_tags = Counter()
        for sid, lb in output[city].items():
            for t in lb.get("planning_tags", []):
                add_tags[f"+{t}"] += 1
            for t in lb.get("risk_tags", []):
                add_tags[f"+{t}"] += 1
            for t in lb.get("planning_tags_remove", []):
                rm_tags[f"-{t}"] += 1
            for t in lb.get("risk_tags_remove", []):
                rm_tags[f"-{t}"] += 1
        if add_tags:
            print(f"    新增标签: {dict(add_tags.most_common(10))}")
        if rm_tags:
            print(f"    移除标签: {dict(rm_tags.most_common(10))}")

    print(f"\n✅ wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
