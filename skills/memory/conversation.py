"""
会话历史存储，按 sender_id 维护最近 N 轮对话。
存储位置: data/memory/conversations/<sender_id>.json
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONV_DIR = ROOT / "data" / "memory" / "conversations"
MAX_ROUNDS = 20


def _ensure_dir():
    CONV_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(sender_id: str) -> str:
    return "".join(c for c in sender_id if c.isalnum() or c in "_-") or "unknown"


def _get_path(sender_id: str) -> Path:
    return CONV_DIR / f"{_safe_name(sender_id)}.json"


def add(sender_id: str, role: str, content: str):
    _ensure_dir()
    path = _get_path(sender_id)
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text())
        except Exception:
            pass
    content_clean = content.strip()
    if not content_clean:
        return
    history.append({
        "role": role,
        "content": content_clean,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    cap = MAX_ROUNDS * 2
    if len(history) > cap:
        history = history[-cap:]
    path.write_text(json.dumps(history, ensure_ascii=False))


def get_recent(sender_id: str, n: int = 20) -> list[dict]:
    _ensure_dir()
    path = _get_path(sender_id)
    if not path.exists():
        return []
    try:
        history = json.loads(path.read_text())
    except Exception:
        return []
    return history[-(n * 2):]


def format_for_llm(sender_id: str, n: int = 10) -> str:
    msgs = get_recent(sender_id, n)
    if not msgs:
        return ""
    lines = []
    for m in msgs:
        label = "主人" if m["role"] == "user" else "Cipher"
        lines.append(f"{label}: {m['content']}")
    return "\n".join(lines)


def clear(sender_id: str):
    _ensure_dir()
    path = _get_path(sender_id)
    if path.exists():
        path.unlink()
