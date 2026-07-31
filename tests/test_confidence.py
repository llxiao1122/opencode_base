"""Phase 3 — FAISS routing + Agent end-to-end tests."""

import sys, json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status, CT
from skills.router.faiss_router import classify


# ── Group A: FAISS confidence computation ──────────────────────────────

EMPTY_CASES = ["", "  ", "\t\n"]
SEED_QUERIES = [
    ("今天有什么任务", "task_query"),
    ("通知各班组明天开会", "event"),
    ("苗笑天是什么样的人", "profile_query"),
    ("灭火器检查周期是多久", "knowledge_retrieve"),
]
NOISE_QUERIES = ["啊啊啊吧吧吧", "。。。", "123456", "x"]


@pytest.mark.parametrize("msg", EMPTY_CASES)
def test_faiss_empty_returns_unknown_zero(msg):
    route, conf = classify(msg)
    assert route == "unknown" and conf == 0.0


@pytest.mark.parametrize("msg,expected_route", SEED_QUERIES)
def test_faiss_seed_high_confidence(msg, expected_route):
    route, conf = classify(msg)
    assert route == expected_route, f"{msg!r} → {route}, want {expected_route}"
    assert conf >= CT.EXECUTE, f"{msg!r} conf={conf} < {CT.EXECUTE}"


@pytest.mark.parametrize("msg", NOISE_QUERIES)
def test_faiss_noise_returns_some_route(msg):
    route, conf = classify(msg)
    assert isinstance(route, str) and route
    assert 0.0 <= conf <= 1.0


def test_faiss_confidence_clamped():
    route, conf = classify("今天有什么任务")
    assert 0.0 <= conf <= 1.0


# ── 人名预检：短查询直返 profile，长叙述不被劫持 ──────────────────

def test_person_name_short_query_still_profile():
    route, conf = classify("苗笑天是什么样的人")
    assert route == "profile_query"
    assert conf >= CT.EXECUTE


def test_person_name_long_narrative_not_hijacked():
    msg = ("今天安排谭继衡完成苗笑天负责模块（工班二级库相关工作），从总库库存将去年"
           "需求计划所提报的物资领出，上午11：30发送他钉钉，下午2：30未读，我担心他"
           "完成不了，遂即提醒")
    route, conf = classify(msg)
    assert route == "event", f"叙述应路由事件层，实际: {route}@{conf}"
    assert conf < CT.HIGH, f"叙述不应进快路径，实际: {conf}"


# ── Group F: Full pipeline end-to-end ──────────────────────────────────

def test_full_pipeline_low_conf_message():
    from skills.entry import handle_core
    result = handle_core("乱七八糟的输入")
    assert result
    assert "[Cipher" in result, f"Expected Cipher prefix, got: {result[:100]}"


def test_full_pipeline_high_conf_event():
    from skills.entry import handle_core
    result = handle_core("通知各班组明天开会检查")
    assert result
    assert "任务已创建" in result or "📋" in result or "Cipher" in result


def test_full_pipeline_high_conf_task():
    from skills.entry import handle_core
    result = handle_core("今天有什么任务")
    assert result
    assert len(result) > 10


def test_full_pipeline_empty_message():
    from skills.entry import handle_core
    result = handle_core("")
    assert result is not None


# ── Group G: Output stability ──────────────────────────────────────────

def test_same_query_10x_identical():
    from skills.entry import handle_core
    rs = [handle_core("明天什么工作安排") for _ in range(10)]
    assert len(set(r for r in rs)) == 1
