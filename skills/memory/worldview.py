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


# ── LLM 调用 ─────────────────────────────────────────────────────

def _llm(prompt: str, system: str = "") -> str:
    from skills.core.llm_client import call
    return call(prompt, system_prompt=system, temperature=0.3, max_tokens=4096)


BOOTSTRAP_SYSTEM = (
    "你是工班管理分析专家。根据提供的原始数据，按要求输出结构化档案。"
    "事实与推断严格分离。每条推断必须附具体证据。"
    "只输出 Markdown 正文，不要任何前缀解释（如'好的''根据原始数据'等）。"
    "近期事件如有大量重复内容，合并为一条并标注次数。"
)


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
    obs_text = _dedup_lines(obs_text)
    sampled = _smart_sample(obs_text, max_chars=8000)
    events_text = "\n".join(
        f"[{e.get('event_type','?')}] {e.get('raw_preview','')[:120]}"
        for e in events[-30:]
    )
    prompt = f"""实体：{name}

## 静态信息
{static_row or '（未在总表中找到）'}

## 观察记录
{sampled if obs_text else '（无）'}

## 相关事件摘要
{events_text or '（无）'}

请生成以下格式的 Markdown 档案。不要添加任何前缀/后缀/解释文字。必须覆盖以下内容：

## 基本信息
- **姓名**: {name}
（根据静态信息填工号/岗位/电话/五大员/库区责任/值班位）
- **静态源**: Knowledge/01-仓储业务/00-日常工作指引.md

## 行为模式
### 核心特质
分析此人行为中的**关键重复模式**，包括但不限于：
- 工作执行风格（主动还是被动？细致还是粗放？）
- 诚信与可靠性（有无编理由/推诿/诚信风险事件）
- 卫生/安全标准意识
- 主动改进还是被动执行
每条附一个具体证据引用。

### 协作关系
（常配合谁、常被指派什么类型任务、信息流向）

## 近期事件（上限 30 条）
按时间倒序，每条一行 [YYYY-MM-DD] 事件简述。完全相同的事件合并为一条并标注次数。

## 关联制度
（此人工作涉及 Knowledge 中哪些制度，列出文件名）

## 证据锚点
| 模式 | 证据位置 | 时间 |
"""
    return _llm(prompt, BOOTSTRAP_SYSTEM)


def _bootstrap_process(name: str) -> str:
    """流程类实体的 Bootstrap"""
    guide = ROOT / "Knowledge" / "01-仓储业务" / "00-日常工作指引.md"
    guide_text = guide.read_text(encoding="utf-8") if guide.exists() else ""
    prompt = f"""实体（流程规则）：{name}

## 知识库相关片段
{guide_text[:2000]}

生成以下格式的 Markdown 档案：

## 基本信息
- **实体类型**: process
- **关联制度**: （如涉及，写出 Knowledge 文件名）
- **静态源**: Knowledge/01-仓储业务/00-日常工作指引.md

## 规则定义
（清晰列出该流程的关键规则）

## 执行观测
（基于知识库信息提炼的执行要点）

## 关联实体
（涉及哪些人）
"""
    return _llm(prompt, BOOTSTRAP_SYSTEM)


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

def _rebuild_faiss():
    """对所有实体档案重新建索引"""
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

    for i, name in enumerate(names):
        path = ENTITIES_DIR / f"{name}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        vec = embedder.encode(text[:500])
        vec = vec.reshape(1, -1).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        index.add(vec)
        chunk_map[str(i)] = {
            "entity_id": name,
            "updated": idx["entities"][name]["updated"],
            "type": idx["entities"][name]["type"],
        }

    faiss_path = VECTOR_DIR / "worldview.index"
    faiss.write_index(index, str(faiss_path))
    cm_path = VECTOR_DIR / "chunk_map.json"
    cm_path.write_text(json.dumps(chunk_map, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("FAISS worldview index rebuilt: %d vectors", index.ntotal)


# ── 增量更新 ──────────────────────────────────────────────────────

def update_entity(name: str, new_records: list[str]):
    idx = _load_index()
    old_path = ENTITIES_DIR / f"{name}.md"
    old_content = old_path.read_text(encoding="utf-8") if old_path.exists() else ""

    records_text = "\n".join(new_records)
    prompt = f"""实体：{name}

## 现有档案
{old_content[:2000] if old_content else '（新实体，无旧档案）'}

## 新增记录
{records_text}

请输出更新后的完整 Markdown 档案。注意：
1. 行为模式节：整合新旧信息，修正过时内容
2. 近期事件节：追加新记录，保留最近 30 条，淘汰最旧的
3. 证据锚点节：保留仍有效的，追加新证据
4. 不要删除仍有价值的旧信息，用 update 语义替代 rewrite
"""
    new_content = _llm(prompt, BOOTSTRAP_SYSTEM)
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

def detect_novel_entities(records: list[str], known: list[str] | None = None) -> list[dict]:
    if known is None:
        known = list(_load_index().get("entities", {}).keys())
    prompt = f"""以下是 50 条行为记录。已知实体列表：{known}
请找出重复出现的**新主题/新实体**不在列表中。
要求：出现 ≥ 3 次，有明确主题一致性。
输出 JSON 数组：[{{"name": "...", "type": "topic", "count": 3, "evidence": ["..."]}}]
"""
    text = "\n".join(records)
    raw = _llm(f"{prompt}\n\n{text[:3000]}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


# ── 查询 ──────────────────────────────────────────────────────────

def search(query: str, top_k: int = 3) -> list[dict]:
    """混合检索：FAISS 向量 + BM25 实体名兜底"""
    results = []

    # ① FAISS 向量检索
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
                    path = ENTITIES_DIR / f"{info['entity_id']}.md"
                    results.append({
                        "entity_id": info["entity_id"],
                        "type": info["type"],
                        "score": round(float(score), 3),
                        "content": path.read_text(encoding="utf-8") if path.exists() else "",
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
                        "score": 1.0,
                        "content": path.read_text(encoding="utf-8"),
                    })
                break

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
