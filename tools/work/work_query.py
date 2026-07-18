"""
work_query.py — 个人工作视图查询
合并 tasks.md（固定周期台账）+ events/（临时动态事件）
"""

import re
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TASKS_FILE = ROOT / "memory" / "tasks.md"
PROFILE_FILE = ROOT / "state" / "user_profile.md"
sys.path.insert(0, str(ROOT / "tools"))

TEAM_MEMBERS = {
    "铁炉西工班": ["李林骁", "陈红洁", "杨梦卓", "谭继衡", "苗笑天", "张志斌"],
}


def _resolve_person(user_input):
    from routing.entity_resolver import resolve_entities

    entities = resolve_entities(user_input)
    names = [e["name"] for e in entities.get("entities", []) if e.get("name")]
    if names:
        return names[0]

    if PROFILE_FILE.exists():
        content = PROFILE_FILE.read_text(encoding="utf-8")
        m = re.search(r"name:\s*(.+)", content)
        if m:
            return m.group(1).strip()
    return None


def _get_team(person):
    for team, members in TEAM_MEMBERS.items():
        if person in members:
            return team
    return None


def _parse_tasks_for_person(person, date=None):
    if not TASKS_FILE.exists():
        return []

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    team = _get_team(person)
    routine = []
    seen = set()

    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"- \[[ x]\]\s*(\d{4}-\d{2}-\d{2}):\s*(.+)", line)
            if not m:
                continue
            task_date, task_text = m.group(1), m.group(2).strip()

            person_match = any(name in task_text for name in [person] if person)
            team_match = team and any(
                keyword in task_text
                for keyword in ["工班", "班组", "库区", "巡检", "台账", "检查", "培训", "演练"]
            )

            if not person_match and not team_match:
                continue

            if task_date < date:
                continue

            key = f"{task_date}:{task_text}"
            if key in seen:
                continue
            seen.add(key)
            routine.append({"date": task_date, "task": task_text})

    return routine


def _search_events_for_person(person):
    from memory.event_search import search_events, build_event_context

    events = search_events(status=["active", "detected"], limit=10)
    team = _get_team(person)
    matched = []

    generic_executors = {"各工班长", "各工班", "全体人员", "各库区"}

    for ev in events:
        ctx = build_event_context(ev["id"])
        if not ctx:
            continue

        people = ctx.get("people", {})
        if isinstance(people, dict):
            executors = people.get("executors", [])
        else:
            executors = []
        participants = ctx.get("participants", executors)

        if person in people.get("owner", []):
            matched.append(ctx)
            continue

        if person in participants or person in executors:
            matched.append(ctx)
            continue

        if team and any(
            t in p or p in t for t in [team] for p in participants
        ):
            matched.append(ctx)
            continue

        if generic_executors & set(participants):
            if team is not None:
                matched.append(ctx)
                continue

    return matched


def get_my_tasks(user_input, date=None):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    person = _resolve_person(user_input)
    if not person:
        return {"person": None, "error": "无法识别查询对象", "routine": [], "events": [], "responsibility": {}}

    routine = _parse_tasks_for_person(person, date)
    events = _search_events_for_person(person)

    from work.responsibility import resolve as classify

    responsibility = {"direct_task": [], "role_task": [], "team_attention": []}
    for ev in events:
        classified = classify(ev)
        for level in ["direct_task", "role_task", "team_attention"]:
            if classified.get(level):
                responsibility[level].extend(classified[level])

    return {
        "person": person,
        "team": _get_team(person),
        "date": date,
        "routine": routine,
        "responsibility": responsibility,
    }
