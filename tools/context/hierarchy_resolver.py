"""
hierarchy_resolver.py — Organization hierarchy resolver (Phase 1.7.8-C)

Loads org.md, leaders.md, entity_index.json to determine role relationships,
outputs context text for LLM prompt injection.

Goal: tell LLM who is superior/colleague/subordinate so it doesn't
say "安排王亮" when 王亮 is a safety manager giving directives.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LEADERS_PATH = ROOT / "state" / "leaders.md"
ORG_PATH = ROOT / "state" / "org.md"
ENTITY_INDEX_PATH = ROOT / "state" / "entity_index.json"

_entity_cache: dict = {}
_loaded = False


def _load():
    global _entity_cache, _loaded
    if _loaded:
        return
    try:
        raw = ENTITY_INDEX_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        for e in data.get("confirmed_entities", []):
            _entity_cache[e["name"]] = {"role": e.get("role", ""), "source": e.get("source", "")}
        for e in data.get("pending_entities", []):
            _entity_cache[e["name"]] = {"role": e.get("role", ""), "source": e.get("source", "")}
    except Exception:
        pass
    _loaded = True


def _parse_leaders_category(name: str) -> str:
    """Determine leadership category from leaders.md: direct/upper/colleague/unknown"""
    if not LEADERS_PATH.exists():
        return "unknown"
    try:
        text = LEADERS_PATH.read_text(encoding="utf-8")
        for section in ("## DIRECT", "## UPPER", "## COLLEAGUE"):
            if section in text:
                start = text.index(section)
                end = text.find("##", start + 3)
                if end == -1:
                    end = len(text)
                block = text[start:end]
                if name in block:
                    return section.lower().split("## ")[-1].strip()
    except Exception:
        pass
    return "unknown"


def _get_role(name: str) -> str:
    _load()
    return _entity_cache.get(name, {}).get("role", "")


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
