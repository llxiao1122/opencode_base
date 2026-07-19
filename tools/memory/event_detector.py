"""
event_detector.py — Backward-compatible re-export from memory.detect.

Migrated to memory/detect/ in Phase 9 refactor.
All public API preserved: detect, load_index, save_index, change_status,
                             list_events, complete, archive, ignore.
"""

from memory.detect import (
    detect, load_index, save_index, change_status,
    complete, archive, ignore, list_events,
)

__all__ = [
    "detect", "load_index", "save_index", "change_status",
    "complete", "archive", "ignore", "list_events",
]
