"""
core/task.py — Task generation from Context.

Generates actionable tasks from Context.
No LLM — pure templates based on my_position.type.

Output Task dict:
    id, owner, executors, responsibility, action, deadline
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX = ROOT / "state" / "entity_index.json"

_TEAM_MAP = {
    "李林骁": "铁炉西工班",
    "陈红洁": "铁炉西工班",
    "杨梦卓": "铁炉西工班",
    "谭继衡": "铁炉西工班",
    "苗笑天": "铁炉西工班",
    "张志斌": "铁炉西工班",
}

ACTION_TEMPLATES = {
    "coordinator": {
        "action_tpl": "督促{scope}完成{summary}",
    },
    "executor": {
        "action_tpl": "本人完成{summary}",
    },
    "supervisor": {
        "action_tpl": "监督{scope}完成{summary}",
    },
    "audience": {
        "action_tpl": "关注{summary}进展",
    },
    "observer": {
        "action_tpl": "了解{summary}",
    },
}


def generate(ctx: dict) -> dict:
    """Generate task from context.

    Args:
        ctx: Context dict from core/context.py

    Returns Task dict:
        id, owner, executors[], responsibility, action, deadline
    """
    pos = ctx.get("my_position", {})
    req = ctx.get("required_action", {})
    pos_type = pos.get("type", "observer")
    owner = pos.get("owner", "")
    scope = req.get("scope", "")
    event_id = ctx.get("event_id", "")

    task = {
        "id": f"task_{event_id}" if event_id else "task_unknown",
        "owner": owner,
        "executors": [],
        "responsibility": pos_type,
        "action": "",
        "deadline": "",
    }

    tpl = ACTION_TEMPLATES.get(pos_type, ACTION_TEMPLATES["observer"])

    if pos_type == "coordinator":
        task["executors"] = _get_team_members(owner)
        task["action"] = tpl["action_tpl"].format(scope=scope or "所属人员", summary="相关任务")

    elif pos_type == "executor":
        task["executors"] = [owner] if owner else []
        task["action"] = tpl["action_tpl"].format(summary="相关任务")

    elif pos_type == "supervisor":
        task["executors"] = [scope] if scope else []
        task["action"] = tpl["action_tpl"].format(scope=scope or "执行人", summary="相关任务")

    elif pos_type == "audience":
        task["action"] = tpl["action_tpl"].format(summary="相关要求")

    else:
        task["action"] = tpl["action_tpl"].format(summary="相关信息")

    return task


def _get_team_members(leader_name: str) -> list:
    """Get all team members for a given leader."""
    team = _TEAM_MAP.get(leader_name, "")
    if not team:
        return []
    return [name for name, t in _TEAM_MAP.items() if t == team and name != leader_name]
