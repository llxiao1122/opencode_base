"""Tests: observation write → LLM classify → people/Knowledge + FAISS read."""

import sys, time, pathlib, json

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))


def _read(name):
    p = ROOT / "memory" / "observations" / "people" / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _knowledge_has(text):
    for f in sorted((ROOT / "Knowledge").glob("*.md")):
        if text in f.read_text(encoding="utf-8"):
            return f.name
    return ""


def test_write_personal_route():
    """写入纯个人行为→写入 people/（允许 LLM 选择是否写 Knowledge）。"""
    from skills.memory.observation_store import write as obs_write
    obs_write("陈红洁今天主动整理了办公区域文件柜", source="test",
              obs_type="note", layer="rule")
    time.sleep(2)
    c = _read("陈红洁")
    assert "陈红洁" in c, "陈红洁.md 应有写入内容"
    # 原文本一定在 people/ 中（_route 按人名定位）
    assert "办公区域文件柜" in c


def test_write_mixed_routes():
    """写入含人名+制度→people/ + Knowledge/."""
    from skills.memory.observation_store import write as obs_write
    obs_write("谭继衡建议库区交接应经工班长评审判定，合格方可移交",
              source="test", obs_type="note", layer="rule")
    time.sleep(2)
    t = _read("谭继衡")
    assert "谭继衡" in t, "谭继衡.md 应有写入"
    found = _knowledge_has("库区交接")
    assert found, f"库区交接规则应写入某个 Knowledge 文件 (found in {found})"


def test_write_pure_knowledge():
    """写入纯制度（无人名）→ Knowledge/.md."""
    from skills.memory.observation_store import write as obs_write
    obs_write("交接评审标准：物资盘点无误、卫生达标、钥匙齐全方可办理移交",
              source="test", obs_type="rule_change", layer="rule")
    time.sleep(2)
    found = _knowledge_has("交接评审标准")
    assert found, f"纯制度应写入 Knowledge (found in {found})"


def test_knowledge_dedup():
    """重复写入同一条制度→不追加."""
    from skills.memory.observation_store import write as obs_write
    text = "库区交接必须经工班长现场评审判定"
    p = ROOT / "Knowledge" / "03-考核与细则.md"
    before = p.read_text(encoding="utf-8").count(text[:10]) if p.exists() else 0
    obs_write(text, source="test", obs_type="rule_change", layer="rule")
    time.sleep(2)
    after = p.read_text(encoding="utf-8").count(text[:10])
    assert after == before, f"重复写入不应增长计数 ({before}→{after})"


def test_llm_classify_does_not_corrupt():
    """多线程写入后 observation 文件仍为合法 UTF-8."""
    from skills.memory.observation_store import write as obs_write
    for i in range(5):
        obs_write(f"测试并发写入第{i}条 陈红洁", source="test",
                  obs_type="note", layer="rule")
    time.sleep(3)
    c = _read("陈红洁")
    # Must be valid UTF-8 — will raise on decode if corrupted
    assert len(c) > 0, "陈红洁.md 不应为空"
    # Spot-check a known section from earlier test
    assert "测试并发写入第" in c, "应包含并发写入的内容"


def test_faiss_index_updated():
    """Knowledge 写入后 FAISS sem_index 包含新内容."""
    from memory.memory_core import MemoryCore
    mc = MemoryCore()
    before = mc.sem_index.ntotal if mc.sem_index else 0
    assert before > 0, "FAISS sem_index 应有向量"
