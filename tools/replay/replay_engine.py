"""
replay/replay_engine.py — Deprecated compatibility wrapper.

This module is kept for backward compatibility only.
All logic now lives in ingestion/batch_importer.py.

Use import_history() from commands/import_history.py for new code.
"""

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))


def replay(text: str, source_file: str = "", current_user=None) -> dict:
    """Deprecated. Use ingestion.batch_importer.import_batch() instead."""
    from ingestion.batch_importer import import_batch
    return import_batch(
        text,
        source_type="history_txt",
        source_file=source_file or "history_replay",
        current_user=current_user,
    )


def replay_dir(dir_path: str, current_user=None) -> dict:
    """Deprecated. Use ingestion.batch_importer.import_dir() instead."""
    from ingestion.batch_importer import import_dir
    return import_dir(dir_path, source_type="history_txt", current_user=current_user)
