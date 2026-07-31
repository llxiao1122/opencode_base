"""
skills/router/faiss_router.py — 两层路由：Worldview → FAISS。

  1. Worldview Layer: 对 197 个实体分节做语义匹配，从命中类型/节名推路由
  2. FAISS Layer: route_index 种子兜底（worldview 匹配 < 0.55 时使用）

Slot 提取 (extract_slots) 保留轻量正则供 agent 语境使用，不参与路由判断。
纠错检测移入 entry.py handle_core() 做预检。
"""

import json, os, re, threading, faiss, numpy as np
from functools import lru_cache
from pathlib import Path
from typing import Tuple, Optional

from skills.shared.path import ensure_paths, root as _project_root

ensure_paths()

_SEEDS_PATH = Path(__file__).resolve().parent / "route_seeds.json"
_STAMP_PATH = _project_root() / "data" / "state" / ".seeds_stamp"

_idx_mgr = None
_idx_lock = threading.Lock()

# ── Slot 提取（仅 agent 语境用，不参与路由）─────────────────────
_SLOT_TIME = re.compile(r"(今|明|昨|后)天|这周|本周|下周|周[一二三四五六日]|\d+月\d+日|\d+号")
_SLOT_CORRECTION = re.compile(r"不对|错了|纠正|更正|修改|说错了|不是的|错了")
_SLOT_KNOWLEDGE = ["制度", "规定", "流程", "标准", "规范", "要求", "怎么办", "如何", "什么", "怎么", "多少", "哪里"]
_SLOT_EVENT = ["通知", "提醒", "记录", "发生", "出现", "收到", "注意"]


def extract_slots(text: str) -> dict:
    """提取结构化信号槽位，供下游 context 使用。"""
    has_time = bool(_SLOT_TIME.search(text))
    has_correction = bool(_SLOT_CORRECTION.search(text))
    has_knowledge = any(kw in text for kw in _SLOT_KNOWLEDGE)
    has_event = any(kw in text for kw in _SLOT_EVENT)
    has_person = False
    person_names = []
    try:
        from skills.router.entity_resolver import resolve_entities
        resolved = resolve_entities(text)
        person_names = [e["name"] for e in resolved.get("entities", []) if _is_person_entity(e["name"])]
        has_person = bool(person_names)
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


def _is_person_entity(name: str) -> bool:
    """检查实体名是否对应 worldview 中的 person 类型"""
    try:
        idx_path = _project_root() / "data" / "state" / "worldview" / "index.json"
        if idx_path.exists():
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            ent = idx.get("entities", {}).get(name, {})
            return ent.get("type") == "person"
    except Exception:
        pass
    return False


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


_CONFIG_PATH = Path(__file__).parent / "route_config.json"
_CONFIG = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
_WV_TYPE_ROUTE = _CONFIG["_WV_TYPE_ROUTE"]
_WV_CONF_DEFAULT = _CONFIG.get("_WV_CONF_DEFAULT", {})


def _worldview_classify(text: str) -> Optional[Tuple[str, float]]:
    """Worldview Layer: 对实体分节做语义匹配，从命中类型推路由。

    Returns (route, confidence) 或 None（匹配 < 0.65）。
    """
    try:
        from skills.memory.worldview import search as wv_search
        hits = wv_search(text, top_k=1)
        if not hits:
            return None
        h = hits[0]
        score = h.get("score", 0.0)
        if score < 0.65:
            return None

        entity_type = h.get("type", "")
        route = _WV_TYPE_ROUTE.get(entity_type, "knowledge_retrieve")
        base_conf = _WV_CONF_DEFAULT.get(entity_type, 0.70)

        if entity_type == "person":
            # 叙述型长文本（>30 字）含事件/任务动词：是"汇报发生了什么"而非
            # "查询某人档案"，交还 Agent 决断（agent 仍可选 profile_query）。
            if len(text) > 30 and _NARRATIVE_KW_RE.search(text):
                return None
            return (route, round(min(score, base_conf), 2))

        return (route, round(min(score + 0.05, base_conf), 2))
    except Exception:
        return None


_PERSON_NAMES_CACHE = None

# 叙述型文本信号：汇报/安排/跟进类动词，命中即视为"事件叙述"而非"档案查询"
_NARRATIVE_KW_RE = re.compile(
    r"安排|完成|负责|发送|钉钉|提醒|回复|上报|运维|联系|咨询|领出|领料|交接|请假|"
    r"任务|反馈|跟进|执行|安排|处理|办理|询问|试了|显示错误|未读|担心|上报运维"
)


def _load_person_names() -> list[str]:
    global _PERSON_NAMES_CACHE
    if _PERSON_NAMES_CACHE is not None:
        return _PERSON_NAMES_CACHE
    try:
        idx_path = _project_root() / "data" / "state" / "worldview" / "index.json"
        if idx_path.exists():
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            _PERSON_NAMES_CACHE = [n for n, v in idx.get("entities", {}).items() if v.get("type") == "person"]
            return _PERSON_NAMES_CACHE
    except Exception:
        pass
    return []


@lru_cache(maxsize=1024)
def classify(user_input: str) -> Tuple[str, float]:
    text = user_input.strip()
    if not text:
        return ("unknown", 0.0)

    # 0. 人名预检：已知 person 实体名精确匹配 → 仅短查询（≤30 字）短路直返。
    #    叙述型长文本（事件汇报/任务安排/反馈）交还语义层与 Agent 决断，
    #    避免"提及人名 ≠ 查询档案"的劫持（如：安排某人完成某事的事件记录）。
    for name in _load_person_names():
        if name in text:
            if len(text) <= 30:
                return ("profile_query", 0.88)
            break

    # 1+2 并行：Worldview + FAISS 种子，选最优
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_wv = ex.submit(_worldview_classify, text)
        f_faiss = ex.submit(_faiss_classify, text)

        # worldview 优先
        wv = f_wv.result()
        if wv is not None:
            return wv

        faiss_result = f_faiss.result()
        if faiss_result is not None:
            return faiss_result

    return ("unknown", 0.0)


def _faiss_classify(text: str) -> Optional[Tuple[str, float]]:
    """FAISS seeds layer: route_index 种子兜底。"""
    try:
        idx_mgr = _get_index()
        raw = idx_mgr.embed(text)
        raw = np.asarray(raw, dtype=np.float32)
        if raw.ndim == 1:
            raw = raw.reshape(1, -1)

        if np.linalg.norm(raw) < 1e-8:
            return None

        faiss.normalize_L2(raw)

        distances, indices = idx_mgr.search(raw, k=3)
        top_dist = float(distances[0][0])
        top_idx = int(indices[0][0])

        confidence = round(max(0.0, min(1.0, top_dist)), 2)

        if confidence < 0.5:
            return None

        return (idx_mgr.route_labels[top_idx], confidence)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("FAISS classify failed: %s", e, exc_info=True)
        return None
