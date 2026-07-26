"""
memory/observation_store.py — Observation Store with index.
Index: data/memory/observations/.index.json — auto-maintained for fast search.
"""

import json, logging, re, threading, os
from pathlib import Path
from datetime import date, datetime, timedelta
from enum import Enum

from skills.shared.path import ensure_paths, root as _root
from skills.shared.schema import ObservationType, ObservationLayer

ensure_paths()

logger = logging.getLogger(__name__)

ROOT = _root()
OBS_DIR = ROOT / "data" / "memory" / "observations"
INDEX_PATH = OBS_DIR / ".index.json"
ENTITY_PATH = ROOT / "data" / "state" / "entity_index.json"


TYPE_MAP = {
    "note": ObservationType.EVENT,
    "task_completion": ObservationType.TASK_FEEDBACK,
    "task_update": ObservationType.TASK_FEEDBACK,
    "dingtalk": ObservationType.NOTIFICATION,
    "push": ObservationType.NOTIFICATION,
}

_write_lock = threading.Lock()
_faiss_lock = threading.Lock()

_entity_names = None
_EXCLUDED_PEOPLE = {"值班", "现场管理与6S"}


def reset_cache():
    global _entity_names
    _entity_names = None
_team_keywords = ["铁炉西工班", "物资总库", "综合工班"]


def _load_entity_names() -> list:
    global _entity_names
    if _entity_names is not None:
        return _entity_names
    _entity_names = []
    if ENTITY_PATH.exists():
        try:
            data = json.loads(ENTITY_PATH.read_text(encoding="utf-8"))
            as_list = data if isinstance(data, list) else data.get("confirmed_entities", [])
            _entity_names = [e["name"] for e in as_list if isinstance(e, dict)]
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug("load entity names failed: %s", e)
    return _entity_names


# ── index ──────────────────────────────────────────────────────────────


def _load_index() -> dict:
    default = {"version": 1, "updated": "", "subjects": {}}
    if not INDEX_PATH.exists():
        return default
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("load index failed, returning default: %s", e)
        return default


def _save_index(idx: dict):
    idx["updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    tmp = Path(str(INDEX_PATH) + ".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX_PATH)


def _index_key(subj_type: str, subj_name: str) -> str:
    return f"{subj_type}/{subj_name}"


def _ensure_subject(idx: dict, key: str, filepath: str):
    if key not in idx["subjects"]:
        idx["subjects"][key] = {"file": filepath, "sections": []}


def _update_index(subj_type: str, subj_name: str, section_date: str,
                  obs_type: str, summary: str):
    key = _index_key(subj_type, subj_name)
    filepath = f"{subj_type}/{subj_name}.md"
    idx = _load_index()
    _ensure_subject(idx, key, filepath)

    existing = idx["subjects"][key]["sections"]
    existing.append({
        "date": section_date,
        "type": obs_type,
        "summary": summary[:80],
    })
    _save_index(idx)


# ── public API ─────────────────────────────────────────────────────────


def write(text: str, source: str = "", obs_type: str = "",
          layer: str = "rule", confidence: float = 0.0):
    _ot = ObservationType
    _ol = ObservationLayer
    obs_type = TYPE_MAP.get(obs_type, _ot(obs_type).value if obs_type in _ot.__members__ else obs_type)
    if layer not in {e.value for e in _ol} and layer not in [getattr(_ol, m).value for m in _ol.__members__]:
        layer = "rule"
    subj_type, subj_name = _route(text)
    target_dir = OBS_DIR / subj_type
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / f"{subj_name}.md"

    today = date.today().isoformat()
    first_line = text.strip().split("\n")[0][:80]
    second_line = ""
    parts = text.strip().split("\n", 1)
    if len(parts) > 1 and parts[1].strip():
        second_line = parts[1].strip()
    summary = first_line
    details = second_line if second_line else first_line
    new_section = (
        f"\n---\n\n## {today}\n\n"
        f"source: {source}\n"
        f"type: {obs_type}\n"
        f"layer: {layer}\n\n"
        f"### Summary\n{summary}\n\n"
        f"### Details\n{details}\n"
    )
    if confidence > 0:
        new_section += f"confidence: {confidence}\n"

    with _write_lock:
        existing = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
        if _can_merge(existing, text, source, obs_type, today):
            merged = _apply_merge(existing, text, source, obs_type, today)
            filepath.write_text(merged, encoding="utf-8")
        else:
            filepath.write_text(existing + new_section, encoding="utf-8")

        _update_index(subj_type, subj_name, today, obs_type,
                      text.strip().split("\n")[0])

    # LLM classification for Knowledge/people routing (fire-and-forget)
    if not os.environ.get("OP_SKIP_BG"):
        try:
            threading.Thread(target=_run_classify, args=(text, source), daemon=True).start()
        except Exception as e:
            logger.warning("classify thread start failed: %s", e, exc_info=True)


