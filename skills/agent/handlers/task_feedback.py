def handle(action: str, executor: str, task_id: str = "") -> str:
    from skills.organization.model import OrganizationModel
    from skills.task.manager import TaskManager

    org = OrganizationModel()
    tm = TaskManager(org)

    event = {
        "event_type": "feedback",
        "action": {"summary": action},
        "actors": [{"name": executor, "role": "", "position": "executor"}],
        "raw": action,
    }
    result = tm.update_from_event(event)
    if task_id and result.get("task_id"):
        result["task_id"] = task_id
    if result.get("matched"):
        return f"[Cipher:task]\n✅ {executor} 已完成：{action}"
    return f"[Cipher:task]\n📝 收到反馈：{executor} — {action}"
