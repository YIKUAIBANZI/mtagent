"""v1.9 Stage 1.5: POI Cache 骨架 — cache_key + load/save + upsert."""


from agents.poi_cache import (
    cache_key,
    load_cache,
    save_cache,
    upsert_entry,
)


def test_cache_key_stable_for_same_inputs():
    k1 = cache_key("钟楼景区", 114.0571, 22.5421)
    k2 = cache_key("钟楼景区", 114.0571, 22.5421)
    assert k1 == k2


def test_cache_key_normalizes_paren_and_branch_suffix():
    """复用 anchor.py 的 _norm_name: 去括号 + 总店/分店 后缀."""
    a = cache_key("老孙家泡馍", 108.9398, 34.2658)
    b = cache_key("老孙家泡馍(总店)", 108.9398, 34.2658)
    c = cache_key("老孙家泡馍 分店", 108.9398, 34.2658)
    assert a == b == c


def test_cache_key_coord_precision_4_digits():
    """≤ 11m 漂移视为同点; 跨区不同坐标不撞 key."""
    same = cache_key("某点", 114.0571, 22.5421)
    drift = cache_key("某点", 114.05712, 22.54211)
    diff = cache_key("某点", 114.1200, 22.5421)
    assert same == drift
    assert same != diff


def test_load_cache_returns_empty_when_file_missing(tmp_path):
    p = tmp_path / "no_such.json"
    data = load_cache(path=p)
    assert data == {}


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "cache.json"
    payload = {
        "k1|114.0571|22.5421": {
            "name": "钟楼",
            "lng": 114.0571,
            "lat": 22.5421,
            "city": "深圳",
            "typecode": "110000",
            "categories": ["景点"],
            "enriched": {
                "poi_role": "city_essential",
                "manual_priority": 90,
                "city_zone": "罗湖",
                "planning_tags": ["landmark"],
                "risk_tags": [],
                "min_stay_minutes": 60,
                "max_stay_minutes": 120,
            },
            "source": "amap_around",
            "version": "v1.9.1",
            "seen_count": 1,
        }
    }
    save_cache(payload, path=p)
    loaded = load_cache(path=p)
    assert loaded == payload


def test_upsert_new_entry_sets_seen_count_one(tmp_path):
    cache = {}
    key = cache_key("新店", 114.0, 22.0)
    upsert_entry(
        cache,
        key,
        name="新店",
        lng=114.0,
        lat=22.0,
        city="深圳",
        typecode="050000",
        categories=["美食"],
        enriched={
            "poi_role": "meal",
            "manual_priority": 75,
            "city_zone": "罗湖",
            "planning_tags": ["food_quality", "local_food"],
            "risk_tags": [],
            "min_stay_minutes": 45,
            "max_stay_minutes": 90,
        },
        source="amap_around",
    )
    assert key in cache
    assert cache[key]["seen_count"] == 1
    assert cache[key]["name"] == "新店"
    assert "created_at" in cache[key]
    assert "last_seen" in cache[key]


def test_upsert_existing_entry_increments_seen_count(tmp_path):
    cache = {}
    key = cache_key("旧店", 114.0, 22.0)
    upsert_entry(
        cache,
        key,
        name="旧店",
        lng=114.0,
        lat=22.0,
        city="深圳",
        typecode="050000",
        categories=["美食"],
        enriched={"poi_role": "meal"},
        source="amap_around",
    )
    first_seen = cache[key]["last_seen"]
    upsert_entry(
        cache,
        key,
        name="旧店",
        lng=114.0,
        lat=22.0,
        city="深圳",
        typecode="050000",
        categories=["美食"],
        enriched={"poi_role": "meal"},
        source="amap_around",
    )
    assert cache[key]["seen_count"] == 2
    # last_seen 应被覆盖 (但 ISO 字符串可能因调用太快相同; 至少不应少于 first_seen)
    assert cache[key]["last_seen"] >= first_seen
    assert cache[key]["created_at"] <= first_seen
