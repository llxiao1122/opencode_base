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
    },
    "task_query": {
        "trigger": "task_query",
        "steps": [
            {
                "skill": "task_query",
                "user_facing": True,
                "timeout": 20,
                "params": {"scope": "input"},
            },
        ],
    },
    "knowledge_retrieve": {
        "trigger": "knowledge_retrieve",
        "steps": [
            {
                "skill": "knowledge_retrieve",
                "user_facing": True,
                "timeout": 20,
                "params": {"topic": "input"},
            },
        ],
    },
    "profile_query": {
        "trigger": "profile_query",
        "steps": [
            {
                "skill": "profile_query",
                "user_facing": True,
                "timeout": 20,
                "params": {"name": "input", "ctx": None},
            },
        ],
    },
}


def get(workflow_id: str) -> dict | None:
    return WORKFLOWS.get(workflow_id)


def list_triggers() -> dict[str, str]:
    return {v["trigger"]: k for k, v in WORKFLOWS.items()}


def register(workflow_id: str, definition: dict) -> None:
    WORKFLOWS[workflow_id] = definition
