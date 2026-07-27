"""
skills/shared/tracer.py — Agent 决策调用链追踪。

每次 LLM 调用产生一个 trace（trace_id + parent_id 树），
记录 request / response / duration / error，最终写入 trace JSON。
"""
import logging, json, time, uuid
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


def _new_id() -> str:
    short = uuid.uuid4().hex[:8]
    return f"cip-{time.strftime('%Y%m%d-%H%M%S')}-{short}"


class Tracer:
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or _new_id()
        self.spans: list[dict] = []
        self._stack: list[str] = []

    @contextmanager
    def span(self, name: str, **tags):
        parent = self._stack[-1] if self._stack else None
        self._stack.append(name)
        start = time.time()
        try:
            yield
        except Exception as e:
            tags["error"] = str(e)[:200]
            raise
        finally:
            elapsed_ms = round((time.time() - start) * 1000)
            self.spans.append({
                "name": name,
                "parent": parent,
                "elapsed_ms": elapsed_ms,
                **tags,
            })
            self._stack.pop()

    def dump(self):
        if not self.spans:
            return
        total_ms = sum(s["elapsed_ms"] for s in self.spans)
        payload = {
            "trace_id": self.trace_id,
            "total_ms": total_ms,
            "spans": self.spans,
        }
        logger.info("[TRACE] %s", json.dumps(payload, ensure_ascii=False))
