"""
memory/detect/ — Event detection module (refactored from event_detector.py).

Public API: detect, load_index, save_index, change_status, list_events,
            complete, archive, ignore.
"""

# 停用：2026-07-30 — 世界观体系已替代 detect 管道
# 恢复：去掉下一行注解即可
def detect(*args, **kwargs):
    return []

from .detector import detect as _detect  # 保留原实现供参考
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
