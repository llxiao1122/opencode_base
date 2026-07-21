"""
task/analyzer.py — Task statistics and overdue checks.

Reads tasks.json to provide per-person stats and deadline awareness.
Stats are separated by role: executed (as executor) vs owned (as owner).
Pure read, no writes. Input for future memory/profile_store.
"""

import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
STORE_PATH = ROOT / "state" / "tasks.json"


def _all_tasks() -> list:
    if not STORE_PATH.exists():
        return []
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def stats_for(name: str) -> dict:
    """Per-person task statistics, separated by role.

    Returns:
        {name, executed: {total, completed, overdue}, owned: {total, completed, overdue}}
    """
    tasks = _all_tasks()
    executed = []
    owned = []

    for t in tasks:
        owner_name = t.get("owner", {}).get("name", "")
        if owner_name == name:
            owned.append(t)
        for e in t.get("executors", []):
            if e.get("name") == name:
                executed.append(t)
                break

    def _aggregate(task_list):
        total = len(task_list)
        completed = sum(1 for t in task_list if t.get("status") == "completed")
        overdue = sum(1 for t in task_list
                      if t.get("status") != "completed"
                      and t.get("deadline")
                      and t["deadline"] < datetime.now().strftime("%Y-%m-%d"))
        avg_hours = None
        if completed > 0:
            deltas = []
            for t in task_list:
                if t.get("status") == "completed" and t.get("created_at") and t.get("completed_at"):
                    try:
                        start = datetime.fromisoformat(t["created_at"])
                        end = datetime.fromisoformat(t["completed_at"])
                        deltas.append((end - start).total_seconds() / 3600)
                    except ValueError:
                        pass
            if deltas:
                avg_hours = round(sum(deltas) / len(deltas), 1)
        return {"total": total, "completed": completed, "overdue": overdue, "avg_hours": avg_hours}

    return {
        "name": name,
        "executed": _aggregate(executed),
        "owned": _aggregate(owned),
    }


def check_overdue(owner=None):
    """List all tasks past deadline that are not completed.

    Returns list of {task_id, action, deadline, pending_executors: [...]}.
    """
    tasks = _all_tasks()
    now_str = datetime.now().strftime("%Y-%m-%d")
    overdue = []

    for t in tasks:
        if t.get("status") == "completed":
            continue
        deadline = t.get("deadline", "")
        if not deadline or deadline >= now_str:
            continue
        if owner and t.get("owner", {}).get("name") != owner:
            continue
        pending = [e["name"] for e in t.get("executors", []) if e.get("status") != "done"]
        overdue.append({
            "task_id": t["id"],
            "action": t.get("action", "")[:60],
            "deadline": deadline,
            "owner": t.get("owner", {}).get("name", ""),
            "pending_executors": pending,
        })

    return overdue


def list_active_due_soon(owner: str, within_days: int = 3) -> list:
    """List active tasks due within N days. Returns executor-level detail."""
    tasks = _all_tasks()
    now = datetime.now()
    upcoming = []

    for t in tasks:
        if t.get("status") == "completed":
            continue
        if t.get("owner", {}).get("name") != owner:
            continue
        deadline = t.get("deadline", "")
        if not deadline:
            continue
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            continue
        days_left = (deadline_dt - now).days
        if days_left < 0 or days_left > within_days:
            continue

        executors_detail = []
        for e in t.get("executors", []):
            executors_detail.append({
                "name": e["name"],
                "status": e.get("status", "pending"),
                "days_left": days_left,
            })

        upcoming.append({
            "task_id": t["id"],
            "action": t.get("action", "")[:60],
            "deadline": deadline,
            "days_left": days_left,
            "priority": t.get("priority", {}).get("value", "normal"),
            "executors": executors_detail,
        })

    return sorted(upcoming, key=lambda x: x["days_left"])
