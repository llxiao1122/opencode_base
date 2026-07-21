"""
knowledge/scanner.py — Incremental file scanner for Knowledge directory.

Detects added, modified, and deleted .md files using SHA256 hashes.
Compares against existing metadata in knowledge_index.json.
"""

import hashlib
from pathlib import Path


def scan(dir_path: str, existing_sources: dict = None) -> dict:
    """Scan directory for .md files and detect changes.

    Args:
        dir_path: path to Knowledge directory
        existing_sources: {filename: sha256_hash} from existing index

    Returns:
        {added: [filepaths], modified: [filepaths], unchanged: [filepaths],
         deleted: [filenames], sibling_conflicts: [{new_file, old_file, base_name}]}
    """
    source_dir = Path(dir_path)
    if not source_dir.is_dir():
        return {"added": [], "modified": [], "unchanged": [], "deleted": [],
                "sibling_conflicts": []}

    existing = existing_sources or {}

    current_files = {}
    for fpath in sorted(source_dir.glob("*.md")):
        h = _hash_file(fpath)
        if h:
            current_files[fpath.name] = h

    # Build base_name map for both current and existing files
    from knowledge.processor import _extract_metadata

    existing_base_map = {}     # base_name → [source_file, ...]
    for fname in existing:
        meta = _extract_metadata(str(source_dir / fname))
        bn = meta["base_name"]
        existing_base_map.setdefault(bn, []).append(fname)

    current_base_map = {}      # base_name → [source_file, ...]
    for fname in current_files:
        meta = _extract_metadata(str(source_dir / fname))
        bn = meta["base_name"]
        current_base_map.setdefault(bn, []).append(fname)

    added = []
    modified = []
    unchanged = []
    deleted = []
    sibling_conflicts = []

    for fname, fhash in current_files.items():
        if fname not in existing:
            added.append(str(source_dir / fname))
            # Check for sibling: same base_name, but different filename
            meta = _extract_metadata(str(source_dir / fname))
            bn = meta["base_name"]
            if bn in existing_base_map:
                for old_fname in existing_base_map[bn]:
                    if old_fname != fname:
                        sibling_conflicts.append({
                            "new_file": fname,
                            "old_file": old_fname,
                            "base_name": bn,
                        })
        elif existing[fname] != fhash:
            modified.append(str(source_dir / fname))
        else:
            unchanged.append(str(source_dir / fname))

    for fname in existing:
        if fname not in current_files:
            deleted.append(fname)

    return {
        "added": sorted(added),
        "modified": sorted(modified),
        "unchanged": sorted(unchanged),
        "deleted": sorted(deleted),
        "sibling_conflicts": sibling_conflicts,
    }


def _hash_file(filepath: Path) -> str:
    try:
        content = filepath.read_bytes()
        return hashlib.sha256(content).hexdigest()
    except Exception:
        return ""
