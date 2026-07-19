"""
memory/detect/persistence.py — Event storage, indexing, lifecycle.

Functions: load_index, save_index, change_status, complete, archive, ignore, list_events.
Exported via memory/detect/__init__.py.
"""

import json
import sys
from datetime import datetime
from pathlib import Path as _PathInternal

_root = _PathInternal(__file__).resolve().parent.parent.parent.parent
INDEX_FILE = _root / "memory" / "events" / "index.json"
EVENTS_DIR = _root / "memory" / "events"


def _load_index():
    if not INDEX_FILE.exists():
        return {"events": []}
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(data):
    tmp = _PathInternal(str(INDEX_FILE) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(INDEX_FILE)


def _next_id():
    index = _load_index()
    existing = {e["id"] for e in index.get("events", [])}
    today = datetime.now().strftime("%Y%m%d")
    for i in range(1, 1000):
        cid = f"evt_{today}_{i:03d}"
        if cid not in existing:
            return cid
    return f"evt_{today}_{int(datetime.now().timestamp()) % 100000:05d}"


def _persist(event):
    return


def list_events(status=None):
    index = _load_index()
    events = index.get("events", [])
    if status:
        events = [e for e in events if e.get("status") == status]
    return sorted(events, key=lambda e: e.get("updated", ""), reverse=True)


def _change_status(event_id, new_status):
    index = _load_index()
    target = None
    for e in index.get("events", []):
        if e["id"] == event_id:
            target = e
            break
    if not target:
        return False

    old_status = target["status"]
    if old_status == new_status:
        return False

    old_dir = EVENTS_DIR / old_status / f"{event_id}.json"
    new_dir = EVENTS_DIR / new_status
    new_dir.mkdir(parents=True, exist_ok=True)
    new_path = new_dir / f"{event_id}.json"

    if old_dir.exists():
        with open(old_dir, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["status"] = new_status
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        old_dir.unlink()
    elif new_dir != old_dir:
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump({"id": event_id, "status": new_status}, f, ensure_ascii=False)

    target["status"] = new_status
    target["updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_index(index)
    return True


def complete(event_id):
    return _change_status(event_id, "completed")


def archive(event_id):
    return _change_status(event_id, "archived")


def ignore(event_id):
    return _change_status(event_id, "ignored")


change_status = _change_status
load_index = _load_index
save_index = _save_index
