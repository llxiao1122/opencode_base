"""
agent/feedback_loop.py — 观测数据利用闭环。

定时从 observations 中提取高置信 pattern，
更新 entity_index.json 的权重/标签/hint。
"""

import json, logging, re
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
OBS_DIR = ROOT / "data" / "memory" / "observations" / "people"
INDEX_PATH = ROOT / "data" / "state" / "entity_index.json"

_ENTITY_CACHE: list[dict] | None = None


# 停用：2026-07-30 — 实体权重管理由 worldview_update() 接管
def apply(*args, **kwargs):
    return None

def _load_entities() -> list[dict]:
    global _ENTITY_CACHE
    if _ENTITY_CACHE is not None:
        return _ENTITY_CACHE
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        _ENTITY_CACHE = data.get("confirmed_entities", [])
        return _ENTITY_CACHE
    except Exception as e:
        logger.warning("feedback_loop: load entities failed: %s", e)
        return []


def _invalidate_cache():
    global _ENTITY_CACHE
    _ENTITY_CACHE = None


def _find_entity(name: str) -> dict | None:
    for e in _load_entities():
        if e["name"] == name:
            return e
        if name in e.get("aliases", []):
            return e
    return None


def _scan_patterns() -> list[dict]:
    results = []
    if not OBS_DIR.exists():
        return results
    for fpath in sorted(OBS_DIR.glob("*.md")):
        name = fpath.stem
        entity = _find_entity(name)
        if not entity:
            continue
        text = fpath.read_text(encoding="utf-8")
        for section in re.split(r"\n---+\n", text):
            if "layer: pattern" not in section:
                continue
            conf_m = re.search(r"confidence:\s*([\d.]+)", section)
            confidence = float(conf_m.group(1)) if conf_m else 0.0
            results.append({
                "entity": entity,
                "name": name,
                "confidence": confidence,
                "text": section[:300],
            })
    return results


def apply():
    patterns = _scan_patterns()
    if not patterns:
        logger.debug("feedback_loop: no patterns found")
        return

    high_conf = [p for p in patterns if p["confidence"] >= 0.7]
    if not high_conf:
        logger.debug("feedback_loop: no high-confidence patterns")
        return

    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        entities = data.get("confirmed_entities", [])
    except Exception as e:
        logger.warning("feedback_loop: read index failed: %s", e)
        return

    changed = False
    for p in high_conf:
        for e in entities:
            if e["name"] != p["entity"]["name"]:
                continue
            new_weight = min(2.0, e.get("weight", 1.0) + 0.1)
            if abs(new_weight - e.get("weight", 1.0)) > 0.01:
                e["weight"] = round(new_weight, 2)
                changed = True
            text_lower = p["text"].lower()
            for kw in ["擅长", "熟练", "高效", "可靠", "负责"]:
                if kw in text_lower:
                    existing = e.get("tags", []) if isinstance(e.get("tags"), list) else []
                    if kw not in existing:
                        e.setdefault("tags", []).append(kw)
                        changed = True
                    break

    if changed:
        data["_meta"]["updated"] = __import__("datetime").datetime.now().strftime(
            "%Y-%m-%d"
        )
        tmp = Path(str(INDEX_PATH) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(INDEX_PATH)
        _invalidate_cache()
        logger.info("feedback_loop: updated %d entities from %d patterns",
                     len(high_conf), len(patterns))