_KNOWLEDGE_FILES = [
    "01-仓储业务/00-日常工作指引.md", "01-仓储业务/01-采购与计划.md",
    "01-仓储业务/06-工作指导手册.md", "01-仓储业务/10-现场管理与6S.md",
    "01-仓储业务/17-物资仓储管理办法-B1.md",
    "01-仓储业务/18-物资验收入库管理规定-A2.md",
    "01-仓储业务/19-二级仓库管理规定-A5.md",
    "01-仓储业务/20-修复件和周转件管理细则-A1.md",
    "02-安全与应急/05-安全管理.md",
    "02-安全与应急/13-法规标准.md",
    "02-安全与应急/14-特种设备证书台账.md",
    "02-安全与应急/16-台风红霞保障方案.md",
    "02-安全与应急/消防知识提炼.md",
    "03-危废与废旧/22-危险废物回收及处置规定-A3.md",
    "03-危废与废旧/23-报废物资回收及处置规定-A3.md",
    "04-资产与鉴定/24-通用类实物资产报废技术鉴定管理规定-V1.2.md",
    "05-行政综合/04-制度修订记录.md", "05-行政综合/07-工作台账与工具.md",
    "05-行政综合/08-培训与学习资料.md", "05-行政综合/09-公文模板与规范.md",
    "05-行政综合/11-三菱备件专项.md", "05-行政综合/12-评估表.md",
    "05-行政综合/15-员工纠错反馈.md", "05-行政综合/21-捐赠物资管理细则-A2.md",
    "05-行政综合/物资管理.md", "05-行政综合/此心安处.md",
    "05-行政综合/物资管理部物资调配室绩效考核细则.md",
]


def _knowledge_tail(filename, lines=20):
    path = ROOT / "Knowledge" / filename
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8")
        return "\n".join(content.strip().split("\n")[-lines:])
    except Exception as e:
        logger.debug("read knowledge tail failed: %s", e)
        return ""


def _llm_classify(text, filenames):
    prompt = (
        "分析以下信息属于什么类型，应该归档到什么位置。\n\n"
        f"信息：{text[:500]}\n\n"
        "可选 Knowledge 文档：\n" + "\n".join(f"- {f}" for f in filenames) + "\n\n"
        "分类定义：\n"
        "- personal：某人的行为、事件、表现、评价 → observations/people\n"
        "- knowledge：制度、规则、流程、决定 → Knowledge/对应文档\n"
        "- analysis：分析、评论、思想、评价 → observations/system\n"
        "- policy：政策、方针、领导指示 → observations/system\n\n"
        "返回 JSON 数组（可多选），每项格式：\n"
        "{\n"
        '  "category": "personal|knowledge|analysis|policy",\n'
        '  "target": "knowledge 时为文档名，其他为空",\n'
        '  "content": "10字摘要",\n'
        '  "confidence": 0.0-1.0\n'
        "}\n只返回 JSON 数组。"
    )
    try:
        from skills.core.llm_client import call as llm_call
        raw = llm_call(prompt, system_prompt="你是一个信息分类助手，只输出 JSON。",
                       max_tokens=500, temperature=0.1)
        raw = str(raw).strip() if raw else ""
        raw = raw.strip()
        if not raw:
            return []
        import json as _j
        result = _j.loads(raw)
        return result if isinstance(result, list) else []
    except Exception as e:
        logger.debug("LLM classify failed: %s", e)
        return []


