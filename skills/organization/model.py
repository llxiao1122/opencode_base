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
    """Read entity_index.json to build team structure.

    SSOT: entity_index.json _meta.team_members defines the core team.
    Falls back to all entity_index names minus the leader.

    Returns: {team_name: {"leader": str, "members": list[str]}}
    """
    teams = {}
    data = {}

    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    # SSOT: team_members list from entity_index _meta
    known_team = set(data.get("_meta", {}).get("team_members", []))

    # Fallback: all confirmed_entities except the leader
    if not known_team:
        for e in data.get("confirmed_entities", []):
            known_team.add(e["name"])

    # Remove leader from members list
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
