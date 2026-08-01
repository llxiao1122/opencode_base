"""
skills/shared/confirm_queue.py — Human-in-the-loop 确认队列。

confirm 类工具（task_create/notification_push/correction_feedback）执行前
生成"建议"入本队列；钉钉推送"待主人确认"；主人回复确认词后执行。

存储：data/state/confirm_queue.json（fcntl 文件锁，与 push_queue 同模式）。
条目：{id, tool, params, summary, created_at, confirmed, executed}
"""

import fcntl
import json
import uuid
from datetime import datetime
from pathlib import Path

from skills.shared.path import root as _root
ROOT = _root()
QUEUE_PATH = ROOT / "data" / "state" / "confirm_queue.json"


def _lock_rw():
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(QUEUE_PATH, "a+", encoding="utf-8")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def _read(f) -> list:
    f.seek(0)
    raw = f.read().strip()
    try:
        return json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []


def propose(tool: str, params: dict, summary: str = "") -> dict:
    """生成待确认建议，返回条目。"""
    item = {
        "id": uuid.uuid4().hex[:12],
        "tool": tool,
        "params": params,
        "summary": summary or f"{tool}",
        "created_at": datetime.now().isoformat(),
        "confirmed": False,
        "executed": False,
    }
    f = _lock_rw()
    try:
        queue = _read(f)
        queue.append(item)
        f.seek(0)
        f.truncate()
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.flush()
    finally:
        f.close()
    return item


def pending() -> list:
    if not QUEUE_PATH.exists():
        return []
    f = _lock_rw()
    try:
        queue = _read(f)
        return [q for q in queue if not q.get("confirmed") and not q.get("executed")]
    finally:
        f.close()


def _match(item: dict, cid: str) -> bool:
    return item.get("id") == cid or item.get("id", "").startswith(cid)


def accept(confirm_id: str) -> dict | None:
    """确认并执行建议。返回条目（含 params/tool 供执行），执行失败不落盘。"""
    f = _lock_rw()
    try:
        queue = _read(f)
        for item in queue:
            if _match(item, confirm_id) and not item.get("executed"):
                item["confirmed"] = True
                f.seek(0)
                f.truncate()
                json.dump(queue, f, ensure_ascii=False, indent=2)
                f.flush()
                return item
    finally:
        f.close()
    return None


def reject(confirm_id: str) -> bool:
    """拒绝建议，从队列移除。"""
    f = _lock_rw()
    try:
        queue = _read(f)
        new_queue = [q for q in queue if not _match(q, confirm_id)]
        if len(new_queue) == len(queue):
            return False
        f.seek(0)
        f.truncate()
        json.dump(new_queue, f, ensure_ascii=False, indent=2)
        f.flush()
        return True
    finally:
        f.close()


def execute(confirm_id: str, ctx=None) -> str:
    """主人确认后真正执行建议中的工具。"""
    from skills.agent.registry import execute as tool_execute
    from skills.shared.schema import RequestContext

    item = accept(confirm_id)
    if not item:
        return "[Cipher:error]\n建议不存在或已执行"
    try:
        result = tool_execute(item["tool"], item["params"], ctx=ctx)
        try:
            from skills.memory.recorder import record
            record(f"主人确认执行: {item['tool']} {item.get('summary','')[:80]}",
                   source="confirm_queue", obs_type="event", layer="rule")
        except Exception:
            pass
        return result
    except Exception as e:
        return f"[Cipher:error]\n确认执行失败: {e}"
