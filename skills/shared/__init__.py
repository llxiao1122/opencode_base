"""
skills/shared/ — 共享工具集。

职责：entity 加载/角色查询、时间解析、路径管理。
所有核心模块共用此处工具，禁止各自实现相同功能。
"""

from .entity import (
    load_entities,
    get_role,
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
