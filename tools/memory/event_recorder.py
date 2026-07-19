"""
event_recorder.py — Event → Memory Recorder (Phase 2)

Records confirmed Events to memory/events/log.jsonl.
Not raw messages — only Events that have passed through core/event.extract().

Input: Event dict from core/event.py
Output: memory/events/log.jsonl (one JSON per line)
"""

import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = ROOT / "memory" / "events" / "log.jsonl"


def record(event: dict):
    """Write a confirmed Event to the event log.

    Args:
        event: Event dict from core/event.py (post-extract, not raw message)
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "id": event.get("id", ""),
        "event_type": event.get("event_type", "unknown"),
        "actors": [
            {"name": a["name"], "role": a.get("role", ""), "position": a.get("position", "")}
            for a in event.get("actors", [])
        ],
        "target": event.get("target", ""),
        "deadline": event.get("time", {}).get("deadline", ""),
        "confidence": event.get("confidence", 0),
        "source": event.get("source", ""),
        "raw_preview": (event.get("raw", "") or "")[:200],
        "recorded_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_events(event_type=None, limit=50):
    """Read recent events from log. Used by analyzer and future profile_store."""
    if not LOG_PATH.exists():
        return []
    events = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line.strip())
                if event_type is None or evt.get("event_type") == event_type:
                    events.append(evt)
            except json.JSONDecodeError:
                continue
    return events[-limit:]
