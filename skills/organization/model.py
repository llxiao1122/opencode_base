"""
organization/model.py — Organization model (Phase 1.8)

Provides team member queries.
Loads from state/entity_index.json and state/team_work.json.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX_PATH = ROOT / "state" / "entity_index.json"
TEAM_WORK_PATH = ROOT / "state" / "team_work.json"


def _build_teams():
    """Read team_work.json + entity_index.json to build team structure.

    Returns: {team_name: {"leader": str, "members": list[str]}}
    """
    teams = {}

    # Read entity_index for known names
    entity_names = set()
    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        for e in data.get("confirmed_entities", []):
            entity_names.add(e["name"])
    except Exception:
        pass

    # Read roles from team_work.json to find known team members
    known_team_members = set()
    try:
        tw = json.loads(TEAM_WORK_PATH.read_text(encoding="utf-8"))
        for r in tw.get("roles", []):
            known_team_members.add(r["name"])
    except Exception:
        pass

    # Default team membership (org.md TREE was "李林骁→5保管")
    known_team = {"李林骁", "陈红洁", "杨梦卓", "谭继衡", "苗笑天", "张志斌"}
    if known_team_members:
        known_team.update(known_team_members)

    members = sorted(n for n in entity_names if n in known_team and n != "李林骁")
    if not members:
        members = sorted(n for n in known_team if n != "李林骁")

    teams["铁炉西工班"] = {"leader": "李林骁", "members": members}
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
