#!/usr/bin/env python3
"""
scripts/bootstrap.py — 知识库冷启动预热脚本 (Phase 3.2 / Cipher 4.1).

燃烧 Knowledge/*.md 原始文档，炼化为 4 大核心资产：
  1. route_seeds.json  — Fast-Path FAISS 路由种子
  2. entity_index.json — 实体 SSOT (NER 专有名词)
  3. MemoryCore FAISS  — 向量知识索引 (chunk + embed)
  4. few_shots.json    — Agent 直觉样例 (CoT)

Usage:
  python3 scripts/bootstrap.py
  python3 scripts/bootstrap.py --dry-run    # 只打印不写入
"""

import json, logging, os, sys, re
from pathlib import Path

# ── path bootstrap ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "skills"))
from skills.shared.path import root as project_root

ROOT = project_root()
KNOWLEDGE_DIR = ROOT / "Knowledge"
ROUTE_SEEDS_PATH = ROOT / "skills" / "router" / "route_seeds.json"
ENTITY_INDEX_PATH = ROOT / "data" / "state" / "entity_index.json"
FEW_SHOTS_PATH = ROOT / "skills" / "agent" / "few_shots.json"

logging.basicConfig(
    level=logging.INFO,
    format="[bootstrap] %(levelname)s %(message)s",
)
logger = logging.getLogger("bootstrap")

DRY_RUN = "--dry-run" in sys.argv


# ── helpers ─────────────────────────────────────────────────────

def _atomic_write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if DRY_RUN:
        logger.info("[dry-run] would write %s (%d items)", path.name,
                    len(data) if isinstance(data, (list, dict)) else 0)
        return
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    logger.info("wrote %s", path)


def _load_markdown_files() -> list[tuple[str, str]]:
    """Return [(filename_stem, full_text), ...] from Knowledge/."""
    if not KNOWLEDGE_DIR.exists():
        logger.warning("Knowledge dir %s not found", KNOWLEDGE_DIR)
        return []
    files = []
    for fpath in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        if fpath.name.startswith("_") or fpath.name == "INDEX.md":
            continue
        text = fpath.read_text(encoding="utf-8").strip()
        if text:
            files.append((fpath.stem, text))
    logger.info("loaded %d markdown files from %s", len(files), KNOWLEDGE_DIR)
    return files


def _call_llm(prompt: str, system_prompt: str = "",
              temperature: float = 0.3, max_tokens: int = 2048) -> str:
    from skills.core.llm_client import call as llm_call
    result = llm_call(prompt, system_prompt=system_prompt,
                      temperature=temperature, max_tokens=max_tokens)
    if isinstance(result, dict) and "error" in result:
        logger.error("LLM call failed: %s", result["error"])
        return ""
    return str(result or "")


# ── 1/4 route seeds ────────────────────────────────────────────

