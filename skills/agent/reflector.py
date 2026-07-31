"""
agent/reflector.py — Phase 4 反思循环。

在工具执行后触发，统计跟踪工具使用模式和异常。
同步调用，限频，不影响主流程。
"""

import json, logging, os, time
from pathlib import Path
from collections import defaultdict

from skills.shared.path import root as _root

logger = logging.getLogger(__name__)

ROOT = _root()
COOLDOWN = 600
_STATE = {"last_reflect": 0.0}

REFLECTION_TOOLS = {"task_create", "task_feedback", "correction_feedback", "event_record"}
_USAGE = defaultdict(int)
_ANOMALIES = defaultdict(list)


def _should_reflect(tool_id: str) -> bool:
    if tool_id not in REFLECTION_TOOLS:
        return False
    if time.time() - _STATE["last_reflect"] < COOLDOWN:
        return False
    return True


def _check_corrections(user_input: str) -> list:
    """从纠错库检索与本次输入相关的纠正记录"""
    try:
        from skills.memory.correction_store import load_recent
        corrections = load_recent(limit=20)
        hits = []
        for c in corrections:
            text = c.get("text", "")
            if not text:
                continue
            if user_input[:6] in text or text[:6] in user_input or any(
                    kw in user_input for kw in text.split() if len(kw) >= 2):
                hits.append(c)
        return hits[:3]
    except Exception as e:
        logger.debug("correction check failed: %s", e)
        return []


def reflect(tool_id: str, params: dict, result: str, user_input: str):
    if not _should_reflect(tool_id):
        return

    _USAGE[tool_id] += 1
    # 权威失败标记为 engine 的 [Cipher:error] 前缀（engine.py 单/多工具失败路径）。
    # 不可用文本关键字"失败/error"——业务文案本身可能含"失败"（如"尝试旧密码失败"），
    # 会造成工具成功却被误报为异常。
    has_anomaly = str(result).lower().startswith("[cipher:error]")
    if has_anomaly:
        preview = result[:150]
        _ANOMALIES[tool_id].append(preview)
        if len(_ANOMALIES[tool_id]) > 10:
            _ANOMALIES[tool_id].pop(0)

    try:
        from skills.memory.recorder import record
    except Exception as e:
        logger.warning("reflect imports failed: %s", e, exc_info=True)
        return

    corrections = _check_corrections(user_input)

    detail_lines = []
    total_usage = sum(_USAGE.values())
    if total_usage > 5:
        top_tools = sorted(_USAGE.items(), key=lambda x: -x[1])[:3]
        detail_lines.append(f"工具使用: {'; '.join(f'{t}={c}次' for t, c in top_tools)}")
    if has_anomaly:
        detail_lines.append(f"异常: {tool_id} 失败")
    if corrections:
        detail_lines.append(f"关联纠正: {json.dumps(corrections[:3], ensure_ascii=False)[:100]}")

    if not detail_lines:
        return

    record(
        "\n".join(detail_lines),
        source="agent.reflector",
        obs_type="reflection",
        layer="pattern",
        importance="medium",
        confidence=0.6,
    )

    _STATE["last_reflect"] = time.time()
    logger.info("reflect done: tool=%s", tool_id)
