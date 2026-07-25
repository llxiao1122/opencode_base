"""
agent/skills/notification.py — 钉钉推送 Skill。

发钉钉 + 写 observation + 返回结果。
"""


def handle(title: str, content: str) -> str:
    from skills.plugins.dingbot.send_msg import send_markdown
    result = send_markdown(title, content)
    if result.get("errcode") != 0:
        return f"[Cipher:error]\n钉钉推送失败: {result.get('errmsg', '')}"
    try:
        from skills.memory.observation_store import write as obs_write
        obs_write(
            f"通知推送: {title}\n{content[:200]}",
            source="agent.notification", obs_type="notification", layer="rule",
        )
    except Exception:
        pass
    return "[Cipher:notification]\n✅ 已推送到钉钉群"
