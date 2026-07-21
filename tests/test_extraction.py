#!/usr/bin/env python3
"""
test_extraction.py — AI Content Extractor Tests (Phase 1.7.7-B)
Golden cases: section_parser → ai_content_extractor → validator → assertions.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT / "schemas"))

from ingestion.section_parser import parse_sections
from ingestion.ai_content_extractor import extract_content


def load_cases():
    case_file = ROOT / "tests" / "golden" / "extraction_cases.json"
    with open(case_file, "r", encoding="utf-8") as f:
        return json.load(f)["cases"]


def _all_texts(sections, field="actions"):
    texts = []
    for s in sections:
        for item in s.get(field, []):
            if isinstance(item, dict):
                texts.append(item.get("text", ""))
    return texts


def _all_texts_flat(sections, field="facts"):
    texts = []
    for s in sections:
        for item in s.get(field, []):
            if isinstance(item, dict):
                texts.append(item.get("text", ""))
    return texts


def check_expect(extracted_sections, expect):
    errors = []
    actions = _all_texts(extracted_sections, "actions")
    constraints = _all_texts(extracted_sections, "constraints")
    facts = _all_texts_flat(extracted_sections, "facts")

    all_actions_text = " ".join(actions)
    all_constraints_text = " ".join(constraints)
    all_facts_text = " ".join(facts)

    # Negative checks: these must NOT appear in actions
    for forbidden in expect.get("no_action_with_text", []):
        for a in actions:
            if forbidden in a:
                errors.append(f"forbidden text '{forbidden}' found in action: '{a[:60]}'")

    # Forbidden in facts
    for forbidden in expect.get("no_fact_with_text", []):
        for f in facts:
            if forbidden in f:
                errors.append(f"forbidden text '{forbidden}' found in fact: '{f[:60]}'")

    # Positive action checks
    for expected in expect.get("has_action_with_text", []):
        if expected not in all_actions_text:
            errors.append(f"expected text '{expected}' not found in any action")

    # Positive constraint checks
    for expected in expect.get("has_constraint_with_text", []):
        if expected not in all_constraints_text:
            errors.append(f"expected text '{expected}' not found in any constraint")

    # Positive fact checks
    for expected in expect.get("has_fact_with_text", []):
        if expected not in all_facts_text:
            errors.append(f"expected text '{expected}' not found in any fact")

    # Count checks
    if "min_actions_total" in expect:
        if len(actions) < expect["min_actions_total"]:
            errors.append(f"min_actions_total: expected >={expect['min_actions_total']}, got {len(actions)}")

    if "max_actions_total" in expect:
        if len(actions) > expect["max_actions_total"]:
            errors.append(f"max_actions_total: expected <={expect['max_actions_total']}, got {len(actions)}")

    if "min_constraints_total" in expect:
        if len(constraints) < expect["min_constraints_total"]:
            errors.append(f"min_constraints_total: expected >={expect['min_constraints_total']}, got {len(constraints)}")

    if "max_constraints_total" in expect:
        if len(constraints) > expect["max_constraints_total"]:
            errors.append(f"max_constraints_total: expected <={expect['max_constraints_total']}, got {len(constraints)}")

    # Constraint types check
    if "constraint_types" in expect:
        expected_types = set(expect["constraint_types"])
        for c_item in [c for s in extracted_sections for c in s.get("constraints", [])]:
            ctype = c_item.get("type", "")
            if ctype in expected_types:
                expected_types.discard(ctype)
        if expected_types:
            errors.append(f"constraint_types missing: {expected_types}")

    return errors


def check_llm_available():
    try:
        from core.llm_client import call as _llm_call
        result = _llm_call("ping", max_tokens=5, timeout=3.0)
        if isinstance(result, dict) and "error" in result:
            return False
        return True
    except Exception:
        return False


def run_tests():
    if not check_llm_available():
        print("LLM not available — skipping extraction tests")
        return 0

    cases = load_cases()
    passed = 0
    failed = 0
    skipped = 0

    print(f"AI Extractor Tests: {len(cases)} golden cases\n")
    print("=" * 60)

    for case in cases:
        cid = case["id"]
        name = case["name"]
        sections = case["input_sections"]
        expect = case.get("expect", {})

        extracted = extract_content(sections, event_meta={"title": name, "target_role": "工班长"})

        if not extracted:
            print(f"\n[{cid}] {name}: SKIP (LLM returned empty)")
            skipped += 1
            continue

        errors = check_expect(extracted, expect)

        if errors:
            print(f"\n[{cid}] {name}: FAIL")
            total_actions = sum(len(s.get("actions", [])) for s in extracted)
            total_constraints = sum(len(s.get("constraints", [])) for s in extracted)
            total_facts = sum(len(s.get("facts", [])) for s in extracted)
            print(f"  Stats: {len(extracted)} sections, {total_actions} actions, {total_constraints} constraints, {total_facts} facts")
            for s in extracted:
                for a in s.get("actions", []):
                    print(f"    action: [{a.get('text', '')[:80]}]")
                for c in s.get("constraints", []):
                    print(f"    constraint: [{c.get('text', '')[:80]}] ({c.get('type','')})")
                for f in s.get("facts", []):
                    print(f"    fact: [{f.get('text', '')[:80]}]")
            for e in errors:
                print(f"  ERROR: {e}")
            failed += 1
        else:
            total_actions = sum(len(s.get("actions", [])) for s in extracted)
            total_constraints = sum(len(s.get("constraints", [])) for s in extracted)
            print(f"\n[{cid}] {name}: PASS ({total_actions} actions, {total_constraints} constraints)")
            passed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
