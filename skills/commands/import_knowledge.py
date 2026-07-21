"""
commands/import_knowledge.py — Knowledge directory import entry point.

Usage:
    from commands.import_knowledge import import_knowledge
    import_knowledge()                # default: Knowledge/
    import_knowledge("custom_dir/")   # custom path

Pipeline:
    scanner → processor → indexer → store
"""

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_DIR))


def import_knowledge(dir_path=None) -> dict:
    """Import all .md files from directory into knowledge index.

    Handles incremental updates: only re-processes changed/added files,
    removes deleted ones.

    Args:
        dir_path: path to directory. Defaults to project_root/Knowledge/

    Returns:
        {files_added, files_modified, files_deleted, files_unchanged,
         total_chunks, total_files}
    """
    if dir_path is None:
        ROOT = Path(__file__).resolve().parent.parent.parent
        dir_path = str(ROOT / "Knowledge")

    from knowledge.scanner import scan
    from knowledge.processor import process
    from knowledge.indexer import rebuild
    from knowledge.store import save, load_all, remove_by_source, get_source_map, stats, deprecate_by_base, version_stats

    print(f"\n[import_knowledge] 来源目录: {dir_path}")

    existing_sources = get_source_map()
    changes = scan(dir_path, existing_sources)

    if not any(changes.values()):
        print("[import_knowledge] 无变化，跳过。")
        s = stats()
        print(f"[import_knowledge] 当前索引: {s['total_files']} 文件, {s['total_chunks']} 块")
        return {
            "files_added": 0, "files_modified": 0,
            "files_deleted": 0, "files_unchanged": len(changes.get("unchanged", [])),
            "total_chunks": s["total_chunks"], "total_files": s["total_files"],
        }

    print(f"[import_knowledge] 新增: {len(changes['added'])} 文件, "
          f"修改: {len(changes['modified'])} 文件, "
          f"删除: {len(changes['deleted'])} 文件")

    # Handle sibling conflicts: new version detected → deprecate old version
    for conflict in changes.get("sibling_conflicts", []):
        base = conflict["base_name"]
        old = conflict["old_file"]
        new = conflict["new_file"]
        count = deprecate_by_base(base)
        print(f"  ~ 版本切换: {base} ({old} → {new}), 废弃 {count} 个旧版块")

    # Process deleted files
    for fname in changes["deleted"]:
        removed = remove_by_source(fname)
        print(f"  - 删除: {fname} ({removed} 块)")

    # Process added and modified files
    for action, file_list in [("新增", changes["added"]), ("修改", changes["modified"])]:
        for fpath in file_list:
            fname = Path(fpath).name
            import hashlib
            fhash = hashlib.sha256(Path(fpath).read_bytes()).hexdigest()

            chunks = process(fpath)
            if not chunks:
                print(f"  - {action}: {fname} (无内容)")
                continue

            # Remove old chunks if modified
            if action == "修改":
                remove_by_source(fname)

            save(chunks, fname, fhash)
            print(f"  + {action}: {fname} ({len(chunks)} 块)")

    # Full index rebuild (FAISS doesn't support incremental delete)
    print("[import_knowledge] 重建 FAISS 索引...")
    all_entries = load_all()
    count = rebuild(all_entries)
    print(f"[import_knowledge] 索引完成: {count} 个向量")

    s = stats()
    vs = version_stats()
    print(f"[import_knowledge] 知识库: {s['total_files']} 文件, {s['total_chunks']} 块")
    print(f"[import_knowledge] 版本: active={vs['active']}, deprecated={vs['deprecated']}, archived={vs['archived']}")
    for fname, cnt in sorted(s["per_file"].items()):
        print(f"    {fname}: {cnt} 块")

    return {
        "files_added": len(changes["added"]),
        "files_modified": len(changes["modified"]),
        "files_deleted": len(changes["deleted"]),
        "files_unchanged": len(changes.get("unchanged", [])),
        "total_chunks": s["total_chunks"],
        "total_files": s["total_files"],
    }
