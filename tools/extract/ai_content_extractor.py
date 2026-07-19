"""
ai_content_extractor.py — AI Content Extractor (Phase 1.7.7-B)

职责：接收 section_parser 输出的 Section[]，通过 LLM 提取 facts/actions/constraints。
一次事件一次 LLM 调用。输出符合 content_extraction.schema.json 契约。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from reasoning.llm_client import call as _llm_call

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPT_DIR / "content_extract.txt"

_detect_cache: dict[str, list[dict]] = {}
CACHE_MAX = 200


def _load_system_prompt():
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return ""


def extract_content(sections, event_meta=None):
    if not sections:
        return []

    cache_key = _make_cache_key(sections)
    if cache_key in _detect_cache:
        return _detect_cache[cache_key]

    event_meta = event_meta or {}
    system_prompt = _load_system_prompt()

    sections_json = _format_sections_for_prompt(sections, event_meta)
    user_prompt = f"以下是一条通知拆分后的章节列表，请分别提取每个section中的facts/actions/constraints，保持section_id对应。\n\n{sections_json}\n\n只返回 JSON 数组:"

    try:
        raw = _llm_call(
            user_prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=2048,
            timeout=30.0,
        )
    except Exception as e:
        _cache_set(cache_key, [])
        return []

    result = _parse_llm_output(raw)
    if result is None:
        _cache_set(cache_key, [])
        return []

    validated = _validate_and_demote(result)
    _cache_set(cache_key, validated)
    return validated


def _format_sections_for_prompt(sections, event_meta):
    lines = []
    event_title = event_meta.get("title", "")
    target_role = event_meta.get("target_role", "")
    if event_title:
        lines.append(f"## 事件: {event_title}")
    if target_role:
        lines.append(f"面向角色: {target_role}")

    for i, s in enumerate(sections):
        sid = s.get("section_id", f"S{i}")
        title = s.get("section_title", "header")
        content = s.get("content", "")
        lines.append(f"\n### [{sid}] {title}\n{content}")

    return "\n".join(lines)


def _extract_json_array(raw):
    if not raw:
        return None
    text = str(raw).strip()
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end])
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def _parse_llm_output(raw):
    parsed = _extract_json_array(raw)
    if not parsed:
        return None

    result = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        section = {
            "section_id": item.get("section_id", ""),
            "section_title": item.get("section_title", ""),
            "facts": _normalize_items(item.get("facts", [])),
            "actions": _normalize_actions(item.get("actions", [])),
            "constraints": _normalize_constraints(item.get("constraints", [])),
            "notes": item.get("notes", []) if isinstance(item.get("notes"), list) else [],
        }
        result.append(section)

    return result if result else None


def _normalize_items(items):
    out = []
    for i in items:
        if isinstance(i, str):
            out.append({"text": i, "source_text": i})
        elif isinstance(i, dict):
            text = i.get("text", "")
            source = i.get("source_text", text)
            if text:
                out.append({"text": text, "source_text": source})
    return out


def _normalize_actions(actions):
    out = []
    for a in actions:
        if isinstance(a, str):
            out.append(_make_action(a, a, "execute"))
        elif isinstance(a, dict):
            text = a.get("text", "")
            if text:
                out.append(_make_action(
                    text,
                    a.get("source_text", text),
                    a.get("type", "execute"),
                    a.get("source_section_id", ""),
                    a.get("confidence", 0.9),
                ))
    return out


def _normalize_constraints(constraints):
    out = []
    for c in constraints:
        if isinstance(c, str):
            out.append(_make_constraint(c, c, "requirement"))
        elif isinstance(c, dict):
            text = c.get("text", "")
            if text:
                out.append(_make_constraint(
                    text,
                    c.get("source_text", text),
                    c.get("type", "requirement"),
                    c.get("source_section_id", ""),
                    c.get("confidence", 0.9),
                ))
    return out


def _make_action(text, source_text, action_type="execute",
                 source_section_id="", confidence=0.9):
    return {
        "text": text,
        "type": action_type if action_type in ("execute", "coordinate", "confirm", "prepare") else "execute",
        "source_text": source_text,
        "source_section_id": source_section_id,
        "confidence": min(max(float(confidence or 0.9), 0), 1),
    }


def _make_constraint(text, source_text, constraint_type="requirement",
                     source_section_id="", confidence=0.9):
    return {
        "text": text,
        "type": constraint_type if constraint_type in ("prohibition", "requirement", "deadline", "condition") else "requirement",
        "source_text": source_text,
        "source_section_id": source_section_id,
        "confidence": min(max(float(confidence or 0.9), 0), 1),
    }


def _validate_and_demote(sections):
    try:
        sys.path.insert(0, str(ROOT / "schemas"))
        from validator import validate_action, validate_constraint, validate_fact
    except Exception:
        return sections

    for section in sections:
        new_facts = list(section.get("facts", []))

        demoted_actions = []
        kept_actions = []
        for a in section.get("actions", []):
            ok, _ = validate_action(a)
            if ok:
                kept_actions.append(a)
            else:
                new_facts.append({"text": a["text"], "source_text": a.get("source_text", a["text"])})

        section["actions"] = kept_actions

        kept_constraints = []
        for c in section.get("constraints", []):
            ok, _ = validate_constraint(c)
            if ok:
                kept_constraints.append(c)

        section["constraints"] = kept_constraints

        kept_facts = []
        for f in new_facts:
            ok, _ = validate_fact(f)
            if ok:
                kept_facts.append(f)
            else:
                kept_facts.append({
                    "text": f["text"],
                    "source_text": f.get("source_text", f["text"]),
                })

        section["facts"] = kept_facts

    return sections


def _make_cache_key(sections):
    raw = json.dumps([{
        "id": s.get("section_id", ""),
        "t": s.get("section_title", ""),
        "c": s.get("content", "")[:200],
    } for s in sections], ensure_ascii=False)
    return raw


def _cache_set(key, value):
    if len(_detect_cache) >= CACHE_MAX:
        for k in list(_detect_cache.keys())[:CACHE_MAX // 2]:
            del _detect_cache[k]
    _detect_cache[key] = value
