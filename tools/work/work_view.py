"""
work_view.py — Work View Formatter (Phase 1.7.6)

Receives full get_my_tasks() result (including events), produces:
  1. build_work_view(result) → structured JSON (test/trace/API)
  2. render_work_view(view_json) → fixed-format Chinese text (LLM feed)
"""


def build_work_view(query_result):
    person = query_result.get("person", "未知")
    team = query_result.get("team", "")
    date_str = query_result.get("date", "")

    routine = query_result.get("routine", [])
    responsibility = query_result.get("responsibility", {})
    events = query_result.get("events", [])

    # Index events by title for detail lookup
    event_map = {}
    for ev in events:
        title = ev.get("title", "")
        if title:
            event_map[title] = ev

    direct = responsibility.get("direct_task", [])
    role = responsibility.get("role_task", [])
    team_attn = responsibility.get("team_attention", [])

    # Build each category with event details where available
    direct_tasks = []
    seen_direct = set()
    for item in direct[:5]:
        ev_title = item.get("event", "")
        key = ev_title[:80]
        if key in seen_direct:
            continue
        seen_direct.add(key)
        ev = event_map.get(ev_title, {})
        entry = {
            "event": ev_title[:80],
            "deadline": item.get("deadline", "") or ev.get("time", {}).get("deadline", ""),
            "actions": _extract_actions(ev),
            "constraints": ev.get("constraints", [])[:3],
            "reason": item.get("why", ""),
        }
        direct_tasks.append(entry)

    coordinate_tasks = []
    seen_coord = set()
    for item in role[:5]:
        ev_title = item.get("event", "")
        key = ev_title[:80]
        if key in seen_coord:
            continue
        seen_coord.add(key)
        ev = event_map.get(ev_title, {})
        contact = _extract_primary_contact(ev)
        entry = {
            "event": ev_title[:80],
            "deadline": item.get("deadline", "") or ev.get("time", {}).get("deadline", ""),
            "actions": _extract_actions(ev),
            "constraints": ev.get("constraints", [])[:3],
            "contact": contact,
            "report_to": item.get("report_to", [])[:3],
            "reason": item.get("why", ""),
            "relation": "role_task",
        }
        coordinate_tasks.append(entry)

    attention_items = []
    seen_attn = set()
    for item in team_attn[:5]:
        ev_title = item.get("event", "")
        key = ev_title[:80]
        if key in seen_attn:
            continue
        seen_attn.add(key)
        ev = event_map.get(ev_title, {})
        entry = {
            "event": ev_title[:80],
            "deadline": item.get("deadline", "") or ev.get("time", {}).get("deadline", ""),
            "actions": _extract_actions(ev),
            "constraints": ev.get("constraints", [])[:3],
            "note": item.get("note", ""),
            "report_to": item.get("report_to", [])[:3],
            "from": "event" if ev else "responsibility",
        }
        attention_items.append(entry)

    # Also capture unique constraints from all events not already in tasks
    all_constraints = {}
    for ev in events:
        for c in ev.get("constraints", []):
            all_constraints[c] = ev.get("title", "")
    for entry in direct_tasks + coordinate_tasks:
        for c in entry.get("constraints", []):
            all_constraints.pop(c, None)

    routine_tasks = [r.get("task", "")[:80] for r in routine[:8]]

    # Collect contacts from all events — resolve roles from entity_index
    contacts = {}
    for ev in events:
        for name in ev.get("people", {}).get("owner", []):
            if name and name not in contacts:
                contacts[name] = {"name": name, "role": "", "from": "event_owner"}
        for rt in ev.get("report_to", []):
            if rt and rt not in contacts:
                contacts[rt] = {"name": rt, "role": "", "from": "report_to"}

    return {
        "person": person,
        "team": team,
        "date": date_str,
        "direct_tasks": direct_tasks,
        "coordinate_tasks": coordinate_tasks,
        "attention_items": attention_items,
        "routine_tasks": routine_tasks,
        "contacts": list(contacts.values()),
    }


def _extract_actions(ev):
    if not ev:
        return []
    ai = ev.get("ai_content", [])
    if ai:
        actions = []
        for section in ai:
            for a in section.get("actions", []):
                text = a.get("text", "")
                if text and text not in actions:
                    actions.append(text)
        return actions[:5]
    tasks = ev.get("tasks", [])
    actions = []
    for t in tasks:
        for a in t.get("actions", []):
            if a not in actions:
                actions.append(a)
    return actions[:5]


def _extract_primary_contact(ev):
    if not ev:
        return None
    people = ev.get("people", {})
    owners = people.get("owner", [])
    if owners:
        return {"name": owners[0], "role": "通知人"}
    return None


def render_work_view(view):
    lines = []
    person = view.get("person", "")
    date_str = view.get("date", "")

    lines.append(f"{person}工作安排")
    if date_str:
        from datetime import datetime
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            wd = ["周一","周二","周三","周四","周五","周六","周日"][dt.weekday()]
            lines.append(f"日期: {date_str} {wd}")
        except ValueError:
            lines.append(f"日期: {date_str}")
    lines.append("")

    # 一、本人需要执行
    lines.append("一、本人需要执行")
    direct = view.get("direct_tasks", [])
    if not direct:
        lines.append("暂无")
    else:
        for i, t in enumerate(direct, 1):
            lines.append(f"{i}. {t.get('event','')}")
            if t.get("deadline"):
                lines.append(f"   截止: {t['deadline']}")
            for a in t.get("actions", []):
                lines.append(f"   - {a}")
    lines.append("")

    # 二、需要协调安排
    lines.append("二、需要协调安排")
    coord = view.get("coordinate_tasks", [])
    if not coord:
        lines.append("暂无")
    else:
        for i, t in enumerate(coord, 1):
            lines.append(f"{i}. {t.get('event','')}")
            if t.get("contact"):
                c = t["contact"]
                lines.append(f"   来源: {c.get('name','')}通知")
            if t.get("deadline"):
                lines.append(f"   截止: {t['deadline']}")
            for a in t.get("actions", []):
                lines.append(f"   - {a}")
            for c in t.get("constraints", []):
                lines.append(f"   ⚠ {c}")
            if t.get("report_to"):
                lines.append(f"   汇报对象: {', '.join(t['report_to'])}")
    lines.append("")

    # 三、需要关注
    lines.append("三、需要关注")
    attn = view.get("attention_items", [])
    if not attn:
        lines.append("暂无")
    else:
        for a in attn:
            ev_title = a.get("event", "")
            note = a.get("note", "")
            if ev_title:
                lines.append(f"· {ev_title[:60]}")
            if note:
                lines.append(f"  {note}")
            if a.get("deadline"):
                lines.append(f"  截止: {a['deadline']}")
            for act in a.get("actions", []):
                lines.append(f"   - {act}")
            for c in a.get("constraints", []):
                lines.append(f"   ⚠ {c}")
            if a.get("report_to"):
                lines.append(f"  汇报: {', '.join(a['report_to'])}")
    lines.append("")

    # 四、固定工作
    lines.append("四、固定工作")
    routine = view.get("routine_tasks", [])
    if not routine:
        lines.append("暂无")
    else:
        for r in routine:
            lines.append(f"· {r}")
    lines.append("")

    # 五、涉及人员（如有）
    contacts = view.get("contacts", [])
    if contacts:
        lines.append("五、涉及人员")
        for c in contacts[:5]:
            name = c.get("name", "")
            role = c.get("role", "")
            if role:
                lines.append(f"· {name}（{role}）")
            else:
                lines.append(f"· {name}")
        lines.append("")

    return "\n".join(lines)
