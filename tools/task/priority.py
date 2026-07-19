"""
task/priority.py — Task priority inference.

Rules only, no LLM. Safety keywords mapped to high priority.
Returns structured dict with value, reason, and rule source for auditability.
"""

HIGH = "high"
NORMAL = "normal"

_SAFETY_KW = ["安全", "消防", "防汛", "暴雨", "应急", "火灾", "严禁", "预警", "整改", "漏水"]


def infer_priority(raw_text: str) -> dict:
    """Return {value, reason, rule} for a given message text."""
    matched = [kw for kw in _SAFETY_KW if kw in raw_text]
    if matched:
        return {
            "value": HIGH,
            "reason": f"安全关键词: {', '.join(matched)}",
            "rule": "safety_keyword_v1",
        }
    return {
        "value": NORMAL,
        "reason": "无安全关键词",
        "rule": "safety_keyword_v1",
    }
