"""QuestionGenerator — 规划前澄清问题生成器 (v1.10).

用快速 LLM (DeepSeek Flash / Kimi / Qwen) 根据 ParsedIntent 生成 0-2 个澄清问题。
LLM 失败时静默返回空列表，路由退化为老路径。
"""

from __future__ import annotations

import json
import os
from typing import Awaitable, Callable, Optional

from dianping.schemas import ClarifyQuestion, ParsedIntent

_SYSTEM_PROMPT = """\
你是一个旅行规划助手，需要在为用户生成路线前，提出 0-2 个最有价值的补充问题。

规则：
1. 只问对路线影响大的信息缺口，不问已知信息
2. 意图已很丰富（有餐饮偏好 + 无排队地标）时输出 0 个问题
3. 每个问题必须提供恰好 3 个高质量、本地化的预设选项
4. 问题优先级：
   a. must_visit 含排队重地标（故宫/颐和园/兵马俑等）→ 询问预约状态
   b. 无餐饮偏好 + 全天行程 → 询问午餐/晚餐口味
   c. time_window 不明确 → 询问行程松紧
   d. traveler_type 含孩子 → 询问孩子年龄/体力
5. 最多 2 个问题，每个问题 options 数组恰好 3 个元素

输出严格 JSON，格式：
{"questions": [{"idx": 0, "text": "...", "options": ["...", "...", "..."]}, ...]}
"""

_HIGH_QUEUE_LANDMARKS = {
    "故宫",
    "天安门",
    "颐和园",
    "天坛",
    "兵马俑",
    "大雁塔",
    "西湖",
    "外滩",
}


def _build_user_payload(intent: ParsedIntent, user_input: str) -> str:
    known = {
        "city": intent.city,
        "days": intent.days,
        "traveler_type": intent.traveler_type,
        "must_visit": list(intent.must_visit or []),
        "preferences": list(intent.preferences or []),
        "time_window": intent.time_window,
        "budget_level": intent.budget_level,
    }
    has_queue_landmark = any(
        lm in (intent.must_visit or []) for lm in _HIGH_QUEUE_LANDMARKS
    )
    has_food_pref = any("美食" in p or "餐" in p for p in (intent.preferences or []))

    hints = []
    if has_queue_landmark:
        hints.append("must_visit 含排队重地标，考虑询问预约状态")
    if not has_food_pref and (intent.time_window or "").startswith("一日"):
        hints.append("无餐饮偏好且全天行程，考虑询问午餐口味")

    return json.dumps(
        {
            "user_original_input": user_input,
            "parsed_intent": known,
            "generation_hints": hints,
        },
        ensure_ascii=False,
    )


class QuestionGenerator:
    def __init__(self, llm_call: Optional[Callable[[str, str], Awaitable[str]]] = None):
        self.llm_call = llm_call or _default_llm_call

    async def generate(
        self, *, intent: ParsedIntent, user_input: str
    ) -> list[ClarifyQuestion]:
        """返回 0-2 个 ClarifyQuestion。LLM 失败时返回空列表。"""
        payload = _build_user_payload(intent, user_input)
        try:
            raw = await self.llm_call(_SYSTEM_PROMPT, payload)
            data = json.loads(raw)
            questions = []
            for item in data.get("questions", [])[:2]:
                questions.append(
                    ClarifyQuestion(
                        idx=item["idx"],
                        text=item["text"],
                        options=item["options"][:3],
                    )
                )
            return questions
        except Exception:
            return []


async def _default_llm_call(system: str, user: str) -> str:
    """OpenAI-compatible call. 优先用 QUESTIONER_* env，回退到 Qwen。"""
    from openai import AsyncOpenAI

    api_key = os.environ.get("QUESTIONER_API_KEY") or os.environ.get(
        "DASHSCOPE_API_KEY", ""
    )
    base_url = os.environ.get(
        "QUESTIONER_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = os.environ.get("QUESTIONER_MODEL", "qwen-plus")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return resp.choices[0].message.content or '{"questions": []}'
