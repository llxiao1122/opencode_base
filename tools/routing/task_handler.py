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

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于任务数据，整理成简洁的待办清单。只陈述事实。"
    )

    if not matched:
        week_day = WEEKDAY_ZH[today.weekday()]
        return f"[Cipher:task]\n{label} {today.strftime('%Y-%m-%d')} {week_day} 暂未找到进行中的任务。"

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
        f"\n{label}的 {total} 项任务:\n\n{task_text}\n\n"
        f"请整理成简洁的{label}工作安排，按\"待办 / 进行中 / 关注\"分组。禁止编造。"
    )

    from routing.entry import _cached_llm
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=60, max_tokens=400, temperature=0.3)
    if not answer:
        answer = f"{label} 进行中的任务 ({total} 项)"
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
    result = []
    for t in tasks:
        if t.get("status") == "completed":
            continue
        deadline = t.get("deadline", "")
        if deadline:
            try:
                dl = datetime.strptime(deadline, "%Y-%m-%d").date()
                if not (start <= dl <= end):
                    continue
            except ValueError:
                pass
        created = t.get("created_at", "")
        if created:
            try:
                ct = datetime.strptime(created[:10], "%Y-%m-%d").date()
                if not (start <= ct <= end):
                    continue
            except ValueError:
                pass
        result.append(t)
    return result
