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
