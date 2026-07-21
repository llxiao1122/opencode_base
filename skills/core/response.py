"""Layer 4 Response — reply composition."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status


class DefaultResponseBuilder:
    def __init__(self, llm=None):
        self._llm = llm

    def respond(self, ctx: RequestContext) -> str:
        if ctx.status == Status.ERROR:
            return f"[Cipher:error]\n{ctx.error}"

        if ctx.route == "profile":
            return self._profile_reply(ctx)

        if ctx.route == "task":
            return self._task_reply(ctx)

        if ctx.route == "knowledge":
            return self._knowledge_reply(ctx)

        return self._event_reply(ctx)

    def _profile_reply(self, ctx: RequestContext) -> str:
        decision = ctx.decision or {}
        if decision.get("type") != "profile_analysis":
            return "[Cipher:profile]\n暂无画像数据。"

        target = decision.get("target", "")
        analysis = decision.get("analysis", {})

        if "error" in str(decision.get("error", "")):
            return f"[Cipher:profile]\n暂无 {target} 的相关记录。"

        summary = analysis.get("summary", "")
        dims = analysis.get("dimensions", {})
        specialties = analysis.get("specialties", [])
        risks = analysis.get("risks", [])
        growth = analysis.get("growth", {})
        recommendation = analysis.get("recommendation", "")

        lines = [f"[Cipher:profile]\n{summary}"]

        if dims:
            lines.append("")
            for key, label in [("efficiency", "执行效率"), ("reliability", "可靠性"), ("collaboration", "协作能力")]:
                d = dims.get(key, {})
                if d and d.get("score"):
                    s = int(d["score"])
                    stars = "★" * s + "☆" * (5 - s)
                    risk_mark = " ⚠️" if d.get("risk") else ""
                    lines.append(f"  {label}: {stars}{risk_mark}")

        if growth and growth.get("evidence"):
            trend_symbol = {"up": "↑", "down": "↓", "flat": "→"}.get(growth.get("trend", ""), "")
            lines.append(f"  趋势: {trend_symbol} {growth['evidence']}")

        if specialties:
            lines.append(f"  专长: {'/'.join(specialties)}")

        if risks:
            for r in risks:
                if r:
                    lines.append(f"  ⚠️ {r}")

        if recommendation:
            lines.append(f"  建议: {recommendation}")

        return "\n".join(lines)

    def _task_reply(self, ctx: RequestContext) -> str:
        from skills.routing.task_handler import handle as task_handle
        return task_handle(ctx.message, ctx)

    def _knowledge_reply(self, ctx: RequestContext) -> str:
        from skills.routing.knowledge_handler import handle as knowledge_handle
        return knowledge_handle(ctx.message, ctx)

    def _event_reply(self, ctx: RequestContext) -> str:
        if ctx.event and ctx.event.get("event_type") == "feedback":
            return self._feedback_reply(ctx)

        pos_type = ""
        if ctx.decision:
            pos_type = ctx.decision.get("pos_type", "")
        llm_reply = ctx.decision.get("llm_reply", "") if ctx.decision else ""

        record_note = ctx.record_note
        prefix = ""
        if record_note:
            prefix = f"{record_note}\n\n"

        task_info = ""
        if ctx.result and ctx.result.get("task_id"):
            task_info = (
                f"\n📋 任务已创建: {ctx.result['task_id']} "
                f"({ctx.result.get('subtask_count', 0)} 子任务)"
            )

        return f"[Cipher:{pos_type}]\n{prefix}{llm_reply}{task_info}"

    def _feedback_reply(self, ctx: RequestContext) -> str:
        result = ctx.result or {}
        if result.get("matched"):
            if result.get("all_done"):
                msg = f"✅ {result['executor']} 已完成。全员完成，任务 {result['task_id']} 已关闭。"
            else:
                msg = f"✅ 已记录：{result['executor']} 完成。"
        else:
            msg = result.get("reason", "未匹配到任务")
        return f"[Core:feedback]\n{msg}"
