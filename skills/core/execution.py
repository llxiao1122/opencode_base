"""Layer 3 Execution — task creation, event recording, persistence."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status


class DefaultExecutor:
    def execute(self, ctx: RequestContext) -> None:
        try:
            if ctx.route == "profile":
                return self._store_profile_analysis(ctx)

            if ctx.route != "event" or ctx.event is None:
                ctx.status = Status.EXECUTION_DONE
                return

            from skills.memory.event_recorder import record as record_event

            try:
                record_event(ctx.event)
            except Exception:
                pass

            if ctx.event.get("event_type") == "feedback":
                self._handle_feedback(ctx, record_event)
                return

            self._create_task(ctx)
        except Exception as e:
            ctx.status = Status.ERROR
            ctx.error = f"execution.execute: {e}"

    def _store_profile_analysis(self, ctx):
        decision = ctx.decision or {}
        if decision.get("type") != "profile_analysis":
            ctx.status = Status.EXECUTION_DONE
            return

        target = decision.get("target", "")
        analysis = decision.get("analysis", {})
        summary = analysis.get("summary", "")

        if summary:
            try:
                from skills.memory.observation_store import write as obs_write
                dims = analysis.get("dimensions", {})
                dim_summary = " | ".join(
                    f"{k}:{d.get('score','?')}" for k, d in dims.items() if d
                )
                obs_text = f"{target} 画像: {summary}"
                if dim_summary:
                    obs_text += f" ({dim_summary})"
                obs_write(obs_text, source="profile_reasoning",
                          obs_type="profile_analysis", layer="conclusion", confidence=0.7)
            except Exception:
                pass

        ctx.result = {"target": target, "stored": bool(summary)}
        ctx.status = Status.EXECUTION_DONE

    def _handle_feedback(self, ctx: RequestContext, record_event):
        evt = ctx.event or {}
        from skills.organization.model import OrganizationModel
        from skills.task.manager import TaskManager

        org = OrganizationModel()
        tm = TaskManager(org)
        result = tm.update_from_event(evt)

        if result.get("matched") and ctx.event is not None:
            ctx.event["related_task"] = result.get("task_id", "")
            ctx.event["feedback_status"] = result.get("status", "")
            try:
                record_event(ctx.event)
            except Exception:
                pass
            try:
                from skills.memory.observation_store import write as obs_write
                status_label = "全部完成" if result.get("all_done") else "部分完成"
                obs_write(f"任务完成: {result['executor']}：{result.get('task_id', '')} {status_label}",
                          source="pipeline", obs_type="task_feedback", layer="rule", confidence=0.9)
            except Exception:
                pass

        ctx.result = result
        ctx.status = Status.EXECUTION_DONE

    def _create_task(self, ctx: RequestContext):
        from skills.organization.model import OrganizationModel
        from skills.task.manager import TaskManager

        org = OrganizationModel()
        tm = TaskManager(org)
        managed_task = tm.create(ctx.event or {}, ctx.subject_context or {}, ctx.user or {})

        executors = [e["name"] for e in managed_task.get("executors", [])]
        subtasks_summary = "\n".join(
            f"  [{t.get('assignee','')}] {t.get('action','')}"
            for t in managed_task.get("subtasks", [])[:6]
        )

        ctx.result = {
            "task_id": managed_task.get("id", ""),
            "action": managed_task.get("action", ""),
            "executors": executors,
            "subtasks_summary": subtasks_summary,
            "subtask_count": len(managed_task.get("subtasks", [])),
            "_raw": managed_task,
        }

        evt = ctx.event or {}
        pos = (ctx.subject_context or {}).get("my_position", {})
        req = (ctx.decision or {}).get("requester", "")
        try:
            from skills.memory.observation_store import write as obs_write
            obs_write(
                f"事件类型: {evt.get('event_type', '')}\n"
                f"责任类型: {pos.get('type', '')}\n"
                f"建议行动: {ctx.result.get('action', '')}\n"
                f"执行人: {', '.join(ctx.result.get('executors', []))}\n"
                f"任务: {ctx.result.get('task_id', '')}\n"
                f"发起人: {req}\n"
                f"原文: {ctx.message[:120]}",
                source="pipeline", obs_type="task_created",
                layer="rule", confidence=evt.get("confidence", 0.0),
            )
        except Exception:
            pass

        ctx.status = Status.EXECUTION_DONE
