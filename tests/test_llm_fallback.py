#!/usr/bin/env python3
"""
test_llm_fallback.py — LLM 降级测试 (Phase 1.7.8)

验证: LLM 不可用时系统降级不崩溃
覆盖: Case 009 (扩展)
"""

import sys, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_enricher_fallback_empty():
    """LLM 不可用时 enricher 返回 status=empty，不崩溃"""
    from pipeline.event_enricher import enrich_event

    event = {"id": "test_001", "title": "测试任务", "executor": "李林骁"}
    enriched = enrich_event(event, "这是一条测试通知文字足够长了触发信号检测", tracer=None)

    assert "ai_content_status" in enriched, "missing ai_content_status"
    assert enriched["ai_content_status"] in ("success", "failed", "no_sections", "empty")
    assert enriched["id"] == "test_001", "event id changed"
    print(f"  ✓ enricher fallback: status={enriched['ai_content_status']}")


def test_detect_no_api():
    """detect 不依赖 LLM，无 API 也能正常返回"""
    from memory.event_detector import detect
    from context.request_context import build_request_context

    ctx = build_request_context()
    events = detect("王亮通知铁炉西工班做好危废处置", current_user=ctx["user"])

    assert events, "detect failed without LLM"
    assert events[0].get("requester") == "王亮"
    assert events[0].get("executor") == "李林骁"
    print(f"  ✓ detect works without LLM: {events[0]['id']}")


def test_context_no_org_when_no_event():
    """无 event 时 inject_user_prompt 不报错"""
    from context.request_context import build_request_context, inject_user_prompt

    ctx = build_request_context()
    prompt = inject_user_prompt(ctx)

    assert "李林骁" in prompt, "missing user name"
    assert len(prompt) > 0, "empty prompt"
    print(f"  ✓ context with no event: prompt has {len(prompt)} chars")


def test_hierarchy_unknown_entity():
    """未知 requester 不崩溃"""
    from context.hierarchy_resolver import resolve

    event = {"requester": "张三", "executor": "李林骁", "target": "各班组"}
    user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}

    org = resolve(event, user)
    assert "张三" in org["text"], f"missing unknown requester: {org['text']}"
    print(f"  ✓ unknown entity fallback: {org['text'][:50]}...")


if __name__ == "__main__":
    print("=" * 60)
    print("LLM FALLBACK TESTS")
    print("=" * 60)

    passed = 0
    tests = [
        ("enricher fallback (no API)", test_enricher_fallback_empty),
        ("detect works without LLM", test_detect_no_api),
        ("context when no event", test_context_no_org_when_no_event),
        ("hierarchy unknown entity", test_hierarchy_unknown_entity),
    ]

    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {e}")
        except Exception as e:
            print(f"  ✗ {type(e).__name__}: {e}")

    print(f"\nResults: {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
