"""
organization/model.py — Organization model (Phase 1.8)

Provides team member queries. Interface-based, internal dict implementation.
Later: load from state/org.md, state/entity_index.json dynamically.
"""


class OrganizationModel:
    """Organization structure with team member queries."""

    def __init__(self):
        self._teams = {
            "铁炉西工班": {
                "leader": "李林骁",
                "members": ["苗笑天", "张志斌", "谭继衡", "杨梦卓", "陈红洁"],
            },
        }

    def get_members(self, owner: str) -> list:
        """Return team member names for a given leader."""
        for team in self._teams.values():
            if team["leader"] == owner:
                return list(team["members"])
        return []

    def get_leader(self, member: str) -> str:
        """Find which leader a member reports to."""
        for team in self._teams.values():
            if member in team["members"]:
                return team["leader"]
        return ""

    def get_team_name(self, owner: str) -> str:
        """Return team name for a leader."""
        for name, team in self._teams.items():
            if team["leader"] == owner:
                return name
        return ""
