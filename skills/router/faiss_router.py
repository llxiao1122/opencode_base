"""
skills/router/faiss_router.py — 三层路由：Signal → FAISS → LLM。

  1. Signal Layer: 结构化信号提取（时间/人名/知识域/纠错标记）
     命中且置信 ≥ 0.8 → 直接返回，不走 FAISS
  2. FAISS Layer: 语义向量检索（原逻辑）
  3. LLM Layer: 由 entry.py 在低置信时调用（外部）
"""

import os, threading, faiss, numpy as np, re
from functools import lru_cache
from pathlib import Path
from typing import Tuple, Optional

from skills.shared.path import ensure_paths

ensure_paths()

_SEEDS_PATH = Path(__file__).resolve().parent / "route_seeds.json"
_STAMP_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "state" / ".seeds_stamp"

_idx_mgr = None
_idx_lock = threading.Lock()

# ── Signal Layer 信号定义 ────────────────────────────────────────
_TIME_PAT = re.compile(r"(今|明|昨|后)天|本周|下周|周[一二三四五六日]|\d+月\d+日|\d+号")
_CORRECTION_PAT = re.compile(r"不对|错了|纠正|更正|修改|说错了|不是的|错了")
_KNOWLEDGE_SEEDS = [
    "制度", "规定", "流程", "标准", "规范", "要求", "怎么办", "如何",
    "什么", "怎么", "多少", "哪里",
]
_EVENT_SEEDS = ["通知", "提醒", "记录", "发生", "出现", "收到", "注意"]


def extract_slots(text: str) -> dict:
    """提取结构化信号槽位，供下游 context 使用。"""
    has_time = bool(_TIME_PAT.search(text))
    has_correction = bool(_CORRECTION_PAT.search(text))
    has_knowledge = any(kw in text for kw in _KNOWLEDGE_SEEDS)
    has_event = any(kw in text for kw in _EVENT_SEEDS)
    has_person = False
    person_names = []
    try:
        from skills.router.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        has_person = bool(resolved.get("entities"))
        person_names = [e["name"] for e in resolved.get("entities", [])]
    except Exception:
        pass
    return {
        "has_time": has_time,
        "has_person": has_person,
        "person_names": person_names,
        "has_correction": has_correction,
        "has_knowledge": has_knowledge,
        "has_event": has_event,
    }


def _signal_extract(text: str) -> Optional[Tuple[str, float]]:
    """结构化信号提取。在 FAISS 之前执行，高置信时直接返回路由。"""
    has_time = bool(_TIME_PAT.search(text))
    has_person = False
    try:
        from skills.router.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        has_person = bool(resolved.get("entities"))
    except Exception:
        pass

    has_correction = bool(_CORRECTION_PAT.search(text))
    has_knowledge = any(kw in text for kw in _KNOWLEDGE_SEEDS)
    has_event = any(kw in text for kw in _EVENT_SEEDS)

    # 事件通知：含事件信号 且 有时间 → event（通知在先，时间是事件内容）
    if has_event and has_time:
        return ("event", 0.80)

    # 排期查询（任务/值班）：有时间指示 且 无人名 → task_query
    if has_time and not has_person:
        return ("task_query", 0.90)

    # 人员查询：有人名 且 无时间指示 → profile_query
    if has_person and not has_time:
        return ("profile_query", 0.85)

    # 纠错：含纠错标记 → correction
    if has_correction:
        return ("correction", 0.80)

    # 知识查询：含知识域信号 且 无人名 → knowledge_retrieve
    if has_knowledge and not has_person:
        return ("knowledge_retrieve", 0.75)

    # 事件：含事件信号 且 无时间 → event（有时间已在上方拦截）
    if has_event:
        return ("event", 0.70)

    return None  # 无明确信号，走 FAISS


def _get_index():
    global _idx_mgr
    if _idx_mgr is not None:
        return _idx_mgr
    with _idx_lock:
        if _idx_mgr is not None:
            return _idx_mgr
        if _STAMP_PATH.exists():
            _STAMP_PATH.unlink(missing_ok=True)
        from skills.router.route_index import RouteIndexManager
        _idx_mgr = RouteIndexManager()
        _idx_mgr.build(_SEEDS_PATH)
    return _idx_mgr


@lru_cache(maxsize=1024)
def classify(user_input: str) -> Tuple[str, float]:
    text = user_input.strip()
    if not text:
        return ("event", 0.0)

    # 1. Signal Layer：结构化信号优先
    sig = _signal_extract(text)
    if sig is not None:
        return sig

    # 2. FAISS Layer：语义向量兜底（原逻辑）
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

        if confidence < 0.5:
            return ("event", confidence)

        return (idx_mgr.route_labels[top_idx], confidence)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("FAISS classify failed: %s", e, exc_info=True)
        return ("event", 0.0)
