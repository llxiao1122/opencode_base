import logging

logger = logging.getLogger(__name__)


def handle(title: str, content: str) -> str:
    import os
    if not os.environ.get("DINGTALK_BOT_TOKEN", ""):
        return "[Cipher:notification]\n⚠ 钉钉未配置（DINGTALK_BOT_TOKEN 为空），通知已记录。"
    from skills.plugins.dingbot.send_msg import send_markdown
    result = send_markdown(title, content)
    if result.get("errcode") != 0:
        return f"[Cipher:error]\n钉钉推送失败: {result.get('errmsg', '')}"
    try:
        from skills.memory.recorder import record
    except ImportError as e:
        logger.warning("cannot import memory.recorder: %s", e)
    else:
        try:
            record(
                f"通知推送: {title}\n{content[:200]}",
                source="agent.notification", obs_type="notification", layer="rule",
            )
        except Exception as e:
            logger.warning("notification record failed: %s", e, exc_info=True)
    return "[Cipher:notification]\n✅ 已推送到钉钉群"
