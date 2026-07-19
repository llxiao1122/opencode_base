"""
ingestion/validator.py — Data quality checker for batch imports.

Read-only analysis, never modifies data.
Two modes:
    validate(text)   — pre-scan: parse quality + entity match rate
    audit_result(r)  — post-import: event confidence + task conversion rate
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITY_INDEX_PATH = ROOT / "state" / "entity_index.json"


def _load_known_names() -> set:
    """Load all known entity names from entity_index.json."""
    if not ENTITY_INDEX_PATH.exists():
        return set()
    try:
        data = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        return {e["name"] for e in data.get("confirmed_entities", [])}
    except (json.JSONDecodeError, KeyError):
        return set()


def validate(text: str) -> dict:
    """Pre-scan raw text before importing.

    Estimates parse quality and entity recognition rate.
    No pipeline execution — pure structural analysis of parse output.

    Returns:
        {total, with_sender, unknown_sender, avg_content_length,
         type_distribution, parse_quality, entity_match}
    """
    from ingestion.message_parser import parse
    from ingestion.message_classifier import classify

    msgs = parse(text)
    total = len(msgs)
    if total == 0:
        return {
            "total": 0,
            "with_sender": 0,
            "unknown_sender": 0,
            "avg_content_length": 0,
            "type_distribution": {},
            "parse_quality": 0.0,
            "entity_match": 0.0,
        }

    with_sender = 0
    unknown_sender = 0
    total_len = 0
    type_dist = {}
    known_names = _load_known_names()
    sender_hits = 0

    for m in msgs:
        if m.get("sender"):
            with_sender += 1
            if m["sender"] in known_names:
                sender_hits += 1
        else:
            unknown_sender += 1

        total_len += len(m.get("content", ""))
        t = classify(m)
        type_dist[t] = type_dist.get(t, 0) + 1

    avg_len = round(total_len / total, 1)

    # Parse quality: sender detection + content length
    pq = 0.0
    pq += (with_sender / total) * 0.5
    if avg_len >= 10:
        pq += 0.3
    elif avg_len >= 5:
        pq += 0.15

    # Entity match: known senders / messages with senders
    em = round(sender_hits / with_sender, 2) if with_sender > 0 else 0.0

    return {
        "total": total,
        "with_sender": with_sender,
        "unknown_sender": unknown_sender,
        "avg_content_length": avg_len,
        "type_distribution": type_dist,
        "parse_quality": round(pq, 2),
        "entity_match": em,
    }


def audit_result(replay_result: dict) -> dict:
    """Post-import audit of a replay or batch import result.

    Analyzes the processing log for quality indicators:
    event confidence, task conversion rate, observer ratio, ignore rate.

    Returns:
        {total_events, low_confidence, low_confidence_rate,
         event_confidence, task_conversion,
         observer_count, coordinator_count,
         ignored_rate, error_count}
    """
    total = replay_result.get("total_messages", 0)
    events = replay_result.get("events_created", 0)
    tasks = replay_result.get("tasks_created", 0)
    log = replay_result.get("log", [])

    if not log:
        return {
            "total_events": 0,
            "low_confidence": 0,
            "low_confidence_rate": 0.0,
            "event_confidence": 0.0,
            "task_conversion": 0.0,
            "observer_count": 0,
            "coordinator_count": 0,
            "ignored_rate": 0.0,
            "error_count": 0,
        }

    low_conf = sum(1 for e in log if 0 < e.get("confidence", 0) < 0.6)
    observer = sum(1 for e in log if e.get("position") == "observer")
    coordinator = sum(1 for e in log if e.get("position") == "coordinator")
    ignored = replay_result.get("ignored", 0)
    err_count = replay_result.get("errors", 0)

    # Average confidence of log entries that have confidence > 0
    confidences = [e["confidence"] for e in log if e.get("confidence", 0) > 0]
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    # Task conversion: tasks / events
    conversion = round(tasks / events, 2) if events > 0 else 0.0

    return {
        "total_events": events,
        "low_confidence": low_conf,
        "low_confidence_rate": round(low_conf / events, 2) if events > 0 else 0.0,
        "event_confidence": avg_conf,
        "task_conversion": conversion,
        "observer_count": observer,
        "coordinator_count": coordinator,
        "ignored_rate": round(ignored / total, 2) if total > 0 else 0.0,
        "error_count": err_count,
    }
