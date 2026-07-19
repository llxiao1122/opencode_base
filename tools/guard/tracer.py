"""
tracer.py — Request-level trace logger
Wire into wrapper.py handle() to record every request end-to-end.

Output: logs/trace.log (JSON lines) + logs/event.log (event transitions)
"""

import json
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = ROOT / "logs"

_current_tracer = None


def get_tracer():
    return _current_tracer


class RequestTracer:
    def __init__(self, user_input):
        global _current_tracer
        self._start = time.time()
        self._data = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "input": user_input[:200],
            "route": None,
            "entities": [],
            "lifecycle": [],
            "pipeline": None,
            "answer": None,
            "elapsed_ms": 0,
            "error": None,
        }
        _current_tracer = self

    def set_route(self, routes, entities=None):
        self._data["route"] = routes
        if entities:
            self._data["entities"] = [
                {"name": e.get("name", ""), "role": e.get("role", "")}
                for e in entities.get("entities", [])[:5]
            ]

    def set_lifecycle(self, affected):
        self._data["lifecycle"] = [
            {"action": a, "event_id": eid} for a, eid in affected
        ]

    def set_pipeline(self, work_result):
        if not work_result:
            return
        self._data["pipeline"] = {
            "person": work_result.get("person", ""),
            "date": work_result.get("date", ""),
            "tasks": len(work_result.get("routine", [])),
            "direct": len(work_result.get("responsibility", {}).get("direct_task", [])),
            "role": len(work_result.get("responsibility", {}).get("role_task", [])),
            "team": len(work_result.get("responsibility", {}).get("team_attention", [])),
        }

    def set_ai_extraction(self, elapsed_ms, section_count, result_count):
        """Phase 1.7.7-C: record AI extraction metrics."""
        self._data["ai_extraction"] = {
            "elapsed_ms": elapsed_ms,
            "sections": section_count,
            "results": result_count,
        }

    def finish(self, answer, error=None):
        global _current_tracer
        self._data["answer"] = (answer or "")[:200]
        self._data["elapsed_ms"] = int((time.time() - self._start) * 1000)
        self._data["error"] = str(error)[:200] if error else None
        _current_tracer = None
        self._write()

    def _write(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "trace.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(self._data, ensure_ascii=False) + "\n")


def log_event_change(action, event_id, title):
    """Called from lifecycle when an event status changes."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "action": action,
        "event_id": event_id,
        "title": (title or "")[:100],
    }
    with open(LOG_DIR / "event.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_error(user_input, error):
    """Write to errors.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "input": (user_input or "")[:200],
        "error": str(error)[:500],
    }
    with open(LOG_DIR / "errors.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
