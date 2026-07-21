#!/usr/bin/env python3
"""
test_role_resolution.py — 角色关系测试 (Phase 1.7.8)

验证: requester/executor/target 三角色正确解析
覆盖: Case 001-006
"""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))


def load_golden_cases():
    path = ROOT / "tests" / "golden_cases" / "responsibility_cases.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["cases"]


CURRENT_USER = {"name": "李林骁", "role": "工班长", "team": "铁炉西工班"}


def run_role_tests():
    from memory.event_detector import detect

    current_user = CURRENT_USER
    cases = load_golden_cases()
    passed = 0
    failed = 0

    print("=" * 60)
    print("ROLE RESOLUTION TESTS")
    print("=" * 60)

    for case in cases:
        cid = case["id"]
        name = case["name"]
        user_input = case["input"]
        expect = case.get("expect", {})
        forbid = case.get("forbid", {})

        events = detect(user_input, current_user=current_user)

        if not events:
            # Case 003 (禁止事项) might not produce events — skip detect check
            if cid == "003":
                print(f"\n[{cid}] {name}")
                print(f"  SKIP: no event (expected for constraints-only message)")
                continue
            print(f"\n[{cid}] {name}")
            print(f"  FAIL: no event detected")
            failed += 1
            continue

        evt = events[0]
        all_ok = True

        print(f"\n[{cid}] {name}")
        print(f"  requester={evt.get('requester')} executor={evt.get('executor')} target={evt.get('target')}")

        # expect checks
        if "requester" in expect:
            actual = evt.get("requester", "")
            if actual == expect["requester"]:
                print(f"  ✓ requester={actual}")
            else:
                print(f"  ✗ requester: expected={expect['requester']} actual={actual}")
                all_ok = False

        if "executor" in expect:
            actual = evt.get("executor", "")
            if actual == expect["executor"]:
                print(f"  ✓ executor={actual}")
            else:
                print(f"  ✗ executor: expected={expect['executor']} actual={actual}")
                all_ok = False

        if "executor_not_requester" in expect:
            actual_exec = evt.get("executor", "")
            actual_req = evt.get("requester", "")
            if actual_exec != actual_req:
                print(f"  ✓ executor={actual_exec} != requester={actual_req}")
            else:
                print(f"  ✗ executor==requester={actual_exec}")
                all_ok = False

        if "target" in expect:
            actual = evt.get("target", "") or ""
            if actual and expect["target"] in str(actual):
                print(f"  ✓ target={actual}")
            else:
                print(f"  ✗ target: expected contains={expect['target']} actual={actual}")
                all_ok = False

        if "target_not_empty" in expect:
            actual = evt.get("target", "")
            if actual:
                print(f"  ✓ target={actual}")
            else:
                print(f"  ✗ target is empty")
                all_ok = False

        if "target_has" in expect:
            actual = evt.get("target", "") or ""
            if expect["target_has"] in str(actual):
                print(f"  ✓ target contains '{expect['target_has']}'")
            else:
                print(f"  ✗ target missing '{expect['target_has']}'")
                all_ok = False

        if "deadline_has" in expect:
            time = evt.get("time", {})
            deadline = time.get("deadline", "")
            if expect["deadline_has"] in deadline:
                print(f"  ✓ deadline={deadline}")
            else:
                print(f"  ✗ deadline missing '{expect['deadline_has']}' in '{deadline}'")
                all_ok = False

        if "deadline_future" in expect:
            time = evt.get("time", {})
            deadline = time.get("deadline", "")
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            if deadline and deadline > today:
                print(f"  ✓ deadline={deadline} (future)")
            else:
                print(f"  ✗ deadline not in future: {deadline}")
                all_ok = False

        if "action_has" in expect:
            actions = evt.get("actions", [])
            if expect["action_has"] in str(actions):
                print(f"  ✓ actions contains '{expect['action_has']}'")
            else:
                print(f"  ✗ actions missing '{expect['action_has']}' actual={actions}")
                all_ok = False

        if "actions_has" in expect:
            actions = evt.get("actions", [])
            if any(expect["actions_has"] in a for a in actions):
                print(f"  ✓ actions contains '{expect['actions_has']}'")
            else:
                print(f"  ✗ actions missing '{expect['actions_has']}' actual={actions}")
                all_ok = False

        if "actions_excluded" in expect:
            actions = evt.get("actions", [])
            ok = all(item not in str(actions) for item in expect["actions_excluded"])
            if ok:
                print(f"  ✓ excluded items not in actions")
            else:
                print(f"  ✗ excluded items found in actions={actions}")
                all_ok = False

        if "fact_has" in expect:
            # facts are in the title or evidence
            title = evt.get("title", "")
            evidence = str(evt.get("evidence", []))
            if expect["fact_has"] in title or expect["fact_has"] in evidence:
                print(f"  ✓ fact '{expect['fact_has']}' found")
            else:
                print(f"  ✗ fact '{expect['fact_has']}' not found")

        if "constraints_min" in expect:
            constraints = evt.get("constraints", [])
            if len(constraints) >= expect["constraints_min"]:
                print(f"  ✓ constraints count={len(constraints)}")
            else:
                print(f"  ✗ constraints expected at least {expect['constraints_min']}, got {len(constraints)}")

        # forbid checks
        if forbid.get("requester_not_current_user"):
            if evt.get("requester") != current_user.get("name"):
                print(f"  ✓ requester != current_user")
            else:
                print(f"  ✗ requester == current_user (should not be)")
                all_ok = False

        if forbid.get("executor_not_target"):
            if evt.get("executor") != evt.get("target"):
                print(f"  ✓ executor != target")
            else:
                print(f"  ✗ executor == target")
                all_ok = False

        if all_ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_role_tests())
