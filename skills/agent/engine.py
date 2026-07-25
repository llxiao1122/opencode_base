"""
agent/engine.py — Agent 核心。

1 次 LLM 调用完成意图理解 + 工具选择 + 参数提取。
容错链保证永不崩溃。
"""

import json, re
from typing import Optional
from pathlib import Path

from skills.shared.schema import RequestContext, CT
from skills.correction.logger import append as log_append
from skills.agent.registry import list_tools, validate_params, execute

ROOT = Path(__file__).resolve().parent.parent.parent

AGENT_SYSTEM_PROMPT = """\
你是 Cipher，{user_name}的企业智能助手。基于用户消息，选择最合适的工具。

可选工具：
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
    return None


def _fallback_search(query: str) -> str:
    try:
        from skills.routing.knowledge_handler import handle as kh
        ctx = RequestContext(message=query)
        try:
            idx = json.loads((ROOT / "state" / "entity_index.json").read_text(encoding="utf-8"))
            for e in idx.get("confirmed_entities", []):
                if e["name"] == "李林骁":
                    ctx.user = {"name": "李林骁", "role": e.get("role", "工班长"),
                                "team": e.get("team", "铁炉西工班")}
                    break
        except Exception:
            ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}
        result = kh(query, ctx)
        return result or f"[Cipher]\n已记录：{query}"
    except Exception:
        return f"[Cipher]\n已记录：{query}"


def run(user_input: str, ctx: Optional[RequestContext] = None) -> str:
    if ctx is None:
        ctx = RequestContext(message=user_input)
        try:
            idx = json.loads((ROOT / "state" / "entity_index.json").read_text(encoding="utf-8"))
            for e in idx.get("confirmed_entities", []):
                if e["name"] == "李林骁":
                    ctx.user = {"name": "李林骁", "role": e.get("role", "工班长"),
                                "team": e.get("team", "铁炉西工班")}
                    break
        except Exception:
            ctx.user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}

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
    sys_prompt = AGENT_SYSTEM_PROMPT.format(user_name=user_name, tools_desc=tools_desc)

    from skills.core.llm_client import call as llm_call

    try:
        raw = llm_call(user_input, system_prompt=sys_prompt, max_tokens=800, temperature=0.3)
        if isinstance(raw, dict) and "error" in raw:
            return _fallback_search(user_input)

        decision = _extract_json(str(raw))
        if not decision:
            return _fallback_search(user_input)

        tool_id = decision.get("tool", "")
        params = decision.get("params", {})

        available = [t["id"] for t in list_tools()]
        if tool_id not in available:
            return _fallback_search(user_input)

        ok, err = validate_params(tool_id, params)
        if not ok:
            return f"[Cipher:agent]\n{err}，请补充后重试。"

        result = execute(tool_id, params)
        ctx.route = tool_id
        ctx.confidence = 0.8
        return result

    except Exception as e:
        return f"[Cipher:error]\n处理失败: {e}"
