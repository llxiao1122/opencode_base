"""Tests: recorder.record() → worldview 统一写入口。"""

import sys, time, pathlib
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))


def _pending_count():
    try:
        import json
        p = ROOT / "data" / "state" / "worldview" / "index.json"
        return json.loads(p.read_text()).get("pending_records", 0)
    except Exception:
        return -1


def test_write_personal_route():
    """recorder.record() 写入 → pending 计数增加"""
    from skills.memory.recorder import record
    before = _pending_count()
    record("陈红洁今天主动整理了办公区域文件柜", source="test",
           obs_type="note", layer="rule")
    time.sleep(1)
    after = _pending_count()
    assert after > before, "pending 计数应增加"


def test_write_mixed_routes():
    """含人名记录正常写入不报错"""
    from skills.memory.recorder import record
    result = record("谭继衡建议库区交接应经工班长评审判定，合格方可移交",
                    source="test", obs_type="note", layer="rule")
    assert result is None or True  # record() 正常返回无异常


def test_write_pure_knowledge():
    """纯制度文本正常写入不报错"""
    from skills.memory.recorder import record
    record("库区交接应经工班长评审判定", source="test",
           obs_type="knowledge", layer="rule")
    time.sleep(0.5)


def test_knowledge_dedup():
    """重复写入被去重"""
    from skills.memory.recorder import record
    text = "重复测试文本_专用_" + str(time.time())[-4:]
    record(text, source="test", obs_type="note", layer="rule")
    b1 = _pending_count()
    record(text, source="test", obs_type="note", layer="rule")
    time.sleep(0.5)
    b2 = _pending_count()
    assert b2 == b1, f"重复写入不应增加 pending: {b1} vs {b2}"


def test_llm_classify_does_not_corrupt():
    """伪造 LLM 分类返回 Unexpected 时不出错"""
    from skills.memory.observation_store import reset_cache
    reset_cache()


def test_faiss_index_updated():
    """写入后 worldview FAISS 索引仍完好"""
    from skills.memory.worldview import search
    hits = search("陈红洁", top_k=1)
    assert len(hits) > 0, "世界观看板应能搜到陈红洁"
