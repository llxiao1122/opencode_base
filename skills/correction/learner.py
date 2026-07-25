"""
correction/learner.py — Offline correction pattern learner.

Detects two implicit correction patterns without needing explicit "不对":
  A. Re-query: adjacent messages in same session with different routes and similar content
  B. Confirm negation: user says "不是"/"不对" right after system asked a confirm question

Accumulated corrections auto-update route_seeds.json.
"""

import json
from collections import Counter
from pathlib import Path
from typing import List, Tuple

_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "state" / "decision_log.jsonl"
_SEEDS_PATH = Path(__file__).resolve().parent.parent.parent / "skills" / "routing" / "route_seeds.json"
_STAMP_PATH = Path(__file__).resolve().parent.parent.parent / "state" / ".seeds_stamp"

_SIMILARITY_M = None


def _load_log() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    raw = _LOG_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    result = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except Exception:
            continue
    return result


def _sem_score(a: str, b: str) -> float:
    """Compute smoothed semantic similarity score 0~1."""
    global _SIMILARITY_M
    if not a or not b:
        return 0.0
    try:
        if _SIMILARITY_M is None:
            from skills.shared.semantic import _get_matcher
            _SIMILARITY_M = _get_matcher()
        return float(_SIMILARITY_M.score(a, [b]))
    except Exception:
        a_set = set(a.lower())
        b_set = set(b.lower())
        inter = len(a_set & b_set)
        union = len(a_set | b_set)
        raw = inter / union if union else 0.0
        return raw * 2.5 if raw > 0 else 0.0


def _detect_requery(entries: list[dict]) -> List[Tuple[str, str]]:
    """Pattern A: same session, adjacent seq, similar msg, different route."""
    corrections = []
    grouped = {}
    for e in entries:
        grouped.setdefault(e["session"], []).append(e)

    for sid, group in grouped.items():
        group.sort(key=lambda x: x["seq"])
        for i in range(len(group) - 1):
            a, b = group[i], group[i + 1]
            if a.get("conf", 0) < 0.4 or b.get("conf", 0) < 0.4:
                continue
            a_route = a.get("tool_id") or a.get("route", "")
            b_route = b.get("tool_id") or b.get("route", "")
            if a_route == b_route:
                continue
            sim = _sem_score(a["msg"], b["msg"])
            if sim < 0.3:
                continue
            corrections.append((a["msg"], b_route))

    return corrections


def _detect_confirm_negation(entries: list[dict]) -> List[Tuple[str, str]]:
    """Pattern B: confirm question followed by negation/re-direction."""
    corrections = []
    grouped = {}
    for e in entries:
        grouped.setdefault(e["session"], []).append(e)

    NEGATIONS = {"不是", "不对", "错了", "查任务", "查人", "查一下", "看任务"}

    for sid, group in grouped.items():
        group.sort(key=lambda x: x["seq"])
        for i in range(len(group) - 1):
            a, b = group[i], group[i + 1]
            if not a.get("has_confirm"):
                continue
            b_msg = b["msg"].strip().lower()
            if any(b_msg.startswith(n) for n in NEGATIONS):
                b_route = b.get("tool_id") or b.get("route", "")
                corrections.append((a["msg"], b_route))

    return corrections


def _dedupe_seeds(seeds: list[str]) -> list[str]:
    seen = set()
    return [s for s in seeds if not (s in seen or seen.add(s))]


def run_learner(min_count: int = 3) -> dict:
    """Run offline learning. Returns summary of what happened."""
    entries = _load_log()
    if not entries:
        return {"added": 0, "corrections_found": 0, "reason": "no_log"}

    requery = _detect_requery(entries)
    negation = _detect_confirm_negation(entries)
    all_corrections = requery + negation

    if not all_corrections:
        return {"added": 0, "corrections_found": 0, "reason": "no_pattern"}

    counts = Counter(all_corrections)
    seeds = json.loads(_SEEDS_PATH.read_text(encoding="utf-8"))
    added = 0

    for (msg, target_route), count in counts.items():
        if count < min_count:
            continue
        if target_route not in seeds:
            continue
        cur = seeds[target_route]["seeds"]
        if msg not in cur:
            cur.append(msg)
            added += 1

    if added:
        _SEEDS_PATH.write_text(json.dumps(seeds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _STAMP_PATH.touch()

    return {
        "added": added,
        "corrections_found": len(all_corrections),
        "requery": len(requery),
        "negation": len(negation),
    }
