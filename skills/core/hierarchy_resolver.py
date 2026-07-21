"""
hierarchy_resolver.py — Organization hierarchy resolver (Phase 1.7.8-C)

Loads entity_index.json to determine role relationships,
outputs context text for LLM prompt injection.

Goal: tell LLM who is superior/colleague/subordinate so it doesn't
say "安排王亮" when 王亮 is a safety manager giving directives.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skills.shared import get_role as _shared_get_role

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX_PATH = ROOT / "state" / "entity_index.json"


def _load_leaders_map() -> dict:
    """Load name → leaders.category dict from entity_index.json."""
    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        result = {}
        for e in data.get("confirmed_entities", []):
            leaders = e.get("leaders")
            if leaders and "category" in leaders:
                result[e["name"]] = leaders["category"]
        return result
    except Exception:
        return {}


_LEADER_CACHE = {}


def _parse_leaders_category(name: str) -> str:
    """Lookup leadership category from cached entity_index leaders map."""
    if not _LEADER_CACHE:
        _LEADER_CACHE.update(_load_leaders_map())
    return _LEADER_CACHE.get(name, "unknown")


def _get_role(name: str) -> str:
    return _shared_get_role(name)


def resolve(event, user):
    """Given event and current user, return org hierarchy context.

    Args:
        event: event dict with requester/executor/target (or None)
        user: current user dict with name/role/team (or None)

    Returns:
        {"text": "层级关系文本", "chain": ["安全管理岗", "工班长"]}
    """
    result = {"text": "", "chain": []}
    if not event or not user:
        return result

    requester = event.get("requester", "") if isinstance(event, dict) else ""
    executor_name = user.get("name", "")
    executor_role = user.get("role", "")
    executor_team = user.get("team", "")

    lines = []

    if executor_name:
        lines.append(f"{executor_name}: {executor_role}（{executor_team}工班，当前用户）")

    if requester and requester != executor_name:
        role = _get_role(requester) or ""
        category = _parse_leaders_category(requester)
        relation_map = {
            "direct": f"来自直接上级 {requester}（{role}）的指令。你负责执行和汇报。",
            "upper": f"来自上级管理层 {requester}（{role}）的指令。你负责落实。",
            "colleague": f"来自 {requester}（{role}）的工作指令。你是执行方——请直接回答你如何落实，不需要教{requester}怎么做。",
            "unknown": f"来自 {requester}" + (f"（{role}）" if role else "") + "的消息。",
        }
        lines.append(relation_map.get(category, relation_map["unknown"]))
        result["chain"] = [_get_role(requester) or "未知", executor_role or "未知"]

    result["text"] = "\n".join(lines)
    return result


def inject_org_context(event, user):
    """Return a prompt-ready org context string."""
    org = resolve(event, user)
    if not org.get("text"):
        return ""
    return f"【组织关系】\n{org['text']}"
