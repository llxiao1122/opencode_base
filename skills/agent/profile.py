"""
agent/skills/profile.py — 人员画像查询 Skill。

包装 entity_resolver + user_retriever。
"""


def handle(name: str) -> str:
    try:
        from skills.routing.entity_resolver import resolve_entities
        resolved = resolve_entities(name)
        if resolved.get("entities"):
            info = resolved["entities"][0]
            return f"[Cipher:profile]\n{info.get('name', name)}: {info.get('role', '未知')}"
    except Exception:
        pass
    return f"[Cipher:profile]\n暂无 {name} 的相关记录。"
