"""
memory/memory_analyzer.py — Offline cognitive pattern discovery (Phase 5).

Reads accumulated Event log + Task results, discovers behavioral/role/work patterns.
Outputs candidate memories with confidence scores. No LLM, no auto-profile changes.

Three pattern types:
    behavior_pattern     — who completes tasks reliably/slowly
    role_pattern         — who frequently sends what kind of messages
    work_relation_pattern — who coordinates with which team/department
"""

import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = ROOT / "memory" / "events" / "log.jsonl"
TASKS_PATH = ROOT / "state" / "tasks.json"


def run() -> list:
    """Main entry: read all data, discover patterns, save candidates.

    Returns list of candidate dicts saved.
    """
    events = _load_events()
    tasks = _load_tasks()
    candidates = []

    candidates.extend(_analyze_behavior(tasks))
    candidates.extend(_analyze_role(events))
    candidates.extend(_analyze_work_relation(tasks))

    if candidates:
        from memory.observation_store import write as obs_write
        for c in candidates:
            obs_write(
                c["fact"],
                source="memory_analyzer",
                obs_type=c.get("type", "behavior"),
                layer="rule",
                confidence=c.get("confidence", 0.0),
            )

    return candidates


def _load_events() -> list:
    if not LOG_PATH.exists():
        return []
    events = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return events


def _load_tasks() -> list:
    if not TASKS_PATH.exists():
        return []
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _next_candidate_id() -> str:
    """Generate unique candidate ID."""
    from pathlib import Path
    store = ROOT / "state" / "memory_candidates.json"
    existing = 0
    if store.exists():
        with open(store) as f:
            existing = len(json.load(f))
    return f"cand_{(existing + 1):04d}"


# ═══════════════════════════════════════════════
# behavior_pattern: executor performance
# ═══════════════════════════════════════════════

def _analyze_behavior(tasks: list) -> list:
    """Analyze per-executor task completion patterns."""
    # Group by executor name
    executor_tasks: dict[str, list] = {}
    for t in tasks:
        for e in t.get("executors", []):
            name = e.get("name", "")
            if name:
                executor_tasks.setdefault(name, []).append(t)

    candidates = []
    for name, task_list in executor_tasks.items():
        total = len(task_list)
        if total < 3:          # Not enough data for meaningful pattern
            continue

        completed = sum(1 for t in task_list if t.get("status") == "completed")
        # Count overdue but not yet completed
        now_str = datetime.now().strftime("%Y-%m-%d")
        overdue = sum(1 for t in task_list
                      if t.get("status") != "completed"
                      and t.get("deadline")
                      and t["deadline"] < now_str)

        success_rate = completed / total if total > 0 else 0
        from memory.confidence import calculate
        confidence = calculate(samples=total, success_rate=success_rate, conflicts=overdue)

        if confidence < 0.4:
            continue

        fact = f"执行任务{total}次，完成{completed}次"
        if overdue > 0:
            fact += f"，逾期{overdue}次"

        candidates.append({
            "id": _next_candidate_id(),
            "type": "behavior_pattern",
            "subject": {"type": "person", "name": name},
            "fact": fact,
            "evidence": {
                "sample_count": total,
                "completed": completed,
                "overdue": overdue,
                "success_rate": round(success_rate, 2),
            },
            "confidence": confidence,
            "source": {"tasks": [t["id"] for t in task_list]},
            "status": "candidate",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_at": None,
        })

    return candidates


# ═══════════════════════════════════════════════
# role_pattern: actor message patterns
# ═══════════════════════════════════════════════

def _analyze_role(events: list) -> list:
    """Analyze per-actor event type distribution."""
    # Group by actor name
    actor_events: dict[str, list] = {}
    for evt in events:
        for a in evt.get("actors", []):
            name = a.get("name", "")
            if name:
                actor_events.setdefault(name, []).append(evt)

    candidates = []
    for name, evt_list in actor_events.items():
        total = len(evt_list)
        if total < 5:          # Not enough data for meaningful pattern
            continue

        # Count by event type
        type_counts: dict[str, int] = {}
        for evt in evt_list:
            et = evt.get("event_type", "unknown")
            type_counts[et] = type_counts.get(et, 0) + 1

        # Find dominant event type
        if not type_counts:
            continue
        dominant = max(type_counts, key=lambda k: type_counts[k])
        dominant_count = type_counts[dominant]
        dominance = dominant_count / total

        if dominance < 0.5:    # No clear pattern
            continue

        from memory.confidence import calculate
        confidence = calculate(samples=total, success_rate=dominance)

        if confidence < 0.5:
            continue

        type_labels = {"instruction": "下发指令", "notification": "发布通知", "feedback": "反馈任务"}
        label = type_labels.get(dominant, dominant)

        candidates.append({
            "id": _next_candidate_id(),
            "type": "role_pattern",
            "subject": {"type": "person", "name": name},
            "fact": f"{total}次消息中{dominant_count}次为{label}",
            "evidence": {
                "sample_count": total,
                "dominant_type": dominant,
                "dominant_count": dominant_count,
                "dominance": round(dominance, 2),
            },
            "confidence": confidence,
            "source": {"events": [e.get("id", "") for e in evt_list if e.get("id")]},
            "status": "candidate",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_at": None,
        })

    return candidates


# ═══════════════════════════════════════════════
# work_relation_pattern: task coordination
# ═══════════════════════════════════════════════

def _analyze_work_relation(tasks: list) -> list:
    """Analyze who coordinates tasks with whom (not org hierarchy)."""

    # Count owner ↔ executor pairs
    relation_counts: dict[tuple, int] = {}
    for t in tasks:
        owner_name = t.get("owner", {}).get("name", "")
        if not owner_name:
            continue
        for e in t.get("executors", []):
            executor_name = e.get("name", "")
            if executor_name and executor_name != owner_name:
                pair = (owner_name, executor_name)
                relation_counts[pair] = relation_counts.get(pair, 0) + 1

    candidates = []
    for (owner, executor), count in relation_counts.items():
        if count < 5:          # Not enough data
            continue

        from memory.confidence import calculate
        confidence = calculate(samples=count, success_rate=0.7)  # neutral base for relations

        if confidence < 0.5:
            continue

        candidates.append({
            "id": _next_candidate_id(),
            "type": "work_relation_pattern",
            "subject": {"type": "pair", "owner": owner, "executor": executor},
            "fact": f"{owner} 与 {executor} 存在 {count} 次任务协调关系",
            "evidence": {"task_count": count},
            "confidence": confidence,
            "source": {"tasks": [t["id"] for t in tasks if t.get("owner", {}).get("name") == owner]},
            "status": "candidate",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_at": None,
        })

    return candidates
