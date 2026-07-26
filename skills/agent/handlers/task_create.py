def handle(summary: str, deadline: str = "", assignee: str = "") -> str:
    from skills.organization.model import OrganizationModel
    from skills.task.manager import TaskManager

    org = OrganizationModel()
    tm = TaskManager(org)

    event = {
        "id": "",
        "event_type": "instruction",
        "time": {"deadline": deadline},
        "source": "agent",
        "actors": [{"name": assignee, "role": "", "position": "executor"}] if assignee else [],
        "action": {"type": "task", "summary": summary},
        "target": assignee or "",
        "confidence": 0.8,
        "raw": summary,
    }
    context = {
        "my_position": {"type": "executor", "owner": "李林骁"},
        "required_action": {"verb": "完成", "scope": summary},
        "reason": "Agent 创建任务",
    }
    user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
    task = tm.create(event, context, user)
    return f"[Cipher:task]\n✅ 任务已创建：{summary}"
