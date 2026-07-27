"""
shared/entity.py — Unified entity + team resolution.

Single source of truth for:
  - Loading entity_index.json (cached)
  - Role lookup by person name
  - Team membership mapping (delegates to organization/model.py)
  - Broadcast/assign word lists
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX_PATH = ROOT / "data" / "state" / "entity_index.json"

BROADCAST_WORDS = [
    "各班组", "各工班", "各工班长", "全体人员", "所有工班", "各部门",
    "全员", "运营公司全员", "相关人员", "责任人", "负责人",
]

ASSIGN_WORDS = ["通知", "安排", "要求", "指定", "负责", "完成"]

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


def resolve_user() -> dict:
    """从 entity_index 解析当前用户（李林骁）的姓名/角色/班组。"""
    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        for e in data.get("confirmed_entities", []):
            if e["name"] == "李林骁":
                return {"name": "李林骁", "role": e.get("role", "工班长"),
                        "team": e.get("team", "铁炉西工班")}
    except Exception:
        pass
    return {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}


def has_known_entity(text: str) -> bool:
    """Check if text contains any known entity name."""
    for e in _load_raw():
        if e["name"] in text:
            return True
        for alias in e.get("aliases", []):
            if alias in text:
                return True
        surname = e["name"][0] if e["name"] else ""
        for suffix in _ROLE_SUFFIXES:
            if suffix in e.get("role", "") and f"{surname}{suffix}" in text:
                return True
    return False


_ROLE_SUFFIXES = ["经理", "主任", "部长", "副总", "总", "书记",
                   "组长", "班长", "科长", "处长", "院长", "校长", "所长"]

def find_entities_in_text(text: str) -> list:
    """Return [{name, role}] for entities mentioned in text.

    Matches by:
      1. Full name substring (existing)
      2. Alias match
      3. Surname + role-title match (e.g. "张经理" → 张新宇)
    """
    seen = set()
    results = []
    for e in _load_raw():
        name = e["name"]
        role = e.get("role", "")
        # 1. Exact name match
        if name in text:
            if name not in seen:
                seen.add(name)
                results.append({"name": name, "role": role})
            continue
        # 2. Alias match
        matched = False
        for alias in e.get("aliases", []):
            if alias in text:
                if name not in seen:
                    seen.add(name)
                    results.append({"name": name, "role": role})
                matched = True
                break
        if matched:
            continue
        # 3. Surname+role-title match
        surname = name[0] if name else ""
        for suffix in _ROLE_SUFFIXES:
            if suffix in role and f"{surname}{suffix}" in text:
                if name not in seen:
                    seen.add(name)
                    results.append({"name": name, "role": role})
                break
    return results
