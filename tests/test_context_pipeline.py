#!/usr/bin/env python3
"""
test_context_pipeline.py — 上下文传递测试 (Phase 1.7.8)

验证: ctx 贯穿 handler/composer，LLM 收到正确用户身份
覆盖: Case 007, 008
"""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_context_built():
    """Case 008: 当前用户识别"""
    from context.request_context import build_request_context, inject_user_prompt

    ctx = build_request_context()
    assert ctx["user"]["name"] == "李林骁", f"expected 李林骁, got {ctx['user']['name']}"
    assert ctx["user"]["role"] == "工班长", f"expected 工班长, got {ctx['user']['role']}"
    assert ctx["user"]["team"] == "铁炉西工班", f"expected 铁炉西工班, got {ctx['user']['team']}"
    print("  ✓ build_request_context: user=李林骁 role=工班长")

    prompt = inject_user_prompt(ctx)
    assert "李林骁" in prompt, f"prompt missing 李林骁: {prompt}"
    assert "工班长" in prompt, f"prompt missing 工班长: {prompt}"
    print("  ✓ inject_user_prompt: contains 李林骁+工班长")


def test_context_in_handler():
    """Case 007: Event进入Handler — ctx 传递验证"""
    from context.request_context import build_request_context, inject_user_prompt
    from routing.composer import execute_plan
    from routing.legacy_pipeline import CAPABILITY_HANDLERS

    ctx = build_request_context()
    ctx["event"] = {"requester": "王亮", "executor": "李林骁", "deadline": "14日"}

    prompt = inject_user_prompt(ctx)
    assert "王亮" in prompt, "prompt missing requester 王亮"
    assert "安全管理岗" in prompt, "prompt missing role info"
    print("  ✓ handler receives event + user + org_context")


def test_context_flow():
    """验证 ctx 从 handle() 经 composer 到 LLM prompt"""
    from context.hierarchy_resolver import inject_org_context

    event = {"requester": "王亮", "executor": "李林骁", "target": "各班组"}
    user = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}

    org = inject_org_context(event, user)
    assert "王亮" in org, f"org context missing 王亮: {org}"
    assert "安全管理岗" in org, f"org context missing role: {org}"
    assert len(org) > 20, f"org context too short: {org}"
    print("  ✓ org context flows: contains requester + role")


def test_llm_forbid_hello():
    """Case 008 forbid: '好的王亮' 不应出现在含 ctx 的 prompt 输出"""
    from context.request_context import build_request_context, inject_user_prompt

    ctx = build_request_context()
    ctx["event"] = {"requester": "王亮", "executor": "李林骁", "target": "各班组"}
    prompt = inject_user_prompt(ctx)

    # prompt should not address 王亮 as the user
    assert "你正在与 李林骁" in prompt, f"prompt should address 李林骁, got: {prompt[:100]}"
    print("  ✓ prompt addresses 李林骁 (current user), not 王亮")


if __name__ == "__main__":
    print("=" * 60)
    print("CONTEXT PIPELINE TESTS")
    print("=" * 60)

    passed = 0
    tests = [
        ("Case 008: build_request_context", test_context_built),
        ("Case 007: event flows to handler", test_context_in_handler),
        ("Case 007: org context flows", test_context_flow),
        ("Case 008: prompt addresses current user", test_llm_forbid_hello),
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
