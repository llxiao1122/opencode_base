"""
organization/model.py — Organization model (V4.2+ worldview SSOT)

Provides team member queries.
Loads from worldview entities/*.md (工班成员 flag).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITIES_DIR = ROOT / "data" / "state" / "worldview" / "entities"


def _load_team_members() -> set[str]:
    """Scan worldview entities/*.md for persons flagged as team members."""
    members = set()
    if not ENTITIES_DIR.exists():
        return members
    for f in sorted(ENTITIES_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        if "**工班成员**: true" in content or "**工班成员**: true" in content:
            members.add(f.stem)
    return members


def _build_teams():
    """Build team structure from worldview entity files.

    SSOT: entities/*.md — person files with `工班成员: true` flag.

    Returns: {team_name: {"leader": str, "members": list[str]}}
    """
    known_team = _load_team_members()
    members = sorted(n for n in known_team if n != "李林骁")
    return {"铁炉西工班": {"leader": "李林骁", "members": members}}


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
