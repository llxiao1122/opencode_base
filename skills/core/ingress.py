"""Layer 0 Ingress — route classification."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills"))

from skills.shared.schema import RequestContext, Status

_RECORD_MARKERS = ["记录", "录入", "记一下", "备忘"]
_TIME_KEYWORDS = ["明天", "今天", "后天", "下周", "下午", "上午", "早上", "晚上"]


class DefaultIngress:
    def build(self, ctx: RequestContext) -> None:
        from skills.routing.query_router import classify
        from skills.shared import has_known_entity

        route = classify(ctx.message)

        ltext = ctx.message.lstrip()
        if any(ltext.startswith(m) for m in _RECORD_MARKERS):
            route = "event"

        if route == "task" and has_known_entity(ctx.message):
            if any(kw in ctx.message for kw in _TIME_KEYWORDS):
                route = "event"

        ctx.route = route
        ctx.status = Status.INGRESS_DONE
