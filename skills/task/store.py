"""
task/store.py — Task JSON persistence.

Single-file store: data/tasks.json
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STORE_PATH = ROOT / "state" / "tasks.json"


def _ensure_store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        _write([])


def _read():
    _ensure_store()
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(data):
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save(task: dict):
    tasks = _read()
    for i, t in enumerate(tasks):
        if t["id"] == task["id"]:
            tasks[i] = task
            _write(tasks)
            return
    tasks.append(task)
    _write(tasks)


def load(task_id: str):
    tasks = _read()
    for t in tasks:
        if t["id"] == task_id:
            return t
    return None


def list_by_owner(owner: str, status=None):
    tasks = _read()
    result = [t for t in tasks if t.get("owner", {}).get("name") == owner]
    if status:
        result = [t for t in result if t.get("status") == status]
    return sorted(result, key=lambda t: t.get("created_at", ""), reverse=True)


def update(task_id: str, updates: dict):
    task = load(task_id)
    if task:
        task.update(updates)
        save(task)
        return task
    return None


def update_executor_status(task_id: str, executor_name: str, new_status: str) -> bool:
    """Mark an executor as done in a task. Updates both executors list and matching subtasks."""
    task = load(task_id)
    if not task:
        return False

    updated = False
    for e in task.get("executors", []):
        if e["name"] == executor_name and e["status"] != new_status:
            e["status"] = new_status
            updated = True

    for st in task.get("subtasks", []):
        if st.get("assignee") == executor_name and not st.get("done"):
            st["done"] = True
            updated = True

    if updated:
        save(task)
    return updated


def get_active_tasks(owner_name: str) -> list:
    """Get all non-completed tasks for an owner."""
    from task.status import IN_PROGRESS
    return list_by_owner(owner_name, status=IN_PROGRESS)


def close(task_id: str) -> bool:
    """Close a task: set status to completed and record completed_at timestamp."""
    import json as _json
    from datetime import datetime
    tasks = _read()
    for t in tasks:
        if t["id"] == task_id and t.get("status") != "completed":
            t["status"] = "completed"
            t["completed_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            _write(tasks)
            return True
    return False
