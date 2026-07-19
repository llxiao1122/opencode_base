"""
sanitizer.py — LLM Context Firewall

Strips internal metadata before passing to LLM. Recursively walks
dicts/lists, removing keys in INTERNAL_FIELDS.

Applied at every _llm() entry point in wrapper.py to ensure no
internal state (source files, confidence scores, debug paths) leaks
into user-facing answers.
"""

import json

INTERNAL_FIELDS = {
    "source", "file", "path", "confidence", "score", "r", "s",
    "executor_analysis", "detected_at", "match_reason",
    "status", "id", "source_section_id", "source_text",
}

ALLOWED_AI_FIELDS = {
    "section_id", "section_title", "facts", "actions", "constraints",
    "notes", "text", "type", "content", "level", "parent_event", "target_role",
}


def sanitize_ai_content(ai_content):
    """White-list based sanitizer for ai_content extraction output.
    Only keeps explicitly allowed fields. Unlike sanitize_context(),
    this does NOT recursively strip everything — it preserves the
    structured schema of ai_content by field whitelist.
    """
    if not ai_content:
        return ai_content
    if isinstance(ai_content, list):
        result = []
        for section in ai_content:
            if isinstance(section, dict):
                cleaned = {}
                for k in ALLOWED_AI_FIELDS:
                    if k in section:
                        cleaned[k] = section[k]
                if cleaned:
                    result.append(cleaned)
        return result
    return ai_content


def _sanitize_value(value):
    if isinstance(value, dict):
        return {
            k: _sanitize_value(v)
            for k, v in value.items()
            if k not in INTERNAL_FIELDS
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def sanitize_context(text):
    """Strip INTERNAL_FIELDS from JSON-like context. Falls back to raw text."""
    if not text:
        return text
    try:
        data = json.loads(text)
        if not isinstance(data, (dict, list)):
            return text
        cleaned = _sanitize_value(data)
        return json.dumps(cleaned, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError, ValueError):
        return text


def sanitize_hits_as_text(hits):
    """Convert FAISS memory hits to clean text."""
    lines = []
    for h in hits:
        chunk = h.get("c", "")
        if chunk:
            lines.append(chunk.strip())
    return "\n\n---\n\n".join(lines)
