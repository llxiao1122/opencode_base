import logging
from contextlib import nullcontext

from skills.workflow.definitions import get as _get_def
from skills.agent.registry import execute as _exec_skill

logger = logging.getLogger(__name__)


class WorkflowResult:
    def __init__(self, text: str, audit: dict | None = None):
        self.text = text
        self.audit = audit or {}


class WorkflowEngine:
    def __init__(self, tracer=None):
        self._tracer = tracer

    def _span(self, name: str, **tags):
        return self._tracer.span(name, **tags) if self._tracer else nullcontext()

    def run(self, workflow_id: str, user_input: str, ctx) -> WorkflowResult:
        wf = _get_def(workflow_id)
        if not wf:
            return WorkflowResult(f"[Cipher:error]\n未知工作流: {workflow_id}")

        steps = wf["steps"]
        results: dict[str, dict] = {}

        with self._span("wf.parallel", steps=len(steps)):
            for step in steps:
                sid = step["skill"]
                result = self._run_step(sid, step, user_input, ctx)
                results[sid] = result

        audit_log = {}
        user_facing = []
        for step in steps:
            sid = step["skill"]
            r = results.get(sid, {"status": "unknown", "text": "", "raw": ""})
            audit_log[sid] = r.get("raw", "")
            if step.get("user_facing", True) and r.get("status") in (None, "ok"):
                text = r.get("text", "")
                if text:
                    user_facing.append(text)

        summary = "\n\n".join(user_facing) if user_facing else "[Cipher:workflow]\n已处理完毕。"
        return WorkflowResult(text=summary, audit=audit_log)

    def _run_step(self, skill_id: str, step: dict, user_input: str, ctx) -> dict:
        params = self._build_params(step, user_input)
        with self._span("wf.step", skill=skill_id):
            raw = _exec_skill(skill_id, params, ctx=ctx)
        text = str(raw).strip() if raw else ""
        return {"status": "ok", "text": text, "raw": text}

    @staticmethod
    def _build_params(step: dict, user_input: str) -> dict:
        rule = step.get("params", {})
        out = {}
        for key, spec in rule.items():
            if spec == "input":
                out[key] = user_input
            elif isinstance(spec, str) and spec.endswith("[:200]"):
                out[key] = user_input[:200]
            elif isinstance(spec, str):
                out[key] = spec
            else:
                out[key] = str(spec) if spec is not None else ""
        return out
