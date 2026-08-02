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
你是 Cipher，{user_name}的企业智能助手。

{identity_style}{context_line}{memory_context}可选工具：
{tools_desc}

## 近期对话历史
{conversation_history}

今天是 {today}（{weekday}，北京时间）。"昨天/今天/明天/后天/大后天"请以今日为基准推算具体日期。

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
6. 查询值班、巡库、待办、任务安排时，必须选择 "task_query"（它内部会推算值班轮序和巡库人员），禁止仅凭制度内容推断人员。
"""

AGENT_LOOP_PROMPT = """\
你是 Cipher，{user_name}的企业智能助手。

{identity_style}{context_line}{memory_context}
今天是 {{today}}({{weekday}}，北京时间)。"昨天/今天/明天/后天/大后天"请以今日为基准推算具体日期。

工具说明：
{tools_desc}

规则：
1. 使用工具查询信息或执行操作，参数从主人的消息中提取
2. 查询值班/巡库/待办/任务安排必须选择 task_query
3. 无法匹配任何工具时选择 knowledge_retrieve，topic 设为消息原文
4. 如果一条消息包含多个独立指令，可依次调用多个工具
5. 工具执行出错时，可调整参数重试或换其他工具
"""

ID_STYLE = (
    "身份：第三人称\"Cipher\"自称，称呼用户为\"主人\"。"
    "沟通风格：详实、解释充分，说明做了什么、为什么、结果如何。\n"
)


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


def _fix_notice_dates(text: str) -> str:
    """规则校正通知内容中的日期（基于今天）。

    LLM 生成通知内容时常把"明天/后天/大后天"对应的具体日期算错一天
    （例：今天 8/2，"后天下午"写成"8月3日"）。此处用 Python 规则
    基于 date.today() 校正：识别相对词后紧跟的"X月X日"，若与正确
    日期不符则替换为正确日期。
    """
    import re as _re
    from datetime import date, timedelta

    today = date.today()
    rel_map = {
        "大后天": 3, "大後天": 3,
        "后天": 2, "後天": 2,
        "明天": 1, "明日": 1,
        "今天": 0, "今日": 0,
    }
    # 形如：8月3日 / 8月3日（周一）/ 2026年8月3日
    date_re = _re.compile(r"(20\d{2}年)?(\d{1,2})月(\d{1,2})日")

    out = text
    for rel, delta in rel_map.items():
        search_from = 0
        while True:
            pos = out.find(rel, search_from)
            if pos < 0:
                break
            tail = out[pos + len(rel):]
            m = date_re.search(tail)
            if m and m.start() <= 6:
                correct = today + timedelta(days=delta)
                if (int(m.group(2)), int(m.group(3))) != (correct.month, correct.day):
                    old = m.group(0)
                    new = f"{correct.year}年{correct.month}月{correct.day}日" if m.group(1) else f"{correct.month}月{correct.day}日"
                    out = out[:pos + len(rel) + m.start()] + new + out[pos + len(rel) + m.end():]
                search_from = pos + len(rel) + m.end()
            else:
                search_from = pos + len(rel)
    return out


def _propose_confirmation(tool_id: str, params: dict, ctx=None) -> dict:
    """confirm 类工具：生成建议入 confirm_queue，并推送钉钉待主人确认。

    Human-in-the-loop：AI 生成建议，人类确认后执行。返回建议条目。
    """
    from skills.shared.confirm_queue import propose as q_propose

    params = dict(params)
    if tool_id == "notification_push" and params.get("content"):
        params["content"] = _fix_notice_dates(str(params["content"]))

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
        title = params.get('title', '')
        content = _fix_notice_dates(str(params.get('content', '')))
        return f"建议推送通知：{title}\n{content}"
    if tool_id == "correction_feedback":
        return f"建议采纳纠正：{params.get('content', '')}"
    return f"建议执行 {tool_id}：{params}"


CHAT_SYSTEM_PROMPT = """\
你是 Cipher，{user_name}的企业智能助手。

