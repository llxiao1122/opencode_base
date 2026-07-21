#!/usr/bin/env python3
"""
routing/builder.py — Entity index builder.
Reads state/team_work.json for org structure + leaders,
preserves existing member extra fields in entity_index.json.

Usage: python3 skills/routing/builder.py
  Called automatically by entry.py on startup.
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TEAM_WORK_FILE = ROOT / "state" / "team_work.json"
INDEX_FILE = ROOT / "state" / "entity_index.json"


def _load_team_work() -> dict:
    if not TEAM_WORK_FILE.exists():
        return {}
    try:
        return json.loads(TEAM_WORK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_entities_from_team_work() -> list[dict]:
    """Build base entity list from team_work.json."""
    tw = _load_team_work()
    entities = []
    seen = set()

    def add(name, role="", extra=None, update_if_seen=False):
        if len(name) < 2:
            return
        if name in seen:
            if update_if_seen and extra:
                for e in entities:
                    if e["name"] == name:
                        e.update(extra)
                        break
            return
        seen.add(name)
        entry = {
            "name": name,
            "aliases": [],
            "route_hint": ["G"],
            "weight": 1.0,
            "role": role,
            "source": "state/team_work.json",
            "team": "铁炉西工班",
        }
        if extra:
            entry.update(extra)
        entities.append(entry)

    # Hierarchy chain
    parts = [p.strip() for p in tw.get("hierarchy", {}).get("chain", "").split("→") if p.strip() and p.strip() != "5保管"]
    for part in parts:
        add(part)

    # Management / safety / assets / clerk lists
    for key in ("management", "safety"):
        for name in tw.get("hierarchy", {}).get(key, []):
            add(name)

    # Roles with area
    for r in tw.get("roles", []):
        add(r["name"], r.get("area", ""), {"area": r.get("area", "")})

    # Leaders with category + strategy (may already exist via hierarchy chain — use update_if_seen)
    for category in ("direct", "upper", "colleague"):
        for item in tw.get("leaders", {}).get(category, []):
            extra = {"leaders": {"category": category}}
            if "strategy" in item:
                extra["leaders"]["strategy"] = item["strategy"]
            add(item["name"], item.get("title", ""), extra, update_if_seen=True)

    # Contacts (names not already seen)
    for key, val in tw.get("contacts", {}).items():
        if isinstance(val, list):
            for name in val:
                add(name)
        elif isinstance(val, str):
            add(val)

    # Asset names
    assets = tw.get("hierarchy", {}).get("assets", {})
    for val in assets.values():
        for part in str(val).split("("):
            name = part.strip()
            if name and len(name) >= 2:
                add(name)

    # Clerk name
    clerk = tw.get("hierarchy", {}).get("clerk", "")
    if clerk:
        name = clerk.split("(")[0].strip()
        add(name)

    # Ensure user is present
    add("李林骁", "工班长")

    return entities


def _load_existing_pending() -> list:
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data.get("pending_entities", [])
    except Exception:
        return []


def _load_existing_entities() -> dict:
    """Load existing confirmed_entities keyed by name."""
    if not INDEX_FILE.exists():
        return {}
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return {e["name"]: e for e in data.get("confirmed_entities", [])}
    except Exception:
        return {}


def build() -> dict:
    existing = _load_existing_entities()

    # Build fresh from team_work.json
    fresh = _extract_entities_from_team_work()
    seen = {}
    entities = []

    for e in fresh:
        name = e["name"]
        if name in existing:
            merged = dict(existing[name])
            merged["role"] = e["role"] or merged.get("role", "")
            merged["source"] = e["source"]
            merged["leaders"] = e.get("leaders", merged.get("leaders"))
            merged["area"] = e.get("area", merged.get("area", ""))
            merged["team"] = e.get("team", merged.get("team", ""))
            entities.append(merged)
            seen[name] = len(entities) - 1
        elif name in seen:
            existing_entry = entities[seen[name]]
            if e["role"] and not existing_entry["role"]:
                existing_entry["role"] = e["role"]
        else:
            entities.append(e)
            seen[name] = len(entities) - 1

    # Preserve existing entities not covered by team_work.json (e.g., members with extra fields)
    for name, entry in existing.items():
        if name not in seen:
            entities.append(entry)
            seen[name] = len(entities) - 1

    pending = _load_existing_pending()

    data = {
        "_meta": {
            "version": 2,
            "updated": datetime.now().strftime("%Y-%m-%d"),
            "source": "state/team_work.json",
        },
        "confirmed_entities": entities,
        "pending_entities": pending,
    }

    tmp = Path(str(INDEX_FILE) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(INDEX_FILE)

    return data


if __name__ == "__main__":
    result = build()
    print(f"Built {len(result['confirmed_entities'])} confirmed, "
          f"{len(result['pending_entities'])} pending entities → state/entity_index.json")
