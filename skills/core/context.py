"""
core/context.py — Context Engine.

Answers: what does this event mean for me?

Input: Event + current user + organization data
Output: Context dict with my_position, required_action, reason, deadline_feasibility

ResponsibilityType enum:
    executor    — I am directly named to execute
    coordinator — notification targets group, I am the leader
    supervisor  — I assigned someone else, I oversee
    audience    — notification targets group, I am not leader
    observer    — pure information / announcement

Deadline feasibility:
    Checks working hours between now and deadline.
    Flags unreasonable deadlines (e.g. Friday after-hours notice → Monday 9am).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta, date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skills.shared import (
    BROADCAST_WORDS,
    ASSIGN_WORDS,
    parse_deadline_dt,
    calc_working_hours,
)

ROOT = Path(__file__).resolve().parent.parent.parent

MIN_WORKING_HOURS = 4  # below this: flag as unreasonable


def _check_deadline_feasibility(event: dict) -> dict:
    """Evaluate whether the deadline is achievable given current time."""
    deadline_str = event.get("time", {}).get("deadline", "")
    feasibility = {"feasible": True, "working_hours": None, "reason": ""}

    if not deadline_str:
        feasibility["reason"] = "无截止时间"
        return feasibility

    now = datetime.now()
    deadline = parse_deadline_dt(deadline_str, ref=now)

    if deadline is None:
        feasibility["reason"] = f"截止时间不可解析: {deadline_str}"
        return feasibility

    if deadline <= now:
        feasibility["feasible"] = False
        feasibility["reason"] = f"截止时间 {deadline_str} 已过期"
        return feasibility

    if deadline.weekday() >= 5:
        feasibility["feasible"] = False
        feasibility["reason"] = f"截止时间 {deadline_str} 落在周末，不可执行"
        return feasibility

    work_hours = calc_working_hours(now, deadline)
    feasibility["working_hours"] = work_hours

    if work_hours < MIN_WORKING_HOURS:
        feasibility["feasible"] = False
        feasibility["reason"] = (
            f"通知到截止仅 {work_hours:.1f} 工作小时（需 ≥{MIN_WORKING_HOURS}h），"
            f"扣除休息/跨班协调后不可执行，建议反馈调整截止时间"
        )
    elif work_hours < MIN_WORKING_HOURS * 2:
        feasibility["feasible"] = "tight"
        feasibility["reason"] = (
            f"通知到截止仅 {work_hours:.1f} 工作小时，时间紧张，优先处理"
        )
    else:
        feasibility["reason"] = f"通知到截止 {work_hours:.1f} 工作小时，可行"

    return feasibility


def resolve(event: dict, user: dict) -> dict:
    """Core resolution. Determines current user's position in this event.

    Returns Context dict:
        event_id, my_position {type, owner, description},
        required_action {verb, scope}, reason
    """
    ctx = {
        "event_id": event.get("id", ""),
        "my_position": {"type": "observer", "owner": "", "description": ""},
        "required_action": {"verb": "", "scope": ""},
        "reason": "",
        "deadline_feasibility": _check_deadline_feasibility(event),
    }

    if not event or not user:
        return ctx

    actors = event.get("actors", [])
    target = event.get("target", "")
    event_type = event.get("event_type", "unknown")
    raw = event.get("raw", "")
    user_name = user.get("name", "")
    user_role = user.get("role", "")
    user_team = user.get("team", "")

    requester = ""
    for a in actors:
        if a.get("position") == "requester":
            requester = a.get("name", "")

    is_target_person = user_name in str(target) or user_name in raw
    is_broadcast = _is_broadcast(target) or _is_broadcast(raw)
    is_leader = any(kw in user_role for kw in ["工班长", "主任", "负责人", "管理"])
    is_user_requester = requester == user_name

    # ── supervisor: I assigned someone else ──
    if is_user_requester:
        executor = _find_assigned_person(raw, user_name)
        if not executor:
            for a in actors:
                if a.get("position") == "executor" and a["name"] != user_name:
                    executor = a["name"]
                    break
        ctx["my_position"] = {
            "type": "supervisor",
            "owner": user_name,
            "description": f"指派 {executor or '他人'} 执行",
        }
        ctx["required_action"] = {"verb": "监督", "scope": executor or "执行人"}
        ctx["reason"] = f"{user_name} 指派 {executor or '他人'} 执行"

    # ── executor: I am directly named ──
    elif is_target_person and requester != user_name:
        ctx["my_position"] = {
            "type": "executor",
            "owner": user_name,
            "description": f"被 {requester or '上级'} 直接指派",
        }
        ctx["required_action"] = {"verb": "完成", "scope": str(target)}
        ctx["reason"] = f"{requester or '上级'} 直接通知 {user_name} 完成"

    # ── coordinator: group notification + I am leader ──
    elif is_broadcast and is_leader:
        team_scope = f"{user_team}员工" if user_team else "所属人员"
        ctx["my_position"] = {
            "type": "coordinator",
            "owner": user_name,
            "description": f"{user_role}，负责落实本{user_team or '班组'}",
        }
        ctx["required_action"] = {"verb": "督促", "scope": team_scope}
        ctx["reason"] = f"{requester or '上级'} 通知各班组，{user_name} 为 {user_team or '工班'} {user_role}"

    # ── audience: group notification + I am not leader ──
    elif is_broadcast and not is_leader:
        ctx["my_position"] = {
            "type": "audience",
            "owner": user_name,
            "description": f"作为 {user_role} 收到群体通知，由工班长负责落实",
        }
        ctx["required_action"] = {"verb": "关注", "scope": "相关要求"}
        ctx["reason"] = f"群体通知面向各班组，{user_name} 非负责人"

    # ── observer: pure information ──
    else:
        ctx["my_position"] = {
            "type": "observer",
            "owner": user_name,
            "description": "信息接收，无直接行动要求",
        }

    return ctx


def _is_broadcast(text_or_list) -> bool:
    if isinstance(text_or_list, list):
        text_or_list = " ".join(text_or_list)
    text_str = str(text_or_list)
    return any(w in text_str for w in BROADCAST_WORDS)


def _find_assigned_person(text: str, assigner: str) -> str:
    """Find who the assigner is assigning to: '李林骁通知苗笑天' → 苗笑天"""
    import re
    for assign in ASSIGN_WORDS:
        prefix = assigner + assign
        idx = text.find(prefix)
        if idx < 0:
            continue
        after = text[idx + len(prefix):].lstrip()
        # Take the first 2-3 Chinese chars as the person name
        m = re.match(r"([\u4e00-\u9fff]{2,3})", after)
        if m:
            name = m.group(1)
            if name != assigner:
                return name
    return ""


def load_user() -> dict:
    """Load current user from entity_index.json."""
    try:
        idx = json.loads((ROOT / "state" / "entity_index.json").read_text(encoding="utf-8"))
        for e in idx.get("confirmed_entities", []):
            if e["name"] == "李林骁":
                return {"name": "李林骁", "role": e.get("role", "工班长"), "team": e.get("team", "铁炉西工班")}
    except Exception:
        pass
    return {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
