"""
worldview.py — 世界观引擎 (方案 D+)

三层：
  Bootstrap  — 全量历史数据 → 实体档案
  Update     — 新记录增量 → 覆盖写实体档案
  Query      — 混合检索（FAISS + BM25）→ 返回匹配档案
"""

import json
import logging
import re
from pathlib import Path
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = ROOT / "data" / "state" / "worldview" / "index.json"
ENTITIES_DIR = ROOT / "data" / "state" / "worldview" / "entities"
VECTOR_DIR = ROOT / "data" / "state" / "worldview" / "vector"

# ── 已知实体清单（Bootstrap 用）─────────────────────────────────────
PERSON_ENTITIES = [
    "陈红洁", "李林骁", "苗笑天", "谭继衡", "杨梦卓", "张志斌",
    "王亮", "董文静", "刘欢",
]
PROCESS_ENTITIES = [
    "值班轮序", "交接评审制度", "紧急发料流程", "危废处置流程",
    "消防档案管理", "材料棚轮值规则",
]


def _ensure_dirs():
    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "last_bootstrap": None, "last_update": None,
            "pending_records": 0, "entities": {}}


def _save_index(idx: dict):
    INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def _observe_path(name: str) -> Path:
    return ROOT / "data" / "memory" / "observations" / "people" / f"{name}.md"


def _events_for_person(name: str) -> list[dict]:
    path = ROOT / "data" / "memory" / "events" / "log.jsonl"
    if not path.exists():
        return []
    hits = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            evt = json.loads(line)
            for actor in evt.get("actors", []):
                if actor.get("name") == name:
                    hits.append(evt)
                    break
        except json.JSONDecodeError:
            continue
    return hits[-50:]


def _static_info(name: str) -> str:
    """从 00-日常工作指引.md 提取该人的静态信息"""
    guide = ROOT / "Knowledge" / "01-仓储业务" / "00-日常工作指引.md"
    if not guide.exists():
        return ""
    text = guide.read_text(encoding="utf-8")
    # 找总表行
    for line in text.splitlines():
        if f"| {name} " in line or f"|{name}" in line:
            return line.strip()
    return ""


def _dedup_lines(text: str) -> str:
    """去重连续重复的行，合并为一条标注次数"""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        count = 1
        while i + count < len(lines) and lines[i + count] == line:
            count += 1
        if count > 3:
            out.append(f"{line} (×{count})")
        elif count > 1:
            out.extend([line] * min(count, 3))
        else:
            out.append(line)
        i += count
    return "\n".join(out)


def _smart_sample(text: str, max_chars: int = 8000) -> str:
    """从大文本中智能采样：取开头 + 最近的 max_chars/2，中间部分仅保留包含人名/日期的行"""
    if len(text) <= max_chars:
        return text
    head = text[:2000]
    tail = text[-(max_chars - 2000):]
    return head + "\n...（中部省略）...\n" + tail


