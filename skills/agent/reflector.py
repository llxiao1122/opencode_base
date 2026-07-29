"""
agent/reflector.py — Phase 4 反思循环。

在工具执行后触发，分析当前交互是否能提炼模式。
同步调用，限频，不影响主流程。
"""

import json, logging, os, time
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
COOLDOWN = 600
_STATE = {"last_reflect": 0.0}

REFLECTION_TOOLS = {"task_create", "task_feedback", "correction_feedback", "event_record"}


def _should_reflect(tool_id: str) -> bool:
    if tool_id not in REFLECTION_TOOLS:
        return False
    if time.time() - _STATE["last_reflect"] < COOLDOWN:
        return False
    return True


def _build_prompt(tool_id: str, params: dict, result: str, user_input: str) -> str:
    params_str = json.dumps(params, ensure_ascii=False)[:200]
    result_str = result[:300]
    user_str = user_input[:200]
    return (
        f"用户操作: tool={tool_id}, params={params_str}\n"
        f"操作结果: {result_str}\n"
        f"原始消息: {user_str}\n\n"
        f"请分析：\n"
        f"1. 这次操作是否能提炼出工作规律？（如某人擅长某事、某类任务固定在某个时间）\n"
        f"2. 是否有异常需要关注？\n"
        f"3. 有什么可主动建议的？\n"
        f"若无有价值内容回复'无'。"
    )


def _check_corrections(user_input: str) -> str:
    """从 Knowledge 中搜索相关纠正记录"""
    try:
        from skills.memory.observation_store import search as _obs_search
        return _obs_search("纠正 反馈 " + user_input[:60], top_k=2)
    except Exception as e:
        logger.debug("correction check failed: %s", e)
        return ""


def reflect(tool_id: str, params: dict, result: str, user_input: str):
    if not _should_reflect(tool_id):
        return

    try:
        from skills.core.llm_client import call as llm_call
        from skills.memory.recorder import record
    except Exception as e:
        logger.warning("reflect imports failed: %s", e, exc_info=True)
        return

    has_anomaly = "error" in result.lower() or "失败" in result

    corrections = _check_corrections(user_input)

    prompt = _build_prompt(tool_id, params, result, user_input)
    if corrections:
        prompt += f"\n相关纠正记录:\n{corrections[:300]}"

    analysis = llm_call(prompt, max_tokens=200, temperature=0.3)
    if isinstance(analysis, dict):
        logger.warning("reflect llm returned error: %s", analysis.get("error"))
        return
    if not analysis or analysis.strip() in ("无", "无。"):
        return

    detail_lines = []
    if has_anomaly:
        detail_lines.append("异常标志: 检测到异常")
    if corrections:
        detail_lines.append(f"关联纠正: {corrections[:100]}")
    detail_lines.append(f"LLM 分析: {analysis.strip()[:300]}")
    detail_text = "\n".join(detail_lines)

    from skills.memory.recorder import record
    record(
        detail_text,
        source="agent.reflector",
        obs_type="reflection",
        layer="pattern",
        importance="medium",
        confidence=0.6,
    )

    _STATE["last_reflect"] = time.time()
    logger.info("reflect done: tool=%s words=%d", tool_id, len(detail_text))
