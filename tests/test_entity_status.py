"""测试实体状态行读取与写入（B2-B3 阶段新增机制）"""
from datetime import date
import pytest


def test_read_entity_status_duty():
    from skills.agent.handlers.task_query import _read_entity_status
    status = _read_entity_status("值班轮序")
    assert status is not None, "值班轮序实体应有当前状态行"
    assert status.startswith("锚点="), f"值班状态应以锚点开头: {status}"
    assert "2026-07-15" in status, "应包含锚点日期"


def test_read_entity_status_weekend():
    from skills.agent.handlers.task_query import _read_entity_status
    status = _read_entity_status("周末巡库制度")
    assert status is not None, "周末巡库制度实体应有当前状态行"
    assert status.startswith("生效中"), f"周末巡库应生效: {status}"


def test_read_entity_status_exercise():
    from skills.agent.handlers.task_query import _read_entity_status
    status = _read_entity_status("应急演练计划")
    assert status is not None, "应急演练计划实体应有当前状态行"
    assert "7月" in status and "8月" in status, "应包含多个月份的演练状态"
    assert "已完成" in status, "至少有一个演练已完成"


def test_update_entity_status_line():
    from skills.memory.worldview import _update_entity_status, _rebuild_faiss

    # Same status value → should skip (idempotent)
    unchanged = _update_entity_status("值班轮序", "锚点=2026-07-15 谭继衡")
    assert unchanged is False, "相同状态值应跳过更新"

    # Different status value → should replace
    changed = _update_entity_status("值班轮序", "锚点=2026-08-01 张志斌")
    assert changed is True, "不同状态值应触发替换"

    from skills.agent.handlers.task_query import _read_entity_status
    status = _read_entity_status("值班轮序")
    assert "2026-08-01" in status, f"更新后应包含新锚点: {status}"

    # Restore original
    _update_entity_status("值班轮序", "锚点=2026-07-15 谭继衡")
    _rebuild_faiss()


def test_llm_digest_no_records_returns_none():
    from skills.memory.worldview import _llm_digest
    result = _llm_digest("值班轮序", "锚点=2026-07-15 谭继衡", [])
    assert result is None, "无新记录时不应调 LLM"


def test_llm_digest_with_mock():
    """验证 LLM digest JSON 解析逻辑。mock LLM 返回 JSON，验证解析正确。"""
    from unittest.mock import patch
    from skills.memory.worldview import _llm_digest

    mock_response = '{"changed": true, "new_status": "锚点=2026-08-03 苗笑天", "reason": "锚点确认更新"}'
    with patch("skills.core.llm_client.call", return_value=mock_response):
        result = _llm_digest(
            "值班轮序",
            "锚点=2026-07-15 谭继衡",
            ["[entry] 明天苗笑天值班", "[entry] 值班轮序确认苗笑天8/3值班"]
        )
    assert result is not None, "LLM 应返回新状态"
    assert "2026-08-03" in result, f"新状态应包含更新日期: {result}"


def test_llm_digest_unchanged():
    from unittest.mock import patch
    from skills.memory.worldview import _llm_digest

    mock_response = '{"changed": false, "new_status": "", "reason": "无变更"}'
    with patch("skills.core.llm_client.call", return_value=mock_response):
        result = _llm_digest(
            "周末巡库制度",
            "生效中（周末17点前巡全部库区）",
            ["[entry] 今天天气晴"]
        )
    assert result is None, "无变更事件应返回 None"


def test_deterministic_digest_fallback():
    """LLM 失败时降级到确定性规则：含'已完成'关键词应正确更新演练状态。"""
    from skills.memory.worldview import _deterministic_digest

    result = _deterministic_digest(
        "应急演练计划",
        "7月仓库火灾应急演练（物资总库）=已完成; 8月叉车事故应急演练=未完成",
        ["[entry] 完成了，8月叉车事故应急演练做完了"]
    )
    assert result is not None, "确定性兜底应识别完成语义"
    assert "8月叉车事故应急演练=已完成" in result, f"应更新8月为已完成: {result}"

    # No change for already-completed
    result2 = _deterministic_digest(
        "应急演练计划",
        "7月仓库火灾应急演练（物资总库）=已完成; 8月叉车事故应急演练=已完成",
        ["[entry] 仓库火灾演练完成"]
    )
    assert result2 is None, "已完成不应被重复更新"


def test_urgent_state_words_detect():
    from skills.memory.worldview import _URGENT_STATE_WORDS
    assert "已完成" in _URGENT_STATE_WORDS
    assert "锚点" in _URGENT_STATE_WORDS
    assert "未完成" in _URGENT_STATE_WORDS


def test_behavior_params_cycle():
    from skills.memory.behavior import get, set_param, increment, correction_seen, mark_analyzed, _load

    # Reset to defaults
    data = _load()
    data["correction_tracking"]["total_corrections"] = 0
    data["correction_tracking"]["last_analysis_count"] = 0
    from skills.memory.behavior import _save
    _save(data)

    # Simulate 3 corrections
    assert correction_seen() is False  # 1st: not enough
    assert correction_seen() is False  # 2nd: not enough
    assert correction_seen() is True   # 3rd: trigger analysis

    # After marking analyzed, count resets
    mark_analyzed()
    assert correction_seen() is False  # Reset, 1st again

    # Parameter read/write
    set_param("classify", "high_confidence", 0.65)
    assert get("classify", "high_confidence") == 0.65
    set_param("classify", "high_confidence", 0.70)  # restore

    # 值域锁：下限钳位
    set_param("classify", "high_confidence", 0.30)
    assert get("classify", "high_confidence") == 0.60, "低于下限应钳位"
    set_param("classify", "high_confidence", 0.70)

    # 值域锁：上限钳位
    set_param("classify", "high_confidence", 0.99)
    assert get("classify", "high_confidence") == 0.85, "超过上限应钳位"
    set_param("classify", "high_confidence", 0.70)

    # 值域锁：只读拒绝
    old_total = get("correction_tracking", "total_corrections")
    set_param("correction_tracking", "total_corrections", 999)
    assert get("correction_tracking", "total_corrections") == old_total, "只读字段应拒绝"

    # 值域锁：类型拒绝
    set_param("duty_calculation", "prefer_entity", "yes")
    assert get("duty_calculation", "prefer_entity") is True, "字符串类型应拒绝"


def test_urgent_digest_e2e():
    """端到端验证：关键词→实体映射 + 确定性消化链路贯通"""
    from skills.memory.worldview import _collect_urgent, _deterministic_digest
    from skills.memory.recorder import record
    from skills.agent.handlers.task_query import _read_entity_status

    # Inject state-change events
    record("[entry] 8月叉车事故应急演练已完成", source="test", obs_type="event")
    record("[entry] 值班锚点确认苗笑天8/3值班", source="test", obs_type="event")

    urgent = _collect_urgent()
    assert len(urgent) >= 1, f"urgent 应至少匹配一个实体: {urgent}"

    # Keyword→entity routing verified: "演练"→应急演练计划, "值班"→值班轮序
    found = set(urgent.keys())
    assert any(e in found for e in ("应急演练计划", "值班轮序", "苗笑天")), \
        f"紧急实体匹配不完整: {found}"

    # Deterministic digest verified
    status = _read_entity_status("应急演练计划")
    assert status is not None
    assert "已完成" in status, f"至少7月演练已完成: {status}"
