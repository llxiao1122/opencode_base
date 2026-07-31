def handle(name: str) -> str:
    from skills.router.entity_resolver import resolve_entities
    resolved = resolve_entities(name)
    entities = resolved.get("entities", [])
    if not entities:
        return f"[Cipher:profile]\n暂无 {name} 的记录。"
    lines = []
    for e in entities:
        lines.append(f"{e['name']}: {e.get('role', '未知')}（{e.get('team', '')}）")
    return f"[Cipher:profile]\n" + "\n".join(lines)


def team_summary() -> str:
    """全成员档案摘要（deliver 推送'工班每个人'场景调用）。"""
    from skills.organization.model import OrganizationModel
    from skills.agent.handlers.profile_query import handle as profile_handle
    org = OrganizationModel()
    members = org.get_members("李林骁")
    out = ["【铁炉西工班成员】"]
    for m in (["李林骁"] + members):
        try:
            r2 = profile_handle(m)
            info = r2.replace("[Cipher:profile]\n", "").strip()
            out.append(f"  {info}")
        except Exception:
            out.append(f"  {m} — 查询失败")
    return "\n".join(out)
