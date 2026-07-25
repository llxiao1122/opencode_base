"""
shared/schema.py — 统一数据合约 (Phase 1).

所有层消费同一协议：
  RequestContext 贯穿 Pipeline，每层只写自己的字段。
  Status 控制流程，error 传递错误。
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List


class CT:
    """置信度阈值统一收拢——调优只改这里"""
    HIGH    = 0.7   # L5 确定性语气水线
    EXECUTE = 0.6   # L2/L4 正常提取与自动建任务水线
    HEDGE   = 0.5   # L5 模棱两可语气水线
    CONFIRM = 0.4   # L4 挂起待确认 / L5 追问触发


class Status(Enum):
    PENDING = "pending"
    INGRESS_DONE = "ingress_done"
    INTENT_DONE = "intent_done"
    REASONING_DONE = "reasoning_done"
    EXECUTION_DONE = "execution_done"
    DONE = "done"
    ERROR = "error"
    SKIP_REMAINING = "skip_remaining"


class ValueDimension(Enum):
    SAFETY = "safety"
    EFFICIENCY = "efficiency"
    COMPLIANCE = "compliance"
    COLLABORATION = "collaboration"
    GROWTH = "growth"


@dataclass
class ValuedHypothesis:
    hypothesis_id: str
    statement: str
    dimension_scores: dict[str, float]
    alignment: str
    recommendation: str
    tags: list[str] = field(default_factory=list)


@dataclass
class RequestContext:
    message: str
    user: Optional[dict] = None
    channel: str = "cli"
    request_id: str = ""
    status: Status = Status.PENDING
    error: Optional[str] = None

    route: Optional[str] = None
    confidence: float = 0.0

    event: Optional[dict] = None
    subject_context: Optional[dict] = None
    record_note: str = ""

    decision: Optional[dict] = None

    result: Optional[dict] = None

    reply: str = ""
