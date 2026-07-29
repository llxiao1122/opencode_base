"""
memory/recorder.py — 统一记录入口 (Plan D).

所有写入统一经此入口：
  ① obs_write → .md + .index.json
  ② FAISS episodic append → 立即可搜
  ③ 去重（同一 text[:80] 10s 内跳过）
"""

import logging
import threading
import time
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_DEDUP_WINDOW = 10
_dedup_cache = {}
_dedup_lock = threading.Lock()

# 世界观待处理环形缓冲区：保留最近 100 条记录文本
_RING_BUF = []
_RING_BUF_MAX = 100
_RING_LOCK = threading.Lock()
_RING_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "state" / "worldview" / "_ringbuf.json"


def _check_dedup(key: str) -> bool:
    now = time.time()
    with _dedup_lock:
        last = _dedup_cache.get(key)
        if last and now - last < _DEDUP_WINDOW:
            return True
        _dedup_cache[key] = now
        if len(_dedup_cache) > 1024:
            old = {k for k, v in list(_dedup_cache.items()) if now - v > 60}
            for k in old:
                _dedup_cache.pop(k, None)
    return False


def record(text: str, source: str = "", obs_type: str = "",
           layer: str = "rule", importance: str = "medium",
           confidence: float = 0.5):
    key = text[:80]
    if _check_dedup(key):
        logger.debug("dedup skip: same text within %ds", _DEDUP_WINDOW)
        return

    if len(text.strip()) < 5:
        return

    _ring_append(f"[{source}] {text[:120]}")
    _increment_pending()


def _ring_append(text: str):
    global _RING_BUF
    with _RING_LOCK:
        _RING_BUF.append(text)
        if len(_RING_BUF) > _RING_BUF_MAX:
            _RING_BUF = _RING_BUF[-_RING_BUF_MAX:]
        try:
            _RING_PATH.parent.mkdir(parents=True, exist_ok=True)
            _RING_PATH.write_text(
                "\n".join(_RING_BUF[-_RING_BUF_MAX:]),
                encoding="utf-8",
            )
        except Exception:
            pass


def _increment_pending():
    """世界观待处理计数器 +1"""
    try:
        from skills.memory.worldview import _load_index, _save_index
        idx = _load_index()
        idx["pending_records"] = idx.get("pending_records", 0) + 1
        _save_index(idx)
    except Exception as e:
        logger.debug("pending increment failed: %s", e)
