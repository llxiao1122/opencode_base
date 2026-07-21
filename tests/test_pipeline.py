#!/usr/bin/env python3
"""
test_pipeline.py — Full pipeline regression test.
钉钉消息 → detect → store → search → classify → context → LLM
"""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in [str(ROOT / "skills"), str(ROOT / "skills" / "work"),
          str(ROOT / "skills" / "memory"), str(ROOT / "skills" / "routing")]:
    sys.path.insert(0, p)


REGRESSION_CASES = [
    # 1: 王超通知 → requester/executor/target 不混
    {
        "name": "王超通知铁炉西工班做好危废处置",
        "input": "王超通知铁炉西工班做好危废处置",
        "assert": lambda evt: (
            evt.get("executor") == "李林骁"
            and evt.get("requester") == "王超"
            and evt.get("target") == "铁炉西工班"
        ),
        "fail_msg": "requester/executor/target mismatch",
    },
    # 2: 各工班长安排人员完成危废回收 → role_task, NOT direct_task
    {
        "name": "各工班长安排人员完成危废回收",
        "input": "各工班长安排人员完成危废回收",
        "assert": lambda evt: (
            evt.get("executor") == "李林骁"
            and "各工班长" in str(evt.get("participants", []))
        ),
        "fail_msg": "executor not resolved or participants wrong",
    },
    # 3: 李林骁请假  → should be classified as direct_task for 李林骁
    {
        "name": "李林骁请假",
        "input": "李林骁请假",
        "assert": lambda evt: (
            evt.get("executor") == "李林骁"
            or "李林骁" in str(evt.get("entities", []))
        ),
        "fail_msg": "请假事件未识别李林骁",
    },
]


def run_pipeline_tests():
    from memory.event_detector import detect
    from memory.event_lifecycle import complete
    from memory.event_search import build_event_context
    from work.responsibility import resolve as classify

    passed = 0
    failed = 0

    print("=" * 60)
    print("PIPELINE REGRESSION TEST")
    print("=" * 60)

    # ── Case 1+2+3: detect → verify fields ──
    for case in REGRESSION_CASES:
        print(f"\n[{case['name']}]")
        events = detect(case["input"])
        if not events:
            print(f"  FAIL: no events detected")
            failed += 1
            continue

        evt = events[0]
        ok = case["assert"](evt)
        if ok:
            print(f"  PASS")
            passed += 1
        else:
            print(f"  FAIL: {case['fail_msg']}")
            print(f"  Detail: executor={evt.get('executor')} requester={evt.get('requester')} target={evt.get('target')}")
            failed += 1

    # ── Case 2 follow-up: verify responsibility ──
    print(f"\n[Responsibility check on Case 2]")
    evt2 = detect("各工班长安排人员完成危废回收")
    if evt2:
        ctx = build_event_context(evt2[0]["id"])
        if ctx:
            r = classify(ctx)
            has_role = len(r.get("role_task", [])) > 0
            has_direct = len(r.get("direct_task", [])) > 0
            if has_role and not has_direct:
                print(f"  PASS: role_task=True, direct_task=False (correct)")
                passed += 1
            else:
                print(f"  FAIL: role_task={has_role} direct_task={has_direct} (expected role_task only)")
                failed += 1
        else:
            print(f"  SKIP: no context built")
    else:
        print(f"  SKIP: no event")

    # ── Case 3: verify date filtering ──
    print(f"\n[Date filtering check]")
    from work.work_query import _parse_date_from_query, _resolve_person, _search_events_for_person
    date = _parse_date_from_query("周一我有什么工作")
    person = _resolve_person("周一我有什么工作")
    events = _search_events_for_person(person, query_date=date)

    has_leave = any("请假" in e.get("title", "") for e in events)
    if not has_leave:
        print(f"  PASS: 李林骁请假 excluded from Monday view (date={date})")
        passed += 1
    else:
        print(f"  FAIL: 李林骁请假 still in Monday view")
        failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_pipeline_tests())
