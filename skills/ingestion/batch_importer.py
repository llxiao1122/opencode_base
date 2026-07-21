"""
ingestion/batch_importer.py — Unified ingestion pipeline.

Single cognitive pipeline shared by all message sources:
    real-time (wrapper) → import_batch(source_type="dingding")
    history files      → import_batch(source_type="history_txt")
    manual paste       → import_batch(source_type="manual")

Pipeline: parse → classify → event → context → task → record

Does NOT modify core modules.
"""

import json as _json
import hashlib as _hashlib
from pathlib import Path
from datetime import datetime

TOOLS_DIR = Path(__file__).resolve().parent.parent
ROOT = TOOLS_DIR.parent


# ── public API ────────────────────────────────────────────────────────


def import_batch(
    text: str,
    source_type: str = "manual",
    source_file: str = "",
    current_user=None,
) -> dict:
    """Unified ingestion pipeline for a batch of raw messages.

    Args:
        text: raw multi-message DingTalk transcript
        source_type: "dingding" | "history_txt" | "manual"
        source_file: filename label for batch import (e.g. "2026Q1.txt")
        current_user: user profile dict

    Returns:
        {total_messages, events_created, tasks_created,
         feedback_matched, ignored, errors,
         source_type, source_file, log}
    """
    from ingestion.message_parser import parse
    from ingestion.message_classifier import classify

    is_clipboard = (source_type == "clipboard_history")
    messages = parse(text, allow_missing_time=is_clipboard)
    messages.sort(key=lambda m: m.get("timestamp", ""))

    processed_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    log = []
    events_created = 0
    tasks_created = 0
    feedback_matched = 0
    ignored = 0
    errors = 0

    for i, msg in enumerate(messages):
        mtype = classify(msg)
        history_ts = msg.get("timestamp", "")
        entry = {
            "msg_id": msg["id"],
            "seq": i + 1,
            "sender": msg["sender"],
            "timestamp": history_ts,
            "content_preview": msg["content"][:80],
            "type": mtype,
            "action": "skipped",
        }

        if mtype in ("irrelevant", "discussion", "question"):
            ignored += 1
            log.append(entry)
            continue

        combined = msg["content"]

        try:
            event = _extract_event(combined, current_user)

            if mtype == "instruction" and event.get("event_type") == "unknown" and event.get("confidence", 0) >= 0.5:
                event["event_type"] = "instruction"
            if mtype == "announcement" and event.get("event_type") == "unknown":
                event["event_type"] = "notification"
            if mtype == "feedback":
                event["event_type"] = "feedback"
                if event.get("confidence", 0) < 0.5:
                    event["confidence"] = 0.5

            entry["event_type"] = event.get("event_type", "")
            entry["confidence"] = event.get("confidence", 0)

            if not event or event.get("event_type") == "unknown":
                entry["action"] = "no_event"
                ignored += 1
                log.append(entry)
                continue

            if history_ts:
                event["time"] = event.get("time", {})
                if not event["time"].get("start"):
                    event["time"]["start"] = history_ts
                event["detected_at"] = history_ts
            elif is_clipboard:
                # Clipboard imports: don't let event detector's default date leak
                event["detected_at"] = ""
                event["time"] = event.get("time", {})
                event["time"]["start"] = ""

            event["source_type"] = source_type
            event["source_file"] = source_file or ""
            event["processed_at"] = processed_at

            event["action_summary"] = (event.get("action") or {}).get("summary", "")

            if is_clipboard:
                has_sender = bool(msg.get("sender"))
                has_ts = bool(msg.get("timestamp"))
                has_content = bool(msg.get("content"))
                event["source_quality"] = {
                    "data_quality": "full" if (has_sender and has_ts and has_content) else "partial",
                    "sender_available": has_sender,
                    "timestamp_available": has_ts,
                    "context_complete": bool(has_sender and has_content),
                }

            if event.get("event_type") == "feedback":
                # Ensure sender is in actors for feedback matching
                sender = msg.get("sender", "")
                if sender and not any(
                    a.get("position") in ("entity", "executor") and a.get("name") == sender
                    for a in event.get("actors", [])
                ):
                    event.setdefault("actors", []).append(
                        {"name": sender, "role": "", "position": "entity"}
                    )
                result = _process_feedback(event)
                entry["action"] = "feedback_processed" if result.get("matched") else "feedback_unmatched"
                entry["feedback_result"] = result.get("matched", False)
                entry["match_type"] = result.get("match_type", "")
                task_id = result.get("task_id", "")
                if task_id:
                    entry["related_task"] = task_id
                    event["related_task"] = task_id
                if result.get("matched"):
                    feedback_matched += 1
                    # Record response time
                    try:
                        from datetime import datetime as _dt
                        task = _load_task_by_id(task_id)
                        if task and task.get("created_at"):
                            t1 = _dt.fromisoformat(task["created_at"])
                            t2 = _dt.fromisoformat(processed_at)
                            entry["response_hours"] = round((t2 - t1).total_seconds() / 3600, 1)
                            event["response_hours"] = entry["response_hours"]
                    except Exception:
                        entry["response_hours"] = None
                    # Feedback → observation (zero LLM)
                    try:
                        executor_name = result.get("executor", "")
                        text = f"{executor_name} 完成反馈 任务{task_id}"
                        if entry.get("response_hours"):
                            text += f" 响应{entry['response_hours']}h"
                        from memory.observation_store import write as obs_write
                        obs_write(text, source="feedback", obs_type="execution", layer="rule", confidence=0.9)
                        _accumulate_org_memory()
                    except Exception:
                        pass
                events_created += 1
                _record_event(event)
                log.append(entry)
                continue

            if event.get("event_type") in (
                "instruction", "notification", "announcement",
                "inspection", "report", "incident",
            ):
                ctx = _resolve_context(event, current_user)
                pos_type = ctx.get("my_position", {}).get("type", "observer")
                entry["position"] = pos_type

                if pos_type in ("coordinator", "executor", "supervisor"):
                    task = _create_task(event, ctx, current_user)
                    if task:
                        entry["action"] = "task_created"
                        entry["task_id"] = task.get("id", "")
                        tasks_created += 1
                    else:
                        entry["action"] = "task_failed"
                else:
                    entry["action"] = f"position_{pos_type}"

            events_created += 1
            _record_event(event)
            entry["action"] = entry.get("action", "event_recorded")

        except Exception as e:
            entry["action"] = "error"
            entry["error"] = str(e)[:100]
            errors += 1

        log.append(entry)

    return {
        "total_messages": len(messages),
        "events_created": events_created,
        "tasks_created": tasks_created,
        "feedback_matched": feedback_matched,
        "ignored": ignored,
        "errors": errors,
        "source_type": source_type,
        "source_file": source_file or "",
        "processed_at": processed_at,
        "log": log,
    }