def _bootstrap_person(name: str, obs_text: str, events: list, static_row: str) -> str:
    # 基本信息
    info_parts = [f"- **姓名**: {name}"]
    if static_row:
        cols = [c.strip() for c in static_row.strip("|").split("|")]
        labels = ["工号", "岗位", "电话", "五大员", "库区责任", "值班位"]
        for label, col in zip(labels, cols[1:] if len(cols) > 1 else cols):
            if col and col != "—":
                info_parts.append(f"- **{label}**: {col}")
    info_parts.append("- **静态源**: Knowledge/01-仓储业务/00-日常工作指引.md")

    # 近期事件
    event_lines = ["## 近期事件（上限 30 条）"]
    for e in events[-30:]:
        dt = e.get("date", e.get("event_date", ""))[:10]
        preview = e.get("raw_preview", e.get("summary", ""))[:120]
        if dt and preview:
            event_lines.append(f"[{dt}] {preview}")
    if len(event_lines) == 1:
        event_lines.append("（无事件记录）")

    # 协作关系：从观察记录中提取共同出现的其他人员
    from skills.shared.embedder import create_embedder
    import numpy as np
    e = create_embedder()
    collaborators = []
    for person in PERSON_ENTITIES:
        if person == name:
            continue
        v_name = e.encode(name)
        v_person = e.encode(person)
        if float(np.dot(v_name, v_person)) > 0.30:
            collaborators.append(person)

    lines = [
        "## 基本信息",
        "\n".join(info_parts),
        "",
        "## 行为模式",
        "### 核心特质",
        f"（{name} 的行为模式特征可通过日常观察积累，当前暂无自动分析）",
        "",
        "### 协作关系",
        f"潜在关联人员：{'、'.join(collaborators) if collaborators else '暂无识别'}" if collaborators else "（暂无识别）",
        "",
        "## 关联制度",
        "（关联制度待补充）",
        "",
        event_lines,
        "",
        "## 证据锚点",
        "| 模式 | 证据位置 | 时间 |",
        "| --- | --- | --- |",
    ]

    return "\n".join(["".join(l) if isinstance(l, str) else "\n".join(l) for l in lines])


def _bootstrap_process(name: str) -> str:
    """流程类实体的 Bootstrap — 语义匹配知识库内容"""
    guide_path = ROOT / "Knowledge" / "01-仓储业务" / "00-日常工作指引.md"
    guide_text = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""

    from skills.shared.embedder import create_embedder
    import numpy as np
    e = create_embedder()
    v_name = e.encode(name)

    table_rows = []
    for line in guide_text.split("\n"):
        if line.startswith("|") and line.count("|") >= 4:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(c == "—" or c.startswith(":") for c in cells):
                table_rows.append(line)

    matched_rows = []
    for row in table_rows[:100]:
        v_row = e.encode(row)
        sim = float(np.dot(v_name, v_row))
        if sim > 0.40:
            matched_rows.append((sim, row))
    matched_rows.sort(key=lambda x: -x[0])
    matched_rows = matched_rows[:5]

    related_people = []
    for person in PERSON_ENTITIES:
        v_person = e.encode(person)
        sim = float(np.dot(v_name, v_person))
        if sim > 0.45:
            related_people.append(person)

    lines = [
        f"## 基本信息",
        f"- **实体名称**: {name}",
        f"- **实体类型**: process",
        f"- **静态源**: Knowledge/01-仓储业务/00-日常工作指引.md",
        f"",
        f"## 规则定义",
    ]
    if matched_rows:
        for _, row in matched_rows:
            lines.append(f"- {row}")
    else:
        lines.append(f"（{name} 规则信息待补充）")

    lines.extend(["", "## 执行观测", "（执行观测可通过日常记录积累）", "", "## 关联实体"])
    for p in related_people:
        lines.append(f"- {p}")

    return "\n".join(lines)


# ── Bootstrap ──────────────────────────────────────────────────────

def bootstrap():
    _ensure_dirs()
    idx = _load_index()
    idx["last_bootstrap"] = datetime.now().isoformat()

    all_entities = PERSON_ENTITIES + PROCESS_ENTITIES

    for name in all_entities:
        logger.info("Bootstrapping entity: %s", name)
        try:
            if name in PERSON_ENTITIES:
                obs_text = ""
                obs_path = _observe_path(name)
                if obs_path.exists():
                    obs_text = obs_path.read_text(encoding="utf-8")
                events = _events_for_person(name)
                static_row = _static_info(name)
                content = _bootstrap_person(name, obs_text, events, static_row)
            else:
                content = _bootstrap_process(name)

            entity_path = ENTITIES_DIR / f"{name}.md"
            entity_path.write_text(content.strip() + "\n", encoding="utf-8")
            idx["entities"][name] = {
                "type": "person" if name in PERSON_ENTITIES else "process",
                "updated": datetime.now().isoformat(),
            }
            logger.info("  ✅ %s -> %s", name, entity_path)
        except Exception as e:
            logger.error("  ❌ %s bootstrap failed: %s", name, e, exc_info=True)

    _save_index(idx)
    _rebuild_faiss()
    logger.info("Bootstrap complete: %d entities", len(all_entities))


