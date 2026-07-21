"""
memory/detect/ — Event detection module (refactored from event_detector.py).

Public API: detect, load_index, save_index, change_status, list_events,
            complete, archive, ignore.
"""

from .detector import detect
from .persistence import (
    load_index, save_index, change_status,
    complete, archive, ignore, list_events,
)

__all__ = [
    "detect",
    "load_index",
    "save_index",
    "change_status",
    "complete",
    "archive",
    "ignore",
    "list_events",
]
