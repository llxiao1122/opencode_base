"""
ingestion/message_parser.py — Raw text → structured Message objects.

Handles common DingTalk group chat formats:
  Date-only headers ("7月19日")
  Sender-marked messages ("王亮：", "苗笑天 2024-08-01 14:30")
  Multi-line content spanning until next sender marker

No judgment, no classification — pure structural parsing.
Output: list of Message dicts {id, timestamp, sender, content, source}.
"""

import re
import hashlib
from datetime import datetime

NOW = datetime.now()


def parse(text: str, allow_missing_time: bool = False) -> list:
    """Split raw multi-message text into individual Message dicts.

    Args:
        text: unstructured DingTalk group chat transcript
        allow_missing_time: if True, timestamp="" when no date header found

    Returns:
        list of dicts: [{id, timestamp, sender, content, source, message_hash}]
    """
    if not text or not text.strip():
        return []

    msgs = []
    default_date = NOW.strftime("%Y-%m-%d")

    # Detect shared date header
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        default_date = f"{NOW.year}-{mo:02d}-{dy:02d}"
    elif allow_missing_time:
        default_date = ""

    # Split into lines, then group by sender marker
    lines = text.strip().split("\n")
    current_sender = None
    current_lines = []

    sender_pat = re.compile(r"^(\S{2,12})[：:]\s*(.*)")
    # Pattern for "董文静(董文静):" format — extract name before parentheses
    at_pat = re.compile(r"^([\u4e00-\u9fffA-Za-z0-9]+)\(")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        sm = sender_pat.match(line)
        if sm:
            # Flush previous message before starting new one
            if current_sender and current_lines:
                msgs.append(_build_msg(msgs, default_date, current_sender, " ".join(current_lines)))
            raw_sender = sm.group(1).strip()
            # Strip parenthetical annotations: "董文静(董文静)" → "董文静"
            am = at_pat.match(raw_sender)
            if am:
                current_sender = am.group(1)
            else:
                current_sender = raw_sender
            content_part = sm.group(2).strip()
            current_lines = [content_part] if content_part else []
        else:
            if current_sender:
                current_lines.append(line)

    # Flush last message
    if current_sender and current_lines:
        msgs.append(_build_msg(msgs, default_date, current_sender, " ".join(current_lines)))

    return msgs


def _build_msg(msgs: list, timestamp: str, sender: str, content: str) -> dict:
    msg = {
        "id": f"msg_{len(msgs) + 1:04d}",
        "timestamp": timestamp,
        "sender": sender,
        "content": content,
        "source": "dingtalk_group",
    }
    raw = f"{sender}|{timestamp}|{content}"
    msg["message_hash"] = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return msg
