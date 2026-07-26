def handle(name: str) -> str:
    try:
        from skills.router.entity_resolver import resolve_entities
        resolved = resolve_entities(name)
        if resolved.get("entities"):
            info = resolved["entities"][0]
            return f"[Cipher:profile]\n{info.get('name', name)}: {info.get('role', '未知')}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("profile_query failed: %s", e, exc_info=True)
    return f"[Cipher:profile]\n暂无 {name} 的相关记录。"