def import_dir(
    dir_path: str,
    source_type: str = "history_txt",
    current_user=None,
) -> dict:
    """Process all .txt/.rtf files in a directory through the unified pipeline.

    Scans for *.txt and *.rtf, processes each via import_batch(),
    writes per-batch reports under data/reports/.

    Returns:
        {batch_id, source, started_at, finished_at,
         total_files, total_messages, total_events, total_tasks, total_errors,
         file_results, reports_dir}
    """
    from ingestion.validator import validate, audit_result

    source_dir = Path(dir_path)
    if not source_dir.is_dir():
        return {"error": f"目录不存在: {dir_path}"}

    import_files = sorted(list(source_dir.glob("*.txt")) + list(source_dir.glob("*.rtf")))
    if not import_files:
        return {"error": f"目录中没有 .txt 或 .rtf 文件: {dir_path}"}

    started_at = datetime.now()
    batch_id = f"batch_{started_at.strftime('%Y%m%d')}_001"

    reports_dir = ROOT / "state" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Load import registry for file-level dedup
    registry = _load_import_registry()

    file_results = []
    total_messages = 0
    total_events = 0
    total_tasks = 0
    total_errors = 0
    all_errors = []
    skipped_count = 0

    for fpath in import_files:
        try:
            file_bytes = fpath.read_bytes()
            file_hash = _hashlib.sha256(file_bytes).hexdigest()
            raw_text = file_bytes.decode("utf-8")
        except Exception as e:
            file_results.append({
                "file": fpath.name,
                "error": f"读取失败: {e}",
                "messages": 0, "events": 0, "tasks": 0, "errors": 1,
            })
            total_errors += 1
            all_errors.append({
                "file": fpath.name, "msg_id": "",
                "error": str(e), "content_preview": "",
            })
            continue

        # File-level dedup: skip if same hash already imported
        if _is_duplicate(registry, fpath.name, file_hash):
            skipped_count += 1
            print(f"  - 跳过(已导入): {fpath.name}")
            file_results.append({
                "file": fpath.name,
                "skipped": True,
                "reason": "duplicate",
                "messages": 0, "events": 0, "tasks": 0, "errors": 0,
            })
            continue

        # RTF conversion
        if fpath.suffix.lower() == ".rtf":
            from ingestion.rtf_parser import rtf_to_text
            raw_text = rtf_to_text(raw_text)

        pre = validate(raw_text)
        result = import_batch(raw_text, source_type=source_type, source_file=fpath.name, current_user=current_user)
        audit = audit_result(result)

        # Record successful import to registry
        _record_import_registry(fpath.name, file_hash)

        file_results.append({
            "file": fpath.name,
            "messages": result["total_messages"],
            "events": result["events_created"],
            "tasks": result["tasks_created"],
            "feedback_matched": result["feedback_matched"],
            "ignored": result["ignored"],
            "errors": result["errors"],
            "parse_quality": pre.get("parse_quality", 0),
            "entity_match": pre.get("entity_match", 0),
            "event_confidence": audit.get("event_confidence", 0),
            "task_conversion": audit.get("task_conversion", 0),
        })

        total_messages += result["total_messages"]
        total_events += result["events_created"]
        total_tasks += result["tasks_created"]
        total_errors += result["errors"]

        for entry in result["log"]:
            if entry.get("action") == "error":
                all_errors.append({
                    "file": fpath.name,
                    "msg_id": entry.get("msg_id", ""),
                    "error": entry.get("error", ""),
                    "content_preview": entry.get("content_preview", ""),
                })

    finished_at = datetime.now()
    duration_sec = round((finished_at - started_at).total_seconds(), 1)

    summary = {
        "batch_id": batch_id,
        "source": str(source_dir.resolve()),
        "source_type": source_type,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_at": finished_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_sec": duration_sec,
        "total_files": len(import_files),
        "total_messages": total_messages,
        "total_events": total_events,
        "total_tasks": total_tasks,
        "total_errors": total_errors,
        "skipped": skipped_count,
    }

    by_source = {"batch_id": batch_id, "files": file_results}
    errors_report = {"batch_id": batch_id, "total_errors": total_errors, "entries": all_errors}

    (reports_dir / "replay_summary.json").write_text(
        _json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports_dir / "replay_by_source.json").write_text(
        _json.dumps(by_source, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports_dir / "replay_errors.json").write_text(
        _json.dumps(errors_report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        **summary,
        "file_results": file_results,
        "reports_dir": str(reports_dir),
    }


# ── internal helpers ───────────────────────────────────────────────────


def _extract_event(text, current_user=None):
    from core.event import extract
    event = extract(text, current_user=current_user)
    if event.get("confidence", 0) > 0:
        event["confidence"] = round(event["confidence"] * 0.85, 2)
    return event


def _resolve_context(event, current_user=None):
    from core.context import resolve as ctx_resolve
    from core.context import load_user
    user = current_user or load_user()
    return ctx_resolve(event, user)


def _create_task(event, ctx, current_user=None):
    from organization.model import OrganizationModel
    from task.manager import TaskManager
    from core.context import load_user
    user = current_user or load_user()
    try:
        org = OrganizationModel()
        tm = TaskManager(org)
        return tm.create(event, ctx, user)
    except Exception:
        return None


def _process_feedback(event):
    from organization.model import OrganizationModel
    from task.manager import TaskManager
    try:
        tm = TaskManager(OrganizationModel())
        return tm.update_from_event(event)
    except Exception:
        return {"matched": False}


def _record_event(event):
    try:
        from memory.event_recorder import record
        record(event)
    except Exception:
        pass


def _load_task_by_id(task_id: str):
    """Load a single task by ID from tasks.json."""
    import json as _j
    task_path = ROOT / "state" / "tasks.json"
    if not task_path.exists():
        return None
    try:
        tasks = _j.loads(task_path.read_text(encoding="utf-8"))
        for t in tasks:
            if t.get("id") == task_id:
                return t
    except (_j.JSONDecodeError, FileNotFoundError):
        pass
    return None


def _accumulate_org_memory():
    """Update org_memory stats after feedback. Zero LLM."""
    try:
        from organization.memory_bridge import accumulate
        accumulate()
    except Exception:
        pass


# ── import registry helpers ─────────────────────────────────────────────


REGISTRY_PATH = ROOT / "state" / "import_registry.json"


def _load_import_registry() -> list:
    """Load import registry for file-level dedup."""
    if not REGISTRY_PATH.exists():
        return []
    try:
        return _json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, FileNotFoundError):
        return []


def _is_duplicate(registry: list, source_file: str, source_hash: str) -> bool:
    """Check if file with same hash was already imported."""
    for entry in registry:
        if entry.get("source_file") == source_file and entry.get("source_hash") == source_hash:
            if entry.get("status") == "completed":
                return True
    return False


def _record_import_registry(source_file: str, source_hash: str):
    """Record a successful import to the registry."""
    registry = _load_import_registry()
    registry.append({
        "source_file": source_file,
        "source_hash": source_hash,
        "import_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "completed",
    })
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(_json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
