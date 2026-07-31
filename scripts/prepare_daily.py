#!/usr/bin/env python3
"""08:45 预执行 — 查当日工作，写入 push_queue，08:50 推送。"""

import sys
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.path import ensure_paths; ensure_paths()
from skills.router.faiss_router import _get_index; _get_index()
from skills.shared.schema import RequestContext
from skills.agent.handlers.task_query import handle as task_query_handle

ctx = RequestContext(message="今天有什么任务")
ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}

result = task_query_handle("今天有什么任务", ctx)
text = result.replace("[Cipher:task]\n", "").strip()
if not text:
    print("SKIP — empty result")
    sys.exit(0)

from skills.shared.push_queue import append as queue_append

today = date.today()

push_at = datetime(today.year, today.month, today.day, 8, 50).isoformat()
queue_append({
    "id": f"daily_{today.isoformat()}",
    "channel": "dingtalk",
    "title": "📋 今日待办",
    "body": text,
    "push_at": push_at,
    "pushed": False,
})
print(f"OK — queued for {push_at}")
