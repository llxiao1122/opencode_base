"""
personal/retriever.py — Personal Context retriever.

Reads data/personal/*.json[l] and formats for LLM injection.
Supports: preferences injection, thought search, preference auto-update.
"""

import json, re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
PERSONAL_DIR = ROOT / "state" / "personal"

THOUGHTS_PATH = PERSONAL_DIR / "thoughts.jsonl"
EMOTIONS_PATH = PERSONAL_DIR / "emotions.jsonl"
PREFERENCES_PATH = PERSONAL_DIR / "preferences.json"

# Topics that trigger personal thought search
PERSONAL_TOPICS = {
    "价值观": ["意义", "值不值得", "方向", "人生", "选择", "后悔"],
    "工作观": ["管理", "效率", "重复", "架构", "长期", "放弃"],
    "思维方式": ["怎么想", "逻辑", "规律", "认知", "判断", "反思"],
    "压力与情绪": ["焦虑", "压力", "累", "烦", "状态", "情绪", "低落"],
}

# Signals for preference auto-update
PREFERENCE_SIGNALS = ["不要", "不喜欢", "以后", "建议你", "我习惯", "我倾向",
                      "我希望", "我偏好", "别给我", "不用", "避免"]


# ── read ───────────────────────────────────────────────────────────


def load_preferences() -> dict:
    if not PREFERENCES_PATH.exists():
        return {}
    try:
        return json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def load_all_thoughts() -> list:
    if not THOUGHTS_PATH.exists():
        return []
    thoughts = []
    with open(THOUGHTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                thoughts.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    thoughts.sort(key=lambda t: t.get("time", ""), reverse=True)
    return thoughts


# ── search ─────────────────────────────────────────────────────────


def search_thoughts(topic: str, top_k: int = 3) -> list:
    """Simple keyword search from thoughts.jsonl. Zero LLM."""
    all_thoughts = load_all_thoughts()
    if not all_thoughts:
        return []

    # Extract search terms from topic
    terms = set()
    for domain, keywords in PERSONAL_TOPICS.items():
        if any(k in topic for k in keywords):
            terms.update(keywords)
    if not terms:
        terms = {topic[:10]}  # fallback: raw topic prefix

    scored = []
    for t in all_thoughts:
        content = t.get("content", "")
        score = sum(1 for kw in terms if kw in content)
        if score > 0:
            scored.append((score, t))

    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:top_k]]


def has_personal_relevance(user_input: str) -> bool:
    """Check if the input touches a personal dimension."""
    for domain, keywords in PERSONAL_TOPICS.items():
        if any(k in user_input for k in keywords):
            return True
    return False


def format_thought_context(topic: str) -> str:
    """Format relevant thoughts as LLM-injectable context."""
    results = search_thoughts(topic, top_k=3)
    if not results:
        return ""
    lines = ["\n## 相关记录"]
    for t in results:
        ts = t.get("time", "")[:10]
        lines.append(f"- [{ts}] {t['content'][:120]}")
    return "\n".join(lines)


# ── preferences update ─────────────────────────────────────────────


def should_update_preferences(user_input: str) -> bool:
    """Check if the input contains preference signals."""
    return any(sig in user_input for sig in PREFERENCE_SIGNALS)


def maybe_update_preferences(user_input: str, ciphers_reply: str):
    """LLM-refined preference update. Appends, doesn't replace."""
    if not should_update_preferences(user_input):
        return

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.llm_client import call as _llm

    current = json.dumps(load_preferences(), ensure_ascii=False)
    prompt = (
        "从对话中提取用户的偏好信号，只更新有变化的字段。不做人格判断。\n\n"
        f"当前偏好:\n{current}\n\n"
        f"用户说: {user_input[:300]}\n"
        f"Cipher 回复: {ciphers_reply[:200]}\n\n"
        "输出一个 JSON patch，只输出变化的键。例如: {\"communication\": {\"prefer\": \"直接\"}}。"
        "如果没有新的偏好信号，输出 {}。只输出 JSON，不解释。"
    )

    try:
        raw = _llm(prompt, system_prompt="你是偏好提取器。只输出JSON。", max_tokens=200, temperature=0.1)
        if raw and isinstance(raw, str) and raw.strip().startswith("{"):
            patch = json.loads(raw.strip())
            if patch and patch != {}:
                _apply_patch(patch)
    except Exception:
        pass


def _apply_patch(patch: dict):
    """Apply a JSON patch to preferences.json."""
    prefs = load_preferences()
    for key, value in patch.items():
        if isinstance(value, dict) and key in prefs and isinstance(prefs[key], dict):
            prefs[key].update(value)
        else:
            prefs[key] = value

    tmp = Path(str(PREFERENCES_PATH) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    tmp.replace(PREFERENCES_PATH)


# ── context formatting ─────────────────────────────────────────────


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

    thoughts = load_all_thoughts()[:3]
    if thoughts:
        parts.append("\n## 近期关注")
        for t in thoughts:
            parts.append(f"- [{t['type']}] {t['content'][:120]}")

    return "\n".join(parts) if parts else ""
