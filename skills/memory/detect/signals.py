"""
memory/detect/signals.py — Event signal detection + confidence scoring.

All functions are module-internal (prefixed with _).
Exposed via memory/detect/__init__.py's re-export of detect().
"""

import re
from datetime import datetime, timedelta

from pathlib import Path as _Path
_sys_root = _Path(__file__).resolve().parent.parent.parent.parent

ACTION_VERBS = [
    "安排", "通知", "协调", "督促", "要求",
    "检查", "整改", "排查", "巡检",
    "办理", "上报", "审批", "验收", "移交", "登记",
    "发放", "领取",
    "启动", "暂停", "恢复", "调整",
    "分配", "部署", "汇总", "跟踪", "组织",
    "回复", "提交", "报备", "确认",
    "执行",
]

TIME_PATTERNS = [
    (r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", "iso_date"),
    (r"(\d{1,2}月\d{1,2}日)", "cn_date"),
    (r"(\d{1,2}月)", "cn_month"),
    (r"明[日天]起?(至|到)?(下?\w{1,3})?", "relative"),
    (r"(今日|今天)(起|开始)?", "today"),
    (r"(下?周[一二三四五六日])", "weekday"),
    (r"(\d+)分钟前", "minutes_ago"),
    (r"即日起", "effective"),
    (r"截止日?期?", "deadline_marker"),
    (r"(\d+)月前", "before_month"),
    (r"(\d{1,2}日)(下班前|之前|前)?", "day_only"),
    (r"下?班前", "end_of_work"),
    (r"立即|马上|尽快|抓紧", "immediate"),
    (r"至\s*(\d{1,2}月\d{1,2}日)", "date_range_end"),
]

ANNOUNCE_PATTERNS = [
    r"通知", r"知悉", r"请各", r"各工班",
    r"根据.*指示", r"按照.*要求", r"根据.*安排",
    r"经.*研究", r"经.*决定",
    r"预警(信号)?", r"应急(预案|响应)?", r"演练",
]

EVENT_KEYWORDS = ["预警", "迎检", "演练", "会议", "通报", "提醒", "专项", "漏水"]
EMERGENCY_KEYWORDS = ["漏水", "火灾", "停电", "塌陷", "积水"]

ROLE_WORDS = ["各工班长", "各工班", "各库区", "各班组", "全体人员", "所有工班",
              "各部门", "相关人员", "责任人", "负责人", "值班人员", "管理人员"]

NUMBERED_PATTERN = re.compile(r"(?:^|\n)\s*\d+[.、)]\s*", re.MULTILINE)


def _signal_count(text, entities_found, participants):
    signals = 0

    has_action = any(v in text for v in ACTION_VERBS)
    has_time = any(re.search(pat, text) for pat, _ in TIME_PATTERNS)
    if has_action and has_time:
        signals += 1

    if has_action and entities_found:
        signals += 1

    if NUMBERED_PATTERN.search(text) and has_action:
        signals += 1

    has_announce = any(re.search(p, text) for p in ANNOUNCE_PATTERNS)
    if has_announce and (has_time or has_action):
        signals += 1

    has_role = any(r in text for r in ROLE_WORDS)
    if has_action and has_role:
        signals += 1

    has_keyword = any(kw in text for kw in EVENT_KEYWORDS)
    if has_keyword and (has_time or has_role or participants):
        signals += 1

    return signals


def _compute_confidence(signals, entities_found, items_found, time_found):
    conf = 0.5
    conf += signals * 0.10
    if entities_found:
        conf += 0.08
    if items_found:
        conf += 0.12
    if time_found:
        conf += 0.10
    return round(min(0.95, conf), 2)
