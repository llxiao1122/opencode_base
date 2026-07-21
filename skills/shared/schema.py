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

    event: Optional[dict] = None
    subject_context: Optional[dict] = None
    record_note: str = ""

    decision: Optional[dict] = None

    result: Optional[dict] = None

    reply: str = ""
