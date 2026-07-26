"""test_task_handler.py — task_handler.py 纯函数测试"""

import sys
from pathlib import Path
from datetime import date, datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from skills.agent.handlers.task_query import _detect_scope, _get_daily_work


def test_detect_scope_today():
    assert _detect_scope("今天任务") == "today"
    assert _detect_scope("随便问问") == "today"


def test_detect_scope_tomorrow():
    assert _detect_scope("明天工作") == "tomorrow"
    assert _detect_scope("明日安排") == "tomorrow"


def test_detect_scope_week():
    assert _detect_scope("本周计划") == "week"
    assert _detect_scope("这周工作") == "week"
    assert _detect_scope("这星期任务") == "week"


def test_get_daily_work_output_not_empty():
    result = _get_daily_work("明天", date(2026, 7, 25))
    assert result
    assert isinstance(result, str)


def test_get_daily_work_contains_sections():
    result = _get_daily_work("明天", date(2026, 7, 25))
    assert "【值班】" in result
    assert "【库区负责人】" in result
    assert "【每日固定工作】" in result
    assert "【本月" in result


def test_get_daily_work_duty_person():
    result = _get_daily_work("明天", date(2026, 7, 25))
    assert "当日值班人员:" in result


def test_get_daily_work_zone_chiefs():
    result = _get_daily_work("明天", date(2026, 7, 25))
    # Extract zone lines
    lines = result.split("\n")
    zone_lines = [l for l in lines if "—" in l and l.strip().startswith("立体")]
    assert len(zone_lines) >= 1


def test_material_shed_merged_no_separate_section():
    """材料棚轮值信息不应作为独立章节出现"""
    result = _get_daily_work("明天", date(2026, 7, 25))
    assert "【材料棚轮换】" not in result, "材料棚轮换应与库区负责人合并"
