import logging

logger = logging.getLogger(__name__)


def handle(params: dict) -> str:
    summary = params.get("summary", "")
    time = params.get("time", "")
    people = params.get("people", "")
    detail = summary
    if time:
        detail += f"（时间: {time}）"
    if people:
        detail += f"（人员: {people}）"
    try:
        from skills.memory.observation_store import write as obs_write
        obs_write(detail, source="agent.event_record", obs_type="event", layer="rule")
    except Exception as e:
        logger.warning("event_record obs_write failed: %s", e, exc_info=True)
    return f"[Cipher:record]\n✅ 已记录：{summary}"
