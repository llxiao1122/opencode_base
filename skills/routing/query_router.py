"""
routing/query_router.py — Query type classifier (Phase 0).

FAISS semantic routing with confidence. Replaces keyword-first approach.
Returns (route, confidence) where route ∈ {profile, task, knowledge, event}.
Routes with confidence < 0.6 fall back to "event".
"""

import os, threading, faiss, numpy as np
from pathlib import Path
from typing import Tuple

_SEEDS_PATH = Path(__file__).resolve().parent / "route_seeds.json"
_STAMP_PATH = Path(__file__).resolve().parent.parent.parent / "state" / ".seeds_stamp"

_idx_mgr = None
_idx_lock = threading.Lock()


def _get_index():
    global _idx_mgr
    if _idx_mgr is not None:
        if _STAMP_PATH.exists():
            _STAMP_PATH.unlink(missing_ok=True)
            from skills.routing.route_index_manager import RouteIndexManager
            _idx_mgr = RouteIndexManager()
            _idx_mgr.build(_SEEDS_PATH)
        return _idx_mgr
    with _idx_lock:
        if _idx_mgr is None:
            from skills.routing.route_index_manager import RouteIndexManager
            _idx_mgr = RouteIndexManager()
            _idx_mgr.build(_SEEDS_PATH)
    return _idx_mgr


def classify(user_input: str) -> Tuple[str, float]:
    """Return (route, confidence). confidence ∈ [0.0, 1.0].

    confidence < 0.6 returns ("event", confidence) as fallback.
    """
    text = user_input.strip()
    if not text:
        return ("event", 0.0)

    try:
        idx_mgr = _get_index()
        raw = idx_mgr.embed(text)
        # embed() 可能返回 1D(384,) 或 2D(1,384)，统一成 2D
        raw = np.asarray(raw, dtype=np.float32)
        if raw.ndim == 1:
            raw = raw.reshape(1, -1)

        # 模长判定：近零向量（空/纯符号输入）直接回退
        if np.linalg.norm(raw) < 1e-8:
            return ("event", 0.0)

        faiss.normalize_L2(raw)

        distances, indices = idx_mgr.search(raw, k=3)
        top_dist = float(distances[0][0])
        top_idx = int(indices[0][0])

        confidence = max(0.0, min(1.0, top_dist))

        if confidence < 0.6:
            return ("event", confidence)

        return (idx_mgr.route_labels[top_idx], confidence)
    except Exception:
        return ("event", 0.0)
