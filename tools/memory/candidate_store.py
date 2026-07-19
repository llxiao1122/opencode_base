"""
memory/candidate_store.py — Candidate memory persistence.

Stores observed patterns in data/memory_candidates.json.
Three types:  behavior_pattern / role_pattern / work_relation_pattern.
Three states: candidate → verified | expired.

Cognitive facts decay over time — "expired" means "no longer observed",
not "was wrong". Wrong inferences are rejected, not expired.
"""

import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
STORE_PATH = ROOT / "data" / "memory_candidates.json"


def _ensure_store():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        _write([])


def _read() -> list:
    _ensure_store()
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(data: list):
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save(candidate: dict):
    """Save or update a candidate memory."""
    candidates = _read()
    for i, c in enumerate(candidates):
        if c["id"] == candidate["id"]:
            candidates[i] = candidate
            _write(candidates)
            return
    candidates.append(candidate)
    _write(candidates)


def list_by_type(candidate_type: str) -> list:
    """List candidates of a given type."""
    return [c for c in _read() if c.get("type") == candidate_type]


def list_active() -> list:
    """List all non-expired candidates."""
    return [c for c in _read() if c.get("status") != "expired"]


def verify(candidate_id: str):
    """Promote candidate → verified."""
    _update_status(candidate_id, "verified")


def expire(candidate_id: str):
    """Mark as expired (pattern no longer observed)."""
    _update_status(candidate_id, "expired")


def _update_status(candidate_id: str, new_status: str):
    candidates = _read()
    for c in candidates:
        if c["id"] == candidate_id:
            c["status"] = new_status
            if new_status == "verified" and not c.get("verified_at"):
                c["verified_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            _write(candidates)
            return
