"""
memory/retriever.py — Unified memory retrieval layer.

Single entry point for searching across all memory stores:
    Event, Task, Observation, Candidate, Organization Memory.

No LLM. No new database. Read-only access to existing files.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

EVENT_PATH = ROOT / "memory" / "events" / "log.jsonl"
TASK_PATH = ROOT / "data" / "tasks.json"
CANDIDATE_PATH = ROOT / "data" / "memory_candidates.json"
ORG_MEMORY_PATH = ROOT / "data" / "org_memory.json"
OBSERVATIONS_DIR = ROOT / "memory" / "observations"


def search_memory(keyword: str, start_date="", end_date="",
                  include_observations=True) -> dict:
    """Unified search across all memory layers.

    Args:
        keyword: search term (person name, topic, etc.)
        start_date: optional lower bound (YYYY-MM-DD)
        end_date: optional upper bound (YYYY-MM-DD)
        include_observations: include observation markdown files

    Returns:
        {query, time_range, results, org_summary, summary}
    """
    results = []

    results.extend(_search_events(keyword, start_date, end_date))
    results.extend(_search_tasks(keyword, start_date, end_date))
    if include_observations:
        results.extend(_search_observations(keyword, start_date, end_date))
    results.extend(_search_candidates(keyword, start_date, end_date))

    results.sort(key=lambda r: r.get("time", ""), reverse=True)

    counts = {}
    for r in results:
        src = r["source"]
        counts[src] = counts.get(src, 0) + 1

    org = _search_org(keyword)

    return {
        "query": keyword,
        "time_range": {"start": start_date, "end": end_date},
        "results": results,
        "org_summary": org,
        "summary": {
            "events": counts.get("event", 0),
            "tasks": counts.get("task", 0),
            "observations": counts.get("observation", 0),
            "candidates": counts.get("candidate", 0),
            "total": len(results),
        },
    }


def search_person(name: str) -> dict:
    """Shortcut: search all memory for a person."""
    return search_memory(name)


def search_period(keyword: str, date: str) -> dict:
    """Shortcut: search within a single date."""
    return search_memory(keyword, start_date=date, end_date=date)


# ── helpers ────────────────────────────────────────────────────────────


def _in_range(date_str: str, start: str, end: str) -> bool:
    if not start and not end:
        return True
    if not date_str:
        return False
    d = date_str[:10]
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def _keyword_match(keyword: str, candidate: str) -> bool:
    return keyword in candidate


def _flatten(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── event search ───────────────────────────────────────────────────────


def _load_events() -> list:
    if not EVENT_PATH.exists():
        return []
    events = []
    with open(EVENT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return events


def _search_events(keyword: str, start: str, end: str) -> list:
    results = []
    for e in _load_events():
        text = _flatten(e)
        if not _keyword_match(keyword, text):
            continue
        et = e.get("event_time") or e.get("import_time") or ""
        if not _in_range(et, start, end):
            continue
        results.append({
            "source": "event",
            "source_id": e.get("id", ""),
            "time": et[:10],
            "type": e.get("event_type", ""),
            "content": e.get("action_summary", "") or e.get("raw_preview", "")[:120],
            "actors": _format_actors(e.get("actors", [])),
        })
    return results


def _format_actors(actors: list) -> str:
    parts = []
    for a in actors:
        name = a.get("name", "")
        pos = a.get("position", "")
        parts.append(f"{name}({pos})" if pos else name)
    return ", ".join(parts)


# ── task search ────────────────────────────────────────────────────────


def _load_tasks() -> list:
    if not TASK_PATH.exists():
        return []
    try:
        return json.loads(TASK_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _search_tasks(keyword: str, start: str, end: str) -> list:
    results = []
    for t in _load_tasks():
        text = _flatten(t)
        if not _keyword_match(keyword, text):
            continue
        created = t.get("created_at", "")[:10]
        completed = t.get("completed_at", "")
        if completed:
            completed = completed[:10]
        in_time = _in_range(created, start, end) or _in_range(completed, start, end)
        if not in_time:
            continue
        results.append({
            "source": "task",
            "source_id": t.get("id", ""),
            "time": created,
            "type": t.get("responsibility_type", ""),
            "action": t.get("action", "")[:120],
            "status": t.get("status", ""),
            "owner": t.get("owner", {}).get("name", ""),
            "role": _task_role(t, keyword),
            "completed_at": completed,
        })
    return results


def _task_role(task: dict, keyword: str) -> str:
    owner = task.get("owner", {}).get("name", "")
    exec_names = [e["name"] for e in task.get("executors", [])]
    is_owner = (keyword == owner)
    is_exec = keyword in exec_names
    if is_owner and is_exec:
        return "owner+executor"
    if is_owner:
        return "owner"
    if is_exec:
        return "executor"
    return "related"


# ── observation search ─────────────────────────────────────────────────


def _search_observations(keyword: str, start: str, end: str) -> list:
    if not OBSERVATIONS_DIR.exists():
        return []
    results = []
    for fpath in sorted(OBSERVATIONS_DIR.glob("*.md")):
        fname = fpath.name
        if fname.startswith("_"):
            continue
        date_str = fname.replace(".md", "")
        if not _in_range(date_str, start, end):
            continue
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line or not _keyword_match(keyword, line):
                continue
            clean = re.sub(r"^-+\s*", "", line)
            clean = re.sub(r"【.+?】", "", clean).strip()
            results.append({
                "source": "observation",
                "source_id": fname,
                "time": date_str,
                "content": clean[:200],
            })
    return results


# ── candidate search ───────────────────────────────────────────────────


def _load_candidates() -> list:
    if not CANDIDATE_PATH.exists():
        return []
    try:
        data = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("candidates", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _search_candidates(keyword: str, start: str, end: str) -> list:
    results = []
    for c in _load_candidates():
        subject = c.get("subject", "") or c.get("fact", "")
        fact = c.get("fact", "")
        if not _keyword_match(keyword, subject + fact):
            continue
        ct = c.get("created_at", "")[:10]
        if not _in_range(ct, start, end):
            continue
        results.append({
            "source": "candidate",
            "source_id": c.get("id", ""),
            "time": ct,
            "fact": fact[:120],
            "confidence": c.get("confidence", 0),
        })
    return results


# ── org search ─────────────────────────────────────────────────────────


def _search_org(keyword: str) -> dict:
    if not ORG_MEMORY_PATH.exists():
        return {}
    try:
        data = json.loads(ORG_MEMORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return {}
    people = data.get("people", {})
    if keyword in people:
        p = people[keyword]
        return {
            "role": p.get("role", ""),
            "appears_in_events": p.get("appears_in_events", 0),
            "appears_in_tasks": p.get("appears_in_tasks", 0),
            "as_requester": p.get("as_requester", 0),
            "as_executor": p.get("as_executor", 0),
            "event_types": p.get("event_types", {}),
        }
    # Fuzzy match
    for name, p in people.items():
        if keyword in name or name in keyword:
            return {
                "role": p.get("role", ""),
                "appears_in_events": p.get("appears_in_events", 0),
                "appears_in_tasks": p.get("appears_in_tasks", 0),
                "as_requester": p.get("as_requester", 0),
                "as_executor": p.get("as_executor", 0),
                "matched_by": "fuzzy",
                "matched_name": name,
            }
    return {}
