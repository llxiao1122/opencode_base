from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
KNOWLEDGE_DIR = ROOT_DIR / "Knowledge"
INDEX_PATH = KNOWLEDGE_DIR / "INDEX.md"


def _search_worldview(query: str, top_k: int = 3) -> str:
    """优先走世界观 FAISS 语义检索（process + topic 实体档案），命中高分即用。"""
    try:
        from skills.memory.worldview import search as wv_search
        hits = wv_search(query, top_k=top_k)
        hits = [h for h in hits if h.get("type") != "person" and h.get("score", 0) >= 0.6]
        if not hits:
            return ""
        blocks = []
        for h in hits:
            snippet = (h.get("content") or "")[:600].strip()
            if snippet:
                blocks.append(f"【{h['entity_id']}】（世界观档案）\n{snippet}")
        return "\n\n".join(blocks[:top_k])
    except Exception:
        return ""


def _search_knowledge(query: str, top_k: int = 3) -> str:
    """词法打分检索 Knowledge 制度原文，附 INDEX.md 标准号/版本元数据。

    分数 = 命中行词频和（标题/条款行加权）。按文件聚合取 top_k。
    """
    if not KNOWLEDGE_DIR.exists():
        return ""
    tokens = _tokenize(query)
    if not tokens:
        return ""

    index_map = _load_index_map()
    results = []

    for md_path in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        if md_path.name == "INDEX.md":
            continue
        rel = md_path.relative_to(KNOWLEDGE_DIR)
        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        file_score = 0
        hits = []
        for i, line in enumerate(lines):
            s = _score_line(line, tokens)
            if s > 0:
                file_score += s
                if len(hits) < 3:
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    hits.append(f"行{i+1}:\n" + "\n".join(lines[start:end]))
        if file_score == 0:
            continue

        meta = index_map.get(md_path.name, {})
        meta_line = ""
        if meta.get("标准号") and meta.get("版本"):
            meta_line = f"（{meta['标准号']} · {meta['版本']}）"
        elif meta.get("内容说明"):
            meta_line = f"（{meta['内容说明'][:30]}）"
        # 文件级命中优先：文件名 + INDEX 内容说明 含查询词的个数（主导排序）
        file_tokens = (meta.get("内容说明", "") + " " + md_path.stem).lower()
        file_hits = sum(1 for t in tokens if t in file_tokens)
        results.append((file_hits, file_score, f"【{rel}】{meta_line}\n" + "\n...\n".join(hits)))

    if not results:
        return ""
    results.sort(key=lambda x: (-x[0], -x[1]))
    return "\n\n".join(r[2] for r in results[:top_k])


_STOP_WORDS = frozenset("的了着过把被在对于因为是就都也很还有个与或但以及吗呢怎么什么如何哪个哪些是否为什么".strip())


def _tokenize(query: str) -> list[str]:
    """提取查询关键词：中文按字符二元组 + 非中文字段整体切词。"""
    import re
    tokens = []
    for seg in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", query.lower()):
        if seg.isascii():
            if len(seg) >= 2:
                tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                bigram = seg[i:i + 2]
                if bigram[0] not in _STOP_WORDS and bigram[-1] not in _STOP_WORDS:
                    tokens.append(bigram)
            if len(seg) == 1 and seg not in _STOP_WORDS:
                tokens.append(seg)
    return tokens


def _load_index_map() -> dict:
    """从 Knowledge/INDEX.md 构建 文件名 → 元数据 映射。"""
    meta = {}
    if not INDEX_PATH.exists():
        return meta
    for line in INDEX_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 5 and cells[1] != "文件" and cells[0] != "编号":
            fname = cells[1]
            meta[fname] = {
                "编号": cells[0],
                "标准号": cells[2],
                "版本": cells[3],
                "内容说明": cells[4],
            }
    return meta


def _score_line(line: str, tokens: list[str]) -> int:
    """单行词法打分：命中词数 + 标题/关键词行加权。"""
    low = line.lower()
    hits = sum(1 for t in tokens if t in low)
    if hits == 0:
        return 0
    score = hits
    stripped = line.strip()
    if stripped.startswith("#"):
        score += 3
    if any(kw in stripped for kw in ("须", "应", "禁止", "不得", "负责", "标准", "流程")):
        score += 1
    return score


def handle(user_input, ctx):
    user_name = (ctx.user or {}).get("name", "未知")

    knowledge_text = _search_worldview(user_input, top_k=3)
    if not knowledge_text:
        knowledge_text = _search_knowledge(user_input, top_k=3)
    if not knowledge_text:
        origin = getattr(ctx, "original_route", "") or ""
        orig_conf = getattr(ctx, "original_confidence", 0.0) or 0.0
        if origin in ("event", "unknown") and orig_conf < 0.5:
            return "[Cipher] 已记录。"
        return "[Cipher] 制度库中暂无匹配条目。"

    sys_prompt = (
        f"你是 Cipher，{user_name}的企业认知系统助手。"
        "基于提供的制度文档，回答合规性问题。引用具体条目。"
    )
    prompt = (
        f"当前用户 {user_name} 提问: {user_input}\n"
        f"\n相关制度内容:\n{knowledge_text}\n"
        f"\n请根据制度内容回答。如果制度未覆盖，如实说明。"
    )
    from skills.shared.llm_cache import call as _cached_llm
    answer = _cached_llm(prompt, sys_prompt, user=user_name, ttl=60, max_tokens=400, temperature=0.2)
    if not answer:
        answer = "未能检索到匹配的制度内容。"
    return f"[Cipher:knowledge]\n{answer}"
