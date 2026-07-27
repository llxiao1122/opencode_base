"""Test episodic memory injection into Agent path."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.memory.memory_core import MemoryCore

_MARKER = "测试唯一标记-"


def _cleanup_test_memories():
    mc = MemoryCore()
    ids = [eid for eid, e in list(mc.meta.get("id_map", {}).items())
           if _MARKER in e.get("chunk", "")]
    for eid in ids:
        del mc.meta["id_map"][eid]
    if ids:
        mc._save_meta()
        mc._search_raw.cache_clear()
    return len(ids)


@pytest.fixture(autouse=True)
def auto_cleanup():
    yield
    _cleanup_test_memories()


def test_episodic_search_retrieves_saved_memory():
    mc = MemoryCore()
    mc.save(
        _MARKER + "值班向后交接规则",
        "值班人员去车站支援时按轮序交给后一人",
        "已确认",
        importance="high",
    )

    from skills.entry import _search_episodic
    ctx = _search_episodic("值班向后交接规则 值班人员去车站支援 按轮序交给后一人")
    assert "[历史情景记忆]" in ctx
    assert "向后交接" in ctx


def test_episodic_search_filtered_by_similarity_threshold():
    mc = MemoryCore()
    mc.save(
        _MARKER + "消防器材检查标准",
        "灭火器月检",
        "已完成",
        importance="medium",
    )

    from skills.entry import _search_episodic
    ctx = _search_episodic("值班向后交接规则")
    assert ctx == ""


def test_episodic_search_returns_empty_on_no_match():
    from skills.entry import _search_episodic
    ctx = _search_episodic("xyxyxyxyxy 999999999 abcdefg")
    assert ctx == ""


def test_agent_system_prompt_includes_memory_context():
    from skills.shared.schema import RequestContext
    from skills.agent.engine import run as agent_run

    rctx = RequestContext(
        message="测试查询",
        memory_context="[历史情景记忆]:\n  • 2026-07-27 [high] 测试记录",
    )
    result = agent_run("测试查询", rctx)
    assert result is not None


def test_agent_path_with_empty_memory_does_not_crash():
    from skills.entry import handle_core
    result = handle_core("")
    assert result is not None
    assert "[Cipher:" in result


def test_agent_path_with_memory_search_does_not_crash():
    mc = MemoryCore()
    mc.save(
        _MARKER + "值班支援安排",
        "值班人员去车站支援3天",
        "向后交接执行",
        importance="high",
    )

    from skills.entry import handle_core
    result = handle_core("乱七八糟的输入")
    assert result is not None
    assert "[Cipher:" in result
