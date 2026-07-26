import os, threading, faiss, numpy as np
from pathlib import Path
from typing import Tuple

from skills.shared.path import ensure_paths

ensure_paths()

_SEEDS_PATH = Path(__file__).resolve().parent / "route_seeds.json"
_STAMP_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "state" / ".seeds_stamp"

_idx_mgr = None
_idx_lock = threading.Lock()


def _get_index():
    global _idx_mgr
    if _idx_mgr is not None:
        if _STAMP_PATH.exists():
            _STAMP_PATH.unlink(missing_ok=True)
            from skills.router.route_index import RouteIndexManager
            _idx_mgr = RouteIndexManager()
            _idx_mgr.build(_SEEDS_PATH)
        return _idx_mgr
    with _idx_lock:
        if _idx_mgr is None:
            from skills.router.route_index import RouteIndexManager
            _idx_mgr = RouteIndexManager()
            _idx_mgr.build(_SEEDS_PATH)
    return _idx_mgr


def classify(user_input: str) -> Tuple[str, float]:
    text = user_input.strip()
    if not text:
        return ("event", 0.0)

    try:
        idx_mgr = _get_index()
        raw = idx_mgr.embed(text)
        raw = np.asarray(raw, dtype=np.float32)
        if raw.ndim == 1:
            raw = raw.reshape(1, -1)

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
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("FAISS classify failed: %s", e, exc_info=True)
        return ("event", 0.0)
