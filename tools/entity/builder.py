#!/usr/bin/env python3
"""
entity/builder.py — Entity index builder.
Parses state/ source files (members/*.md, leaders.md, org.md)
and rebuilds state/entity_index.json.

Usage: python3 tools/entity/builder.py
  Called automatically by entry.py on startup.
"""

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MEMBERS_DIR = ROOT / "state" / "members"
LEADERS_FILE = ROOT / "state" / "leaders.md"
ORG_FILE = ROOT / "state" / "org.md"
INDEX_FILE = ROOT / "state" / "entity_index.json"


def parse_members() -> list[dict]:
    entities = []
    if not MEMBERS_DIR.exists():
        return entities
    for fpath in sorted(MEMBERS_DIR.glob("*.md")):
        name = fpath.stem
        role = ""
        try:
            for line in fpath.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if line.startswith("职责"):
                    # "职责:" or "职责：" after separator
                    sep = line.find(":") if ":" in line else line.find("：")
                    if sep >= 0:
                        role = line[sep + 1:].strip()
                    break
        except Exception:
            pass
        if name:
            entities.append({
                "name": name,
                "aliases": [],
                "route_hint": ["G"],
                "weight": 1.0,
                "role": role,
                "source": f"state/members/{fpath.name}",
            })
    return entities


def parse_leaders() -> list[dict]:
    entities = []
    if not LEADERS_FILE.exists():
        return entities
    try:
        text = LEADERS_FILE.read_text(encoding="utf-8")
    except Exception:
        return entities

    current_section = ""
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            if line.startswith("##"):
                current_section = line.strip("# ").strip()
            continue

        name = ""
        role = current_section

        # "王敬宇(主任·直接上级·物资管理中心)"
        m = re.match(r"^(.+?)\((.+?)\)$", line)
        if m:
            name = m.group(1).strip()
            role = m.group(2).strip().replace("·", "/")
        # "董文静: 物资管理岗·包保·转达上级"
        elif ":" in line or "：" in line:
            sep = ":" if ":" in line else "："
            parts = line.split(sep, 1)
            name = parts[0].strip()
            role = parts[1].strip().replace("·", "/") if len(parts) > 1 else current_section

        if name and len(name) >= 2:
            entities.append({
                "name": name,
                "aliases": [],
                "route_hint": ["G"],
                "weight": 1.0,
                "role": role,
                "source": "state/leaders.md",
            })
    return entities


def parse_org() -> list[dict]:
    entities = []
    if not ORG_FILE.exists():
        return entities
    try:
        text = ORG_FILE.read_text(encoding="utf-8")
    except Exception:
        return entities

    name_pattern = re.compile(r"([\u4e00-\u9fff]{2,4})(?:→|\|)")

    in_tree = False
    for line in text.split("\n"):
        line = line.strip()
        if line == "## TREE":
            in_tree = True
            continue
        if line.startswith("##") and in_tree:
            in_tree = False
            break
        if not in_tree:
            continue
        for m in name_pattern.finditer(line):
            name = m.group(1)
            if name.endswith("郝晓平"):
                continue
            if name and len(name) >= 2:
                entities.append({
                    "name": name,
                    "aliases": [],
                    "route_hint": ["G"],
                    "weight": 1.0,
                    "role": "",
                    "source": "state/org.md",
                })

    # Parse ROLE section for per-person assignments
    person_role_pattern = re.compile(r"^(.+?):\s*(.+)")
    in_role = False
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("## ROLE"):
            in_role = True
            continue
        if line.startswith("##") and in_role:
            in_role = False
            break
        if not in_role:
            continue
        m = person_role_pattern.match(line)
        if m:
            name = m.group(1).strip()
            role_text = m.group(2).strip()
            if name and len(name) >= 2 and "【" not in name:
                found = False
                for e in entities:
                    if e["name"] == name:
                        e["role"] = role_text[:40]
                        found = True
                        break
                if not found:
                    entities.append({
                        "name": name,
                        "aliases": [],
                        "route_hint": ["G"],
                        "weight": 1.0,
                        "role": role_text[:40],
                        "source": "state/org.md",
                    })

    return entities


def _load_user_profile_role() -> dict:
    profile = ROOT / "state" / "user_profile.md"
    if not profile.exists():
        return {}
    name = ""
    role = ""
    in_current = False
    for line in profile.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if "current_user:" in line:
            in_current = True
            continue
        if in_current:
            if ":" in line and not line.startswith("-"):
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k == "name":
                    name = v
                elif k == "role":
                    role = v
            elif line.startswith("-") or not line:
                pass
            else:
                if name:
                    break
    return {"name": name, "role": role} if name else {}


def _load_existing_pending() -> list:
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data.get("pending_entities", [])
    except Exception:
        return []


def build() -> dict:
    seen = {}
    entities = []

    for src_func in [parse_members, parse_leaders, parse_org]:
        for e in src_func():
            if e["name"] in seen:
                existing = entities[seen[e["name"]]]
                if e["role"] and not existing["role"]:
                    existing["role"] = e["role"]
                continue
            seen[e["name"]] = len(entities)
            entities.append(e)

    # Inject user profile role (李林骁 as 工班长)
    user = _load_user_profile_role()
    if user.get("name") and user.get("role"):
        uname = user["name"]
        if uname in seen:
            idx = seen[uname]
            if not entities[idx].get("role"):
                entities[idx]["role"] = user["role"]
        else:
            entities.append({
                "name": uname,
                "aliases": [],
                "route_hint": ["G"],
                "weight": 1.0,
                "role": user["role"],
                "source": "state/user_profile.md",
            })

    pending = _load_existing_pending()

    data = {
        "_meta": {
            "version": 1,
            "updated": datetime.now().strftime("%Y-%m-%d"),
            "source": "state/members/*.md, state/leaders.md, state/org.md",
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
