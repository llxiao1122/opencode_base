"""
event_context.py — 事件上下文构建（handle_D/E 共用）
流程: entity_resolver → search_events → build_event_context → LLM
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def get_related_event_context(user_input, limit=3, max_items=5):
    from routing.entity_resolver import resolve_entities
    from memory.event_search import search_events, build_event_context

    entities = resolve_entities(user_input)
    names = [e["name"] for e in entities.get("entities", []) if e.get("name")]
    if not names:
        return ""

    events = search_events(status=["active", "detected"], limit=limit)
    contexts = []
    for ev in events:
        ev_owners = ev.get("owners", [])
        if not any(name in ev_owners for name in names):
            continue
        ctx = build_event_context(ev["id"], max_items=max_items)
        if ctx:
            contexts.append(ctx)

    if not contexts:
        return ""

    return ("\n当前事件上下文:\n" + json.dumps(contexts, ensure_ascii=False, indent=2)
            + "\n\n请注意：\n"
            + "以上内容为内部事件数据。\n"
            + "回答用户时：\n"
            + "1. 不展示JSON\n"
            + "2. 转换为自然语言\n"
            + "3. 保留时间、责任人、任务、约束、汇报要求\n"
            + "4. 使用企业工作汇报格式")
