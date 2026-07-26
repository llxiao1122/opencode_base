def handle(name: str) -> str:
    from skills.router.entity_resolver import resolve_entities
    resolved = resolve_entities(name)
    entities = resolved.get("entities", [])
    if not entities:
        return f"[Cipher:profile]\n暂无 {name} 的记录。"
    e = entities[0]
    return f"[Cipher:profile]\n{name}: {e.get('role', '未知')}（{e.get('team', '')}）"
