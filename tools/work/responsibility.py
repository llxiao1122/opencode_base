"""
responsibility.py — 责任解析器
判断：这个事件和个人是什么关系？
三级输出：direct_task / role_task / team_attention / ignored
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_FILE = ROOT / "state" / "user_profile.md"
sys.path.insert(0, str(ROOT / "tools"))


def _load_profile():
    if not PROFILE_FILE.exists():
        return {}
    profile = {}
    content = PROFILE_FILE.read_text(encoding="utf-8")
    for line in content.split("\n"):
        m = re.match(r"\s*(name|role|team):\s*(.+)", line)
        if m:
            profile[m.group(1)] = m.group(2).strip()
    return profile


def _has_action_target(data):
    tasks = data.get("tasks", [])
    actions_text = " ".join(a for t in tasks for a in t.get("actions", []))
    constraints_text = " ".join(data.get("constraints", []))

    manager_actions = {"安排", "协调", "通知", "催促", "部署", "分配", "汇总", "跟踪"}
    exec_actions = {"完成", "清空", "执行", "接收", "暂停", "回收", "处置", "清运"}

    has_manager = any(v in actions_text for v in manager_actions)
    has_exec = any(v in actions_text for v in exec_actions)

    return has_manager, has_exec


def resolve(event_context, user_profile=None):
    if user_profile is None:
        user_profile = _load_profile()

    if not user_profile or not event_context:
        return {"direct_task": [], "role_task": [], "team_attention": []}

    user_name = user_profile.get("name", "")
    user_role = user_profile.get("role", "")
    user_team = user_profile.get("team", "")

    people = event_context.get("people", {})
    owners = people.get("owner", []) if isinstance(people, dict) else []
    executors = people.get("executors", []) if isinstance(people, dict) else []
    report_to = people.get("report_to", []) if isinstance(people, dict) else []

    result = {"direct_task": [], "role_task": [], "team_attention": []}

    # 1. direct_task: 明确点名
    if user_name and user_name in owners:
        result["direct_task"].append({
            "event": event_context.get("title", ""),
            "deadline": event_context.get("time", {}).get("deadline", ""),
            "why": f"明确负责人: {user_name}",
        })
        return result

    if user_name and user_name in executors:
        result["direct_task"].append({
            "event": event_context.get("title", ""),
            "deadline": event_context.get("time", {}).get("deadline", ""),
            "why": f"明确执行人: {user_name}",
        })
        return result

    # 2. role_task: 岗位匹配 + action_target 分析
    if user_role:
        has_manager, has_exec = _has_action_target(event_context)
        exec_text = " ".join(executors)

        role_hit = user_role in exec_text
        role_by_inference = (
            "工班长" in exec_text
            or ("各工班" in exec_text and "工班长" in user_role)
            or ("各库区" in exec_text and "工班长" in user_role)
        )

        if role_hit or role_by_inference:
            if has_manager:
                result["role_task"].append({
                    "event": event_context.get("title", ""),
                    "deadline": event_context.get("time", {}).get("deadline", ""),
                    "why": f"岗位({user_role})匹配: 需协调安排，非亲自执行",
                    "report_to": report_to,
                })
            elif has_exec:
                result["role_task"].append({
                    "event": event_context.get("title", ""),
                    "deadline": event_context.get("time", {}).get("deadline", ""),
                    "why": f"岗位({user_role})匹配: 需要关注执行进度",
                    "report_to": report_to,
                })
            else:
                result["role_task"].append({
                    "event": event_context.get("title", ""),
                    "deadline": event_context.get("time", {}).get("deadline", ""),
                    "why": f"岗位({user_role})匹配",
                    "report_to": report_to,
                })

    # 3. team_attention: 团队影响（与 role_task 可共存，不同维度）
    if user_team:
        generic_execs = {"各工班", "各工班长", "各库区", "全体人员", "所有工班"}
        team_hit = generic_execs & set(executors)
        team_name_hit = user_team in " ".join(executors)
        if team_hit or team_name_hit:
            result["team_attention"].append({
                "event": event_context.get("title", ""),
                "deadline": event_context.get("time", {}).get("deadline", ""),
                "why": f"涉及团队({user_team}): 集体执行事项",
                "report_to": report_to,
                "note": f"不是你的个人任务，而是{user_team}受到该事项影响",
            })

    return result
