"""Agent LLM 路径真实测试：mock 输出可配置，验证真实分支而非 fallback。

- test_agent_llm_selects_tool_and_executes: LLM 返回工具决策 → 工具真实执行
- test_agent_llm_text_answer_flows: LLM 返回文本 → knowledge_retrieve 走生成回答
- test_agent_llm_empty_falls_back: 无决策 → 安全降级（原有行为保持）
"""

import pytest

import conftest

from skills.shared.schema import RequestContext


def _run_agent(text: str) -> str:
    from skills.agent.engine import run as agent_run
    rctx = RequestContext(message=text)
    return agent_run(text, rctx)


def test_agent_llm_selects_tool_and_executes():
    """LLM 决策选中 task_query → 工具真实执行，而非 fallback。"""
    old = conftest.MOCK_LLM_CONTENT
    conftest.MOCK_LLM_CONTENT = '[{"tool": "task_query", "params": {"scope": "today"}}]'
    try:
        result = _run_agent("今天有什么任务")
    finally:
        conftest.MOCK_LLM_CONTENT = old
    assert result is not None
    assert str(result).startswith("[Cipher:task]"), f"应走工具路径，实际: {str(result)[:100]}"


def test_agent_llm_text_answer_flows():
    """LLM 文本应答 → knowledge_retrieve 直接生成回答（非空）。"""
    old = conftest.MOCK_LLM_CONTENT
    conftest.MOCK_LLM_CONTENT = "[Cipher:mock] 依据制度内容生成的回答。"
    try:
        from skills.agent.handlers.knowledge_retrieve import handle as kh
        result = kh("物资验收入库规定", RequestContext(message="物资验收入库规定"))
    finally:
        conftest.MOCK_LLM_CONTENT = old
    assert result is not None
    assert "[Cipher:mock] 依据制度内容生成的回答。" in str(result)


def test_agent_llm_empty_falls_back():
    """无决策输出 → 安全降级到知识检索（行为不回退）。"""
    old = conftest.MOCK_LLM_CONTENT
    conftest.MOCK_LLM_CONTENT = "[]"
    try:
        result = _run_agent("随便说点什么")
    finally:
        conftest.MOCK_LLM_CONTENT = old
    assert result is not None
    assert "[Cipher" in str(result) and "Error" not in str(result)
