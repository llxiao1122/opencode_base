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
from skills.agent.registry import list_tools, validate_params, execute, action_type

ensure_paths()

logger = logging.getLogger(__name__)

ROOT = _root()

AGENT_SYSTEM_PROMPT = """\
你是 Cipher，{user_name}的企业智能助手。基于用户消息，选择最合适的工具。
{context_line}{memory_context}可选工具：
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
    # Try full parse
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Try regex approach: assume single JSON object
    m = re.search(r'\{\s*"thought"\s*:.*?"params"\s*:\s*\{.*?\}\s*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # Last resort: extract tool name and assume empty params
    m = re.search(r'"tool"\s*:\s*"([^"]+)"', raw)
    if m:
        return {"thought": "", "intent": "", "tool": m.group(1), "params": {}}
    return None


def _parse_decisions(raw: str) -> list[dict]:
    decisions = []
    # First try: brace-matching to extract JSON objects
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
    if decisions:
        return decisions
    # Second try: line-split format (tool on line 1, JSON on line 2)
    lines = raw.strip().split("\n", 1)
    if len(lines) == 2:
        tool_candidate = lines[0].strip()
        known_tools = {t["id"] for t in list_tools()}
        if tool_candidate in known_tools:
            try:
                params = json.loads(lines[1])
            except json.JSONDecodeError:
                params = {}
            return [{"thought": "", "intent": "", "tool": tool_candidate, "params": params}]
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


def _propose_confirmation(tool_id: str, params: dict, ctx=None) -> dict:
    """confirm 类工具：生成建议入 confirm_queue，并推送钉钉待主人确认。

    Human-in-the-loop：AI 生成建议，人类确认后执行。返回建议条目。
    """
    from skills.shared.confirm_queue import propose as q_propose

    summary = _describe_intent(tool_id, params)
    item = q_propose(tool_id, dict(params), summary=summary)

    try:
        from skills.shared.push_queue import append as queue_append
        from datetime import datetime
        import uuid
        queue_append({
            "id": uuid.uuid4().hex[:12],
            "channel": "dingtalk",
            "title": "🤝 待主人确认",
            "body": (f"{summary}\n\n回复「确认 {item['id'][:6]}」执行，"
                     f"或「拒绝 {item['id'][:6]}」取消。"),
            "push_at": datetime.now().isoformat(),
            "pushed": False,
        })
    except Exception as e:
        logger.warning("confirm push failed: %s", e, exc_info=True)
    return item


def _describe_intent(tool_id: str, params: dict) -> str:
    """将工具意图转为人可读的一句话建议。"""
    if tool_id == "task_create":
        return f"建议创建任务：{params.get('summary', '')}"
    if tool_id == "notification_push":
        return f"建议推送通知：{params.get('title', '')}\n{params.get('content', '')}"
    if tool_id == "correction_feedback":
        return f"建议采纳纠正：{params.get('content', '')}"
    return f"建议执行 {tool_id}：{params}"


def run(user_input: str, ctx: Optional[RequestContext] = None) -> str:
    # 世界观自动更新：pending ≥ 50 时先 batch_update 再处理 query
    try:
        from skills.memory.worldview import check_and_update
        check_and_update()
    except Exception:
        pass

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

    context_parts = []
    slots = ctx.slots or {}
    if slots.get("has_time"):
        context_parts.append("时间指示")
    if slots.get("person_names"):
        context_parts.append("涉及人员 " + "、".join(slots["person_names"]))
    if slots.get("has_correction"):
        context_parts.append("纠错")
    if slots.get("has_knowledge"):
        context_parts.append("知识查询")
    context_line = "当前语境：" + "，".join(context_parts) + "\n" if context_parts else ""

    # 世界观检索：语义匹配最相关的实体档案
    try:
        from skills.memory.worldview import search as worldview_search
        wv_hits = worldview_search(user_input, top_k=2)
        if wv_hits:
            memory_text += "\n\n## 世界观档案\n"
            for h in wv_hits:
                memory_text += f"---\n{h['content'][:1500]}\n"
    except Exception:
        pass

    # 纠错库加载：系统自身成长记忆，应答前全文注入
    try:
        from skills.memory.correction_store import load_recent
        corrections = load_recent(limit=20)
        if corrections:
            memory_text += "\n\n## 纠错记忆（系统成长）\n"
            for c in corrections:
                memory_text += f"- [{c['date']}] {c['text']}\n"
    except Exception:
        pass

    sys_prompt = AGENT_SYSTEM_PROMPT.format(
        user_name=user_name,
        tools_desc=tools_desc,
        memory_context=memory_text,
        context_line=context_line,
    )

    from skills.core.llm_client import call as llm_call

    try:
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

            # Human-in-the-loop：confirm 类工具生成建议入队列，等主人确认后执行
            atype = action_type(tool_id)
            if atype == "confirm":
                proposal = _propose_confirmation(tool_id, params, ctx)
                result = (f"[Cipher:confirm]\n{proposal['summary']}\n"
                          f"建议ID: {proposal['id']}\n"
                          f"已推送待主人确认，回复「确认 {proposal['id'][:6]}」后执行。")
                if is_multi:
                    results.append(result)
                    continue
                return result

            result = execute(tool_id, params, ctx=ctx)

            if is_multi and str(result).startswith("[Cipher:error]"):
                results.append(f"[Cipher]\n第{i+1}条命令失败：{result}")
                continue

            if not is_multi and str(result).startswith("[Cipher:error]"):
                logger.warning("tool %s returned error: %.120s", tool_id, result)
                result = f"[Cipher:agent]\n执行出错（{tool_id}）：{result}\n请重新描述需求。"

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