def _dedup_check(filename, text):
    tail = _knowledge_tail(filename, lines=15)
    if not tail:
        return "append"
    prompt = (
        f"目标文件：{filename}\n"
        f"文件末尾内容：\n{tail}\n\n"
        f"新内容：{text[:300]}\n\n"
        "判断新内容是否已存在于文件末尾中。"
        "返回 JSON：{\"action\": \"skip|append\", \"reason\": \"10字理由\"}"
    )
    try:
        from skills.core.llm_client import call as llm_call
        raw = llm_call(prompt, system_prompt="只返回 JSON。",
                       max_tokens=100, temperature=0.1)
        raw = str(raw).strip() if raw else ""
        raw = raw.strip()
        if not raw:
            return "append"
        import json as _j
        d = _j.loads(raw)
        return d.get("action", "append")
    except Exception as e:
        logger.warning("dedup check failed: %s", e)
        return "append"


def _append_knowledge(filename, text, confidence):
    path = ROOT / "Knowledge" / filename
    if not path.exists():
        return
    today = date.today().isoformat()
    first_line = text.strip().split("\n")[0][:60]
    entry = (
        f"\n\n---\n### {first_line}\n"
        f"_归档于 {today}_\n"
        f"{text}\n"
    )
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning("append knowledge file failed: %s", e, exc_info=True)
        return

    # Incrementally update FAISS semantic index so new entry is immediately searchable
    with _faiss_lock:
        try:
            from memory.memory_core import MemoryCore
            mc = MemoryCore()
            vec = mc._embed(text[:500])
            mc.sem_index.add(vec)
            eid = f"sem-{mc.sem_index.ntotal:04d}"
            mc.meta["id_map"][eid] = {"chunk": text[:500], "source": filename}
            mc._save_index("semantic", mc.sem_index)
            mc._save_meta()
            mc._search_raw.cache_clear()
        except Exception as e:
            logger.warning("FAISS incremental update failed: %s", e, exc_info=True)


def _run_classify(text, source=""):
    if source == "llm_classify":
        return
    try:
        results = _llm_classify(text, _KNOWLEDGE_FILES)
        if not results:
            return
        all_targets = set()
        for r in results:
            cat = r.get("category")
            conf = r.get("confidence", 0)
            if conf < 0.7:
                continue
            if cat == "personal":
                content = r.get("content", "")
                if content:
                    write(content, source="llm_classify",
                          obs_type="event", layer="rule", confidence=conf)
            elif cat == "knowledge":
                target = r.get("target", "")
                if target in _KNOWLEDGE_FILES and target not in all_targets:
                    all_targets.add(target)
                    action = _dedup_check(target, text)
                    if action == "append":
                        _append_knowledge(target, r.get("content", text[:100]), conf)
    except Exception as e:
        logger.warning("run_classify failed: %s", e, exc_info=True)


def read(subject_type: str, subject_name: str) -> str:
    filepath = OBS_DIR / subject_type / f"{subject_name}.md"
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8")


def search(target: str, obs_type: str = None,
           since_days: int = None, top_k: int = 10) -> list:
    idx = _load_index()
    now = date.today()
    cutoff = now - timedelta(days=since_days) if since_days else date.min

    candidates = _filter_index(idx, target, obs_type, cutoff)
    if not candidates:
        return []

    file_groups = {}
    for key, section_dates in candidates.items():
        rel = Path(key)
        subject_dir = str(rel.parent)
        subject_name = rel.name
        fpath = OBS_DIR / subject_dir / f"{subject_name}.md"
        if fpath not in file_groups:
            file_groups[fpath] = []
        file_groups[fpath].extend(section_dates)

    results = []
    for fpath, wanted_dates in file_groups.items():
        if not fpath.exists():
            continue
        subj_name = fpath.stem
        content = fpath.read_text(encoding="utf-8")
        section_texts = content.split("\n---\n")
        for sec in section_texts:
            if not sec.strip():
                continue
            sec_date = _parse_section_date(sec)
            if sec_date and sec_date.isoformat() in wanted_dates:
                parsed = _extract_fact(sec)
                if parsed:
                    parsed["subject"] = subj_name
                    results.append(parsed)

    results.sort(key=lambda r: r.get("time", ""), reverse=True)
    return results[:top_k]


