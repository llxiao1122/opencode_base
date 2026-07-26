"""
correction/logger.py — Decision log writer.

Appends one JSON line to state/decision_log.jsonl after every pipeline run.
No guessing, no marking. Just raw facts.
"""

import json, logging, os
from datetime import datetime
from pathlib import Path
from typing import Optional

from skills.shared.schema import RequestContext

logger = logging.getLogger(__name__)

_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "state" / "decision_log.jsonl"

_session: str = datetime.now().strftime("%Y%m%d%H%M%S")
_seq: int = 0


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def append(ctx: RequestContext, reply: str, tool_id: str = ""):
    """Append one decision record after pipeline finishes."""
    if not ctx.message.strip():
        return

    try:
        record = {
            "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "session": _session,
            "seq": _next_seq(),
            "msg": ctx.message[:200],
            "conf": round(ctx.confidence, 4),
            "reply_len": len(reply or ""),
            "has_confirm": ("?" in reply or "？" in reply) and ("需要" in reply or "是否" in reply),
            "has_hedge": any(w in reply for w in ["推测", "不太确定", "可能不准确", "仅供参考"]),
        }
        tid = tool_id or ctx.route or ""
        if tid:
            record["tool_id"] = tid

        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("append decision log failed: %s", e, exc_info=True)
