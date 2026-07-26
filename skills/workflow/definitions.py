"""Workflow definitions — declarative step sequences."""

WORKFLOWS = {
    "correction": {
        "trigger": "correction_detected",
        "steps": [
            {"skill": "correction_feedback", "user_facing": False, "timeout": 90},
            {"skill": "event_record", "user_facing": False, "timeout": 30},
            {"skill": "notification_push", "user_facing": True, "timeout": 30},
        ],
        "llm_summary": True,
        "llm_timeout": 15,
    },
}


def get(workflow_id: str) -> dict | None:
    return WORKFLOWS.get(workflow_id)


def list_triggers() -> dict[str, str]:
    return {v["trigger"]: k for k, v in WORKFLOWS.items()}
