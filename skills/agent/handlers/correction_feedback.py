import json
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
KNOWLEDGE_DIR = ROOT_DIR / "Knowledge"
CORRECTIONS_FILE = KNOWLEDGE_DIR / "05-行政综合" / "15-员工纠错反馈.md"


def _append_knowledge(content: str, context: str):
    date_tag = datetime.now().strftime("%Y-%m-%d")
    section = context.strip() or "通用知识纠正"
    entry = (
        f"\n---\n"
        f"### {section}\n"
        f"_归档于 {date_tag}_\n"
        f"{content}\n"
    )
    CORRECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CORRECTIONS_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def _rebuild_indexes():
    try:
        from skills.router.builder import build as build_entities
        build_entities()
    except Exception:
        pass
    try:
        from skills.router.faiss_router import _get_index as build_route
        build_route()
    except Exception:
        pass
    try:
        from memory.memory_core import MemoryCore
        mc = MemoryCore()
        mc._rebuild_full()
    except Exception:
        pass


def handle(content: str, context: str = ""):
    _append_knowledge(content, context)
    _rebuild_indexes()
    return f"[Cipher:correction]\n✅ 纠正已记录至知识库并重建索引"