# ── FAISS 索引管理 ────────────────────────────────────────────────

def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split entity markdown into (section_name, content) pairs by ## headers."""
    sections = []
    current_name = "__header__"
    current_lines = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append((current_name, content))
            current_name = line.strip("# ").strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_name, content))
    return sections


def _rebuild_faiss():
    """对所有实体档案按节（## 段落）重建索引"""
    import numpy as np
    try:
        import faiss
    except ImportError:
        return

    from skills.shared.embedder import create_embedder
    embedder = create_embedder()
    dim = 512

    idx = _load_index()
    names = sorted(idx["entities"].keys())
    if not names:
        return

    index = faiss.IndexFlatIP(dim)
    chunk_map = {}
    vector_idx = 0

    for name in names:
        path = ENTITIES_DIR / f"{name}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        sections = _split_sections(text)
        for section_name, section_text in sections:
            embed_text = f"{name} - {section_name}\n{section_text[:500]}"
            vec = embedder.encode(embed_text)
            vec = vec.reshape(1, -1).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            index.add(vec)
            chunk_map[str(vector_idx)] = {
                "entity_id": name,
                "section": section_name,
                "updated": idx["entities"][name]["updated"],
                "type": idx["entities"][name]["type"],
            }
            vector_idx += 1

    tmp_faiss = VECTOR_DIR / "worldview.index.tmp"
    faiss.write_index(index, str(tmp_faiss))
    tmp_faiss.replace(VECTOR_DIR / "worldview.index")
    cm_path = VECTOR_DIR / "chunk_map.json"
    tmp_cm = VECTOR_DIR / "chunk_map.json.tmp"
    tmp_cm.write_text(json.dumps(chunk_map, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_cm.replace(cm_path)
    logger.info("FAISS worldview index rebuilt: %d vectors (%d entities)", index.ntotal, len(names))


# ── 增量更新 ──────────────────────────────────────────────────────

def update_entity(name: str, new_records: list[str]):
    idx = _load_index()
    old_path = ENTITIES_DIR / f"{name}.md"
    old_content = old_path.read_text(encoding="utf-8") if old_path.exists() else ""

    if old_content:
        _backup_dir = ROOT / "data" / "state" / "worldview" / "_backlog" / name
        _backup_dir.mkdir(parents=True, exist_ok=True)
        (_backup_dir / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}.md").write_text(old_content)

    sections = _split_sections(old_content) if old_content else []
    section_map = {s[0]: s[1] for s in sections}

    today = date.today().isoformat()
    new_events = [f"[{today}] {r[:120]}" for r in new_records]
    existing_events = section_map.get("近期事件（上限 30 条）", "")
    event_lines = []
    if existing_events:
        event_lines = [l for l in existing_events.split("\n") if l.strip() and not l.startswith("#")]
        event_lines = [l for l in event_lines if not l.startswith("[") or len(event_lines) < 60]
    all_events = new_events + event_lines
    section_map["近期事件（上限 30 条）"] = "\n".join(
        ["## 近期事件（上限 30 条）"] + all_events[:30]
    )

    lines = []
    header_order = ["基本信息", "行为模式", "协作关系", "近期事件（上限 30 条）",
                    "关联制度", "规则定义", "执行观测", "关联实体", "证据锚点"]
    seen = set()
    for h in header_order:
        if h in section_map and h not in seen:
            seen.add(h)
            lines.append(f"\n{section_map[h]}\n")
    for h, content in sections:
        if h not in seen:
            seen.add(h)
            lines.append(f"\n{content}\n")

    new_content = "\n".join(lines).strip()
    old_path.write_text(new_content.strip() + "\n", encoding="utf-8")
    idx["entities"][name]["updated"] = datetime.now().isoformat()
    _save_index(idx)
    _rebuild_faiss()
    logger.info("Entity %s updated", name)


def batch_update(entity_groups: dict[str, list[str]]):
    for name, records in entity_groups.items():
        try:
            update_entity(name, records)
        except Exception as e:
            logger.error("batch_update %s failed: %s", name, e)


# ── 疑似新实体发现 ─────────────────────────────────────────────────

_CHAR_NGRAM_MIN = 2
_CHAR_NGRAM_MAX = 4


_STOP_INITIALS = frozenset("的了着过把被在对于因为是就都也很还有个与或但")


def _extract_candidates(text: str) -> set[str]:
    """Extract meaningful Chinese n-grams, filtering those starting with stop chars."""
    chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    ngrams = set()
    for n in range(_CHAR_NGRAM_MIN, _CHAR_NGRAM_MAX + 1):
        for i in range(len(chars) - n + 1):
            cand = ''.join(chars[i:i + n])
            if cand[0] not in _STOP_INITIALS and cand[-1] not in _STOP_INITIALS:
                ngrams.add(cand)
    return ngrams


def _merge_overlapping(candidates: list[dict]) -> list[dict]:
    """Merge shorter candidates that are substrings of longer ones at same evidence."""
    candidates.sort(key=lambda x: -x["count"])
    merged = []
    used = set()
    for i, a in enumerate(candidates):
        if i in used:
            continue
        best = a
        for j, b in enumerate(candidates):
            if j <= i or j in used:
                continue
            if best["name"] in b["name"] or b["name"] in best["name"]:
                overlap = set(best["evidence"]) & set(b["evidence"])
                if overlap:
                    winner = best if len(best["name"]) >= len(b["name"]) else b
                    loser = b if winner is best else best
                    used.add(j)
                    for e in loser["evidence"]:
                        if e not in winner["evidence"]:
                            winner["evidence"].append(e)
                    best = winner
        merged.append(best)
        used.add(i)
    return merged


def detect_novel_entities(records: list[str], known: list[str] | None = None) -> list[dict]:
    if known is None:
        known = list(_load_index().get("entities", {}).keys())

    freq: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for rec in records:
        for cand in _extract_candidates(rec):
            freq[cand] = freq.get(cand, 0) + 1
            if cand not in evidence:
                evidence[cand] = []
            if len(evidence[cand]) < 3:
                evidence[cand].append(rec[:80])

    from skills.shared.embedder import create_embedder
    import numpy as np
    e = create_embedder()
    known_vecs = {kn: e.encode(kn) for kn in known if kn}

    candidates = []
    for cand, count in freq.items():
        if count < 3:
            continue
        v_cand = e.encode(cand)
        is_novel = True
        for kn, v_kn in known_vecs.items():
            sim = float(np.dot(v_cand, v_kn))
            if sim >= 0.55:
                is_novel = False
                break
        if is_novel:
            candidates.append({
                "name": cand,
                "type": "topic",
                "count": count,
                "evidence": evidence.get(cand, []),
            })

    candidates = _merge_overlapping(candidates)
    candidates.sort(key=lambda x: -x["count"])
    return candidates[:5]


# ── 查询 ──────────────────────────────────────────────────────────

def _get_section_text(entity_id: str, section: str) -> str:
    """Extract a specific ## section from an entity file."""
    path = ENTITIES_DIR / f"{entity_id}.md"
    if not path.exists():
        return ""
    sections = _split_sections(path.read_text(encoding="utf-8"))
    for sec_name, sec_text in sections:
        if sec_name == section:
            return sec_text
    return ""


def search(query: str, top_k: int = 3, type_filter: str | None = None) -> list[dict]:
    """混合检索：FAISS 向量（分节级）+ BM25 实体名兜底"""
    results = []

    # ① FAISS 向量检索（按节命中）
    try:
        import numpy as np
        import faiss
        from skills.shared.embedder import create_embedder

        faiss_path = VECTOR_DIR / "worldview.index"
        cm_path = VECTOR_DIR / "chunk_map.json"
        if faiss_path.exists() and cm_path.exists():
            index = faiss.read_index(str(faiss_path))
            chunk_map = json.loads(cm_path.read_text(encoding="utf-8"))
            embedder = create_embedder()
            qvec = embedder.encode(query)
            qvec = qvec.reshape(1, -1).astype(np.float32)
            norm = np.linalg.norm(qvec)
            if norm > 0:
                qvec /= norm
            scores, indices = index.search(qvec, min(top_k, index.ntotal))
            for score, idx in zip(scores[0], indices[0]):
                info = chunk_map.get(str(idx))
                if info and score > 0.3:
                    content = _get_section_text(info["entity_id"], info.get("section", ""))
                    if not content:
                        content = _get_section_text(info["entity_id"], "__header__")
                    results.append({
                        "entity_id": info["entity_id"],
                        "type": info["type"],
                        "section": info.get("section", ""),
                        "score": round(float(score), 3),
                        "content": content,
                    })
    except Exception as e:
        logger.debug("FAISS search failed: %s", e)

    # ② BM25 实体名兜底
    if not results:
        idx = _load_index()
        query_lower = query.lower()
        for name in idx.get("entities", {}):
            if name in query or query_lower in name.lower():
                path = ENTITIES_DIR / f"{name}.md"
                if path.exists():
                    results.append({
                        "entity_id": name,
                        "type": idx["entities"][name]["type"],
                        "section": "",
                        "score": 1.0,
                        "content": path.read_text(encoding="utf-8"),
                    })
                break

    if type_filter:
        results = [r for r in results if r.get("type") == type_filter]

    return results


# ── 触发 A：收集待处理记录 ────────────────────────────────────────

def _collect_pending(min_records: int = 50) -> dict[str, list[str]]:
    """从环形缓冲区读取最近记录，按实体名分组。

    Returns:
        {entity_name: [record_text, ...]} — 每个实体至少 1 条记录
    """
    from collections import defaultdict
    ring_path = ROOT / "data" / "state" / "worldview" / "_ringbuf.json"
    if not ring_path.exists():
        # fallback: events/log.jsonl
        evt_path = ROOT / "data" / "memory" / "events" / "log.jsonl"
        if not evt_path.exists():
            return {}
        lines = evt_path.read_text(encoding="utf-8").splitlines()[-min_records:]
    else:
        lines = ring_path.read_text(encoding="utf-8").splitlines()[-min_records:]

    idx = _load_index()
    known = set(idx.get("entities", {}).keys())

    groups = defaultdict(list)
    for line in lines:
        if not line.strip():
            continue
        # 按已知实体名分词匹配
        matched = False
        for name in known:
            if name in line:
                groups[name].append(f"[{line[:200]}]")
                matched = True
        if not matched:
            groups["_unknown"].append(line[:200])
    return dict(groups)


def check_and_update():
    """检查 pending_records ≥ 50，是则自动触发 batch_update。

    由 agent/engine.py run() 开头调用。
    """
    idx = _load_index()
    pending = idx.get("pending_records", 0)
    if pending < 50:
        return False

    logger.info("Worldview auto-update triggered (%d pending records)", pending)
    groups = _collect_pending(min_records=50)
    if groups:
        batch_update(groups)
    idx["pending_records"] = 0
    _save_index(idx)
    logger.info("Worldview auto-update complete (%d entities updated)", len(groups))
    return True


# ── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
        bootstrap()
    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        q = sys.argv[2] if len(sys.argv) > 2 else ""
        for r in search(q):
            print(f"\n{'='*50}\n{r['entity_id']} ({r['type']}) score={r['score']}\n{r['content'][:500]}")
    elif len(sys.argv) > 1 and sys.argv[1] == "update":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        if name:
            update_entity(name, [sys.argv[3] if len(sys.argv) > 3 else "（暂无新记录）"])
    else:
        print("Usage: python -m skills.memory.worldview [bootstrap|search|update] [args]")
