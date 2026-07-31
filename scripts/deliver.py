#!/usr/bin/env python3
"""每分钟扫描 push_queue，到期推送。"""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.path import ensure_paths; ensure_paths()
from skills.shared.push_queue import read as queue_read, write as queue_write

queue = queue_read()
if not queue:
    sys.exit(0)

now = datetime.now()
changed = False

from skills.plugins.dingbot.send_msg import send_markdown

for item in queue:
    if item.get("pushed"):
        continue
    try:
        dt = datetime.fromisoformat(item["push_at"])
    except Exception:
        continue
    if dt > now:
        continue

    body = item.get("body", "")
    title = item.get("title", "⏰ 提醒")

    if "工班每个人" in body[:60] or "每个人的情况" in body[:60]:
        from skills.organization.model import OrganizationModel
        from skills.agent.handlers.profile_query import handle as profile_handle
        org = OrganizationModel()
        members = org.get_members("李林骁")
        out = ["【铁炉西工班成员】"]
        for m in (["李林骁"] + members):
            try:
                r2 = profile_handle(m)
                info = r2.replace("[Cipher:profile]\n", "").strip()
                out.append(f"  {info}")
            except Exception:
                out.append(f"  {m} — 查询失败")
        body = "\n".join(out)
    resp = send_markdown(title, body)
    if resp.get("errcode") == 0:
        item["pushed"] = True
        changed = True
        print(f"PUSH_OK: {item['id']} {body[:60]}")
        try:
            from skills.memory.recorder import record
            record(
                f"通知推送: {title}\n{body[:200]}",
                source="cron.deliver", obs_type="notification", layer="rule",
            )
        except Exception:
            pass
    else:
        print(f"PUSH_FAIL: {item['id']} {resp.get('errmsg', '未发送')}")

if changed:
    queue_write(queue)
