"""
profile/retriever.py — Profile context provider for AI consumption.

Computes person profiles in real-time from:
    data/tasks.json        → execution stats, patterns
    data/org_memory.json   → activity base counts (when available)
    state/entity_index.json → role

No pre-computation. No profiles.json. No LLM.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.shared import get_role

ROOT = Path(__file__).resolve().parent.parent.parent

TASK_PATH = ROOT / "data" / "tasks.json"
ORG_PATH = ROOT / "data" / "org_memory.json"

ALLOWED_PATTERN_TYPES = {"completion", "frequency", "event_role", "collaboration", "instruction_source"}
ACTION_KEYWORDS = [
    "消防", "安全", "防汛", "入库", "废旧", "巡检", "台账", "迎检",
    "考勤", "检查", "培训", "演练", "考试", "施工",
]

_cache_tasks = None
_cache_org = None


def _tasks():
    global _cache_tasks
    if _cache_tasks is None:
        if TASK_PATH.exists():
            try:
                _cache_tasks = json.loads(TASK_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                _cache_tasks = []
        else:
            _cache_tasks = []
    return _cache_tasks


def _org():
    global _cache_org
    if _cache_org is None:
        if ORG_PATH.exists():
            try:
                _cache_org = json.loads(ORG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                _cache_org = {}
        else:
            _cache_org = {}
    return _cache_org


def _person_tasks(name: str) -> list:
    """Tasks where this person appears as owner or executor."""
    result = []
    for t in _tasks():
        if t.get("owner", {}).get("name") == name:
            result.append(t)
            continue
        for ex in t.get("executors", []):
            if ex.get("name") == name:
                result.append(t)
                break
    return result


def _executor_tasks(name: str) -> list:
    """Tasks where this person is in the executors list."""
    result = []
    for t in _tasks():
        for ex in t.get("executors", []):
            if ex.get("name") == name:
                result.append(t)
                break
    return result


def _load_events() -> list:
    """Load all events from log.jsonl."""
    EVENT_LOG_PATH = ROOT / "memory" / "events" / "log.jsonl"
    if not EVENT_LOG_PATH.exists():
        return []
    events = []
    with open(EVENT_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except (json.JSONDecodeError, KeyError):
                continue
    return events


# ── trends ───────────────────────────────────────────────────────────


def _build_trends(name: str, tasks: list) -> dict:
    """Compute time-based trends from task data.

    Returns empty structures when data is insufficient.
    """
    trending = {}

    # ── monthly task trends ──
    month_data = defaultdict(lambda: {"tasks": 0, "completed": 0})
    for t in tasks:
        created = t.get("created_at", "")[:7]  # YYYY-MM
        if not created:
            continue
        month_data[created]["tasks"] += 1
        is_done = any(
            ex["name"] == name and ex.get("status") == "done"
            for ex in t.get("executors", [])
        )
        if is_done:
            month_data[created]["completed"] += 1

    monthly = []
    months = sorted(month_data)
    for m in months:
        d = month_data[m]
        rate = round(d["completed"] / d["tasks"], 2) if d["tasks"] > 0 else 0.0
        monthly.append({
            "month": m,
            "tasks": d["tasks"],
            "completed": d["completed"],
            "rate": rate,
        })

    if len(months) >= 2:
        prev_rate = monthly[-2]["rate"]
        curr_rate = monthly[-1]["rate"]
        if curr_rate > prev_rate:
            monthly[-1]["direction"] = "up"
        elif curr_rate < prev_rate:
            monthly[-1]["direction"] = "down"
        else:
            monthly[-1]["direction"] = "flat"

    trending["monthly"] = monthly

    # ── task type shift ──
    type_by_month = defaultdict(lambda: defaultdict(int))
    for t in tasks:
        created = t.get("created_at", "")[:7]
        if not created:
            continue
        action = t.get("action", "")
        for kw in ACTION_KEYWORDS:
            if kw in action:
                type_by_month[kw][created] += 1

    task_type_shift = {}
    for kw in sorted(type_by_month):
        mdata = type_by_month[kw]
        total = sum(mdata.values())
        task_type_shift[kw] = {
            "months": dict(sorted(mdata.items())),
            "total": total,
        }
    trending["task_type_shift"] = task_type_shift

    # ── completion cycle (avg days from created_at → completed_at) ──
    cycles = []
    for t in tasks:
        if t.get("status") != "completed":
            continue
        created = t.get("created_at", "")[:10]
        completed = t.get("completed_at", "")
        if not created or not completed:
            continue
        completed = completed[:10]
        try:
            from datetime import date
            d1 = date.fromisoformat(created)
            d2 = date.fromisoformat(completed)
            cycles.append((d2 - d1).days)
        except (ValueError, TypeError):
            continue

    if cycles:
        trending["completion_cycle"] = {
            "avg_days": round(sum(cycles) / len(cycles), 1),
            "min_days": min(cycles),
            "max_days": max(cycles),
            "samples": len(cycles),
        }
    else:
        trending["completion_cycle"] = {
            "avg_days": None,
            "samples": 0,
            "note": "暂无已完成任务，无法计算周期",
        }

    return trending


# ── public API ────────────────────────────────────────────────────────


def get_person_context(name: str) -> dict:
    """Get a single person's profile context computed in real-time.

    Returns {"name": name, "error": "no_data"} if no tasks/org data found.
    """
    org_people = _org().get("people", {})
    org_person = org_people.get(name, {})
    entity_role = get_role(name)
    tasks = _person_tasks(name)
    exec_tasks = _executor_tasks(name)
    events = _load_events()

    if not tasks and not org_person:
        return {"name": name, "error": "no_data"}

    role_current = entity_role or org_person.get("role", "")

    # ── activity ──
    activity = {
        "events_total": org_person.get("appears_in_events", 0),
        "tasks_total": len(tasks),
        "executor_count": org_person.get("as_executor", len(exec_tasks)),
        "requester_count": org_person.get("as_requester", 0),
    }

    # ── execution ──
    completed = 0
    pending = 0
    task_ids_done = []
    task_ids_pending = []
    for t in exec_tasks:
        for ex in t.get("executors", []):
            if ex["name"] != name:
                continue
            if ex.get("status") == "done":
                completed += 1
                task_ids_done.append(t["id"])
            else:
                pending += 1
                task_ids_pending.append(t["id"])

    total = completed + pending
    execution = {
        "completed": completed,
        "pending": pending,
        "completion_rate": round(completed / total, 2) if total > 0 else None,
        "task_ids_done": task_ids_done,
        "task_ids_pending": task_ids_pending,
    }

    # ── responsibility ──
    kw_counter = Counter()
    for t in tasks:
        action = t.get("action", "")
        for kw in ACTION_KEYWORDS:
            if kw in action:
                kw_counter[kw] += 1

    responsibility = {
        "common_tasks": [kw for kw, _ in kw_counter.most_common(5)],
        "event_types": org_person.get("event_types", {}),
    }

    # ── patterns ──
    patterns = []
    if exec_tasks:
        rate = completed / len(exec_tasks) if exec_tasks else 0
        patterns.append({
            "type": "completion",
            "fact": f"近{len(exec_tasks)}次任务完成{completed}次",
            "confidence": round(min(rate + 0.1, 0.95), 2),
            "source": {
                "type": "task_execution",
                "task_ids": [t["id"] for t in exec_tasks],
                "completed": completed,
                "total": len(exec_tasks),
            },
        })

    for kw, cnt in kw_counter.most_common(3):
        if cnt >= 1:
            kw_task_ids = [t["id"] for t in tasks if kw in t.get("action", "")]
            patterns.append({
                "type": "frequency",
                "fact": f"参与{kw}类任务{cnt}次",
                "confidence": round(min(0.7 + cnt * 0.03, 0.90), 2),
                "source": {
                    "type": "action_keyword",
                    "keyword": kw,
                    "task_ids": kw_task_ids,
                },
            })

    # ── instruction_source patterns (from events) ──
    source_counter = Counter()
    source_event_ids = defaultdict(list)
    for e in events:
        requester = ""
        for a in e.get("actors", []):
            if a.get("position") == "requester":
                requester = a.get("name", "")
                break
        if not requester or requester == name:
            continue
        for a in e.get("actors", []):
            if a.get("name") == name and a.get("position") in ("entity", "executor"):
                source_counter[requester] += 1
                source_event_ids[requester].append(e.get("id", ""))
        if name in str(e.get("target", "")):
            source_counter[requester] += 1
            source_event_ids[requester].append(e.get("id", ""))

    for src, cnt in source_counter.most_common(3):
        if cnt >= 1:
            patterns.append({
                "type": "instruction_source",
                "fact": f"主要接收{src}指令{cnt}次",
                "confidence": round(min(0.65 + cnt * 0.05, 0.88), 2),
                "source": {
                    "type": "event_instruction",
                    "requester": src,
                    "event_ids": source_event_ids[src],
                },
            })

    # ── relations ──
    collab = Counter()
    for t in tasks:
        exec_names = [ex["name"] for ex in t.get("executors", [])]
        owner_name = t.get("owner", {}).get("name", "")
        if name in exec_names or name == owner_name:
            for other in exec_names:
                if other != name:
                    collab[other] += 1
            if owner_name and owner_name != name:
                collab[owner_name] += 1
    relations = [{"person": p, "count": c} for p, c in collab.most_common(8)]

    patterns = [p for p in patterns if p["type"] in ALLOWED_PATTERN_TYPES]

    # ── trends ──
    trends = _build_trends(name, tasks)

    return {
        "name": name,
        "role": {
            "current": role_current,
            "source": "entity_index" if entity_role else ("org_memory" if role_current else ""),
        },
        "activity": activity,
        "execution": execution,
        "responsibility": responsibility,
        "patterns": patterns,
        "relations": relations,
        "trends": trends,
        "updated_at": _org().get("accumulated_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
    }


def search_profiles(names: list) -> dict:
    """Batch lookup multiple person profiles."""
    result = {}
    for name in names:
        result[name] = get_person_context(name)
    return {"profiles": result}


def format_context(name: str) -> str:
    """Generate LLM-injectable context text for a person."""
    ctx = get_person_context(name)
    if "error" in ctx:
        return ""

    lines = [f"## 人员：{name}\n"]

    role = ctx.get("role", {}).get("current", "")
    if role:
        lines.append(f"岗位：\n{role}\n")

    exec_data = ctx.get("execution", {})
    completed = exec_data.get("completed", 0)
    pending = exec_data.get("pending", 0)
    if completed or pending:
        lines.append("近期任务：")
        if completed:
            lines.append(f"- 完成 {completed} 次")
        if pending:
            lines.append(f"- 进行中 {pending} 次")

    resp = ctx.get("responsibility", {})
    common = resp.get("common_tasks", [])
    if common:
        lines.append(f"\n常见任务：")
        for t in common[:5]:
            lines.append(f"- {t}")

    trends = ctx.get("trends", {})
    monthly = trends.get("monthly", [])
    if monthly:
        lines.append("\n趋势：")
        for m in monthly:
            tag = ""
            direction = m.get("direction", "")
            if direction == "up":
                tag = "↑"
            elif direction == "down":
                tag = "↓"
            elif direction == "flat":
                tag = "→"
            lines.append(f"- {m['month']}: {m['tasks']}任务 完成{m['completed']}次(率{m['rate']:.0%}) {tag}".rstrip())
        cycle = trends.get("completion_cycle", {})
        if cycle.get("avg_days") is not None:
            lines.append(f"- 平均完成周期: {cycle['avg_days']}天 ({cycle['samples']}样本)")
        elif cycle.get("note"):
            lines.append(f"- {cycle['note']}")

    activity = ctx.get("activity", {})
    if activity:
        lines.append("\n历史统计：")
        events = activity.get("events_total", 0)
        tasks = activity.get("tasks_total", 0)
        executor = activity.get("executor_count", 0)
        if events:
            lines.append(f"- 累计事件 {events} 次")
        if tasks:
            lines.append(f"- 累计任务 {tasks} 次")
        if executor:
            lines.append(f"- 作为执行人 {executor} 次")

    lines.append("\n> 以上为历史统计数据，不代表能力评价。")
    return "\n".join(lines)


# Cache invalidation for use after new imports
def invalidate_cache():
    global _cache_tasks, _cache_org, _cache_entity
    _cache_tasks = None
    _cache_org = None
    _cache_entity = None
