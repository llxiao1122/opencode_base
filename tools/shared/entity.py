"""
shared/entity.py — Unified entity + team resolution.

Single source of truth for:
  - Loading entity_index.json (cached)
  - Role lookup by person name
  - Team membership mapping
  - Broadcast/assign word lists
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX_PATH = ROOT / "state" / "entity_index.json"

BROADCAST_WORDS = [
    "各班组", "各工班", "各工班长", "全体人员", "所有工班", "各部门",
    "全员", "运营公司全员", "相关人员", "责任人", "负责人",
]

ASSIGN_WORDS = ["通知", "安排", "要求", "指定", "负责", "完成"]

TEAM_MAP = {
    "李林骁": "铁炉西工班",
    "陈红洁": "铁炉西工班",
    "杨梦卓": "铁炉西工班",
    "谭继衡": "铁炉西工班",
    "苗笑天": "铁炉西工班",
    "张志斌": "铁炉西工班",
}

TEAM_LEADER_MAP = {
    "铁炉西工班": "李林骁",
}

_entities_cache: list = None


def _load_raw():
    global _entities_cache
    if _entities_cache is not None:
        return _entities_cache
    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        _entities_cache = (
            data.get("confirmed_entities", []) +
            data.get("pending_entities", [])
        )
    except Exception:
        _entities_cache = []
    return _entities_cache


def load_entities() -> list:
    """Return all entity dicts [{name, role, ...}]."""
    return list(_load_raw())


def get_role(name: str) -> str:
    """Look up a person's organizational role."""
    for e in _load_raw():
        if e["name"] == name:
            return e.get("role", "")
    return ""


def get_team(name: str) -> str:
    """Look up a person's team name."""
    return TEAM_MAP.get(name, "")


def get_team_leader(team: str) -> str:
    """Return team leader name for a given team."""
    return TEAM_LEADER_MAP.get(team, "")


def has_known_entity(text: str) -> bool:
    """Check if text contains any known entity name."""
    for e in _load_raw():
        if e["name"] in text:
            return True
    return False


def find_entities_in_text(text: str) -> list:
    """Return [{name, role}] for entities mentioned in text."""
    results = []
    for e in _load_raw():
        if e["name"] in text:
            results.append({"name": e["name"], "role": e.get("role", "")})
    return results
