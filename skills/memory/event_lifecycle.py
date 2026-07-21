"""
event_lifecycle.py — Event Lifecycle Manager
Status transitions: detected→active→completed/cancelled→archived; expired auto.
Message-driven updates via update_from_message().
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from memory.event_detector import change_status, load_index

COMPLETE_WORDS = ["完成", "结束了", "已处理", "已关闭", "已完成", "搞定了", "处理好了"]
CANCEL_WORDS = ["取消", "暂停", "终止", "不做了", "撤销"]
CONFIRM_WORDS = ["确认", "开始", "启动", "执行", "安排"]


def complete(event_id):
    return change_status(event_id, "completed")


def cancel(event_id):
    return change_status(event_id, "cancelled")


def confirm(event_id):
    return change_status(event_id, "active")


def expire(event_id):
    return change_status(event_id, "expired")


def _extract_entities_from_text(text):
    try:
        from routing.entity_resolver import resolve_entities

        resolved = resolve_entities(text)
        return [e["name"] for e in resolved.get("entities", [])]
    except Exception:
        return []


def _event_detail_text(event_id):
    index = load_index()
    for e in index.get("events", []):
        if e["id"] == event_id:
            status = e.get("status", "active")
            detail_path = (
                Path(__file__).resolve().parent.parent.parent
                / "memory" / "events" / status / f"{event_id}.json"
            )
            if detail_path.exists():
                with open(detail_path, "r", encoding="utf-8") as f:
                    detail = json.load(f)
                parts = [detail.get("title", "")]
                for item in detail.get("items", []):
                    parts.append(item.get("text", ""))
                return " ".join(parts)
    return ""


def _event_matches_message(event_meta, entity_names, text):
    owners = event_meta.get("owners", [])
    if any(owner in entity_names for owner in owners):
        return True

    title = event_meta.get("title", "")
    for name in entity_names:
        if name in title:
            return True

    title_words = title.replace("，", ",").replace("、", ",").replace("：", ",")
    for word in title_words.split(","):
        word = word.strip()
        if len(word) >= 2 and word in text:
            return True

    detail_text = _event_detail_text(event_meta["id"])
    if detail_text:
        keywords = []
        for w in re.split(r"[，。；：、\s]", text):
            w = w.strip()
            if len(w) >= 2 and w not in ("已经", "处理", "完成", "本次", "可能", "进行"):
                keywords.append(w)
        for kw in keywords:
            if kw in detail_text:
                return True

        for kw in keywords:
            for n in (2, 3):
                for i in range(len(kw) - n + 1):
                    ng = kw[i:i + n]
                    if ng in detail_text:
                        return True

    return False


def _score_event_for_message(event_meta, entity_names, text):
    score = 0

    owners = event_meta.get("owners", [])
    if any(owner in entity_names for owner in owners):
        score += 3

    title = event_meta.get("title", "")
    for name in entity_names:
        if name in title:
            score += 2
            break

    # Title words in user message → strong signal
    for sep in "，,、：；":
        title = title.replace(sep, ",")
    for tw in title.split(","):
        tw = tw.strip()
        if len(tw) >= 2 and tw in text:
            score += 2

    detail_text = _event_detail_text(event_meta["id"])
    if not detail_text:
        return score

    keywords = []
    for w in re.split(r"[，。；：、\s]", text):
        w = w.strip()
        if len(w) >= 2 and w not in ("已经", "处理", "完成", "本次", "可能", "进行", "具体"):
            keywords.append(w)

    STOP_NGRAMS = {"完成", "处理", "已经", "本次", "可能", "进行", "具体", "通知", "安排"}

    for kw in keywords:
        if kw in detail_text:
            score += 2
        else:
            for n in (2, 3):
                for i in range(len(kw) - n + 1):
                    ng = kw[i : i + n]
                    if ng in STOP_NGRAMS:
                        continue
                    if ng in detail_text:
                        score += 1

    return score

def update_from_message(text):
    if not text.strip():
        return []

    entity_names = _extract_entities_from_text(text)
    index = load_index()
    active_events = [
        e
        for e in index.get("events", [])
        if e["status"] in ("active", "detected")
    ]

    has_complete = any(w in text for w in COMPLETE_WORDS)
    has_cancel = any(w in text for w in CANCEL_WORDS)
    has_confirm = any(w in text for w in CONFIRM_WORDS)

    affected = []
    for evt in active_events:
        score = _score_event_for_message(evt, entity_names, text)
        # Completion intent bonus: if message has completion word AND any topic
        # overlap exists, treat as enough to trigger completion
        if has_complete and score > 0:
            score += 1
        if score < 2:
            continue

        if has_cancel:
            change_status(evt["id"], "cancelled")
            affected.append(("cancelled", evt["id"]))
        elif has_complete:
            change_status(evt["id"], "completed")
            affected.append(("completed", evt["id"]))
        elif evt["status"] == "detected" and has_confirm:
            change_status(evt["id"], "active")
            affected.append(("confirmed", evt["id"]))

    return affected
