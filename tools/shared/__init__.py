"""
tools/shared/ — Unified shared utilities (v2.1 refactor).

Single source of truth for: entity loading, role lookup, team map,
broadcast detection, and time/deadline parsing.

Previously duplicated across 8+ files (core/event.py, core/context.py,
pipeline/instruction_resolver.py, context/hierarchy_resolver.py,
organization/memory_bridge.py, profile/retriever.py, etc.).
"""

from .entity import (
    load_entities,
    get_role,
    get_team,
    get_team_leader,
    has_known_entity,
    find_entities_in_text,
    BROADCAST_WORDS,
    ASSIGN_WORDS,
)

from .time_parse import (
    WORK_START,
    WORK_END,
    WEEKDAY_MAP,
    parse_deadline_dt,
    calc_working_hours,
)

__all__ = [
    "load_entities",
    "get_role",
    "get_team",
    "get_team_leader",
    "has_known_entity",
    "find_entities_in_text",
    "BROADCAST_WORDS",
    "ASSIGN_WORDS",
    "WORK_START",
    "WORK_END",
    "WEEKDAY_MAP",
    "parse_deadline_dt",
    "calc_working_hours",
]
