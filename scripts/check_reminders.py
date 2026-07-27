#!/usr/bin/env python3
"""每分钟扫描 reminders.json，到期提醒推钉钉。"""

import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.path import ensure_paths
ensure_paths()

REMINDERS_PATH = ROOT / "data" / "state" / "reminders.json"
if not REMINDERS_PATH.exists():
    sys.exit(0)

try:
    reminders = json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

if not reminders:
    sys.exit(0)

now = datetime.now()
changed = False

for r in reminders:
    if r.get("pushed"):
        continue
    try:
        dt = datetime.fromisoformat(r["time_iso"])
    except Exception:
        continue
    if dt <= now:
        r["pushed"] = True
        changed = True
        from skills.plugins.dingbot.send_msg import send_markdown
        if "工班每个人" in r["message"] or "每个人的情况" in r["message"]:
            from skills.organization.model import OrganizationModel
            from skills.agent.handlers.profile_query import handle as profile_handle
            org = OrganizationModel()
            members = org.get_members("李林骁")
            lines = ["【铁炉西工班成员】"]
            for m in (["李林骁"] + members):
                try:
                    r2 = profile_handle(m)
                    info = r2.replace("[Cipher:profile]\n", "").strip()
                    lines.append(f"  {info}")
                except Exception:
                    lines.append(f"  {m} — 查询失败")
            content = "\n".join(lines)
            resp = send_markdown("⏰ 工班成员情况", content)
        else:
            from skills.entry import handle_core
            reply = handle_core(r["message"])
            content = f"{r['message']}\n\n{reply[:1500]}"
            resp = send_markdown("⏰ 提醒", content)
        if resp.get("errcode") != 0 and resp.get("errcode") != -1:
            print(f"PUSH_FAIL: {r['id']} {resp.get('errmsg', '')}")
        else:
            print(f"PUSH_OK: {r['id']} {r['message'][:60]}")

if changed:
    REMINDERS_PATH.write_text(json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8")
