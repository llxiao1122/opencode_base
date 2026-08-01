"""
memory/behavior.py — 神经可塑性行为参数层。

行为参数是代码决策的可调节"突触权重"——由 reflector 分析模式后调整，
由各决策点消费。参数不是硬编码，而是可被观察→学习的动态配置。

数据: data/state/behavior.json
"""

import json
import logging
import threading
from pathlib import Path

from skills.shared.path import root as _root

logger = logging.getLogger(__name__)

ROOT = _root()
BEHAVIOR_PATH = ROOT / "data" / "state" / "behavior.json"
_LOCK = threading.Lock()

_DEFAULTS = {
    "duty_calculation": {"prefer_entity": True, "correction_count": 0},
    "classify": {"high_confidence": 0.70},
    "correction_tracking": {"last_analysis_count": 0, "total_corrections": 0},
}


def _load() -> dict:
    if not BEHAVIOR_PATH.exists():
        return dict(_DEFAULTS)
    try:
        with _LOCK:
            data = json.loads(BEHAVIOR_PATH.read_text(encoding="utf-8"))
        # merge missing keys from defaults
        for key, val in _DEFAULTS.items():
            if key not in data:
                data[key] = val
        return data
    except Exception:
        return dict(_DEFAULTS)


def _save(data: dict):
    BEHAVIOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        BEHAVIOR_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(key: str, subkey: str | None = None):
    """读取行为参数。get('classify', 'high_confidence') → 0.70"""
    data = _load()
    section = data.get(key, {})
    if subkey:
        return section.get(subkey)
    return section


def set_param(key: str, subkey: str, value):
    """设置行为参数。set_param('classify', 'high_confidence', 0.65)"""
    data = _load()
    if key not in data:
        data[key] = dict(_DEFAULTS.get(key, {}))
    data[key][subkey] = value
    _save(data)
    logger.info("behavior param updated: %s.%s = %s", key, subkey, value)


def increment(key: str, subkey: str, delta: int = 1):
    """自增行为参数。increment('correction_tracking', 'total_corrections')"""
    data = _load()
    if key not in data:
        data[key] = dict(_DEFAULTS.get(key, {}))
    data[key][subkey] = data[key].get(subkey, 0) + delta
    _save(data)


def correction_seen():
    """每次新纠错进入时调用，更新纠错计数。返回是否需要触发模式分析（≥ 3 条新记录）。"""
    data = _load()
    total = data["correction_tracking"]["total_corrections"] + 1
    data["correction_tracking"]["total_corrections"] = total
    new_since_last = total - data["correction_tracking"]["last_analysis_count"]
    _save(data)
    data["duty_calculation"]["correction_count"] = new_since_last
    _save(data)
    return new_since_last >= 3


def mark_analyzed():
    """标记已执行完模式分析，重置计数。"""
    data = _load()
    data["correction_tracking"]["last_analysis_count"] = data["correction_tracking"]["total_corrections"]
    _save(data)
