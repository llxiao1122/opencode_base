import json, uuid
from datetime import datetime, timedelta
from pathlib import Path
import portalocker

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
QUEUE_PATH = ROOT_DIR / "data" / "state" / "push_queue.json"


def handle(message: str, time: str = "") -> str:
    queue = _load()
    now = datetime.now()

    dt = _parse_time(time, now)
    if not dt:
        return "[Cipher:error]\n无法解析时间，请用格式：Y-m-d H:M 或相对时间如 1分钟后"

    queue.append({
        "id": uuid.uuid4().hex[:12],
        "channel": "dingtalk",
        "title": "⏰ 提醒",
        "body": message,
        "push_at": dt.isoformat(),
        "pushed": False,
    })
    _save(queue)

    until = dt - now
    mins = int(until.total_seconds() // 60)
    return f"[Cipher:task]\n✅ 已设提醒：{message}（{mins} 分钟后）"


def _load() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            portalocker.lock(f, portalocker.LOCK_SH)
            return json.load(f)
    except Exception:
        return []


def _save(data: list[dict]):
    tmp = Path(str(QUEUE_PATH) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(QUEUE_PATH, "a") as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        tmp.replace(QUEUE_PATH)


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
