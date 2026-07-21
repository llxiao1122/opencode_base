"""
commands/import_history.py — User-facing import entry point.

Usage:
    from commands.import_history import import_history
    import_history()            # default: files/
    import_history("history/")  # custom dir

Pipeline:
    validate() → import_dir() → memory_bridge.accumulate()
"""

import json
from pathlib import Path
from datetime import datetime


def import_history(dir_path=None) -> dict:
    """Import all .txt/.rtf files from directory into enterprise cognitive system.

    Args:
        dir_path: path to directory. Defaults to project_root/files/

    Returns:
        dict with batch summary + organization memory snapshot
    """
    if dir_path is None:
        ROOT = Path(__file__).resolve().parent.parent.parent
        dir_path = str(ROOT / "files")

    import sys
    TOOLS_DIR = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(TOOLS_DIR))

    from ingestion.batch_importer import import_dir

    ROOT = Path(__file__).resolve().parent.parent.parent

    started_at = datetime.now()
    batch_id = f"batch_{started_at.strftime('%Y%m%d')}_001"

    print(f"\n[import_history] 批次: {batch_id}")
    print(f"[import_history] 来源目录: {dir_path}")
    print("[import_history] 启动导入管线...\n")

    result = import_dir(dir_path, source_type="history_txt")
    if "error" in result:
        print(f"[import_history] 错误: {result['error']}")
        _record_batch(batch_id, dir_path, started_at, datetime.now(), result, error=result["error"])
        return result

    finished_at = datetime.now()

    print(f"\n[import_history] 导入完成: "
          f"{result['total_files']} 文件, "
          f"{result['total_messages']} 条消息, "
          f"{result['total_events']} 事件, "
          f"{result['total_tasks']} 任务, "
          f"{result.get('skipped', 0)} 跳过, "
          f"{result['total_errors']} 错误")
    print(f"[import_history] 报告: {result.get('reports_dir', '')}")

    print("[import_history] 积累组织记忆...")
    from organization.memory_bridge import accumulate
    mem = accumulate()
    print(f"[import_history] 组织记忆: {mem['sources']['events']} 事件, "
          f"{len(mem['people'])} 人物")

    # Deprecated: curiosity_engine removed

    _record_batch(batch_id, dir_path, started_at, finished_at, result)

    return {
        "batch_id": batch_id,
        "batch": result,
        "org_memory_people": len(mem.get("people", {})),
        "org_memory_path": str(ROOT / "state" / "org_memory.json"),
    }


def _record_batch(batch_id: str, dir_path: str, started_at: datetime,
                  finished_at: datetime, result: dict, error=""):
    """Record batch import to import_batches.json."""
    ROOT = Path(__file__).resolve().parent.parent.parent
    batches_path = ROOT / "state" / "import_batches.json"

    batches = []
    if batches_path.exists():
        try:
            batches = json.loads(batches_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            batches = []

    batch = {
        "batch_id": batch_id,
        "source": str(Path(dir_path).resolve()),
        "start_time": started_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "end_time": finished_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "error" if error else "completed",
        "error": error or "",
        "statistics": {
            "files": result.get("total_files", 0) if not error else 0,
            "messages": result.get("total_messages", 0) if not error else 0,
            "events": result.get("total_events", 0) if not error else 0,
            "tasks": result.get("total_tasks", 0) if not error else 0,
            "skipped": result.get("skipped", 0) if not error else 0,
            "errors": result.get("total_errors", 0) if not error else 0,
        },
    }

    batches.append(batch)
    batches_path.parent.mkdir(parents=True, exist_ok=True)
    batches_path.write_text(json.dumps(batches, ensure_ascii=False, indent=2), encoding="utf-8")


def clipboard_import(text: str) -> dict:
    """Import manually copied chat history (no reliable timestamps).

    Processes text through the full cognitive pipeline but marks
    data as low-quality. Uses source_type="clipboard_history".
    No time data is fabricated — event_time stays empty.

    Args:
        text: raw copied text from DingTalk/WeChat group chat

    Returns:
        dict with {messages, events, tasks, data_quality}
    """
    import sys
    TOOLS_DIR = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(TOOLS_DIR))

    from ingestion.batch_importer import import_batch
    from organization.memory_bridge import accumulate

    print("\n[clipboard_import] 处理手工复制文本...")

    result = import_batch(
        text,
        source_type="clipboard_history",
        source_file="clipboard_paste",
    )

    print(f"[clipboard_import] 完成: "
          f"{result['total_messages']} 条消息, "
          f"{result['events_created']} 事件, "
          f"{result['tasks_created']} 任务")

    print("[clipboard_import] 积累组织记忆...")
    mem = accumulate()
    print(f"[clipboard_import] 组织记忆: {mem['sources']['events']} 事件, "
          f"{len(mem['people'])} 人物")

    return {
        "messages": result["total_messages"],
        "events": result["events_created"],
        "tasks": result["tasks_created"],
        "source_type": "clipboard_history",
        "log": result.get("log", []),
    }
