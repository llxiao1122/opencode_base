import time
import logging
from datetime import datetime
from skills.agent.handlers.notification import handle as send_notification
from skills.task.store import get_impending_tasks, mark_notified
from skills.task.priority import THRESHOLD_MAP
from skills.shared.time_parse import parse_deadline_dt

logger = logging.getLogger(__name__)


class ProactiveDaemon:
    def __init__(self, check_interval_sec: int = 300):
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
                summary_parts = {
                    "action": action[:60],
                    "deadline": dl_str,
                    "threshold": f"{threshold}h",
                    "task_id": task["id"],
                }
                title = f"⏰ 任务临期提醒（提前{threshold}小时）"
                content = (
                    f"### {title}\n\n"
                    f"**任务**：{action}\n\n"
                    f"**截止**：{dl_str}\n\n"
                    f"**优先级**：{pval}\n\n"
                    "---\n"
                    f"回复 `已完成 {action[:20]}` 确认完成。"
                )
                send_notification(title=title, content=content)
                mark_notified(task["id"], threshold)
                logger.info(
                    "Alert sent: task=%s action=%s deadline=%s threshold=%sh",
                    task["id"], action[:40], dl_str, threshold,
                )


if __name__ == "__main__":
    daemon = ProactiveDaemon(check_interval_sec=300)
    daemon.start_loop()
