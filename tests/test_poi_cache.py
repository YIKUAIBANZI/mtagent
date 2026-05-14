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


def test_build_enrich_prompt_includes_name_categories_typecode():
    from agents.poi_cache import build_enrich_prompt

    poi = {
        "name": "钟楼景区",
        "city": "深圳",
        "typecode": "110200",
        "categories": ["景点", "历史文化"],
    }
    prompt = build_enrich_prompt(poi)
    assert "钟楼景区" in prompt
    assert "深圳" in prompt
    assert "110200" in prompt
    assert "景点" in prompt


def test_build_enrich_prompt_lists_vocab():
    """prompt 应列出词表防 LLM 自造 tag."""
    from agents.poi_cache import build_enrich_prompt

    poi = {"name": "X", "city": "X", "typecode": "050000", "categories": ["美食"]}
    prompt = build_enrich_prompt(poi)
    assert "food_quality" in prompt or "planning_tags" in prompt
    assert "queue_heavy" in prompt or "risk_tags" in prompt
    assert "poi_role" in prompt


def test_classify_line_a_for_landmark_keywords():
    from agents.poi_cache import classify_line

    assert classify_line("西安城墙", "110000") == "A"
    assert classify_line("故宫博物院", "110000") == "A"
    assert classify_line("百年老字号店", "050000") == "A"


def test_classify_line_a_for_transit_typecode():
    from agents.poi_cache import classify_line

    assert classify_line("市民中心地铁站", "150500") == "A"
    assert classify_line("世界之窗", "110000") == "A"


def test_classify_line_b_for_food_and_shopping():
    from agents.poi_cache import classify_line

    assert classify_line("某网红咖啡", "050000") == "B"
    assert classify_line("万象天地", "060000") == "B"
    assert classify_line("某酒吧", "080000") == "B"


async def test_batch_enrich_empty_list_returns_empty():
    from agents.poi_cache import batch_enrich

    result = await batch_enrich([])
    assert result == {}


async def test_batch_enrich_calls_llm_per_poi(monkeypatch):
    from agents import poi_cache as pc

    call_count = {"n": 0}

    async def _fake_enrich(poi):
        call_count["n"] += 1
        return {
            "poi_role": "meal",
            "planning_tags": ["food_quality", "local_food"],
            "risk_tags": [],
            "city_zone": "test",
            "manual_priority": 75,
            "min_stay_minutes": 45,
            "max_stay_minutes": 90,
        }

    monkeypatch.setattr(pc, "_enrich_via_qwen", _fake_enrich)
    pois = [
        {
            "name": "A",
            "lng": 114.0,
            "lat": 22.0,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
        },
        {
            "name": "B",
            "lng": 114.1,
            "lat": 22.1,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
        },
        {
            "name": "C",
            "lng": 114.2,
            "lat": 22.2,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
        },
    ]
    result = await pc.batch_enrich(pois)
    assert call_count["n"] == 3
    assert len(result) == 3
    for entry in result.values():
        assert entry["poi_role"] == "meal"


async def test_lookup_and_enrich_all_cache_hit_skips_llm(monkeypatch, tmp_path):
    """全 cache hit → 不调 batch_enrich, 返回 POI 含 enriched."""
    from agents import poi_cache as pc
    from agents.anchor import AroundPOI

    cache_path = tmp_path / "cache.json"
    around = [
        AroundPOI(
            name="X",
            lng=114.0,
            lat=22.0,
            typecode="050000",
            distance_m=100,
            address="addr",
        ),
    ]
    key = pc.cache_key("X", 114.0, 22.0)
    seed_cache = {
        key: {
            "name": "X",
            "lng": 114.0,
            "lat": 22.0,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
            "enriched": {
                "poi_role": "meal",
                "planning_tags": ["food_quality", "local_food"],
                "risk_tags": [],
                "city_zone": "罗湖",
                "manual_priority": 80,
                "min_stay_minutes": 45,
                "max_stay_minutes": 90,
            },
            "source": "amap_around",
            "version": "v1.9.1",
            "created_at": "2026-01-01T00:00:00Z",
            "last_seen": "2026-01-01T00:00:00Z",
            "seen_count": 5,
        }
    }
    pc.save_cache(seed_cache, path=cache_path)

    batch_called = {"n": 0}

    async def _no_call(pois):
        batch_called["n"] += 1
        return {}

    monkeypatch.setattr(pc, "batch_enrich", _no_call)

    result = await pc.lookup_and_enrich(around, city="深圳", cache_path=cache_path)
    assert batch_called["n"] == 0
    assert len(result) == 1
    assert result[0].name == "X"
    assert result[0].enriched is not None
    assert result[0].enriched.poi_role == "meal"