{identity_style}

## 记忆上下文
{memory_context}

## 近期对话历史
{conversation_history}

今天是 {today}（{weekday}，北京时间）。"昨天/今天/明天/后天/大后天"请以今日为基准推算具体日期。

根据以上记忆和对话历史，用自然流畅的中文回复主人的问题。
直接回复内容即可，不要加任何前缀标记（如 [Cipher:xxx]）。

规则：
1. 如果提供了「工具执行结果」，必须**以工具结果为准**逐字转述事实（值班人员、日期、任务、天气等），禁止自行推算、改写或"纠正"其中的日期和人员。
2. 若工具结果含日期而你不确定今日是哪天，直接用工具结果中的日期表述。
3. 记忆与工具结果冲突时，以工具结果为准。
"""


def _build_self_status() -> str:
    lines = []
    try:
        from skills.core.llm_client import _resolve_config
        _, _, model, _ = _resolve_config()
        lines.append(f"- 后台模型：{model}")
    except Exception:
        pass

    try:
        from skills.memory.behavior import get
        dc = get("duty_calculation") or {}
        ct = get("correction_tracking") or {}
        cf = get("classify") or {}
        total = ct.get("total_corrections", 0)
        last = ct.get("last_analysis_count", 0)
        new_count = dc.get("correction_count", 0)
        lines.append(f"- 累计纠错：{total} 条（距上次进化分析新增 {new_count} 次）")
        if last > 0:
            lines.append(f"- 进化历史：已完成 1 次进化分析（累计 {last} 条时触发），当前参数 prefer_entity={'实体优先' if dc.get('prefer_entity') else 'md 推算'}")
        else:
            lines.append("- 进化历史：尚未触发进化分析")
        lines.append(f"- 快路径置信阈值：{cf.get('high_confidence', 0.70)}（高于此值直接执行，不走 LLM）")
    except Exception:
        pass

    lines.append("- 权限边界：负责工班人员安排/库区物资管理/安全管理/工作协调；有权安排班组人员/协调库区工作/反馈问题；无权审批报废/决定危废处置时间/调整处置商计划")

    try:
        from skills.agent.registry import list_tools
        tools = list_tools()
        read_tools = [t["id"] for t in tools if t.get("action_type") == "read"]
        direct_tools = [t["id"] for t in tools if t.get("action_type") in ("write", "confirm")]
        lines.append(f"- 可用工具（{len(tools)} 个）：查询类 {', '.join(read_tools)}；执行类 {', '.join(direct_tools)}（网页对话中直接执行）")
    except Exception:
        pass

    try:
        from skills.memory.observation_store import read as obs_read
        content = obs_read("system", "Cipher")
        if content:
            summaries = []
            in_detail = False
            for line in content.splitlines():
                if line.strip().startswith("source:"):
                    in_detail = True
                    continue
                if in_detail and line.strip():
                    summaries.append(line.strip()[:120])
                    in_detail = False
            if summaries:
                recent = summaries[-5:]
                lines.append(f"- 近期观测记忆（{len(summaries)} 条中最近 5 条）：" + "；".join(recent))
    except Exception:
        pass

    if not lines:
        return ""
    return "## Cipher 自身状态\n" + "\n".join(lines) + "\n\n"


def _build_memory_context(user_input: str) -> str:
    memory_text = ""

    try:
        from skills.memory.worldview import search as worldview_search
        wv_hits = worldview_search(user_input, top_k=2)
        if wv_hits:
            memory_text += "\n\n## 世界观档案\n"
            for h in wv_hits:
                memory_text += f"---\n{h['content'][:1500]}\n"
    except Exception:
        pass

    try:
        from skills.memory.correction_store import load_recent
        corrections = load_recent(limit=20)
        if corrections:
            memory_text += "\n\n## 纠错记忆（系统成长）\n"
            for c in corrections:
                memory_text += f"- [{c['date']}] {c['text']}\n"
    except Exception:
        pass

    try:
        from skills.memory.behavior import get
        dc = get("duty_calculation", "correction_count") or 0
        if dc >= 2:
            memory_text += (
                f"\n\n⚠ 重要提示：近期值班推算已被纠正 {dc} 次，"
                "回答值班/排班问题时请严格按实体档案事实对话，不要自行推算。\n"
            )
    except Exception:
        pass

    try:
        from skills.memory.observation_store import read as obs_read
        content = obs_read("system", "Cipher")
        if content:
            style_lines = []
            in_summary = False
            for line in content.splitlines():
                if line.strip().startswith("### Summary"):
                    in_summary = True
                    continue
                if in_summary and line.strip():
                    t = line.strip()
                    if ("主人" in t and not t.startswith("通知推送")
                            and "未归类" not in t):
                        style_lines.append(t[:120])
                    in_summary = False
            if style_lines:
                memory_text += "\n\n## 风格约束（主人行为偏好）\n"
                for sl in style_lines[-4:]:
                    memory_text += f"- {sl}\n"
    except Exception:
        pass

    memory_text += _build_self_status()

    return memory_text


def _today_str() -> str:
    from datetime import date
    return date.today().strftime("%Y年%m月%d日")


def _weekday_str() -> str:
    from datetime import date
    return "一二三四五六日"[date.today().weekday()]


def run_agent_loop(user_input, ctx=None, max_steps=10, event_sink=None):
    """Agent 工具调用循环（opencode 同款）。

    Native function calling + 混合文本 JSON 兜底 + 报错回喂重试。
    仅负责工具调用，不生成自然语言回复。

    Returns:
        {"type": "ok", "tool_context": str}
        {"type": "confirm", "content": str, "proposal_id": str}
        {"type": "error", "content": str}
    """
    from skills.core.llm_client import call as llm_call
    from skills.agent.registry import tools_schema as get_tools_schema

    if ctx is None:
        ctx = RequestContext(message=user_input)
        ctx.user = resolve_user()

    slots_context = ""
    try:
        from skills.router.faiss_router import extract_slots
        slots = extract_slots(user_input)
        parts = []
        if slots.get("has_time"):
            parts.append("时间指示")
        if slots.get("person_names"):
            parts.append("涉及人员 " + "、".join(slots["person_names"]))
        if slots.get("has_correction"):
            parts.append("纠错")
        if parts:
            slots_context = "当前语境：" + "，".join(parts) + "\n"
    except Exception:
        pass

    episodic_text = ""
    try:
        from skills.memory.worldview import search as wv_search
        hits = wv_search(user_input, top_k=2, type_filter="person")
        hits = [h for h in hits if h.get("score", 0) >= 0.6]
        if hits:
            lines = ["[世界观档案]:"]
            for h in hits:
                snippet = h.get("content", "")[:300].replace("\n", " ").strip()
                lines.append(f"  • {h['entity_id']} ({h['type']}) {snippet}")
            episodic_text = "\n".join(lines) + "\n"
    except Exception:
        pass

    memory_context = _build_memory_context(user_input)
    if episodic_text:
        memory_context = episodic_text + "\n" + memory_context

    tools_desc = "\n".join(
        "- {}: {}  -> {}".format(
            t["id"], t["description"],
            "; ".join("{}={}".format(k,
                v.get("description", v.get("default", "required")))
                for k, v in t["params"].items())
        )
        for t in list_tools()
    )

    tools = get_tools_schema()

    system_msg = AGENT_LOOP_PROMPT.format(
        user_name="主人",
        tools_desc=tools_desc,
        memory_context=memory_context,
        context_line=slots_context,
        identity_style=ID_STYLE,
        today=_today_str(),
        weekday=_weekday_str(),
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_input},
    ]

    tool_outputs = []
    available = {t["id"] for t in list_tools()}

    user_id = None
    try:
        uname = (ctx.user or {}).get("name", "")
        import re as _re
        m = _re.sub(r"[^a-zA-Z0-9\-_]", "", uname)
        if m:
            user_id = m[:512]
    except Exception:
        pass

    for step in range(max_steps):
        raw = llm_call(messages=messages, tools=tools, max_tokens=800,
                       thinking={"type": "enabled"}, reasoning_effort="high",
                       user_id=user_id)

        if isinstance(raw, dict) and raw.get("tool_calls"):
            reasoning_content = raw.get("reasoning_content")
            tool_results = []
            for tc in raw["tool_calls"]:
                fn = tc.get("function", {})
                tool_id = fn.get("name", "")
                try:
                    params = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    params = {}

                if event_sink:
                    event_sink({"type": "tool_start", "tool_id": tool_id,
                               "params": params, "step": step + 1})

                atype = action_type(tool_id)
                if atype == "confirm":
                    proposal = _propose_confirmation(tool_id, params, ctx)
                    if event_sink:
                        event_sink({"type": "tool_done", "tool_id": tool_id,
                                   "status": "confirm", "step": step + 1})
                    return {"type": "confirm", "content": proposal["summary"],
                            "proposal_id": proposal["id"]}

                if tool_id not in available:
                    result = f"[Cipher:error]\n未知工具: {tool_id}"
                else:
                    ok, err = validate_params(tool_id, params)
                    if not ok:
                        result = f"[Cipher:error]\n参数校验失败({tool_id}): {err}"
                    else:
                        try:
                            result = execute(tool_id, params, ctx=ctx) or ""
                        except Exception as e:
                            logger.warning("tool exec failed: %s", e)
                            result = f"[Cipher:error]\n工具执行失败({tool_id}): {e}"

                status = "error" if str(result).startswith("[Cipher:error]") else "ok"
                tool_outputs.append(f"[{tool_id}]:\n{result}")

                if event_sink:
                    event_sink({"type": "tool_done", "tool_id": tool_id,
                               "status": status, "step": step + 1})

                tool_results.append((tc, str(result)))

            # 整轮 tool_calls 作为一条 assistant 消息（思考模式必须带 reasoning_content）
            assistant_msg = {"role": "assistant", "content": None,
                             "tool_calls": raw["tool_calls"]}
            if reasoning_content:
                assistant_msg["reasoning_content"] = reasoning_content
            messages.append(assistant_msg)
            for tc, result in tool_results:
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                "content": result})

            continue

        elif isinstance(raw, dict) and "error" in raw:
            return {"type": "error", "content": raw.get("error", "LLM 调用失败")}

        else:
            content = str(raw).strip() if raw else ""
            decisions = _parse_decisions(content)
            if decisions:
                for decision in decisions:
                    tool_id = decision.get("tool", "")
                    params = decision.get("params", {})

                    if tool_id not in available:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user",
                                        "content": f"[Cipher:error]\n未知工具 '{tool_id}'"})
                        continue

                    ok, err = validate_params(tool_id, params)
                    if not ok:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user",
                                        "content": f"[Cipher:error]\n参数校验失败({tool_id}): {err}"})
                        continue

                    atype = action_type(tool_id)
                    if atype == "confirm":
                        proposal = _propose_confirmation(tool_id, params, ctx)
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": proposal["summary"]})
                        if event_sink:
                            event_sink({"type": "tool_done", "tool_id": tool_id,
                                       "status": "confirm"})
                        return {"type": "confirm", "content": proposal["summary"],
                                "proposal_id": proposal["id"]}

                    result = execute(tool_id, params, ctx=ctx) or ""
                    is_err = str(result).startswith("[Cipher:error]")
                    tool_outputs.append(f"[{tool_id}]:\n{result}")

                    if event_sink:
                        event_sink({"type": "tool_start", "tool_id": tool_id,
                                   "params": params, "step": step + 1})
                        event_sink({"type": "tool_done", "tool_id": tool_id,
                                   "status": "error" if is_err else "ok",
                                   "step": step + 1})

                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user",
                                    "content": f"工具 {tool_id} 的执行结果：\n{result}"})

                continue

            # No tool_calls and no JSON decisions — collect as context and stop
            if content and content not in ("[]", "null", "None"):
                tool_outputs.append(f"[Cipher 分析]:\n{content}")
            break

    return {"type": "ok", "tool_context": "\n\n".join(tool_outputs) if tool_outputs else ""}


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

    memory_text += _build_memory_context(user_input)

    sys_prompt = AGENT_SYSTEM_PROMPT.format(
        user_name=user_name,
        tools_desc=tools_desc,
        memory_context=memory_text,
        context_line=context_line,
        identity_style=ID_STYLE,
        conversation_history="（无历史对话）",
        today=_today_str(),
        weekday=_weekday_str(),
    )

    from skills.core.llm_client import call as llm_call

    try:
        raw = llm_call(user_input, system_prompt=sys_prompt, max_tokens=800, temperature=0.0,
                       thinking={"type": "enabled"}, reasoning_effort="high")
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


def run_stream(sender_id: str, user_input: str, event_sink=None):
    """流式对话生成器，与 handle_core() 功能对齐。
    流程：slots → 纠错检测 → episodic → 分类 → fast_dispatch/agent → 流式生成 → 记录+进化。
    用法: for chunk in run_stream(sender_id, text): ..."""
    from skills.core.llm_client import call_stream as llm_stream
    from skills.memory.conversation import format_for_llm as conv_history

    # === Step 1: Slot extraction (Gap 2) ===
    has_correction = False
    slots_context = ""
    try:
        from skills.router.faiss_router import extract_slots
        slots = extract_slots(user_input)
        parts = []
        if slots.get("has_time"):
            parts.append("时间指示")
        if slots.get("person_names"):
            parts.append("涉及人员 " + "、".join(slots["person_names"]))
        if slots.get("has_correction"):
            parts.append("纠错")
            has_correction = True
        if slots.get("has_knowledge"):
            parts.append("知识查询")
        if parts:
            slots_context = "当前语境：" + "，".join(parts) + "\n"
    except Exception:
        pass

    # === Step 2: Correction detection → direct write (Gap 6, P0) ===
    correction_processed = False
    if has_correction:
        try:
            from skills.memory.correction_store import append as corr_append
            corr_append(user_input)
            from skills.memory.behavior import correction_seen
            correction_seen()
            correction_processed = True
        except Exception:
            pass

    # === Step 3: Episodic search (Gap 3, P1) ===
    episodic_text = ""
    try:
        from skills.memory.worldview import search as wv_search
        hits = wv_search(user_input, top_k=2, type_filter="person")
        hits = [h for h in hits if h.get("score", 0) >= 0.6]
        if hits:
            lines = ["[世界观档案]:"]
            for h in hits:
                snippet = h.get("content", "")[:300].replace("\n", " ").strip()
                lines.append(f"  • {h['entity_id']} ({h['type']}) {snippet}")
            episodic_text = "\n".join(lines) + "\n"
    except Exception:
        pass

    # === Step 4: Memory context ===
    memory_context = _build_memory_context(user_input)
    if episodic_text:
        memory_context = episodic_text + "\n" + memory_context

    conv_text = conv_history(sender_id, n=10)
    tools_desc = "\n".join(
        "- {}: {}  -> {}".format(
            t["id"], t["description"],
            "; ".join("{}={}".format(k,
                v.get("description", v.get("default", "required")))
                for k, v in t["params"].items())
        )
        for t in list_tools()
    )

    # === Step 5: Classify + Fast dispatch (Gap 1+2+4, P2) ===
    tool_result = None
    use_fast = False
    try:
        from skills.router.faiss_router import classify as faiss_classify
        route, confidence = faiss_classify(user_input)
        from skills.memory.behavior import get as behavior_get
        threshold = behavior_get("classify", "high_confidence") or 0.70
        if round(confidence, 2) >= threshold and route != "event":
            import importlib
            _FAST_HANDLERS = {
                "task_query": "skills.agent.handlers.task_query",
                "knowledge_retrieve": "skills.agent.handlers.knowledge_retrieve",
                "profile_query": "skills.agent.handlers.profile_query",
            }
            mod_path = _FAST_HANDLERS.get(route)
            if mod_path:
                mod = importlib.import_module(mod_path)
                handler = getattr(mod, "handle")
                from skills.shared.schema import RequestContext
                from skills.shared.entity import resolve_user
                rctx = RequestContext(message=user_input)
                rctx.user = resolve_user() or {"name": "李林骁"}
                rctx.slots = {}
                tool_result = handler(user_input, rctx)
                use_fast = True
    except Exception:
        pass

    # === Phase 1: Agent tool loop (fallback when not fast-dispatch) ===
    if not use_fast:
        try:
            loop_result = run_agent_loop(user_input, max_steps=10,
                                          event_sink=event_sink)
        except Exception:
            loop_result = None
        if loop_result and loop_result.get("type") == "ok":
            tool_result = loop_result.get("tool_context", "") or None
        elif loop_result and loop_result.get("type") == "confirm":
            tool_result = (f"[Cipher:confirm]\n{loop_result['content']}\n"
                           f"建议ID: {loop_result['proposal_id']}\n"
                           f"已推送待主人确认，回复「确认 {loop_result['proposal_id'][:6]}」后执行。")
        elif loop_result and loop_result.get("type") == "error":
            tool_result = f"[Cipher:info]\n{loop_result['content']}"

    # === Phase 2: Streaming natural response ===
    chat_memory = memory_context
    if tool_result:
        chat_memory += f"\n\n## 工具执行结果\n{str(tool_result)[:3000]}"

    chat_prompt = CHAT_SYSTEM_PROMPT.format(
        user_name="主人",
        identity_style=ID_STYLE,
        memory_context=chat_memory,
        conversation_history=conv_text if conv_text else "（无历史对话）",
        today=_today_str(),
        weekday=_weekday_str(),
    )

    collected = ""
    uid = None
    try:
        import re as _re
        _u = _re.sub(r"[^a-zA-Z0-9\-_]", "", str(sender_id)[:512])
        if _u:
            uid = _u
    except Exception:
        pass
    try:
        for chunk in llm_stream(user_input, system_prompt=chat_prompt, max_tokens=1024,
                                temperature=0.3, thinking={"type": "enabled"},
                                reasoning_effort="high", user_id=uid, include_usage=True):
            if isinstance(chunk, dict) and "error" in chunk:
                yield f"\n[Cipher]\n处理出错：{chunk['error']}"
                return
            collected += str(chunk)
            yield str(chunk)
        if not collected:
            if tool_result:
                yield f"\n{tool_result}"
            else:
                yield "\n[Cipher]\n主人，Cipher 收到了，但目前没有足够的依据来回答。"
    except Exception as e:
        logger.error("run_stream error: %s", e, exc_info=True)
        if collected:
            return
        if tool_result:
            yield f"\n{tool_result}"
        else:
            yield "\n[Cipher]\n处理出错，请重试。"

    # === Post-stream: Observer record (Gap 7, P1) + Evolution (Gap 5, P0) ===
    if not correction_processed:
        try:
            from skills.memory.recorder import record as recorder_record
            recorder_record(user_input, source="web_chat", obs_type="interaction",
                          layer="rule", confidence=0.7, skip_learning=False)
        except Exception:
            pass

    if correction_processed:
        try:
            from skills.agent.reflector import _try_behavior_adjustment
            _try_behavior_adjustment()
        except Exception:
            pass



