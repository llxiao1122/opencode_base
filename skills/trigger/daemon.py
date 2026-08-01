"""
skills/trigger/daemon.py — 主动巡检守护线程。

每 3600 秒（1 小时）扫描 tasks.json，检查到期/临期任务，
按多级阈值（红色/橙色/黄色/绿色）触发钉钉通知。
由 entry.py handle_core 在首次消息处理时启动。
"""

import time
import uuid
import logging
from datetime import datetime
from skills.task.store import get_impending_tasks, mark_notified
from skills.task.priority import THRESHOLD_MAP
from skills.shared.time_parse import parse_deadline_dt
from skills.shared.push_queue import append as queue_append

logger = logging.getLogger(__name__)


class ProactiveDaemon:
    def __init__(self, check_interval_sec: int = 3600):
        self.interval = check_interval_sec

    def start_loop(self):
        logger.info("Cipher Proactive Daemon started (interval=%ss)", self.interval)
        while True:
            try:
                self._check_impending_tasks()
            except Exception as e:
                logger.error("Daemon loop error: %s", e, exc_info=True)
            time.sleep(self.interval)

    def _check_impending_tasks(self):
        now = datetime.now()
        for threshold in [24, 2]:
            tasks = get_impending_tasks(threshold, now_dt=now)
            for task in tasks:
                priority = task.get("priority", {})
                pval = priority.get("value", "normal") if isinstance(priority, dict) else "normal"
                allowed = THRESHOLD_MAP.get(pval, [2])
                if threshold not in allowed:
                    continue
                action = task.get("action", "")
                dl = task.get("deadline", "")
                dl_dt = parse_deadline_dt(dl)
                dl_str = dl_dt.strftime("%m-%d %H:%M") if dl_dt else dl
                title = f"⏰ 任务临期提醒（提前{threshold}小时）"
                content = (
                    f"### {title}\n\n"
                    f"**任务**：{action}\n\n"
                    f"**截止**：{dl_str}\n\n"
                    f"**优先级**：{pval}\n\n"
                    "---\n"
                    f"回复 `已完成 {action[:20]}` 确认完成。"
                )
                queue_append({
                    "id": f"daemon_{task['id']}_{threshold}h_{uuid.uuid4().hex[:6]}",
                    "channel": "dingtalk",
                    "title": title,
                    "body": content,
                    "push_at": datetime.now().isoformat(),
                    "pushed": False,
                })
                mark_notified(task["id"], threshold)
                logger.info(
                    "Alert queued: task=%s action=%s deadline=%s threshold=%sh",
                    task["id"], action[:40], dl_str, threshold,
                )
        try:
            from skills.memory.recorder import record
            record(f"daemon 扫描临期任务: 已推送 {sum(1 for t in [24, 2] for _ in get_impending_tasks(t, now_dt=now))} 条提醒",
                   source="daemon", obs_type="observation", layer="rule")
        except Exception:
            pass


if __name__ == "__main__":
    daemon = ProactiveDaemon(check_interval_sec=3600)
    daemon.start_loop()
