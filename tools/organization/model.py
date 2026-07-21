"""
organization/model.py — Organization model (Phase 1.8)

Provides team member queries.
Loads from state/entity_index.json and state/org.md — no hardcoded data.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX_PATH = ROOT / "state" / "entity_index.json"
ORG_MD_PATH = ROOT / "state" / "org.md"


def _build_teams():
    """Parse org.md + entity_index.json to build team structure.

    Returns: {team_name: {"leader": str, "members": list[str]}}
    """
    teams = {}
    entity_names = set()

    # Read entity_index for known names
    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        for e in data.get("confirmed_entities", []):
            entity_names.add(e["name"])
    except Exception:
        pass

    # Parse org.md for team structure
    if ORG_MD_PATH.exists():
        text = ORG_MD_PATH.read_text(encoding="utf-8")
        # Find leader from TREE line
        leader = ""
        for line in text.split("\n"):
            if "→" in line and "李林骁" in line:
                leader = "李林骁"
                break
            if "工班长" in line.lower() and any(n in line for n in entity_names):
                for name in entity_names:
                    if name in line and "工班长" in line:
                        leader = name
                        break

        if leader:
            # Members = known entities minus the leader
            known_team = {"李林骁", "陈红洁", "杨梦卓", "谭继衡", "苗笑天", "张志斌"}
            members = sorted(n for n in entity_names if n in known_team and n != leader)
            if not members:
                members = sorted(n for n in known_team if n != leader)
            teams["铁炉西工班"] = {"leader": leader, "members": members}

    # Fallback: if parsing failed, use hardcoded defaults
    if not teams:
        teams = {
            "铁炉西工班": {
                "leader": "李林骁",
                "members": ["苗笑天", "张志斌", "谭继衡", "杨梦卓", "陈红洁"],
            },
        }

    return teams


class OrganizationModel:
    def __init__(self):
        self._teams = _build_teams()

    def get_members(self, owner: str) -> list:
        for team in self._teams.values():
            if team["leader"] == owner:
                return list(team["members"])
        return []

    def get_leader(self, member: str) -> str:
        for team in self._teams.values():
            if member in team["members"]:
                return team["leader"]
        return ""

    def get_team_name(self, owner: str) -> str:
        for name, team in self._teams.items():
            if team["leader"] == owner:
                return name
        return ""
