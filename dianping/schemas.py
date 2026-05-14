"""Pydantic v2 schemas mirroring Dianping POI / UGC interface field tables.

All rich fields are Optional/default-empty to:
1. Accommodate unknown permission scenario for the real API.
2. Tolerate mock data variations.

Source of truth: mt接口文档.md (POI 详情 / 搜索 / UGC interface specs)
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============== UGC nested ===============


class UGC(BaseModel):
    nick: str = ""
    userface: str = ""
    ispithy: bool = False
    score: float = 0.0
    star: int = 0
    content: str = ""
    photos: list[str] = Field(default_factory=list)
    addtime: int = 0  # millisecond timestamp


class ReviewTag(BaseModel):
    tag: str
    hit: int = 0


# =============== Dishes ===============


class Dish(BaseModel):
    dishName: str
    picUrl: str = ""
    price: float = 0.0
    recommendCount: int = 0


# =============== Mall info ===============


class MallInfo(BaseModel):
    popularShops: list[str] = Field(default_factory=list)
    dzPopularShops: list[str] = Field(default_factory=list)
    discount: bool = False
    foodRankingListUrl: str = ""
    mFoodRankingListUrl: str = ""
    appFoodRankingListUrl: str = ""
    floorGuideUrl: str = ""
    mFloorGuideUrl: str = ""
    appFloorGuideUrl: str = ""
    discountUrl: str = ""
    mDiscountUrl: str = ""
    appDiscountUrl: str = ""
    foodListUrl: str = ""
    mallBaseInfoUrl: str = ""
    mMallBaseInfoUrl: str = ""
    appMallBaseInfoUrl: str = ""


# =============== Deal info ===============


class DealInfo(BaseModel):
    dealName: str
    originPrice: float = 0.0
    discountPrice: float = 0.0
    dealPicUrl: str = ""
    shopName: str = ""
    type: int = 1  # 1 美食 2 到综


# =============== Takeaway info ===============


class TakeawayInfo(BaseModel):
    tag: str = ""
    longTag: str = ""
    url: str = ""
    mUrl: str = ""


# =============== Shop image ===============


class ShopPic(BaseModel):
    picUrl: str = ""
    title: str = ""
    addTime: str = ""


# =============== I18n ===============


class ShopI18n(BaseModel):
    shopName: str = ""
    branchName: str = ""
    address: str = ""


# =============== POI (full detail) ===============


class POI(BaseModel):
    """Full POI detail per /router/poi/getsinglepoi field table."""

    model_config = ConfigDict(extra="ignore")

    # --- identity ---
    openshopid: str
    openstatus: int = 1
    highquality: int = 0
    name: str
    branch_name: str = ""
    address: str = ""
    shopDesc: str = ""
    city: str
    isOverseas: bool = False
    latitude: float
    longitude: float
    telephone: str = ""
    business_hour: str = ""
    categories: list[str] = Field(default_factory=list)
    shopI18ns: list[ShopI18n] = Field(default_factory=list)

    # --- urls (kept Optional, not used in v0 logic) ---
    mShopInfoUrl: str = ""
    appShopInfoUrl: str = ""
    evtShopInfoUrl: str = ""
    pcShopInfoUrl: str = ""
    wxShopInfoUrl: str = ""
    headPic: str = ""
    headPicVisible: int = 0

    # --- review aggregates ---
    reviewCount: int = 0
    star: float = 0.0
    avgprice: int = 0
    reviewTags: list[ReviewTag] = Field(default_factory=list)
    mReviewAllUrl: str = ""
    appReviewAllUrl: str = ""

    # --- UGC list (precision selected) ---
    ugcs: list[UGC] = Field(default_factory=list)

    # --- pictures ---
    picCount: int = 0
    shopPics: list[ShopPic] = Field(default_factory=list)

    # --- recommended dishes ---
    dishs: list[Dish] = Field(default_factory=list)
    mRecommendDishUrl: str = ""
    appRecommendDishUrl: str = ""

    # --- attributes ---
    special: list[str] = Field(default_factory=list)
    isBlackPearl: int = 0
    takeawayable: bool = False
    takeawayinfo: Optional[TakeawayInfo] = None
    queueable: bool = False
    appQueueUrl: str = ""
    mQueueUrl: str = ""
    bookable: bool = False
    appBookURL: str = ""
    mBookURL: str = ""

    # --- mall + deal ---
    mallInfo: Optional[MallInfo] = None
    dealInfo: list[DealInfo] = Field(default_factory=list)

    brandName: str = ""

    # --- v0 business extension fields, optional ---
    min_stay_minutes: Optional[int] = None
    max_stay_minutes: Optional[int] = None

    # --- v2.5 persona routing ---
    persona_labels: Optional["PersonaLabels"] = None

    # --- v1.7 即时出发: enriched routing label ---
    enriched: Optional["EnrichedLabel"] = None


# =============== Search result item ===============


class SearchRecord(BaseModel):
    """Per /router/poisearch/search records.item.

    Distance / shopaddress / category require permission and may be missing.
    """

    model_config = ConfigDict(extra="ignore")

    openshopid: str
    name: str
    branchname: Optional[str] = ""
    distance: Optional[float] = None
    shopaddress: Optional[str] = None
    category: Optional[str] = None


# =============== Business domain types (mtagent-internal) ===============

TravelerType = Literal["情侣", "家庭亲子", "银发", "独行", "商务", "朋友团"]
BudgetLevel = Literal["性价比", "适中", "精致"]
PaceLevel = Literal["暴走", "适中", "佛系"]
SlotName = Literal["上午景点", "午饭", "下午", "下午茶", "晚饭", "夜场"]
ModifierName = Literal["轻量体力", "重文化", "重美食", "怕排队"]
# v1.7 即时出发: 半日/一日 时间窗口
TimeWindow = Literal["半日_上午", "半日_下午", "半日_夜间", "一日", "多日"]
# v1.7 即时出发: 用户约束 (与 modifiers 并行, modifiers 是负空间口语, constraints 是中性结构)
ConstraintName = Literal[
    "avoid_queue",  # 怕排队
    "avoid_walking",  # 少走路
    "avoid_cross_district",  # 不想跨区
    "need_meal",  # 必须安排餐饮
]


class PersonaLabels(BaseModel):
    """v2.5: Per-POI labels for persona routing."""

    traveler_types: list[TravelerType] = Field(default_factory=list)
    modifiers: dict[ModifierName, bool] = Field(default_factory=dict)


# v1.7 即时出发: enriched 标签 schema (来自 data/poi_enriched_labels.json)
PoiRole = Literal[
    "city_essential", "persona_preferred", "meal", "connector", "fallback"
]
UniversalLevel = Literal["high", "medium", "low"]
SuggestedSlot = Literal[
    "morning", "lunch", "afternoon", "afternoon_tea", "dinner", "evening"
]


class EnrichedLabel(BaseModel):
    """Per-POI enriched routing label. Source: data/poi_enriched_labels.json.

    Generated by data-foundation pipeline (agent + manual). Loaded by DianpingClient
    and attached to POI for Planner consumption.
    """

    model_config = ConfigDict(extra="ignore")

    # role + priority
    poi_role: PoiRole = "fallback"
    universal_level: UniversalLevel = "low"
    must_consider: bool = False
    manual_priority: int = 0

    # routing-relevant tags
    planning_tags: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)

    # geography
    district: str = ""
    city_zone: str = ""
    neighbor_zones: list[str] = Field(default_factory=list)

    # scheduling
    suggested_slots: list[SuggestedSlot] = Field(default_factory=list)
    min_stay_minutes: int = 60
    max_stay_minutes: int = 120

    # persona overlap (与 PersonaLabels 字段重叠, 这里也带一份方便 Planner 单点取)
    traveler_types: list[TravelerType] = Field(default_factory=list)
    modifiers: dict[ModifierName, bool] = Field(default_factory=dict)

    # provenance
    label_sources: list[str] = Field(default_factory=list)


class UserInput(BaseModel):
    free_text: str
    cookie_key: Optional[str] = None  # v3 reserved


TripMode = Literal[
    "anchor_explore",
    "layover_eat",
    "layover_explore",
    "landmark_must",
    "multi_day",
]
HubType = Literal["train", "highspeed", "airport", "bus"]


class ParsedIntent(BaseModel):
    city: str
    days: int
    traveler_type: TravelerType
    budget_level: Optional[BudgetLevel] = None
    pace: Optional[PaceLevel] = None
    preferences: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    start_date: Optional[date] = None
    modifiers: dict[ModifierName, bool] = Field(default_factory=dict)
    # v1.7 即时出发扩展 (全部 optional, 多日路径不依赖, 不破坏 v0/v1/v2.5 测试)
    time_window: Optional[TimeWindow] = None
    interests: list[str] = Field(default_factory=list)
    constraints: dict[ConstraintName, bool] = Field(default_factory=dict)
    start_location_text: Optional[str] = None  # "我现在在 XX 附近", geo 解析后续做
    start_with_meal: bool = False  # Profiler 时刻感知推断: 现在该先吃还是先玩
    estimated_hours: Optional[int] = None  # 实际可用时长 (从 now → time_window 结束)
    current_time: Optional[str] = None  # ISO 8601, Profiler 注入的服务器时间快照
    # v1.7.2 天气感知 (高德 weather API)
    # hint 值: rainy / stormy / snowy / hot / cold / normal / unknown
    weather_hint: Optional[str] = None
    weather_raw: Optional[str] = None  # 原始描述 "小雨" / "晴" / "多云"
    weather_temp_c: Optional[int] = None
    # v1.8 trip_mode 路由 + 锚点驱动 (全部 optional, 老 v1.7 路径不依赖)
    trip_mode: Optional[TripMode] = None
    anchor_radius_km: Optional[float] = None  # 默认按 mode 推 (anchor_explore=4.0)
    hub_type: Optional[HubType] = None  # layover 专用
    safety_margin_min: Optional[int] = None  # layover 返程预留分钟
    anchor_lng: Optional[float] = None  # 高德 geocode 解析后的坐标
    anchor_lat: Optional[float] = None
    anchor_resolved_name: Optional[str] = None  # 高德标准化地名


class ProfilerOutput(BaseModel):
    understood: ParsedIntent
    ready_to_plan: bool
    missing_fields: list[str] = Field(default_factory=list)
    narrative: str = ""


class TimeSlot(BaseModel):
    """Concrete time slot occupied by a Stop."""

    name: SlotName
    start: time
    end: time


TransitMode = Literal["drive", "walk", "transit", "bicycle"]
# v1.7: 三档可信度. amap=真实路径; estimated=有距离/时间但无街道点; unavailable=完全失败, 前端不应画线
TransitSource = Literal["amap", "estimated", "unavailable"]


class TransitInfo(BaseModel):
    """Per-mode transit details for one stop pair."""

    mode: TransitMode
    minutes: int
    distance_km: float
    price_yuan: Optional[float] = None
    source: TransitSource


class Stop(BaseModel):
    poi: POI
    slot: TimeSlot
    arrival_time: time
    leave_time: time
    transport_to_next_minutes: int = 30
    transport_options: Optional[dict[str, TransitInfo]] = None


class DayPlan(BaseModel):
    day_index: int
    anchor_district: str = ""
    stops: list[Stop] = Field(default_factory=list)
    transit_segments: list[dict] = Field(default_factory=list)
    # 每段形如: {"from_index": 0, "to_index": 1,
    #           "options": {mode: TransitInfo dict}, "recommended": "transit"}


class RouteDraft(BaseModel):
    days: list[DayPlan]
    summary: str = ""


class Patch(BaseModel):
    """Critic suggestion (v2 will populate)."""

    day: int
    stop_idx: int
    issue: str
    suggestion_type: Literal["replace", "remove", "swap_time"] = "replace"
    new_poi_id: Optional[str] = None


class Feedback(BaseModel):
    """Adjuster input (v3 will use)."""

    action: Literal["replace_stop", "redo_day", "mark_disliked", "mark_been_there"]
    target_day: Optional[int] = None
    target_stop_idx: Optional[int] = None
    reason: str = ""


# v1.9 Stage 3: Adjuster v1 request schema
AdjustOperation = Literal[
    "replace_stop", "remove_stop", "regenerate_day", "switch_variant"
]


class AdjustRequest(BaseModel):
    """POST /api/plan/{trip_id}/adjust request body.

    target 字段按 operation 不同含义:
    - replace_stop / remove_stop: day_index + slot_name
    - regenerate_day: day_index
    - switch_variant: variant
    """

    operation: AdjustOperation
    day_index: int = 0
    slot_name: str = ""  # SlotName 文本, replace/remove 用
    variant: str = ""  # switch_variant 用 (main / low_queue / interest_first)
    user_hint: str = ""  # 自由文本 "想换辣一点的"


class Event(BaseModel):
    """TripContext trace event."""

    timestamp: datetime
    agent: str
    type: str
    payload: dict = Field(default_factory=dict)


class UserMarked(BaseModel):
    """v0 schema reserved; v3 reads from user_profile."""

    been_there: list[str] = Field(default_factory=list)
    disliked: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    """v3 reserved."""

    cookie_key: str
    user_marked: UserMarked = Field(default_factory=UserMarked)
    loved_categories: list[str] = Field(default_factory=list)
    rejected_categories: list[str] = Field(default_factory=list)
    avg_budget_per_day: int = 0
    history: list[dict] = Field(default_factory=list)
