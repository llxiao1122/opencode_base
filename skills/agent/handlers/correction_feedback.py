import logging
from datetime import datetime
from pathlib import Path
import portalocker

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
KNOWLEDGE_DIR = ROOT_DIR / "Knowledge"
CORRECTIONS_FILE = KNOWLEDGE_DIR / "05-行政综合" / "15-员工纠错反馈.md"

logger = logging.getLogger(__name__)


def handle(content: str, context: str = ""):
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
        portalocker.lock(f, portalocker.LOCK_EX)
        f.write(entry)
    try:
        from skills.router.faiss_router import _get_index as build_route
        build_route()
    except Exception as e:
        logger.warning("route index rebuild failed: %s", e, exc_info=True)
    try:
        from skills.router.entity_resolver import resolve_entities
        from skills.memory.worldview import update_entity
        resolved = resolve_entities(content)
        for e in resolved.get("entities", []):
            update_entity(e["name"], [content[:500]])
    except Exception as exc:
        logger.debug("entity update failed: %s", exc)
    return f"[Cipher:correction]\n✅ 纠正已记录"