def rebuild_index():
    """Scan all observation files and rebuild .index.json from scratch."""
    idx = {"version": 1, "updated": "", "subjects": {}}
    for subj_type in ["people", "teams", "system"]:
        d = OBS_DIR / subj_type
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            if f.name.startswith("_"):
                continue
            key = f"{subj_type}/{f.name.replace('.md', '')}"
            filepath = str(f.relative_to(OBS_DIR))
            _ensure_subject(idx, key, filepath)
            content = f.read_text(encoding="utf-8")
            sections = content.split("\n---\n")
            for sec in sections:
                if not sec.strip():
                    continue
                sec_date = _parse_section_date(sec)
                if not sec_date:
                    continue
                obs_type = ""
                summary = ""
                for l in sec.strip().split("\n"):
                    if l.startswith("type:"):
                        obs_type = l.replace("type:", "").strip()
                    elif not l.startswith("##") and not l.startswith("source:") and not l.startswith("layer:") and not l.startswith("confidence:") and l.strip():
                        if not summary:
                            summary = l.strip()[:80]
                if summary:
                    idx["subjects"][key]["sections"].append({
                        "date": sec_date.isoformat(),
                        "type": obs_type,
                        "summary": summary,
                    })
    _save_index(idx)
    return idx


# ── internal helpers ───────────────────────────────────────────────────


def _filter_index(idx, target, obs_type, cutoff_date):
    """Filter index and return {key: set of date strings} matching criteria."""
    matched = {}
    for key, info in idx.get("subjects", {}).items():
        if target and target not in key and target not in _subject_summaries(info):
            continue
        matching_dates = set()
        for sec in info.get("sections", []):
            if obs_type and sec.get("type") != obs_type:
                continue
            try:
                sd = date.fromisoformat(sec["date"])
            except (ValueError, KeyError) as e:
                logger.debug("skipping invalid date in index: %s", e)
                continue
            if sd < cutoff_date:
                continue
            if target and target not in sec.get("summary", ""):
                if target not in key:
                    continue
            matching_dates.add(sec["date"])
        if matching_dates:
            matched[key] = matching_dates
    return matched


def _subject_summaries(info: dict) -> str:
    parts = [s.get("summary", "") for s in info.get("sections", [])]
    return " ".join(parts)


def _parse_section_date(sec: str) -> date:
    m = re.search(r"## (\d{4}-\d{2}-\d{2})", sec)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError as e:
            logger.debug("invalid date in section header: %s", e)
            return None
    return None


def _extract_fact(sec: str) -> dict:
    lines = sec.strip().split("\n")
    fact = ""
    src = ""
    tp = ""
    sec_date = ""
    m = re.search(r"## (\d{4}-\d{2}-\d{2})", sec)
    if m:
        sec_date = m.group(1)
    for l in lines:
        if l.startswith("source:"):
            src = l.replace("source:", "").strip()
        elif l.startswith("type:"):
            tp = l.replace("type:", "").strip()
        elif not l.startswith("##") and not l.startswith("layer:") and not l.startswith("confidence:") and l.strip():
            if not fact:
                fact = l.strip()
    if fact:
        return {
            "time": sec_date,
            "type": tp,
            "source": src,
            "subject": "",
            "fact": fact,
        }
    return None


def _route(text: str) -> tuple:
    all_names = _load_entity_names() + _load_people_file_names()
    all_names.sort(key=len, reverse=True)
    for name in all_names:
        if name in text:
            return ("people", name)
    for kw in _team_keywords:
        if kw in text:
            return ("teams", kw)
    return ("system", "Cipher")


def _load_people_file_names() -> list:
    people_dir = OBS_DIR / "people"
    if not people_dir.is_dir():
        return []
    return [p.stem for p in people_dir.iterdir()
            if p.suffix == ".md" and p.stem not in _EXCLUDED_PEOPLE]


def _can_merge(existing: str, text: str, source: str, obs_type: str, today: str) -> bool:
    sections = existing.split("\n---\n")
    if not sections:
        return False
    last = sections[-1]
    return (f"## {today}" in last
            and f"source: {source}" in last
            and f"type: {obs_type}" in last)


def _apply_merge(existing: str, text: str, source: str, obs_type: str, today: str) -> str:
    sections = existing.split("\n---\n")
    last = sections[-1]
    merged = last
    new_count = _extract_count(text)
    old_count = _extract_count(last)
    if new_count and old_count:
        total = old_count + new_count
        merged = re.sub(r"连续\d+次", f"连续{total}次", last)
    else:
        merged = last.rstrip() + "\n" + text.strip()
    sections[-1] = merged
    return "\n---\n".join(sections)


def _extract_count(text: str) -> int:
    m = re.search(r"连续(\d+)次", text)
    if m:
        return int(m.group(1))
    m = re.search(r"完成(\d+)次", text)
    if m:
        return int(m.group(1))
    return 0