def _build_route_seeds(files: list[tuple[str, str]]) -> dict:
    logger.info("[1/4] Generating route seeds from %d documents ...", len(files))
    combined = "\n\n".join(f"\n=== {name} ===\n{text[:2000]}" for name, text in files)
    prompt = (
        "You are a knowledge distillation engine for an enterprise agent (Cipher).\n"
        "Your task: extract high-frequency query patterns and FAQ-style questions from the "
        "following enterprise SOP / regulation documents, then produce colloquial variants.\n\n"
        f"Documents:\n{combined}\n\n"
        "Output a JSON object with exactly 4 keys: task_query, knowledge_retrieve, profile_query, event.\n"
        "Each key maps to an object with a 'seeds' array of 5~10 natural Chinese questions.\n"
        "- task_query: questions about daily work, tasks, schedules (e.g. '今天有什么任务')\n"
        "- knowledge_retrieve: questions about regulations, procedures, policies (e.g. '灭火器检查周期是多久')\n"
        "- profile_query: questions about people's roles, capabilities, info (e.g. '这个人怎么样')\n"
        "- event: statements that describe events, notifications, reports (e.g. '通知各班组明天开会')\n\n"
        "Output format (strict JSON, exactly this shape, no extra keys):\n"
        '{\n'
        '  "task_query": {"seeds": ["口语化问题1", "口语化问题2", ...]},\n'
        '  "knowledge_retrieve": {"seeds": [...]},\n'
        '  "profile_query": {"seeds": [...]},\n'
        '  "event": {"seeds": [...]}\n'
        "}\n\n"
        "Rules:\n"
        "1. Questions must sound like real user speech, not formal document titles.\n"
        "2. Cover diverse document topics; don't all come from the same file.\n"
        "3. Keep each question under 30 characters.\n"
        "4. Output ONLY the JSON object, no markdown fences, no commentary."
    )
    raw = _call_llm(prompt, max_tokens=4096, temperature=0.4)
    if not raw:
        logger.warning("[1/4] LLM returned empty, using existing seeds")
        if ROUTE_SEEDS_PATH.exists():
            return json.loads(ROUTE_SEEDS_PATH.read_text(encoding="utf-8"))
        return {}

    logger.debug("[1/4] LLM raw output (first 300 chars): %.300s", raw)

    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.IGNORECASE)
    try:
        seeds = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("[1/4] LLM output not valid JSON, falling back")
        logger.debug("[1/4] raw: %.300s", raw)
        if ROUTE_SEEDS_PATH.exists():
            return json.loads(ROUTE_SEEDS_PATH.read_text(encoding="utf-8"))
        return {"task_query": {"seeds": []}, "knowledge_retrieve": {"seeds": []},
                "profile_query": {"seeds": []}, "event": {"seeds": []}}

    if not isinstance(seeds, dict):
        logger.warning("[1/4] LLM returned a %s, falling back to existing seeds", type(seeds).__name__)
        if ROUTE_SEEDS_PATH.exists():
            fallback = json.loads(ROUTE_SEEDS_PATH.read_text(encoding="utf-8"))
            if isinstance(fallback, dict):
                return fallback
        return {"task_query": {"seeds": []}, "knowledge_retrieve": {"seeds": []},
                "profile_query": {"seeds": []}, "event": {"seeds": []}}

    # Normalize: LLM may return arrays directly instead of {"seeds": [...]}
    now = {"task_query", "knowledge_retrieve", "profile_query", "event"}
    for route in now:
        val = seeds.get(route)
        if isinstance(val, list):
            seeds[route] = {"seeds": val}
        elif not isinstance(val, dict):
            seeds[route] = {"seeds": []}

    # Merge with existing seeds (dedup preserve)
    existing = {}
    if ROUTE_SEEDS_PATH.exists():
        existing = json.loads(ROUTE_SEEDS_PATH.read_text(encoding="utf-8"))
    for route in ("task_query", "knowledge_retrieve", "profile_query", "event"):
        new_set = set(s.strip() for s in seeds.get(route, {}).get("seeds", []) if s.strip())
        old_set = set(s.strip() for s in existing.get(route, {}).get("seeds", []) if s.strip())
        merged = sorted(old_set | new_set)
        seeds.setdefault(route, {})["seeds"] = merged
    logger.info("[1/4] route seeds: task=%d knowledge=%d profile=%d event=%d",
                len(seeds.get("task_query", {}).get("seeds", [])),
                len(seeds.get("knowledge_retrieve", {}).get("seeds", [])),
                len(seeds.get("profile_query", {}).get("seeds", [])),
                len(seeds.get("event", {}).get("seeds", [])))
    return seeds


# ── 2/4 entity SSOT ────────────────────────────────────────────

