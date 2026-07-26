"""WorkflowEngine: parallel skill execution + LLM kill + fallback."""

import json, logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError

from skills.workflow.definitions import get as _get_def
from skills.agent.registry import execute as _exec_skill

logger = logging.getLogger(__name__)
_POOL = ThreadPoolExecutor(max_workers=4)


class WorkflowResult:
    def __init__(self, text: str, audit: dict | None = None):
        self.text = text
        self.audit = audit or {}


class WorkflowEngine:
    def run(self, workflow_id: str, user_input: str, ctx) -> WorkflowResult:
        wf = _get_def(workflow_id)
        if not wf:
            return WorkflowResult(f"[Cipher:error]\n未知工作流: {workflow_id}")

        steps = wf["steps"]
        results: dict[str, dict] = {}

        futures = {}
        for step in steps:
            sid = step["skill"]
            fut = _POOL.submit(self._run_step, sid, step, user_input, ctx)
            futures[sid] = fut

        for step in steps:
            sid = step["skill"]
            timeout = step.get("timeout", 15)
            try:
                step_result = futures[sid].result(timeout=timeout)
            except _TimeoutError:
                logger.warning("workflow step '%s' timed out after %ss", sid, timeout)
                step_result = {"status": "timeout", "text": "", "raw": ""}
            except Exception as e:
                logger.error("workflow step '%s' failed: %s", sid, e, exc_info=True)
                step_result = {"status": "error", "text": "", "raw": str(e)}
            results[sid] = step_result

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

        if wf.get("llm_summary") and user_facing:
            summary = self._llm_summarize(user_input, user_facing,
                                          timeout=wf.get("llm_timeout", 15))
        else:
            summary = self._fallback_text(user_facing)

        return WorkflowResult(text=summary, audit=audit_log)

    def _run_step(self, skill_id: str, step: dict, user_input: str, ctx) -> dict:
        params = self._build_params(step, skill_id, user_input)
        raw = _exec_skill(skill_id, params, ctx=ctx)
        text = str(raw).strip() if raw else ""
        return {"status": "ok", "text": text, "raw": text}

    def _build_params(self, step: dict, skill_id: str, user_input: str) -> dict:
        if skill_id == "correction_feedback":
            return {"content": user_input, "context": ""}
        if skill_id == "event_record":
            return {"summary": user_input, "time": ""}
        if skill_id == "notification_push":
            title = "Cipher 处理结果"
            content = user_input[:200]
            return {"title": title, "content": content}
        return {}

    def _llm_summarize(self, user_input: str, texts: list[str], timeout: int) -> str:
        from skills.core.llm_client import call as llm_call
        context = "\n\n".join(texts)
        prompt = (
            f"用户消息：{user_input}\n\n"
            f"系统执行结果：\n{context}\n\n"
            f"请根据以上结果，生成一段简洁的自然语言回复。"
        )
        fut = _POOL.submit(llm_call, prompt,
                           system_prompt="你是 Cipher，一个企业智能助手。用自然语言回复用户。",
                           temperature=0.3, max_tokens=300)
        try:
            result = fut.result(timeout=timeout)
            if isinstance(result, dict) and "error" in result:
                logger.warning("LLM summary returned error: %s", result["error"])
                return self._fallback_text(texts)
            return str(result).strip() if result else self._fallback_text(texts)
        except _TimeoutError:
            logger.warning("LLM summary timed out after %ss", timeout)
            return self._fallback_text(texts)

    def _fallback_text(self, texts: list[str]) -> str:
        if not texts:
            return "[Cipher:workflow]\n已处理完毕。"
        lines = []
        for t in texts:
            cleaned = self._strip_cipher_tag(t)
            if cleaned:
                lines.append(f"- {cleaned}")
        if not lines:
            return "[Cipher:workflow]\n已处理完毕。"
        return "[Cipher:workflow]\n" + "\n".join(lines)

    @staticmethod
    def _strip_cipher_tag(text: str) -> str:
        for prefix in ("[Cipher:notification]", "[Cipher:record]",
                       "[Cipher:correction]", "[Cipher:task]",
                       "[Cipher:error]", "[Cipher:workflow]",
                       "[Cipher:profile]"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                text = text.lstrip("\n✅ ").lstrip("\n").strip()
                return text
        return text.strip()
