#!/usr/bin/env python3
"""
test_responsibility.py — Responsibility Resolver Benchmark
Uses real detect() → build_event_context() → classify() pipeline.
"""

import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in [str(ROOT / "skills"), str(ROOT / "skills" / "work"),
          str(ROOT / "skills" / "memory"), str(ROOT / "skills" / "routing")]:
    sys.path.insert(0, p)


def build_event_ctx(text):
    from memory.event_detector import detect
    from memory.event_search import build_event_context

    events = detect(text)
    if not events:
        return None
    ctx = build_event_context(events[0]["id"])
    return ctx


def run_benchmark():
    cases_file = ROOT / "tests" / "responsibility_cases.json"
    cases = json.loads(cases_file.read_text(encoding="utf-8"))

    from work.responsibility import resolve as classify

    stats = {"direct_task": {"tp": 0, "fp": 0, "fn": 0},
             "role_task": {"tp": 0, "fp": 0, "fn": 0},
             "team_attention": {"tp": 0, "fp": 0, "fn": 0}}
    errors = []
    skipped = 0

    for i, case in enumerate(cases):
        ctx = build_event_ctx(case["text"])
        if not ctx:
            skipped += 1
            continue

        result = classify(ctx)
        actual = {
            "direct_task": len(result.get("direct_task", [])) > 0,
            "role_task": len(result.get("role_task", [])) > 0,
            "team_attention": len(result.get("team_attention", [])) > 0,
        }
        expect = case["expect"]

        for level in ["direct_task", "role_task", "team_attention"]:
            if actual[level] and expect[level]:
                stats[level]["tp"] += 1
            elif actual[level] and not expect[level]:
                stats[level]["fp"] += 1
                errors.append((i, case["text"], level, f"FP: got True, expected False | executors={ctx['people'].get('executors',[])}"))
            elif not actual[level] and expect[level]:
                stats[level]["fn"] += 1
                errors.append((i, case["text"], level, f"FN: got False, expected True | executors={ctx['people'].get('executors',[])}"))

    print("=" * 60)
    print("RESPONSIBILITY BENCHMARK")
    print(f"Skipped (no event detected): {skipped}/{len(cases)}")
    print("=" * 60)

    for level in ["direct_task", "role_task", "team_attention"]:
        tp = stats[level]["tp"]
        fp = stats[level]["fp"]
        fn = stats[level]["fn"]
        total_true = tp + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        print(f"\n[{level}]")
        print(f"  Expected={total_true}  TP={tp}  FP={fp}  FN={fn}")
        print(f"  Precision={precision:.2f}  Recall={recall:.2f}  F1={f1:.2f}")

    total_cases = len(cases) - skipped
    total_errors = len(errors)
    print(f"\n{'=' * 60}")
    print(f"Tested: {total_cases}  Errors: {total_errors}")

    if errors:
        print(f"\nERRORS ({total_errors}):")
        for idx, text, level, msg in errors:
            print(f"  [#{idx}] [{level}] {msg}")
            print(f"         '{text}'")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(run_benchmark())
