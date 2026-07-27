"""
shared/schema.py — 统一数据合约 (Phase 3).

RequestContext 贯穿 Agent 路径。
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
    DONE = "done"
    ERROR = "error"


class ObservationType(str, Enum):
    EVENT = "event"
    TASK_CREATED = "task_created"
    TASK_FEEDBACK = "task_feedback"
    NOTIFICATION = "notification"
    REFLECTION = "reflection"
    PATTERN = "pattern"
    CONCLUSION = "conclusion"
    PROBE = "probe"


class ObservationLayer(str, Enum):
    RULE = "rule"
    PATTERN = "pattern"
    CONCLUSION = "conclusion"


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
    trace_id: str = ""
    status: Status = Status.PENDING
    error: Optional[str] = None

    route: Optional[str] = None
    confidence: float = 0.0

    event: Optional[dict] = None
    subject_context: Optional[dict] = None
    record_note: str = ""

    decision: Optional[dict] = None

    memory_context: Optional[str] = None

    result: Optional[dict] = None

    reply: str = ""
