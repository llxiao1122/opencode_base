import json, uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
REMINDERS_PATH = ROOT_DIR / "data" / "state" / "reminders.json"


def handle(message: str, time: str = "") -> str:
    reminders = _load()
    now = datetime.now()

    dt = _parse_time(time, now)
    if not dt:
        return "[Cipher:error]\n无法解析时间，请用格式：Y-m-d H:M 或相对时间如 1分钟后"

    reminder = {
        "id": uuid.uuid4().hex[:12],
        "message": message,
        "time_iso": dt.isoformat(),
        "pushed": False,
        "created_at": now.isoformat(),
    }
    reminders.append(reminder)
    _save(reminders)

    until = dt - now
    mins = int(until.total_seconds() // 60)
    return f"[Cipher:task]\n✅ 已设提醒：{message}（{mins} 分钟后）"


def _load() -> list[dict]:
    if not REMINDERS_PATH.exists():
        return []
    try:
        return json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(data: list[dict]):
    REMINDERS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
