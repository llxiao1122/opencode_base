"""
agent/registry.py — Skills Registry + 参数校验 + 动态导入 handler.

Phase 3: Agentic Pipeline.
"""

import importlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

_TOOL_PARAM_MAP = {
    "task_query": {
        "msg": lambda p, ctx: {"today": "今天任务", "tomorrow": "明天任务",
                                "week": "本周任务", "month": "本月任务"}.get(
            p.get("scope", "today"), p.get("scope", "today")),
        "ctx": lambda p, ctx: ctx,
    },
    "knowledge_retrieve": {
        "topic": lambda p, ctx: p["topic"],
        "ctx": lambda p, ctx: ctx,
    },
    "profile_query": {
        "name": lambda p, ctx: p["name"],
    },
}

TOOL_REGISTRY = {
    "task_query": {
        "description": "查询今日/本周/本月工作安排、待办事项、任务列表",
        "params_schema": {
            "scope": {"type": "str", "required": False, "default": "today",
                      "description": "today|tomorrow|week|month"},
        },
        "handler": "skills.routing.task_handler:handle",
    },
    "knowledge_retrieve": {
        "description": "查询制度/流程/规范/操作规程等知识库内容",
        "params_schema": {
            "topic": {"type": "str", "required": True,
                      "description": "查询主题，如灭火器更换周期"},
        },
        "handler": "skills.routing.knowledge_handler:handle",
    },
    "profile_query": {
        "description": "查询某位人员的工作画像、能力评价、岗位信息",
        "params_schema": {
            "name": {"type": "str", "required": True,
                     "description": "人员姓名"},
        },
        "handler": "skills.agent.skills.profile:handle",
    },
    "notification_push": {
        "description": "推送通知消息到钉钉群，用于安全宣贯、通知下达",
        "params_schema": {
            "title": {"type": "str", "required": True},
            "content": {"type": "str", "required": True},
            "target": {"type": "str", "required": False, "default": "dingtalk_group"},
        },
        "handler": "skills.agent.skills.notification:handle",
    },
    "event_record": {
        "description": "记录一条事件信息，包含时间、人员、动作，用于任务创建或日常记录",
        "params_schema": {
            "summary": {"type": "str", "required": True},
            "time": {"type": "str", "required": False},
            "people": {"type": "str", "required": False},
        },
        "handler": "skills.agent.skills.event_record:handle",
    },
    "task_create": {
        "description": "从事件信息创建任务/待办事项",
        "params_schema": {
            "summary": {"type": "str", "required": True,
                        "description": "任务摘要"},
            "deadline": {"type": "str", "required": False,
                         "description": "截止时间"},
            "assignee": {"type": "str", "required": False,
                         "description": "执行人"},
        },
        "handler": "skills.agent.skills.task_create:handle",
    },
    "task_feedback": {
        "description": "反馈任务完成状态，标记完成/取消",
        "params_schema": {
            "action": {"type": "str", "required": True,
                       "description": "完成描述"},
            "executor": {"type": "str", "required": True,
                         "description": "执行人姓名"},
            "task_id": {"type": "str", "required": False,
                        "description": "任务ID"},
        },
        "handler": "skills.agent.skills.task_feedback:handle",
    },
    "org_lookup": {
        "description": "查询组织关系、班组结构、人员上下级",
        "params_schema": {
            "name": {"type": "str", "required": True,
                     "description": "人员姓名"},
        },
        "handler": "skills.agent.skills.org_lookup:handle",
    },
}


def list_tools() -> list[dict]:
    return [
        {"id": tid, "description": t["description"],
         "params": {k: v for k, v in t["params_schema"].items()}}
        for tid, t in TOOL_REGISTRY.items()
    ]


def validate_params(tool_id: str, params: dict) -> tuple[bool, str]:
    tool = TOOL_REGISTRY.get(tool_id)
    if not tool:
        return False, f"tool '{tool_id}' 未注册"
    schema = tool["params_schema"]
    for key, rule in schema.items():
        if rule.get("required", False) and key not in params:
            return False, f"缺少必要参数: {key}"
    return True, ""


def _default_ctx():
    from skills.shared.schema import RequestContext
    ctx = RequestContext(message="")
    try:
        idx = json.loads((ROOT / "state" / "entity_index.json").read_text(encoding="utf-8"))
        for e in idx.get("confirmed_entities", []):
            if e["name"] == "李林骁":
                ctx.user = {"name": "李林骁", "role": e.get("role", "工班长"),
                            "team": e.get("team", "铁炉西工班")}
                break
    except Exception:
        ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
    return ctx


def _clean_params(params: dict) -> dict:
    """防御：LLM 有时返回 schema 对象而非实际值"""
    cleaned = {}
    for k, v in params.items():
        if isinstance(v, dict):
            cleaned[k] = v.get("default", v.get("description", ""))
        else:
            cleaned[k] = v
    return cleaned


def execute(tool_id: str, params: dict) -> str:
    tool = TOOL_REGISTRY.get(tool_id)
    if not tool:
        return f"[Cipher:error]\n未知工具: {tool_id}"

    mod_path, func_name = tool["handler"].split(":")
    mod = importlib.import_module(mod_path)
    handler = getattr(mod, func_name)

    ctx = _default_ctx()
    params = _clean_params(params)

    if tool_id in _TOOL_PARAM_MAP:
        mapping = _TOOL_PARAM_MAP[tool_id]
        args = []
        for key in ["msg", "topic", "name", "title", "summary", "action"]:
            if key in mapping:
                args.append(mapping[key](params, ctx))
        for key in ["ctx", "context"]:
            if key in mapping:
                args.append(mapping[key](params, ctx))
        result = handler(*args)
    elif tool_id == "notification_push":
        result = handler(params.get("title", ""), params.get("content", ""))
    elif tool_id == "event_record":
        result = handler(params)
    elif tool_id == "task_create":
        result = handler(
            params.get("summary", ""),
            params.get("deadline", ""),
            params.get("assignee", ""),
        )
    elif tool_id == "task_feedback":
        result = handler(
            params.get("action", ""),
            params.get("executor", ""),
            params.get("task_id", ""),
        )
    elif tool_id == "org_lookup":
        result = handler(params.get("name", ""))
    else:
        result = handler(**params)

    return str(result).strip() if result else ""
