"""Agent tool-calling loop 测试 — 原生 function calling + 多步循环 + 错误重试。"""

import pytest
import conftest

from skills.shared.schema import RequestContext


def _make_tool_call(tool_id, args_dict):
    return {
        "id": f"call_test_{tool_id}",
        "type": "function",
        "function": {
            "name": tool_id,
            "arguments": __import__("json").dumps(args_dict),
        },
    }


def test_run_agent_loop_native_single_tool():
    """原生 function calling: 一次 tool_calls → 执行 → 获得 tool_context。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    conftest.MOCK_LLM_SEQUENCE = [
        (None, [_make_tool_call("task_query", {"scope": "today"})]),
        ("[Cipher:mock] 查询完成。", None),
    ]
    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("今天有什么任务", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "ok"
    assert "[task_query]" in result.get("tool_context", "")
    assert "[Cipher:task]" in result.get("tool_context", "")


def test_run_agent_loop_native_no_tool():
    """无需工具：LLM 直接返回内容 → type=ok（文本作为上下文）。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    conftest.MOCK_LLM_SEQUENCE = [
        ("你好主人，有什么可以帮您？", None),
    ]
    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("你好", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "ok"
    assert "有什么可以帮您" in result.get("tool_context", "")


def test_run_agent_loop_multi_step():
    """多步工具：第一步 task_query，第二步 profile_query。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    tc1 = _make_tool_call("task_query", {"scope": "today"})
    tc2 = _make_tool_call("profile_query", {"name": "杨梦卓"})
    conftest.MOCK_LLM_SEQUENCE = [
        (None, [tc1]),
        (None, [tc2]),
        ("主人，杨梦卓是今天的值班人员。", None),
    ]
    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("今天谁值班，查一下她的档案", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "ok"
    ctx = result.get("tool_context", "")
    assert "[task_query]" in ctx
    assert "[profile_query]" in ctx


def test_run_agent_loop_error_retry():
    """工具报错 → 回喂重试 → 模型换工具。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    # First: unknown tool → error fed back
    tc_bad = _make_tool_call("nonexistent_tool", {})
    # Second: correct tool
    tc_good = _make_tool_call("task_query", {"scope": "today"})
    # Third: natural answer
    conftest.MOCK_LLM_SEQUENCE = [
        (None, [tc_bad]),
        (None, [tc_good]),
        ("主人，查询完成。", None),
    ]
    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("有什么任务", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "ok"
    ctx = result.get("tool_context", "")
    # Error from unknown tool should be fed back, correct tool called
    assert "[task_query]" in ctx


def test_run_agent_loop_event_sink():
    """event_sink 回调在每步工具执行时触发。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    conftest.MOCK_LLM_SEQUENCE = [
        (None, [_make_tool_call("task_query", {"scope": "today"})]),
        ("[Cipher:mock] 完成。", None),
    ]
    events = []

    def sink(evt):
        events.append(evt)

    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("今天任务", max_steps=5, event_sink=sink)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "ok"
    assert len(events) >= 2  # tool_start + tool_done
    assert any(e["type"] == "tool_start" for e in events)
    assert any(e["type"] == "tool_done" for e in events)


def test_run_agent_loop_confirm_tool():
    """confirm 类工具：返回 confirm 类型，不执行。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    conftest.MOCK_LLM_SEQUENCE = [
        (None, [_make_tool_call("task_create", {"summary": "测试批准任务"})]),
    ]
    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("批准创建一个任务", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "confirm"
    assert "proposal_id" in result


def test_run_agent_loop_text_fallback():
    """混合解析兜底：无原生 tool_calls 时 _parse_decisions 提取文本 JSON 决策。"""
    old_seq = conftest.MOCK_LLM_SEQUENCE
    old_content = conftest.MOCK_LLM_CONTENT
    # No sequence → fallback to MOCK_LLM_CONTENT
    conftest.MOCK_LLM_SEQUENCE = None
    conftest.MOCK_LLM_CONTENT = '[{"tool": "task_query", "params": {"scope": "today"}}]'
    try:
        from skills.agent.engine import run_agent_loop
        result = run_agent_loop("今天有什么任务", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq
        conftest.MOCK_LLM_CONTENT = old_content

    assert result["type"] == "ok"
    assert "[task_query]" in result.get("tool_context", "")


def test_run_agent_loop_thinking_reasoning_content():
    """思考模式：tool_calls 返回时必须携带 reasoning_content 回传给后续轮次。"""
    import json
    from unittest.mock import patch
    from skills.core import llm_client as lc

    old_seq = conftest.MOCK_LLM_SEQUENCE
    tc1 = _make_tool_call("task_query", {"scope": "today"})
    conftest.MOCK_LLM_SEQUENCE = [
        (None, [tc1], "先思考：需要查询任务"),
        ("主人，查询完成。", None),
    ]
    seen_messages = []

    real_call = lc.call

    def spy_call(*args, **kwargs):
        if kwargs.get("messages"):
            seen_messages.append(kwargs["messages"])
        return real_call(*args, **kwargs)

    try:
        with patch.object(lc, "call", spy_call):
            from skills.agent.engine import run_agent_loop
            result = run_agent_loop("今天有什么任务", max_steps=5)
    finally:
        conftest.MOCK_LLM_SEQUENCE = old_seq

    assert result["type"] == "ok"
    # 第二轮请求的 messages 中，上一轮 assistant 消息必须带 reasoning_content
    assert len(seen_messages) >= 2, f"应发生多轮调用, 实际 {len(seen_messages)}"
    second_round = seen_messages[1]
    assert any(
        m.get("role") == "assistant" and m.get("reasoning_content") == "先思考：需要查询任务"
        and m.get("tool_calls") is not None
        for m in second_round
    ), "思考模式 assistant 消息必须带 reasoning_content 回传"


def test_fix_notice_dates():
    """规则校正通知日期：相对词后错误日期替换为正确日期（基于今天）。"""
    from datetime import date
    from skills.agent.engine import _fix_notice_dates

    today = date.today()
    m2 = (today.replace(day=1) + __import__("datetime").timedelta(days=32)).replace(day=1)
    # 明天正确日
    tm = today.replace(month=today.month, day=today.day) + __import__("datetime").timedelta(days=1)
    correct_tm = f"{tm.month}月{tm.day}日"
    wrong = f"{correct_tm.split('月')[0]}月{int(correct_tm.split('月')[1][:-1]) + 1}日" \
        if int(correct_tm.split("月")[1][:-1]) < 28 else "8月1日"

    fixed = _fix_notice_dates(f"请于明天（{wrong}）上午开会")
    assert fixed == f"请于明天（{correct_tm}）上午开会", f"期望 {correct_tm}, 实际 {fixed}"

    # 正确日期不动
    ok = _fix_notice_dates(f"请于明天（{correct_tm}）上午开会")
    assert ok == f"请于明天（{correct_tm}）上午开会"

    # 无日期不动
    assert _fix_notice_dates("明天上午开会") == "明天上午开会"
