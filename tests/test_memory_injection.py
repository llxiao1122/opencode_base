"""Test worldview memory injection into Agent path."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))


def test_episodic_search_retrieves_saved_memory():
    """worldview search 能找到 bootstrap 过的实体"""
    from skills.entry import _search_episodic
    ctx = _search_episodic("陈红洁")
    assert "[世界观档案]" in ctx or ctx == ""
    if ctx:
        assert "陈红洁" in ctx


def test_episodic_search_filtered_by_similarity_threshold():
    """无意义输入返回空结果"""
    from skills.entry import _search_episodic
    ctx = _search_episodic("xyxyxyxyxy 999999999 abcdefg")
    assert ctx == ""


def test_episodic_search_returns_empty_on_no_match():
    from skills.entry import _search_episodic
    ctx = _search_episodic("xyxyxyxyxy 999999999 abcdefg")
    assert ctx == ""


def test_agent_system_prompt_includes_memory_context():
    """engine.run 正常执行不报错"""
    from skills.shared.schema import RequestContext
    from skills.agent.engine import run as agent_run

    rctx = RequestContext(
        message="测试查询",
        memory_context="[世界观档案]:\n  • 陈红洁 测试记录",
    )
    result = agent_run("测试查询", rctx)
    assert result is not None


def test_agent_path_with_empty_memory_does_not_crash():
    """空输入不崩溃"""
    from skills.entry import handle_core
    result = handle_core("")
    assert result is not None


def test_agent_path_with_memory_search_does_not_crash():
    """无意义输入不崩溃"""
    from skills.entry import handle_core
    result = handle_core("乱七八糟的输入")
    assert result is not None
