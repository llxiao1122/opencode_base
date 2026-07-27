"""Workflow definitions — declarative step sequences with param extraction rules."""
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
