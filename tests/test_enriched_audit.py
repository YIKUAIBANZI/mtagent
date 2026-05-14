"""v1.9 enriched 脏点扫描规则单测."""

from scripts.audit_enriched import audit_poi, AuditFlag


def _poi_dict(**kw):
    """简化 dict, 不走 full POI schema (audit 只看必要字段)."""
    d = dict(
        openshopid="x",
        name="测试 POI",
        categories=["景点"],
        enriched={
            "poi_role": "city_essential",
            "manual_priority": 80,
            "city_zone": "福田",
            "planning_tags": ["photo_friendly", "landmark"],
            "risk_tags": [],
        },
    )
    d.update(kw)
    return d


def test_audit_flags_landmark_with_food_category():
    """城墙/古城/塔/寺 含 美食 categories → 脏点."""
    p = _poi_dict(name="西安城墙", categories=["美食"])
    flags = audit_poi(p)
    assert AuditFlag.LANDMARK_WITH_FOOD in flags


def test_audit_flags_hotel_in_route():
    """酒店/宾馆 不应进路线."""
    p = _poi_dict(name="如家酒店深圳店", categories=["住宿"])
    flags = audit_poi(p)
    assert AuditFlag.HOTEL_AS_POI in flags


def test_audit_flags_meal_role_without_food_category():
    """poi_role=meal 但 categories 不含美食."""
    p = _poi_dict(
        name="某公园",
        categories=["休闲娱乐"],
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "",
            "planning_tags": [],
            "risk_tags": [],
        },
    )
    flags = audit_poi(p)
    assert AuditFlag.MEAL_ROLE_NO_FOOD_CATEGORY in flags


def test_audit_flags_city_essential_low_priority():
    """city_essential 角色但 manual_priority < 70."""
    p = _poi_dict(
        enriched={
            "poi_role": "city_essential",
            "manual_priority": 50,
            "city_zone": "福田",
            "planning_tags": ["landmark"],
            "risk_tags": [],
        }
    )
    flags = audit_poi(p)
    assert AuditFlag.CITY_ESSENTIAL_LOW_PRIORITY in flags


def test_audit_flags_missing_city_zone():
    p = _poi_dict(
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "",
            "planning_tags": ["food_quality"],
            "risk_tags": [],
        },
        categories=["美食"],
    )
    flags = audit_poi(p)
    assert AuditFlag.MISSING_CITY_ZONE in flags


def test_audit_flags_too_few_planning_tags():
    p = _poi_dict(
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "福田",
            "planning_tags": ["food_quality"],
            "risk_tags": [],
        },
        categories=["美食"],
    )
    flags = audit_poi(p)
    assert AuditFlag.TOO_FEW_PLANNING_TAGS in flags


def test_audit_clean_poi_no_flags():
    p = _poi_dict(
        name="老孙家泡馍",
        categories=["美食"],
        enriched={
            "poi_role": "meal",
            "manual_priority": 80,
            "city_zone": "钟楼-鼓楼",
            "planning_tags": ["food_quality", "local_food", "lunch_friendly"],
            "risk_tags": [],
        },
    )
    flags = audit_poi(p)
    assert flags == []
