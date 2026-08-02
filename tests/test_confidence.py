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
    ("通知各班组明天开会", "notification_push"),
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


# ── 周末无工作 + 已完成演练过滤 + 值班锚点 ─────────────────────────

def test_weekend_shows_patrol_duty():
    from datetime import date
    from skills.agent.handlers.task_query import _get_daily_work
    sat = _get_daily_work(date(2026, 8, 1))
    assert "周末巡库" in sat, f"周六应展示巡库专项: {sat}"
    assert "17 点前" in sat, "应包含完成时限"
    assert "当日值班人员" in sat, f"周末也应展示值班人员: {sat}"
    assert "张志斌" in sat, f"8/1 应展示张志斌值班: {sat}"
    sun = _get_daily_work(date(2026, 8, 2))
    assert "周末巡库" in sun, "周日也应展示巡库"
    assert "杨梦卓" in sun, f"8/2 应展示杨梦卓值班: {sun}"

    # 非周末不展示巡库
    mon = _get_daily_work(date(2026, 8, 3))
    assert "周末巡库" not in mon, "周一不应展示周末巡库"


def test_completed_exercise_filtered():
    from datetime import date
    from skills.agent.handlers.task_query import _get_daily_work
    # 7 月演练已完成 → 7 月查询不展示
    work_jul = _get_daily_work(date(2026, 7, 27))
    assert "仓库火灾" not in work_jul, f"7月已完成演练仍展示: {work_jul}"
    # 8 月演练未完成 → 8 月查询正常展示
    work_aug = _get_daily_work(date(2026, 8, 3))
    assert "叉车事故应急演练" in work_aug, f"8月未完成演练缺失: {work_aug}"


def test_duty_anchor_monday_tuesday():
    from datetime import date
    from skills.agent.handlers.task_query import _get_duty_person
    md = (ROOT / "Knowledge" / "01-仓储业务" / "00-日常工作指引.md").read_text()
    assert _get_duty_person(date(2026, 8, 1), md=md) == "张志斌", "8/1 应为张志斌（主人确认）"
    assert _get_duty_person(date(2026, 8, 3), md=md) == "苗笑天", "8/3 周一应为苗笑天"


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