def _extract_entities(files: list[tuple[str, str]]) -> dict:
    logger.info("[2/4] Extracting named entities from %d documents ...", len(files))
    combined = "\n\n".join(f"\n=== {name} ===\n{text[:3000]}" for name, text in files)
    prompt = (
        "Extract all named entities from the following enterprise documents.\n"
        "Entity types: person names, project code names, department names, "
        "specific tool/equipment names, location names, regulation titles.\n\n"
        f"Documents:\n{combined}\n\n"
        "Output a JSON list of objects:\n"
        '[{"name": "...", "type": "person|project|department|equipment|location|regulation", '
        '"aliases": ["...", "..."], "role": "..."}]\n\n'
        "Rules:\n"
        "1. person: full Chinese names (2-4 characters)\n"
        "2. project: code names like '台风XX' or event names\n"
        "3. department: organization/team names\n"
        "4. equipment: specific machine/system names\n"
        "5. location: workplace/warehouse names\n"
        "6. regulation: document/training names\n"
        "7. aliases are optional alternative names or abbreviations\n"
        "8. Deduplicate by name. Merge aliases if same name appears multiple times.\n"
        "Output ONLY the JSON array, no markdown fences."
    )
    raw = _call_llm(prompt, max_tokens=4096, temperature=0.2)
    if not raw:
        logger.warning("[2/4] LLM returned empty, skipping entity extraction")
        return {}

    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.IGNORECASE)
    new_entities = []
    try:
        new_entities = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("[2/4] LLM output not valid JSON")
        return {}

    if not isinstance(new_entities, list):
        logger.warning("[2/4] LLM output not a list")
        return {}

    # Merge with existing
    existing = {"confirmed_entities": [], "pending_entities": []}
    if ENTITY_INDEX_PATH.exists():
        try:
            existing = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    seen = {e["name"] for e in existing.get("confirmed_entities", [])
            if isinstance(e, dict)}
    for ne in new_entities:
        name = ne.get("name", "").strip()
        if not name or len(name) < 2:
            continue
        if name in seen:
            # merge aliases into existing
            for e in existing["confirmed_entities"]:
                if isinstance(e, dict) and e["name"] == name:
                    new_aliases = ne.get("aliases", [])
                    old_aliases = set(e.get("aliases", []))
                    for a in new_aliases:
                        if a and a not in old_aliases:
                            e.setdefault("aliases", []).append(a)
                    break
            continue
        seen.add(name)
        entry = {
            "name": name,
            "type": ne.get("type", "unknown"),
            "aliases": ne.get("aliases", []),
            "role": ne.get("role", ""),
            "source": "bootstrap/knowledge_extraction",
            "team": "",
        }
        existing["confirmed_entities"].append(entry)

    logger.info("[2/4] total entities: %d confirmed, %d pending",
                len(existing["confirmed_entities"]), len(existing["pending_entities"]))
    return existing


# ── 3/4 knowledge vector index ─────────────────────────────────

def _rebuild_knowledge_index():
    logger.info("[3/4] Rebuilding MemoryCore knowledge vector index ...")
    try:
        from memory.memory_core import MemoryCore
        mc = MemoryCore()
        mc._rebuild_full()
        logger.info("[3/4] knowledge index rebuilt (ntotal=%d)", mc.sem_index.ntotal)
    except Exception as e:
        logger.warning("[3/4] MemoryCore rebuild failed: %s", e)


# ── 4/4 few-shot CoT examples ──────────────────────────────────

