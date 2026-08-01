"""
shared/entity.py — Unified entity + team resolution (worldview SSOT).

Single source of truth:
  - Loading worldview entities/*.md (cached)
  - Role lookup by person name
  - Team membership mapping (delegates to organization/model.py)
  - Broadcast/assign word lists
"""

import json
import re
from pathlib import Path

from skills.shared.path import root as _root
ROOT = _root()
ENTITIES_DIR = ROOT / "data" / "state" / "worldview" / "entities"

_entities_cache: list = None


_RE_ROLE = re.compile(r"-\s+\*\*角色\*\*:\s*(.*)")
_RE_ALIAS = re.compile(r"-\s+\*\*别名\*\*:\s*(.*)")
_RE_NAME = re.compile(r"-\s+\*\*姓名\*\*:\s*(.*)")
_RE_WEIGHT = re.compile(r"-\s+\*\*权重\*\*:\s*(\d+(?:\.\d+)?)")
_RE_ROUTE_HINT = re.compile(r"-\s+\*\*路由提示\*\*:\s*(.*)")


def _parse_md(filepath: Path) -> dict | None:
    """Parse a worldview entity .md file into a structured dict."""
    content = filepath.read_text(encoding="utf-8")
    name = filepath.stem
    role = ""
    aliases = []
    weight = 1.0
    route_hint = []

    for line in content.splitlines():
        m = _RE_ROLE.match(line)
        if m:
            role = m.group(1).strip()
        m = _RE_ALIAS.match(line)
        if m:
            raw = m.group(1).strip()
            aliases = [a.strip() for a in raw.split("、") if a.strip()]
        m = _RE_WEIGHT.match(line)
        if m:
            weight = float(m.group(1))
        m = _RE_ROUTE_HINT.match(line)
        if m:
            try:
                route_hint = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                route_hint = []

    return {
        "name": name,
        "role": role,
        "aliases": aliases,
        "weight": weight,
        "route_hint": route_hint,
    }


def _load_raw() -> list:
    global _entities_cache
    if _entities_cache is not None:
        return _entities_cache
    results = []
    if ENTITIES_DIR.exists():
        for f in sorted(ENTITIES_DIR.glob("*.md")):
            try:
                parsed = _parse_md(f)
                if parsed:
                    results.append(parsed)
            except Exception:
                pass
    _entities_cache = results
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
    """从 worldview 解析当前用户（李林骁）的姓名/角色/班组。"""
    """从 worldview 解析当前用户（李林骁）的姓名/角色/班组。"""
    from skills.organization.model import OrganizationModel
    org = OrganizationModel()
    for e in _load_raw():
        if e["name"] == "李林骁":
            return {
                "name": "李林骁",
                "role": e.get("role", "工班长"),
                "team": org.get_team_name("李林骁") or "铁炉西工班",
            }
    return {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
