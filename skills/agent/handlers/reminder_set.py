import uuid
from datetime import datetime, timedelta


def handle(message: str, time: str = "") -> str:
    from skills.shared.push_queue import append as queue_append
    now = datetime.now()

    dt = _parse_time(time, now)
    if not dt:
        return "[Cipher:error]\n无法解析时间，请用格式：Y-m-d H:M 或相对时间如 1分钟后"

    queue_append({
        "id": uuid.uuid4().hex[:12],
        "channel": "dingtalk",
        "title": "⏰ 提醒",
        "body": message,
        "push_at": dt.isoformat(),
        "pushed": False,
    })

    until = dt - now
    mins = int(until.total_seconds() // 60)
    try:
        from skills.memory.recorder import record
        record(f"设置提醒: {message}（{mins}分钟后）", source="reminder", obs_type="event", layer="rule")
    except Exception:
        pass
    return f"[Cipher:task]\n✅ 已设提醒：{message}（{mins} 分钟后）"


def _parse_time(text: str, now: datetime) -> datetime | None:
    text = text.strip()
    if not text:
        return None

    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        pass

    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M")
    except ValueError:
        pass

    m = __import__("re").match(r"(\d+)\s*分(钟)?(后)?", text)
    if m:
        return now + timedelta(minutes=int(m.group(1)))

    m = __import__("re").match(r"(\d+)\s*小(时)?(后)?", text)
    if m:
        return now + timedelta(hours=int(m.group(1)))

    return None
