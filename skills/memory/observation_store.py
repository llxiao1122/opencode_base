"""
memory/observation_store.py — Observation Store with index.
Index: memory/observations/.index.json — auto-maintained for fast search.
"""

import json, re
from pathlib import Path
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
OBS_DIR = ROOT / "memory" / "observations"
INDEX_PATH = OBS_DIR / ".index.json"
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
            as_list = data if isinstance(data, list) else data.get("confirmed_entities", [])
            _entity_names = [e["name"] for e in as_list if isinstance(e, dict)]
        except (json.JSONDecodeError, KeyError):
            pass
    return _entity_names


# ── index ──────────────────────────────────────────────────────────────


def _load_index() -> dict:
    default = {"version": 1, "updated": "", "subjects": {}}
    if not INDEX_PATH.exists():
        return default
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return default


def _save_index(idx: dict):
    idx["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    tmp = Path(str(INDEX_PATH) + ".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX_PATH)


def _index_key(subj_type: str, subj_name: str) -> str:
    return f"{subj_type}/{subj_name}"


def _ensure_subject(idx: dict, key: str, filepath: str):
    if key not in idx["subjects"]:
        idx["subjects"][key] = {"file": filepath, "sections": []}


def _update_index(subj_type: str, subj_name: str, section_date: str,
                  obs_type: str, summary: str):
    key = _index_key(subj_type, subj_name)
    filepath = f"{subj_type}/{subj_name}.md"
    idx = _load_index()
    _ensure_subject(idx, key, filepath)

    existing = idx["subjects"][key]["sections"]
    existing.append({
        "date": section_date,
        "type": obs_type,
        "summary": summary[:80],
    })
    _save_index(idx)


# ── public API ─────────────────────────────────────────────────────────


def write(text: str, source: str = "", obs_type: str = "",
          layer: str = "rule", confidence: float = 0.0):
    subj_type, subj_name = _route(text)
    target_dir = OBS_DIR / subj_type
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / f"{subj_name}.md"

    today = date.today().isoformat()
    new_section = f"\n---\n\n## {today}\n\nsource: {source}\ntype: {obs_type}\nlayer: {layer}\n\n{text}\n"
    if confidence > 0:
        new_section += f"confidence: {confidence}\n"

    existing = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    if _can_merge(existing, text, source, obs_type, today):
        merged = _apply_merge(existing, text, source, obs_type, today)
        filepath.write_text(merged, encoding="utf-8")
    else:
        filepath.write_text(existing + new_section, encoding="utf-8")

    _update_index(subj_type, subj_name, today, obs_type,
                  text.strip().split("\n")[0])


def read(subject_type: str, subject_name: str) -> str:
    filepath = OBS_DIR / subject_type / f"{subject_name}.md"
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8")


def search(target: str, obs_type: str = None,
           since_days: int = None, top_k: int = 10) -> list:
    idx = _load_index()
    now = date.today()
    cutoff = now - timedelta(days=since_days) if since_days else date.min

    candidates = _filter_index(idx, target, obs_type, cutoff)
    if not candidates:
        return []

    file_groups = {}
    for key, section_dates in candidates.items():
        rel = Path(key)
        subject_dir = str(rel.parent)
        subject_name = rel.name
        fpath = OBS_DIR / subject_dir / f"{subject_name}.md"
        if fpath not in file_groups:
            file_groups[fpath] = []
        file_groups[fpath].extend(section_dates)

    results = []
    for fpath, wanted_dates in file_groups.items():
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8")
        section_texts = content.split("\n---\n")
        for sec in section_texts:
            if not sec.strip():
                continue
            sec_date = _parse_section_date(sec)
            if sec_date and sec_date.isoformat() in wanted_dates:
                parsed = _extract_fact(sec)
                if parsed:
                    results.append(parsed)

    results.sort(key=lambda r: r.get("time", ""), reverse=True)
    return results[:top_k]


