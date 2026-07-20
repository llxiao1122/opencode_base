"""
memory/observation_store.py — Observation Store.

Unified entry point for all observation data. All modules read/write
through this store. Never access the filesystem directly.

API:
    write(text, source, obs_type, layer, confidence) → auto-route + merge + persist
    read(subject_type, subject_name)                  → full content
    search(target, type, since_days, top_k)           → structured results
    _route(text)                                      → (subject_type, subject_name)
    _merge(text, source, obs_type, filepath)          → same-day merge
"""

import json, re
from pathlib import Path
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
OBS_DIR = ROOT / "memory" / "observations"
ENTITY_PATH = ROOT / "state" / "entity_index.json"

_entity_names = None
_team_keywords = ["铁炉西工班", "物资总库", "综合工班"]


def _load_entity_names() -> list:
    global _entity_names
    if _entity_names is not None:
        return _entity_names
    _entity_names = []
    if ENTITY_PATH.exists():
        try:
            data = json.loads(ENTITY_PATH.read_text(encoding="utf-8"))
            _entity_names = [e["name"] for e in data.get("confirmed_entities", [])]
        except (json.JSONDecodeError, KeyError):
            pass
    return _entity_names


# ── public API ────────────────────────────────────────────────────────


def write(text: str, source: str = "", obs_type: str = "",
          layer: str = "rule", confidence: float = 0.0):
    """Write an observation. Auto-routes by person/team/leader name in text."""
    subj_type, subj_name = _route(text)
    target_dir = OBS_DIR / subj_type
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / f"{subj_name}.md"

    # Build section
    today = date.today().isoformat()
    new_section = f"\n---\n\n## {today}\n\nsource: {source}\ntype: {obs_type}\nlayer: {layer}\n\n{text}\n"
    if confidence > 0:
        new_section += f"confidence: {confidence}\n"

    # Merge or append
    existing = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    if _can_merge(existing, text, source, obs_type, today):
        merged = _apply_merge(existing, text, source, obs_type, today)
        filepath.write_text(merged, encoding="utf-8")
    else:
        filepath.write_text(existing + new_section, encoding="utf-8")


def read(subject_type: str, subject_name: str) -> str:
    """Read full observation file."""
    filepath = OBS_DIR / subject_type / f"{subject_name}.md"
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8")


def search(target: str, obs_type: str = None,
           since_days: int = None, top_k: int = 10) -> list:
    """Search observations for a person/team/leader by keyword."""
    results = []
    search_dirs = ["people", "teams", "leaders", "system"]

    for sd in search_dirs:
        sdir = OBS_DIR / sd
        if not sdir.exists():
            continue
        for fpath in sdir.glob("*.md"):
            if fpath.name.startswith("_"):
                continue
            if target and target not in fpath.name and target not in fpath.name.replace(".md", ""):
                if target not in fpath.read_text(encoding="utf-8")[:2000]:
                    continue
            content = fpath.read_text(encoding="utf-8")
            sections = content.split("\n---\n")
            for sec in sections:
                if not sec.strip():
                    continue
                if obs_type and f"type: {obs_type}" not in sec:
                    continue
                if since_days:
                    cutoff = date.today() - timedelta(days=since_days)
                    m = re.search(r"## (\d{4}-\d{2}-\d{2})", sec)
                    if m:
                        try:
                            sec_date = date.fromisoformat(m.group(1))
                            if sec_date < cutoff:
                                continue
                        except ValueError:
                            pass
                # Extract fact line
                lines = sec.strip().split("\n")
                fact = ""
                src = ""
                tp = ""
                for l in lines:
                    if l.startswith("source:"):
                        src = l.replace("source:", "").strip()
                    elif l.startswith("type:"):
                        tp = l.replace("type:", "").strip()
                    elif not l.startswith("##") and not l.startswith("layer:") and not l.startswith("confidence:") and l.strip():
                        if not fact:
                            fact = l.strip()
                if fact:
                    results.append({
                        "time": m.group(1) if 'm' in dir() and m else "",
                        "type": tp,
                        "source": src,
                        "subject": fpath.name.replace(".md", ""),
                        "fact": fact,
                    })
    results.sort(key=lambda r: r.get("time", ""), reverse=True)
    return results[:top_k]


# ── internal ───────────────────────────────────────────────────────────


def _route(text: str) -> tuple:
    """Route text to (subject_type, subject_name) by entity matching."""
    for name in _load_entity_names():
        if name in text:
            return ("people", name)
    for kw in _team_keywords:
        if kw in text:
            return ("teams", kw)
    return ("system", "Cipher")


def _can_merge(existing: str, text: str, source: str, obs_type: str, today: str) -> bool:
    """Check if we can merge with today's last section of same source+type."""
    sections = existing.split("\n---\n")
    if not sections:
        return False
    last = sections[-1]
    return (f"## {today}" in last
            and f"source: {source}" in last
            and f"type: {obs_type}" in last)


def _apply_merge(existing: str, text: str, source: str, obs_type: str, today: str) -> str:
    """Merge new fact into today's section. Combines counts if numeric."""
    sections = existing.split("\n---\n")
    last = sections[-1]

    # Extract existing count pattern: "连续N次"
    merged = last
    new_count = _extract_count(text)
    old_count = _extract_count(last)
    if new_count and old_count:
        total = old_count + new_count
        merged = re.sub(r"连续\d+次", f"连续{total}次", last)
    else:
        # Append fact line
        merged = last.rstrip() + "\n" + text.strip()

    sections[-1] = merged
    return "\n---\n".join(sections)


def _extract_count(text: str) -> int:
    m = re.search(r"连续(\d+)次", text)
    if m:
        return int(m.group(1))
    m = re.search(r"完成(\d+)次", text)
    if m:
        return int(m.group(1))
    return 0
