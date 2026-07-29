import logging

logger = logging.getLogger(__name__)


def handle(params: dict) -> str:
    summary = params.get("summary", "")
    if not summary:
        return "[Cipher:error]\n缺少事件摘要"
    time = params.get("time", "")
    people = params.get("people", "")
    detail = summary
    if time and people:
        detail += f"（时间: {time}）（人员: {people}）"
    elif time:
        detail += f"（时间: {time}）"
    elif people:
        detail += f"（人员: {people}）"
    try:
        from skills.memory.recorder import record
        record(detail, source="agent.event_record", obs_type="event", layer="rule")
    except Exception as e:
        logger.warning("event_record obs_write failed: %s", e, exc_info=True)
    return f"[Cipher:record]\n✅ 已记录：{summary}"
