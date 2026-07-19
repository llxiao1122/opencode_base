"""
personal/retriever.py — Personal Context retriever.

Reads data/personal/*.json[l] and formats for LLM injection.
No LLM. No writes. Pure read-only access.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PERSONAL_DIR = ROOT / "data" / "personal"

THOUGHTS_PATH = PERSONAL_DIR / "thoughts.jsonl"
EMOTIONS_PATH = PERSONAL_DIR / "emotions.jsonl"
PREFERENCES_PATH = PERSONAL_DIR / "preferences.json"


def load_preferences() -> dict:
    if not PREFERENCES_PATH.exists():
        return {}
    try:
        return json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def load_recent_thoughts(limit: int = 10) -> list:
    if not THOUGHTS_PATH.exists():
        return []
    thoughts = []
    with open(THOUGHTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                thoughts.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return thoughts[-limit:]


def load_recent_emotions(days: int = 7) -> list:
    if not EMOTIONS_PATH.exists():
        return []
    emotions = []
    with open(EMOTIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                emotions.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return emotions[-days:]


def format_personal_context() -> str:
    """Generate LLM-injectable personal context text."""
    parts = []

    prefs = load_preferences()
    if prefs:
        parts.append("## 用户偏好")
        comm = prefs.get("communication", {})
        if comm:
            parts.append(f"- 沟通: {comm.get('prefer', '直接')}")
        tech = prefs.get("technical", {})
        if tech.get("prefer"):
            parts.append(f"- 技术: {' > '.join(tech['prefer'])}")
        dec = prefs.get("decision", {})
        if dec.get("style"):
            parts.append(f"- 决策: {dec['style']}")
        think = prefs.get("thinking", {})
        if think.get("patterns"):
            parts.append(f"- 思维模式: {', '.join(think['patterns'])}")

    thoughts = load_recent_thoughts(5)
    if thoughts:
        parts.append("\n## 近期关注")
        for t in thoughts[-3:]:
            parts.append(f"- [{t['type']}] {t['content'][:100]}")

    return "\n".join(parts) if parts else ""
