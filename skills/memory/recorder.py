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

logger = logging.getLogger(__name__)

_DEDUP_WINDOW = 10
_dedup_cache = {}
_dedup_lock = threading.Lock()
_mc_lock = threading.Lock()
_mc_instance = None


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


def _append_to_episodic(text: str, importance: str = "medium"):
    global _mc_instance
    with _mc_lock:
        if _mc_instance is None:
            from skills.memory.memory_core import MemoryCore
            _mc_instance = MemoryCore()
        mc = _mc_instance
    try:
        vec = mc._embed(text[:500])
        mc.epi_index.add(vec)
        eid = f"ep-{mc.epi_index.ntotal:04d}"
        today = date.today().isoformat()
        mc.meta["id_map"][eid] = {"chunk": text, "date": today, "importance": importance}
        mc._save_index("episodic", mc.epi_index)
        mc._save_meta()
        mc._search_raw.cache_clear()
    except Exception as e:
        logger.warning("FAISS episodic append failed: %s", e)


def record(text: str, source: str = "", obs_type: str = "",
           layer: str = "rule", importance: str = "medium",
           confidence: float = 0.0, _skip_faiss: bool = False):
    key = text[:80]
    if _check_dedup(key):
        logger.debug("dedup skip: same text within %ds", _DEDUP_WINDOW)
        return

    try:
        from skills.memory.observation_store import write as _obs_write
        _obs_write(text, source=source, obs_type=obs_type, layer=layer, confidence=confidence)
    except Exception as e:
        logger.warning("obs_write failed: %s", e)

    if not _skip_faiss:
        _append_to_episodic(text, importance)
