import fcntl
import json
from pathlib import Path

from skills.shared.path import root as _root
ROOT = _root()
QUEUE_PATH = ROOT / "data" / "state" / "push_queue.json"


def _lock_rw():
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(QUEUE_PATH, "a+", encoding="utf-8")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def read() -> list:
    if not QUEUE_PATH.exists():
        return []
    f = _lock_rw()
    try:
        f.seek(0)
        return json.load(f)
    finally:
        f.close()


def write(queue: list):
    f = _lock_rw()
    try:
        f.seek(0)
        f.truncate()
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.flush()
    finally:
        f.close()


def append(item: dict):
    f = _lock_rw()
    try:
        f.seek(0)
        raw = f.read().strip()
        queue = json.loads(raw) if raw else []
        queue.append(item)
        f.seek(0)
        f.truncate()
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.flush()
    finally:
        f.close()
