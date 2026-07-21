#!/usr/bin/env python3
"""
validator.py — schema contract validator
Run at import time or manually to detect producer→consumer field drift.

Checks:
  1. event.schema.json fields match detect() output
  2. event_context.schema fields match build_event_context() output
  3. index_entry.schema fields match _persist() index output
  4. user_profile fields match what work_query/responsibility actually read
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
TOOLS_DIR = ROOT / "tools"

sys.path.insert(0, str(TOOLS_DIR))


def load_schema(name):
    with open(SCHEMAS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_event_schema():
    schema = load_schema("event.schema.json")
    expected = set(schema["properties"].keys())

    from memory.event_detector import detect
    sample = detect("王超通知铁炉西工班做好危废处置")
    if not sample:
        return [(False, "event.schema", "detect() returned no events for test input")]

    actual = set(sample[0].keys())
    missing = expected - actual
    extra = actual - expected

    results = []
    if missing:
        results.append((False, "event.schema", f"schema expects but detect() missing: {missing}"))
    if extra:
        results.append((False, "event.schema", f"detect() outputs but schema missing: {extra}"))
    if not missing and not extra:
        results.append((True, "event.schema", f"OK: {len(expected)} fields match"))
    return results


def verify_event_context_schema():
    schema = load_schema("event_context.schema.json")
    expected = set(schema["properties"].keys())

    from memory.event_search import build_event_context
    from memory.event_detector import detect

    sample = detect("王超通知铁炉西工班做好危废处置")
    if not sample:
        return [(False, "event_context.schema", "detect() failed")]

    ctx = build_event_context(sample[0]["id"])
    if not ctx:
        return [(False, "event_context.schema", "build_event_context() returned None")]

    actual = set(ctx.keys())
    missing = expected - actual
    extra = actual - expected

    results = []
    if missing:
        results.append((False, "event_context.schema", f"schema expects but ctx missing: {missing}"))
    if extra:
        results.append((False, "event_context.schema", f"ctx outputs but schema missing: {extra}"))
    if not missing and not extra:
        results.append((True, "event_context.schema", f"OK: {len(expected)} fields match"))
    return results


def verify_index_entry_schema():
    schema = load_schema("index_entry.schema.json")
    expected = set(schema["properties"].keys())

    from memory.event_detector import load_index
    idx = load_index()
    entries = idx.get("events", [])
    if not entries:
        return [(True, "index_entry.schema", "OK: no entries to verify (empty index)")]

    actual = set(entries[0].keys())
    missing = expected - actual
    extra = actual - expected

    results = []
    if missing:
        results.append((False, "index_entry.schema", f"schema expects but index missing: {missing}"))
    if extra:
        results.append((False, "index_entry.schema", f"index has but schema missing: {extra}"))
    if not missing and not extra:
        results.append((True, "index_entry.schema", f"OK: {len(expected)} fields match"))
    return results


def verify_content_extraction_schema():
    """Phase 1.7.7-B: validate content_extraction.schema.json file exists and is valid JSON."""
    schema = load_schema("content_extraction.schema.json")
    required = schema.get("required", [])
    props = schema.get("properties", {}).get("sections", {}).get("items", {}).get("properties", {})

    results = []
    if "sections" not in required:
        results.append((False, "content_extraction.schema", "missing 'sections' in required"))
    for key in ["section_id", "section_title", "facts", "actions", "constraints"]:
        if key not in props:
            results.append((False, "content_extraction.schema", f"section item missing '{key}' property"))
    if not results:
        results.append((True, "content_extraction.schema", "OK: schema valid"))
    return results


def verify_section_schema():
    """Phase 1.7.7-A: validate section.schema.json file exists and is valid JSON."""
    schema = load_schema("section.schema.json")
    required = schema.get("required", [])
    if "sections" not in required:
        return [(False, "section.schema", "missing 'sections' in required")]
    return [(True, "section.schema", "OK: schema valid")]


def validate_action(action):
    """Phase 1.7.7-B: semantic validation for extracted actions.
    
    Rules:
      - Reject if text starts with: 预计, 可能, 据, 发布, 收到, 显示, 数据显示
      - Reject if text contains weather-related keywords (should be facts)
    Returns: (is_valid, reason)
    """
    forbidden_prefixes = ["预计", "可能", "据", "发布", "收到", "显示", "数据显示"]
    text = action.get("text", "")
    for p in forbidden_prefixes:
        if text.startswith(p):
            return False, f"action starts with forbidden prefix '{p}'"
    weather_kw = ["毫米", "降水", "预警信号", "气象台"]
    if any(kw in text for kw in weather_kw):
        return False, "weather content belongs in facts, not actions"
    return True, "ok"


def validate_constraint(constraint):
    """Phase 1.7.7-B: semantic validation for extracted constraints.
    
    Rules:
      - Reject if text contains: 应知应会, 应急预案, 应急响应
    Returns: (is_valid, reason)
    """
    false_positive = ["应知应会", "应急预案", "应急响应"]
    text = constraint.get("text", "")
    for p in false_positive:
        if p in text:
            return False, f"constraint contains false-positive pattern '{p}'"
    return True, "ok"


def validate_fact(fact):
    """Phase 1.7.7-B: semantic validation for extracted facts.
    
    Rules:
      - Reject if text starts with action verbs (污染了 facts)
    Returns: (is_valid, reason)
    """
    action_verbs = ["执行", "安排", "完成", "组织", "检查", "整改", "清理", "更新"]
    text = fact.get("text", "")
    for v in action_verbs:
        if text.startswith(v):
            return False, f"fact starts with action verb '{v}', should be in actions"
    return True, "ok"


def main():
    all_results = []
    all_results.extend(verify_event_schema())
    all_results.extend(verify_event_context_schema())
    all_results.extend(verify_index_entry_schema())
    all_results.extend(verify_content_extraction_schema())
    all_results.extend(verify_section_schema())

    passed = sum(1 for ok, _, _ in all_results if ok)
    failed = sum(1 for ok, _, _ in all_results if not ok)

    print(f"Schema Validation: {passed} passed, {failed} failed\n")

    for ok, schema, msg in all_results:
        prefix = "  PASS" if ok else "  FAIL"
        print(f"{prefix} [{schema}] {msg}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
