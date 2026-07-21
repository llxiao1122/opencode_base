"""
shared/interfaces.py — Layer 接口定义 (Protocol).

仅类型提示用途，不强制实现。
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skills.shared.schema import RequestContext


class Ingress(Protocol):
    def build(self, ctx: RequestContext) -> None: ...


class IntentExtractor(Protocol):
    def extract(self, ctx: RequestContext) -> None: ...


class ReasoningEngine(Protocol):
    def reason(self, ctx: RequestContext) -> None: ...


class Executor(Protocol):
    def execute(self, ctx: RequestContext) -> None: ...


class ResponseBuilder(Protocol):
    def respond(self, ctx: RequestContext) -> str: ...


class Reflector(Protocol):
    def reflect(self, ctx: RequestContext) -> None: ...
