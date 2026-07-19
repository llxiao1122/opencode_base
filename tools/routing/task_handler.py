"""
routing/task_handler.py — Task query handler (Phase 13.1).

Queries: today, tomorrow, this week.
Data source: data/tasks.json (dynamic tasks only).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TASKS_PATH = ROOT_DIR / "data" / "tasks.json"

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def handle(user_input, ctx):
    user_name = ctx.get("user", {}).get("name", "未知")
    today = datetime.now().date()

    scope = _detect_scope(user_input)
    if scope == "today":
        date_range = (today, today)
        label = "今天"
    elif scope == "tomorrow":
        date_range = (today + timedelta(days=1), today + timedelta(days=1))
        label = "明天"
    elif scope == "week":
        days_ahead = 7 - today.weekday()
        week_end = today + timedelta(days=days_ahead - 1)
        date_range = (today, week_end)
        label = "本周"
    else:
        date_range = (today, today)
        label = "今天"

    tasks = _load_tasks()
    matched = _filter_tasks(tasks, date_range)

    daily_work = _get_daily_work(user_input)

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于任务数据和固定工作，整理成简洁的待办清单。只陈述事实。"
    )

    task_lines = []
    for i, t in enumerate(matched):
        deadline = t.get("deadline", "")
        dl_str = f" ⏰ 截止: {deadline}" if deadline else ""
        exec_names = [e["name"] for e in t.get("executors", [])]
        exec_str = f" — 负责人: {', '.join(exec_names)}" if exec_names else ""
        status = "进行中"
        if t.get("status") == "completed":
            status = "✅ 已完成"
        task_lines.append(f"{i+1}. {status} — {t['action'][:60]}{exec_str}{dl_str}")

        subtasks = t.get("subtasks", [])
        for st in subtasks[:4]:
            mark = "✅" if st.get("done") else "○"
            task_lines.append(f"   {mark} [{st.get('assignee', '')}] {st['action'][:50]}")

    task_text = "\n".join(task_lines)
    total = len(matched)

    prompt = (
        f"当前用户 {user_name} 查询了{label}的工作安排。\n"
        f"日期: {today.strftime('%Y-%m-%d')} {WEEKDAY_ZH[today.weekday()]}\n"
    )
    if daily_work:
        prompt += f"\n{label}的固定工作:\n{daily_work}\n"
    if task_text:
        prompt += f"\n{label}的 {total} 项动态任务:\n\n{task_text}\n"
    if not daily_work and not task_text:
        week_day = WEEKDAY_ZH[today.weekday()]
        return f"[Cipher:task]\n{label} {today.strftime('%Y-%m-%d')} {week_day} 暂未找到进行中的任务。"

    prompt += "\n请整理成简洁的工作安排清单。禁止编造。"

    from routing.entry import _cached_llm
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=60, max_tokens=600, temperature=0.3)
    if not answer:
        answer = _format_fallback(label, today, week_day=daily_work, tasks=task_lines)
    return f"[Cipher:task]\n{answer}"


def _detect_scope(text):
    if "本周" in text or "这周" in text or "这星期" in text:
        return "week"
    if "明天" in text or "明日" in text:
        return "tomorrow"
    return "today"


def _load_tasks():
    if not TASKS_PATH.exists():
        return []
    try:
        return json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _filter_tasks(tasks, date_range):
    start, end = date_range
    active = []
    for t in tasks:
        if t.get("status") == "completed":
            continue
        active.append(t)
    return active


def _format_fallback(label, today, week_day="", tasks=None):
    lines = []
    if week_day:
        lines.append(week_day)
    if tasks:
        lines.append(f"\n{label} 进行中的任务 ({len(tasks)} 项)")
    return "\n".join(lines) if lines else f"{label} 暂未找到进行中的任务。"


def _get_daily_work(user_input):
    """Parse Knowledge/00-日常工作指引.md for today/tomorrow/week routines."""
    md_path = ROOT_DIR / "Knowledge" / "00-日常工作指引.md"
    if not md_path.exists():
        return ""
    md = md_path.read_text(encoding="utf-8")

    now = datetime.now()
    if "明天" in user_input:
        target = now + timedelta(days=1)
        label = f"明天（{target.strftime('%Y-%m-%d')}）"
    elif "今天" in user_input:
        target = now
        label = f"今天（{target.strftime('%Y-%m-%d')}）"
    else:
        target = now
        label = f"今日工作（{target.strftime('%Y-%m-%d')}）"

    weekday_zh = ["周一","周二","周三","周四","周五","周六","周日"][target.weekday()]
    label += f" {weekday_zh}"

    lines_out = []

    lines_out.append("【每日固定工作】")
    daily = _parse_table_section(md, "## 每日")
    for row in daily:
        lines_out.append(f"  {row.get('#', '')}. {row.get('工作项', '')} — {row.get('负责人', '')}")

    if target.weekday() == 4:
        lines_out.append("")
        lines_out.append("【每周五固定工作】")
        weekly = _parse_table_section(md, "## 每周五")
        for row in weekly:
            lines_out.append(f"  {row.get('#', '')}. {row.get('工作项', '')} — {row.get('负责人', '')}")

    day = target.day
    lines_out.append("")
    lines_out.append(f"【本月{day}日固定工作】")
    monthly = _parse_monthly_table(md, "## 每月固定日期")
    matched = [r for r in monthly if r.get("日期") == f"{day}日"]
    if matched:
        for row in matched:
            lines_out.append(f"  {row.get('#', '')}. {row.get('工作项', '')} — {row.get('负责人', '')}")
    else:
        lines_out.append("  （无）")

    yr = target.year
    mon = target.month
    for line in md.split("\n"):
        if "应急演练" in line and "月份" in line:
            continue
        if f"{mon}月" in line and "应急演练" in line:
            exercise = line.strip().lstrip("|").split("|")
            if len(exercise) >= 3:
                lines_out.append("")
                lines_out.append(f"【本月演练】{exercise[1].strip()} — {exercise[2].strip()}")

    return "\n".join(lines_out)


def _parse_table_section(md, section_header):
    """Parse a markdown table section into list of dicts."""
    import re as _re
    pos = md.find(section_header)
    if pos < 0:
        return []
    section = md[pos:].split("\n## ")[0]
    lines = section.split("\n")
    headers = None
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if headers is None:
            headers = cells
        else:
            if len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
    return rows


def _parse_monthly_table(md, section_header):
    """Parse monthly table (day-based) into list of dicts."""
    import re as _re
    pos = md.find(section_header)
    if pos < 0:
        return []
    section = md[pos:].split("\n## ")[0]
    lines = section.split("\n")
    headers = None
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if headers is None:
            headers = cells
        else:
            if len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
    return rows
