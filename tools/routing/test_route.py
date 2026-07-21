#!/usr/bin/env python3
# DEPRECATED — route_request 已废弃，本测试无对应功能
"""路由测试 —— 验证三层路由框架"""

import sys, time
sys.path.insert(0, "/home/admin/opencode_base/tools")
from routing.route_request import route_request, route_request_detailed

TESTS = [
    # Layer 1 — 硬编码命中
    ("明天谁值班",                              ["G"]),
    ("李林骁请假",                              ["G"]),
    ("暴雨应急预案",                            ["F", "D"]),
    ("基坑积水了",                              ["F", "C"]),
    ("上周考勤台账",                            ["E", "G"]),
    ("灭火器更换周期",                          ["D"]),
    ("塔吊故障排查",                            ["C"]),
    ("总结本周工作",                            ["B"]),
    ("查一下混凝土养护标准",                    ["D"]),
    ("安排陈红洁排查故障",                      ["H", "C", "G"]),
    ("你好",                                    ["A"]),
    # Layer 2 — LLM 语义标签
    ("近期下雨频繁，工地需要注意什么",           ["F", "C"]),
    ("最近有哪些材料要整理归档的",              ["E"]),
    ("帮我看看上周安全检查的问题怎么改",        ["C"]),
    ("这道工序老是出问题，帮我分析一下",        ["C"]),
    ("最近大家都挺累的",                        ["A"]),
    ("学习塔吊操作规程",                        ["I", "D"]),
    ("什么是边坡支护",                          ["I", "F"]),
    # 实体联动
    ("安排王超排查故障",                        ["H", "C", "G"]),
    ("让荆幸斌催一下废旧",                      ["E", "H", "G"]),
    # 缓存测试
    ("基坑积水怎么处理",                        ["F"]),
    ("基坑积水怎么处理",                        ["F"]),
]

print("=" * 60)
print("路由测试")
print("=" * 60)

passed = 0
failed = 0
for text, expected in TESTS:
    start = time.time()
    result = route_request(text)
    elapsed = (time.time() - start) * 1000
    status = "✓" if result == expected else f"✗ (expected {expected})"
    if result == expected:
        passed += 1
    else:
        failed += 1
    result_str = "/".join(result)
    print(f"  {status} | {elapsed:6.1f}ms | {text[:38]:38s} → {result_str}")

print(f"\n{passed} passed, {failed} failed, {len(TESTS)} total")

# Phase 1.2: route_request_detailed
print()
print("=" * 60)
print("detailed 模式")
print("=" * 60)

dr1 = route_request_detailed("安排王超排查故障")
assert dr1["routes"] == route_request("安排王超排查故障"), "routes should match"
assert "pending_hints" in dr1, "must have pending_hints"
print(f"  安排王超排查故障 → routes={dr1['routes']} hints={len(dr1['pending_hints'])}")

dr2 = route_request_detailed("你好")
assert dr2["routes"] == ["A"], "greeting stays A"
assert dr2["pending_hints"] == [], "greeting should have no pending hints"
print(f"  你好 → routes={dr2['routes']} hints={len(dr2['pending_hints'])}")

dr3 = route_request_detailed("明天谁值班")
assert dr3["routes"] == route_request("明天谁值班")
print(f"  明天谁值班 → routes={dr3['routes']} hints={len(dr3['pending_hints'])}")

print()
print("detailed mode: all assertions passed")