def rebuild_index():
    """Scan all observation files and rebuild .index.json from scratch."""
    idx = {"version": 1, "updated": "", "subjects": {}}
    for subj_type in ["people", "teams", "system"]:
        d = OBS_DIR / subj_type
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            if f.name.startswith("_"):
                continue
            key = f"{subj_type}/{f.name.replace('.md', '')}"
            filepath = str(f.relative_to(OBS_DIR))
            _ensure_subject(idx, key, filepath)
            content = f.read_text(encoding="utf-8")
            sections = content.split("\n---\n")
            for sec in sections:
                if not sec.strip():
                    continue
                sec_date = _parse_section_date(sec)
                if not sec_date:
                    continue
                obs_type = ""
                summary = ""
                for l in sec.strip().split("\n"):
                    if l.startswith("type:"):
                        obs_type = l.replace("type:", "").strip()
                    elif not l.startswith("##") and not l.startswith("source:") and not l.startswith("layer:") and not l.startswith("confidence:") and l.strip():
                        if not summary:
                            summary = l.strip()[:80]
                if summary:
                    idx["subjects"][key]["sections"].append({
                        "date": sec_date.isoformat(),
                        "type": obs_type,
                        "summary": summary,
                    })
    _save_index(idx)
    return idx


# ── internal helpers ───────────────────────────────────────────────────


def _filter_index(idx, target, obs_type, cutoff_date):
    """Filter index and return {key: set of date strings} matching criteria."""
    matched = {}
    for key, info in idx.get("subjects", {}).items():
        if target and target not in key and target not in _subject_summaries(info):
            continue
        matching_dates = set()
        for sec in info.get("sections", []):
            if obs_type and sec.get("type") != obs_type:
                continue
            try:
                sd = date.fromisoformat(sec["date"])
            except (ValueError, KeyError):
                continue
            if sd < cutoff_date:
                continue
            if target and target not in sec.get("summary", ""):
                if target not in key:
                    continue
            matching_dates.add(sec["date"])
        if matching_dates:
            matched[key] = matching_dates
    return matched


def _subject_summaries(info: dict) -> str:
    parts = [s.get("summary", "") for s in info.get("sections", [])]
    return " ".join(parts)


def _parse_section_date(sec: str) -> date:
    m = re.search(r"## (\d{4}-\d{2}-\d{2})", sec)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


def _extract_fact(sec: str) -> dict:
    lines = sec.strip().split("\n")
    fact = ""
    src = ""
    tp = ""
    sec_date = ""
    m = re.search(r"## (\d{4}-\d{2}-\d{2})", sec)
    if m:
        sec_date = m.group(1)
    for l in lines:
        if l.startswith("source:"):
            src = l.replace("source:", "").strip()
        elif l.startswith("type:"):
            tp = l.replace("type:", "").strip()
        elif not l.startswith("##") and not l.startswith("layer:") and not l.startswith("confidence:") and l.strip():
            if not fact:
                fact = l.strip()
    if fact:
        return {
            "time": sec_date,
            "type": tp,
            "source": src,
            "subject": "",
            "fact": fact,
        }
    return None


def _route(text: str) -> tuple:
    for name in _load_entity_names():
        if name in text:
            return ("people", name)
    for kw in _team_keywords:
        if kw in text:
            return ("teams", kw)
    return ("system", "Cipher")


def _can_merge(existing: str, text: str, source: str, obs_type: str, today: str) -> bool:
    sections = existing.split("\n---\n")
    if not sections:
        return False
    last = sections[-1]
    return (f"## {today}" in last
            and f"source: {source}" in last
            and f"type: {obs_type}" in last)


def _apply_merge(existing: str, text: str, source: str, obs_type: str, today: str) -> str:
    sections = existing.split("\n---\n")
    last = sections[-1]
    merged = last
    new_count = _extract_count(text)
    old_count = _extract_count(last)
    if new_count and old_count:
        total = old_count + new_count
        merged = re.sub(r"连续\d+次", f"连续{total}次", last)
    else:
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
