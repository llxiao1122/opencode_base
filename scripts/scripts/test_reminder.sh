#!/usr/bin/env bash
export DINGTALK_BOT_TOKEN=871e8ca746a4514807e8c958bf8fdebde00261ff0feba370f73173c967982639
sleep 60
cd /home/admin/opencode_base || exit 1
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from skills.plugins.dingbot.send_msg import send_markdown
r = send_markdown('⏰ 台账填写提醒', '### ⏰ 每日台账填写提醒\n\n您好，请及时填写今日台账。\n\n---\n*Cipher 自动提醒*\n回复 **台账已填** 确认完成。')
print(r)
" >> data/logs/cron_reminders.log 2>&1
