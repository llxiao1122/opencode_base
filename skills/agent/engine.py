"""
agent/engine.py — Agent 核心。

1 次 LLM 调用完成意图理解 + 工具选择 + 参数提取。
容错链保证永不崩溃。
"""

import json, logging, re
from typing import Optional
from pathlib import Path

from skills.shared.path import ensure_paths, root as _root
from skills.shared.schema import RequestContext, CT
from skills.shared.entity import resolve_user
from skills.correction.logger import append as log_append
from skills.agent.registry import list_tools, validate_params, execute

ensure_paths()

logger = logging.getLogger(__name__)

ROOT = _root()

AGENT_SYSTEM_PROMPT = """\
你是 Cipher，{user_name}的企业智能助手。基于用户消息，选择最合适的工具。
{memory_context}可选工具：
{tools_desc}

输出格式（严格 JSON，只输出 JSON 对象，不要 markdown 代码块）：
{{
  "thought": "简要推理过程",
  "intent": "意图分类",
  "tool": "选中的工具 id",
  "params": {{ 工具参数字典 }}
}}

规则：
1. thought 字段记录推理过程，不用于执行
2. tool 必须从可选工具中选择
3. params 必须符合工具的参数定义
4. 无法匹配任何工具时，tool 设为 "knowledge_retrieve"，params.topic 设为消息原文
5. 如果消息包含多个语义命令，按行依次输出，每行一个完整 JSON 对象；如果只有一个命令，输出一行 JSON 即可。
"""


def _extract_json(raw: str) -> Optional[dict]:
    raw = raw.strip()
    clean = raw
    for prefix in ["```json", "```"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip()
    if clean.endswith("```"):
        clean = clean[:-3].strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    m = re.search(r'"tool"\s*:\s*"([^"]+)"', raw)
    if m:
        return {"thought": "", "intent": "", "tool": m.group(1), "params": {}}
    lines = raw.strip().split("\n", 1)
    if len(lines) == 2:
        tool_candidate = lines[0].strip()
        known_tools = {t["id"] for t in list_tools()}
        if tool_candidate in known_tools:
            try:
                params = json.loads(lines[1])
            except json.JSONDecodeError:
                params = {}
            return {"thought": "", "intent": "", "tool": tool_candidate, "params": params}
    return None


def _parse_decisions(raw: str) -> list[dict]:
    decisions = []
    i = 0
    while i < len(raw):
        start = raw.find("{", i)
        if start == -1:
            break
        depth = 0
        for j in range(start, len(raw)):
            if raw[j] == "{":
                depth += 1
            elif raw[j] == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start:j+1]
                    d = _extract_json(candidate)
                    if d:
                        decisions.append(d)
                    i = j + 1
                    break
        else:
            break
    return decisions


def _fallback_search(query: str) -> str:
    try:
        from skills.agent.handlers.knowledge_retrieve import handle as kh
        ctx = RequestContext(message=query)
        ctx.user = resolve_user()
        result = kh(query, ctx)
        return result or f"[Cipher]\n已记录：{query}"
    except Exception as e:
        logger.error("fallback search failed: %s", e, exc_info=True)
        return f"[Cipher]\n已记录：{query}"


def run(user_input: str, ctx: Optional[RequestContext] = None,
        tracer=None) -> str:
    if ctx is None:
        ctx = RequestContext(message=user_input)
        ctx.user = resolve_user()
    else:
        if ctx.user is None:
            ctx.user = resolve_user()

    ctx.route = "agent"
    ctx.confidence = 0.0

    user_name = (ctx.user or {}).get("name", "用户")
    tools_desc = "\n".join(
        "- {}: {}  -> {}".format(
            t["id"], t["description"],
            "; ".join("{}={}".format(k,
                v.get("description", v.get("default", "required")))
                for k, v in t["params"].items())
        )
        for t in list_tools()
    )
    memory_text = (ctx.memory_context or "").strip()
    if memory_text and not memory_text.endswith("\n"):
        memory_text += "\n"
    sys_prompt = AGENT_SYSTEM_PROMPT.format(
        user_name=user_name,
        tools_desc=tools_desc,
        memory_context=memory_text,
    )

    from skills.core.llm_client import call as llm_call

    try:
        with (tracer.span("agent.llm_think") if tracer else _nullctx()):
            raw = llm_call(user_input, system_prompt=sys_prompt, max_tokens=800, temperature=0.0)
        if isinstance(raw, dict) and "error" in raw:
            logger.warning("LLM call returned error: %s", raw.get("error"))
            return _fallback_search(user_input)

        decisions = _parse_decisions(str(raw))
        if not decisions:
            logger.warning("LLM response could not be parsed as JSON: %.200s", str(raw))
            return _fallback_search(user_input)

        available = {t["id"] for t in list_tools()}
        results = []
        last_tool = ""
        is_multi = len(decisions) > 1

        for i, decision in enumerate(decisions):
            tool_id = decision.get("tool", "")
            params = decision.get("params", {})
            if tool_id not in available:
                logger.warning("LLM selected unknown tool '%s'", tool_id)
                if is_multi:
                    results.append(f"[Cipher]\n第{i+1}条命令失败：未知工具 '{tool_id}'")
                    continue
                return _fallback_search(user_input)

            ok, err = validate_params(tool_id, params)
            if not ok:
                logger.warning("param validation failed for %s: %s", tool_id, err)
                if is_multi:
                    results.append(f"[Cipher]\n第{i+1}条命令失败：{err}")
                    continue
                return f"[Cipher:agent]\n{err}，请补充后重试。"

            with (tracer.span("agent.execute", tool=tool_id) if tracer else _nullctx()):
                result = execute(tool_id, params, ctx=ctx)

            if is_multi and str(result).startswith("[Cipher:error]"):
                results.append(f"[Cipher]\n第{i+1}条命令失败：{result}")
                continue

            if not is_multi and str(result).startswith("[Cipher:error]"):
                logger.warning("tool %s returned error, retrying once: %.120s", tool_id, result)
                retry_raw = llm_call(
                    f"之前选择的工具 {tool_id} 执行失败：{result}\n\n"
                    f"用户原始消息：{user_input}\n\n"
                    f"请修正参数后重试。只输出 JSON 对象。",
                    system_prompt="你是 Cipher，修正参数后重新选择工具。",
                    max_tokens=800, temperature=0.3,
                )
                if not (isinstance(retry_raw, dict) and "error" in retry_raw):
                    retry_decision = _extract_json(str(retry_raw))
                    if retry_decision:
                        retry_tool = retry_decision.get("tool", tool_id)
                        retry_params = retry_decision.get("params", params)
                        if retry_tool in available:
                            ok, _ = validate_params(retry_tool, retry_params)
                            if ok:
                                with (tracer.span("agent.retry_execute", tool=retry_tool) if tracer else _nullctx()):
                                    result = execute(retry_tool, retry_params, ctx=ctx)
                                tool_id = retry_tool

            results.append(result)
            last_tool = tool_id

        ctx.route = last_tool
        ctx.confidence = 0.8
        if not results:
            return _fallback_search(user_input)
        if not is_multi:
            return results[0]
        return "\n---\n".join(
            f"{i+1}. {r}" for i, r in enumerate(results)
        )

    except Exception as e:
        logger.error("agent run failed: %s", e, exc_info=True)
        return f"[Cipher:error]\n处理失败: {e}"


def _nullctx():
    from contextlib import nullcontext
    return nullcontext()
