"""
core/event.py — Pure fact extraction layer.

Only answers: who, what action, to whom, when.
No reasoning, no "what should I do". Pure facts.

Input: raw text
Output: Event dict
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.shared import get_role, has_known_entity, find_entities_in_text

TOOLS_DIR = Path(__file__).resolve().parent.parent

EVENT_TYPES = ["instruction", "notification", "report", "inspection", "incident", "feedback", "unknown"]


def extract(text: str, current_user=None) -> dict:
    """Extract pure facts from text. Reuses event_detector + event_enricher.

    Returns Event dict with:
        id, event_type, time, source,
        actors, action, target, recipients,
        confidence, raw
    """
    import sys
    sys.path.insert(0, str(TOOLS_DIR))

    event = _empty_event(text)

    try:
        from memory.event_detector import detect
        events = detect(text, current_user=current_user)
        if events:
            raw_evt = events[0]
            event["id"] = raw_evt.get("id", "")
            event["time"] = raw_evt.get("time", {})
            event["actors"] = _build_actors(raw_evt)
            event["target"] = raw_evt.get("target", "") or raw_evt.get("participants", [])
            event["confidence"] = raw_evt.get("confidence", 0)
            event["event_type"] = _infer_event_type(text, raw_evt)
        else:
            event["event_type"] = _infer_event_type(text, {"entities": [], "title": ""})
    except Exception:
        pass

    # For feedback without detect output: populate actors from entity_index
    if event["event_type"] == "feedback" and not event["actors"]:
        event["actors"] = _build_actors_from_text(text)

    return event


def _empty_event(text: str) -> dict:
    return {
        "id": "",
        "event_type": "unknown",
        "time": {"deadline": ""},
        "source": "钉钉",
        "actors": [],
        "action": {"type": "unknown", "summary": ""},
        "target": "",
        "recipients": [],
        "confidence": 0.0,
        "raw": text[:500],
    }


def _build_actors_from_text(text: str) -> list:
    actors = []
    for e in find_entities_in_text(text):
        actors.append({"name": e["name"], "role": e["role"], "position": "entity"})
    return actors


def _build_actors(raw_evt: dict) -> list:
    actors = []
    requester = raw_evt.get("requester", "")
    if requester:
        actors.append({"name": requester, "role": get_role(requester), "position": "requester"})
    executor = raw_evt.get("executor", "")
    if executor and executor != requester:
        actors.append({"name": executor, "role": get_role(executor), "position": "executor"})
    for e in raw_evt.get("entities", []):
        name = e.get("name", "") if isinstance(e, dict) else str(e)
        role = e.get("role", "") if isinstance(e, dict) else ""
        if name and name not in {a["name"] for a in actors}:
            actors.append({"name": name, "role": role, "position": "entity"})
    return actors


def _infer_event_type(text: str, raw_evt: dict) -> str:
    title = raw_evt.get("title", "")
    entities = raw_evt.get("entities", [])

    # Instruction / notification take priority over feedback
    if any(kw in title for kw in ["通知", "要求", "安排", "督促"]):
        return "instruction"
    if any(kw in title for kw in ["培训", "学习", "会议"]):
        return "notification"
    if any(kw in title for kw in ["巡检", "检查", "整改", "排查"]):
        return "inspection"
    if any(kw in title for kw in ["汇报", "总结"]):
        return "report"
    if any(kw in title for kw in ["预警", "暴雨", "火灾", "漏水", "应急"]):
        return "incident"

    # Feedback: short message + known entity + completion keywords
    feedback_kw = any(kw in text for kw in ["完成", "好了", "做完", "已做", "做完了", "搞定"])
    if feedback_kw and len(text) < 30:
        has_person = bool(entities) or has_known_entity(text)
        if has_person:
            return "feedback"

    return "unknown"
