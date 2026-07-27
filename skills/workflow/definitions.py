"""
skills/workflow/definitions.py — Workflow 步骤定义。

每个 Step 包含：
  - skill_id: 要调用的工具名
  - params:   参数字典，支持 "input"（用户原文）、"input[:N]"（截断）、字面量
  - on_success / on_failure: 条件跳转（预留）

list_triggers() 返回关键词 → workflow_id 的映射，
供 entry.py _should_route_to_workflow 使用。
"""
from __future__ import annotations

WORKFLOWS = {
    "correction": {
        "trigger": "correction_detected",
        "steps": [
            {
                "skill": "correction_feedback",
                "user_facing": False,
                "timeout": 90,
                "params": {"content": "input", "context": ""},
            },
            {
                "skill": "event_record",
                "user_facing": False,
                "timeout": 30,
                "params": {"summary": "input", "time": ""},
            },
            {
                "skill": "notification_push",
                "user_facing": True,
                "timeout": 30,
                "params": {"title": "Cipher 处理结果", "content": "input[:200]"},
            },
        ],
        "llm_summary": True,
        "llm_timeout": 15,
    },
}


def get(workflow_id: str) -> dict | None:
    return WORKFLOWS.get(workflow_id)


def list_triggers() -> dict[str, str]:
    return {v["trigger"]: k for k, v in WORKFLOWS.items()}
