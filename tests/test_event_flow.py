#!/usr/bin/env python3
"""
test_event_flow.py — 事件流水线测试。

注：detect 管道已于 2026-07-30 停用（世界观体系替代），
    这些测试仅验证停用后接口返回空列表不报错。
"""

import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))


CURRENT_USER = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}


def test_event_schema():
    """验证 detect 停用后返回空列表"""
    from memory.detect import detect
    events = detect("王亮在钉钉群各班组督促一下", current_user=CURRENT_USER)
    assert events == [], "detect 应返回空列表（已停用）"


def test_event_persist():
    """验证停用后不写任何数据"""
    from memory.detect import detect
    events = detect("王亮通知铁炉西工班做好危废处置", current_user=CURRENT_USER)
    assert events == [], "detect 已停用"


def test_detect_timing():
    """验证停用后瞬时返回（不执行任何逻辑）"""
    from memory.detect import detect
    t0 = time.time()
    events = detect("王亮通知铁炉西工班做好危废处置", current_user=CURRENT_USER)
    elapsed = (time.time() - t0) * 1000
    assert events == [], "detect 已停用"
    assert elapsed < 100, f"停用后 detect 应瞬时返回: {elapsed}ms"
