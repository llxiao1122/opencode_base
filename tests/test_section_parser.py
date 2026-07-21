#!/usr/bin/env python3
"""
test_section_parser.py — Section Parser Tests (Phase 1.7.7-A)
Runs against tests/golden/section_cases.json (22 cases).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))

from ingestion.section_parser import parse


def load_cases():
    case_file = ROOT / "tests" / "golden" / "section_cases.json"
    with open(case_file, "r", encoding="utf-8") as f:
        return json.load(f)["cases"]


def check_expect(result, expect):
    sections = result.get("sections", [])
    errors = []

    if "min_sections" in expect:
        if len(sections) < expect["min_sections"]:
            errors.append(
                f"min_sections: expected >={expect['min_sections']}, got {len(sections)}"
            )

    if "max_sections" in expect:
        if len(sections) > expect["max_sections"]:
            errors.append(
                f"max_sections: expected <={expect['max_sections']}, got {len(sections)}"
            )

    if "no_empty_section_content" in expect and expect["no_empty_section_content"]:
        for s in sections:
            if not s.get("content", "").strip() and s.get("section_title") != "header":
                errors.append(f"empty content in section {s.get('section_id')}")

    if "has_header" in expect:
        has_header = any(
            s.get("section_title") == "header" for s in sections
        )
        if expect["has_header"] and not has_header:
            errors.append("expected header section but none found")
        if not expect["has_header"] and has_header:
            errors.append("expected no header section but found one")

    if "first_section_title" in expect:
        if sections:
            got = sections[0].get("section_title", "")
            expected = expect["first_section_title"]
            if got != expected:
                errors.append(
                    f"first_section_title: expected '{expected}', got '{got}'"
                )

    if "section_titles" in expect:
        got_titles = [s.get("section_title", "") for s in sections]
        for expected_title in expect["section_titles"]:
            if expected_title not in got_titles:
                errors.append(
                    f"section_titles: missing '{expected_title}' in {got_titles}"
                )

    if "title_contains" in expect:
        got_titles = [s.get("section_title", "") for s in sections]
        for frag in expect["title_contains"]:
            if not any(frag in t for t in got_titles):
                errors.append(
                    f"title_contains: '{frag}' not found in any title: {got_titles}"
                )

    if "content_contains" in expect:
        all_content = " ".join(s.get("content", "") for s in sections)
        for frag in expect["content_contains"]:
            if frag not in all_content:
                errors.append(
                    f"content_contains: '{frag}' not found in combined content"
                )

    return errors


def run_tests():
    cases = load_cases()
    passed = 0
    failed = 0

    print(f"Section Parser Tests: {len(cases)} cases\n")
    print("=" * 60)

    for case in cases:
        cid = case["id"]
        name = case["name"]
        text = case["input"]
        expect = case.get("expect", {})

        result = parse(text, parent_event=name, target_role="工班长")
        errors = check_expect(result, expect)

        if errors:
            print(f"\n[{cid}] {name}: FAIL")
            print(f"  Sections: {len(result['sections'])}")
            for s in result["sections"]:
                title = s.get("section_title", "").replace("\n", "\\n")[:60]
                content_preview = s.get("content", "").replace("\n", "\\n")[:80]
                print(f"    {s['section_id']}: [{title}] -> {content_preview}")
            for e in errors:
                print(f"  ERROR: {e}")
            failed += 1
        else:
            print(f"\n[{cid}] {name}: PASS")
            print(f"  Sections: {len(result['sections'])}")
            for s in result["sections"]:
                title = s.get("section_title", "").replace("\n", "\\n")[:50]
                print(f"    {s['section_id']}: [{title}]")
            passed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
