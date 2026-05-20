"""v1.10 P0.2: 3 variant 对同类 amap 注入 POI 的打分应明显不同.

修前: amap text_search 命中的 POI 没有 enriched.planning_tags / risk_tags,
score_poi 的 variant 偏置块 (line 91+) 完全不生效, 3 variant 看到同样的 top-N,
LLM 选出同样的 stops.

修后: must_consider=True 且无 enriched.planning_tags 时, 用 name + categories
关键词推断 variant bias.
"""

from agents.candidate_pool import score_poi
from dianping.schemas import POI, EnrichedLabel, ParsedIntent


def _intent(interests=None):
    return ParsedIntent(
        city="南昌",
        days=1,
        traveler_type="情侣",
        time_window="一日",
        anchor_lng=115.904,
        anchor_lat=28.673,
        anchor_radius_km=3.0,
        interests=list(interests or []),
    )


def _injected_poi(name, categories):
    """模拟 _apply_text_search_keywords 注入的 POI: must_consider=True, 无 planning_tags."""
    p = POI(
        openshopid=f"amap_{name}",
        name=name,
        city="南昌",
        latitude=28.673,
        longitude=115.904,
        categories=categories,
        avgprice=0,
        star=0,
        business_hour="",
    )
    p.enriched = EnrichedLabel(
        poi_role="city_essential",
        must_consider=True,
        manual_priority=80,
        planning_tags=[],
        risk_tags=[],
    )
    return p


def test_low_queue_prefers_niche_over_provincial():
    """low_queue 对 '省' / '商场' 减权, 对 '县' / '纪念' 加权.

    场景: amap 搜 '南昌博物馆' 返回 7 家, 3 variant 应选不同候选.
    """
    intent = _intent()
    big = _injected_poi("江西省博物馆", ["科教文化", "博物馆"])
    small = _injected_poi("南昌县博物馆", ["科教文化", "博物馆"])
    s_main_big = score_poi(big, intent, variant="main")
    s_main_small = score_poi(small, intent, variant="main")
    s_lq_big = score_poi(big, intent, variant="low_queue")
    s_lq_small = score_poi(small, intent, variant="low_queue")
    # main: 两者打分相近 (没 variant bias)
    # low_queue: small 应明显高过 big
    assert s_lq_small > s_lq_big + 15, (
        f"low_queue should prefer 南昌县博物馆 over 江西省博物馆: "
        f"big={s_lq_big} small={s_lq_small}"
    )
    # main 不该有 variant bias
    assert abs(s_main_big - s_main_small) < 5, (
        f"main should not bias: big={s_main_big} small={s_main_small}"
    )


def test_interest_first_boosts_culture_and_user_interests():
    """interest_first 对 '博物/艺术/文化' 加 +10, 对用户 intent.interests 命中加 +15."""
    intent = _intent(interests=["文化"])
    museum = _injected_poi("江西省博物馆", ["科教文化", "博物馆"])
    mall = _injected_poi("正嘉都荟广场", ["购物服务", "商场"])
    s_main_museum = score_poi(museum, intent, variant="main")
    s_if_museum = score_poi(museum, intent, variant="interest_first")
    s_if_mall = score_poi(mall, intent, variant="interest_first")
    # interest_first 对博物馆加分明显
    assert s_if_museum > s_main_museum + 15, (
        f"interest_first should boost museum: main={s_main_museum} if={s_if_museum}"
    )
    # interest_first 下博物馆应明显高于商场
    assert s_if_museum > s_if_mall + 15, (
        f"interest_first should prefer museum over mall: "
        f"museum={s_if_museum} mall={s_if_mall}"
    )


def test_interest_first_boosts_indie_keywords_for_chain_food():
    """interest_first 对'独立店/老字号/手工/精品/小店/特色/创意/网红' 关键词加分.

    场景: 哈尔滨拌粉/咖啡/西餐没有 enriched.planning_tags=文化, 现有 bias 打不出区分.
    新规则: 让 interest_first 对'独立/非连锁'信号也加分, 真正分流同名连锁店."""
    intent = _intent()
    chain = _injected_poi("塔道斯西餐厅(中央大街店)", ["美食", "西餐"])
    indie = _injected_poi("安德列维奇的店", ["美食", "西餐"])
    s_if_chain = score_poi(chain, intent, variant="interest_first")
    s_if_indie = score_poi(indie, intent, variant="interest_first")
    s_main_chain = score_poi(chain, intent, variant="main")
    s_main_indie = score_poi(indie, intent, variant="main")
    # main 不区分（两者无显著差距）
    assert abs(s_main_chain - s_main_indie) < 5, (
        f"main should not bias indie vs chain: chain={s_main_chain} indie={s_main_indie}"
    )
    # interest_first: indie 应显著高于 chain（"的店" 是独立小店强信号 / "中央大街店" 是连锁分店减分）
    assert s_if_indie > s_if_chain + 8, (
        f"interest_first should prefer indie over chain: "
        f"chain={s_if_chain} indie={s_if_indie}"
    )


def test_main_variant_unchanged_for_injected_poi():
    """main variant 对 amap 注入 POI 的打分应等同于无 variant bias 时.

    回归条件: 不应该让 main 也走 variant 分支, 否则破坏现状.
    """
    intent = _intent(interests=["文化"])
    museum = _injected_poi("江西省博物馆", ["科教文化", "博物馆"])
    # main 的分数 = manual_priority 80 + (其他基础项) — 没 variant 偏置
    # 验证: 加 variant=main 后跟无 variant 信号时 (默认 'main') 一致
    s_with_main = score_poi(museum, intent, variant="main")
    s_default = score_poi(museum, intent)  # variant default = main
    assert s_with_main == s_default
