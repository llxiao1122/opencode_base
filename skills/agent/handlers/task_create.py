def handle(summary: str, deadline: str = "", assignee: str = "",
           ctx=None) -> str:
    from skills.organization.model import OrganizationModel
    from skills.task.manager import TaskManager

    org = OrganizationModel()
    tm = TaskManager(org)

    owner_name = (ctx.user or {}).get("name", "李林骁")
    owner_role = (ctx.user or {}).get("role", "工班长")
    owner_team = (ctx.user or {}).get("team", "铁炉西工班")

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
        "my_position": {"type": "executor", "owner": owner_name},
        "required_action": {"verb": "完成", "scope": summary},
        "reason": "Agent 创建任务",
    }
    user = {"name": owner_name, "role": owner_role, "team": owner_team}
    task = tm.create(event, context, user)
    if not task or not task.get("id"):
        return f"[Cipher:error]\n任务创建失败"
    return f"[Cipher:task]\n✅ 任务已创建：{summary}"
