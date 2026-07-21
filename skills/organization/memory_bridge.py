"""
organization/memory_bridge.py — Organization memory accumulation (Phase 2 prep).

Reads existing event log + task store, produces statistical observations.
No LLM. No profile generation. Pure fact aggregation.

Output: data/org_memory.json
  - people: per-person event/task/frequency stats
  - patterns: relationship graph, top requesters/executors, common topics

This is the bridge between raw task data and future profile_store.
Systems accumulates facts here; profile_store reasons about them later.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skills.shared import load_entities

TOOLS_DIR = Path(__file__).resolve().parent.parent
ROOT = TOOLS_DIR.parent

LOG_PATH = ROOT / "memory" / "events" / "log.jsonl"
TASKS_PATH = ROOT / "state" / "tasks.json"
OUTPUT_PATH = ROOT / "state" / "org_memory.json"


def _load_entity_roles() -> dict:
    """Load {name: role} from entity_index.json."""
    roles = {}
    for e in load_entities():
        roles[e["name"]] = e.get("role", "")
    return roles


def _load_events() -> list:
    """Load all events from log.jsonl."""
    events = []
    if not LOG_PATH.exists():
        return events
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue
    return events


def _load_tasks() -> list:
    """Load all tasks from tasks.json."""
    if not TASKS_PATH.exists():
        return []
    try:
        return json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def accumulate() -> dict:
    """Read event log + task store, produce per-person statistical observations.

    Only reports facts: frequency counts, event types, task involvement.
    Does NOT generate profiles, evaluations, or recommendations.

    Returns:
        {accumulated_at, people, patterns}
    """
    events = _load_events()
    tasks = _load_tasks()
    entity_roles = _load_entity_roles()

    person_event_count = Counter()
    person_requester_count = Counter()
    person_event_types = {}
    person_task_count = Counter()
    person_executor_count = Counter()
    assignment_pairs = Counter()

    for evt in events:
        actors = evt.get("actors", [])
        for a in actors:
            name = a.get("name", "")
            if not name:
                continue
            pos = a.get("position", "")

            person_event_count[name] += 1
            types = person_event_types.setdefault(name, Counter())
            etype = evt.get("event_type", "unknown")
            types[etype] += 1

            if pos == "requester":
                person_requester_count[name] += 1

    for task in tasks:
        owner = task.get("owner", {})
        owner_name = owner.get("name", "")
        if owner_name:
            person_task_count[owner_name] += 1

        executors = task.get("executors", [])
        for exe in executors:
            ename = exe.get("name", "")
            if ename:
                person_executor_count[ename] += 1
                if owner_name:
                    assignment_pairs[(owner_name, ename)] += 1

    people = {}
    all_names = set(person_event_count) | set(person_task_count) | set(person_executor_count)
    for name in sorted(all_names):
        people[name] = {
            "role": entity_roles.get(name, ""),
            "appears_in_events": person_event_count.get(name, 0),
            "appears_in_tasks": person_task_count.get(name, 0),
            "as_requester": person_requester_count.get(name, 0),
            "as_executor": person_executor_count.get(name, 0),
            "event_types": dict(person_event_types.get(name, {})),
        }

    relationship_graph = {}
    for name in sorted(all_names):
        assigned = []
        for (src, tgt), count in assignment_pairs.items():
            if src == name:
                assigned.append({"target": tgt, "count": count})
        if assigned:
            assigned.sort(key=lambda x: -x["count"])
            relationship_graph[name] = {"often_assign_to": assigned}

    top_requesters = [p for p, _ in person_requester_count.most_common(10)]
    top_executors = [p for p, _ in person_executor_count.most_common(10)]

    action_words = Counter()
    for task in tasks:
        action = task.get("action", "")
        for word in ["消防检查", "安全检查", "入库", "巡检", "废旧", "台账", "迎检", "防汛", "考勤", "安全"]:
            if word in action:
                action_words[word] += 1

    result = {
        "accumulated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": {
            "events": len(events),
            "tasks": len(tasks),
        },
        "people": dict(sorted(people.items())),
        "patterns": {
            "top_requesters": top_requesters,
            "top_executors": top_executors,
            "common_task_topics": [w for w, _ in action_words.most_common(15)],
            "relationship_graph": relationship_graph,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def get_person_summary(name: str) -> dict:
    """Quick lookup of a single person's accumulated stats.

    Returns empty dict if person not found in org_memory.
    """
    if not OUTPUT_PATH.exists():
        return {}
    try:
        data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        return data.get("people", {}).get(name, {})
    except (json.JSONDecodeError, FileNotFoundError):
        return {}
