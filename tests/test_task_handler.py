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
    result = _get_daily_work( date(2026, 7, 24))
    assert result
    assert isinstance(result, str)


def test_get_daily_work_contains_sections():
    result = _get_daily_work( date(2026, 7, 24))
    assert "【值班】" in result
    assert "【库区负责人】" in result
    assert "【每日固定工作】" in result
    assert "【本月" in result


def test_get_daily_work_duty_person():
    result = _get_daily_work( date(2026, 7, 24))
    assert "当日值班人员:" in result


def test_get_daily_work_zone_chiefs():
    result = _get_daily_work( date(2026, 7, 24))
    # Extract zone lines
    lines = result.split("\n")
    zone_lines = [l for l in lines if "—" in l and l.strip().startswith("立体")]
    assert len(zone_lines) >= 1


def test_material_shed_merged_no_separate_section():
    """材料棚轮值信息不应作为独立章节出现"""
    result = _get_daily_work( date(2026, 7, 24))
    assert "【材料棚轮换】" not in result, "材料棚轮换应与库区负责人合并"


# ── build_title 规格保留 ──────────────────────────────────────────

def test_build_title_keeps_spec_full():
    from skills.shared.task_format import build_title
    spec = ("提报编码申请：手动油桶装卸车[通用类;/;/;额定载重不小于300kg，脚踩液压式，"
            "钢塑两用，最大升起高度离地不小于1.0米，车身整体高度不大于1.85米，复式加强"
            "链条，单鹰嘴式自动机械叼扣，带刹车轮] 按通用类走")
    title = build_title(spec, spec, "2026-08-03")
    assert "带刹车轮" in title, "规格尾部不得被裁剪"
    assert "300kg" in title and "1.85米" in title, "规格细节应完整"


def test_build_title_plain_still_truncated():
    from skills.shared.task_format import build_title
    long_text = "请明天上午去大件库区检查消防器材是否过期并登记台账后反馈结果"
    title = build_title(long_text, long_text, "")
    assert len(title) < 50, "普通长文本仍应截断保持简洁"
