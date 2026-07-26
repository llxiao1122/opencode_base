#!/usr/bin/env python3
"""
scripts/migrate_observations.py — 存量 observation 迁移至统一 schema.

Changes:
  1. Converge legacy types (note→event, task_completion→task_feedback, etc.)
  2. Ensure layer field exists (default rule)
  3. Restructure body to ### Summary / ### Details format

Usage:
  python3 scripts/migrate_observations.py        # apply
  python3 scripts/migrate_observations.py --dry-run  # preview only
"""

import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills"))
sys.path.insert(0, str(ROOT))

OBS_DIR = ROOT / "data" / "memory" / "observations"
INDEX_PATH = OBS_DIR / ".index.json"

TYPE_MIGRATION = {
    "note": "event",
    "task_completion": "task_feedback",
    "task_update": "task_feedback",
    "dingtalk": "notification",
    "push": "notification",
}

DRY_RUN = "--dry-run" in sys.argv


def _rebuild_section(sec: str) -> str:
    """Extract raw metadata + body from any format, rebuild in canonical form."""
    lines = sec.strip().split("\n")
    meta = {"##": "", "source": "", "type": "", "layer": "", "confidence": ""}
    body_parts = []
    in_summary_or_details = False

    for l in lines:
        if l.startswith("### "):
            in_summary_or_details = True
            continue
        if l.startswith("## "):
            meta["##"] = l
            continue
        if l.startswith("source:"):
            meta["source"] = l
            continue
        if l.startswith("type:"):
            meta["type"] = l
            continue
        if l.startswith("layer:"):
            meta["layer"] = l
            continue
        if l.startswith("confidence:"):
            meta["confidence"] = l
            continue
        if not l.strip():
            continue
        body_parts.append(l)

    # Converge legacy types
    _t = meta.get("type", "")
    for old_t, new_t in TYPE_MIGRATION.items():
        if _t.strip().endswith(old_t):
            meta["type"] = f"type: {new_t}"
            break
    # Ensure layer
    if not meta.get("layer", "").strip():
        meta["layer"] = "layer: rule"
    # Ensure source
    if not meta.get("source", "").strip():
        meta["source"] = "source: unknown"

    body = "\n".join(body_parts).strip()
    if not body:
        body = "ok"
    first_line = body.split("\n")[0][:80]
    rest = "\n".join(body.split("\n")[1:]).strip() if "\n" in body else ""
    new_body = f"### Summary\n{first_line}\n\n### Details\n{rest}" if rest else f"### Summary\n{first_line}\n\n### Details\n{first_line}"

    header_parts = [meta.get(k, "") for k in ("##", "source", "type", "layer") if meta.get(k, "").strip()]
    header = "\n".join(header_parts).strip()
    out = header + "\n\n" + new_body
    if meta.get("confidence", "").strip():
        out += "\n" + meta["confidence"]
    return out


def _migrate_file(fpath: Path) -> bool:
    content = fpath.read_text(encoding="utf-8")
    original = content

    sections = content.split("\n---\n")
    rebuilt = []
    changed = False
    for sec in sections:
        if not sec.strip():
            rebuilt.append(sec)
            continue
        new_sec = _rebuild_section(sec)
        if new_sec != sec.strip():
            changed = True
        rebuilt.append(new_sec)

    if changed:
        content = "\n---\n".join(rebuilt)

    if content != original:
        if DRY_RUN:
            print(f"  [dry-run] would update {fpath.relative_to(OBS_DIR)}")
        else:
            fpath.write_text(content, encoding="utf-8")
        return True
    return False


def main():
    print(f"{'[dry-run] ' if DRY_RUN else ''}Migrating observations in {OBS_DIR} ...")
    total = 0
    changed = 0
    for subj_type in ["people", "teams", "system"]:
        d = OBS_DIR / subj_type
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name.startswith("_"):
                continue
            total += 1
            if _migrate_file(f):
                changed += 1

    # Rebuild index
    if not DRY_RUN:
        from skills.memory.observation_store import rebuild_index
        rebuild_index()
        print(f"Index rebuilt: {INDEX_PATH}")
    else:
        print("  [dry-run] would rebuild index")

    print(f"\nDone: {total} files scanned, {changed} migrated.")


if __name__ == "__main__":
    main()
