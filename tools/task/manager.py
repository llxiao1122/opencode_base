"""
task/manager.py — Task lifecycle manager (Phase 1.8)

Creates tasks from Event + Context, with subtask splitting.
No LLM, pure rules.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

TOOLS_DIR = Path(__file__).resolve().parent.parent


class TaskManager:
    """Creates and queries tasks. Uses task/store for persistence."""

    def __init__(self, org_model):
        self._org = org_model
        self._counter = 0

    def create(self, event: dict, context: dict, user: dict) -> dict:
        """Create a task from event + context.

        Returns Task dict:
            id, source_event_id, responsibility_type,
            owner {name, role}, action, executors[{name,status}],
            subtasks[{action,assignee,done}], deadline, status, created_at
        """
        import sys
        sys.path.insert(0, str(TOOLS_DIR))
        from task.store import save
        from task.status import IN_PROGRESS, EXECUTOR_PENDING
        from task.priority import infer_priority

        pos = context.get("my_position", {})
        req = context.get("required_action", {})
        pos_type = pos.get("type", "observer")
        owner_name = pos.get("owner", "")
        owner_role = user.get("role", "")

        summary = event.get("action", {}).get("summary", "") or ""
        if not summary:
            title = event.get("raw", "") or ""
            # Strip notification boilerplate: "王亮在钉钉群各班组督促一下"
            for sep in ["督促", "通知", "安排", "要求"]:
                idx = title.find(sep)
                if idx >= 0:
                    after = title[idx + len(sep):].strip("一下：:： ").lstrip("，。；")
                    if len(after) >= 2:
                        summary = after[:40].rstrip("，。；、")
                        break
            if not summary or len(summary) < 2:
                summary = "相关任务"
        deadline = event.get("time", {}).get("deadline", "")
        event_id = event.get("id", "")
        scope = req.get("scope", "")
        verb = req.get("verb", "")
        action_text = f"{verb}{scope}{summary}" if verb and scope else summary

        # Strip leading duplicate verb for cleaner subtask text
        clean_summary = summary
        for prefix in ["完成", "进行", "做好", "组织"]:
            if clean_summary.startswith(prefix):
                clean_summary = clean_summary[len(prefix):].lstrip()
                break
        if not clean_summary:
            clean_summary = "相关任务"

        executors = []
        subtasks = []

        if pos_type == "coordinator":
            members = self._org.get_members(owner_name)
            executors = [{"name": m, "status": EXECUTOR_PENDING} for m in members]
            for m in members:
                subtasks.append({
                    "action": f"通知{m}完成{clean_summary}",
                    "assignee": m,
                    "done": False,
                })
            subtasks.append({
                "action": f"汇总{scope}完成情况",
                "assignee": owner_name,
                "done": False,
            })

        elif pos_type == "executor":
            executors = [{"name": owner_name, "status": EXECUTOR_PENDING}]
            subtasks.append({
                "action": action_text,
                "assignee": owner_name,
                "done": False,
            })

        elif pos_type == "supervisor":
            assigned = scope or req.get("scope", "执行人")
            executors = [{"name": assigned, "status": EXECUTOR_PENDING}]
            subtasks.append({
                "action": f"监督{assigned}完成{summary}",
                "assignee": owner_name,
                "done": False,
            })

        event_time = event.get("detected_at") or event.get("time", {}).get("start", "")
        task = {
            "id": self._next_id(event_id),
            "source_event_id": event_id,
            "responsibility_type": pos_type,
            "priority": infer_priority(event.get("raw", "")),
            "owner": {"name": owner_name, "role": owner_role},
            "action": action_text,
            "executors": executors,
            "subtasks": subtasks,
            "deadline": deadline,
            "status": IN_PROGRESS,
            "created_at": event_time if event_time else datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "created_source": "event_time" if event_time else "import_time",
        }

        save(task)
        return task

    def list_active(self, owner_name: str) -> list:
        from task.store import list_by_owner
        from task.status import IN_PROGRESS
        return list_by_owner(owner_name, status=IN_PROGRESS)

    def get(self, task_id: str):
        from task.store import load
        return load(task_id)

    def _next_id(self, event_id: str) -> str:
        self._counter += 1
        short = event_id.replace("evt_", "") if event_id.startswith("evt_") else event_id
        return f"task_{short}_{self._counter:03d}"

    def update_from_event(self, event: dict) -> dict:
        """Process a feedback event. Match executor, update status, check completion.

        Returns dict:
            {matched: bool, task_id, executor, all_done, status}
        """
        import sys
        sys.path.insert(0, str(TOOLS_DIR))
        from task.store import update_executor_status, get_active_tasks, close as store_close
        from task.status import EXECUTOR_DONE

        actors = event.get("actors", [])
        entities = event.get("entities", []) or event.get("raw", "")

        # Find executor from event actors
        executor_name = ""
        for a in actors:
            if a.get("position") in ("entity", "executor"):
                executor_name = a.get("name", "")
                break
        if not executor_name:
            return {"matched": False, "match_type": "unmatched", "reason": "无法从反馈中识别人名"}

        # Find matching active task
        owner_name = self._org.get_leader(executor_name)
        if not owner_name:
            # Person not in 铁炉西工班 — try org-wide search for known persons
            if _is_known_person(executor_name):
                import json
                tasks = json.loads((TOOLS_DIR.parent / "data" / "tasks.json").read_text(encoding="utf-8"))
                from task.status import IN_PROGRESS
                for t in tasks:
                    if t.get("status") != IN_PROGRESS:
                        continue
                    for ex in t.get("executors", []):
                        if ex["name"] == executor_name:
                            owner_name = t.get("owner", {}).get("name", "")
                            matched = t
                            break
                    if matched:
                        break
            if not owner_name:
                return {"matched": False, "match_type": "unmatched", "reason": f"{executor_name} 无归属工班"}

        active = get_active_tasks(owner_name)
        matched = None
        for task in active:
            for e in task.get("executors", []):
                if e["name"] == executor_name:
                    matched = task
                    break
            if matched:
                break

        if not matched:
            # Try related match: find tasks executor might be connected to
            candidate_tasks = []
            for t in active:
                for ex in t.get("executors", []):
                    if ex["name"] == executor_name:
                        candidate_tasks.append({"task_id": t["id"], "action": t.get("action", "")[:60]})
                        break
            if candidate_tasks:
                return {
                    "matched": False,
                    "match_type": "candidate",
                    "reason": f"{executor_name} 存在关联任务但不在当前执行人中",
                    "candidate_tasks": candidate_tasks,
                }
            return {"matched": False, "match_type": "unmatched", "reason": f"{executor_name} 不在活跃任务中"}

        # Update status (direct match)
        from task.status import EXECUTOR_DONE
        updated = update_executor_status(matched["id"], executor_name, EXECUTOR_DONE)

        # Check completion
        all_done = self._check_complete(matched["id"])
        if all_done:
            store_close(matched["id"])

        return {
            "matched": True,
            "match_type": "direct",
            "task_id": matched["id"],
            "executor": executor_name,
            "all_done": all_done,
            "status": "completed" if all_done else "in_progress",
        }

    def _check_complete(self, task_id: str) -> bool:
        """Check if all executors are done (owner subtask auto-closes with team)."""
        import sys
        sys.path.insert(0, str(TOOLS_DIR))
        from task.store import load, update_executor_status

        task = load(task_id)
        if not task:
            return False
        executors_done = all(e.get("status") == "done" for e in task.get("executors", []))
        if not executors_done:
            return False

        # Auto-complete owner's subtasks when all executors done
        owner_name = task.get("owner", {}).get("name", "")
        subtasks_done = all(st.get("done", False)
                            for st in task.get("subtasks", [])
                            if st.get("assignee") != owner_name)
        if subtasks_done:
            for st in task.get("subtasks", []):
                if st.get("assignee") == owner_name:
                    st["done"] = True
            return True
        return False


def _is_known_person(name: str) -> bool:
    from tools.shared import get_role
    return bool(get_role(name))
