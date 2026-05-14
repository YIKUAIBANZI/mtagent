"""v1.9.2 M6: must_visit 未命中本地 POI 时, SSE 发 chat 警告."""

from __future__ import annotations

import json


def _parse_sse(body: str):
    out = []
    cur_event = None
    cur_data = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            cur_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            cur_data = line[len("data:") :].strip()
        elif line == "":
            if cur_event:
                try:
                    out.append((cur_event, json.loads(cur_data)))
                except Exception:
                    out.append((cur_event, {"_raw": cur_data}))
                cur_event = None
                cur_data = ""
    return out


def test_unmatched_must_visit_emits_chat_warning(sse_app_client):
    """用户必去 '完全不存在的虚构景点XYZ', SSE 应发 chat 警告."""
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照 必去完全虚构景点XYZ"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    chat_evs = [
        d for ev, d in events if ev == "chat" and d.get("kind") == "must_visit_warning"
    ]
    assert len(chat_evs) >= 1, (
        f"应发 must_visit_warning chat 事件, 实际 events={[e[0] for e in events]}"
    )
    assert "完全虚构景点XYZ" in chat_evs[0]["unmatched"]


def test_matched_must_visit_no_warning(sse_app_client):
    """用户必去 mock 库里有的 POI, 不发警告."""
    # 西安 mock 含 "钟楼"  / "兵马俑" 等大景点
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照 必去钟楼"},
    )
    events = _parse_sse(resp.text)
    chat_evs = [
        d for ev, d in events if ev == "chat" and d.get("kind") == "must_visit_warning"
    ]
    assert chat_evs == [], f"钟楼 mock 中存在, 不应警告, 实际: {chat_evs}"


def test_no_must_visit_no_warning(sse_app_client):
    resp = sse_app_client.post(
        "/api/plan/stream",
        json={"free_text": "情侣 西安 半天 拍照"},
    )
    events = _parse_sse(resp.text)
    chat_evs = [
        d for ev, d in events if ev == "chat" and d.get("kind") == "must_visit_warning"
    ]
    assert chat_evs == []
