#!/usr/bin/env python3
"""每日晨报 8:45 — 查当日工作安排，推钉钉群。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.path import ensure_paths
ensure_paths()

from skills.router.builder import build as build_entity_index
build_entity_index()

from skills.router.faiss_router import _get_index
_get_index()

from skills.shared.schema import RequestContext
from skills.agent.handlers.task_query import handle as task_query_handle

ctx = RequestContext(message="今天有什么任务")
ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}

result = task_query_handle("今天有什么任务", ctx)
text = result.replace("[Cipher:task]\n", "").strip()

if not text:
    print("SKIP — empty result")
    sys.exit(0)

from skills.plugins.dingbot.send_msg import send_markdown
resp = send_markdown("📋 今日待办", text)
if resp.get("errcode") != 0:
    print(f"FAIL: {resp.get('errmsg', '')}")
    sys.exit(1)

print(f"OK — {len(text)} chars")
