"""
memory/detect/persistence.py — Unified event + task storage.
Single file: state/tasks.json. Each record has a 'type' field ("event" or "task").
"""

import json
from datetime import datetime, timedelta
from pathlib import Path as _PathInternal

_root = _PathInternal(__file__).resolve().parent.parent.parent.parent
STORE_PATH = _root / "state" / "tasks.json"
RETENTION_DAYS = 30


def _ensure_store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        _save_index([])


def _load_index():
    _ensure_store()
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(data):
    tmp = _PathInternal(str(STORE_PATH) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(STORE_PATH)


def _persist(event):
    return


def _next_id():
    index = _load_index()
    existing = {e["id"] for e in index}
    today = datetime.now().strftime("%Y%m%d")
    for i in range(1, 1000):
        cid = f"evt_{today}_{i:03d}"
        if cid not in existing:
            return cid
    return f"evt_{today}_{int(datetime.now().timestamp()) % 100000:05d}"


def list_events(status=None):
    index = _load_index()
    events = [e for e in index if e.get("type") == "event"]
    if status:
        events = [e for e in events if e.get("status") == status]
    return sorted(events, key=lambda e: e.get("updated", ""), reverse=True)


def _change_status(event_id, new_status):
    index = _load_index()
    target = None
    for e in index:
        if e["id"] == event_id:
            target = e
            break
    if not target:
        return False

    old_status = target["status"]
    if old_status == new_status:
        return False

    target["status"] = new_status
    target["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if new_status == "completed":
        target["completed_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    _save_index(index)
    return True


def _cleanup_expired():
    index = _load_index()
    now = datetime.now()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    before = len(index)
    index = [
        e for e in index
        if not (
            e.get("type") == "event"
            and e.get("status") in ("completed", "cancelled", "archived", "ignored")
            and _parse_dt(e.get("completed_at", e.get("updated", ""))) < cutoff
        )
    ]
    if len(index) < before:
        _save_index(index)


def _parse_dt(s):
    if not s:
        return datetime.min
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.min


def complete(event_id):
    return _change_status(event_id, "completed")


def archive(event_id):
    return _change_status(event_id, "archived")


def ignore(event_id):
    return _change_status(event_id, "ignored")


change_status = _change_status
load_index = _load_index
save_index = _save_index