def _build_few_shots(files: list[tuple[str, str]]) -> list[dict]:
    logger.info("[4/4] Generating few-shot CoT examples from complex SOPs ...")
    combined = "\n\n".join(f"\n=== {name} ===\n{text[:3000]}" for name, text in files[:6])
    prompt = (
        "You are generating few-shot Chain-of-Thought examples for an enterprise agent (Cipher).\n"
        "Each example shows: user message → agent thought → tool selection → parameters.\n\n"
        f"Available tools:\n"
        "- task_query(scope): query work schedules\n"
        "- knowledge_retrieve(topic): query regulations/knowledge\n"
        "- profile_query(name): query person profile\n"
        "- notification_push(title,content): send notification\n"
        "- event_record(summary[,time,people]): record an event\n"
        "- task_create(summary[,deadline,assignee]): create a task\n"
        "- task_feedback(action,executor[,task_id]): update task status\n"
        "- org_lookup(name): look up org relationships\n"
        "- correction_feedback(content[,context]): record a correction\n\n"
        f"Base your examples on these real documents:\n{combined}\n\n"
        "Output a JSON array of 8~12 examples. Each example:\n"
        '{"input": "realistic user message in Chinese",\n'
        ' "thought": "brief reasoning why this tool and these params",\n'
        ' "tool": "tool_id",\n'
        ' "params": {param_key: param_value}}\n\n'
        "Rules:\n"
        "1. Cover at least 5 different tools across all examples.\n"
        "2. inputs must sound like real operator speech, not formal.\n"
        "3. Include examples from the document content above.\n"
        "4. Output ONLY the JSON array, no markdown fences."
    )
    raw = _call_llm(prompt, max_tokens=4096, temperature=0.4)
    if not raw:
        logger.warning("[4/4] LLM returned empty, skipping few-shots")
        return []

    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.IGNORECASE)
    try:
        shots = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("[4/4] LLM output not valid JSON")
        return []

    if not isinstance(shots, list):
        logger.warning("[4/4] LLM output not a list")
        return []

    # Merge with existing
    existing = []
    if FEW_SHOTS_PATH.exists():
        try:
            existing = json.loads(FEW_SHOTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    seen_inputs = {e.get("input", "") for e in existing if isinstance(e, dict)}
    for s in shots:
        inp = s.get("input", "").strip()
        if inp and inp not in seen_inputs:
            seen_inputs.add(inp)
            existing.append(s)

    logger.info("[4/4] few-shot examples: %d total (%d new)",
                len(existing), len(shots))
    return existing


# ── final route index rebuild ──────────────────────────────────

def _rebuild_route_index():
    logger.info("Rebuilding FAISS route index ...")
    try:
        from skills.router.route_index import RouteIndexManager
        mgr = RouteIndexManager()
        mgr.build(ROUTE_SEEDS_PATH)
        logger.info("route index built successfully")
    except Exception as e:
        logger.warning("route index rebuild failed: %s", e)


# ── main ────────────────────────────────────────────────────────

def main():
    logger.info("=" * 50)
    logger.info("Cipher Knowledge Base Bootstrap v1.0")
    logger.info("Source: %s", KNOWLEDGE_DIR)
    if DRY_RUN:
        logger.info("[dry-run] mode — no files will be written")

    files = _load_markdown_files()
    if not files:
        logger.warning("No markdown files found, nothing to bootstrap")
        return

    # 1/4
    seeds = _build_route_seeds(files)
    _atomic_write(ROUTE_SEEDS_PATH, seeds)

    # 2/4
    entities = _extract_entities(files)
    if entities:
        _atomic_write(ENTITY_INDEX_PATH, entities)

    # 3/4
    if not DRY_RUN:
        _rebuild_knowledge_index()
    else:
        logger.info("[3/4] [dry-run] would rebuild MemoryCore index")

    # 4/4
    shots = _build_few_shots(files)
    _atomic_write(FEW_SHOTS_PATH, shots)

    # Final route index rebuild
    if not DRY_RUN:
        _rebuild_route_index()
    else:
        logger.info("[dry-run] would rebuild FAISS route index")

    logger.info("=" * 50)
    logger.info("Bootstrap complete. 4 assets generated.")
    logger.info("  1. route_seeds.json  -> %s", ROUTE_SEEDS_PATH)
    logger.info("  2. entity_index.json -> %s", ENTITY_INDEX_PATH)
    logger.info("  3. Knowledge FAISS   -> MemoryCore index rebuilt")
    logger.info("  4. few_shots.json    -> %s", FEW_SHOTS_PATH)


if __name__ == "__main__":
    main()
