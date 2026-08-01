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
