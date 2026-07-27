"""
agent/registry.py — Skills Registry + 参数校验 + 动态导入 handler.

Phase 3: Agentic Pipeline. Refactored: declarative param map, no if/elif chain.
"""

import importlib, logging
from pathlib import Path
from typing import Optional

from skills.shared.path import ensure_paths, root as _root
from skills.shared.schema import RequestContext
from skills.shared.entity import resolve_user

ensure_paths()

logger = logging.getLogger(__name__)

ROOT = _root()


TOOL_REGISTRY = {
    "task_query": {
        "description": "查询今日/本周/本月工作安排、待办事项、任务列表",
        "params_schema": {
            "scope": {"type": "str", "required": False, "default": "today",
                      "description": "today|tomorrow|week|month"},
        },
        "handler": "skills.agent.handlers.task_query:handle",
        "param_map": {"user_input": "scope", "ctx": None},
    },
    "knowledge_retrieve": {
        "description": "查询制度/流程/规范/操作规程等知识库内容",
        "params_schema": {
            "topic": {"type": "str", "required": True,
                      "description": "查询主题，如灭火器更换周期"},
        },
        "handler": "skills.agent.handlers.knowledge_retrieve:handle",
        "param_map": {"user_input": "topic", "ctx": None},
    },
    "profile_query": {
        "description": "查询某位人员的工作画像、能力评价、岗位信息",
        "params_schema": {
            "name": {"type": "str", "required": True,
                     "description": "人员姓名"},
        },
        "handler": "skills.agent.handlers.profile_query:handle",
        "param_map": {"name": "name", "ctx": None},
    },
    "notification_push": {
        "description": "推送通知消息到钉钉群，用于安全宣贯、通知下达",
        "params_schema": {
            "title": {"type": "str", "required": True},
            "content": {"type": "str", "required": True},
            "target": {"type": "str", "required": False, "default": "dingtalk_group"},
        },
        "handler": "skills.agent.handlers.notification:handle",
        "param_map": {"title": "title", "content": "content"},
    },
    "event_record": {
        "description": "记录一条事件信息，包含时间、人员、动作，用于任务创建或日常记录",
        "params_schema": {
            "summary": {"type": "str", "required": True},
            "time": {"type": "str", "required": False},
            "people": {"type": "str", "required": False},
        },
        "handler": "skills.agent.handlers.event_record:handle",
        "param_map": None,
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
        "handler": "skills.agent.handlers.task_create:handle",
        "param_map": {"summary": "summary", "deadline": "deadline", "assignee": "assignee"},
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
        "handler": "skills.agent.handlers.task_feedback:handle",
        "param_map": {"action": "action", "executor": "executor", "task_id": "task_id"},
    },
    "org_lookup": {
        "description": "查询组织关系、班组结构、人员上下级",
        "params_schema": {
            "name": {"type": "str", "required": True,
                     "description": "人员姓名"},
        },
        "handler": "skills.agent.handlers.org_lookup:handle",
        "param_map": {"name": "name"},
    },
    "correction_feedback": {
        "description": "纠正错误信息：用户发现Cipher回答有误时，提交纠正内容写入知识库",
        "params_schema": {
            "content": {"type": "str", "required": True,
                        "description": "纠正的内容/正确信息"},
            "context": {"type": "str", "required": False,
                        "description": "此纠正涉及的主题或上下文"},
        },
        "handler": "skills.agent.handlers.correction_feedback:handle",
        "param_map": {"content": "content", "context": "context"},
    },
}


_SPECIAL_SCOPE_MAP = {
    "today": "今天任务",
    "tomorrow": "明天任务",
    "week": "本周任务",
    "month": "本月任务",
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


def _clean_params(params: dict) -> dict:
    """防御：LLM 有时返回 schema 对象而非实际值"""
    cleaned = {}
    for k, v in params.items():
        if isinstance(v, dict):
            cleaned[k] = v.get("default", v.get("description", ""))
        else:
            cleaned[k] = v
    return cleaned


def _apply_param_map(tool_id: str, params: dict, ctx: Optional[RequestContext] = None):
    """Unified parameter extraction: param_map declares (handler_arg → params_key) mapping.
    A value of None means inject ctx."""
    tool = TOOL_REGISTRY.get(tool_id)
    if not tool:
        return []
    pmap = tool.get("param_map")
    if pmap is None:
        return [params]
    args = []
    for handler_key, source_key in pmap.items():
        if source_key is None:
            args.append(ctx)
        elif source_key == "scope" or (source_key == "user_input" and "scope" in params):
            raw = params.get("scope", "today")
            args.append(_SPECIAL_SCOPE_MAP.get(raw, raw))
        elif source_key == "params":
            args.append(params)
        else:
            args.append(params.get(source_key, params.get("user_input", params.get(source_key, ""))))
    return args


def execute(tool_id: str, params: dict, ctx: Optional[RequestContext] = None) -> str:
    tool = TOOL_REGISTRY.get(tool_id)
    if not tool:
        logger.warning("execute called with unknown tool '%s'", tool_id)
        return f"[Cipher:error]\n未知工具: {tool_id}"

    mod_path, func_name = tool["handler"].split(":")
    try:
        mod = importlib.import_module(mod_path)
    except Exception as e:
        logger.error("cannot import handler module %s: %s", mod_path, e, exc_info=True)
        return f"[Cipher:error]\n工具加载失败: {tool_id}"
    handler = getattr(mod, func_name)

    if ctx is None:
        ctx = RequestContext(message="")
        ctx.user = resolve_user()

    params = _clean_params(params)
    args = _apply_param_map(tool_id, params, ctx)
    result = handler(*args)
    return str(result).strip() if result else ""
