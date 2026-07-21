"""
context_builder.py — 组装 LLM 上下文 — DEPRECATED: 无调用方
输入 work_query 结果 → 输出三层结构化提示
"""

import json
from datetime import datetime


MAX_DIRECT = 5
MAX_ROLE = 5
MAX_TEAM = 5
MAX_CONTEXT_CHARS = 8000


def _truncate_event_item(item):
    if not isinstance(item, dict):
        return item
    ev = item.get("event", "")[:80]
    why = (item.get("why", "") or "")[:100]
    note = (item.get("note", "") or "")[:100]
    return {"event": ev, "why": why, "note": note,
            "deadline": item.get("deadline", ""),
            "report_to": item.get("report_to", [])[:3]}


def _section_text(label, items, empty_text="暂无"):
    if not items:
        return f"{label}\n{empty_text}"
    lines = [f"{label}"]
    for i, item in enumerate(items, 1):
        item = _truncate_event_item(item)
        event = item.get("event", "")
        deadline = item.get("deadline", "")
        why = item.get("why", "")
        note = item.get("note", "")
        report_to = item.get("report_to", [])
        parts = [event]
        if deadline:
            parts.append(f"截止{deadline}")
        if why:
            parts.append(f"({why})")
        if report_to:
            parts.append(f"→汇报对象:{','.join(report_to)}")
        if note:
            parts.append(f"({note})")
        lines.append(f"  {i}. {' '.join(parts)}")
    return "\n".join(lines)


def build_work_context(query_result):
    person = query_result.get("person", "未知")
    team = query_result.get("team", "")
    date_str = query_result.get("date", datetime.now().strftime("%Y-%m-%d"))
    routine = query_result.get("routine", [])
    responsibility = query_result.get("responsibility", {})

    direct = responsibility.get("direct_task", [])[:MAX_DIRECT]
    role = responsibility.get("role_task", [])[:MAX_ROLE]
    attention = responsibility.get("team_attention", [])[:MAX_TEAM]

    if not routine and not direct and not role and not attention:
        return f"\n当前用户: {person}\n暂无本周安排。"

    lines = [f"### 个人工作视图: {person}({team}) {date_str}", ""]

    if routine:
        lines.append("**固定工作:**")
        for r in routine[:8]:
            task_text = r.get("task", "")[:80]
            lines.append(f"  - {task_text}")
        lines.append("")

    lines.append(_section_text("**【直接任务】**", direct))
    lines.append("")
    lines.append(_section_text("**【岗位关注】**", role))
    lines.append("")
    lines.append(_section_text("**【团队事项】**", attention))
    lines.append("")

    return (
        "\n".join(lines)
        + "\n请将以上数据转换为自然语言工作汇报：\n"
        + "1. 先列出固定工作，再按【直接任务】→【岗位关注】→【团队事项】顺序输出\n"
        + "2. 每个类别内用数字编号，格式: 1. 事件标题 (原因说明)\n"
        + "3. 【直接任务】是你必须亲自完成的\n"
        + "4. 【岗位关注】是你岗位职责范围内需协调安排的，不是亲自执行\n"
        + "5. 【团队事项】是你的团队受影响的，你只需关注，不是你的个人任务\n"
        + "6. 保留时间节点、约束条件、汇报对象\n"
        + "7. 如果某类别为空，输出'暂无'\n"
        + "8. 结尾加一句：当前重点不是由你负责全部事项，而是做好本工班范围内协调和执行\n"
        + "9. 格式简洁，每项一行，不用分段"
    )
