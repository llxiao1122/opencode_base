"""
memory/detect/detector.py — Main event detection entry point.

Orchestrates: signals → extraction → persistence → hazwaste enrichment.
"""

from datetime import datetime

from .signals import (
    _signal_count, _compute_confidence,
    ACTION_VERBS, EMERGENCY_KEYWORDS,
)
from .extractors import (
    _extract_entities, _extract_participants,
    _extract_time, _extract_title, _extract_items,
    _extract_report_to, _extract_related_teams,
    _extract_sender, _resolve_executor, _resolve_target,
)
from .persistence import _next_id, _persist
from .hazwaste import _enrich_hazwaste


def _guess_priority(text):
    if any(kw in text for kw in ["紧急", "立即", "马上", "立刻", "尽快"]):
        return "high"
    if any(kw in text for kw in ["注意", "重要", "严格"]):
        return "normal"
    return "normal"


def detect(text: str, current_user=None) -> list:
    """事件候选提取。
    Args:
        text: 输入文本
        current_user: 当前用户 {'name', 'role', 'team'}，用于 executor 解析
    """
    if not text.strip():
        return []

    entities = _extract_entities(text)
    participants = _extract_participants(text)

    signals = _signal_count(text, entities, participants)
    is_emergency = any(kw in text for kw in EMERGENCY_KEYWORDS)
    min_signals = 1 if (
        is_emergency or
        (len(text) <= 15 and entities and any(v in text for v in ACTION_VERBS))
    ) else 2
    if signals < min_signals:
        return []

    time_info = _extract_time(text)
    if not time_info.get("start") and not time_info.get("deadline"):
        time_info["start"] = datetime.now().strftime("%Y-%m-%d")
    items = _extract_items(text)
    title = _extract_title(text)

    confidence = _compute_confidence(
        signals=signals,
        entities_found=bool(entities),
        items_found=bool(items),
        time_found=bool(time_info.get("deadline") or time_info.get("start")),
    )

    requester = _extract_sender(text, entities)
    executor = _resolve_executor(participants, current_user=current_user)
    target = _resolve_target(participants)

    event = {
        "id": _next_id(),
        "type": "work_event",
        "title": title,
        "requester": requester,
        "executor": executor,
        "target": target,
        "entities": entities,
        "actions": [],
        "required_actions": [],
        "time": time_info,
        "items": [],
        "priority": _guess_priority(text),
        "confidence": confidence,
        "constraints": [],
        "evidence": [],
        "report_to": _extract_report_to(text),
        "participants": participants,
        "related_teams": _extract_related_teams(entities),
        "source": {
            "type": "text",
            "raw": text[:1000],
        },
        "detected_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if confidence >= 0.85:
        event["status"] = "active"
    elif confidence >= 0.60:
        event["status"] = "detected"
    else:
        return []

    _persist(event)
    return [event]
