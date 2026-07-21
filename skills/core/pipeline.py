"""
core/pipeline.py — Pipeline 编排器 (Phase 4).

编排 6 层流水线：
  Ingress → Intent → Reasoning → Execution → Response → Reflection

RequestContext 贯穿全程，每层只写自己的字段。
错误通过 ctx.status / ctx.error 传递。
Reflection 层不阻塞回复，fire-and-forget。
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status


class Pipeline:
    def __init__(self, ingress, intent, reasoning, execution, response, reflection=None):
        self._ingress = ingress
        self._intent = intent
        self._reasoning = reasoning
        self._execution = execution
        self._response = response
        self._reflection = reflection

    def run(self, ctx: RequestContext) -> str:
        if ctx.user is None:
            import json as _json
            try:
                _idx = _json.loads((ROOT / "state" / "entity_index.json").read_text(encoding="utf-8"))
                for _e in _idx.get("confirmed_entities", []):
                    if _e["name"] == "李林骁":
                        ctx.user = {"name": "李林骁", "role": _e.get("role", "工班长"), "team": _e.get("team", "铁炉西工班")}
                        break
                else:
                    ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
            except Exception:
                ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}

        self._ingress.build(ctx)
        if ctx.status == Status.ERROR:
            return self._error_reply(ctx)

        self._intent.extract(ctx)
        if ctx.status == Status.ERROR:
            return self._error_reply(ctx)
        if ctx.status == Status.SKIP_REMAINING:
            ctx.status = Status.DONE
            return ctx.record_note

        self._reasoning.reason(ctx)
        if ctx.status == Status.ERROR:
            return self._error_reply(ctx)

        self._execution.execute(ctx)
        if ctx.status == Status.ERROR:
            return self._error_reply(ctx)

        reply = self._response.respond(ctx)
        ctx.reply = reply
        ctx.status = Status.DONE

        if self._reflection:
            try:
                self._reflection.reflect(ctx)
            except Exception:
                pass

        return reply

    @classmethod
    def build_default(cls):
        from skills.core.llm_client import call as _llm
        from skills.core.ingress import DefaultIngress
        from skills.core.intent import DefaultIntentExtractor
        from skills.core.reasoning import DefaultReasoningEngine
        from skills.core.execution import DefaultExecutor
        from skills.core.response import DefaultResponseBuilder
        from skills.core.reflection import DefaultReflector
        from skills.core.cognitive_loop import CognitiveLoop

        return cls(
            ingress=DefaultIngress(),
            intent=DefaultIntentExtractor(),
            reasoning=DefaultReasoningEngine(llm=_llm),
            execution=DefaultExecutor(),
            response=DefaultResponseBuilder(llm=_llm),
            reflection=DefaultReflector(llm=_llm, cognitive_loop=CognitiveLoop.build_default()),
        )

    @staticmethod
    def _error_reply(ctx: RequestContext) -> str:
        return f"[Cipher:error]\n{ctx.error}"
