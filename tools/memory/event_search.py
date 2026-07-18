"""
event_search.py — Event Query Engine
Index-first, details-lazy. No directory scanning.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_FILE = ROOT / "memory" / "events" / "index.json"
EVENTS_DIR = ROOT / "memory" / "events"


def _load_index():
    if not INDEX_FILE.exists():
        return {"events": []}
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_detail(event_id):
    index = _load_index()
    for e in index.get("events", []):
        if e["id"] == event_id:
            status = e.get("status", "active")
            detail_path = EVENTS_DIR / status / f"{event_id}.json"
            if detail_path.exists():
                with open(detail_path, "r", encoding="utf-8") as f:
                    return json.load(f)
    return None


def _normalize(s):
    return s.replace(" ", "").replace("　", "").lower()


def _entity_overlap(owners, entity_name):
    target = _normalize(entity_name)
    for owner in owners:
        if target in _normalize(owner) or _normalize(owner) in target:
            return True
    return False


def _generate_summary(detail):
    items = detail.get("items", [])
    if items:
        parts = []
        for item in items[:2]:
            text = item.get("text", "")
            if len(text) > 20:
                text = text[:20] + "..."
            parts.append(text)
        summary = "；".join(parts) if parts else detail.get("title", "")
        return summary
    title = detail.get("title", "")
    return title if len(title) <= 40 else title[:37] + "..."


def search_events(
    entity=None,
    status=None,
    keyword=None,
    deadline_before=None,
    deadline_after=None,
    limit=20,
):
    index = _load_index()
    events = index.get("events", [])

    if status:
        if isinstance(status, str):
            status = [status]
        events = [e for e in events if e.get("status") in status]

    if entity:
        matched = []
        for e in events:
            owners = e.get("owners", [])
            if _entity_overlap(owners, entity):
                matched.append(e)
                continue
            detail = _load_detail(e["id"])
            if detail and _entity_overlap(
                [en.get("name", "") for en in detail.get("entities", [])], entity
            ):
                matched.append(e)
        events = matched

    if deadline_before:
        events = [
            e
            for e in events
            if e.get("deadline", "") and e["deadline"] <= deadline_before
        ]
    if deadline_after:
        events = [
            e
            for e in events
            if e.get("deadline", "") and e["deadline"] >= deadline_after
        ]

    if keyword:
        filtered = []
        for e in events:
            if keyword in e.get("title", ""):
                filtered.append(e)
                continue
            detail = _load_detail(e["id"])
            if detail:
                items_text = " ".join(
                    item.get("text", "") for item in detail.get("items", [])
                )
                if keyword in items_text:
                    filtered.append(e)
                    continue
        events = filtered

    events = sorted(
        events, key=lambda e: e.get("updated", ""), reverse=True
    )[:limit]

    return [
        {
            "id": e["id"],
            "title": e.get("title", ""),
            "status": e.get("status", ""),
            "owners": e.get("owners", []),
            "deadline": e.get("deadline", ""),
            "summary": _generate_summary(_load_detail(e["id"]) or e),
            "priority": _load_detail(e.get("id")) and _load_detail(e["id"]).get(
                "priority", "normal"
            ) or "normal",
        }
        for e in events
    ]


def _extract_people(detail):
    owner_names = []
    for e in detail.get("entities", []):
        if isinstance(e, dict):
            name = e.get("name", "")
            if name:
                owner_names.append(name)
        elif isinstance(e, str):
            if e:
                owner_names.append(e)
    for o in detail.get("owners", []):
        if o not in owner_names:
            owner_names.append(o)

    return {
        "owner": owner_names,
        "executors": detail.get("participants", []),
        "report_to": detail.get("report_to", []),
    }


def _is_constraint_like(item_text, constraints, evidence, item_required_actions):
    if item_required_actions:
        return False
    for c in constraints:
        if c in item_text:
            return True
    for e_item in evidence:
        for e_piece in re.split(r"[，。；；\n]", e_item):
            e_piece = e_piece.strip()
            if len(e_piece) >= 4 and e_piece in item_text:
                return True
    return False


def build_event_context(event_id, max_items=5):
    detail = _load_detail(event_id)
    if not detail:
        return None

    items = detail.get("items", [])[:max_items]
    constraints = detail.get("constraints", [])
    evidence = detail.get("evidence", [])

    if items:
        tasks = [
            {
                "content": item.get("text", ""),
                "actions": item.get("required_actions", []),
            }
            for item in items
            if item.get("text", "")
            and not _is_constraint_like(item["text"], constraints, evidence, item.get("required_actions", []))
        ]
    elif detail.get("required_actions"):
        tasks = [{
            "content": detail.get("title", ""),
            "actions": detail.get("required_actions", []),
        }]
    else:
        tasks = []

    return {
        "title": detail.get("title", ""),
        "people": _extract_people(detail),
        "time": {
            "start": detail.get("time", {}).get("start", ""),
            "deadline": detail.get("time", {}).get("deadline", ""),
        },
        "tasks": tasks,
        "constraints": constraints,
        "evidence": evidence,
        "report_to": detail.get("report_to", []),
        "source": detail.get("source", {}).get("type", "dingtalk"),
    }


def get_event_detail(event_id):
    return _load_detail(event_id)