async def test_lookup_and_enrich_miss_calls_batch_enrich_and_writes_cache(
    monkeypatch, tmp_path
):
    """全 miss → 调 batch_enrich, 写入 cache, 返回 POI 含 enriched."""
    from agents import poi_cache as pc
    from agents.anchor import AroundPOI

    cache_path = tmp_path / "cache.json"
    around = [
        AroundPOI(
            name="新店 A",
            lng=114.0,
            lat=22.0,
            typecode="050000",
            distance_m=200,
            address="addrA",
        ),
        AroundPOI(
            name="新店 B",
            lng=114.1,
            lat=22.1,
            typecode="110000",
            distance_m=300,
            address="addrB",
        ),
    ]
    fake_enriched_a = {
        "poi_role": "meal",
        "planning_tags": ["food_quality", "local_food"],
        "risk_tags": [],
        "city_zone": "罗湖",
        "manual_priority": 75,
        "min_stay_minutes": 45,
        "max_stay_minutes": 90,
    }
    fake_enriched_b = {
        "poi_role": "city_essential",
        "planning_tags": ["landmark", "photo_friendly"],
        "risk_tags": ["crowded_weekend"],
        "city_zone": "南山",
        "manual_priority": 90,
        "min_stay_minutes": 60,
        "max_stay_minutes": 120,
    }

    async def _fake_batch(pois, **kw):
        return {
            pc.cache_key("新店 A", 114.0, 22.0): fake_enriched_a,
            pc.cache_key("新店 B", 114.1, 22.1): fake_enriched_b,
        }

    monkeypatch.setattr(pc, "batch_enrich", _fake_batch)

    result = await pc.lookup_and_enrich(around, city="深圳", cache_path=cache_path)
    assert len(result) == 2
    names = {p.name for p in result}
    assert names == {"新店 A", "新店 B"}
    for p in result:
        assert p.enriched is not None
        assert len(p.enriched.planning_tags) >= 2

    # 写回 cache
    saved = pc.load_cache(path=cache_path)
    assert len(saved) == 2
    for entry in saved.values():
        assert entry["seen_count"] == 1


async def test_lookup_and_enrich_hit_increments_seen_count(monkeypatch, tmp_path):
    from agents import poi_cache as pc
    from agents.anchor import AroundPOI

    cache_path = tmp_path / "cache.json"
    key = pc.cache_key("X", 114.0, 22.0)
    seed = {
        key: {
            "name": "X",
            "lng": 114.0,
            "lat": 22.0,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
            "enriched": {
                "poi_role": "meal",
                "planning_tags": ["food_quality", "local_food"],
                "risk_tags": [],
                "city_zone": "罗湖",
                "manual_priority": 80,
                "min_stay_minutes": 45,
                "max_stay_minutes": 90,
            },
            "source": "amap_around",
            "version": "v1.9.1",
            "created_at": "2026-01-01T00:00:00Z",
            "last_seen": "2026-01-01T00:00:00Z",
            "seen_count": 3,
        }
    }
    pc.save_cache(seed, path=cache_path)

    async def _no_call(pois, **kw):
        return {}

    monkeypatch.setattr(pc, "batch_enrich", _no_call)

    around = [
        AroundPOI(
            name="X", lng=114.0, lat=22.0, typecode="050000", distance_m=100, address=""
        )
    ]
    await pc.lookup_and_enrich(around, city="深圳", cache_path=cache_path)
    saved = pc.load_cache(path=cache_path)
    assert saved[key]["seen_count"] == 4


async def test_lookup_and_enrich_llm_failure_returns_poi_without_enriched(
    monkeypatch, tmp_path
):
    """batch_enrich 失败 (key 不在返回 dict) → POI 仍返回但 enriched=None,
    走 _bucket_of categories 兜底."""
    from agents import poi_cache as pc
    from agents.anchor import AroundPOI

    cache_path = tmp_path / "cache.json"

    async def _empty_batch(pois, **kw):
        return {}

    monkeypatch.setattr(pc, "batch_enrich", _empty_batch)
    around = [
        AroundPOI(
            name="Z", lng=114.0, lat=22.0, typecode="050000", distance_m=100, address=""
        )
    ]
    result = await pc.lookup_and_enrich(around, city="深圳", cache_path=cache_path)
    assert len(result) == 1
    assert result[0].name == "Z"
    assert result[0].enriched is None  # LLM 失败, _bucket_of 走 categories


async def test_batch_enrich_failure_does_not_block_others(monkeypatch):
    from agents import poi_cache as pc

    async def _flaky_enrich(poi):
        if poi["name"] == "BAD":
            raise RuntimeError("LLM 失败")
        return {
            "poi_role": "meal",
            "planning_tags": ["food_quality", "local_food"],
            "risk_tags": [],
            "city_zone": "x",
            "manual_priority": 70,
            "min_stay_minutes": 45,
            "max_stay_minutes": 90,
        }

    monkeypatch.setattr(pc, "_enrich_via_qwen", _flaky_enrich)
    pois = [
        {
            "name": "OK1",
            "lng": 114.0,
            "lat": 22.0,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
        },
        {
            "name": "BAD",
            "lng": 114.1,
            "lat": 22.1,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
        },
        {
            "name": "OK2",
            "lng": 114.2,
            "lat": 22.2,
            "city": "深圳",
            "typecode": "050000",
            "categories": ["美食"],
        },
    ]
    result = await pc.batch_enrich(pois)
    # BAD 失败不进结果, OK1/OK2 应在
    assert len(result) == 2
    [v.get("_name") for v in result.values() if "_name" in v]
    # 用 cache_key 验证: BAD 的 key 不应出现
    from agents.poi_cache import cache_key

    bad_key = cache_key("BAD", 114.1, 22.1)
    assert bad_key not in result


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
