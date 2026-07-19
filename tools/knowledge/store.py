"""
knowledge/store.py — Knowledge block metadata persistence.

Manages knowledge_index.json: maps chunk IDs to metadata.
Used for incremental updates: find chunks by source file for delete/replace.
"""

import json
from pathlib import Path
from datetime import datetime

TOOLS_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = TOOLS_DIR.parent / "data" / "knowledge" / "knowledge_index.json"


def save(chunks: list, source_file: str, source_hash: str):
    """Save knowledge chunk metadata. Replaces existing entries for source_file.

    Args:
        chunks: list of {section_path, text, type, version, base_name, status} from processor
        source_file: original filename (basename)
        source_hash: SHA256 of source file
    """
    existing = load_all()
    existing = [e for e in existing if e.get("source_file") != source_file]

    indexed_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for i, c in enumerate(chunks):
        existing.append({
            "id": _chunk_id(source_file, i),
            "source_file": source_file,
            "source_hash": source_hash,
            "base_name": c.get("base_name", ""),
            "version": c.get("version", "v1"),
            "section_path": c.get("section_path", []),
            "text": c["text"],
            "type": c.get("type", "reference"),
            "status": c.get("status", "active"),
            "indexed_at": indexed_at,
        })

    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all() -> list:
    """Load all knowledge chunk metadata."""
    if not STORE_PATH.exists():
        return []
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def find_by_source(source_file: str) -> list:
    """Find all chunk metadata for a given source file."""
    return [e for e in load_all() if e.get("source_file") == source_file]


def find_by_id(chunk_id: str) -> dict:
    """Find a single chunk by ID."""
    for e in load_all():
        if e.get("id") == chunk_id:
            return e
    return {}


def remove_by_source(source_file: str) -> int:
    """Remove all chunks for a source file. Returns count removed."""
    existing = load_all()
    before = len(existing)
    remaining = [e for e in existing if e.get("source_file") != source_file]
    after = len(remaining)
    STORE_PATH.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
    return before - after


def get_source_map() -> dict:
    """Get {filename: source_hash} for all indexed files."""
    sources = {}
    for e in load_all():
        sf = e.get("source_file", "")
        sh = e.get("source_hash", "")
        if sf and sh:
            sources[sf] = sh
    return sources


def stats() -> dict:
    """Return index statistics."""
    entries = load_all()
    files = {}
    for e in entries:
        sf = e.get("source_file", "")
        files[sf] = files.get(sf, 0) + 1
    return {
        "total_chunks": len(entries),
        "total_files": len(files),
        "per_file": files,
    }


def deprecate_by_base(base_name: str) -> int:
    """Mark all chunks with given base_name as deprecated.
    
    Only called when a new version is detected, never unilaterally.
    Returns count of chunks deprecated.
    """
    entries = load_all()
    changed = 0
    for e in entries:
        if e.get("base_name", "") == base_name and e.get("status") == "active":
            e["status"] = "deprecated"
            e["deprecated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            changed += 1
    if changed:
        STORE_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def list_versions(base_name: str) -> list:
    """List all versions of a document, grouped by version."""
    entries = [e for e in load_all() if e.get("base_name", "") == base_name]
    versions = {}
    for e in entries:
        v = e.get("version", "v1")
        if v not in versions:
            versions[v] = {"version": v, "status": e.get("status", "active"), "source_file": e.get("source_file", ""), "chunk_count": 0}
        versions[v]["chunk_count"] += 1
    return sorted(versions.values(), key=lambda x: x["version"])


def version_stats() -> dict:
    """Return per-version summary of all indexed documents."""
    entries = load_all()
    active_count = sum(1 for e in entries if e.get("status") == "active")
    deprecated_count = sum(1 for e in entries if e.get("status") == "deprecated")
    archived_count = sum(1 for e in entries if e.get("status") == "archived")
    return {
        "active": active_count,
        "deprecated": deprecated_count,
        "archived": archived_count,
        "total": len(entries),
    }


def _chunk_id(source_file: str, index: int) -> str:
    import hashlib
    h = hashlib.md5(f"{source_file}:{index}".encode()).hexdigest()[:8]
    return f"kb_{h}"
