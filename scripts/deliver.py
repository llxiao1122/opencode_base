#!/usr/bin/env python3
"""每分钟扫描 push_queue，到期推送。"""

import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.path import ensure_paths; ensure_paths()

QUEUE = ROOT / "data" / "state" / "push_queue.json"
if not QUEUE.exists():
    sys.exit(0)

try:
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

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
    elif title == "⏰ 提醒" and len(body) < 200:
        from skills.entry import handle_core
        try:
            reply = handle_core(body)
            body = f"{body}\n\n{reply[:1500]}"
        except Exception as e:
            body = f"{body}\n\n（处理失败: {e}）"

    resp = send_markdown(title, body)
    if resp.get("errcode") == 0:
        item["pushed"] = True
        changed = True
        print(f"PUSH_OK: {item['id']} {body[:60]}")
    else:
        print(f"PUSH_FAIL: {item['id']} {resp.get('errmsg', '未发送')}")

if changed:
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
