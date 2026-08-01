"""
agent/reflector.py — Phase 4 反思循环 + 行为参数自适应。

在工具执行后触发，双阶段：
  a. 文本级异常检测 — [Cipher:error] 前缀
  b. 纠错模式分析 — correction ≥ 3 条新纠错时，LLM 分析可学习模式
     输出 → behavior.json 参数调整（神经可塑性闭环）
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

    # 阶段 b：纠错模式分析 → 行为参数自适应
    _try_behavior_adjustment()


def _try_behavior_adjustment():
    """当纠错库积累 ≥ 3 条新纠错时，LLM 分析可学习模式。

    输出 → behavior.json 参数调整（不直接写文件，LLM 输出建议，代码校验执行）。
    限频：每次 reflect 调用一次，但仅当 correction_seen 触发 ≥ 3 次时。
    """
    try:
        from skills.memory.behavior import correction_seen, mark_analyzed, get, set_param
        from skills.memory.correction_store import load_recent
        from skills.core.llm_client import call as llm_call
    except ImportError:
        return

    df = get("duty_calculation", {})
    if df.get("correction_count", 0) < 3:
        return

    corrections = load_recent(limit=10)
    if len(corrections) < 3:
        return

    # Build analysis prompt
    corr_texts = "\n".join(
        f"  [{c.get('date','?')}] {c.get('text','')[:120]}"
        for c in corrections[-10:]
    )
    current_params = json.dumps({
        "duty_calculation": get("duty_calculation"),
        "classify": get("classify"),
    }, ensure_ascii=False)

    prompt = f"""你是系统自诊分析器。分析最近的纠错记录，判断是否有可学习的模式。

当前行为参数：
{current_params}

最近纠错记录（最近 10 条）：
{corr_texts}

分析规则：
- 如果值班推算被反复纠正 → 建议 prefer_entity=true（实体状态优先于 md 推算）
- 如果快路径分类频繁出错 → 建议降低 high_confidence 阈值（让更多查询走 LLM 路径）
- 如果某领域纠错密集 → 不做具体建议，仅报告"该领域稳定性差"
- 如果无重复模式 → 返回 changed=false

返回 JSON（只返回 JSON）：
{{"changed": true/false, "updates": [{{"key": "duty_calculation", "subkey": "prefer_entity", "value": true}}], "reason": "分析结论（15字以内）"}}"""

    try:
        result = llm_call(prompt, temperature=0.0, max_tokens=256, timeout=30)
        if not result or isinstance(result, dict):
            return
        result = result.strip()
        if result.startswith("```"):
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
        data = json.loads(result)
        if data.get("changed"):
            for upd in data.get("updates", []):
                key = upd.get("key", "")
                subkey = upd.get("subkey", "")
                value = upd.get("value")
                if key and subkey and value is not None:
                    set_param(key, subkey, value)
                    logger.info("behavior adjusted: %s.%s = %s (%s)",
                                key, subkey, value, data.get("reason", ""))
    except Exception as e:
        logger.debug("behavior adjustment analysis failed: %s", e)

    mark_analyzed()
